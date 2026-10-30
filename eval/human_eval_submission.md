# 人工评测填写交付说明

输出目录：`E:\all-in-rag\eval_outputs\`

## 生成的文件

- `retrieval_gold_template.csv`：60 行 gold，49 行已填页码，11 行按指南留空（对比/创新/总结/澄清类，无单一 gold 页）。
- `retrieval_gold.json`：用上面的 CSV 直接生成，供 recall 计算。
- `annotations.csv`：120 行双人标注（A/B 各 60 行）已填完。

## 怎么用

```powershell
Copy-Item E:\all-in-rag\eval_outputs\retrieval_gold_template.csv E:\paperpilot\eval\retrieval_gold_template.csv -Force
Copy-Item E:\all-in-rag\eval_outputs\annotations.csv E:\paperpilot\eval\annotations.csv -Force

cd E:\paperpilot
E:\paperpilot\.venv\Scripts\python.exe eval\build_retrieval_gold.py
E:\paperpilot\.venv\Scripts\python.exe eval\score_annotations.py
```

## 必须复核/注意的点

1. **我无法真正运行你的后端**（沙箱禁网、且无 E:\paperpilot 写权限），所以原来为空的 30 个
   `answer_preview`/`citations` 是我根据样例论文和《统计建模》论文自己写的草稿，不是系统真实输出。
   你应当在 UI 里按 `paper_keys + question` 重新补跑这 30 条，再覆盖对应单元格。

2. **gold 页码是草稿**：s*/r* 和样例论文能核对；p01–p30 的 arXiv 题是按论文正文关键词定位的，
   `notes` 里标了“页码待复核”的请打开原文再确认。对比/创新/总结类按指南留空，不进入 recall。

3. **A/B 都是我填的**，本质是同一来源，因此 `cohen_kappa` 会虚高（接近 1.0），没有真实测量意义。
   真正跑分前建议找另一位同学独立填 B 列。

4. 指南核心规则“gold 独立于模型输出”我已遵守：gold 页码来自论文原文，不是从 answer_preview 反填。

## 中间产物

`E:\all-in-rag\_eval\txt\` 是我抽取的论文正文（每页带 `===== PAGE n =====`），
`_eval\search_p.py`、`_eval\build_outputs.py` 是定位页码和生成 CSV 的脚本，供你复核时参考。
