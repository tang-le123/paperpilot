"""Convert retrieval_gold_template.csv into retrieval_gold.json."""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DEFAULT_IN = ROOT / "retrieval_gold_template.csv"
DEFAULT_OUT = ROOT / "retrieval_gold.json"


def split(value: str) -> list[str]:
    return [item.strip() for item in value.split("|") if item.strip()]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default=str(DEFAULT_IN))
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    args = parser.parse_args()

    rows = list(csv.DictReader(Path(args.input).open(encoding="utf-8-sig")))
    cases = []
    for row in rows:
        if not (row.get("gold_pages") or row.get("gold_chunk_ids")):
            continue
        cases.append(
            {
                "id": row["id"],
                "paper_keys": split(row["paper_keys"]),
                "question": row["question"],
                "gold_pages": [int(value) for value in split(row.get("gold_pages", ""))],
                "gold_chunk_ids": split(row.get("gold_chunk_ids", "")),
                "notes": row.get("notes", ""),
            }
        )
    Path(args.out).write_text(json.dumps(cases, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {len(cases)} labeled cases to {args.out}")


if __name__ == "__main__":
    main()
