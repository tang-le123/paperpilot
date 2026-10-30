# PaperPilot

一个面向中英文论文的阅读助手：上传论文，选择一篇或多篇，用中文或英文提问，回答带页码和章节引用。

> 求职/面试材料：[一页纸](docs/ONE_PAGER.md) · [完整项目故事](docs/PORTFOLIO.md) · [深度设计与 all-in-rag 对应](docs/PROJECT_DEEP_DIVE.md) · [性能评估](docs/PERFORMANCE.md) · [解析/分块对比](docs/PARSING.md)

> 人工评测：[填表指南](docs/HUMAN_EVAL_GUIDE.md) · [评测结果](docs/EVAL_RESULTS.md)
## 当前能做什么

- 上传文本型 PDF、扫描版 PDF、DOCX、Markdown；
- 自动解析、按章节切块；
- 使用 `bge-m3` 建立多语言向量索引；
- 使用 BM25 + 向量 + RRF + `bge-reranker-base` 精排；
- 单篇 / 多篇问答；
- 按问题复杂度自动分流：内容问答 / 论文对比 / 创新点 / 术语解释 / 总结；
- 术语解释优先查本地 `knowledge/glossary.md`，区分“论文中的用法”和“通用解释”；
- 回答语言切换：中文 / English；
- 引用精确到论文、页码、章节，附原文片段；
- 引用可打开原文页截图并高亮段落；
- 引用逐条校验：支持 / 部分支持 / 不支持；
- partial 引用会触发二次检索 + 补证改写；
- claim 级检查：每句 yes / partial / no / uncited；
- 分节 map-reduce 总结 + 多篇综合；
- 论文章节大纲、重解析；
- React 单前端（唯一 UI）；
- 60 条分支评测集（含 11 篇真实论文、引用支持率）；
- Dockerfile + docker-compose。

## 架构

```text
React (Vite)
  → FastAPI（同一端口 8001 托管 React 静态文件）
      → 上传 / 论文库
      → 后台解析（pymupdf4llm / PDF / DOCX / Markdown / OCR）
      → 切块 + 页码元数据
      → bge-m3 Embedding
      → Chroma
      → 问答：BM25 + 向量 → RRF → Cross-Encoder → DeepSeek
      → 总结：分节 map → 单篇 reduce → 多篇综合
```

引用链接会打开：

```text
/api/v1/papers/{id}/page/{page}?chunk_id=...
```

返回带高亮的 PDF 页截图。

## 引用支持校验

回答中的每个 `[n]` 都会额外判断是否被对应 chunk 支持：

```text
yes      ✅ 已支持
partial  ⚠️ 部分支持
no       ❌ 不支持
unknown  ❔ 未校验
```

- 默认用一次批量 LLM 审核；
- LLM 不可用或解析失败时回退到词重合启发式；
- `ChatResponse.citations[].support` / `support_reason` 返回结果；
- `ChatResponse.claims` 返回句子级 claim；
- `claim_support_rate` 返回 claim 支持率；
- `citation_support_rate` 返回整体支持率；
- 低于 `CITATION_SUPPORT_THRESHOLD` 时不展示完整回答，只返回证据不足提示；
- `no` 的引用标记会被删除；
- `partial` 会触发一次补证改写；
- React 引用卡片显示对应标记。

> 这是辅助判断，不是形式化证明；`no` 应该人工复核或删除对应引用。

默认阈值：

```text
CITATION_SUPPORT_THRESHOLD=0.35
```

可写入 `.env` 调整。

### 人工校准

```powershell
cd E:\paperpilot
E:\paperpilot\.venv\Scripts\python.exe eval\export_citation_review.py
```

导出：

```text
eval/citation_review.csv
```

包含 LLM 判定、理由、原文片段，以及待填写的：

```text
human_support
human_notes
```

首轮人工复核：

```text
30 条
完全一致 24/30 = 80.00%
加权一致率 88.33%（yes=1, partial=0.5, no=0）
```

明细：

```text
eval/citation_review_filled.csv
eval/citation_review_summary.md
eval/citation_review_summary.json
```

### Verifier 回归

人工复核暴露了 6 类分歧，已加入一个小回归集：

```powershell
cd E:\paperpilot
E:\paperpilot\.venv\Scripts\python.exe eval\verifier_calibration.py
```

结果：

```text
6/6 = 100%
```

覆盖：

```text
标题/作者页不能当定义证据
只有部分子句支持 → partial
SOTA / exact 等强限定词缺失 → no 或 partial
多动作 claim 只覆盖一部分 → partial
```

