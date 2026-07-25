# ADR 0001: 向量存储引擎技术选型 — LanceDB vs pgvector (Vector Storage Engine Selection)

## 状态 (Status)

**Accepted** (已采纳)

## 背景与架构语境 (Context)

个人知识库（Inquisitive）定位为一款轻量级、低维护成本、高度隐私自托管的知识管理与 Retrieval-Augmented Generation (RAG) 系统。在 v1.3 版本架构固化（Hardening）与评估（Evaluation）阶段，为了支撑三路召回（Vector + FTS5 + Structured）与异步分块入库，我们需要对底层的向量数据库引擎进行确定性的技术选型。

评估核心聚焦于两个关键备选方案：
1. **LanceDB**: 嵌入式列式存储向量引擎，基于 Apache Arrow 与 Lance 文件格式，支持零服务器部署与本地直接读写。
2. **Postgres + pgvector**: 传统的客户端-服务器关系型数据库扩展，具备成熟的 ACID 事务特性、多并发写入能力及运维生态。

## 决策 (Decision)

**当前默认使用 LanceDB 作为知识库的主力向量存储引擎；对于个人知识库的应用规模而言已完全够用；在团队级协作或多节点写密集扩展场景下，再评估引入 Postgres + pgvector**。

具体的决策依据如下：

1. **零依赖与极简部署 (Zero-Dependency Deployment)**
   个人知识库的核心设计目标之一是「开箱即用」。LanceDB 属于嵌入式引擎，直接随 Python 进程启动并读写本地磁盘目录（`~/.config/inquisitive/lance_db/`），无需用户配置独立的 Docker 数据库容器、管理连接池或维护后台常驻守护进程。
2. **个人库规模性能过剩 (Sufficient for Personal KB Scale)**
   在个人应用场景下（通常是万级至十万级切块 Chunking），LanceDB 基于 Arrow 的内存映射（mmap）查询极快，查询延迟稳定在毫秒级。结合我们的 SQLite FTS5 倒排索引，无需引入外部系统即可完美支撑日常高频问答与检索。
3. **分层清晰与架构可插拔 (Pluggable Adapter Interface)**
   当前架构已通过 `backend/vector_store/adapter.py` 对向量引擎进行了抽象封装。系统在代码层并未将自身解耦绑定到特定引擎，而是保留了通过配置开关路由至其他后端的架构弹性。

> [!IMPORTANT]
> **诚实声明 (Honesty Protocol)**: 本系统目前在产线与默认发布状态下**全部基于 LanceDB 运行**，代码库尚未把 pgvector 作为生产级默认依赖引入。绝不夸大或虚构架构中未落实的依赖技术。

## 结果与后置影响 (Consequences)

### 正向收益 (Positive)
- **降低内存与资源开销**：宿主机内存占用大幅降至最低，非常适合个人服务器、NAS 及笔记本电脑本地自托管部署。
- **备份极简化**：向量库与 SQLite 元关系库处于同一宿主机目录（`~/.config/inquisitive/`），进行系统迁移或备份时只需直接对目录打包。

### 约束与未来演进路线 (Limitations & Scaling Path)
- **多写并发限制**：由于 LanceDB 依赖底层文件锁机制，在面对团队级多用户写入、大规模高并发持续 Ingestion 场景时，会遭遇写竞态阻塞。
- **演进路线 (Scaling Path)**：当知识库未来走向 **企业级多用户团队协作 (Team / Multi-writer Scaling)**、分批极速高并发入库需求时，架构将基于现有适配器抽象，无缝引入 **Postgres + pgvector** 作为独立服务存储引擎以替代单机本地嵌入式引擎。
