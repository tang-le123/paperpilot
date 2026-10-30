# Bilingual Paper: Retrieval-Augmented Generation for Scientific Reading

## Abstract

This paper studies how retrieval-augmented generation can help researchers read long scientific papers. We combine BM25 and dense retrieval, then rerank the candidates before answer generation. The system returns page-level citations so that every claim can be checked against the source.

本文研究如何用检索增强生成帮助研究者阅读长篇论文。系统结合 BM25 与稠密向量检索，并在生成前进行精排；回答会附带页码引用，方便核对原文。

## 1 Introduction

Scientific papers are long, dense, and multilingual. A single paper often contains abstract, method, experiments, and limitations. Readers need answers that are grounded in specific sections rather than generic summaries.

科学论文通常很长，而且中英文混合。读者需要的是有出处的答案，而不是泛泛而谈的摘要。

## 2 Method

The proposed pipeline has three stages. First, we parse PDF, DOCX, and Markdown into section-aware chunks. Second, we build a hybrid index with BM25 and multilingual embeddings. Third, we use reciprocal rank fusion and a cross-encoder reranker to select evidence. The language model must answer in the language selected by the user, while citations keep the original paper language.

系统分为三步：解析文档并按章节切块；建立 BM25 与多语言向量的混合索引；用 RRF 和 Cross-Encoder 选择证据。回答语言由用户选择，引用保留论文原文语言。

## 3 Results

On a pilot set of ten papers, hybrid retrieval found the correct page in the top three results for most questions. Multi-paper comparison improved when each paper contributed at least three candidate chunks. The main failure mode was PDF parsing of two-column layouts and mathematical formulas.

在十篇论文的试点集合上，混合检索大多数问题都能在前三条结果中命中正确页码。多篇对比时，每篇论文至少保留三个候选块效果更好。主要失败模式是双栏排版和数学公式的 PDF 解析。

## 4 Conclusion

A practical paper-reading assistant should prioritize reliable parsing, page-level citations, and explicit language control. Summaries should be generated section by section rather than stuffing the whole paper into one prompt.

一个实用的论文阅读助手应优先保证解析可靠、引用精确到页、回答语言可控。总结应分节生成，而不是把整篇论文塞进一个 Prompt。

## References

[1] Example reference. This section should not be used for question answering.
