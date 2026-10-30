"""Run PaperPilot branch-level evaluation against the live API."""
from __future__ import annotations

import argparse
import json
import re
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent
DATASET = ROOT / "dataset.json"
REPORT = ROOT / "report.json"



def _tokens(text: str) -> set[str]:
    lowered = text.lower()
    tokens = set(re.findall(r"[a-z0-9]+", lowered))
    for seq in re.findall(r"[\u4e00-\u9fff]{2,}", lowered):
        tokens.update(seq[i : i + 2] for i in range(len(seq) - 1))
    return tokens


def citation_support(answer: str, citations: list[dict]) -> list[dict]:
    """Heuristic: does the sentence around [n] overlap the cited snippet?"""
    results = []
    for index, citation in enumerate(citations, 1):
        marker = f"[{index}]"
        position = answer.find(marker)
        if position < 0:
            results.append({"index": index, "score": 0.0, "supported": False})
            continue
        context = answer[max(0, position - 180) : position + 180]
        context_tokens = _tokens(context)
        snippet_tokens = _tokens(citation.get("snippet", ""))
        overlap = len(context_tokens & snippet_tokens)
        denominator = max(1, min(len(context_tokens), len(snippet_tokens)))
        score = round(overlap / denominator, 3)
        results.append({"index": index, "score": score, "supported": score >= 0.12})
    return results

def resolve_ids(papers: list[dict], keys: list[str]) -> list[int]:
    ids = []
    for key in keys:
        lowered = key.lower()
        for paper in papers:
            if lowered in paper["title"].lower() or lowered in paper["filename"].lower():
                ids.append(paper["id"])
                break
    return ids


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://127.0.0.1:8001")
    parser.add_argument("--username", default="demo")
    parser.add_argument("--password", default="demo1234")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--only", default="")
    parser.add_argument("--prefix", default="")
    args = parser.parse_args()

    base = args.base.rstrip("/")
    login = httpx.post(
        f"{base}/api/v1/auth/login",
        json={"username": args.username, "password": args.password},
        timeout=30,
    )
    login.raise_for_status()
    headers = {"Authorization": f"Bearer {login.json()['token']}"}
    papers = httpx.get(f"{base}/api/v1/papers", headers=headers, timeout=30).json()
    cases = json.loads(DATASET.read_text(encoding="utf-8"))
    if args.only:
        cases = [case for case in cases if case["id"] == args.only]
    if args.prefix:
        cases = [case for case in cases if case["id"].startswith(args.prefix)]
    if args.limit:
        cases = cases[: args.limit]

    results = []
    for case in cases:
        ids = resolve_ids(papers, case["paper_keys"])
        if len(ids) != len(case["paper_keys"]):
            results.append({**case, "passed": False, "error": "paper not found", "paper_ids": ids})
            print(f"[{case['id']}] FAIL paper not found")
            continue

        started = time.perf_counter()
        response = httpx.post(
            f"{base}/api/v1/chat",
            headers=headers,
            json={
                "paper_ids": ids,
                "question": case["question"],
                "answer_language": case.get("language", "zh"),
                "mode": "auto",
            },
            timeout=600,
        )
        elapsed = round(time.perf_counter() - started, 2)
        if response.status_code != 200:
            results.append({**case, "passed": False, "error": response.text[:300]})
            print(f"[{case['id']}] FAIL HTTP {response.status_code}")
            continue

        data = response.json()
        answer = data.get("answer", "").lower()
        citations = data.get("citations", [])
        strategy_ok = data.get("strategy") == case["strategy"]
        page_hit = not case.get("pages") or any(
            citation.get("page") in case["pages"] for citation in citations
        )
        keyword_hit = not case.get("keywords") or any(
            keyword.lower() in answer for keyword in case["keywords"]
        )
        paper_hit = True
        if case["strategy"] in {"compare", "innovate"} and len(case["paper_keys"]) > 1:
            titles = [citation.get("title", "").lower() for citation in citations]
            paper_hit = all(
                any(key.lower() in title for title in titles) for key in case["paper_keys"]
            )
        support = citation_support(data.get("answer", ""), citations)
        supported = sum(1 for item in support if item["supported"])
        support_rate = data.get("citation_support_rate")
        if support_rate is None:
            support_rate = round(supported / len(support), 3) if support else None
        passed = strategy_ok and page_hit and keyword_hit and paper_hit

        results.append(
            {
                **case,
                "paper_ids": ids,
                "strategy": data.get("strategy"),
                "route_reason": data.get("route_reason"),
                "latency_s": elapsed,
                "citations": citations,
                "answer_preview": data.get("answer", "")[:500],
                "checks": {
                    "strategy": strategy_ok,
                    "page": page_hit,
                    "keyword": keyword_hit,
                    "paper_coverage": paper_hit,
                },
                "citation_support": support,
                "citation_support_rate": support_rate,
                "claim_support_rate": data.get("claim_support_rate"),
                "claims": data.get("claims", []),
                "answer_suppressed": bool(data.get("answer_suppressed")),
                "citation_support_threshold": data.get("citation_support_threshold"),
                "passed": passed,
            }
        )
        mark = "PASS" if passed else "FAIL"
        print(
            f"[{case['id']}] {mark} strategy={data.get('strategy')} "
            f"pages={[c.get('page') for c in citations]} latency={elapsed}s"
        )

    total = len(results)
    passed = sum(1 for result in results if result["passed"])
    summary = {
        "total": total,
        "passed": passed,
        "accuracy": round(passed / total, 4) if total else 0.0,
        "by_strategy": {},
        "citation_support_rate": None,
        "claim_support_rate": None,
        "suppressed": 0,
        "suppression_rate": 0.0,
    }
    for result in results:
        strategy = result.get("strategy") or result.get("strategy")
        bucket = summary["by_strategy"].setdefault(strategy, {"total": 0, "passed": 0})
        bucket["total"] += 1
        bucket["passed"] += int(bool(result["passed"]))

    supported_rates = [
        result["citation_support_rate"]
        for result in results
        if result.get("citation_support_rate") is not None
    ]
    if supported_rates:
        summary["citation_support_rate"] = round(sum(supported_rates) / len(supported_rates), 3)
    claim_rates = [
        result["claim_support_rate"]
        for result in results
        if result.get("claim_support_rate") is not None
    ]
    summary["claim_support_rate"] = (
        round(sum(claim_rates) / len(claim_rates), 3) if claim_rates else None
    )
    summary["suppressed"] = sum(1 for result in results if result.get("answer_suppressed"))
    summary["suppression_rate"] = (
        round(summary["suppressed"] / total, 3) if total else 0.0
    )

    report = {"summary": summary, "results": results}
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"report: {REPORT}")


if __name__ == "__main__":
    main()