结果文件：

```text
eval/verifier_calibration_result.json
```

## 检索优化

- 规则 query rewrite：定义 / 数值 / 方法 / 结果；
- 章节/元数据过滤：按题型限制 section；
- 多篇 per-paper 平衡取证；
- 预留 recall@k 评测。

评测工具：

```text
eval/retrieval_eval.py
eval/retrieval_gold_template.csv
eval/annotations_template.csv
eval/annotation_guidelines.md
eval/score_annotations.py
```

### 已测出的负结果

49 条有页码 gold 的检索对比：

```text
baseline：        recall@1 0.531 / recall@5 0.898 / MRR 0.662
rewrite-only：    0.531 / 0.898 / 0.662（没有提升）
rewrite + section：0.490 / 0.776 / 0.597（下降）
```

所以两个开关默认关闭：

```text
QUERY_REWRITE_ENABLED=false
SECTION_FILTER_ENABLED=false
```

这不是“没做”，而是测过之后没有把负优化留在默认链路里。

## 自适应路由

参考 Adaptive-RAG 的分流思路：

| 问题类型 | 策略 | 处理 |
|---|---|---|
| “这篇论文的方法是什么？” | `single` | 单篇/多篇内容检索 + 回答 |
| “比较这两篇论文” | `compare` | 每篇保底取证据 + 结构化对比 |
| “基于这些论文提出创新点” | `innovate` | 检索局限/未来工作 + 生成可验证想法 |
| “LASSO 是什么？” | `explain` | 论文用法 + 本地术语库解释 |
| “总结这篇论文” | `summary` | 分节 map-reduce 总结 |
| 只选一篇却要求对比 | `clarify` | 直接提示至少选两篇 |

请求里的 `mode` 可以手动覆盖：

```json
{"mode": "auto"}
```

`auto` 按问题自动判断；也可以固定为 `single`、`compare`、`innovate`、`summary`、`explain`。

术语解释可以关闭通用知识：

```json
{"allow_general_knowledge": false}
```

响应会返回：

```json
{"source_scope": "paper+glossary", "general_knowledge_used": false}
```

## 环境

项目使用独立 `.venv`，但复用了 `all-in-rag` 环境里的
`torch`、`sentence-transformers`、`chromadb` 等依赖。

模型路径在 `.env`：

```text
EMBEDDING_MODEL=E:/all-in-rag/models/bge-m3
RERANK_MODEL=E:/all-in-rag/models/bge-reranker-base
OCR_ENABLED=true
RERANK_ENABLED=true
RERANK_DEVICE=cpu
```

如果换机器，需要把模型复制到本地并修改 `.env`。

## MySQL

默认仍使用 SQLite；SQLite 已启用 WAL 和 `busy_timeout=5000`，适合当前单机后台索引与问答并发。MySQL 适配层保留但默认不启用。

如果以后确实要切 MySQL，在 `.env` 中改为：

```text
DB_BACKEND=mysql
MYSQL_HOST=127.0.0.1
MYSQL_PORT=3306
MYSQL_DATABASE=paperpilot
MYSQL_USER=paperpilot
MYSQL_PASSWORD=你的密码
```

后端会用 `pymysql` 连接，数据库不存在时自动创建（需要该用户有建库权限）。

把现有 SQLite 数据迁移到 MySQL：

```powershell
cd E:\paperpilot\backend
$env:DB_BACKEND='mysql'
E:\paperpilot\.venv\Scripts\python.exe scripts\migrate_sqlite_to_mysql.py
```

迁移内容包括：

```text
users
collections
papers
chunks
```

> 密码不要提交到 Git；`.env` 已在 `.gitignore` 中。

## 启动后端

```powershell
cd E:\paperpilot\backend
$env:PYTHONIOENCODING='utf-8'
E:\paperpilot\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8001
```

- API 文档：<http://127.0.0.1:8001/docs>
- 健康检查：<http://127.0.0.1:8001/health>

## 登录

本地首次启动会创建演示账号：

```text
demo / demo1234
```

也可以注册新账号。登录后论文和集合按 `owner_id` 隔离。

Access Token 默认 2 小时，Refresh Token 默认 30 天；前端会在 401 时自动刷新并重试。

可配置：

```text
ACCESS_TTL_SECONDS=7200
REFRESH_TTL_SECONDS=2592000
```

> 这是本地单机认证：PBKDF2 密码哈希 + 不透明 Bearer Token，不面向公网生产环境。

