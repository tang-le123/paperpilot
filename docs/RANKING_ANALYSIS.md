# 排序质量分析与优化

## 1. 现象

49 条 retrieval gold：

```text
recall@1  = 0.531
recall@5  = 0.898
recall@10 = 0.918
```

## 2. 第一次命中的名次分布

| 首次命中名次 | 数量 | 占比 |
|---|---:|---:|
| 第 1 条 | 26 | 53.1% |
| 第 2–3 条 | 13 | 26.5% |
| 第 4–5 条 | 5 | 10.2% |
| 第 6–10 条 | 1 | 2.0% |
| 10 条以后 | 4 | 8.2% |

结论：

```text
18 / 49 = 36.7% 的题，gold 在第 2–5 条
→ 排序问题

5 / 49 = 10.2% 的题，gold 在第 6 条以后或没有
→ 召回/分块问题
```

不是“找不到”，主要是“没有排到第一”。

---

## 3. 根因判断

### 根因 A：reranker 输入被截断

当前：

```text
chunk ≈ 800 字符
bge-reranker-base 最大输入通常 512 token
```

中文 800 字符往往接近或超过 512 token。  
如果关键句在 chunk 后半段，reranker 可能根本没看到它。

这是最优先怀疑点。

### 根因 B：RRF 权重相等

```text
BM25 rank 1
向量 rank 10
→ 目前按同一个 RRF 权重融合
```

但论文场景中：

- 数值/术语题：BM25 重要；
- 同义改写/跨语言：向量重要。

固定等权不一定最优。

### 根因 C：候选池偏小

```text
candidates = max(top_k * 3, 12) = 18
```

如果 gold 在 18 名之后，reranker 没机会看到。

### 根因 D：chunk 粒度

```text
800 字符固定切分
```

- 公式/表格被切断；
- 同一页多个 chunk，gold 页命中但 chunk 不是最相关；
- 没有 parent-child。

### 根因 E：page-level gold 太粗

当前 `gold_pages` 只要求命中页，不要求命中具体 chunk。  
这会高估召回，也会让“第一条命中”看起来比实际更差/更好。

---

## 4. 优化顺序

### P0：修 reranker 截断

把每个候选 chunk 切成窗口：

```text
section 标题 + chunk 内容
→ 每 500 字一个窗口
→ 每个窗口单独打分
→ 取 max
```

这样关键句在 chunk 后半段也能被看到。

预期：修复一部分“gold 在第 2–5 条”的案例。

### P1：加权 RRF

```text
score = w / (60 + dense_rank)
      + (1-w) / (60 + bm25_rank)
```

在 49 条 gold 上网格搜索：

```text
w = 0.3 / 0.5 / 0.7
```

不要一次调太多参数。

### P1：候选池扩大

```text
18 → 30 或 40
```

只看 recall@1 是否提升，同时记录延迟。

### P2：parent-child chunk

```text
child 400–600 token 检索
parent 章节上下文送生成
```

### P2：section soft boost

不要 hard filter（已证明会掉召回）。  
在 reranker 输入中加 section 标题，或者给同 section 候选小加权。

---

## 5. 验收标准

```text
recall@1 ≥ 0.65
recall@5 ≥ 0.93
recall@5 不能下降
citation_precision ≥ 0.70
```

每次只改一个变量，49 条 gold 上对比：

```text
baseline
→ P0 reranker window
→ P1 weighted RRF
→ P1 candidate 30
→ P2 parent-child
```

如果某一项没有提升，就回退，不要叠加。

---

## 6. 本轮实验结果（49 条 gold）

| 方案 | recall@1 | recall@5 | recall@10 | MRR |
|---|---:|---:|---:|---:|
| baseline（原 reranker + RRF 0.5） | 0.531 | 0.898 | 0.918 | 0.662 |
| window reranker + RRF 0.5 | 0.531 | 0.878 | 0.918 | 0.686 |
| window reranker + RRF 0.7 | 0.531 | 0.878 | 0.918 | 0.686 |
| window off + section prefix | 0.510 | 0.878 | 0.918 | 0.656 |
| window off + no prefix（最终） | 0.531 | 0.898 | 0.918 | 0.662 |

结论：

```text
window：MRR 升但 recall@5 下降，不采用
section prefix：recall@1/@5 都下降，不采用
RRF 0.5/0.7：完全一样，说明 reranker 主导
```

最终默认：

```text
RERANK_WINDOW_ENABLED=false
RERANK_SECTION_PREFIX=false
RRF_DENSE_WEIGHT=0.5
RRF_LEXICAL_WEIGHT=0.5
```

RRF 权重在 0.5 和 0.7 下结果完全一样，说明当前 reranker 对最终顺序影响更大。

下一步不要继续在这两个开关上堆参数，转向：

```text
1. parent-child chunk
2. 更强的 reranker / 领域微调
3. 用 chunk-level gold 复核 page-level gold
```

---

## 7. Chunk 大小对比

同一批 49 条 gold，固定 reranker 默认配置：

| chunk | overlap | recall@1 | recall@5 | recall@10 | MRR |
|---|---:|---:|---:|---:|---:|
| 800 | 100 | 0.531 | 0.898 | 0.918 | 0.662 |
| 1200 | 150 | 0.490 | 0.898 | 0.939 | 0.663 |
| 1200 + RRF 0.7 | 150 | 0.490 | 0.898 | 0.939 | 0.663 |

结论：

```text
chunk 调大：
  recall@10 +2.1pp
  recall@5 持平
  recall@1 -4.1pp
→ 不采用 1200，恢复 800
```

原因：

- 大 chunk 覆盖更多内容，@10 变好；
- 但单个 chunk 主题更杂，reranker 更难把“精确证据”排第一；
- RRF 权重在 1200 上仍然没有影响，说明排序主要由 reranker 决定。

最终恢复：

```text
CHUNK_SIZE=800
CHUNK_OVERLAP=100
```
