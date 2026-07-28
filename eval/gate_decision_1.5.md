# Gate Decision — 1.5 Chunking 2.0 + Multimodal RAG（收尾版）

> 日期: 2026-07-27  
> 分支: `feat/v1.5-chunking-multimodal`  
> 测试: **158 passed**  
> 身份: **Text-centric Hybrid RAG** + OCR-augmented ingest（不是 PixelRAG）

---

## Track A: Chunking 2.0

### A1 语义 separators

| config | MRR@10 | Recall@10 | chunks |
|--------|--------|-----------|--------|
| current | 0.950 | 0.272 | 3321 |
| semantic | **0.956** | 0.303 | 3017 |

**Gate: ON**（小正收益 + 更少 chunk）

### A2 小→大 expand

| expand | MRR@10 | Recall@10 |
|--------|--------|-----------|
| OFF | 0.933 | 0.309 |
| ON | 0.933 | 0.309 |

**Gate: ON 可选（体验）** — **不改 MRR**，只扩返回上下文。旧报告 +4.21% 为误读，已作废。

### A3 Late chunking

| config | MRR@10 | time |
|--------|--------|------|
| standard | 0.963 | 99s |
| late | 0.950 | 17s |

**Gate: OFF**（略损 MRR）

---

## Track B: Multimodal（OCR-first）

架构（用户纠正后）:

```
image/PDF page → PaddleOCR (primary) → text ≥ threshold → [OCR] …
                              ↘ empty → Gemini VL → [Gemini] …
                              ↘ both empty → ""
```

| 项 | 状态 |
|----|------|
| 代码路径 | ✅ `multimodal.py` + `ocr_client.py` |
| 单测 | ✅ |
| Gemini key | ⚠️ 需 `GEMINI_API_KEY` 或 `GOOGLE_API_KEY`（config 已兼容两者） |
| 公开 MM 基准 | ⚠️ 见 Open RAG Bench |

### Open RAG Bench（55q / 51 PDF / 1184 sections）

| mode | doc MRR@10 | sec MRR@10 | 说明 |
|------|------------|------------|------|
| text_only | **0.979** (R@10=1.0) | **0.661** | 文本 hybrid 近天花板 |
| text_table | 0.970 | 0.657 | 加表 alone 几乎无 doc 增益 |
| text_table_ocr | 0.832* | 0.548* | *无效 MM 信号：0/42 caption + embed 失败污染 |

**Gate: MULTIMODAL 默认 OFF**  
主指标用 **section MRR**；doc 已饱和不能证 MM。  
未配 Gemini + 论文图 OCR 常空 → **不能宣称多模态成熟**。

报告: `eval/ab_matrix_open_ragbench_mm.md`  
脚本: `eval/run_open_ragbench_mm.py`

---

## Track C: 检索成熟度（LeCaRDv2 30q / 5000 chunks）

| config | MRR@10 | Recall@10 |
|--------|--------|-----------|
| vector_only | **0.967** | 0.275 |
| hybrid_only (w_v=3) | **0.967** | 0.275 |
| hybrid_rerank | **0.967** | 0.275 |

- bge-m3 在中文法律文本上极强；FTS5/rerank **无增量**（非坏，是向量已够准）
- FTS5 CJK 已修（2/3-gram OR）；修前中文 hybrid 实质退化为纯向量
- RRF 默认 `HYBRID_RRF_WEIGHT_VECTOR=3.0`
- Structured Recall：长 query 截断 200 防 LIKE too complex

---

## 1.5 收尾代码修复（本轮审查）

| 问题 | 修复 |
|------|------|
| Embed SSL/半截 body → 零向量污染索引 | `embedder.py`：3 次重试 + backoff；batch 中零向量逐条重试 |
| Lance `create_index("vector")` 被当成 metric | `lance_db.ensure_vector_ann_index`：只传 `metric="cosine"`；IVF_PQ 参数安全化；失败降级 flat scan |
| OCR 只读 `markdown.text` | `ocr_client._extract_texts_from_ocr_item`：rec_texts / prunedResult 等 fallback |
| MM caption 受 `OCR_MODE=off` 短路 | multimodal：`MULTIMODAL_ENABLED` 时临时 force OCR |
| Gemini key 不进 Settings | `GEMINI_API_KEY` validator 回落 `GOOGLE_API_KEY` |
| MMR 默认与门禁不一致 | **MMR_ENABLED=False**, **MMR_LAMBDA=0.85** |
| FTS5 中文零命中 | 已修（1.5 中） |
| Structured Recall 长 query 崩 | 已修（1.5 中） |

新增测试: `tests/test_embedder_ocr_lance_fixes.py`  
全量: **158 passed**

---

## 推荐 1.5 发货默认

| 开关 | 推荐 | 理由 |
|------|------|------|
| TEXT_SPLITTER_SEPARATORS | 语义中文边界 | A1 +0.66% |
| CHUNK_EXPAND_ENABLED | True（体验） | MRR 不变，上下文更完整 |
| LATE_CHUNKING_ENABLED | False | -1.3% MRR |
| MULTIMODAL_ENABLED | False | 需 key；公开 MM 未证 |
| OCR_MODE | off（文档抽取按需） | MM 开时 caption 会 force OCR |
| HYBRID_SEARCH_ENABLED | True（生产 env） | 多路召回；中文短 query 受益 |
| HYBRID_RRF_WEIGHT_VECTOR | 3.0 | 防 FTS 稀释强向量 |
| MMR_ENABLED | **False** | λ 网格：OFF 最优 / λ=0.85 可选项 |
| MMR_LAMBDA | 0.85 | 若启用 |
| RERANK_ENABLED | False | LeCaRDv2 无增益；key 可回落 EMBEDDING |
| QUERY_CLASSIFIER_ENABLED | False | 1.4 门禁 |

---

## 成熟度一句话

| 维度 | 判定 |
|------|------|
| 文本 Hybrid RAG | **作品集可用**（LeCaRDv2 / Open RAG Bench doc 级强） |
| Chunking 2.0 | **可收**（A1 ON，A2 体验，A3 OFF） |
| 多模态 | **原型**（路径通，公开 MM 基准未证明有效） |
| 工程 | **可用**（158 tests、cache/obs、fail-soft+retry） |

**不要对外写：** PixelRAG / 多模态 RAG 已成熟  
**可以写：** Hybrid RAG + OCR-first multimodal ingest（实验开关）

---

## 未做 / 下版本

1. 配 `GOOGLE_API_KEY` 后重跑 Open RAG Bench `text_table_ocr`  
2. 用户自有笔记/PDF 验收  
3. Pixel-style 旁路（可选，非默认）  
4. Audio STT（SiliconFlow SenseVoice，已冻结为可选 ingest）  
5. 多账号隔离硬验收 / PPT→OCR 冒烟  

---

## 人签字

- [ ] 我确认以上 1.5 收尾结论（签字: ______________ 日期: ______________）
