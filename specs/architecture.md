# 架构规范（Architecture）

## 1. 目标形态

自托管知识库：

- **CRUD**：笔记 / 文件 / 链接  
- **异步入库**：解析 → 切块 → embedding → 向量库  
- **检索 + 对话**：后端统一编排，SSE 流式回答并带引用  

## 2. 逻辑分层

```text
HTTP Routers (backend/api/routers/*, auth in router.py)
    → Services (backend/api/services/*)   # 编排，无 HTTP 细节堆砌
        → ORM / SQLAlchemy session       # 元数据
        → Workers (backend/worker/*)     # 长时间任务
        → Parsers (backend/parsers/*)    # 纯解析
        → Vector store (backend/vector_store/*)
```

| 层 | 允许 | 禁止 |
|----|------|------|
| Router | 参数校验、鉴权依赖、状态码、调 service | 大段业务、直接 embed |
| Service | 用例编排、事务边界意识 | 绑死 Streamlit |
| Worker | 入库、重试、调用 parser/vector | 返回 HTTP |
| Parser | 文件→文本+meta | 写库、调 Ollama |
| Vector | 增删查向量 | 用户密码、JWT |

现状：部分 SQL 仍在 router；**新代码优先下沉 service**，旧代码渐进搬迁。

## 3. 双存储

| 存储 | 职责 | 默认实现 |
|------|------|----------|
| 关系库 | 用户、资源元数据、任务、状态 | SQLite（`~/.config/inquisitive/`） |
| 向量库 | chunk 向量与检索 meta | LanceDB（可切换 Chroma/Milvus Lite） |

原则：

- **元数据权威在 SQL**；向量是派生物。  
- 更新/删除必须考虑 **两边**（允许最终一致，但要有明确策略）。  
- 向量 meta 必须能过滤租户：`user_id`（及兼容 `belongs_to`）；未来 `workspace_id`。

## 4. 运行时拓扑

```text
Streamlit UI (:8501) --JWT--> FastAPI (:8000)
                                ├─ lifespan: create tables, job workers
                                ├─ Ollama (embed + chat)
                                ├─ SQLite
                                └─ Vector DB files
```

- 入口：`backend/main.py`（`lifespan`，禁止回到全局 `on_event` 启动关键逻辑）。  
- CLI：`inquisitive-start-backend` / `inquisitive-start-ui`（包名兼容，产品名「个人知识库」）。

## 5. 目录约定

| 路径 | 用途 |
|------|------|
| `backend/api/routers/` | 按域拆分路由 |
| `backend/api/services/` | 用例服务 |
| `backend/parsers/` | 可插拔解析器 + registry |
| `backend/worker/` | durable jobs、URL 处理 |
| `backend/vector_store/` | 向量引擎适配 |
| `frontend/` | Streamlit 联调/使用 UI |
| `tests/` | 自动化测试 |
| `specs/` | 本规范 |
| `eval/` | （规划）评估集，见升级 plan |
| `.hermes/plans/` | 实施计划 |

## 6. 扩展点

- **新文件类型**：`backend/parsers/` 新 Parser + registry + 白名单配置。  
- **新向量后端**：实现与 adapter 相同的 add/search/delete 语义。  
- **新用例**：先 service 方法，再薄 router。

## 7. 非架构（明确不做）

- 不在本阶段引入独立微服务拆分。  
- 不把 Streamlit 当唯一长期架构中心；API 才是稳定边界。  
- 不把 LangChain Agent 作为主干（允许少量胶水：切块/Embedding）。
