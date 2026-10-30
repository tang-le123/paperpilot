"""Rebuild chunks and Chroma for all ready papers using current CHUNK_SIZE.

Run with CHUNK_SIZE / CHUNK_OVERLAP environment variables, e.g.:

    $env:CHUNK_SIZE='1200'; $env:CHUNK_OVERLAP='150'
    python eval/reindex_chunks.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.config import CHUNK_OVERLAP, CHUNK_SIZE  # noqa: E402
from app.db import delete_chunks, insert_chunks, list_papers, update_paper  # noqa: E402
from app.indexing import EmbeddingService, PaperIndex  # noqa: E402
from app.parsing import parse_file  # noqa: E402


def main() -> None:
    papers = [p for p in list_papers() if p.get("status") == "ready" and p.get("stored_path")]
    embedder = EmbeddingService()
    index = PaperIndex()
    print(f"chunk_size={CHUNK_SIZE} overlap={CHUNK_OVERLAP} papers={len(papers)}")
    for number, paper in enumerate(papers, 1):
        path = Path(paper["stored_path"])
        if not path.exists():
            print(f"skip missing {paper['id']} {path}")
            continue
        parsed = parse_file(paper["id"], path, paper["file_type"])
        for chunk in parsed.chunks:
            chunk["title"] = parsed.title
        delete_chunks(paper["id"])
        insert_chunks(parsed.chunks)
        index.delete_paper(paper["id"])
        embeddings = embedder.embed_documents([chunk["content"] for chunk in parsed.chunks])
        index.add(parsed.chunks, embeddings)
        update_paper(
            paper["id"],
            title=parsed.title,
            page_count=parsed.page_count,
            chunk_count=len(parsed.chunks),
        )
        print(f"[{number}/{len(papers)}] paper={paper['id']} chunks={len(parsed.chunks)}")


if __name__ == "__main__":
    main()