## 构建并启动 React 生产包

```powershell
cd E:\paperpilot\frontend_react
cmd /c "npm ci"
cmd /c "npm run build"

cd E:\paperpilot\backend
$env:PYTHONIOENCODING='utf-8'
E:\paperpilot\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8001
```

打开：<http://127.0.0.1:8001>

FastAPI 会自动托管 `frontend_react/dist`，所以只有 React，没有 Streamlit。

## 启动 React 开发服务器

```powershell
cd E:\paperpilot\frontend_react
cmd /c "npm install"
cmd /c "npm run dev"
```

打开：<http://127.0.0.1:5173>

开发模式下 React 通过 CORS 调用 `http://127.0.0.1:8001/api/v1`；生产构建由 FastAPI 同源托管。

## PyCharm 运行

1. 打开 `E:\paperpilot`
2. 解释器选 `E:\paperpilot\.venv\Scripts\python.exe`
3. 运行配置选 **PaperPilot One Click**

`.run/PaperPilot One Click.run.xml` 会：

```text
检查 frontend_react/dist
缺构建就先 npm run build
启动 FastAPI :8001
自动打开 http://127.0.0.1:8001
```

也可以单独运行 `PaperPilot API` 或 `PaperPilot Tests`。

## 测试

```powershell
cd E:\paperpilot
E:\paperpilot\.venv\Scripts\python.exe -m pytest -q
```

## 分支评测

```powershell
cd E:\paperpilot
E:\paperpilot\.venv\Scripts\python.exe eval\run_eval.py
```

评测覆盖：

```text
single     内容问答
compare    论文对比
innovate   创新点
summary    总结
explain    术语解释
clarify    单篇要求对比
```

结果写入 `eval/report.json`。

当前评测：

```text
60 条：30 条样例/中文真实论文 + 30 条 arXiv 真实论文
覆盖 11 篇真实论文（含中文 32 页论文 + 10 篇 arXiv）
覆盖 single / compare / innovate / summary / explain / clarify
citation_support_rate 由批量 LLM 审核计算，失败时回退到词重合启发式
```

最近一次：

```text
v1 门控：12/30，citation_support_rate ≈ 0.494
v2 @0.50：10/30，citation_support_rate ≈ 0.361，抑制率 66.7%
v2 @0.35：15/30，citation_support_rate ≈ 0.370，claim_support_rate ≈ 0.387
v2 @0.35 抑制率：46.7%（14/30）
```

人工对齐（0.35 跑出的引用与旧 30 条标签只能部分匹配）：

```text
匹配 25 条
完全一致 64.0%
加权一致率 82.0%
误杀代理指标：0/14（只表示被抑制 case 的已有人工引用标签没有全 yes，不是完整答案级评估）
```

阈值 0.35 比 0.50 少抑制 6 条，但支持率并没有实质提升；  
下一步应优化检索/claim 校验，而不是继续下调阈值。

`eval/citation_review.csv` 已导出 30 条引用，供人工填写：

```text
human_support
human_notes
```

## 评测论文

`eval/arxiv_sources.json` 记录了 10 篇 arXiv 开放论文（RAG / GraphRAG / RAGAS / CRAG / LightRAG / Agentic RAG 等），PDF 放在：

```text
data/samples/papers/
```

加上原有中文 32 页论文，真实评测覆盖 11 篇论文。评测题总数为 60。

## Docker

```powershell
cd E:\paperpilot
docker compose up --build
```

- API + React UI：<http://127.0.0.1:8001>
- 模型目录通过 `MODELS_DIR` 挂载，默认 `E:/all-in-rag/models`。

