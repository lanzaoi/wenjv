# Gate Notes v1.7: 图像入库与检索加速

本决策记录 (Gate Note) 汇总了 v1.7 周期内完成的多模态图片入库、图问 API 以及检索加速优化的 DoD（Definition of Done）清单与关键说明。

## 1. 核心能力验收 (DoD)

### 图像入库 (T1) & 图问 API (T2/T3)
- [x] 支持 `.png`, `.jpg`, `.jpeg` 文件的上传与持久化存储。
- [x] `durable_jobs` 异步抽字：利用本地 OCR 或云端大模型提取图像描述 (Caption) 作为文本索引，失败自动进入 Failed 队列。
- [x] 跨租户与门禁隔离防御：通过 `test_isolation.py` 及 `IMAGE_INGEST_ENABLED` 开关覆盖 4xx/401 隔离阻断逻辑。
- [x] 新增 `POST /documents/search/by-image`（别名 `/documents/search-by-image`）与 `POST /chat/by-image`，共用底层文字抽取做 **T0 图→文→Hybrid**（非原生视觉向量检索）。

### 检索加速 (T4/T5)
- [x] 在 `search_documents` 中引入详尽的延迟耗时测定 (`SEARCH_TIMING_ENABLED`)，输出各路检索真实耗时基线。
- [x] 实现 `SEARCH_PARALLEL_LEGS=true`，通过 `asyncio.gather` 并行执行向量、FTS5 与 Structured 三路检索，缩短 I/O 等待。
- [x] 单腿保护 (Fail-open) 测试，确保辅助词法或结构化错误不拖垮核心向量检索（异常退回空集），且主线向量检索报错正确透传。
- [x] 查询向量级别的 Embedding 缓存验证，确保高频相同 query 的 Embed 操作热命中小于 `1ms`。

## 2. 关键环境变量 (env) 列表

| 变量名 | 默认值 / 示例 | 说明 |
|---|---|---|
| `IMAGE_INGEST_ENABLED` | `true` | 图片入库与图问 API 的总开关 |
| `IMAGE_CAPTION_FALLBACK_ENABLED` | `true` | 是否允许使用多模态 LLM 进行 Caption 增强 |
| `SEARCH_TIMING_ENABLED` | `false` | 是否开启底层详细搜索分段延迟打点记录 |
| `SEARCH_PARALLEL_LEGS` | `true` | 启用通过 asyncio 并行多路混合检索 I/O |
| `SEARCH_FETCH_MULTIPLIER` | `1` | 放大候选池的倍率因子 |
| `RERANK_ENABLED` | `false` | (警告：开启 Rerank 将对速度产生显著拖累) |

## 3. 端点路径汇总

- `POST /file/upload`: 扩展支持图片上传 (202 Accepted)。
- `POST /documents/search/by-image`（及别名 `search-by-image`）: T0 图问检索。
- `POST /chat/by-image`: T0 图问 + RAG 流式对话。

## 4. 已知限制与声明

- 所有的多模态检索建立在**将图片转写为文本** (Image-to-Text) 基础之上，底层检索仍然是文本向量与 FTS5。本应用未实装也不声明诸如 ColPali 之类的原生多模态向量嵌入架构能力。
- 并行检索加速 (`SEARCH_PARALLEL_LEGS`) 依赖底层 I/O 隔离。在 Windows 本地单机 CPU 受限的测算中，Python 多线程与 SQLite 并发带来的真实加速比可能有限；显著的延迟红利将在外挂独立向量数据库及远端 Embedding 服务后体现。
