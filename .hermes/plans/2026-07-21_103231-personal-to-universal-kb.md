# 个人知识库 → 高效率通用知识库 升级计划

> **For Hermes:** Use subagent-driven-development skill to implement this plan phase-by-phase (not all at once).  
> **Mode:** Plan only — 本文档是路线图 + 可执行任务切片，不在本文件内直接改业务代码。

**Goal:** 在现有「个人知识库（FastAPI CRUD + 异步向量化 + RAG 对话）」底座上，分阶段演进为**高效率、可协作、可治理的通用知识库**（个人/小团队/部门级通用，而非一次性企业套件重写）。

**Architecture（目标态）:**  
关系库继续管 **权威元数据与生命周期**；向量库管 **语义召回**；可选全文索引管 **关键词召回**；入库走 **可观测、可重试的 ingestion pipeline**；问答走 **后端统一 RAG + 引用**；多租户以 **workspace/org + RBAC** 扩展用户隔离；前端从 Streamlit 联调壳升级为 **可日常使用的 Web 客户端**。保持 YAGNI：先通用效率，再企业级花活。

**Tech Stack（延续 + 渐进加）:**  
Python 3.11+ / FastAPI / SQLAlchemy / SQLite→Postgres / LanceDB(+可选全文) / Ollama / JWT / （后期）Vue 或现有 Streamlit 增强 / pytest / docker-compose

**License 约束:** 仓库 AGPL-3.0；对外分发/SaaS 需遵守 AGPL。计划内不假设闭源商业分发。

---

## 0. 当前上下文与假设

### 0.1 现有项目已具备（底座）

