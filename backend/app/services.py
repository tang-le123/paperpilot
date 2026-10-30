"""Paper ingestion pipeline."""
from __future__ import annotations

import asyncio
from pathlib import Path

from app.db import get_paper, insert_chunks, update_paper
from app.indexing import EmbeddingService, PaperIndex
from app.parsing import parse_file


async def process_paper(
    *,
    paper_id: int,
    path: Path,
    file_type: str,
    embedder: EmbeddingService,
    index: PaperIndex,
) -> None:
    """Parse, chunk, embed and index one paper. Runs after the upload response."""
    try:
        update_paper(paper_id, status="parsing", error=None)
        parsed = await asyncio.to_thread(parse_file, paper_id, path, file_type)
        paper = get_paper(paper_id)
        fallback_title = Path(paper["filename"]).stem if paper else path.stem
        if not parsed.title.strip() or parsed.title == path.stem:
            parsed.title = fallback_title
        for chunk in parsed.chunks:
            chunk["title"] = parsed.title
        await asyncio.to_thread(insert_chunks, parsed.chunks)

        update_paper(
            paper_id,
            status="indexing",
            title=parsed.title,
            page_count=parsed.page_count,
            chunk_count=len(parsed.chunks),
        )
        embeddings = await asyncio.to_thread(
            embedder.embed_documents,
            [chunk["content"] for chunk in parsed.chunks],
        )
        await asyncio.to_thread(index.delete_paper, paper_id)
        await asyncio.to_thread(index.add, parsed.chunks, embeddings)
        update_paper(paper_id, status="ready", error=None)
    except Exception as exc:  # keep the failure visible in the paper list
        update_paper(paper_id, status="failed", error=str(exc)[:800])
