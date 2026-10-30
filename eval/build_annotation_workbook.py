"""Build a human annotation workbook from the latest eval report.

The report may contain only a subset of cases; missing cases are still included
with a blank answer so the annotator can run them in the UI.
"""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATASET = ROOT / "dataset.json"
REPORT = ROOT / "report.json"
OUT = ROOT / "annotations_workbook.csv"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", default=str(DATASET))
    parser.add_argument("--report", default=str(REPORT))
    parser.add_argument("--out", default=str(OUT))
    args = parser.parse_args()

    cases = json.loads(Path(args.dataset).read_text(encoding="utf-8"))
    report = json.loads(Path(args.report).read_text(encoding="utf-8")) if Path(args.report).exists() else {}
    by_id = {result.get("id"): result for result in report.get("results", [])}

    rows = []
    for case in cases:
        result = by_id.get(case["id"], {})
        citations = result.get("citations", [])
        citation_text = " | ".join(
            f"[{index}] p{citation.get('page')} {citation.get('support')}"
            for index, citation in enumerate(citations, 1)
        )
        for annotator in ("A", "B"):
            rows.append(
                {
                    "case_id": case["id"],
                    "question": case["question"],
                    "paper_keys": "|".join(case["paper_keys"]),
                    "answer_preview": result.get("answer_preview", ""),
                    "citations": citation_text,
                    "suppressed": int(bool(result.get("answer_suppressed"))),
                    "annotator": annotator,
                    "answer_correct": "",
                    "citation_support": "",
                    "should_answer": "",
                    "notes": "",
                }
            )

    out = Path(args.out)
    with out.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    print(f"wrote {len(rows)} annotation rows to {out}")


if __name__ == "__main__":
    main()
