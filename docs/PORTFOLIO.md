# PaperPilot：一个可验证引用的论文阅读 RAG 助手

> 面试一句话：
>
> **我做的不是一个“套壳 ChatGPT”，而是一个能对论文问题分流、检索证据、校验引用、在证据不足时拒绝回答的科研阅读助手。**

---

## 1. 30 秒版本（给 HR）

PaperPilot 面向“读论文”这个具体场景：

- 上传 PDF / DOCX / Markdown；
- 选择一篇或多篇论文；
- 用中文或英文提问；
- 回答必须带页码、章节和原文引用；
- 引用会逐条校验：支持 / 部分支持 / 不支持；
- 证据不足时，不让模型硬答。

它解决的不是“能不能生成”，而是：

> **生成的内容到底有没有论文证据支撑。**

---

## 2. 我发现了什么问题

普通 RAG 的做法是：

```text
问题 → 检索 Top-K → 交给大模型 → 生成答案
```

看起来很完整，但实际有三个问题：

1. **问题类型不同，检索策略不应该一样**
   - “这篇论文的方法是什么？”是单跳问答；
   - “比较两篇论文”需要每篇都有证据；
   - “提出创新点”需要局限、未来工作、研究空白；
   - “LASSO 是什么？”需要定义，不一定是论文内容；
   - “总结”需要 map-reduce。

2. **有引用 ≠ 引用支持结论**
   - 模型可能引用一个只出现过关键词的 chunk；
   - 引用页码对，但原文不支持这句话；
   - 多篇对比时，证据可能全部来自同一篇论文。

3. **没有评测，就无法判断改动是否真的有效**
   - 只测“能不能返回 200”没有意义；
   - 需要测策略、页码、引用支持、拒答和延迟。

---

## 3. 我的方案

### 3.1 自适应路由

规则路由，不额外调用 LLM：

```text
single     内容问答
compare    论文对比
innovate   创新点
explain    术语解释
summary    总结
clarify    条件不足
```

选择规则路由的原因：

- 延迟低；
- 可解释；
- 可测试；
- 对当前任务足够；
- 不为了“像 Agent”而增加复杂度。

### 3.2 混合检索

```text
query
├── BM25（jieba）
└── bge-m3 + Chroma 向量检索
        ↓
      RRF
        ↓
bge-reranker-base 精排
        ↓
Top-K 证据
```

多篇对比/创新点使用 **per-paper balanced retrieval**：

```text
每篇论文至少保留候选
→ 合并
→ 精排
```

避免全部证据来自一篇论文。

### 3.3 引用支持校验

这是项目最核心的差异化。

```text
答案
→ 找到 [1] [2] 对应的句子
→ 与引用 chunk 的原文片段配对
→ 批量 LLM 审核
→ yes / partial / no
```

处理策略：

```text
no       删除引用标记
partial  二次检索补充证据 + 补证改写
低于阈值 不展示完整答案，只提示证据不足
```

### 3.4 Claim 级检查

除了引用，还会把回答拆成句子级 claim：

```text
每个句子 → 对应引用 → yes / partial / no / uncited
claim_support_rate
```

这样可以发现“没有引用的句子”和“引用只覆盖部分句子”的问题。

不是“让模型再检查一遍”，而是把引用变成**可计算的质量指标**。

### 3.4 评测驱动

```text
eval/dataset.json
eval/run_eval.py
eval/citation_review_filled.csv
eval/verifier_calibration.py
```

评测不只看通过率，还看：

```text
strategy accuracy
page hit
keyword hit
citation support rate
suppression rate
latency
```

---

## 4. 关键数据

| 指标 | 结果 |
|---|---|
| 论文 | 14 篇（含 10 篇 arXiv、1 篇 32 页中文论文） |
| 评测题 | 60 条 |
| 策略 | single / compare / innovate / explain / summary / clarify |
| 原始评测 | 30/30（未开引用门控，标准过宽） |
| v1 门控 | 12/30，支持率约 0.494 |
| v2 严格门控 @0.50 | 10/30，支持率 0.361，抑制率 66.7% |
| v2 门控 @0.35 | 15/30，支持率 0.370，claim 支持率 0.387，抑制率 46.7% |
| 人工复核 | 30 条，完全一致 24/30 = 80% |
| 加权一致率 | 88.33% |
| Verifier 回归 | 6/6 |
| 单元测试 | 9 passed |
| 前端 | React 单前端，FastAPI 同端口托管 |
| 流式 | SSE token 流，final 事件带引用与支持率 |

我特意保留了一个“不好看”的数字：

> **v2 @0.50 只有 10/30 通过，20/30 被抑制；降到 0.35 后 15/30 通过、14/30 被抑制。**

另外，检索召回对比也得出了负结果：

```text
49 条 gold：
baseline recall@5 = 0.898
rewrite-only recall@5 = 0.898
rewrite + section filter recall@5 = 0.776
```

所以 rewrite 和 section filter 默认关闭，没有把负优化留在主链路。

这不是系统退步，而是三个事实同时暴露：

1. 原来“有引用就算通过”的评测太宽松；
2. v2 太严格，0.35 只是减少误杀，并没有真正提升支持率；
3. 章节过滤在当前 chunk/标题质量下会丢召回。

人工对齐（旧 30 条标签与 0.35 新结果匹配 25 条）：

```text
完全一致 64.0%
加权一致率 82.0%
误杀代理指标 0/14
```

