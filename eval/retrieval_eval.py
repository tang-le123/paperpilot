"""Recall@k evaluation for the retriever.

Gold data must be human-labeled. Put a JSON file at eval/retrieval_gold.json:

[
  {
    "id": "r01",
    "paper_keys": ["2026统计建模"],
    "question": "LASSO 的 R² 是多少？",
    "gold_pages": [20, 21],
    "gold_chunk_ids": ["p4_c0034"]
  }
]

Run from the project root:
    E:\\paperpilot\\.venv\\Scripts\\python.exe eval\\retrieval_eval.py
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.db import list_papers  # noqa: E402
from app.indexing import EmbeddingService, HybridRetriever, PaperIndex, Reranker  # noqa: E402
from app.query import classify, rewrite, sections  # noqa: E402

GOLD = ROOT / "eval" / "retrieval_gold.json"
REPORT = ROOT / "eval" / "retrieval_report.json"


def resolve_ids(papers: list[dict], keys: list[str]) -> list[int]:
    ids = []
    for key in keys:
        for paper in papers:
            if key.lower() in paper["title"].lower() or key.lower() in paper["filename"].lower():
                ids.append(paper["id"])
                break
    return ids


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--gold", default=str(GOLD))
    parser.add_argument("--out", default=str(REPORT))
    parser.add_argument("--no-rewrite", action="store_true")
    parser.add_argument("--rewrite-only", action="store_true")
    parser.add_argument("--section-only", action="store_true")
    args = parser.parse_args()

    use_rewrite = not args.no_rewrite and not args.section_only
    use_sections = not args.no_rewrite and not args.rewrite_only
    mode = (
        "baseline"
        if args.no_rewrite
        else "rewrite-only"
        if args.rewrite_only
        else "section-only"
        if args.section_only
        else "rewrite+section"
    )

    gold_path = Path(args.gold)
    if not gold_path.exists():
        print(f"missing {gold_path}; use eval/retrieval_gold_template.csv to create gold labels")
        return

    cases = json.loads(gold_path.read_text(encoding="utf-8"))
    papers = list_papers()
    retriever = HybridRetriever(EmbeddingService(), PaperIndex(), Reranker())
    results = []

    for case in cases:
        paper_ids = resolve_ids(papers, case["paper_keys"])
        intent = case.get("intent") or classify(case["question"])
        retrieval_query = rewrite(case["question"], intent) if use_rewrite else case["question"]
        section_filter = sections(intent) if use_sections else None
        chunks = retriever.retrieve(
            paper_ids,
            case["question"],
            top_k=10,
            retrieval_query=retrieval_query,
            sections=section_filter,
        )
        gold_ids = set(case.get("gold_chunk_ids", []))
        gold_pages = set(case.get("gold_pages", []))
        hits = [
            1
            if (chunk["chunk_id"] in gold_ids or chunk["page"] in gold_pages)
            else 0
            for chunk in chunks
        ]
        first_hit = next((index + 1 for index, hit in enumerate(hits) if hit), None)
        results.append(
            {
                "id": case["id"],
                "question": case["question"],
                "intent": intent,
                "retrieved": [
                    {"chunk_id": c["chunk_id"], "page": c["page"], "section": c.get("section")}
                    for c in chunks
                ],
                "hit@1": int(bool(hits[:1]) and bool(hits[0])),
                "hit@5": int(any(hits[:5])),
                "hit@10": int(any(hits[:10])),
                "mrr": round(1 / first_hit, 4) if first_hit else 0.0,
            }
        )

    total = len(results)
    summary = {
        "mode": mode,
        "total": total,
        "recall@1": round(sum(r["hit@1"] for r in results) / total, 3) if total else 0,
        "recall@5": round(sum(r["hit@5"] for r in results) / total, 3) if total else 0,
        "recall@10": round(sum(r["hit@10"] for r in results) / total, 3) if total else 0,
        "mrr": round(sum(r["mrr"] for r in results) / total, 3) if total else 0,
    }
    out = Path(args.out)
    out.write_text(json.dumps({"summary": summary, "results": results}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"report: {out}")


if __name__ == "__main__":
    main()
