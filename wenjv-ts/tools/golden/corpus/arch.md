# 问据知识库系统架构

问据是一个私有部署的全栈个人知识库系统。

## 核心模块

- 向量检索：BGE-M3 嵌入模型
- 语义重排：BGE-Reranker
- 混合检索：RRF 与 BM25 全文检索

| 特性 | 说明 |
| --- | --- |
| 存储 | SQLite WAL + LanceDB |
| 语言 | TypeScript + Node.js |
