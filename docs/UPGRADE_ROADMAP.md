# Progressive Upgrade Roadmap

项目采用分阶段演进策略，保持架构清晰与运行稳定。
如果基于本仓库代码公开发布衍生版本，请遵循 AGPL-3.0 许可协议的相关条款。

## Phase 1: Reliability & Safety Baseline

- [x] 修复 `update_note` 空指针判断与状态流转
- [x] 文件与笔记后台 Worker：状态记录为 `IN_PROGRESS` / `FAILED` 并持久化 `error_message`
- [x] 后端上传防护：扩展名白名单校验与文件体积上限限制
- [x] 配置收紧：保守的并发默认值，默认占位密钥启动告警
- [x] 轻量 Schema 迁移机制（基于 SQLite `ALTER TABLE`）
- [x] PDF 抽取失败显式抛出异常，消除静默假成功
- [x] Lance 检索过滤表达式安全转义

## Phase 2: Durable Jobs

- [x] 引入 `ingestion_jobs` 持久化任务表，支持故障恢复与重试
- [x] 服务启动时自动认领并恢复 `pending` 与中断的 `running` 任务
- [x] 提供任务查询接口：`GET /jobs` 与 `GET /jobs/{id}`
- [x] 文件、笔记与网页链接入库接入持久化调度管道

## Phase 3: Architecture Decoupling

- [x] 使用 FastAPI `lifespan` 机制替代废弃的 `on_event`
- [x] 拆分路由模块：`backend/api/routers/{jobs,documents,chat,files,links}.py`
- [x] 业务服务分层：建立 `backend/api/services/` 业务与事务编排层
- [x] 认证模块重组：基础鉴权逻辑集中在 `backend/api/router.py`
- [x] 建立自动化架构冒烟测试：`tests/test_smoke_architecture.py`

## Phase 4: Document Parsers

- [x] 文档解析插件化：`backend/parsers/`（支持 text, pdf, docx, pptx）
- [x] 建立 `load_and_chunk_document` 统一入库路径
- [x] 前后端文件扩展名白名单统一校验
- [x] 完善依赖环境支持（pypdf, python-docx, python-pptx）

## Phase 5: RAG Quality & Hybrid Search

- [x] Lance 元数据增加稳定 `user_id`，兼容历史 `belongs_to` 字段
- [x] 向量索引构建：小数据跳过，达到阈值自动创建 ANN 索引
- [x] 检索链路全程贯穿 `user_id` 行级租户作用域过滤
- [x] 混合检索 (Hybrid Search)：实现向量与 SQLite FTS5 的非对称加权 RRF 融合
- [x] 检索分腿并行加速与单腿异常 Fail-open 降级
- [x] 引入 MS MARCO 标准化评测体系 (`eval/`)，确立默认关闭 MMR 的门禁决策

## Phase 6: Chat on Backend & Refusal

- [x] 后端接管 RAG 编排：`POST /chat` SSE 实现流式生成
- [x] SSE 消息事件流：支持 citations 引用事件与 token 流
- [x] 提供可用模型列表查询：`GET /chat/models`
- [x] 空检索拒答机制：当 `RAG_REFUSE_ON_EMPTY=true` 且无检索命中时直接返回提示，抑制幻觉生成
- [x] 前端问答模式扩展：支持 context-aware、non-context 与 only-links 模式

## Phase 7: Product & Deployment

- [x] 前端重构：采用 Vue 3 + Vite 现代化 SPA 架构（`web/`）
- [x] 容器化交付：提供开箱即用的 `docker-compose.yml` 配置
- [x] 统一持久化兼容：容器环境与本地脚本共享宿主机数据目录
- [x] 磁盘文件软删除与数据库状态联动

## Phase 8: Engineering Purification & Solidification

- [x] 历史代号清理：移除历史 `inquisitive` CLI 别名，统一为 `wenjv*` 标准入口；启动脚本统一为 `start-wenjv.bat` 与 `wenjv_launcher.py`
- [x] 数据向后兼容：保留对 `~/.config/inquisitive` 与 `inquisitive.db` 的只读自动探测与平滑回退
- [x] 路由层彻底纯化：将 Router 中残留的 ORM Session 操作与复杂事务彻底下沉至 Service 层
- [x] 管道异常加固：修复耐久任务假成功、扫描件 PDF 异常路由与 URL 抓取失败状态落库
- [x] 技术文档重构与去 AI 化：全量更新 17 份技术规范与说明文档，确保参数真实与表述客观

---

### 核心接口清单

| 方法 | 路径 | 功能说明 |
|---|---|---|
| GET | `/jobs` | 当前用户的入库任务列表 |
| GET | `/jobs/{id}` | 任务详情与处理状态 |
| POST | `/documents/search` | 向量与混合检索（强制携带租户过滤） |
| POST | `/chat` | 基于知识库依据的 SSE 流式问答 |
| GET | `/chat/models` | 可用大语言模型列表 |

### 向量检索分数量纲说明

LanceDB 返回的 `score` 字段为引擎底层原生距离度量值（Distance）。数值越小代表相关度越高，客户端展示或业务判断时不要直接将其等同于 0 到 1 的相似度百分比。
