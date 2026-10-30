"""DeepSeek answer generation with citations."""
from __future__ import annotations

import asyncio
import json
import re

import httpx

from app.config import DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, DEEPSEEK_MODEL
from app.schemas import Citation, ClaimCheck


CITATION_RULES = """引用规则：
- 每个事实性句子只引用直接支持它的 chunk；
- 论文标题、作者、机构、页眉页脚不能作为定义或结论证据；
- 数值、方法名、数据集名必须与证据原文一致；
- 没有直接证据时，不要引用，明确写“证据不足”。"""


def _extractive(chunks: list[dict], language: str) -> tuple[str, list[Citation]]:
    citations = [
        Citation(
            chunk_id=chunk["chunk_id"],
            paper_id=chunk["paper_id"],
            title=chunk.get("title", ""),
            page=chunk.get("page", 0),
            section=chunk.get("section", ""),
            snippet=chunk["content"][:300],
        )
        for chunk in chunks[:3]
    ]
    snippet = chunks[0]["content"][:700] if chunks else ""
    if language == "en":
        answer = f"Unable to generate a full answer right now. Relevant excerpt:\n\n> {snippet}"
    else:
        answer = f"暂时无法生成完整回答，先给你相关原文：\n\n> {snippet}"
    return answer, citations


def _parse_json(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {"answer": text, "citation_ids": []}


def _citation(chunk: dict) -> Citation:
    return Citation(
        chunk_id=chunk["chunk_id"],
        paper_id=chunk["paper_id"],
        title=chunk.get("title", ""),
        page=chunk.get("page", 0),
        section=chunk.get("section", ""),
        snippet=chunk["content"][:300],
    )


def _renumber_citations(
    answer: str, citations: list[Citation]
) -> tuple[str, list[Citation]]:
    """Number citations by first appearance; return reordered citation cards."""
    by_id = {citation.chunk_id: citation for citation in citations}
    mapping: dict[str, str] = {}
    order: list[str] = []

    def replace(match: re.Match[str]) -> str:
        chunk_id = match.group(1)
        if chunk_id not in by_id:
            return ""
        if chunk_id not in mapping:
            mapping[chunk_id] = str(len(mapping) + 1)
            order.append(chunk_id)
        return f"[{mapping[chunk_id]}]"

    rewritten = re.sub(r"\[([A-Za-z0-9_]+)\]", replace, answer)
    ordered = [by_id[chunk_id] for chunk_id in order]
    ordered.extend(citation for citation in citations if citation.chunk_id not in mapping)
    return rewritten, ordered


def strip_citation_markers(answer: str) -> str:
    return re.sub(r"\s*\[[A-Za-z0-9_]+\]", "", answer)


async def generate_answer(
    *,
    question: str,
    chunks: list[dict],
    language: str,
) -> tuple[str, list[Citation]]:
    if not chunks:
        if language == "en":
            return "The selected papers do not contain enough evidence to answer this question.", []
        return "选中的论文中没有足够的证据来回答这个问题。", []

    if not DEEPSEEK_API_KEY:
        return _extractive(chunks, language)

    evidence = "\n\n".join(
        f"[{chunk['chunk_id']}] {chunk.get('title', '')} | page {chunk.get('page', '?')} | "
        f"{chunk.get('section', '')}\n{chunk['content']}"
        for chunk in chunks[:8]
    )
    language_instruction = "Answer in English." if language == "en" else "用简体中文回答。"
    prompt = f"""你是论文阅读助手。只根据给定的论文证据回答，不要编造。
{language_instruction}
如果证据不足，直接说明证据不足，不要猜测。
保留论文标题、方法名、数据集名的原文；可以在括号中给译文。
回答中引用证据编号，例如 [p1_c0003]。
{CITATION_RULES}

问题：{question}

论文证据：
{evidence}

只返回 JSON，不要 Markdown 代码块：
{{"answer":"...","citation_ids":["p1_c0003"]}}
"""

    try:
        async with httpx.AsyncClient(
            base_url=DEEPSEEK_BASE_URL.rstrip("/"),
            timeout=httpx.Timeout(connect=5.0, read=90.0, write=15.0, pool=5.0),
        ) as client:
            response = await client.post(
                "/chat/completions",
                headers={"Authorization": f"Bearer {DEEPSEEK_API_KEY}"},
                json={
                    "model": DEEPSEEK_MODEL,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.1,
                    "max_tokens": 1000,
                    "response_format": {"type": "json_object"},
                },
            )
            response.raise_for_status()
            content = response.json()["choices"][0]["message"]["content"]
    except Exception:
        return _extractive(chunks, language)

    payload = _parse_json(content)
    answer = str(payload.get("answer") or "").strip() or _extractive(chunks, language)[0]
    wanted = set(payload.get("citation_ids") or [])
    citations = [_citation(chunk) for chunk in chunks if chunk["chunk_id"] in wanted]
    if not citations:
        citations = [_citation(chunk) for chunk in chunks[:2]]
    return _renumber_citations(answer, citations)


async def _complete(prompt: str, *, max_tokens: int = 800) -> str | None:
    if not DEEPSEEK_API_KEY:
        return None
    try:
        async with httpx.AsyncClient(
            base_url=DEEPSEEK_BASE_URL.rstrip("/"),
            timeout=httpx.Timeout(connect=5.0, read=120.0, write=15.0, pool=5.0),
        ) as client:
            response = await client.post(
                "/chat/completions",
                headers={"Authorization": f"Bearer {DEEPSEEK_API_KEY}"},
                json={
                    "model": DEEPSEEK_MODEL,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.1,
                    "max_tokens": max_tokens,
                },
            )
            response.raise_for_status()
            return response.json()["choices"][0]["message"]["content"] or ""
    except Exception:
        return None


def _make_units(chunks: list[dict], *, max_chars: int, max_units: int) -> list[list[dict]]:
    ordered = sorted(chunks, key=lambda chunk: chunk.get("chunk_index", 0))
    units: list[list[dict]] = []
    current: list[dict] = []
    size = 0
    for chunk in ordered:
        length = len(chunk["content"])
        if current and size + length > max_chars:
            units.append(current)
            current = []
            size = 0
        current.append(chunk)
        size += length
    if current:
        units.append(current)
    if len(units) <= max_units:
        return units
    # Keep the beginning and end of the paper; sample evenly in between.
    indexes = sorted({round(i * (len(units) - 1) / (max_units - 1)) for i in range(max_units)})
    return [units[index] for index in indexes]


def _fallback_summary(papers: list[dict], language: str) -> str:
    blocks = []
    for paper in papers:
        excerpt = "\n\n".join(
            f"[{chunk['chunk_id']}] page {chunk.get('page', '?')} | {chunk.get('section', '')}\n"
            f"{chunk['content'][:700]}"
            for chunk in paper["chunks"][:4]
        )
        blocks.append(f"### {paper['title']}\n{excerpt}")
    prefix = "Summary generation failed; excerpts:\n\n" if language == "en" else "总结生成失败，先返回原文节选：\n\n"
    return prefix + "\n\n".join(blocks)[:5000]


async def _summarize_paper(paper: dict, language: str, *, max_units: int) -> str:
    language_instruction = (
        "You MUST write the entire summary in English."
        if language == "en"
        else "必须用简体中文总结。"
    )
    section_label = "Section" if language == "en" else "分段"
    reduce_structure = (
        """## Research Question
## Method
## Data and Experiments
## Main Results
## Limitations
## Key Points (3–5)"""
        if language == "en"
        else """## 研究问题
## 方法
## 数据与实验
## 主要结果
## 局限
## 知识点（3–5 条）"""
    )
    units = _make_units(paper["chunks"], max_chars=5000, max_units=max_units)
    semaphore = asyncio.Semaphore(3)

    async def map_unit(unit: list[dict]) -> str:
        evidence = "\n\n".join(
            f"[{chunk['chunk_id']}] page {chunk.get('page', '?')} | {chunk.get('section', '')}\n"
            f"{chunk['content']}"
            for chunk in unit
        )
        prompt = f"""你是论文阅读助手。下面是论文《{paper['title']}》的一部分。
{language_instruction}
请提取这一部分的关键事实：研究问题、方法、数据、结果、局限。
保留方法名、数据集名、关键数字；保留 [chunk_id] 引用。
输出 3–6 条短要点，不要编造。

{evidence}
"""
        async with semaphore:
            result = await _complete(prompt, max_tokens=450)
        if result:
            return result.strip()
        return "\n".join(f"[{chunk['chunk_id']}] {chunk['content'][:300]}" for chunk in unit[:3])

    map_results = await asyncio.gather(*(map_unit(unit) for unit in units))
    merged_maps = "\n\n".join(
        f"### {section_label} {index + 1}\n{text}" for index, text in enumerate(map_results)
    )

    reduce_prompt = f"""你是论文阅读助手。下面是对论文《{paper['title']}》各部分的摘要。
{language_instruction}
请合并成一份结构化总结，不要编造；保留重要 [chunk_id] 引用。
如果原文是英文而用户选择中文，用中文总结，但保留方法名、数据集名的原文。

请严格使用以下结构（标题也用同一种语言）：
{reduce_structure}

各部分摘要：
{merged_maps}
"""
    reduced = await _complete(reduce_prompt, max_tokens=1200)
    return reduced or merged_maps


async def summarize_papers(*, papers: list[dict], language: str) -> str:
    """Map section batches, then reduce per paper; synthesize across papers."""
    if not papers:
        return "没有可总结的论文。" if language == "zh" else "No papers to summarize."
    if not DEEPSEEK_API_KEY:
        return _fallback_summary(papers, language)

    max_units = 6 if len(papers) == 1 else 4
    paper_summaries = []
    for paper in papers:
        paper_summaries.append(
            {
                "title": paper["title"],
                "summary": await _summarize_paper(paper, language, max_units=max_units),
            }
        )

    if len(paper_summaries) == 1:
        return paper_summaries[0]["summary"]

    language_instruction = (
        "You MUST write the entire synthesis in English."
        if language == "en"
        else "必须用简体中文综合。"
    )
    synthesis_structure = (
        """## Common Ground
## Differences
## When to Choose Which
## Synthesized Key Points (3–5)"""
        if language == "en"
        else """## 共同点
## 差异
## 各自适用场景
## 综合知识点（3–5 条）"""
    )
    combined = "\n\n".join(
        f"### {item['title']}\n{item['summary']}" for item in paper_summaries
    )
    synthesis_prompt = f"""你是论文阅读助手。下面是对多篇论文分别做的总结。
{language_instruction}
请只根据这些总结做综合对比，不要编造；保留 [chunk_id] 引用。

请严格使用以下结构（标题也用同一种语言）：
{synthesis_structure}

各论文总结：
{combined}
"""
    synthesized = await _complete(synthesis_prompt, max_tokens=1200)
    if synthesized:
        return synthesized
    return combined


def _citations_from_answer(answer: str, chunks: list[dict]) -> list[Citation]:
    wanted = set(re.findall(r"\[([A-Za-z0-9_]+)\]", answer))
    seen: set[str] = set()
    citations = []
    for chunk in chunks:
        chunk_id = chunk["chunk_id"]
        if chunk_id in wanted and chunk_id not in seen:
            seen.add(chunk_id)
            citations.append(_citation(chunk))
    return citations


def _evidence_by_paper(chunks: list[dict]) -> str:
    grouped: dict[str, list[dict]] = {}
    for chunk in chunks:
        grouped.setdefault(chunk.get("title", "Unknown"), []).append(chunk)
    blocks = []
    for title, items in grouped.items():
        excerpts = "\n\n".join(
            f"[{item['chunk_id']}] page {item.get('page', '?')} | {item.get('section', '')}\n"
            f"{item['content']}"
            for item in items
        )
        blocks.append(f"### {title}\n{excerpts}")
    return "\n\n".join(blocks)


async def answer_compare(
    *,
    question: str,
    chunks: list[dict],
    language: str,
) -> tuple[str, list[Citation]]:
    if not chunks:
        return ("没有足够的论文证据进行对比。", []) if language == "zh" else (
            "There is not enough evidence to compare the selected papers.",
            [],
        )
    instruction = "You MUST write the entire answer in English." if language == "en" else (
        "必须用简体中文回答。"
    )
    structure = (
        """## Comparison Table
| Dimension | Paper A | Paper B |
## Key Differences
## When to Choose Which"""
        if language == "en"
        else """## 对比表
| 维度 | 论文 A | 论文 B |
## 关键差异
## 选择建议"""
    )
    prompt = f"""你是论文阅读助手。下面是多篇论文的证据。
{instruction}
请做结构化对比，只根据证据，不要编造；保留 [chunk_id] 引用。
{CITATION_RULES}
重点比较：研究问题、方法、数据、主要结果、局限、适用场景。
如果某篇论文缺少某个维度，明确写“未提及”。

用户问题：{question}

证据：
{_evidence_by_paper(chunks)}

请严格使用以下结构（标题也用同一种语言）：
{structure}
"""
    answer = await _complete(prompt, max_tokens=1400)
    if not answer:
        return _extractive(chunks, language)
    citations = _citations_from_answer(answer, chunks)
    return _renumber_citations(answer, citations)


async def answer_innovation(
    *,
    question: str,
    chunks: list[dict],
    language: str,
) -> tuple[str, list[Citation]]:
    if not chunks:
        return ("没有足够的论文证据提出创新点。", []) if language == "zh" else (
            "There is not enough evidence to propose innovations.",
            [],
        )
    instruction = "You MUST write the entire answer in English." if language == "en" else (
        "必须用简体中文回答。"
    )
    structure = (
        """### Innovation N: title
- Evidence (citation): ...
- Research gap: ...
- What is new: ...
- Validation plan: ...
- Risks and boundaries: ...

## Further Reading Needed"""
        if language == "en"
        else """### 创新点 N：标题
- 依据（引用）：...
- 研究空白：...
- 新在哪里：...
- 验证方案：...
- 风险与边界：...

## 需要补充的文献"""
    )
    prompt = f"""你是论文阅读与科研选题助手。下面是论文证据。
{instruction}
请基于这些证据提出 3–5 个可验证的创新点，但不要声称“绝对原创”；
每个创新点必须说明依据、研究空白、验证方案和风险。
保留 [chunk_id] 引用；证据不足时明确写“需要进一步检索”。
{CITATION_RULES}

用户问题：{question}

证据：
{_evidence_by_paper(chunks)}

请严格使用以下结构：
{structure}
"""
    answer = await _complete(prompt, max_tokens=1600)
    if not answer:
        return _extractive(chunks, language)
    citations = _citations_from_answer(answer, chunks)
    return _renumber_citations(answer, citations)

async def answer_explain(
    *,
    question: str,
    chunks: list[dict],
    glossary_body: str | None,
    language: str,
    allow_general: bool,
) -> tuple[str, list[Citation], str, bool]:
    """Explain a term: paper usage first, then glossary/general knowledge."""
    if not chunks and not glossary_body and not allow_general:
        text = (
            "论文和本地术语库都没有找到这个术语的定义。"
            if language == "zh"
            else "The paper and local glossary do not define this term."
        )
        return text, [], "paper", False

    instruction = "You MUST write the entire answer in English." if language == "en" else (
        "必须用简体中文回答。"
    )
    evidence = "\n\n".join(
        f"[{chunk['chunk_id']}] page {chunk.get('page', '?')} | {chunk.get('section', '')}\n"
        f"{chunk['content']}"
        for chunk in chunks[:6]
    ) or "(无论文证据)"
    glossary_text = glossary_body or "(术语库未收录)"
    general_rule = (
        "如果论文和术语库都没有定义，可以用通用知识补充，但必须明确标注"
        "“通用知识，不在论文中，请自行核对”。"
        if allow_general
        else "如果论文和术语库都没有定义，只说明“论文/术语库未定义”，不要使用通用知识。"
    )

    prompt = f"""你是论文阅读助手。用户在读论文时问到一个术语。
{instruction}
请严格区分“论文中的用法”和“术语解释”，不要编造论文内容。

用户问题：{question}

论文证据（可能只包含术语的使用，未必有定义）：
{evidence}

本地术语库（若收录，优先作为术语定义）：
{glossary_text}

输出要求：
## 论文中的用法
只根据论文证据总结这个术语在论文中用来做什么；引用 [chunk_id]。
如果论文没有提到，写“论文未提及”。

## 术语解释
- 如果术语库有定义：用术语库解释，并标注“来源：本地术语库”。
- 如果论文本身给出了定义：引用论文并标注“来源：论文”。
- 如果两者都没有：{general_rule}

## 与本论文的关系
用 1–2 句说明这个术语在论文上下文中的作用。
"""
    answer = await _complete(prompt, max_tokens=1200)
    if not answer:
        answer = "暂时无法生成术语解释。"
    citations = _citations_from_answer(answer, chunks)
    answer, citations = _renumber_citations(answer, citations)
    if glossary_body:
        return answer, citations, "paper+glossary", False
    return answer, citations, "paper+general" if allow_general else "paper", bool(allow_general)

async def stream_complete(prompt: str, max_tokens: int = 1600):
    """Yield DeepSeek content deltas. Falls back to one chunk if no API key."""
    if not DEEPSEEK_API_KEY:
        yield "（未配置 DEEPSEEK_API_KEY，无法流式生成。）"
        return

    payload = {
        "model": DEEPSEEK_MODEL,
        "messages": [
            {"role": "system", "content": "你是严谨的论文阅读助手。"},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.2,
        "max_tokens": max_tokens,
        "stream": True,
    }
    headers = {
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
        "Content-Type": "application/json",
    }
    async with httpx.AsyncClient(timeout=300) as client:
        async with client.stream(
            "POST", f"{DEEPSEEK_BASE_URL}/chat/completions", json=payload, headers=headers
        ) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                try:
                    chunk = json.loads(data)
                except json.JSONDecodeError:
                    continue
                delta = (
                    chunk.get("choices", [{}])[0]
                    .get("delta", {})
                    .get("content", "")
                )
                if delta:
                    yield delta


def build_stream_prompt(
    strategy: str,
    *,
    question: str,
    chunks: list[dict],
    language: str,
    glossary_body: str | None = None,
    allow_general: bool = True,
) -> str:
    instruction = "You MUST write the entire answer in English." if language == "en" else (
        "必须用简体中文回答。"
    )
    evidence = _evidence_by_paper(chunks) if chunks else "(无论文证据)"
    if strategy == "compare":
        return f"""你是论文阅读助手。{instruction}
请根据证据做结构化对比，保留 [chunk_id]，证据不足写“未提及”。
{CITATION_RULES}
用户问题：{question}
证据：{evidence}
"""
    if strategy == "innovate":
        return f"""你是科研选题助手。{instruction}
请基于证据提出 3–5 个可验证创新点，说明依据、空白、验证方案和风险；
不要声称绝对原创；保留 [chunk_id]。
{CITATION_RULES}
用户问题：{question}
证据：{evidence}
"""
    if strategy == "explain":
        rule = (
            "论文和术语库都没有定义时，可补充通用知识，但必须标注“通用知识，不在论文中”。"
            if allow_general
            else "论文和术语库都没有定义时，只说明未定义，不要使用通用知识。"
        )
        return f"""你是论文阅读助手。{instruction}
请区分“论文中的用法”和“术语解释”。{rule}
论文中的用法必须引用 [chunk_id]；没有证据就写“论文未提及”。
{CITATION_RULES}
本地术语库：{glossary_body or "(未收录)"}
用户问题：{question}
论文证据：{evidence}
"""
    return f"""你是论文阅读助手。{instruction}
请只根据论文证据回答，每个结论保留 [chunk_id]；证据不足要明确说明。
{CITATION_RULES}
用户问题：{question}
证据：{evidence}
"""

def _support_tokens(text: str) -> set[str]:
    lowered = text.lower()
    tokens = set(re.findall(r"[a-z0-9]+", lowered))
    for seq in re.findall(r"[\u4e00-\u9fff]{2,}", lowered):
        tokens.update(seq[i : i + 2] for i in range(len(seq) - 1))
    return tokens


def _claim_for_marker(answer: str, marker: str) -> str:
    sentences = [
        part.strip()
        for part in re.split(r"(?<=[。！？.!?])\s+|\n+", answer)
        if part.strip()
    ]
    for index, sentence in enumerate(sentences):
        if marker not in sentence:
            continue
        cleaned = sentence.replace(marker, "").strip()
        if len(cleaned) >= 8:
            return sentence[:700]
        if index > 0:
            return f"{sentences[index - 1]} {sentence}"[:700]
        return sentence[:700]
    position = answer.find(marker)
    if position < 0:
        return ""
    return answer[max(0, position - 180) : position + 180].strip()


def _lexical_support(claim: str, snippet: str) -> str:
    claim_tokens = _support_tokens(claim)
    snippet_tokens = _support_tokens(snippet)
    if not claim_tokens or not snippet_tokens:
        return "unknown"
    overlap = len(claim_tokens & snippet_tokens)
    denominator = max(1, min(len(claim_tokens), len(snippet_tokens)))
    score = overlap / denominator
    if score >= 0.24:
        return "yes"
    if score >= 0.10:
        return "partial"
    return "no"


async def verify_citations(
    answer: str,
    citations: list[Citation],
) -> tuple[list[Citation], float | None]:
    """Judge whether each cited chunk supports the sentence using it."""
    if not citations:
        return [], None

    items = []
    for index, citation in enumerate(citations, 1):
        marker = f"[{index}]"
        claim = _claim_for_marker(answer, marker)
        items.append(
            {
                "index": index,
                "claim": claim or "(answer does not contain this marker)",
                "evidence": citation.snippet,
            }
        )

    prompt = f"""你是严格的引用审核员。逐条判断“证据”是否支持“答案中的句子”。
严格输出 JSON，不要 Markdown：
{{"results":[{{"index":1,"support":"yes|partial|no","reason":"简短理由"}}]}}

判定规则（按顺序执行）：
1. 如果证据只有论文标题、作者、机构、页眉页脚，不能作为定义或结论证据 → no。
2. 如果 claim 含“SOTA / first / all / only / 最优 / 全部 / 首次 / 精确数值”等强限定词，而证据没有明确给出该限定 → 不能判 yes；只能 partial 或 no。
3. 如果 claim 由多个子句、步骤或动作组成，证据支持其中至少一个实质部分，但缺少其他部分 → partial；不要因为缺少“主要结论”就统一判 no。
4. 只有证据明确陈述了 claim 的主要结论，并且关键限定词也一致，才判 yes。
5. 不要因为主题相近、出现同一个术语、或标题包含该术语就判 yes。
6. 不要使用证据之外的知识。

例子：
- claim: “Ragas 是无参考自动评估框架。” evidence: 只有 “Ragas: Automated Evaluation...” 标题和作者 → no。
- claim: “Ragas 是无参考自动评估框架，并提供 llama-index 集成。” evidence: 提到 reference-free 或 llama-index 集成，但没有完整定义 → partial。
- claim: “CRAG 会自我修正，并使用 decompose-then-recompose 和三类动作。” evidence: 只说明 CRAG 会 self-correct（支持第一个动作）→ partial，不能判 no。
- claim: “RAG 在开放域 QA 达到 SOTA。” evidence: 只说 FEVER 差 4.3% → no。
- claim: “GraphRAG 两阶段构建图谱。” evidence: 只说明第一阶段实体图 → partial。

待审核：
{json.dumps(items, ensure_ascii=False)}
"""
    raw = await _complete(prompt, max_tokens=900)
    parsed = _parse_json(raw) if raw else {}
    verdicts = {}
    for item in parsed.get("results", []) if isinstance(parsed, dict) else []:
        try:
            index = int(item.get("index"))
        except (TypeError, ValueError):
            continue
        support = str(item.get("support", "")).lower()
        if support in {"yes", "partial", "no"}:
            verdicts[index] = (support, str(item.get("reason", ""))[:300])

    verified = []
    total = 0.0
    for index, citation in enumerate(citations, 1):
        support, reason = verdicts.get(index, ("unknown", ""))
        if support == "unknown":
            support = _lexical_support(items[index - 1]["claim"], items[index - 1]["evidence"])
            reason = "启发式：回答句子与引用片段词重合"
        if support == "yes" and re.search(
            r"(?:并|且|同时|以及)(?:使用|触发|提供|支持|采用|包含|实现|进行|"
            r"检索|生成|执行|给出|选择|修正|完成|引入|结合)",
            items[index - 1]["claim"],
        ):
            support = "partial"
            reason = (reason + "；claim 含多个动作，未能证明全部动作").strip("；")
        total += {"yes": 1.0, "partial": 0.5, "no": 0.0}.get(support, 0.0)
        verified.append(
            citation.model_copy(update={"support": support, "support_reason": reason})
        )
    return verified, round(total / len(verified), 3)

def clean_citations(
    answer: str, citations: list[Citation]
) -> tuple[str, list[Citation]]:
    """Remove [n] markers judged unsupported and renumber the rest."""
    by_index = {index: citation for index, citation in enumerate(citations, 1)}
    new_index: dict[int, int] = {}
    ordered: list[Citation] = []

    def replace(match: re.Match[str]) -> str:
        old = int(match.group(1))
        citation = by_index.get(old)
        if citation is None or citation.support == "no":
            return ""
        if old not in new_index:
            new_index[old] = len(new_index) + 1
            ordered.append(citation)
        return f"[{new_index[old]}]"

    rewritten = re.sub(r"\[(\d+)\]", replace, answer)
    # Keep citations that were never referenced only if they are supported.
    for index, citation in by_index.items():
        if index not in new_index and citation.support == "yes":
            ordered.append(citation)
    return rewritten, ordered


async def repair_partial_answer(
    answer: str,
    citations: list[Citation],
    language: str,
    extra_chunks: list[dict] | None = None,
) -> str:
    """Ask the model to repair claims that are only partially supported."""
    partial = [
        (index, citation)
        for index, citation in enumerate(citations, 1)
        if citation.support == "partial"
    ]
    if not partial:
        return answer
    instruction = "You MUST write the revised answer in English." if language == "en" else (
        "必须用简体中文改写。"
    )
    evidence = "\n\n".join(
        f"[{index}] {citation.snippet}" for index, citation in partial
    )
    extra_text = ""
    if extra_chunks:
        extra_text = "\n\n".join(
            f"[二次检索] page {chunk.get('page', '?')} | {chunk.get('section', '')}\n"
            f"{chunk['content'][:900]}"
            for chunk in extra_chunks[:6]
        )
    prompt = f"""你是论文阅读助手。下面这份回答有部分引用只得到“部分支持”。
{instruction}
请改写回答：
1. 只保留证据能支持的结论；
2. 对证据不足的部分，明确写“证据不足”或“需要进一步核实”；
3. 不要引入新的引用或新的事实；
4. 保留仍然成立的 [n] 标记；
5. 如果二次检索证据能补全 partial，优先吸收它，但仍使用原有 [n] 标记。

原回答：
{answer}

部分支持的证据：
{evidence}

二次检索补充证据：
{extra_text or "(无)"}
"""
    repaired = await _complete(prompt, max_tokens=1600)
    return repaired or answer


def support_gate_message(rate: float | None, threshold: float, language: str) -> str:
    if language == "en":
        return (
            "Evidence is insufficient to display a reliable answer.\n\n"
            f"Citation support rate: {rate:.2f}; required threshold: {threshold:.2f}.\n"
            "Try a narrower question or select another paper."
        )
    return (
        "证据不足，暂不展示生成答案。\n\n"
        f"引用支持率：{rate:.2f}；要求阈值：{threshold:.2f}。\n"
        "建议缩小问题范围，或换一篇论文/补充更具体的章节。"
    )

def build_claim_checks(
    answer: str, citations: list[Citation]
) -> tuple[list[ClaimCheck], float | None]:
    """Split an answer into sentences and attach citation-level support."""
    claims: list[ClaimCheck] = []
    scored = 0.0
    total = 0
    for sentence in re.split(
        r"(?<=[。！？!?])|(?<=\.)(?=\s+[A-Z\u4e00-\u9fff])|\n+", answer
    ):
        text = sentence.strip().strip("#*- ").strip()
        if len(text) < 12 or text.startswith("|"):
            continue
        markers = list(
            dict.fromkeys(
                int(value)
                for value in re.findall(r"\[(\d+)\]", sentence)
                if 1 <= int(value) <= len(citations)
            )
        )
        if not markers:
            support = "uncited"
            reason = "该句没有引用"
        else:
            statuses = [citations[index - 1].support for index in markers]
            if all(status == "yes" for status in statuses):
                support = "yes"
                reason = "所有引用均支持"
            elif all(status == "no" for status in statuses):
                support = "no"
                reason = "所有引用均不支持"
            else:
                support = "partial"
                reason = "引用只支持部分内容"
        claims.append(
            ClaimCheck(
                claim=text[:500],
                citations=markers,
                support=support,
                reason=reason,
            )
        )
        total += 1
        scored += {"yes": 1.0, "partial": 0.5}.get(support, 0.0)
    rate = round(scored / total, 3) if total else None
    return claims, rate

