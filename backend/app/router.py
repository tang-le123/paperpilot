"""Query routing for PaperPilot, inspired by Adaptive-RAG."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Strategy(str, Enum):
    SINGLE = "single"
    COMPARE = "compare"
    INNOVATE = "innovate"
    SUMMARY = "summary"
    EXPLAIN = "explain"
    CLARIFY = "clarify"


@dataclass(frozen=True)
class RouteDecision:
    strategy: Strategy
    reason: str


_COMPARE_CUES = (
    "比较",
    "对比",
    "区别",
    "差异",
    "相比",
    "不同",
    "共同点",
    "相同",
    "共同",
    "哪个更好",
    "compare",
    "comparison",
    "difference",
    "versus",
    " vs ",
)
_INNOVATE_CUES = (
    "创新",
    "改进",
    "新想法",
    "新思路",
    "研究空白",
    "空白",
    "未来工作",
    "还能怎么做",
    "选题",
    "发论文",
    "innovation",
    "novel",
    "research gap",
    "future work",
    "idea",
)
_SUMMARY_CUES = (
    "总结",
    "概括",
    "摘要",
    "summarize",
    "summary",
    "overview",
)
_EXPLAIN_CUES = (
    "什么是",
    "定义",
    "全称",
    "含义",
    "什么意思",
    "what is",
    "stands for",
    "definition",
    "define ",
)
_PAPER_CONTENT_CUES = (
    "方法",
    "结果",
    "结论",
    "贡献",
    "创新",
    "内容",
    "数据集",
    "实验",
    "研究",
    "论文",
    "文章",
    "主要",
    "标题",
    "问题",
    "阶段",
    "模式",
    "失败",
    "作用",
    "用途",
    "为什么",
    "method",
    "result",
    "conclusion",
    "contribution",
    "dataset",
    "experiment",
    "goal",
    "title",
    "paper",
    "study",
    "main",
    "failure",
    "problem",
    "stage",
    "phase",
    "pattern",
    "purpose",
    "why",
    "how",
)


def _is_explain_question(text: str) -> bool:
    if any(cue in text for cue in _EXPLAIN_CUES):
        return not any(cue in text for cue in _PAPER_CONTENT_CUES)
    # "LASSO 是什么" is a definition; "这篇论文的方法是什么" is content.
    if "是什么" in text:
        return not any(cue in text for cue in _PAPER_CONTENT_CUES)
    return False


def route(question: str, paper_count: int, mode: str = "auto") -> RouteDecision:
    """Choose a strategy. Explicit UI mode wins over automatic routing."""
    text = question.lower().strip()

    if mode == "compare":
        return RouteDecision(
            Strategy.COMPARE if paper_count >= 2 else Strategy.CLARIFY,
            "用户手动选择论文对比",
        )
    if mode == "innovate":
        return RouteDecision(Strategy.INNOVATE, "用户手动选择创新点")
    if mode == "summary":
        return RouteDecision(Strategy.SUMMARY, "用户手动选择总结")
    if mode == "explain":
        return RouteDecision(Strategy.EXPLAIN, "用户手动选择术语解释")
    if mode == "single":
        return RouteDecision(Strategy.SINGLE, "用户手动选择内容问答")

    # Auto routing: innovation first because it subsumes comparison.
    if any(cue in text for cue in _INNOVATE_CUES):
        return RouteDecision(Strategy.INNOVATE, "检测到创新/研究空白线索")
    if any(cue in text for cue in _COMPARE_CUES):
        if paper_count < 2:
            return RouteDecision(Strategy.CLARIFY, "论文对比至少需要两篇论文")
        return RouteDecision(Strategy.COMPARE, "检测到论文对比线索")
    if any(cue in text for cue in _SUMMARY_CUES):
        return RouteDecision(Strategy.SUMMARY, "检测到总结线索")
    if _is_explain_question(text):
        return RouteDecision(Strategy.EXPLAIN, "检测到术语解释线索")
    return RouteDecision(Strategy.SINGLE, "默认单篇/多篇内容问答")
