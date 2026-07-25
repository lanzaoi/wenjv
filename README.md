# 个人知识库（CRUD + RAG）

自托管的个人知识库系统：管理 **笔记 / 文件 / 网页链接**，异步向量化入库，并提供 **带引用的检索与流式问答**。

- **后端**：FastAPI + SQLAlchemy + JWT  
- **前端**：Streamlit（联调 UI）  
- **关系库**：SQLite（默认可换）  
- **向量库**：LanceDB（默认；可选 Chroma / Milvus Lite）  
- **模型**：本地 [Ollama](https://github.com/ollama/ollama)（Embedding + 对话）

适合本地单机或小团队内网自用；强调「可恢复入库 + 后端统一 RAG 编排」，而不是只做聊天 Demo。

---

## 功能特性

### 知识源

| 类型 | 能力 |
|------|------|
| **笔记** | Markdown 创建 / 编辑 / 列表 / 删除；改后自动刷新向量 |
| **文件** | 上传、状态轮询、下载；支持 txt / md / pdf / docx / pptx / csv / json 等（可配置） |
| **链接** | 单条 / 批量提交；抓取正文后入库；可选实验性递归抓取 |

### 工程能力 (v1.3 强固与标准化)

- **严密的多租户安全隔离**：基于 **JWT 鉴权** 与 `user_id` / `belongs_to` 硬过滤，通过矩阵测试用例验证从 API 接口到底层向量检索的100%跨租户隔离防御。  
- **异步任务队列与失败重试**（`ingestion_jobs`）：支持状态转换（pending → running → succeeded/failed）、超时自动回收及新增的 `POST /jobs/{id}/retry` 失败或撤销任务重试端点。  
- **高精准检索与重排管线**：支持基于向量与 SQLite FTS5 词法补充的混合检索 (Hybrid Search)、等权 RRF 融合计算及 MMR 边际多样性去重过滤。  
- **量化评估与配置门禁**：内置基于 MS MARCO 数据集的标准化检索评分评估系统 (`eval/`) 与 4 组矩阵测试跑批，以数据门禁文档（`gate_decision.md`）指导默认配置。  
- **生产级 Docker Compose 部署**：支持 `docker-compose up` 一键拉起，采用非 root 专用账户 (`appuser`) 安全运行、零凭据外泄配置，并与本机直接运行共享统一持久化数据。  
- **嵌入式向量存储引擎**：默认采用单文件高性能 LanceDB 引擎（选型论证详见 [ADR 0001](./specs/adr/0001-lance-vs-pgvector.md)；我们恪守诚实原则，在个人自用与小团队规模下不宣称且不滥用服务器端 pgvector）。  
- **可插拔文档解析**（`backend/parsers/`）：支持 text / pdf / docx / pptx，提供清晰的容错与报错反馈。  
- **后端统一 RAG 编排**：`POST /chat` SSE 流式输出（附带 citations 与 token 流）；避免前端直接直连大模型。  
- **资源安全与自检 API**：上传文件扩展名白名单 + 25 MiB 体积上限防御，提供启动后可直接访问的 `/redoc` 与 `/ping` 接口。

### 对话模式（前端）

- **context-aware**：检索 + 仅基于上下文回答  
- **non-context**：不强制 RAG，普通问答  
- **only-links**：只展示检索引用，不生成回答  
- 快捷过滤：`/notes`、`/files`、`/links` 等提示词前缀  

---

## 架构概览

```text
Streamlit UI (:8501)
        │  Bearer JWT
        ▼
FastAPI (:8000)
  ├── routers: auth / file / links / documents / jobs / chat
  ├── services: ingestion / search / chat
  ├── SQLite  ← 用户、资源元数据、任务表
  ├── durable worker → parsers → embeddings → Vector DB
  └── /chat SSE → 检索 + Ollama 流式生成
```

**双存储分工**

| 存储 | 职责 |
|------|------|
| SQLite | CRUD、处理状态、任务队列持久化 |
| 向量库 | chunk 语义检索（metadata 含 `user_id` 等） |

- 工程与产品规范：[`specs/`](./specs/)（架构、API、RAG、安全、范围）  
- 选型论证文档：[`specs/adr/0001-lance-vs-pgvector.md`](./specs/adr/0001-lance-vs-pgvector.md)（LanceDB vs pgvector 诚实决策）
- 参数门禁决策：[`eval/gate_decision.md`](./eval/gate_decision.md)（M-small 矩阵测试报表与默认开关签字确认）
- 已完成改造清单：[`UPGRADE_ROADMAP.md`](./UPGRADE_ROADMAP.md)  
- 可执行演进计划：[`.hermes/plans/`](./.hermes/plans/)

---

## 环境要求

- Python **3.11+**
- 默认推理演示使用 **云端兼容服务**（如 SiliconFlow + DeepSeek），也支持完全本地切换至 **Ollama**。

### 1. 云服务推理（推荐默认）

您需要准备好符合 OpenAI 接口规范的 API Keys，推荐组合：
- **Embedding**：SiliconFlow (bge-m3 等)
- **Chat**：DeepSeek (deepseek-chat 等)

> **⚠️ 维度警告：**
> 云端 `bge-m3` 的向量维度为 `1024`。若要使用此模型，必须在环境中同步配置 `EMBEDDINGS_DIMENSION=1024`，并配合**全新的向量库目录**使用。不要将 `1024` 维的数据与默认的 `384` 维混合，否则会引发严重检索错误。

### 2. Ollama 本地推理（可选）

如需纯本地运行，请安装并启动 Ollama：

```bash
# 默认配置下对应的 Embedding 模型（维度 384）：
ollama pull chroma/all-minilm-l6-v2-f32:latest

# 对话模型：
ollama pull mistral:7b-instruct-q4_0
ollama serve
```

---

## 安装与启动

### 1. 创建虚拟环境并安装

```bash
python -m venv venv

# Windows
venv\Scripts\activate

# Linux / macOS
# source venv/bin/activate

pip install -e .
# 或：pip install -r requirements.txt
```

### 2. 分别启动后端与前端（推荐）

两个终端，均先激活同一 venv，并在项目根目录执行：

```bash
# 终端 1 — API
inquisitive-start-backend

# 终端 2 — UI
inquisitive-start-ui
```

- 前端：<http://localhost:8501>  
- 后端：<http://localhost:8000>  
- API 文档：<http://localhost:8000/redoc>  
- 健康检查：<http://localhost:8000/ping>

### 3. 开发模式（热重载）

```bash
# 终端 1
uvicorn backend.main:app --reload --port 8000 --log-level debug

# 终端 2
set STREAMLIT_BROWSER_GATHER_USAGE_STATS=false   # Windows cmd
# export STREAMLIT_BROWSER_GATHER_USAGE_STATS=false  # bash
streamlit run frontend/app.py
```

### 4. 一键启动（实验）

```bash
inquisitive-start
```

首次拉起后端可能稍慢，请等待完成。

### 5. Docker Compose 容器化部署

本项目支持通过 `docker-compose` 极速拉起可复现的后端 API 容器运行环境。

#### 前置条件
1. **容器引擎**：Linux / macOS 系统直接支持；Windows 系统请确保已安装并启动 **Docker Desktop**，并开启 **WSL2 引擎** (Windows Subsystem for Linux 2) 支持。
2. **外部配置文件与数据目录**：启动前，请务必确认宿主机上已创建 `~/.config/inquisitive/`（Windows 下为 `%USERPROFILE%\.config\inquisitive\`）目录，并将配置放置于该目录下的 `backend.env` 文件中。

> [!IMPORTANT]
> 零外泄安全铁律：为遵循安全最佳实践，**严禁**在 Git 仓库的 `Dockerfile` 或 `docker-compose.yml` 中硬编码 `SECRET_KEY` 或 API 密钥。所有敏感配置均需通过宿主机上的 `~/.config/inquisitive/backend.env` 外部注入。

#### 启动命令
在项目根目录下开启终端执行：
```bash
docker-compose up -d --build
```
容器启动后，后端 API 服务将挂载于 `<http://localhost:8000>`，OpenAPI 交互式接口文档见 `<http://localhost:8000/redoc>`。

#### 数据持久化与多模式互通说明
- **目录挂载关系**：在 `docker-compose.yml` 中，宿主机的 `~/.config/inquisitive` 目录通过 bind mount 映射至容器内部非 root 用户（`appuser`）的主目录 `/home/appuser/.config/inquisitive`。
- **与本机脚本 (bat/sh) 互通**：使用 `docker-compose` 与使用本机直接运行脚本（如 `start-kb.bat` 或 `inquisitive-start`）**共享完全相同的宿主机数据目录**。因此，无论通过容器还是原生脚本启动，SQLite 数据库 (`inquisitive.db`) 与 LanceDB 向量库 (`lance_db/`) 均可无缝互通与持久化保存。
- **⚠️ 读写并发警告**：由于 SQLite 与 LanceDB 属于嵌入式存储引擎，不支持跨独立的 OS 运行环境进行多进程并发写。严禁**同时**运行后台 Docker 容器与本机终端（如双击 `start-kb.bat`）对同一份数据进行操作，否则会导致数据库死锁 (`database is locked`) 甚至文件锁冲突损坏。

---

## 配置说明

首次启动后，数据与配置默认落在：

```text
~/.config/inquisitive/
  ├── backend.env      # 后端覆盖项
  ├── frontend.env     # 前端覆盖项
  ├── inquisitive.db   # SQLite
  ├── uploads/         # 上传与笔记文件
  ├── lance_db/        # 默认向量库数据
  └── logs/
```

### 建议立刻修改

在 `backend.env` 中设置强随机密钥（不要使用代码里的默认占位）：

```env
SECRET_KEY=请换成足够长的随机串
```

启动时若仍使用不安全默认密钥，后端日志会给出警告。

### 常用可覆盖项（示例）

| 变量 | 含义 |
|------|------|
| `SECRET_KEY` | JWT 密钥，防止安全泄漏必备 |
| `EMBEDDING_PROVIDER` | `openai_compatible` 或 `ollama` 等 |
| `CHAT_PROVIDER` | `openai_compatible` 或 `ollama` 等 |
| `EMBEDDING_API_KEY` / `CHAT_API_KEY` | 对应云服务的鉴权密钥 |
| `EMBEDDINGS_MODEL` / `EMBEDDINGS_DIMENSION` | 嵌入模型名称与**强绑定**的维度 |
| `CHAT_MODEL` | 对话大模型名称 |
| `OLLAMA_HOST` | Ollama 本地地址（若开启） |
| `DEFAULT_VECTOR_DB` | 向量后端（默认 Lance） |
| `ALLOWED_UPLOAD_EXTENSIONS` | 允许上传的扩展名 |
| `MAX_UPLOAD_BYTES` | 单文件大小上限 |
| 前端 `API_URL` | Streamlit 访问后端的地址 |

默认值见 `backend/config.py`、`frontend/config.py`。  
若通过环境变量改了数据目录路径，请自行创建对应子目录。

---

## 主要 API

| 方法 | 路径 | 说明 |
|------|------|------|
| — | `/auth/*` | 注册、登录、用户、JWT |
| POST | `/file/upload` | 上传文件（202 + 异步入库） |
| * | `/file/note...` | 笔记 CRUD / sync |
| GET | `/file/status/{filename}` | 处理状态（含错误信息） |
| * | `/links/*` | 链接提交、批量、列表、删除、crawl |
| POST | `/documents/search` | 向量检索 |
| GET | `/jobs`、`/jobs/{id}` | 入库任务 |
| POST | `/chat` | RAG 流式对话（SSE） |
| GET | `/chat/models` | 列出 Ollama 模型 |
| GET | `/ping` | 健康检查 |

完整契约以运行中的 **Redoc** 为准。

### SSE 对话事件（`POST /chat`）

```text
data: {"type":"citations","citations":[...]}
data: {"type":"token","content":"..."}
data: {"type":"done"}
```

请求体可带 `use_rag`、`model`、`window_size`、`source_type`、`history` 等字段。

---

## 目录结构（简）

```text
.
├── backend/
│   ├── main.py              # 入口、lifespan、路由挂载
│   ├── api/
│   │   ├── router.py        # 鉴权
│   │   ├── routers/         # files / links / documents / jobs / chat
│   │   ├── services/        # ingestion / search / chat
│   │   ├── models.py
│   │   └── schemas.py
│   ├── parsers/             # 文档解析插件
│   ├── vector_store/        # Lance / Chroma / Milvus
│   ├── worker/              # 持久任务与链接处理
│   └── core/
├── frontend/                # Streamlit UI
├── tests/                   # 结构冒烟测试
├── start/                   # CLI 启动器
├── UPGRADE_ROADMAP.md
└── requirements.txt
```

---

## 测试

```bash
pytest tests/test_smoke_architecture.py -q
```

当前以架构/接线冒烟为主，不包含完整 Ollama 端到端。

---

## 部署提示

- **本机自用**：保证 8000 / 8501 空闲即可。  
- **局域网 / 公网**：务必配置 HTTPS、修改 `SECRET_KEY`、收紧 CORS，并建议在反向代理（如 Nginx）后暴露。  
- **删除资源**：默认从数据库与向量库移除记录；磁盘上的原始文件可能仍保留在 `uploads/`，请按需自行清理或后续扩展硬删策略。  
- **备份**：定期备份 `~/.config/inquisitive/` 整个目录。

---

## 已知限制

- 扫描件 / 纯图片 PDF 无 OCR，可能抽取为空并标记失败  
- 向量库返回的 `score`（前端展示为“距离”）为引擎原生距离分（Distance），通常越小代表越相关，**切勿直接当成 0–1 相似度百分比**。
- **Hybrid 检索 (合成方案)**：默认关闭 (`HYBRID_SEARCH_ENABLED=false`)。采用「向量主 + 词法辅」架构，词法检索支持 `fts5` 或 `like`，并通过等权 RRF (w_v=1.0, w_k=1.0, k=5) 融合重排。进入 RRF 前，向量距离大于设定的最大阈值（默认 0.8）的文档会被直接抛弃。需要使用 `backend/worker/fts5_backfill.py` 进行历史数据 backfill，FTS5 不可用或未命中时，默认退回纯向量。由于 RRF 的分数叠加，混合检索开启时输出的距离量纲可能与纯 Lance 向量不同。仅当专有名词召回率显著提升，且长尾语义不掉级时，才建议在生产环境开启。

---

## 许可证

Copyright (C) 2026 Lanzao

本仓库代码按 **GNU Affero General Public License v3.0（AGPL-3.0）** 提供，详见 [`LICENSE`](./LICENSE)。

对外提供网络服务时，请遵守 AGPL 对源码提供的要求。

> 说明：Python 包名与 CLI 入口仍为 `inquisitive-*`，配置目录默认为 `~/.config/inquisitive/`，仅为兼容已有安装路径，与产品展示名「个人知识库」无关。

---

## 快速自检清单

1. `ollama serve` 正常，已 pull embedding 与至少一个对话模型  
2. `inquisitive-start-backend` 无报错，`/ping` 返回 pong  
3. `backend.env` 已设置 `SECRET_KEY`  
4. 前端能注册/登录，上传一篇 md 或 pdf，任务状态变为 finished  
5. 在聊天中提问，侧栏出现引用，回答为流式输出  

祝用得顺利。

## 配置与行为说明

- **拒答行为 (Refusal)**：默认开启 (`RAG_REFUSE_ON_EMPTY=true`)。当启用 RAG 且检索未能命中任何知识库片段时，系统将直接返回“库中未找到相关依据”的提示，而不会调用大模型进行无根据的推演或幻觉生成。

## 评测与架构门禁 (Eval & Gate Decisions)

为了评估 RAG 检索管线的真实质量，请参考 [eval/README.md](eval/README.md) 使用黄金测试集与 A/B Test 矩阵进行打分。

关于系统核心检索参数（Hybrid/MMR/Rerank 等）的默认值开关选型与演进准则，请参阅并严格遵守 **[配置门禁决策文档 (Gate Decision)](eval/gate_decision.md)**。**在未获得人工签字确认前，不得擅自修改源码中的默认配置。**
