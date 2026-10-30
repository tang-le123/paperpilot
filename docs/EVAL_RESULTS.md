# PaperPilot 评测结果汇总

## 输入

```text
评测题库：eval/dataset.json（60 条）
检索 gold：eval/retrieval_gold.json（49 条有页码/块）
人工标注：eval/annotations.csv（60 题 x A/B = 120 行）
```

未标注的 11 条是对比、创新、总结、澄清类，没有单一 gold 页，不进入 recall。

---

## 1. 答案与引用指标

来自 `eval/score_annotations.py`：

| 指标 | 结果 |
|---|---:|
| answer_accuracy | 0.750 |
| citation_precision | 0.550 |
| suppressed | 14 / 60 |
| suppressed_answerable | 14 / 60 = 23.3% |
| false_suppression | 0 |
| Cohen's kappa | 1.000 |

解释：

- `answer_accuracy`：75% 的答案被标为正确；
- `citation_precision`：yes=1 / partial=0.5 / no=0 的加权结果；
- 14 条被门控，且都标为“本应回答”；
- `false_suppression=0`：被抑制的展示答案被标为不正确，不能算误杀正确答案；
- `kappa=1.000`：A/B 两套标签完全一致，只能说明标签一致，不等于独立人工验证。

---

## 2. Recall@k（49 条 gold）

| 模式 | recall@1 | recall@5 | recall@10 | MRR |
|---|---:|---:|---:|---:|
| baseline | 0.531 | 0.898 | 0.918 | 0.662 |
| rewrite-only | 0.531 | 0.898 | 0.918 | 0.662 |
| rewrite + section | 0.490 | 0.776 | 0.816 | 0.597 |

18 条旧 gold 的子集结果：

| 模式 | recall@1 | recall@5 | recall@10 | MRR |
|---|---:|---:|---:|---:|
| baseline | 0.722 | 1.000 | 1.000 | 0.833 |
| rewrite-only | 0.722 | 1.000 | 1.000 | 0.833 |
| rewrite + section | 0.667 | 0.778 | 0.778 | 0.713 |

结论：

```text
query rewrite 没有提升
section filter 明显掉召回
默认关闭两者：
QUERY_REWRITE_ENABLED=false
SECTION_FILTER_ENABLED=false
```

---

## 3. 阈值

当前：

```text
CITATION_SUPPORT_THRESHOLD=0.35
```

30 条 arXiv 子集：

```text
v2 @0.50：10/30，support 0.361，抑制率 66.7%
v2 @0.35：15/30，support 0.370，抑制率 46.7%
```

注意：这两组不是 60 条全量。

---

## 4. 结论

```text
answer_accuracy 0.750
citation_precision 0.550
recall@5        0.898
recall@1        0.531
```

不是“效果很好”：

- 引用精度只有 0.55；
- 14 条被门控；
- recall@1 只有 0.531，排序仍不够好；
- kappa 1.0 不能当作独立双人结论。

可以说明：

```text
检索前 5 条覆盖 89.8% 的 gold
但第一条命中率只有 53.1%
主要瓶颈是排序和引用支持，不是数据库
```

---

## 5. 建议

1. 保持 rewrite / section 默认关闭；
2. 优先做 parent-child chunk、相邻块扩展、reranker 优化；
3. 把 recall@5 目标设到 0.90+，recall@1 目标 0.65+；
4. 重新设计 false suppression：保留原始答案，不能只看门控后的文本；
5. 让第二位标注者独立填 B，重新计算 kappa。

---

## 6. 边界

```text
单机
60 题
49 条 gold
当前主要是本地原型评测
```

不能据此宣称生产准确率、跨领域泛化或多用户性能。
