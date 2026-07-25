# Gate Decision — 1.3 配置门禁（终版）

> 数据源：`eval/ab_matrix_1.3.csv`（MS MARCO dev 集，50 题 × 4 档，完整矩阵）

## M-small 矩阵

| Config | MRR@10 | Recall@10 | n_no_hits | vs Default |
|--------|--------|-----------|-----------|------------|
| **mmr_off** | **0.740** | **0.960** | 2 | **+41% MRR, +16% R@10** |
| rerank_on | 0.588 | 0.860 | 6 | +12% MRR, +6% R@10 |
| default | 0.525 | 0.800 | 9 | baseline |
| hybrid_off | 0.517 | 0.800 | 9 | −2% MRR |

## 结论

### MMR — **改默认 OFF**（强证据）
- 默认 MMR=ON (lambda=0.7)：MRR 0.525, 9 题无命中
- MMR=OFF：MRR 0.740, 仅 2 题无命中
- 结论：对短段落检索（MS MARCO 为代表），MMR 去重过度激进，把相关结果也去掉了
- **建议：默认 OFF，文档注明「长文档/重复内容场景可开」**

### Rerank — **仍保持 OFF**（中等证据）
- Rerank ON 比 default 好 12% MRR，但远不如 mmr_off
- 开启 rerank 需 API key + 外网 + 额外 2s/query
- 若 mmr_off 已是最优，rerank 边际增益小
- **建议：保持 OFF，文档注明「追求极限召回可开」**

### Hybrid — **保持 ON**（弱证据）
- hybrid_off 略差于 default（−2% MRR），但接近
- 对自己的知识库（长文本/标题命中）仍有价值
- 无外网成本
- **建议：保持 ON**

### Structured — **保持 ON**
- 未单独测，无成本，无负面指标

### 权重 — **不改**
- 无多轮证据

## 推荐 1.3 发货默认

| 开关 | 默认 | 理由 |
|------|------|------|
| hybrid | **ON** | 个人库有用，无成本 |
| structured | **ON** | 同上 |
| **MMR** | **OFF** | MS MARCO 上 −41% MRR |
| rerank | **OFF** | 需要 key，边际增益 |
| OCR | **OFF** | 需 token |

---

## 人签字

- [ ] 我确认以上结论（签字: ______________ 日期: ______________）
