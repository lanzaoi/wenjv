# 数据与任务规范 (Data & Jobs)

## 1. 核心业务实体

| 实体模型 | 职责说明 |
|----------|----------|
| User | 基础认证主体（基于 fastapi-users） |
| Note | 用户自建 Markdown 笔记及落盘文件 |
| FileUpload | 上传文件元数据、存储路径及解析状态 |
| Link | 网页链接 URL、抓取配置与状态 |
| IngestionJob | 异步持久化入库任务状态机 |

后续通用化扩展可增加工作区隔离模型（Workspace / Membership），新增字段遵循向前兼容原则。

## 2. 状态机与处理流程

资源实体流转状态：`pending` -> `in_progress` -> `finished` 或 `failed`（具体枚举定义参见 `backend/api/models.py`）。

持久化任务流转状态：`pending` -> `running` -> `succeeded` 或 `failed`，记录 `attempts` 与 `last_error`。

状态管理规则：

- 异常必须可观测：解析或写入失败必须持久化 `error_message`，杜绝静默失败。
- 重试机制：任务执行失败时允许按退避策略重试，达到 `JOB_MAX_ATTEMPTS` 上限后最终置为 `failed`。
- 实例恢复：服务启动时，Worker 会自动扫描并回收超时的 `running` 任务并重新入队调度。

## 3. 持久化任务调度 (Durable Jobs)

- 核心实现位于 `backend/worker/durable_jobs.py`。
- 文件、笔记与网页链接的入库链路统一由 SQLite 任务表接管，不依赖易失的进程内内存队列。
- 实验性递归爬虫若使用临时队列，应在日志中显式提示。

接口定义：

- `GET /jobs`: 查询当前租户的任务列表
- `GET /jobs/{id}`: 查询单个任务的详细执行状态与错误信息

## 4. 数据一致性保障

| 业务操作 | 存储协同与期望行为 |
|----------|--------------------|
| 资源创建 | 写入 SQLite 记录 (状态 pending) -> 派发任务 -> 写入向量库 -> 更新状态为 finished |
| 笔记更新 | 清理所属旧向量切块 -> 重新执行分块与向量入库 |
| 资源删除 | 同步清理 SQLite 元数据及向量库中对应的文本切块 |
| 磁盘文件管理 | 默认保留 `uploads/` 中的原始物理文件，支持按需配置物理清理策略 |

双写异常处理：当关系数据库或向量库写入失败时，系统将实体及任务显式置为 `failed` 状态并记录具体堆栈，支持排查或触发重试修复。

## 5. 配置参数

- 任务并发度、轮询间隔及任务超时判定：参见 `backend/config.py` 与 `backend.env`。
- 数据根目录：默认使用 `~/.config/wenjv/`，底层保留对历史目录 `~/.config/inquisitive/` 的自动探测与平滑回退。

## 6. 数据迁移准则

- 针对 SQLite 字段扩展，提供轻量 `ALTER TABLE` 兼容检测。系统通过 `backend.database._ensure_sqlite_columns` 在初始化时对 `file_uploads`、`notes`、`links` 的 `tags`（JSON 字符串数组，默认 `'[]'`）等新增列执行幂等无损追加，保证升级过程无感知。
- 涉及表结构重大变动时，必须提供独立的迁移脚本与回滚说明。
