# Gate Decision — 1.5 版本核心特性门禁决策报告

> 评测数据源：
> - `eval/ab_matrix_1.5_chunk_semantic.md`（LeCaRDv2 法律长文本数据集，语义切分对比）
> - `eval/ab_matrix_1.5_small_large.md`（LeCaRDv2 法律长文本数据集，小→大检索动态上下文对比）
> - 自动化回归测试矩阵：`pytest tests/ -q` 全量 146 项单元与集成回归测试

---

## 1. 实验综合数据与能力提升矩阵

### Track A: 语义切分 (Chunking 2.0) 与 小→大检索 (Small-to-Large Retrieval)

| 实验组 / 机制 | MRR@10 | Recall@5 | Recall@10 | 相对提升 | 推荐默认值 |
| :--- | :---: | :---: | :---: | :---: | :--- |
| **旧版默认切分** (`current_separators`) | 0.2981 | 0.0437 | 0.0754 | Baseline | —— |
| **纯语义切分** (`semantic_separators`) | 0.3015 | 0.0452 | 0.0781 | **+1.14% MRR** | **强烈建议默认升级** |
| **小→大检索** (`SMALL_TO_LARGE_ENABLED=True`) | **0.3142** | **0.0478** | **0.0812** | **+4.21% MRR** | **默认 OFF**（按场景可选开） |

### Track B: PDF 图表多模态提取 (Multimodal RAG)
- **视觉处理能力**：基于 `pdfplumber` 和 `google.generativeai` Vision (`gemini-2.5-flash`) 构建了完整的图片 Caption 生成与复杂表格 Markdown 转化链路。
- **系统安全与隔离**：通过 `MULTIMODAL_ENABLED` 独立开关控制，在摄入流水线 `durable_jobs.py` 中异步追加；全流程**绝对 Fail-Open**，遇外网异常/接口超时自动静默跳过，保证原文本摄入不受扰动。

---

## 2. 核心决策与发货默认策略

### 1) 文本切分符 (`TEXT_SPLITTER_SEPARATORS`) — **推荐升级为纯语义切分**
- **证据**：在 LeCaRDv2 上，纯语义边界 `["\n\n", "。", "！", "？", "；"]` 避免了逗号和空格切断句意的弊端，MRR@10 提升 1.14% 且切块数减少 4.6%。
- **决策**：推荐配置中将默认切分符号向纯语义切分演进。

### 2) 小→大检索 (`SMALL_TO_LARGE_ENABLED`) — **默认 OFF，特定长文本场景建议开启**
- **证据**：256 字细粒度召回配合 ±2 chunk 的动态展开 (`_expand_context`) 取得了最佳的 MRR@10 表现 (0.3142, 相对提升 4.21%)。但超细粒度切分会增加约 4 倍的 SQLite `chunk_mapping` 记录数与 LanceDB 向量条目数。
- **决策**：**发货默认保持 OFF**。对于法务、科研文献、长篇合规报告等严密语义检索场景，强烈建议开启。

### 3) 多模态图表解析 (`MULTIMODAL_ENABLED`) — **默认 OFF，有视觉依赖时按需开启**
- **证据**：多模态解析需要消耗额外的 Gemini VL API Token 并依赖外界网络环境。为确保普通用户本地搭建与常规文本知识库摄入的极速体验，必须保持零外网强制依赖。
- **决策**：**发货默认保持 OFF**。文档明确标注「存在复杂图表与架构图 PDF 时，配置 API Key 并开启此项」。

---

## 3. v1.5 发货配置推荐一览

| 配置开关 / 字段 | 1.5 推荐默认 | 理由与场景说明 |
| :--- | :---: | :--- |
| `TEXT_SPLITTER_SEPARATORS` | `["\n\n", "。", "！", "？", "；"]` | 纯语义切分保留句意完整度，提升 MRR 并省存储 |
| `SMALL_TO_LARGE_ENABLED` | **OFF** | 默认安全低消耗；长文章/精准问答场景推荐开启 |
| `CHUNK_RETRIEVAL_SIZE` | `256` | 开启小大检索时标准召回切块大小 |
| `CHUNK_EXPAND_WINDOW` | `2` | 开启小大检索时上下展开窗口跨度 (中心前后 ±2 块) |
| `MULTIMODAL_ENABLED` | **OFF** | 默认免外网无消费；PDF 图表解析需求时开启 |
| `IMAGE_CAPTION_MODEL` | `gemini-2.5-flash` | 性能与成本最优的视觉理解模型 |

---

## 4. 人签字

- [ ] 我确认以上评测结果、工程架构与默认配置发货策略（签字: ______________ 日期: ______________）
