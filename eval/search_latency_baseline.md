# 搜索阶段耗时观测（Instrumentation）基线测试

此文档为 T4 耗时观测的结果基线，为后续的检索加速（T5）优化提供对比指标。

## 测试环境

- **测试用户**：`test@example.com`
- **Query**：`"测试查询：什么是向量检索？"`
- **测试轮数**：热身 1 次，重复执行 5 次
- **缓存状态**：无命中（如果开启了缓存，这里主要测的是冷启动及底层检索的延迟）
- **混合检索**：开启

## 耗时分发记录 (当前未优化状态)

通过在 `backend/api/services/search.py` 中埋点记录各阶段耗时（`timings` 字段），汇总如下：

| 指标 | 平均耗时 (ms) | 备注 |
|---|---|---|
| **Query Cache Check** | `~0.1ms` | 缓存检索非常快 |
| **Vector Leg** | `~280ms - 320ms` | 包含 Query Embedding 和向量近似匹配（LanceDB） |
| **Keyword Leg** | `~10ms - 15ms` | FTS5 全文搜索 |
| **Structured Leg** | `~20ms - 30ms` | 结构化匹配及结果聚合 |
| **Fusion Leg (RRF)** | `~1ms` | 本地内存融合重排 |
| **MMR / Rerank Leg** | `~0ms` | 未触发大模型重排时 |
| **Total Latency** | `~388.00 ms` | 综合全部流程的总体端到端延迟 |

> **注**：以上测试基于 `eval/run_search_latency.py` 的脚本单线程执行采集，`Vector Leg` 由于包含模型 Embedding 操作占比最大，将是后续并发优化的主要发力点。

## 测试结论 (T4 阶段)

当前阶段的所有检索步骤是**串行**执行的（先 Vector，再 Keyword，再 Structured）。为了在不改变底层 DB 架构的情况下提高速度，可以在 T5 中利用 `asyncio.gather` 或者多线程，将不互相依赖的 Vector、Keyword 和 Structured 查询转为**并行（并发）执行**。

---

## 延迟调优对比记录 (T5 阶段)

我们在 T5 阶段通过 `SEARCH_PARALLEL_LEGS` 开关引入了并行检索能力，并继续使用 `eval/run_search_latency.py` 进行验证（测试环境：Windows 本地单机，Embedding/DB 查询均在同一 CPU 执行，且由于是 Python GIL 限制，并发受限于单核上下文切换开销）。

### 测试环境

- **硬件/位置**：本地本机环境
- **模型支持**：调用本地或云端 Embedder（取决于环境变量，实际主要时间在本地 CPU 执行向量/FTS 检索）
- **混合检索**：开启

### 对比数据

| 模式 | Average Total Latency | 备注 |
|---|---|---|
| **Parallel=False** (串行) | `393.99 ms` | 依次执行 Vector -> FTS5 -> Structured |
| **Parallel=True** (并行) | `396.93 ms` | 使用 `asyncio.gather` 并发执行三条腿 |

> **现象与结论分析**：
> 在本地 Windows 及 Python 线程池环境下，由于底层 SQLite/LanceDB 以及 GIL 的原因，将检索强行分配到多个线程中（`asyncio.to_thread`）并未带来预期的显著耗时降低，甚至可能由于线程切换与 asyncio 调度开销导致延迟微幅上升（约 +3ms）。
>
> 尽管本地小规模数据集的并行化未体现出极大优势，但此重构成功分离了各个查询流程：
> 1. 在生产环境或将 DB/Embedding API 化拆分为独立服务时，真实的 I/O 阻塞将被 `asyncio.gather` 显著抹平。
> 2. 具备了在各腿实现相互独立 **fail-open** 降级的能力，且已通过自动化测试覆盖。
