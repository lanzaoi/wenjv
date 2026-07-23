# Progressive Upgrade Roadmap

本仓库采用**保留原结构、分阶段优化**策略。  
对外叙事可按独立作品包装；若仍基于本仓库大量原代码公开发布，请自行处理 **AGPL-3.0** reciprocal 义务。

## Phase 1 — Reliability & Safety Baseline

- [x] 修复 `update_note` 空指针（先判空再改状态）
- [x] 文件/笔记 worker：`IN_PROGRESS` / `FAILED` + `error_message`
- [x] 后端上传：扩展名白名单 + 大小限制
- [x] 配置：更保守的并发默认值；默认密钥启动告警
- [x] 轻量 schema 补列（SQLite `ALTER TABLE`）
- [x] PDF 抽取失败显式抛错（避免假成功）
- [x] Lance filter 基础转义（单引号）

## Phase 2 — Durable Jobs

- [x] `ingestion_jobs` 表（可恢复、可重试）
- [x] 启动时 reclaim `pending` / 卡住的 `running`
- [x] `GET /jobs` + `GET /jobs/{id}`
- [x] 文件/笔记/链接入库走 durable dispatcher（递归 crawl 仍内存队列）

## Phase 3 — Architecture

- [x] `lifespan` 替代 `on_event`
- [x] 拆出 `backend/api/routers/{jobs,documents,chat,files,links}.py`
- [x] thin services：`services/{ingestion,search,chat}.py`
- [x] auth 留在 `backend/api/router.py`（瘦身）
- [x] 核心路径 pytest 冒烟：`tests/test_smoke_architecture.py`

## Phase 4 — Document Parsers

- [x] Parser 插件：`backend/parsers/`（text/pdf/docx/pptx）
- [x] `load_and_chunk_document` 统一入库路径
- [x] FE/BE 扩展名白名单对齐（含 docx/pptx）
- [x] requirements 增加 pypdf / python-docx / python-pptx

## Phase 5 — RAG Quality

- [x] Lance metadata 增加稳定 `user_id`（兼容旧 `belongs_to=email`）
- [x] 尽力创建向量 ANN 索引（`ensure_vector_ann_index`，小数据跳过）
- [x] search 传入 `user_id`
- [ ] hybrid / rerank（后续）
- [x] score 语义：engine-native distance；见下方说明

## Phase 6 — Chat on Backend

- [x] `POST /chat` SSE：retrieve → prompt → stream Ollama
- [x] citations 事件 + token 事件
- [x] `GET /chat/models`
- [x] FE 改为优先调 BE `/chat` SSE（失败再回退直连 Ollama）
- [x] `use_rag` 开关（non-context 模式）

## Phase 7 — Product / Frontend

- [ ] Vue（或其它）替代 Streamlit 门面
- [ ] docker-compose
- [ ] 删除策略：可选硬删磁盘文件

---

**原则：** 每一阶段保持可运行；不一次推翻目录。

### 关键新 API

| Method | Path | 说明 |
|---|---|---|
| GET | `/jobs` | 当前用户任务列表 |
| GET | `/jobs/{id}` | 任务详情 |
| POST | `/documents/search` | 检索（支持 user_id 过滤） |
| POST | `/chat` | SSE RAG 对话 |
| GET | `/chat/models` | Ollama 模型列表 |

### RAG score 说明

Lance 返回的 `score` 当前为引擎原生 `_distance`（通常越小越近，取决于 metric）。客户端不要直接当成 0–1 相似度百分比，除非后续做归一化。
