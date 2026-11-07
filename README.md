# wenjv（问据）

wenjv（问据）自托管知识库：**笔记 / 文件 / 网页链接** 管理，异步向量化入库，**Hybrid 检索 + 带引用的流式问答**。

> 产品名 **wenjv**（问据：有问有据）。
>
> **向下兼容（数据优先，空目录不抢库）**：
> - **CLI**：提供 `wenjv-start` / `wenjv-start-backend` / `wenjv-start-ui` / `wenjv` 标准入口。
> - **配置目录**：优先使用 `~/.config/wenjv/`（须含真实数据标记：非空 db / backend.env / 非空 lance_db|uploads 等）。若 wenjv **不存在或只是空壳**，而 `~/.config/inquisitive/` 存在历史数据，系统会自动回退旧目录，避免误创建空目录导致旧数据无法访问。
> - **数据库文件**：同目录下优先使用非空 `wenjv.db`，若不存在则回退至非空 `inquisitive.db`；全新安装默认创建 `wenjv.db`。
> - **Docker Compose**：默认挂载宿主机 `~/.config/wenjv`。旧数据仍在 inquisitive 时，可设置环境变量 `WENJV_CONFIG_DIR` 指向该目录。
> - 解析实现：`backend/core/paths.py`（与 `start/wenjv_launcher.py` / `start-wenjv.bat` 共用规则）。

