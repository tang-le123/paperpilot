"""Embeddings, Chroma index, BM25 and reciprocal-rank fusion."""
from __future__ import annotations

import re
import threading
from typing import Any

import chromadb
import jieba
import torch
from rank_bm25 import BM25Okapi
from sentence_transformers import SentenceTransformer

from app.config import (
    CHROMA_DIR,
    EMBEDDING_DEVICE,
    EMBEDDING_MODEL,
    RERANK_DEVICE,
    RERANK_ENABLED,
    RERANK_MAX_WINDOWS,
    RERANK_MODEL,
    RERANK_SECTION_PREFIX,
    RERANK_WINDOW_CHARS,
    RERANK_WINDOW_ENABLED,
    RERANK_WINDOW_OVERLAP,
    RRF_DENSE_WEIGHT,
    RRF_LEXICAL_WEIGHT,
)
from app.db import get_chunks

jieba.setLogLevel(20)


def tokenize(text: str) -> list[str]:
    lowered = text.lower()
    english = re.findall(r"[a-z0-9][a-z0-9_\-]*", lowered)
    chinese = [token for token in jieba.lcut(lowered) if token.strip()]
    return chinese + english


class EmbeddingService:
    def __init__(self) -> None:
        device = EMBEDDING_DEVICE or ("cuda" if torch.cuda.is_available() else "cpu")
        self.device = device
        self.model = SentenceTransformer(str(EMBEDDING_MODEL), device=device)

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        vectors = self.model.encode(
            texts,
            batch_size=16,
            normalize_embeddings=True,
            show_progress_bar=False,
            convert_to_numpy=True,
        )
        return vectors.tolist()

    def embed_query(self, text: str) -> list[float]:
        return self.embed_documents([text])[0]


class PaperIndex:
    def __init__(self) -> None:
        self.client = chromadb.PersistentClient(path=str(CHROMA_DIR))
        self.collection = self.client.get_or_create_collection(
            name="paper_chunks",
            metadata={"hnsw:space": "cosine"},
        )

    def add(self, chunks: list[dict], embeddings: list[list[float]]) -> None:
        if not chunks:
            return
        self.collection.upsert(
            ids=[chunk["id"] for chunk in chunks],
            documents=[chunk["content"] for chunk in chunks],
            metadatas=[
                {
                    "paper_id": chunk["paper_id"],
                    "page": chunk["page"],
                    "section": chunk["section"],
                    "chunk_index": chunk["chunk_index"],
                    "is_reference": bool(chunk["is_reference"]),
                    "title": chunk.get("title", ""),
                }
                for chunk in chunks
            ],
            embeddings=embeddings,
        )

    def delete_paper(self, paper_id: int) -> None:
        self.collection.delete(where={"paper_id": paper_id})

    def query(
        self,
        paper_ids: list[int],
        vector: list[float],
        *,
        per_paper: int = 3,
        sections: list[str] | None = None,
    ) -> list[dict]:
        results: list[dict] = []
        for paper_id in paper_ids:
            fetch_n = max(per_paper * 3, 9) if sections else per_paper
            response = self.collection.query(
                query_embeddings=[vector],
                n_results=fetch_n,
                where={"paper_id": paper_id},
                include=["documents", "metadatas", "distances"],
            )
            ids = response.get("ids", [[]])[0]
            documents = response.get("documents", [[]])[0]
            metadatas = response.get("metadatas", [[]])[0]
            distances = response.get("distances", [[]])[0]
            paper_results = []
            for chunk_id, document, metadata, distance in zip(
                ids, documents, metadatas, distances, strict=False
            ):
                paper_results.append(
                    {
                        "chunk_id": chunk_id,
                        "content": document or "",
                        "score": 1.0 - float(distance),
                        "source": "vector",
                        **metadata,
                    }
                )
            if sections:
                matched = [
                    item for item in paper_results
                    if any(section.lower() in (item.get("section") or "").lower() for section in sections)
                ]
                if matched:
                    paper_results = matched
            results.extend(paper_results[:per_paper])
        return results


def _bm25_query(
    paper_ids: list[int],
    query: str,
    *,
    per_paper: int = 3,
    sections: list[str] | None = None,
) -> list[dict]:
    chunks = get_chunks(paper_ids)
    if not chunks:
        return []
    by_paper: dict[int, list[dict]] = {}
    for chunk in chunks:
        by_paper.setdefault(chunk["paper_id"], []).append(chunk)

    results: list[dict] = []
    query_tokens = tokenize(query)
    for paper_id, paper_chunks in by_paper.items():
        filtered = paper_chunks
        if sections:
            matched = [
                chunk for chunk in paper_chunks
                if any(section.lower() in (chunk.get("section") or "").lower() for section in sections)
            ]
            if matched:
                filtered = matched
        corpus = [tokenize(chunk["content"]) for chunk in filtered]
        bm25 = BM25Okapi(corpus)
        scores = bm25.get_scores(query_tokens)
        ranked = sorted(range(len(scores)), key=lambda index: scores[index], reverse=True)[:per_paper]
        for rank, index in enumerate(ranked, start=1):
            if scores[index] <= 0:
                continue
            chunk = filtered[index]
            results.append(
                {
                    "chunk_id": chunk["id"],
                    "paper_id": chunk["paper_id"],
                    "title": chunk.get("title", ""),
                    "page": chunk["page"],
                    "section": chunk["section"],
                    "content": chunk["content"],
                    "score": float(scores[index]),
                    "rank": rank,
                    "source": "bm25",
                }
            )
    return results


