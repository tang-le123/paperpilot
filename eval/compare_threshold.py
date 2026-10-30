"""Compare a verifier run against the 30-item human citation review."""
from __future__ import annotations

import csv
import json
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REPORT = ROOT / "report.json"
REVIEW = ROOT / "citation_review_filled.csv"
OUT = ROOT / "threshold_compare.json"


def score(label: str) -> float:
    return {"yes": 1.0, "partial": 0.5, "no": 0.0}.get(label, 0.0)


def main() -> None:
    report = json.loads(REPORT.read_text(encoding="utf-8"))
    human = list(csv.DictReader(REVIEW.open(encoding="utf-8-sig")))
    human_by_case: dict[str, list[dict]] = defaultdict(list)
    for row in human:
        human_by_case[row["case_id"]].append(row)

    results = report.get("results", [])
    matches = []
    for result in results:
        case_id = result.get("id", "")
        labels = human_by_case.get(case_id, [])
        for index, citation in enumerate(result.get("citations", []), 1):
            if index > len(labels):
                continue
            human_label = labels[index - 1]["human_support"]
            llm_label = citation.get("support", "unknown")
            matches.append(
                {
                    "case_id": case_id,
                    "citation_index": index,
                    "llm": llm_label,
                    "human": human_label,
                    "match": llm_label == human_label,
                    "llm_score": score(llm_label),
                    "human_score": score(human_label),
                }
            )

    exact = sum(item["match"] for item in matches)
    weighted = (
        1
        - sum(abs(item["llm_score"] - item["human_score"]) for item in matches)
        / len(matches)
        if matches
        else 0.0
    )

    suppressed = [result for result in results if result.get("answer_suppressed")]
    # Proxy only: a suppressed case whose available human citation labels are all "yes".
    false_suppression_candidates = []
    for result in suppressed:
        labels = human_by_case.get(result.get("id", ""), [])
        if labels and all(row["human_support"] == "yes" for row in labels):
            false_suppression_candidates.append(result.get("id"))

    summary = report.get("summary", {})
    output = {
        "threshold": 0.35,
        "total_cases": len(results),
        "passed": summary.get("passed"),
        "citation_support_rate": summary.get("citation_support_rate"),
        "claim_support_rate": summary.get("claim_support_rate"),
        "suppressed": len(suppressed),
        "suppression_rate": round(len(suppressed) / len(results), 3) if results else 0.0,
        "matched_human_rows": len(matches),
        "exact_agreement": round(exact / len(matches), 3) if matches else None,
        "weighted_agreement": round(weighted, 3) if matches else None,
        "false_suppression_candidates": false_suppression_candidates,
        "note": "误杀是代理指标：只检查被抑制且该 case 的已有人工引用标签是否全为 yes；不是完整答案级人工评估。",
        "matches": matches,
    }
    OUT.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: value for key, value in output.items() if key != "matches"}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