- **后端**：FastAPI + SQLAlchemy + JWT  
- **前端**：Vue 3 + Vite（`web/`，Apple light UI）  
- **关系库**：SQLite（默认可换）
- **向量库**：LanceDB（默认；可选 Chroma / Milvus Lite）  
- **模型**：云端兼容接口（SiliconFlow + DeepSeek）或本地 [Ollama](https://github.com/ollama/ollama)（Embedding + 对话）

系统适用于本地单机或小团队内网自用，核心能力涵盖异步持久化入库、混合检索与带溯源引用的流式对话。

---

## 功能特性

### 知识源

| 类型 | 能力 |
|------|------|
| **笔记** | Markdown 创建、编辑、列表查询与删除；内容更新后自动触发向量刷新 |
| **文件** | 上传、状态轮询、下载；支持 txt / md / pdf / docx / pptx / csv / json / **png / jpg / jpeg** 等配置格式 |
| **图片** | 独立图片入库：OCR 识别，提取为空时调用多模态描述，仍为空则标记失败；查询侧提供基于图片解析文本的图问检索与对话接口：`POST /documents/search/by-image`（兼容 `/documents/search-by-image`）、`POST /chat/by-image` |
| **链接** | 单条与批量提交；抓取正文后异步入库；提供可选的实验性递归抓取机制 |

### 工程能力

- **租户逻辑隔离**：基于 JWT 鉴权解析用户身份，在 SQLite 与 LanceDB 底层硬注入 `user_id` / `belongs_to` 过滤条件，在应用层实现严格的租户边界防御。
- **异步任务队列与微批聚合**（`ingestion_jobs`）：后台 durable worker 管理任务状态流转（`PARSED -> EMBEDDED -> PERSISTED`），支持跨文档 `MicroBatchEmbedder` 微批向量化与单排他写锁。
- **结构感知切分与检索上限**：支持 Markdown 表格原子保护、围栏代码块完整保留、40% 断层相对截断、相邻分块去重合并以及 Lost-in-the-Middle 首尾抗疲劳重排。
- **混合检索与分腿并行加速**：支持基于向量与 SQLite FTS5 词法的混合检索 (Hybrid Search)。提供分腿并行执行选项 (`SEARCH_PARALLEL_LEGS`) 缩短 I/O 等待，并在单腿异常时触发 Fail-open 降级保底。
- **量化评估套件**：内置检索精度与并发吞吐评估套件 (`eval/`)，支持端到端三维评测与学术基准测试。
- **容器化部署支持**：提供 `docker-compose.yml` 配置文件，服务在专用非 root 用户 (`appuser`) 下运行，配置通过宿主机外部文件注入，与本机脚本共享同一套持久化数据。
- **嵌入式向量存储引擎**：默认采用轻量高效的单文件 LanceDB 引擎（选型论证详见 [ADR 0001](./specs/adr/0001-lance-vs-pgvector.md)）。
- **模块化文档解析**（`backend/parsers/`）：支持 text / pdf / docx / pptx，提供详细的解析状态回写与异常捕获。
- **后端统一 RAG 编排**：`POST /chat` 采用 SSE 流式输出（包含 citations 引用信息与 token 流），前端无需直连外部大模型服务。
- **上传防护与健康自检**：提供上传文件扩展名白名单校验与 25 MiB 大小上限限制，开箱提供 `/redoc` 接口文档与 `/ping` 健康探测接口。

### 对话模式（前端）

- **context-aware**：检索匹配片段，严格基于上下文依据生成回答
- **non-context**：跳过检索流程，执行通用大模型问答
- **only-links**：仅展示检索命中的参考依据，不触发文本生成
- 快捷过滤：支持输入 `/notes`、`/files`、`/links` 等提示词前缀限定检索范围

---

## 架构概览

```text
Vue SPA (:5173) (web/)
        │  Bearer JWT  (/api proxy -> backend)
        ▼
FastAPI (:8000)
  ├── routers: auth / files / links / documents / jobs / chat (轻量接口层)
  ├── services: files / notes / links / jobs / ingestion / search / chat (业务与事务编排)
  ├── SQLite: 用户表、资源元数据、持久化任务表
  ├── durable worker -> parsers -> embeddings -> Vector DB
  └── /chat SSE -> 检索 + 云端/本地模型流式生成
```

**双存储分工**

| 存储 | 职责 |
|------|------|
| SQLite | 用户账户、业务实体 CRUD、入库任务队列与状态持久化 |
| 向量库 | 文本切块语义向量索引（Metadata 包含 `user_id` 等租户属性） |

- 工程与产品规范：[`specs/`](./specs/)（架构、API、RAG、安全、范围）  
- 选型论证文档：[`specs/adr/0001-lance-vs-pgvector.md`](./specs/adr/0001-lance-vs-pgvector.md)（LanceDB 存储选型决策）
- 评测报告：[`eval/mm_l2_l3_benchmark_report.md`](./eval/mm_l2_l3_benchmark_report.md)
- 升级演进清单：[`docs/UPGRADE_ROADMAP.md`](./docs/UPGRADE_ROADMAP.md)
- 工程审计与过程文档：[`docs/`](./docs/)（索引见 [`docs/README.md`](./docs/README.md)）

---

## 环境要求

- Python **3.11+**
- 默认推荐使用 **云端兼容服务**（如 SiliconFlow + DeepSeek），同时支持完全切换至本地 **Ollama** 服务。

### 1. 云端推理配置（推荐默认）

需要准备符合 OpenAI 接口规范的 API Key，典型配置：
- **Embedding**：SiliconFlow (`bge-m3` 等)
- **Chat**：DeepSeek (`deepseek-chat` 等)

> **⚠️ 向量维度注意：**
> 云端 `bge-m3` 模型的向量维度为 `1024`。使用此模型时，必须在配置文件中设置 `EMBEDDINGS_DIMENSION=1024`，并使用全新的向量存储目录。切勿将 `1024` 维数据与 `384` 维数据存放在同一向量表中。

### 2. Ollama 本地推理配置（可选）

如需在本地离线运行，请安装并启动 Ollama：

```bash
# 下载默认配置对应的 Embedding 模型（维度 384）：
ollama pull chroma/all-minilm-l6-v2-f32:latest

# 下载对话模型：
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

在两个终端窗口中，分别激活同一虚拟环境并在项目根目录执行：

```bash
# 终端 1: 启动后端 API 服务
wenjv-start-backend

# 终端 2: 启动前端 Web 界面
wenjv-start-ui
```

- 前端界面：<http://localhost:5173>  
- 后端服务：<http://localhost:8000>  
- 接口文档：<http://localhost:8000/redoc>  
- 健康检查：<http://localhost:8000/ping>

### 3. 本地开发模式（热重载）

```bash
# 终端 1: 后端热重载
uvicorn backend.main:app --reload --port 8000 --log-level debug

# 终端 2: 前端开发服务器
cd web
set VITE_PROXY_TARGET=http://127.0.0.1:8000
npm run dev
```

### 4. 一键启动服务

```bash
wenjv-start
```

首次启动初始化后端组件可能需要数秒，等待启动完成即可。

### 5. Docker Compose 容器化部署

本项目提供预配置的 `docker-compose.yml`，用于构建和拉起后端 API 容器环境。

#### 前置要求
1. **容器运行环境**：Linux / macOS 系统原生支持；Windows 系统请安装 **Docker Desktop** 并启用 **WSL2** 后端。
2. **外部配置文件与数据目录**：启动前，请确认宿主机上已创建 `~/.config/wenjv/` 目录（若有历史数据，也可沿用 `~/.config/inquisitive/`；Windows 路径对应 `%USERPROFILE%\.config\wenjv\`），并将配置文件放置于该目录下的 `backend.env`。

> [!IMPORTANT]
> 安全提示：禁止在 Git 仓库内的 `Dockerfile` 或 `docker-compose.yml` 中提交真实的 `SECRET_KEY` 或 API 密钥。所有敏感凭证均应通过宿主机外部配置文件按需挂载注入。

#### 启动命令
在项目根目录下执行：
```bash
docker-compose up -d --build
```
容器运行后，后端服务挂载于 `<http://localhost:8000>`，接口文档位于 `<http://localhost:8000/redoc>`。

#### 数据持久化与运行模式说明
- **目录挂载**：`docker-compose.yml` 将宿主机配置目录（`~/.config/wenjv` 或兼容目录 `~/.config/inquisitive`）挂载至容器内部 `appuser` 的主目录。
- **与本地脚本互通**：使用 `docker-compose` 与使用本地脚本（如 `start-wenjv.bat` 或 `wenjv-start`）**共享相同的宿主机数据目录**。因此无论采用容器还是直接运行，SQLite 数据库（`wenjv.db` 或兼容 `inquisitive.db`）与 LanceDB 向量库（`lance_db/`）均统一持久化在宿主机上。
- **并发写限制**：SQLite 与 LanceDB 均为嵌入式单机文件存储，不支持跨进程并发写入。请勿同时运行 Docker 容器与本地原生脚本操作同一套数据目录，以避免触发数据库锁定错误 (`database is locked`) 或文件锁冲突。

---

## 配置说明

首次启动后，配置与业务数据默认保存在 `~/.config/wenjv/`（若检测到历史配置且无新数据，会自动回退至 `~/.config/inquisitive/`）：

```text
~/.config/wenjv/  (回退兼容 ~/.config/inquisitive/)
  ├── backend.env      # 后端配置项
  ├── frontend.env     # 前端配置项
  ├── wenjv.db         # SQLite 数据库文件 (回退兼容 inquisitive.db)
  ├── uploads/         # 上传文件与笔记实体存储
  ├── lance_db/        # 默认向量库持久化目录
  └── logs/
```

### 安全密钥配置

在生产或正式使用前，请在 `backend.env` 中配置高强度随机密钥：

```env
SECRET_KEY=请使用高强度随机字符串
```

如果启动时仍使用默认占位密钥，后端控制台会打印安全告警。

### 核心配置项列表

| 变量 | 含义 |
|------|------|
| `SECRET_KEY` | JWT 签名密钥，生产环境必须显式配置 |
| `EMBEDDING_PROVIDER` | 向量提供商：`openai_compatible` 或 `ollama` |
| `CHAT_PROVIDER` | 对话模型提供商：`openai_compatible` 或 `ollama` |
| `EMBEDDING_API_KEY` / `CHAT_API_KEY` | 云端服务对应的鉴权 Token |
| `EMBEDDINGS_MODEL` / `EMBEDDINGS_DIMENSION` | 向量模型名称及与之严格对应的维度大小 |
| `CHAT_MODEL` | 对话大模型名称 |
| `OLLAMA_HOST` | 本地 Ollama 服务的访问地址 |
| `DEFAULT_VECTOR_DB` | 默认向量存储引擎（默认 `lance`） |
| `ALLOWED_UPLOAD_EXTENSIONS` | 允许上传的文件后缀白名单 |
| `MAX_UPLOAD_BYTES` | 单文件体积上限（字节数） |
| 前端 `API_URL` / Vite `VITE_PROXY_TARGET` | 前端反向代理指向后端的地址 |

默认值请参阅 `backend/config.py`。前端配置详见 `web/README.md`。

---

## 主要 API 契约

| 方法 | 路径 | 功能说明 |
|------|------|----------|
| ANY | `/auth/*` | 账户注册、登录认证、当前用户信息与凭证刷新 |
| POST | `/file/upload` | 上传文件（返回 202 状态码，后台异步启动解析入库） |
| ANY | `/file/note...` | 笔记实体的创建、编辑、同步与删除 |
| GET | `/file/status/{filename}` | 查询文件解析入库状态与错误信息 |
| ANY | `/links/*` | 网页链接提交、批量导入、列表查询、删除与内容抓取 |
| POST | `/documents/search` | 语义向量检索与混合检索接口 |
| POST | `/documents/search/by-image` | 基于图片识别文本的图问检索接口 |
| GET | `/jobs`、`/jobs/{id}` | 异步任务列表与任务详细状态查询 |
| POST | `/chat` | RAG 问答流式输出（SSE 事件流） |
| POST | `/chat/by-image` | 基于多模态图片识别结果的流式对话接口 |
| GET | `/chat/models` | 获取当前可用的对话模型列表 |
| GET | `/ping` | 服务健康探测接口 |

完整 API 规范请在服务运行后查阅 `/redoc`。

### SSE 对话事件格式（`POST /chat`）

```text
data: {"type":"citations","citations":[...]}
data: {"type":"token","content":"..."}
data: {"type":"done"}
```

请求体支持传入 `use_rag`、`model`、`window_size`、`source_type`、`history` 等参数。

---

## 目录结构概览

```text
.
├── backend/
│   ├── main.py              # 服务入口、lifespan 生命周期管理与路由注册
│   ├── api/
│   │   ├── router.py        # 路由总装与基础认证依赖
│   │   ├── routers/         # 接口呈现层 (files / links / documents / jobs / chat)
│   │   ├── services/        # 核心业务服务与数据库事务编排层
│   │   ├── models.py        # SQLAlchemy 数据模型定义
│   │   └── schemas.py       # Pydantic 请求与响应校验模型
│   ├── parsers/             # 文档解析适配器
│   ├── vector_store/        # 向量存储适配器 (Lance / Chroma / Milvus)
│   ├── worker/              # 后台持久化任务与网页抓取处理器
│   └── core/                # 路径探测、FTS5 全文检索等核心工具
├── web/                     # Vue 3 + Vite SPA 前端工程
├── tests/                   # 自动化测试套件
├── start/                   # 跨平台启动脚本与入口
├── docs/                    # 文档索引见 docs/README.md
│   ├── UPGRADE_ROADMAP.md   # 升级演进清单
│   ├── wenv_context_and_roadmap.md   # 项目全景与演进路线
│   ├── deployment-diagram.md          # 部署架构图
│   ├── ENGINEERING_HYGIENE_AUDIT.md   # 工程卫生审计
│   ├── code-scan-todo*.md             # 历史代码扫描待办
│   ├── worklog/             # 任务发现、进度与计划日志
│   └── testing/             # 基准测试基础设施与就绪报告
├── specs/                   # 工程与产品规范（架构 / API / RAG / 安全）
├── eval/                    # 量化评测套件与评测报告
└── requirements.txt         # 基础依赖清单
```

---

## 自动化测试

运行核心架构与分层冒烟测试：

```bash
pytest tests/test_smoke_architecture.py -q
```

---

## 部署与运维提示

- **单机使用**：确保本地 8000 与 5173 端口未被占用。
- **局域网与公网暴露**：必须配置 TLS/HTTPS 加密传输、配置强随机 `SECRET_KEY` 并收紧 CORS 跨域规则，建议挂载在 Nginx 反向代理之后。
- **资源清理**：删除知识库条目时，系统会同步清理 SQLite 记录与 LanceDB 向量块；`uploads/` 目录中的物理原始文件可根据运维策略进行归档或清理。
- **数据备份**：日常维护只需定期冷备份 `~/.config/wenjv/`（或历史兼容目录 `~/.config/inquisitive/`）目录即可完成全量恢复。

---

## 技术边界与已知限制

- 扫描件与纯图片 PDF：若未配置外部 OCR 引擎，抽取文本可能为空并记录解析失败状态。
- 检索分数量纲：LanceDB 默认返回引擎原生距离分（Distance），数值越小通常代表语义距离越近，切勿直接视为 0 到 1 的相似度百分比。
- 混合检索 (Hybrid Search)：系统支持向量与 SQLite FTS5 的混合检索，融合采用非对称加权 RRF 算法（默认向量权重 3.0，词法权重 1.0，k=5）。在进入 RRF 前，向量距离超出阈值（默认 0.8）的数据会被预先过滤。词法服务不可用时，系统自动降级为纯向量检索。

---

## 许可证

Copyright (C) 2026 Lanzao

本项目依照 **GNU Affero General Public License v3.0（AGPL-3.0）** 许可协议开源，完整协议内容请参阅 [`LICENSE`](./LICENSE)。

通过网络提供交互服务时，请遵循 AGPL 协议关于开源代码分发的相关要求。

> 兼容性声明：系统统一采用 `wenjv*` CLI 入口命令，配置目录为 `~/.config/wenjv/`，数据库文件为 `wenjv.db`。底层自动保留对历史配置目录 `~/.config/inquisitive/` 与数据库文件 `inquisitive.db` 的只读探测与透明回退逻辑。

---

## 快速自检

1. 本地模型服务（Ollama）或云端 API 可正常访问，Embedding 与对话模型已准备完毕。
2. 执行 `wenjv-start-backend` 服务正常启动，访问 `/ping` 返回 pong。
3. `backend.env` 文件已配置独立生成的 `SECRET_KEY`。
4. 前端正常完成用户注册与登录，上传 txt、md 或 pdf 之后任务状态转为 finished。
5. 在问答界面发起提问，检索命中时展开引用来源并流式输出回答内容。

---

## 核心行为与配置准则

- **空检索拒答机制 (Refusal)**：默认开启 (`RAG_REFUSE_ON_EMPTY=true`)。在启用 RAG 模式下，若检索未能命中任何有效参考切块，系统将直接返回无知识库依据提示并终结输出，不调用大模型生成无依据文本。
- **断层截断与抗疲劳重排**：精排后默认开启 40% 相对跌幅肘部截断（`truncate_by_score_gap`），自动合并同源相邻重叠块，并通过 Lost-in-the-Middle 排布将高分块置于上下文首尾。
