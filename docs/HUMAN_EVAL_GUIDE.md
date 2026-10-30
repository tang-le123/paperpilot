# PaperPilot 人工评测指南

> 你负责标注，我负责跑分。  
> 所有路径都在 `E:\paperpilot` 下。

---

## 0. 总览

需要填两个文件：

| 文件 | 行数 | 作用 |
|---|---:|---|
| `eval/retrieval_gold_template.csv` | 60 | 每个问题“应该检索到哪一页/哪一块” |
| `eval/annotations_workbook.csv` | 120 | 60 题 × 2 个标注者，判断答案和引用 |

填完后生成：

```text
eval/retrieval_gold.json
eval/annotations.csv
```

然后跑：

```text
recall@1/5/10
citation precision
answer correctness
false suppression
Cohen's kappa
```

---

# A. 填 60 条 retrieval gold

## A1. 文件

打开：

```text
E:\paperpilot\eval\retrieval_gold_template.csv
```

字段：

```csv
id,paper_keys,question,gold_pages,gold_chunk_ids,notes
```

- `id`：不要改；
- `paper_keys`：不要改；
- `question`：不要改；
- `gold_pages`：你填；
- `gold_chunk_ids`：可选；
- `notes`：可选。

当前状态：

```text
60 行
18 行已有页码（来自旧 dataset）
42 行待填
```

> 已填的 18 行也要复核，不要默认正确。

---

## A2. gold page 是什么

定义：

> **回答这个问题必须看到的证据页。**

不是：

```text
✗ 模型回答里引用的页码
✗ 论文第一页
✗ 随便能搜到关键词的页
```

要打开论文自己确认。

---

## A3. 怎么找页码

### 单篇论文

打开 React：

```text
http://127.0.0.1:8001
```

登录：

```text
demo / demo1234
```

在论文库选择对应论文，问 CSV 里的 `question`，看引用页；再打开原文确认证据是否真的在那页。

也可以直接打开 PDF：

```text
data/uploads/...
```

或在引用卡片点“打开原文页（高亮）”。

### 多篇论文

`paper_keys` 有多个时，分别确认每篇的证据页。

注意：

> 当前 `gold_pages` 只存页码，不区分论文。  
> 多篇题最好填 `gold_chunk_ids`，否则 page 1 可能被两篇论文同时命中，recall 会偏高。

---

## A4. 填法

单页：

```text
20
```

多页：

```text
20|21
```

chunk id：

```text
p4_c0034|p4_c0035
```

示例：

```csv
r05,2026统计建模,LASSO 模型的 R² 是多少？,20|21,,R² 在结果表
p01,rag_lewis_2005.11401,RAG 模型由哪两部分记忆组成？,1|2,,abstract + method
```

### 填不了怎么办

如果问题本身不可回答，或没有明确证据页：

```text
gold_pages 留空
notes 写“不可回答 / 无单一 gold 页”
```

这一行不会进入 recall 计算；不要硬填。

---

## A5. 生成 JSON

```powershell
cd E:\paperpilot
E:\paperpilot\.venv\Scripts\python.exe eval\build_retrieval_gold.py
```

输出：

```text
eval/retrieval_gold.json
```

只包含填了 `gold_pages` 或 `gold_chunk_ids` 的行。

---

## A6. 跑 recall@k

### 当前链路

```powershell
E:\paperpilot\.venv\Scripts\python.exe eval\retrieval_eval.py `
  --out eval\retrieval_report_rewrite.json
```

### 基线

```powershell
E:\paperpilot\.venv\Scripts\python.exe eval\retrieval_eval.py `
  --no-rewrite --out eval\retrieval_report_baseline.json
```

### 只开 rewrite

```powershell
E:\paperpilot\.venv\Scripts\python.exe eval\retrieval_eval.py `
  --rewrite-only --out eval\retrieval_report_rewrite_only.json
```

### 只开 section filter

```powershell
E:\paperpilot\.venv\Scripts\python.exe eval\retrieval_eval.py `
  --section-only --out eval\retrieval_report_section_only.json
```

输出：

```text
recall@1
recall@5
recall@10
MRR
```

### 当前 18 条已知结果

```text
baseline:       recall@1 0.722 / recall@5 1.000 / MRR 0.833
rewrite-only:   recall@1 0.722 / recall@5 1.000 / MRR 0.833
rewrite+section: 0.667 / 0.778 / 0.713
```

结论：

```text
rewrite 暂无提升
section filter 明显掉召回
```

所以 section filter 默认关闭：

```text
SECTION_FILTER_ENABLED=false
```

