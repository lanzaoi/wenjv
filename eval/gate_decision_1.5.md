# Gate Decision — 1.5 Chunking 2.0 + 多模态 RAG

> 数据源: LeCaRDv2 中文裁判文书 20 题

---

## Track A: Chunking 2.0

### A1: 语义分块

| config | MRR@10 | 95% CI | Recall@10 | chunks | runtime |
|--------|--------|--------|-----------|--------|---------|
| `current` | 0.950 | [0.85, 1.0] | 0.272 | 3321 | 30s |
| `semantic` | 0.956 | [0.87, 1.0] | 0.303 | 3017 | 39s |

**结论**: 语义分块 (+0.66% MRR, -9% chunks)。推荐默认改为 semantic separators。

### A2: 小→大检索

| config | MRR@10 | Recall@10 |
|--------|--------|-----------|
| expand OFF | 0.302 | 0.077 |
| expand ON | 0.314 | 0.081 |

**结论**: +4.21% MRR。对长文档场景推荐默认开启 CHUNK_EXPAND_ENABLED=True, WINDOW=2。

### A3: Late Chunking

| config | MRR@10 | Recall@10 | time |
|--------|--------|-----------|------|
| standard | 0.963 | 0.305 | 99s |
| late_chunking | 0.950 | 0.209 | 17s |

**结论**: MRR -1.3% 但速度快 6×。适合大文档集合的速度优先场景。推荐默认 OFF。

---

## Track B: 多模态 RAG

| 子方向 | 状态 | 依赖 |
|--------|------|------|
| B1 VL 图片 caption | ✅ | Gemini API key |
| B2 表格提取 | ✅ | Gemini API key |
| B3 多模态检索 | ✅ | caption/table 自动入 LanceDB |

**结论**: 功能完成，默认 OFF（需 Gemini key）。13 个测试绿。

---

## 推荐 1.5 发货默认

| 开关 | 1.4 默认 | 1.5 推荐 | 理由 |
|------|----------|----------|------|
| TEXT_SPLITTER_SEPARATORS | `["\n\n","\n","。","，"," ",""]` | `["\n\n","。","！","？","；"]` | +0.66% MRR, -9% chunks |
| CHUNK_EXPAND_ENABLED | False | **True** | +4.21% MRR |
| CHUNK_EXPAND_WINDOW | 2 | 2 | 默认值合理 |
| LATE_CHUNKING_ENABLED | False | False | -1.3% MRR，不推荐 |
| MULTIMODAL_ENABLED | False | False | 需 Gemini key |

---

## 人签字

- [ ] 我确认以上结论（签字: ______________ 日期: ______________）
