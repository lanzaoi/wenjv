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

## 4. Embedding

- 模型与 **维度** 必须一致（配置项成对修改）。  
- 更换 embedding 模型 ≈ **重建向量库**。  
- 调用可经 LangChain 薄封装；业务编排不依赖 LangChain Agent。

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
- 无命中：倾向拒答或明确「库中无依据」，避免一本正经瞎编。  
- 评估：使用 `eval/` + 脚本对比改动前后（见 `.hermes/plans` 中 G0/G1）。

## 9. 使用频率加权

- **默认不做**复杂热度排序（见 `product-scope.md`）。  
- 若将来加：仅轻量 boost + 防马太效应，且排在 hybrid/治理之后。
