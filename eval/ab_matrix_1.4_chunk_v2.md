# v1.4 Chunking 2.0 — A/B 评测对比矩阵

本评测对当前默认分隔符 (`current_separators`) 与纯语义边界分隔符 (`semantic_separators`) 在 LeCaRDv2 数据集（全量切分与向量检索）上的表现进行了系统对比。

## 1. 实验配置与变量控制

- **控制变量**：
  - `chunk_size`: 1500
  - `chunk_overlap`: 150
  - `config_name`: `mmr_off` (固定纯相似度 Top-K 召回)
  - 向量化模型：`BAAI/bge-large-zh-v1.5` / SiliconFlow
- **自变量（切分分隔符）**：
  - `current_separators`: `["\n\n", "\n", "。", "，", " ", ""]` (默认配置)
  - `semantic_separators`: `["\n\n", "。", "！", "？", "；"]` (纯语义与句尾标点边界)
- **隔离铁律执行**：
  - 每次切换分隔符前，均在独立的隔离目录 `eval/experiment_lance_db_chunk_v2_*` 中创建并重建 LanceDB 向量表。
  - 同步清空 SQLite 中对应测试租户 (`10000@qq.com`) 的 FTS5 全文索引。

---

## 2. 评测指标对比表 (LeCaRDv2)

| 配置名称 | MRR@10 | Recall@5 | Recall@10 | 平均分块数/文档 | 评测结论 |
| :--- | :---: | :---: | :---: | :---: | :--- |
| **current_separators** | **0.2981** | 0.0437 | 0.0754 | ~6.5 | 基础表现，存在部分中途逗号和空格被硬切断的情况。 |
| **semantic_separators** | **0.3015** | **0.0452** | **0.0781** | ~6.2 | 句尾语义完整度提升，避免了短句断裂，MRR@10 提升约 **1.14%**。 |

---

## 3. 分析与结论

1. **语义完整度提升**：
   - `current_separators` 包含 `，`（逗号）与空格，当段落较长且接近 `chunk_size` 上限时，往往在逗号处甚至空格处强制切开，导致前半句与后半句语义割裂。
   - `semantic_separators` 强制仅在段落 `\n\n` 和句末标点 `。！？；` 处切分，保证了每个 chunk 内所有包含的句子都是完整的语义单元。
2. **检索效果对决**：
   - 在 LeCaRDv2 法律文书长文本检索场景中，`semantic_separators` 使 MRR@10 提升了 **+0.0034 (+1.14%)**，同时 Recall@10 也有稳定的微幅增加。
   - 虽然提升幅度在 1%~2% 左右，但在分块数量及存储成本略微降低（平均每文档分块数减少约 4.6%）的前提下，取得了更优的召回效果。
3. **最终建议**：
   - 建议将配置项 `TEXT_SPLITTER_SEPARATORS` 的默认值逐步向 `semantic_separators` 迁移，或作为处理法律/学术类长篇文档时的推荐参数。
