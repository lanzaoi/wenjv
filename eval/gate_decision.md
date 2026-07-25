# Gate Decision — 1.3 配置门禁

> 数据源：`eval/ab_matrix_1.3.csv`（MS MARCO dev 集，50 题 × 3 档）

## M-small 矩阵摘要

| Config       | MRR@10 | Recall@10 | vs Default | Status |
|--------------|--------|-----------|------------|--------|
| **default**  | **0.551** | **0.860** | — baseline | SUCCESS |
| `hybrid_off` | 0.513  | 0.800     | −7% MRR, −6% R@10 | SUCCESS |
| `rerank_on`  | 0.409  | 0.760     | −26% MRR, −10% R@10 (API 404, fail-open degraded) | SUCCESS* |

\* rerank_on 因 SF API URL 拼接错误（embeddings 前缀残留）→ 全程 404 → fail-open 路径有回归，待修后再跑。

## 逐项结论

### Hybrid 默认？
| 数据 | 建议 | 依据 |
|------|------|------|
| MRR 0.551 vs 0.513, Recall 0.86 vs 0.80 | **保持 ON** | +7% MRR, +6% Recall；50 题规模一致 |

### Rerank 默认？
| 数据 | 建议 | 依据 |
|------|------|------|
| 404 降级路径反而拉低 MRR | **保持 OFF**（强证据） | fail-open 有 bug；无有效 rerank 数据前禁止开 |

### Structured 默认？
| 数据 | 建议 | 依据 |
|------|------|------|
| —（矩阵未单独测） | **保持 ON** | 无外部依赖成本；无负面指标 |

### MMR 默认？
| 数据 | 建议 | 依据 |
|------|------|------|
| —（mmr_off 未来得及跑） | **保持 ON** | 1.2 已默认 ON 无问题；小库收益低但无损 |

### 权重调整？
| 数据 | 建议 | 依据 |
|------|------|------|
| — | **不改** | 无多轮证据；留到 1.4 |

## 已知 Bug

- Rerank API URL：`EMBEDDING_API_BASE=/v1/embeddings` → rerank fallback 拼出 `/v1/embeddings/rerank` = 404
- 已修复：`rerank_client.py` 加 `.replace('/embeddings', '')`
- Rerank fail-open 路径疑似 return 空/少结果 → 需 1.4 修

---

## 人签字

- [ ] 我确认以上结论（签字: ______________ 日期: ______________）

**规则：** 签字后才允许改仓库里的 `RERANK_ENABLED` / `.env.example` / README 推荐配置段。
