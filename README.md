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

### 工程能力

- **JWT 鉴权**，多用户资源隔离  
- **可恢复异步任务**（`ingestion_jobs`）：pending → running → succeeded/failed，支持重试与重启回收  
- **可插拔文档解析**（`backend/parsers/`）：text / pdf / docx / pptx  
- **向量检索**：用户隔离、`source_type` 过滤、引用 include/exclude  
- **后端 RAG 对话**：`POST /chat` SSE（citations + token 流）；前端优先走后端，失败再回退  
- 上传 **扩展名白名单 + 体积上限**  
- API 文档：后端启动后访问 `/redoc`

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
- 已完成改造清单：[`UPGRADE_ROADMAP.md`](./UPGRADE_ROADMAP.md)  
- 可执行演进计划：[`.hermes/plans/`](./.hermes/plans/)

---

## 环境要求

- Python **3.11+**
- 本机已安装并可访问 **Ollama**
- 建议有一定内存；有 GPU 时 7B 级对话模型体验更好

### Ollama 模型示例

```bash
# Embedding（与默认配置维度 384 对应；可按需更换）
ollama pull chroma/all-minilm-l6-v2-f32:latest

# 对话模型（任选其一或更多，前端可切换）
ollama pull mistral:7b-instruct-q4_0
# 轻量示例：
# ollama pull gemma3:4b
# ollama pull deepseek-r1:1.5b

ollama serve
```

Embedding 模型名与维度请在 `backend/config.py` 或 `backend.env` 中保持一致。

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
| `SECRET_KEY` | JWT 密钥 |
| `OLLAMA_HOST` | Ollama 地址，如 `http://127.0.0.1:11434` |
| `DEFAULT_VECTOR_DB` | 向量后端（默认 Lance） |
| `EMBEDDINGS_MODEL` / `EMBEDDINGS_DIMENSION` | 嵌入模型与维度 |
| `ALLOWED_UPLOAD_EXTENSIONS` | 允许上传的扩展名 |
| `MAX_UPLOAD_BYTES` | 单文件大小上限 |
| `JOB_WORKER_CONCURRENCY` / `JOB_MAX_ATTEMPTS` | 任务并发与重试 |
| `CORS_ORIGINS` | 前端来源（JSON 或逗号分隔） |
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
- 向量库返回的 `score` 为引擎原生距离，**不要直接当成 0–1 相似度百分比**  
- 递归 crawl 仍为实验能力  
- hybrid 检索 / rerank、Vue 门面、docker-compose 等见路线图待办  

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
