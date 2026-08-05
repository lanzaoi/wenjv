# 数据与任务规范（Data & Jobs）

## 1. 核心实体（逻辑）

| 实体 | 说明 |
|------|------|
| User | 认证主体（fastapi-users） |
| Note | Markdown 笔记 + 落盘文件 |
| FileUpload | 上传文件元数据 + 路径 |
| Link | URL 与抓取状态 |
| IngestionJob | 可恢复入库任务 |

未来通用化可增加 Workspace / Membership（见升级 plan G3），新字段优先可空 + 迁移脚本。

## 2. 处理状态

资源侧常见：`pending` → `in_progress` → `finished` | `failed`（具体枚举以 `models.py` 为准）。

任务侧：`pending` → `running` → `succeeded` | `failed`，含 attempts / last_error。

规则：

- 失败必须可观察（`error_message` / job error）。  
- 允许重试；超过 `JOB_MAX_ATTEMPTS` 保持 failed。  
- 进程重启：reclaim 超时 `running` → 再入队。

## 3. Durable jobs

- 实现：`backend/worker/durable_jobs.py`。  
- 文件/笔记/链接主路径走 **DB 任务表**，不依赖进程内内存队列做唯一真相。  
- 实验性递归 crawl 可暂留内存队列，但不得作为「已生产级」承诺。

API：

- `GET /jobs`、`GET /jobs/{id}`  
- 规划：`POST /jobs/{id}/retry`

## 4. 一致性

| 操作 | 期望 |
|------|------|
| 创建 | SQL 行 pending → job → 向量写入 → finished |
| 更新笔记 | 删旧向量（按源）→ 再入库 |
| 删除 | SQL 删除 + 向量按 file_id/link_id/source 清理 |
| 磁盘文件 | 可与「软删」并存；硬删磁盘为可选策略，需显式产品决定 |

双写失败：SQL 与向量可能短暂不一致；应用 failed 状态与重试修复，而不是静默成功。

## 5. 配置

- 任务并发、轮询、stale 时间：`backend/config.py` / `backend.env`。  
- 数据目录默认 `~/.config/wenjv/`（自动回退历史路径 `~/.config/inquisitive/`）。

## 6. 迁移

- SQLite 轻量 `ALTER` 补列可接受。  
- 结构性大变（workspace 等）应提供脚本 + 文档，避免只改 ORM。
