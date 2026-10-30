"""Export a human-review CSV for citation support calibration."""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REPORT = ROOT / "report.json"
OUT = ROOT / "citation_review.csv"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", default=str(REPORT))
    parser.add_argument("--out", default=str(OUT))
    parser.add_argument("--limit", type=int, default=30)
    args = parser.parse_args()

    report = json.loads(Path(args.report).read_text(encoding="utf-8"))
    rows = []
    for result in report.get("results", []):
        answer = result.get("answer_preview", "")
        for index, citation in enumerate(result.get("citations", []), 1):
            rows.append(
                {
                    "case_id": result.get("id", ""),
                    "question": result.get("question", ""),
                    "strategy": result.get("strategy", ""),
                    "answer_preview": answer[:300],
                    "citation_index": index,
                    "paper": citation.get("title", ""),
                    "page": citation.get("page", ""),
                    "section": citation.get("section", ""),
                    "snippet": citation.get("snippet", ""),
                    "llm_support": citation.get("support", ""),
                    "llm_reason": citation.get("support_reason", ""),
                    "human_support": "",
                    "human_notes": "",
                }
            )
            if len(rows) >= args.limit:
                break
        if len(rows) >= args.limit:
            break

    out = Path(args.out)
    with out.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()) if rows else [])
        writer.writeheader()
        writer.writerows(rows)
    print(f"wrote {len(rows)} citation rows to {out}")


if __name__ == "__main__":
    main()
