# 解析与分块：pymupdf4llm vs Unstructured

## 结论

Unstructured 适合做**元素识别和结构提取**，不适合被当成“万能 chunk 器”直接替换现有链路。

推荐：

```text
Unstructured 负责识别 Title / NarrativeText / Table / ListItem
→ 自研 token / parent-child chunk
→ 保留 page / section / bbox
```

而不是：

```text
partition_pdf → chunk_by_title → 直接入库
```

---

## Unstructured 能解决什么

- PDF / DOCX / HTML / PPTX 统一 element 输出；
- 标题、段落、列表、表格等元素类型；
- `chunk_by_title` 按标题聚合；
- 保留页码、坐标、父级标题等 metadata；
- `hi_res` 能处理更复杂版式。

对论文场景有价值的是：

```text
Title
NarrativeText
Table
ListItem
PageNumber
```

---

## 它的代价

- `hi_res` 依赖布局模型/OCR，安装和运行都重；
- 首次模型下载大；
- 扫描件慢；
- 公式、跨页表格仍然不保证；
- `chunk_by_title` 可能产生过长 chunk；
- 不同版本的 API/依赖变化较快；
- 仍然需要自己做 token 预算和检索评测。

所以：

> Unstructured 解决“文档结构”，不解决“检索命中”和“引用支持”。

---

## 对比

| 维度 | pymupdf4llm（当前） | Unstructured |
|---|---|---|
| 安装 | 轻 | 重，可选依赖多 |
| 阅读顺序 | 较好 | `hi_res` 较好，`fast` 一般 |
| 表格 | 一般 | 元素级更好，但仍需校验 |
| 公式 | 弱 | 弱 |
| 页码/元数据 | 有 | 有 |
| 速度 | 快 | `hi_res` 慢 |
| 适合 | 默认解析 | 复杂版式/结构化抽取 |

---

## 建议路线

1. 保持 `pymupdf4llm` 作为默认解析；
2. 增加 `PARSER=unstructured` 可选开关；
3. 在 10 篇双栏/表格论文上比较：
   - 标题识别
   - 阅读顺序
   - 表格完整性
   - chunk 数量
   - recall@k
4. 只有 recall 提升才切换默认解析器。

---

## 当前分块问题

```text
CHUNK_SIZE=800 字符
CHUNK_OVERLAP=100 字符
```

问题：

- 字符不是 token；
- 跨语言长度不稳定；
- 公式/表格被切断；
- 没有 parent-child；
- 没有相邻块扩展。

优先改：

```text
400–600 token
parent section + child chunk
相邻块扩展
表格独立 chunk
```

这比直接换 Unstructured 更可能提升 recall。
