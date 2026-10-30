# 引用支持人工复核结果

- 样本：30 条
- 完全一致：24/30 = 80.00%
- 加权一致率（yes=1, partial=0.5, no=0）：88.33%

## 混淆矩阵

| LLM \ 人工 | yes | partial | no |
|---|---:|---:|---:|
| yes | 10 | 2 | 1 |
| partial | 0 | 14 | 3 |
| no | 0 | 0 | 0 |

## 分歧

- `p02` citation 1: LLM=yes, 人工=no — 片段只说 FEVER 差 4.3%，不支持 SOTA 结论
- `p04` citation 1: LLM=partial, 人工=no — 片段只有标题和作者，没有 Ragas 定义
- `p04` citation 3: LLM=yes, 人工=partial — 支持无参考/集成，但未完整支持全称与自动框架
- `p06` citation 1: LLM=partial, 人工=no — 只有标题作者，不支持 Ragas 特点
- `p08` citation 1: LLM=yes, 人工=partial — 支持自我修正，未支持 decompose 与三类动作
- `p11` citation 4: LLM=partial, 人工=no — 只支持风险提示，不支持具体误用机制

> 人工标签为本次逐条复核结果；部分样本的 answer_preview 已被阈值抑制，备注中按原引用证据判断。