| 能力 | 现状路径/说明 |
|------|----------------|
| Auth JWT | `backend/api/router.py`, `dependencies.py` |
| Note/File/Link CRUD | `backend/api/routers/files.py`, `links.py` |
| 可恢复入库任务 | `backend/worker/durable_jobs.py`, `IngestionJob` |
| 解析插件 | `backend/parsers/`（text/pdf/docx/**pptx**；无 .ppt/OCR） |
| 检索 | `backend/api/services/search.py`, `vector_store/lance_db.py` |
| 对话 SSE | `backend/api/routers/chat.py`, `services/chat.py` |
| FE 优先走 BE chat | `frontend/utils.py`, `streamlit_ui.py` |
| 用户隔离 | SQL `user_id` + 向量 `user_id`/`belongs_to` |
| 测试 | `tests/test_smoke_architecture.py`（冒烟级） |

### 0.2 明确未做/偏弱（本计划要覆盖）

- PPT 解析偏「抽字」；无 OCR；chunk 策略单一  
- **未真正落地 HNSW**（Lance 侧 ANN 尽力 IVF_PQ，小数据可能 flat）  
- 无 hybrid（BM25+向量）、无 rerank  
- 无质量评估集、无「过期/冲突」治理  
- 无 workspace/角色/审核流  
- Streamlit 非长期通用 UI；无 docker-compose  
- DAO 层未抽干净；LangChain 仅胶水但依赖仍重  

### 0.3 假设

- 第一用户画像：个人 → 2～20 人小团队「通用知识库」，不是 500+ 人复杂 IAM  
- 默认本地/内网 Ollama；可后接云 API  
- 实施者熟悉 Python，正在补 FastAPI/RAG 基础（见会话内学习清单）  
- **不**在本阶段做 K8s/Go 重写（属作品集其它线）

---

## 1. 传统知识库痛点（深度综合）→ 产品对策

综合公开讨论与行业材料中的高频痛点（信息孤岛、检索差、内容腐烂、更新滞后、参与度低、权限与信任等），映射到「通用高效知识库」能力：

| # | 传统/遗留知识库痛点 | 用户体感 | 通用知识库应对能力 | 本项目跃迁优先级 |
|---|---------------------|----------|--------------------|------------------|
| P1 | **信息孤岛 / 多套库** | 不知道去哪找 | 统一入口 + 多源接入（笔记/文件/链接/目录同步）+ 全局搜索 | P0 |
| P2 | **检索弱（纯关键词/目录）** | 找不到、找不对 | 语义检索 + 关键词 hybrid + 过滤/权限 | P0 |
| P3 | **内容过期/冲突/重复** | 不敢信答案 | 新鲜度、版本、冲突标记、废弃策略、引用带来源 | P0–P1 |
| P4 | **更新滞后、维护贵** | 文档发布即过时 | 低摩擦录入、异步入库、状态可见、失败可修、后续：变更检测 | P0 |
| P5 | **AI 幻觉 / 不可追溯** | 答得像真的但是错的 | 强制 citation、无命中拒答、置信/空结果策略 | P0 |
| P6 | **切片/解析差导致答不准** | 「库里有但答不出」 | 解析质量、chunk 策略、页/slide 定位、可选 QA 对 | P1 |
| P7 | **权限与泄露风险** | 怕越权 | workspace + RBAC + 向量侧强制 filter | P1 |
| P8 | **参与度低 / 无归属** | 没人写文档 | 贡献者、简单审核、使用分析（什么被问到） | P2 |
| P9 | **多端/多格式支持差** | 办公文档进不去 | 稳健 pdf/docx/pptx + 后续 OCR | P1 |
| P10 | **规模性能** | 一慢就弃用 | 真索引（ANN）、任务背压、Postgres、连接池 | P1–P2 |
| P11 | **与业务脱节** | 库是库、活是活 | API/Webhook/目录同步；先做好 API 通用性 | P2 |
| P12 | **评估缺失** | 不知变好还是变差 | 黄金集、命中率/引用率人工抽检 | P1 |

**「高效率」在本计划中的可操作定义（验收用语）：**

1. **找得到**：P@k / 人工抽检命中率可测、可对比  
2. **信得过**：默认带引用；无依据可拒绝  
3. **跟得上**：入库异步 + 状态/错误可见 + 可重试  
4. **进得去**：常见办公格式稳定；失败可解释  
5. **分得清**：按人/空间隔离，不串库  
6. **用得快**：常见库规模下检索+首 token 可接受（本地模型另计）

---

## 2. 目标产品形态（通用知识库 MVP+）

### 2.1 角色

| 角色 | 能力 |
|------|------|
| Viewer | 检索、问答、看自己有权的引用 |
| Editor | 上传/笔记/链接、重跑失败任务 |
| Admin | 空间设置、成员、模型/索引配置、评估集 |

个人模式 = 单用户自动 Admin（兼容现状）。

### 2.2 核心对象（在现有模型上演进）

```text
User
Workspace (新增，通用化关键)
  ├── Membership (user, role)
  ├── SourceDocument (统一 Note/File/Link 的上层或并行)
  ├── IngestionJob (已有，挂 workspace_id)
  ├── ChunkMeta (可选落库，对齐向量 chunk)
  ├── Conversation / Message (可选)
  └── EvaluationCase (黄金问句)
```

近阶段允许 **先保留 Note/File/Link 三表**，加 `workspace_id`；不必第一天合并成单一 Source 表（YAGNI）。

### 2.3 API 面（稳定对外，UI 可换）

保持并强化：

- `/auth/*`
- `/workspaces/*`（新）
- `/file/*` `/links/*`（加 workspace 作用域）
- `/documents/search`
- `/chat` SSE
- `/jobs`
- `/admin/metrics`（后）
- `/eval/*`（后）

---

## 3. 分阶段路线图（总览）

| Phase | 名称 | 解决痛点 | 成功标准（可演示） | 预估 |
|-------|------|----------|-------------------|------|
| **G0** | 巩固个人高效底座 | P4/P5 基线 | 文档+测试+评估脚本骨架；聊天必带引用 | 3–5 天 |
| **G1** | 检索效率与可信 | P2/P5/P6 | hybrid 或等价提升；评估集 20 问可跑 | 1–2 周 |
| **G2** | 内容治理 | P3/P4 | 新鲜度字段、失败任务修复流、重复/过期标记 | 1–2 周 |
| **G3** | 多用户通用空间 | P1/P7 | workspace + 角色；串库测试 | 1–2 周 |
| **G4** | 解析与定位质量 | P6/P9 | chunk 策略分类型；引用可回跳页/slide | 1–2 周 |
| **G5** | 性能与部署 | P10 | 真 ANN 可验证；docker-compose 一键 | 1 周 |
| **G6** | 体验与增长 | P8/P11 | Web UI 主路径 or Streamlit 产品化；使用统计 | 2+ 周 |

**与旧 UPGRADE_ROADMAP 关系：**  
个人线 1–6 已完成的作为 G0 输入；原「HNSW/hybrid/Vue/docker」并入 G1/G5/G6，不再当孤立彩蛋。

---

## 4. Phase G0 — 巩固个人高效底座

**Objective:** 不扩业务大面，先让「个人库」达到可量化、可回归的高效基线。

### Task G0.1: 建立评估目录与 20 条黄金问句模板

**Files:**
- Create: `eval/README.md`
- Create: `eval/golden_set.example.json`
- Create: `eval/datasets/.gitkeep`

**`eval/golden_set.example.json` 形状：**

```json
{
  "version": 1,
  "cases": [
    {
      "id": "Q001",
      "question": "项目的 JWT 默认过期时间是多久？",
      "expect_keywords": ["JWT", "过期", "分钟"],
      "expect_source_substrings": ["config"],
      "notes": "应命中配置相关笔记/文件"
    }
  ]
}
```

**验证:** 文件存在且 JSON 可被 `json.load`。

### Task G0.2: 最小评估脚本（search only）

**Files:**
- Create: `scripts/eval_search.py`
- Test: `tests/test_eval_script_smoke.py`

**行为:**
1. 读 `eval/golden_set.json`（或 example）  
2. 对每条 call 内部 `search_service.search_documents`（或 HTTP）  
3. 输出：命中关键词比例、是否出现 expect_source_substrings  
4. 打印 summary JSON 到 stdout  

**Run:**  
`python scripts/eval_search.py --dataset eval/golden_set.example.json`  
Expected: 无后端时可 mock；有后端时输出 `passed/total`。

### Task G0.3: Chat API 契约测试（citations 必有）

**Files:**
- Modify: `backend/api/services/chat.py`（仅当缺字段时）
- Create: `tests/test_chat_events_unit.py`

**断言:**
- `use_rag=True` 时事件序列允许：`citations` → (`token`)* → `done`  
- `citations` 项含 `source` 或 `snippet`  
- `use_rag=False` 时 `citations` 可为 `[]` 但仍先发 citations 事件  

**Run:** `pytest tests/test_chat_events_unit.py -v`

### Task G0.4: README 增加「通用化愿景」一小节（链到本 plan）

**Files:**
- Modify: `README.md`（简短「演进方向」+ 链接 `.hermes/plans/2026-07-21_103231-personal-to-universal-kb.md`）

### Task G0.5: 基线手工验收清单

写在 `eval/BASELINE_CHECKLIST.md`：

- [ ] 上传 md/pdf/docx/pptx 各 1  
- [ ] job 失败可在 `/jobs` 看到 error  
- [ ] search 返回分数与来源  
- [ ] chat 流式 + 侧栏引用  
- [ ] 两用户互不可见（注册两号验证）

---

## 5. Phase G1 — 检索效率与可信（高效率核心）

**Objective:** 针对 P2/P5，让「找得到、信得过」明显好于纯向量 Top-K。

### Task G1.1: 检索结果规范化 score

**Files:**
- Modify: `backend/vector_store/lance_db.py`（`fetch_documents` 返回）
- Modify: `backend/api/services/search.py`
- Modify: `backend/api/schemas.py`（可选 `score_type: distance|similarity`）

**规则（选一写清文档）:**
- 方案 A: 增加 `distance` 与 `similarity` 双字段  
- 方案 B: 仅文档约定 + 日志  

**推荐方案 A 最小实现：** Response 增加可选 `score_type`。

### Task G1.2: SQLite FTS5 关键词召回

**Files:**
- Create: `backend/search/fts.py`
- Modify: `backend/database.py`（建 `chunks_fts` 或 `documents_fts` 表）
- Modify: `backend/worker/durable_jobs.py` / 向量写入成功回调处写入 FTS  
- Modify: `backend/api/services/search.py` 增加 `hybrid_search`

**算法（简单可用）:**
1. `vector_hits = top_k * 3`  
2. `fts_hits = top_k * 3`  
3. RRF 融合：`score = Σ 1/(60+rank)`  
4. 截断 top_k，附 `match_type: vector|fts|both`

**测试:**
- `tests/test_hybrid_rrf.py`：纯函数测 RRF 排序  

### Task G1.3: Search API 开关

**Files:**
- Modify: `backend/api/schemas.py` → `DocumentSearchRequest.mode: semantic|keyword|hybrid = hybrid`
- Modify: `backend/api/routers/documents.py`
- Modify: `frontend/utils.py` `fetch_documents` 传 mode（可选 UI 以后再加）

### Task G1.4: 拒答策略强化

**Files:**
- Modify: `backend/api/services/chat.py` `build_messages` / `rag_chat_events`

**规则:**
- `use_rag=True` 且 citations 为空 → 不调用 LLM，直接 token/事件返回固定拒答文案（或单条 token）  
- 有 citations 才 stream Ollama  

**验证:** 单元测试空 citations 路径不调用 `stream_ollama_chat`（mock）。

### Task G1.5: 跑黄金集对比 semantic vs hybrid

**Run:**  
`python scripts/eval_search.py --mode semantic`  
`python scripts/eval_search.py --mode hybrid`  
**记录:** `eval/results/YYYYMMDD_baseline.json`（手动或脚本写出）

---

## 6. Phase G2 — 内容治理（对抗腐烂）

**Objective:** 解决「过期/失败/重复导致不敢用」。

### Task G2.1: 资源治理字段

**Files:**
- Modify: `backend/api/models.py`  
  - `Note`/`FileUpload`/`Link` 增加：  
    - `freshness_at` (DateTime, 内容变更时间)  
    - `is_stale` (bool, default False)  
    - `stale_reason` (str, nullable)  
    - `content_hash` (str, nullable)  
- Modify: `backend/database.py` `_ensure_sqlite_columns` 补列  

### Task G2.2: 入库写 content_hash

**Files:**
- Modify: `backend/core/utils.py` 或 parsers 出口  
- Modify: durable job 成功路径更新 hash + freshness_at  

**用途:** 相同 hash 跳过重复 embedding（效率）。

### Task G2.3: Job 管理 API

**Files:**
- Modify: `backend/api/routers/jobs.py`  
  - `POST /jobs/{id}/retry`  
  - `GET /jobs?status=failed`  

**Service:** `backend/api/services/ingestion.py` 增加 `retry_job`.

### Task G2.4: 简单重复检测（按 hash + 标题）

**Files:**
- Create: `backend/api/services/governance.py`  
- Endpoint（可选）: `GET /documents/duplicates`  

### Task G2.5: 引用展示新鲜度

**Files:**
- Modify: chat citations 增加 `freshness_at`（若有）  
- FE: `citations_to_docs` 带上该字段（Streamlit 侧栏可显示「更新于」）

---

## 7. Phase G3 — Workspace 通用化（从「我的」到「我们的」）

**Objective:** 小团队可共用一个知识空间且不串数据。

### Task G3.1: Workspace 模型

**Files:**
- Modify: `backend/api/models.py`

```python
class Workspace(Base):
    __tablename__ = "workspaces"
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    slug = Column(String, unique=True, index=True)
    created_at = Column(DateTime, server_default=func.now())

class WorkspaceMember(Base):
    __tablename__ = "workspace_members"
    id = Column(Integer, primary_key=True)
    workspace_id = Column(Integer, ForeignKey("workspaces.id"), index=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True)
    role = Column(String, default="editor")  # viewer|editor|admin
```

- Note/File/Link/IngestionJob 增加 `workspace_id`（可空=个人默认空间）

### Task G3.2: 默认空间迁移

**Files:**
- Create: `scripts/migrate_personal_workspaces.py`  
- 为每个 User 创建 `ws-personal-{id}`，回填已有资源  

### Task G3.3: 依赖注入当前 workspace

**Files:**
- Modify: `backend/api/dependencies.py`  
  - `get_current_workspace`：header `X-Workspace-Id` 或 query  
  - 校验 membership  

### Task G3.4: 全路由作用域替换

**Files:**
- Modify: `routers/files.py`, `links.py`, `documents.py`, `chat.py`, `jobs.py`  
- 所有 query 增加 `workspace_id` 条件  
- 向量 metadata 增加 `workspace_id`；search filter 强制带上  

**测试:**
- `tests/test_workspace_isolation.py`：用户 A 空间数据 search 不可见 B  

### Task G3.5: 成员管理 API

- `POST /workspaces`  
- `POST /workspaces/{id}/members`  
- `GET /workspaces`  

---

## 8. Phase G4 — 解析与 Chunk 质量（含 PPT「别再太糙」）

**Objective:** 针对 P6/P9；在你补完文档知识后实施，避免过早炫技。

### Task G4.1: Chunk 策略配置化

**Files:**
- Modify: `backend/config.py`  
  - `CHUNK_SIZE_TEXT`, `CHUNK_SIZE_PDF`, `CHUNK_SIZE_PPTX`, overlaps  
- Modify: `backend/core/utils.py` `load_and_chunk_document` 按 parser meta 分支  

### Task G4.2: PPTX 增强（第二代，非重写）

**Files:**
- Modify: `backend/parsers/pptx_parser.py`  
  1. 抽取 `notes_slide` 备注  
  2. 表格 shape 尝试按 cell 拼接  
  3. meta 保留 `slide_title`（若有）  
- Create: `tests/fixtures/sample.pptx`（最小夹具）  
- Create: `tests/test_pptx_parser.py`  

**不做（本阶段 YAGNI）:** OCR、动画、老 `.ppt`。

### Task G4.3: PDF 定位增强

**Files:**
- Modify: `backend/parsers/pdf_parser.py` 保证 page 稳定  
- Citations 已含 page；FE「View Document」跳页验证  

### Task G4.4:（可选）Q-A 块模式实验

**Files:**
- Create: `backend/rag/chunking_qa.py`  
- 仅当评估集证明传统切片不足时启用开关 `CHUNK_MODE=paragraph|qa_hint`

---

## 9. Phase G5 — 性能与部署

### Task G5.1: 向量索引可验证

**Files:**
- Modify: `backend/vector_store/lance_db.py` `ensure_vector_ann_index`  
  - 成功/失败结构化日志：`index_type`, `rows`, `ok`  
  - 配置 `VECTOR_INDEX_MIN_ROWS`, `VECTOR_INDEX_TYPE=IVF_PQ|AUTO`  
- Create: `scripts/report_vector_index.py` 打印当前表行数与索引状态（能查则查）  

**说明:** 真 HNSW 仅当目标引擎+版本支持时单独立项；默认诚实使用 IVF_PQ/AUTO。

### Task G5.2: Postgres 可选

**Files:**
- Modify: `backend/config.py` `DATABASE_URL`  
- Modify: `database.py` 去掉 sqlite-only 假设  
- Docs: README 一节  

### Task G5.3: docker-compose

**Files:**
- Create: `docker-compose.yml`  
  - `api` (uvicorn)  
  - `ui` (streamlit)  
  - 可选 `ollama`（或 document 使用 host ollama）  
- Create: `Dockerfile.api`, `Dockerfile.ui`  

**验证:** `docker compose up --build` 后 `/ping` 通。

### Task G5.4: 背压与限流

- 上传/chat 简易 rate limit（按 user）  
- job 并发已有；补全局队列深度指标日志  

---

## 10. Phase G6 — 体验与「通用产品」外壳

### Task G6.1: Streamlit 产品化（低成本）或 Vue MVP（高成本二选一）

**路径 A（快）:** 强化 Streamlit  
- 工作空间切换器  
- 失败任务面板  
- search mode 切换  
- 评估结果页  

**路径 B（作品集门面）:** `frontend-web/` Vue3  
- 登录、库列表、上传、聊天（SSE）、引用列表  
- 只消费 API，零业务逻辑  

**建议:** G3 完成前走路径 A；作品集冲刺再 B。

### Task G6.2: 使用分析（治 P8）

- 表 `query_logs(question, user_id, workspace_id, hit_count, created_at)`  
- chat/search 各写一条  
- Admin：Top 问题、零命中问题（驱动补文档）

### Task G6.3: 导入出口

- `POST /import/zip` 批量 md  
- `GET /export/workspace.zip`  

---

## 11. 近端实施顺序（建议你个人执行的 10 个下一步任务）

按依赖排序，**先做完这 10 个再开 Workspace**：

1. G0.1 评估目录与 example 黄金集  
2. G0.2 `scripts/eval_search.py`  
3. G0.3 chat citations 单测  
4. G0.5 手工基线清单跑一遍  
5. G1.4 空引用拒答（立刻提升「可信」）  
6. G1.1 score 语义字段  
7. G1.2 FTS + RRF 纯函数 + 接入  
8. G1.3 Search mode API  
9. G1.5 黄金集对比留结果  
10. G2.3 Job retry API（效率/可运营）

之后：G3 Workspace → G4 解析增强 → G5 docker/索引 → G6 UI。

---

## 12. 关键文件地图（实施时高频）

| 区域 | 路径 |
|------|------|
| 入口 | `backend/main.py` |
| 检索 | `backend/api/services/search.py`, `routers/documents.py` |
| 对话 | `backend/api/services/chat.py`, `routers/chat.py` |
| 入库 | `backend/worker/durable_jobs.py` |
| 解析 | `backend/parsers/*.py`, `backend/core/utils.py` |
| 向量 | `backend/vector_store/lance_db.py` |
| 模型 | `backend/api/models.py`, `database.py` |
| 前端 API | `frontend/utils.py`, `frontend/streamlit_ui.py` |
| 配置 | `backend/config.py` |
| 测试 | `tests/` |
| 评估 | `eval/`, `scripts/eval_search.py` |

---

## 13. 测试与验证策略

| 层级 | 内容 | 命令/方式 |
|------|------|-----------|
| 单元 | RRF、拒答、parser 小夹具 | `pytest tests/ -q` |
| 契约 | OpenAPI 关键路径仍注册 | smoke + 可选 schemathesis 以后 |
| 评估 | 黄金集 semantic/hybrid | `python scripts/eval_search.py` |
| 隔离 | 两用户/两 workspace | `tests/test_workspace_isolation.py` |
| 手工 | BASELINE_CHECKLIST | 每次发版前 |
| 性能 | 1k/10k chunk 下 p95 检索 | 脚本 + 日志 |

**Definition of Done（通用知识库 MVP）:**

- [ ] hybrid 检索可开关且评估集不弱于 semantic  
- [ ] chat 空库拒答；有库必带 citations  
- [ ] failed job 可 retry  
- [ ] workspace 隔离测试通过  
- [ ] docker-compose 可起 API（UI 可选）  
- [ ] README 与 plan 链接一致，无虚假「已用 HNSW」表述  

---

## 14. 风险、权衡、开放问题

### 风险

| 风险 | 缓解 |
|------|------|
| 过早上 Workspace 导致个人路径回归 | 默认自动个人空间；header 可缺省 |
| FTS 与向量双写不一致 | 同 job 成功提交；重建脚本 |
| 本地 LLM 拖慢「高效」体感 | 指标分开：检索延迟 vs 生成延迟 |
| AGPL 限制商业闭源 SaaS | 作品集/自托管叙事；商用另案 |
| 解析完美主义拖死进度 | G4 分代；先 hash 去重与拒答 |

### 权衡

- **Streamlit vs Vue:** 速度 vs 作品集观感 → 分阶段  
- **SQLite vs Postgres:** 个人默认 SQLite；通用小团队再 Postgres  
- **LangChain:** 保持胶水或逐步去除；G1 不必引入更多 LC  
- **HNSW:** 不作为营销点；有需要再单独立项验证  

### 开放问题（实施前可再定）

1. 通用化第一客户：仅个人加强，还是必须 2 周内多用户？  
2. UI：G6 走 Streamlit 产品化还是直接 Vue？  
3. 默认检索 mode：`hybrid` 还是 `semantic`？  
4. 是否要做「目录同步」（本地 folder watch）还是 API/上传足够？  
5. 评估集语言：中文为主还是中英混合？  

---

## 15. 与学习清单的衔接

实施本 plan 时，建议你同步的基础（已在会话列出，此处只钉依赖）：

| Plan Phase | 你应先掌握 |
|------------|------------|
| G0–G1 | HTTP/FastAPI、embedding/检索直觉、pytest |
| G2 | 状态机、哈希、一致性 |
| G3 | 鉴权 vs 授权、多租户 filter |
| G4 | 文档结构、chunking |
| G5 | ANN 概念、Docker 基础 |
| G6 | 前端消费 SSE、产品度量 |

---

## 16. 执行方式建议

1. **不要**一次性实现 G0–G6。  
2. 每个 Task 单独分支/提交：`feat(g1): hybrid rrf pure function` 这类。  
3. 每完成一个 Phase，跑：  
   - `pytest tests/ -q`  
   - `python scripts/eval_search.py`（若已有）  
   - 手工 BASELINE 子集  
4. 可用 Hermes `subagent-driven-development`：**一次一个 Task**，先 G0.1。  

---

## 17. 一句话愿景

> 把现在的「能跑的个人 RAG 库」，升级成「找得到、信得过、跟得上、分得清、可评估」的通用知识库；  
> 用治理与检索效率对抗传统知识库的腐烂与孤岛，而不是用更多模型幻觉掩盖内容问题。

---

**Plan complete.**  
实现时从 **§11 近端 10 任务** 的 Task 1（G0.1）开始即可。
