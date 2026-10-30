# 人工标注规范

## 目标

建立 100–200 条**答案级 + 引用级** gold，用于：

```text
retrieval recall@k
citation precision
answer correctness
false suppression
双人标注 + Cohen's kappa
```

## 1. 检索 gold

文件：`eval/retrieval_gold_template.csv`

字段：

```text
id
paper_keys
question
gold_pages       # 允许的页码，多个用 |
gold_chunk_ids   # 如果能定位到 chunk，多个用 |
notes
```

填写规则：

- 只填“回答这个问题必须看到的证据”；
- 不要求填满所有相关页；
- 没有明确证据就留空，不要猜。

## 2. 答案/引用标注

从模板开始：

```text
eval/annotations_template.csv
```

当前是 120 个标注位（60 题 × 2 标注者），但**human 字段是空的**，需要人工填写，不能把模板当 gold。

字段：

```text
case_id, annotator, answer_correct, citation_support, suppressed, should_answer
```

- `annotator`：A / B
- `answer_correct`：0/1
- `citation_support`：yes / partial / no
- `suppressed`：0/1
- `should_answer`：0/1

规则：

- 两个标注者独立标注；
- 先看问题，再看答案，最后看引用；
- `partial` 只在证据支持一部分结论时使用；
- `no` 包括“引用无关”和“引用页码对但内容不支持”；
- 对 `suppressed=1`，要判断原问题是否本应回答，用于计算误杀。

## 3. 统计

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

## 4. 规模建议

```text
至少 100 条答案级
至少 200 条引用级
2 个标注者
分歧样本第三人仲裁
```

少于 100 条时，不要用百分比下强结论。