---

# B. 填 120 个双人标注

## B1. 文件

打开：

```text
E:\paperpilot\eval\annotations_workbook.csv
```

字段：

```csv
case_id,question,paper_keys,answer_preview,citations,suppressed,
annotator,answer_correct,citation_support,should_answer,notes
```

当前：

```text
60 题 × 2 人 = 120 行
30 个 case 已有当前回答预览（60 行）
30 个 case 需要你在 UI 补跑（60 行）
```

如果之后重新跑了完整 60 条评测，可刷新回答预览：

```powershell
cd E:\paperpilot
E:\paperpilot\.venv\Scripts\python.exe eval\build_annotation_workbook.py
```

---

## B2. 谁填

```text
A 标注者：填 annotator=A 的 60 行
B 标注者：填 annotator=B 的 60 行
```

要求：

- A/B 独立；
- 不要互相看；
- 不要一个人填两边；
- 否则 kappa 没有意义。

---

## B3. 每列怎么填

### answer_correct

```text
1 = 核心答案正确
0 = 错误、答非所问、明显缺少核心结论
```

只看答案，不因为引用缺失就判 0。

### citation_support

```text
yes     = 引用支持整段核心结论
partial = 只支持一部分，或需要推断
no      = 引用不支持 / 无关
```

### suppressed

系统预填：

```text
1 = 回答被门控
0 = 正常展示
```

不要改。  
如果 `answer_preview` 是空的，需要先在 UI 跑一遍再确认。

### should_answer

```text
1 = 论文里有答案，问题本身成立
0 = 论文没有答案 / 问题不成立
```

用于计算误杀：

```text
false_suppression = suppressed=1 AND should_answer=1
```

### notes

写一句原因，例如：

```text
引用页对，但原文只提到 LASSO，没有 R²
```

---

## B4. 怎么补跑缺失的 30 条

打开：

```text
http://127.0.0.1:8001
```

登录 `demo / demo1234`，按照：

```text
paper_keys → 选择论文
question   → 原样提问
```

把：

```text
answer_preview
citations
suppressed
```

补进 `annotations_workbook.csv` 对应行。

---

## B5. 另存为 annotations.csv

关闭 Excel/WPS 后：

```powershell
Copy-Item `
  E:\paperpilot\eval\annotations_workbook.csv `
  E:\paperpilot\eval\annotations.csv `
  -Force
```

然后填 `annotations.csv`，不要直接改 workbook 副本。

---

## B6. 跑分

```powershell
cd E:\paperpilot
E:\paperpilot\.venv\Scripts\python.exe eval\score_annotations.py
```

输出：

```text
answer_accuracy
citation_precision
false_suppression
cohen_kappa
```

Kappa 解释：

```text
< 0.4        差
0.4–0.6      中等
0.6–0.8      较好
> 0.8        很好
```

---

# C. 用 gold 校准阈值

先不要调阈值。  
顺序：

```text
填完 60 条 retrieval gold
→ 填完 120 个双人标注
→ 得到 answer_accuracy
→ 得到 citation_precision
→ 得到 false_suppression
→ 再比较 0.35 / 0.50
```

判定标准：

```text
false_suppression < 10%
citation_precision 尽量高
answer_accuracy 不下降
```

如果 0.35 只是让更多回答通过，但 answer_accuracy 没提升，就不算有效校准。

---

# D. Unstructured 什么时候引入

先看 recall@k。

```text
如果相同 gold 下 pymupdf4llm 的 recall@5 明显低
→ 选 10 篇双栏/表格论文
→ 做 pymupdf4llm vs Unstructured A/B
→ 比较标题、阅读顺序、表格、recall
→ 只有 recall 提升才换默认解析器
```

不要因为“Unstructured 很有名”就直接替换。

详见：

```text
docs/PARSING.md
```

---

# E. 你需要交回什么

最低交付：

```text
1. eval/retrieval_gold_template.csv 填完 42 条
2. eval/annotations.csv 填完 120 行
```

可选：

```text
3. 每个争议样本在 notes 写一句原因
4. 保留 A/B 两套原始文件，不要互相覆盖
```

---

# F. 时间估算

```text
60 条 retrieval gold：约 45–90 分钟
120 条双人标注：约 2–3 小时（两个人各 1–1.5 小时）
```

不要一次填完 120 条；建议按 10 题一批，避免疲劳导致标签漂移。

---

# G. 最重要的一句话

> **gold 必须独立于模型输出。**  
> 不要拿当前引用反填 gold，否则 recall@k 和 kappa 都会变成自证。
