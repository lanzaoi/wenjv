# RAG 与检索规范（RAG & Retrieval）

## 1. 流水线（唯一主路径）

```text
Source (note|file|link)
  → Parser (backend/parsers)
  → Chunk (load_and_chunk_document / splitter)
  → Embed (Ollama embeddings)
  → Vector upsert + SQL status=finished
                ↓
Question → (optional) history
  → Embed(query) → Search + tenant filter
  → Build prompt + citations
  → LLM stream (Ollama via backend /chat)
```

禁止另起一套「仅前端本地 RAG」作为默认生产路径。

## 2. 解析（Parser）

| 规则 | 说明 |
|------|------|
| 插件化 | 新格式 = 新 Parser + registry，不写巨型 if-else |
| 失败显式 | 抽不到文本 → 失败状态 + error_message，禁止假成功 |
| 元数据 | 尽量保留 page/slide 等，供引用定位 |
| 当前支持 | text/md/json…、pdf、docx、**pptx** |
| 明确未承诺 | 老 `.ppt`、OCR 扫描件、完美版面还原 |

PPTX：允许「按幻灯片抽文本」的务实实现；增强（备注/表格）单独迭代，不在未完成时对外宣称「完整 PPT 支持」。

## 3. 切块（Chunking）

- 默认：递归字符切块（size/overlap 见 `backend/config.py`）。  
- 改参数必须考虑：**旧向量不自动迁移**，需重建或版本化 collection。  
- 未来可按类型分配置（text/pdf/pptx 不同 size）；未配置前保持简单。

## 4. Hybrid (合成方案)

- **默认关闭** (`HYBRID_SEARCH_ENABLED=false`)，未开启或未完成 backfill 时默认依赖纯向量或 LIKE。
- **检索路线**：采用「向量主 + 词法辅」架构。
- **L2 词法后端** (HYBRID_KEYWORD_BACKEND)：支持 `fts5` (默认) 或 `like`。不再包含 `fts5_then_like` 拼接策略。
- **L3 融合重排**：采用等权 RRF (Weighted RRF)，默认权重 `w_v=1.0, w_k=1.0`（$k=5$）。进入 RRF 前，向量距离大于最大阈值的文档会被直接抛弃。
- **注意**：FTS 不可用时会安全退回纯向量。混合检索开启时，由于 RRF 分数叠加，最终输出的 score 与纯 Lance 向量的 distance 量纲可能不同（RRF 输出越大越好）。
- **同步要求**：使用 FTS5 需运行 `backend/worker/fts5_backfill.py` 脚本；增量入库会自动双写。
- **效果门禁**：仅当专有名词召回率显著提升，且长尾语义不掉级时才建议在生产环境默认开启。

## 5. Embedding 与 Chat Provider

- 推理后端目前支持配置化双路（Ollama 与 OpenAI 兼容 API），详见配置 `EMBEDDING_PROVIDER` 与 `CHAT_PROVIDER`。
- 模型与 **维度** 必须一致（配置项成对修改，例如 bge-m3 必须配 1024）。  
- 更换 embedding 模型或云提供商 ≈ **重建向量库**，不要混用旧的维度数据。
- 调用可经薄封装或内置 HTTP 客户端拉流；业务编排不依赖 LangChain Agent 框架。

## 5. 检索

- 必须带 **租户过滤**（user_id / belongs_to；未来 workspace_id）。  
- Top-K 由 `window_size` 等参数控制。  
- include/exclude 源过滤是一等能力，勿删除。  

### 索引表述（对外与文档）

| 可说 | 不可说 |
|------|--------|
| 支持向量检索；Lance 侧可尽力创建 ANN（如 IVF_PQ）；小数据可能 flat | 「已采用并调优 HNSW」 |
| metadata 标量索引加速过滤 | 「标量 BTREE = 语义索引」 |

## 6. Score 语义

- Lance 等返回值可能是 **距离（越小越近）**，不是百分比。  
- API/UI 展示避免「匹配度 87%」除非实现了归一化并写明公式。  
- 规划：可同时返回 `distance` 与可选 `similarity` 字段。

## 7. 对话与「记忆」

| 类型 | 本项目做法 |
|------|------------|
| 知识记忆 | 向量知识库 + SQL 元数据 |
| 多轮短上下文 | 请求体 `history`（窗口截断）+ FE `session_state.messages` |
| Agent Memory | **不做**（非目标，见 `product-scope.md`） |
| 会话持久化表 | 非当前必做；若做则命名为 conversation，不叫 memory 引擎 |

## 8. 质量与拒答

- 有 RAG 时优先 **带 citations**。  
- 无命中：系统会触发硬拒答（默认 `RAG_REFUSE_ON_EMPTY=true`），直接返回无依据提示，避免大模型一本正经瞎编。
- 评估：使用 `eval/` + 脚本对比改动前后（见 `.hermes/plans` 中 G0/G1）。

### 自动化评估与架构门禁（v1.3 规范）
为杜绝“凭感觉调参”，本项目在 `eval/` 目录构建了基于 MS MARCO 的标准检索评估流水线与消融实验矩阵：
1. **如何跑评估**：
   - 准备数据：通过 `python eval/sample_msmarco.py` 采样评测集，通过 `python eval/ingest_msmarco.py` 写入向量库。
   - 运行实验：使用 `python eval/run_eval.py` 进行单次评测，或使用 `python eval/run_matrix.py` 自动批量运行 4 组消融矩阵（`default`、`hybrid_off`、`rerank_on`、`mmr_off`）。
   - 查看报告：评估结果自动生成于 `eval/ab_matrix_1.3.csv` 与 `eval/ab_matrix_1.3.md`，重点观测 **MRR@10**、**Recall@5**、**Recall@10** 及耗时指标。
2. **默认配置与门禁表述**：
   - 决策依据：实验矩阵数据结论统一归档于 [`eval/gate_decision.md`](../eval/gate_decision.md)。
   - 门禁纪律：**严禁任何自动化脚本或开发人员私自修改代码默认开关**，参数变更必须经由人审核签署。当前推荐默认配置为：
     - **Hybrid 混合检索**：默认推荐开启（配合 FTS5 弥补专用名词与准确代码召回）。
     - **MMR 多样性重排**：默认推荐开启（有效剔除高相似度冗余块，提升信息熵）。
     - **Rerank 二次重排**：默认推荐关闭（推理耗时显著升高，且易增加不确定的拒答率，仅限高算力场景选配）。

## 9. 使用频率加权

- **默认不做**复杂热度排序（见 `product-scope.md`）。  
- 若将来加：仅轻量 boost + 防马太效应，且排在 hybrid/治理之后。
