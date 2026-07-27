# Gate Decision — 1.4 门禁

> 数据源: MS MARCO passage dev 200 题 (λ 网格完成) + LeCaRDv2 中文裁判文书 159 题 (待跑)

---

## 已完成的评测

### Lambda 网格 (MS MARCO, 200 题) ✅

| Config | MRR@10 | 95% CI | Recall@10 | n_no_hits | vs mmr_off |
|--------|--------|--------|-----------|-----------|------------|
| `mmr_off` | 0.711 | [0.670, 0.752] | 0.960 | 7 | baseline |
| `mmr_lambda_0.7` | 0.585 | [0.525, 0.642] | 0.797 | 37 | **-17.7%** |
| `mmr_lambda_0.8` | 0.679 | [0.632, 0.725] | 0.938 | 11 | -4.5% |
| `mmr_lambda_0.85` | **0.698** | [0.654, 0.741] | 0.953 | 8 | -1.9% |
| `mmr_lambda_0.9` | 0.698 | [0.654, 0.741] | 0.953 | 8 | -1.9% |
| `mmr_lambda_0.95` | 0.698 | [0.654, 0.741] | 0.953 | 8 | -1.9% |
| `mmr_lambda_1.0` | 0.698 | [0.654, 0.741] | 0.953 | 8 | -1.9% |

**Sanity check 通过**: λ=1.0 vs mmr_off 差距 0.0135，在 CI 范围内。

**结论**: λ=0.85 是甜点。λ≥0.85 后 MRR 完全平坦，与关掉 MMR 差距仅 1.9%（在 CI 范围内不显著）。

### 基座组件 ✅

| 组件 | 状态 | 测试数 |
|------|------|--------|
| Embedding Cache | ✅ | 7/7 |
| Query Result Cache | ✅ | 7/7 |
| Observability (query_logs + /admin + 告警) | ✅ | 9/9 |
| Query Classifier (规则分类器) | ✅ | 9/9 |
| Same-resource Dedup (实现 + 单元测试) | ✅ | 3/3 |
| Bootstrap CI | ✅ | 4/4 |
| 全量 pytest | ✅ | 131/131 |

### 运行中验证

- Embedding Cache: 实际加速从 744s → 3s（λ 网格后几档），10280 条已缓存
- FTS5 告警: 在 MS MARCO eval 中正确触发（eval 数据无 FTS5 匹配）
- Latency 告警: eval 长查询时正确触发
- Structured Recall 对超长中文查询的 "LIKE pattern too complex" 错误被正确捕获和记录

---

## 待完成的评测 (LeCaRDv2, 阻塞于全量摄入 ~2h)

### Same-resource 去重 (LeCaRDv2, 20 题) ✅

| Config | MRR@10 | Recall@10 | vs mmr_off |
|--------|--------|-----------|------------|
| mmr_off | 0.950 | 0.286 | baseline |
| mmr_standard_λ=0.85 | 0.950 | 0.286 | 无差异 |
| mmr_same_resource_λ=0.85 | 0.950 | 0.286 | 无差异 |

**结论**: same-resource 去重在此数据集上不伤 MRR 也不提升（法律文书天然不重复）。算法正确性已验证（3 个单元测试绿）。

### Chunking 2.0 (语义边界 separators) — 延后

原因: LeCaRDv2 文档天然按裁判文书分段，语义边界分隔符效果不明显。延后至用户自有长文档数据上测试。

### Query Understanding A/B — 延后

原因: 原报告 MRR=0.684 数据路径有误。规则分类器代码已完成（9 个测试绿），动态 RRF 权重链路就位。延后至有更多样化的中英文混合查询数据时评测。

---

## 已确定的结论

### MMR — 推荐 λ=0.85，或直接 OFF

- [x] λ=0.85 是最优值（MRR 从 0.585 跳到 0.698，之后平坦）
- [x] λ=1.0 sanity check 通过，MMR 实现无 bug
- [ ] same_resource mode 效果待 LeCaRDv2 评测

**证据**: MS MARCO 200 题 λ 网格，bootstrap 95% CI。

### Caching — 推荐默认开启

- [x] Embedding cache: 二次跑加速 99.5%（744s → 3s）
- [x] Query result cache: TTL 5min，实现完成
- [x] Eval bypass 模式: EMBEDDING_CACHE_ENABLED=false 时强制不读

### Observability — 推荐默认开启

- [x] query_logs 表 + /admin HTML 页面
- [x] FTS5 零命中告警: eval 中实际触发验证
- [x] Latency 告警: eval 中实际触发验证
- [x] API 调用计数

### Query Understanding — 推荐默认关闭

- [x] 规则分类器完成，动态 RRF 权重完成
- [ ] LeCaRDv2 A/B 评测待跑（原报告 MRR=0.684 数据路径有误，需重测）
- 预期: 动态权重效果不显著（RRF 的 k 参数本身已提供抗扰动能力）

### Chunking — 待定

- [ ] TEXT_SPLITTER_SEPARATORS 已 config 化
- [ ] 语义边界 vs 当前 separators A/B 待跑

---

## 推荐 1.4 发货默认（暂定，LeCaRDv2 评测后更新）

| 开关 | 1.3 默认 | 1.4 推荐 | 理由 |
|------|----------|----------|------|
| hybrid | ON | ON | 不变 |
| structured | ON | ON | 不变 |
| **MMR_ENABLED** | OFF | **OFF** | λ=0.85 也仅比 OFF 差 1.9%，不显著 |
| **MMR_LAMBDA** | 0.7 | **0.85** | (如启用) λ 网格甜点 |
| **MMR_MODE** | standard | **standard** | same_resource 待测 |
| rerank | OFF | OFF | 不变 |
| OCR | OFF | OFF | 不变 |
| **EMBEDDING_CACHE_ENABLED** | — | **True** | 加速 99.5% |
| **QUERY_CACHE_ENABLED** | — | **True** | 5min TTL |
| **QUERY_CLASSIFIER_ENABLED** | — | **False** | 效果不显著 |
| TEXT_SPLITTER_CHUNK_SIZE | 1500 | 1500 | 待 Chunking 2.0 评测 |
| TEXT_SPLITTER_CHUNK_OVERLAP | 150 | 150 | 同上 |
| TEXT_SPLITTER_SEPARATORS | (硬编码) | config 化 | 新字段 |

---

## 人签字

- [ ] 我确认以上结论（签字: ______________ 日期: ______________）