def _rrf(
    lists: list[list[dict]],
    *,
    k: int = 60,
    weights: list[float] | None = None,
) -> list[dict]:
    if weights is None:
        weights = [1.0] * len(lists)
    if len(weights) != len(lists):
        raise ValueError("RRF weights must match input lists")
    scores: dict[str, float] = {}
    canonical: dict[str, dict] = {}
    for weight, ranked in zip(weights, lists, strict=False):
        for rank, chunk in enumerate(ranked, start=1):
            chunk_id = chunk["chunk_id"]
            scores[chunk_id] = scores.get(chunk_id, 0.0) + weight / (k + rank)
            if chunk_id not in canonical:
                canonical[chunk_id] = dict(chunk)
    fused = []
    for chunk_id, score in sorted(scores.items(), key=lambda item: item[1], reverse=True):
        item = canonical[chunk_id]
        item["score"] = score
        item["source"] = "rrf"
        fused.append(item)
    return fused


class Reranker:
    """Local Cross-Encoder reranker, loaded lazily and falling back to RRF order."""

    def __init__(self) -> None:
        self._model = None
        self._error: str | None = None
        self._init_lock = threading.Lock()

    def _ensure_model(self):
        if not RERANK_ENABLED:
            return None
        if self._model is not None or self._error is not None:
            return self._model
        with self._init_lock:
            if self._model is not None or self._error is not None:
                return self._model
            try:
                from sentence_transformers import CrossEncoder

                self._model = CrossEncoder(RERANK_MODEL, device=RERANK_DEVICE)
            except Exception as exc:
                self._error = str(exc)
                self._model = None
            return self._model

    def rerank(self, query: str, chunks: list[dict], *, top_k: int) -> list[dict]:
        model = self._ensure_model()
        if model is None or len(chunks) <= 1:
            return chunks[:top_k]
        try:
            pairs = []
            owners = []
            for index, chunk in enumerate(chunks):
                section = (chunk.get("section") or "").strip()
                content = chunk.get("content") or ""
                prefix = f"{section}\n" if section and RERANK_SECTION_PREFIX else ""
                # Long chunks can exceed the cross-encoder's 512-token limit.
                # Score overlapping windows and keep the best window per chunk.
                windows = []
                if not RERANK_WINDOW_ENABLED or len(content) <= RERANK_WINDOW_CHARS:
                    windows = [content]
                else:
                    step = max(1, RERANK_WINDOW_CHARS - RERANK_WINDOW_OVERLAP)
                    for start in range(0, len(content), step):
                        windows.append(content[start : start + RERANK_WINDOW_CHARS])
                        if len(windows) >= RERANK_MAX_WINDOWS:
                            break
                for window in windows:
                    pairs.append((query, prefix + window))
                    owners.append(index)
            scores = model.predict(pairs, batch_size=8, show_progress_bar=False)
            best: dict[int, float] = {}
            for owner, score in zip(owners, scores, strict=False):
                best[owner] = max(best.get(owner, float("-inf")), float(score))
            ordered = sorted(
                ((chunk, best.get(index, float("-inf"))) for index, chunk in enumerate(chunks)),
                key=lambda item: item[1],
                reverse=True,
            )
            results = []
            for chunk, score in ordered[:top_k]:
                item = dict(chunk)
                item["score"] = float(score)
                item["source"] = "rerank"
                results.append(item)
            return results
        except Exception:
            return chunks[:top_k]


class HybridRetriever:
    def __init__(
        self,
        embedder: EmbeddingService,
        index: PaperIndex,
        reranker: Reranker | None = None,
    ) -> None:
        self.embedder = embedder
        self.index = index
        self.reranker = reranker or Reranker()

    def retrieve(
        self,
        paper_ids: list[int],
        query: str,
        *,
        top_k: int = 5,
        retrieval_query: str | None = None,
        sections: list[str] | None = None,
    ) -> list[dict]:
        paper_ids = sorted(set(paper_ids))
        if not paper_ids or not query.strip():
            return []
        search_query = retrieval_query or query
        vector = self.embedder.embed_query(search_query)
        candidates = max(top_k * 3, 12)
        dense = self.index.query(paper_ids, vector, per_paper=candidates, sections=sections)
        lexical = _bm25_query(
            paper_ids, search_query, per_paper=candidates, sections=sections
        )
        fused = _rrf(
            [dense, lexical],
            weights=[RRF_DENSE_WEIGHT, RRF_LEXICAL_WEIGHT],
        )
        return self.reranker.rerank(query, fused, top_k=top_k)

    def retrieve_balanced(
        self,
        paper_ids: list[int],
        query: str,
        *,
        per_paper: int = 2,
        retrieval_query: str | None = None,
        sections: list[str] | None = None,
    ) -> list[dict]:
        """Keep at least `per_paper` candidates per paper, then rerank jointly."""
        paper_ids = sorted(set(paper_ids))
        if not paper_ids or not query.strip():
            return []
        search_query = retrieval_query or query
        vector = self.embedder.embed_query(search_query)
        dense = self.index.query(
            paper_ids, vector, per_paper=max(per_paper * 3, 6), sections=sections
        )
        lexical = _bm25_query(
            paper_ids,
            search_query,
            per_paper=max(per_paper * 3, 6),
            sections=sections,
        )
        fused = _rrf(
            [dense, lexical],
            weights=[RRF_DENSE_WEIGHT, RRF_LEXICAL_WEIGHT],
        )

        grouped: dict[int, list[dict]] = {paper_id: [] for paper_id in paper_ids}
        for chunk in fused:
            bucket = grouped.setdefault(chunk["paper_id"], [])
            if len(bucket) < per_paper:
                bucket.append(chunk)
        balanced = [chunk for paper_id in paper_ids for chunk in grouped.get(paper_id, [])]
        if not balanced:
            return []
        return self.reranker.rerank(query, balanced, top_k=len(balanced))


