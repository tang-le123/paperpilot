"""Score human annotations: correctness, citation precision, false suppression, kappa.

Expected CSV columns:
    case_id, annotator, answer_correct, citation_support, suppressed, should_answer
Values:
    answer_correct / should_answer / suppressed: 0 or 1
    citation_support: yes | partial | no
"""
from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def kappa(pairs: list[tuple[str, str]]) -> float:
    if not pairs:
        return 0.0
    labels = sorted({label for pair in pairs for label in pair})
    total = len(pairs)
    observed = sum(a == b for a, b in pairs) / total
    expected = 0.0
    for label in labels:
        pa = sum(a == label for a, _ in pairs) / total
        pb = sum(b == label for _, b in pairs) / total
        expected += pa * pb
    if expected == 1:
        return 1.0
    return round((observed - expected) / (1 - expected), 3)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default=str(ROOT / "annotations.csv"))
    parser.add_argument("--out", default=str(ROOT / "annotation_report.json"))
    args = parser.parse_args()

    path = Path(args.input)
    if not path.exists():
        print(f"missing {path}; use eval/annotation_guidelines.md to create it")
        return

    rows = list(csv.DictReader(path.open(encoding="utf-8-sig")))
    by_case: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        by_case[row["case_id"]].append(row)

    correctness = [float(row["answer_correct"]) for row in rows if row.get("answer_correct") in {"0", "1"}]
    citation_scores = [
        {"yes": 1.0, "partial": 0.5, "no": 0.0}.get(row.get("citation_support", ""), 0.0)
        for row in rows
        if row.get("citation_support") in {"yes", "partial", "no"}
    ]
    suppressed_cases = {
        row["case_id"] for row in rows if row.get("suppressed") == "1"
    }
    suppressed_answerable = {
        row["case_id"]
        for row in rows
        if row.get("suppressed") == "1" and row.get("should_answer") == "1"
    }
    false_suppression_cases = {
        row["case_id"]
        for row in rows
        if row.get("suppressed") == "1"
        and row.get("should_answer") == "1"
        and row.get("answer_correct") == "1"
    }
    false_suppression = len(false_suppression_cases)

    pair_map: dict[str, dict[str, str]] = defaultdict(dict)
    for row in rows:
        pair_map[row["case_id"]][row["annotator"]] = row.get("citation_support", "")
    annotators = sorted({row["annotator"] for row in rows})
    pairs = []
    if len(annotators) >= 2:
        for labels in pair_map.values():
            if annotators[0] in labels and annotators[1] in labels:
                pairs.append((labels[annotators[0]], labels[annotators[1]]))

    summary = {
        "rows": len(rows),
        "cases": len(by_case),
        "answer_accuracy": round(sum(correctness) / len(correctness), 3) if correctness else None,
        "citation_precision": round(sum(citation_scores) / len(citation_scores), 3) if citation_scores else None,
        "false_suppression": false_suppression,
        "false_suppression_rate": (
            round(false_suppression / len(by_case), 3) if by_case else None
        ),
        "suppressed": len(suppressed_cases),
        "suppressed_answerable": len(suppressed_answerable),
        "suppressed_answerable_rate": (
            round(len(suppressed_answerable) / len(by_case), 3) if by_case else None
        ),
        "annotators": annotators,
        "cohen_kappa": kappa(pairs),
        "kappa_pairs": len(pairs),
    }
    Path(args.out).write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