> Docker 采用多阶段构建：Node 构建 React，Python 镜像托管 `dist`，只有一个 8001 端口。
>
> 实际构建已在当前机器尝试；Docker Hub / 镜像下载速度过慢，未能在本轮完成。可用镜像参数：
>
> ```powershell
> docker build --build-arg NODE_IMAGE=docker.m.daocloud.io/library/node:22-alpine `
>   --build-arg PYTHON_IMAGE=docker.m.daocloud.io/library/python:3.12-slim `
>   --build-arg PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple `
>   -t paperpilot:latest .
> ```


## 使用流程

1. 左侧上传 PDF / DOCX / Markdown；
2. 等待状态从 `pending` 变成 `ready`；
3. 在论文库中选择论文；
4. 选择语言和分析模式；
5. 提问；
6. 展开引用查看页码、章节和原文片段，或打开高亮页；
7. 点“总结选中论文”生成单篇/多篇总结。

## API

| 方法 | 路径 | 作用 |
|---|---|---|
| POST | `/api/v1/auth/register` | 注册并获取 Token |
| POST | `/api/v1/auth/login` | 登录并获取 Token |
| POST | `/api/v1/auth/refresh` | 用 refresh token 换新 token |
| GET | `/api/v1/auth/me` | 当前用户 |
| GET | `/api/v1/collections` | 论文集合列表 |
| POST | `/api/v1/collections` | 新建论文集合 |
| PATCH | `/api/v1/collections/{id}` | 重命名集合 |
| DELETE | `/api/v1/collections/{id}` | 删除集合，论文移到其他集合 |
| POST | `/api/v1/papers/upload` | 上传论文（可带 `collection_id`） |
| GET | `/api/v1/papers` | 当前用户论文列表 |
| GET | `/api/v1/papers/{id}` | 论文详情 |
| GET | `/api/v1/papers/{id}/status` | 解析状态 |
| GET | `/api/v1/papers/{id}/sections` | 章节大纲 |
| POST | `/api/v1/papers/{id}/reindex` | 重新解析/索引 |
| DELETE | `/api/v1/papers/{id}` | 删除论文与索引 |
| GET | `/api/v1/papers/{id}/file` | 下载原文 |
| GET | `/api/v1/papers/{id}/page/{page}` | 页截图/高亮 |
| PATCH | `/api/v1/papers/{id}/collection` | 移动论文到集合 |
| POST | `/api/v1/chat` | 问答 |
| POST | `/api/v1/chat/stream` | SSE 流式问答 |
| POST | `/api/v1/summarize` | 总结 |

除 `/health`、`/docs`、`/auth/*` 外，接口需要：

```http
Authorization: Bearer <token>
```

问答请求：

```json
{
  "paper_ids": [1, 2],
  "question": "两篇论文的方法有什么区别？",
  "answer_language": "zh",
  "mode": "auto"
}
```

响应会多两个字段：

```json
{
  "strategy": "compare",
  "route_reason": "检测到论文对比线索"
}
```

## 当前限制

- 扫描版 PDF 使用 RapidOCR；OCR 速度和准确率取决于扫描质量；
- 双栏 PDF 和复杂公式可能解析不准；
- 参考文献会被标记，但不参与默认检索；
- 总结需要多次 LLM 调用，论文越长越慢；
- 单篇问答最多选 10 篇，总结最多 5 篇；
- 评测集 60 条，覆盖 11 篇真实论文，但仍不是大规模基准；
- 本地术语库只覆盖常见术语；未收录时“通用解释”需要人工核对；
- 认证是本地单机实现，Token 未加密存储、没有邮箱验证/找回密码/限流，不适合直接公网部署；
- 论文集合只支持新建和选择，暂不支持重命名/删除/移动；
- 流式回答首 token 前仍需等待检索和精排；
- MinerU/Marker 尚未安装，目前用 `pymupdf4llm` 做布局感知解析；
- Docker 镜像已尝试构建，因基础镜像下载速度过慢，尚未完成验证。

## 目录

```text
paperpilot/
├── backend/
│   └── app/
│       ├── main.py          # FastAPI 入口
│       ├── config.py        # 配置
│       ├── db.py            # SQLite 元数据
│       ├── parsing.py       # PDF/DOCX/MD 解析
│       ├── indexing.py      # Embedding、Chroma、BM25、RRF
│       ├── llm.py           # DeepSeek 问答与总结
│       ├── services.py      # 后台解析/索引
│       └── schemas.py       # Pydantic 模型
├── frontend_react/
│   ├── src/App.jsx
│   └── src/styles.css
├── eval/
│   ├── dataset.json
│   ├── run_eval.py
│   └── report.json
├── knowledge/
│   └── glossary.md          # 本地术语库
├── data/
│   ├── uploads/
│   ├── chroma/
│   └── papers.db
├── Dockerfile
├── docker-compose.yml
└── requirements.txt
```

## 下一步

1. 把本地认证升级为生产级：邮箱验证、找回密码、限流、Token 过期/刷新；
2. 用 PDF.js 在 React 内嵌原文跳转和段落高亮；
3. 安装 MinerU/Marker，替换 `pymupdf4llm` 作为可选高质量解析器；
4. 把评测扩到 10–20 篇真实论文，并增加人工引用核对；
5. 加 CI、前端测试和 Docker 实际构建验证。