误杀代理指标不是完整答案级人工评估，只说明被抑制 case 的已有人工引用标签没有“全 yes”。

---

## 5. 工程亮点

### 不是 demo，而是完整闭环

```text
上传
→ 解析
→ 切块
→ 索引
→ 检索
→ 精排
→ 路由
→ 回答
→ 引用
→ 引用校验
→ 评测
→ 前端展示
```

### 有取舍

- **SQLite**：单机、低运维、WAL；不是无脑上 MySQL。
- **Reranker CPU**：避免和 bge-m3 抢 6GB 显存。
- **规则路由**：不为 Agent 而 Agent。
- **门控**：宁可拒答，也不展示高风险引用。
- **兜底**：reranker、LLM、verifier 失败都有降级路径。

### 有产品意识

- 登录 / 注册 / Token 刷新；
- 论文集合；
- 集合重命名、删除、移动论文；
- 引用原文页高亮；
- React 单端口部署；
- SSE 流式回答。

---

## 6. 简历 bullet

### 中文版

- 独立设计并实现 PaperPilot 论文阅读 RAG 系统，支持 PDF/DOCX/Markdown 解析、混合检索、跨论文对比、术语解释与流式问答。
- 设计基于问题复杂度的 6 路自适应路由，将内容问答、论文对比、创新点、术语解释、总结和条件不足分流处理。
- 构建 BM25 + bge-m3 + RRF + bge-reranker 的混合检索链路，并为多篇任务实现 per-paper 平衡取证。
- 设计引用支持校验与门控机制：逐条判断引用是否支持答案，删除不支持引用，低支持率回答自动降级为“证据不足”。
- 建立 60 条评测集和 30 条人工引用复核集，完成 verifier 回归测试；当前人工一致率 80%，加权一致率 88.33%。

### 英文版

- Built PaperPilot, an evidence-grounded RAG assistant for paper reading, with PDF/DOCX/Markdown ingestion, hybrid retrieval, cross-paper comparison, term explanation, and streaming answers.
- Designed a six-way adaptive router for single-hop QA, comparison, innovation, explanation, summarization, and clarification.
- Implemented hybrid retrieval with BM25, bge-m3, RRF, and bge-reranker, plus per-paper balanced evidence retrieval for multi-paper tasks.
- Built a citation-support verifier and gate that removes unsupported citations and suppresses answers below a support threshold.
- Created a 60-question evaluation suite and a 30-item human citation review; achieved 80% exact and 88.33% weighted agreement, with a 6/6 verifier regression set.

---

## 7. 2 分钟演示脚本

```text
1. 登录 demo 账号
2. 选择中文论文，问：“这篇论文的主要方法是什么？”
3. 展示回答、页码、引用卡片
4. 问：“LASSO 是什么？”
5. 展示“论文中的用法”和“术语库解释”
6. 展示引用支持徽章：✅ / ⚠️ / ❌
7. 展示低支持率时被门控为“证据不足”
8. 选两篇论文，问：“比较这两篇论文的方法”
9. 展示 per-paper 证据和对比表
10. 新建集合、移动论文
11. 展示流式输出
```

---

## 8. 面试问答

### Q：为什么不用 Agent？

> 当前问题不需要多步工具调用。路由 + 检索 + 校验已经能解决；上 Agent 会增加延迟和调试成本。  
> 如果要做“查论文 + 查术语库 + 查网页 + 交叉验证”，再上 Agent 更合理。

### Q：为什么用 SQLite？

> 单机、单用户、写少读多，SQLite + WAL 足够。MySQL 适配层也写了，但当前不引入额外运维。  
> 如果多人/公网/多副本，再切 MySQL。

### Q：Reranker 为什么放 CPU？

> bge-m3 已经占 GPU，6GB 显存下同时放 reranker 容易 OOM；CPU 延迟可接受，稳定优先。

### Q：引用支持率只有 0.49，项目是不是不行？

> 这恰好说明评测有效。之前“有引用就算过”是假通过；现在能量化“引用是否支持结论”。  
> 下一步是二次检索和 claim 级校验，而不是把阈值调低。

### Q：怎么防止幻觉？

> 三层：
> 1. 检索只给证据；
> 2. Prompt 要求证据不足要说明；
> 3. 生成后逐条引用校验，低于阈值拒答。

### Q：最大的技术难点？

> 不是接模型，而是把“引用可信度”变成可评测、可门控、可回归的工程指标。

---

## 9. 当前不足（要主动说）

- 人工复核只有 30 条，且是单标注者；
- 10 篇 arXiv + 1 篇中文论文，规模仍小；
- 门控会误杀一部分正常回答；
- Docker 镜像未完成构建；
- PDF.js 内嵌阅读器还没做；
- 认证是本地单机实现，不是生产级。

> 主动说不足，比假装完美更加分。

---

## 10. 下一步路线

```text
1. verifier v2 重跑 30 条，统计抑制率与误杀
2. partial claim 二次检索（已实现基础版）
3. claim 级校验（已实现基础版）
4. 100 条双人标注
5. 按策略调阈值
6. 检索/解析优化
7. PDF.js + 引用跳转
8. 生产级认证
```

---

## 11. 项目定位

这不是“又一个 RAG Demo”。

它体现的是：

```text
能把问题拆清楚
能设计取舍
能建立评测
能承认指标不好
能定位下一步
```

对实习面试来说，这比“用了多少框架”更重要。
