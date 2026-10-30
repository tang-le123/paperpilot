"""Rule-based query intent, rewrite and section filters.

The rewrite is intentionally deterministic: it adds retrieval terms without
another LLM call, so latency stays predictable.
"""
from __future__ import annotations

import re

DEFINITION = "definition"
NUMERIC = "numeric"
METHOD = "method"
RESULT = "result"
GENERAL = "general"

_DEFINITION_CUES = ("是什么", "什么是", "定义", "全称", "含义", "stands for", "what is")
_NUMERIC_CUES = (
    "多少", "数值", "几", "比例", "百分比", "r²", "r2", "rmse", "mae",
    "指标", "参数", "how many", "how much", "percentage", "number",
)
_METHOD_CUES = (
    "方法", "模型", "算法", "如何实现", "怎么实现", "流程", "框架",
    "method", "methodology", "approach", "algorithm", "how does",
)
_RESULT_CUES = (
    "结果", "结论", "表现", "性能", "实验", "效果", "提升", "下降",
    "result", "conclusion", "performance", "experiment", "improve",
)

_SECTION_FILTERS = {
    DEFINITION: ["Abstract", "摘要", "Introduction", "引言", "Background", "背景", "Method", "方法"],
    NUMERIC: ["Results", "结果", "Experiment", "实验", "Evaluation", "评估", "Conclusion", "结论"],
    METHOD: ["Method", "方法", "Methodology", "Approach", "实验", "Experiment", "Introduction", "引言"],
    RESULT: ["Results", "结果", "Experiment", "实验", "Evaluation", "评估", "Conclusion", "结论"],
}


def classify(question: str) -> str:
    text = question.lower()
    if any(cue in text for cue in _DEFINITION_CUES):
        return DEFINITION
    if any(cue in text for cue in _NUMERIC_CUES):
        return NUMERIC
    if any(cue in text for cue in _METHOD_CUES):
        return METHOD
    if any(cue in text for cue in _RESULT_CUES):
        return RESULT
    return GENERAL


def rewrite(question: str, intent: str) -> str:
    expansions = {
        DEFINITION: "定义 全称 概念 definition",
        NUMERIC: "数值 结果 指标 表格 number result metric table",
        METHOD: "方法 模型 流程 methodology method approach",
        RESULT: "结果 实验 性能 结论 results experiment performance conclusion",
    }
    suffix = expansions.get(intent, "")
    # Avoid duplicating the same expansion on an already-expanded query.
    if suffix and suffix in question:
        return question
    return f"{question} {suffix}".strip()


def sections(intent: str) -> list[str] | None:
    return _SECTION_FILTERS.get(intent)
