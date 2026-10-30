"""Small regression set for the citation verifier, derived from human review."""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.llm import verify_citations  # noqa: E402
from app.schemas import Citation  # noqa: E402

CASES = [
    {
        "id": "p02_c1",
        "claim": "RAG 在开放域 QA 上达到 SOTA。",
        "evidence": "For 3-way classification, RAG scores are within 4.3% of state-of-the-art models.",
        "expected": "no",
    },
    {
        "id": "p04_c1",
        "claim": "Ragas 是面向 RAG 的自动化评估框架。",
        "evidence": "Ragas: Automated Evaluation of Retrieval Augmented Generation. Authors: Shahul Es, Jithin James, Luis Espinosa-Anke, Steven Schockaert.",
        "expected": "no",
    },
    {
        "id": "p04_c3",
        "claim": "Ragas 是无参考自动评估框架，并提供 llama-index 集成。",
        "evidence": "We focus on settings where reference answers may not be available... The Ragas framework provides an integration with both llama-index and Langchain.",
        "expected": "partial",
    },
    {
        "id": "p06_c1",
        "claim": "Ragas 的主要特点是 reference-free 自动评估框架。",
        "evidence": "Ragas: Automated Evaluation of Retrieval Augmented Generation. Authors: Shahul Es et al.",
        "expected": "no",
    },
    {
        "id": "p08_c1",
        "claim": "CRAG 会自我修正，并使用 decompose-then-recompose 和三类动作。",
        "evidence": "CRAG is proposed to self-correct the results of retriever and improve the utilization of documents.",
        "expected": "partial",
    },
    {
        "id": "p11_c4",
        "claim": "GraphRAG 能缓解全局问题被检索事实样本误作全局摘要的风险。",
        "evidence": "There are risks to downstream sensemaking and decision-making tasks if the generated answers do not accurately represent the source data.",
        "expected": "no",
    },
]


async def main() -> None:
    correct = 0
    results = []
    for case in CASES:
        citation = Citation(
            chunk_id=case["id"],
            paper_id=1,
            title="calibration",
            page=1,
            section="",
            snippet=case["evidence"],
        )
        verified, _ = await verify_citations(
            f"{case['claim']} [1]", [citation]
        )
        actual = verified[0].support
        ok = actual == case["expected"]
        correct += int(ok)
        results.append({"id": case["id"], "expected": case["expected"], "actual": actual, "ok": ok, "reason": verified[0].support_reason})
        print(f"{case['id']}: expected={case['expected']} actual={actual} ok={ok}")
        print(f"  reason={verified[0].support_reason}")
    summary = {"total": len(CASES), "correct": correct, "accuracy": round(correct / len(CASES), 4), "results": results}
    (ROOT / "eval" / "verifier_calibration_result.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"accuracy: {correct}/{len(CASES)} = {correct / len(CASES):.2%}")


if __name__ == "__main__":
    asyncio.run(main())
