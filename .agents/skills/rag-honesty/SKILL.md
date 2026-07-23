---
name: rag-honesty
description: "Use when changing retrieval, embeddings, parsers, /chat, citations, vector metadata, or docs about RAG capabilities. Enforces honest claims and tenant-safe filters."
---

# RAG Honesty（本仓库）

真源：`specs/rag-and-retrieval.md`、`specs/product-scope.md`。

## 硬禁止（代码与文档）

- 宣称 **HNSW 已优化/已上线**（除非代码与迁移明确实现且 specs 已改）
- 把引擎 **distance** 当成 0–1「相似度百分比」对外展示而不说明
- 宣称 **完美 PPT/OCR/老 .ppt** 支持
- 把「未做」的 hybrid/rerank/拒答写成「已支持」
- 绕过 **user_id**（或等价租户键）做默认全局向量扫描
- 入库失败却标 **succeeded** / 静默吞异常

## 维度与模型

- Embedding **模型与维度绑定**；更换模型必须同步 `EMBEDDINGS_DIMENSION`
- 换维度后旧向量库不可混用；干净数据或重建索引
- 今日 1.0：SiliconFlow bge-m3 通常 **1024** 维（以厂商为准）

## Chat / citations

- RAG 生成默认走后端 `POST /chat` SSE
- 有检索命中时应能产出 **citations** 事件/字段
- `use_rag=false` 行为保持可测、可文档化

## 改动后自检

- [ ] specs/README 表述与真实能力一致
- [ ] 租户过滤仍在
- [ ] job 失败可见 `error_message`
- [ ] 未引入虚假能力文案
