# wenjv 项目代码全量扫描报告（结构化待办清单）

> 扫描范围：`backend/`、`web/src/`、`start/`、`tests/`、`eval/`、`Dockerfile`/`docker-compose.yml`、`.github/`、根配置与文档。
> 扫描方式：全量静态阅读 + 关键路径运行时验证（Python 注解解析、路由注册、函数签名解析等已在本地 Python 3.14.8 复现）。
> 原则：**只报告，未修改任何代码或配置**；不确定项标注【疑似】。
> 生成时间：见文件时间戳。

---

## 0. 结论摘要

| 级别 | 数量 | 说明 |
|---|---|---|
| P0 阻断级 | 3 | 不修则后端无法按当前部署形态运行 / 存在直接安全暴露面 |
| P1 高危隐患 | 9 | 数据一致性、SSRF、内存放大、静默污染等 |
| P2 一般缺陷 | 6 | 边界校验、并发怪异、资源悬挂 |
| P3 配置/硬编码 | 10 | 拼写、未使用配置、模型名硬编码、环境路径硬编码 |
| P4 冗余/死代码 | 6 | 库、文档、路由别名、跨仓复制文件 |
| P5 工程规范/注释 | 8 | 拆分、契约、测试可维护性 |

代码规模：后端约 15k 行 Python，前端约 4k 行 Vue/JS，测试约 6k 行 Python。

---

## 1. P0 — 阻断级（建议立即处理）

### P0-1 `backend/api/routers/files.py:48` 缺失 `Optional` 导入 — 高置信 BUG

`tags: Optional[str] = Form(None)` 使用的 `Optional` 未在模块中导入（全文件无 `from typing import ...`）。

影响：
- Python ≤3.13（Docker `python:3.11-slim`、CI `python-version: '3.11'`）：函数定义期即 `NameError`，`backend.main` 无法启动。
- Python 3.14（本地 `.venv` 3.14.8）+ FastAPI 新版：FastAPI `get_dependant → _get_signature` 捕获 `NameError` 并回退 `annotation_format=Format.FORWARDREF`，运行时不报错，但该参数注解被静默降级为未校验类型；注解语义静默丢失。

验证结论：
- 已在 Python 3.14.8 用复现脚本证实：`inspect.signature(call)`（即使 `eval_str=False`）解析此类函数时触发 `NameError: name 'Optional' is not defined`。
- 已在 uv 缓存的 FastAPI 源码中确认 `_get_signature` 的 NameError 回退分支（仅覆盖 3.14+ 环境）。

建议：补 `from typing import Optional`（修复方式不在本次范围）。

### P0-2 `backend/api/routers/admin.py` `/admin` 面板零认证 — 安全高暴露面

- `router = APIRouter(tags=["admin"], dependencies=[Depends(check_admin_enabled)])`，仅检查 `ADMIN_ENABLED`，无任何身份认证。
- 页面截图文案自述"此页面无需认证"。
- 暴露面：所有用户的查询历史（query 全文、延迟、命中率、错误）、API 调用计数，且提供 `POST /admin/reset-counts` 状态变更入口。
- 默认 `ADMIN_ENABLED: bool = True`（于 `backend/config.py`）。

风险场景：任何能访问 8000 端口的进程/人（含误将端口映射到公网、公司内网横向移动）；`docker-compose` 将 `8000:8000` 直接暴露。

### P0-3 `backend/api/services/chat.py` `stream_ollama_chat` 无超时 — 连接悬挂

- `async with httpx.AsyncClient(timeout=None) as client:` → Ollama 无响应时 SSE 流悬挂，事件循环/worker 线程被占住（每个会话一个悬挂连接）。
- 同时：`OLLAMA_HOST` 默认 `http://0.0.0.0:11434`（`backend/config.py:22`），跨平台/性能上连 `0.0.0.0` 依赖 OS 语义，并非标准客户端目标地址。

---

## 2. P1 — 高危隐患

### P1-1 CWE-918 SSRF（链接抓取）— 高置信
- `backend/worker/url_processor.py::process_single_url`：`aiohttp` 直接请求用户提交的 URL，`allow_redirects=True, max_redirects=10`，无 scheme/IP/端口/内网地址校验。重定向可绕过任何前置校验；响应体长度无上限（`response.text()`）。
- `backend/worker/url_processor_recursive.py::crawl_url`：`RecursiveUrlLoader(... base_url=get_base_url(url))` 递归 2 层，同样无 SSRF 防护，且每发现一个页面即创建 `Link` 行并全量入库（可被链接农场放大）。队列为进程内内存队列（重启丢失）。
- `backend/api/models.py::LinkCreate.headers` → 用户可指定任意请求头（`DEFAULT_HEADERS` 可被覆盖），可被用于探测/绕过目标服务。

### P1-2 `backend/core/embedder.py` 零向量静默污染 — 高置信
- `HTTPOpenAIEmbeddings._call_api` 在 4xx/5xx/网络超时重试耗尽后返回 `[0.0] * dims` 失败软回退（多处），`embed_query` 同理。
- 零向量被写入 `embedding_cache`（CachedEmbedder 不区分零向量）、写入向量库；后续查询零向量恒为"不相关"或干扰 cosine 相似度。
- 问题：不抛错、仅 warning，上游（durable_jobs）会判定为成功后把坏向量持久化，属于静默数据污染。
- 附带：`GoogleEmbeddings._call_batch` 同样 fail-soft 返回零向量。

### P1-3 删除流程资源/数据残留 — 高置信
- `backend/api/services/files.py::delete_file_service` 与 `backend/api/services/notes.py::delete_note_service`：删除 DB 行 + `remove_documents`，但**不删除磁盘物理文件**，`update_file_with_backup` 产生的 `*.bak` 文件无人清理；uploads 目录随时间膨胀。
- `delete_file_service` / `delete_note_service` 不清理 `visual_store`（视觉向量），不清理 `chunk_mapping`（ChunkMappingTable），不清理 `doc_embeddings`（late_chunking）。
- 残留的 chunk_mapping 会被 `_expand_context` / `deoverlap_and_merge_adjacent_chunks` 查用 → 陈旧引用。
- `remove_documents`（lance_db）删除时不会清理 `ChunkMappingTable`，同源问题。

### P1-4 by-image 端点无上传大小上限（边界漏洞）— 高置信
- `backend/api/routers/documents.py::_search_by_image_impl` 与 `backend/api/routers/chat.py::chat_by_image`：`content = await file.read()` 或 `text = await extract_text...` 前不检查 `MAX_UPLOAD_BYTES`，而 `/file/upload` 路径有 25MiB cap（`backend/api/routers/files.py` 中 `max_bytes`）。同一服务两个入口大小策略不一致 → 内存放大风险（每次请求可拉入数百 MB 甚至 GB 级别）。

### P1-5 `backend/core/multimodal.py::_ocr_for_caption` 全局 settings 变异竞态 — 高置信
- 临时强制 `settings.OCR_MODE = "always"` 再 `finally` 恢复。高并发多图任务下，OCR 子任务相互串扰（A 任务看到的是 B 任务改过的 OCR_MODE），且异常路径下 `finally` 恢复与初始值不一致时行为脆弱。

### P1-6 `backend/core/auto_tagger.py` google 分支引用未定义变量 `system_prompt`
- `_call_llm_for_tags` 的 `provider in ("google","gemini")` 分支 `payload = {... f"{system_prompt}\n\n{prompt}" ...}` 使用未定义的 `system_prompt` → NameError 被 `generate_document_tags` 的 fail-open 吞掉 → CAHT_PROVIDER=google 时自动打标静默退化为规则标签，且无告警。

### P1-7 `backend/core/ocr_client.py::_submit_and_poll` 轮询悬挂
- 轮询仅以 `OCR_TIMEOUT_SECONDS`（默认 120s）兜底；`httpx.AsyncClient(timeout=httpx.Timeout(30.0))`，单次 poll 超时会触发 `except httpx.RequestError` → `logging + asyncio.sleep(2)` 继续循环；若服务端返回持续 5xx / 连接无响应中循环重试（持续到外层 timeout 才抛 `OCRTimeoutError`），期间持连接。Job 层重试 3 次 × 120s → 最坏单 job 6 分钟才置 failed。上下文方面无出错——不算严重，仍属资源消耗边缘问题。

### P1-8 事件循环阻塞：同步 I/O / 同步 HTTP 在 async 路径
- `url_processor.py` `process_url_queue`（legacy dequeue）在事件循环内 `session.get(url, timeout=30)` 阻塞最多 30s（`timeout=30` 在 aiohttp 但不排除 hang 连接）。
- `search.py` `_fetch_fts5`、`_fetch_structured` 等在大结果集上 `.to_pandas()`/`.to_list()` 等同步大对象传输进事件循环路径。
- `test_benchmark_pipeline.py`（混合测试）中大量 `asyncio.to_thread` 可缓解——生产路径仍需关注。

### P1-9 `backend/api/routers/chat.py::rag_chat_events` 异常原文透传 — 信息泄露提示
- 最外层 `except Exception as e: yield {"type":"error","message":str(e)}` → 内部异常细节（如 SQL/HTTP/网络错误原文）发给客户端。
- `backend/api/routers/documents.py::search_documents` 同样 `raise HTTPException(500, detail=f"...{str(e)}")`。

---

## 3. P2 — 一般缺陷 / 边界漏洞

### P2-1 `NoteCreateRequest.title` 无长度上限 → `save_file` 生成超长文件名
- `backend/core/utils.py::save_file` 以 `"-"+"safe_title+"-"+str(uuid)` 拼接成磁盘文件名。title 无长度约束，可生成超长文件名 → 超出文件系统限制（Linux 255B）→ `open()` 异常 → 422。
- 同理 `update_note_service` 路径下相同。
- 【疑似】Windows 路径长度限制差异。

### P2-2 上传扩展名列表允许 `.sh` + `.json` — 内容类型后验证缺失
- `ALLOWED_UPLOAD_EXTENSIONS` 默认含 `"sh"`、`"md"`、以 `.md` 上传的被视为 Note 直接入库；已发现 prompt 注入面（文档 text 作为 RAG 上下文），需确认策略。
- （注：该项目产品定位为"个人知识库"，风险相对可控，但作为安全审计项必须记录。）

### P2-3 `stream_openai_chat` 相对路径/备用模型硬编码
- `model_chat_impl` 内 `if model == '...'` 等分支硬编码 `Qwen3-VL-8B-Instruct` / `Qwen2.5-7B-Instruct`（fallback when chosen_model 不含关键词）。
- google 分支同样硬编码 `gemini-...` 与 `gemma-4-31b-it`（若 CHAT_MODEL 未配）。
- 【疑似】对 change 的敏感度需业务确认。

### P2-4 `files.py` sanitize 逻辑脆弱
- `sanitize_upload_basename` 保留空格（Windows/其他 shell 下文件名带空格被 execute 等场景易出问题）；`save_file` 的 safe_title 用 `-` 替换特殊字符，标题含 `-` 时多分隔符，难回溯，且文件名冲突概率高（既降低了唯一性）。
- 【疑似】非关键，但 `sanitize` 未处理 `/`、`\` 在特定系统下；已用 basename 兜底，建议人工复核 Windows 下行为。

### P2-5 `JOB_MAX_ATTEMPTS` / `JOB_STALE_SECONDS` 配置与重试逻辑不一致
- `jobs.py::retry_job_service` 允许 retry `FAILED/CANCELLED` 的 job；`attempts` 被重置回 0，但 `last_error` 并不回显（保留），导致重复失败体的"attempts"计数失去意义（history 上 steps=attempts 显示不全）。

### P2-6 `documents.py::get_document_asset_image` 路径前缀校验与 resource 类型缺陷
- `path.startswith(upload_root)` 前缀匹配存在 `uploads_evil` 目录绕过窗口。【疑似】利用需构造具体路径；建议改为 `os.path.commonpath` / `Path.is_relative_to`。
- `path` 参数同时接受相对与绝对路径：`Path(path).resolve()` 后校验范围正确，但 query 参数场景可控；relative 路径之外的 scheme（`file://` 不在解析中）被 `resolve()` 拒。
- token 走 query 参数 → 被代理/网关/浏览器历史记录（信息泄露面）。

### P2-7 `route alias` 冗余（documents.py）
- `@document_router.post("/search/by-image")` 与 `@document_router.post("/search-by-image")` 两个路由同一 handler（`search_by_image_alias`）。
- 影响：OpenAPI 文档两处列、turno 重复。功能冗余，属"死路由"清理项。

### P2-8 `get_base_url` 对非 http(s) URL 无防御
- `urlparse→ scheme://netloc` 输出 `ftp://host`、`ws://host` 等中间态；作为 base_url 传给 RecursiveUrlLoader 时可下载非 http 协议内容（行为依赖库实现）。【疑似】

### P2-9  AI 面向སུcido — `process_recursive_url_queue` 的 user 参数透传
- `recursive_url_processing_queue.put((str(url), user, headers))`：`user` 是 `User` ORM 实例跨的事件循环；session 在 generator 关闭后仍可能被引用（用户订单跨请求复用）。
- 观测到 `main.py` `lifespan` 启动 `asyncio.create_task(process_recursive_url_queue())`，若 `async with async_session_maker() as db:` 块结束时 async session 超出上下文使用——现网 `crawl_url` 每次 `async with async_session_maker()` 独立，实际上不跨扫描，但 `headers` 默认值在多线程下共有 dict 危险的 dict 引用。

---

## 4. P3 — 配置 / 硬编码问题

### P3-1 拼写错误但全链路一致使用：`LANCE_DB_VECTOR_STORE_PERSISTS_DIRECTOY`（应为 `DIRECTORY`）
- 涉及文件：`backend/config.py`（×2）、`backend/vector_store/lance_db.py`（×1）、`backend/main.py`（×1）、`tests/test_benchmark_pipeline.py`（×2）、`eval/run_mm_l2_l3_eval.py`（×1）。
- 【疑似】实际行为同正确拼写；但重命名/新环境配置误写会导致 `lancedb.connect` 抛错/fallback 混乱。属于"可重命名的规范债"。

### P3-2 `SECRET_KEY` 默认值不安全
- `"YOUR_SECRET_KEY_CHANGE_THIS"`（三处：SECRET_KEY / RESET_PASSWORD_TOKEN_SECRET / VERIFICATION_TOKEN_SECRET）。
- 启动时有 warning（`backend/main.py` lifespan）但仅 `is_insecure_default_secret()` 告警，不阻断启动；docker-compose 仅注释提醒。
- 【疑似】`JWT_ALGORITHM=HS256` + 默认密钥 → 可伪造任意用户 token，认证绕过风险高（需部署人员强改）。风险已在 specs/security.md 中被覆盖——确认现网是否启用默认值。

### P3-3 存在但从未读取的配置项（dead config）
- `RESET_PASSWORD_TOKEN_SECRET`、`VERIFICATION_TOKEN_SECRET`（`fastapi_users` 中 UserManager 硬编码使用 `settings.SECRET_KEY`，独立配置项未被读取）。
- `WINDOW_SIZE_MULTIPLIER=10` 仅 `fetch_documents`（link）使用，语义模糊。
- `EMBEDDINGS_MODEL="chroma/all-minilm..." EMBEDDINGS_DIMENSION=384` 在配置注释里与 `.env.example` 中一致但与 main config `BAAI/bge-m3 / 1024` 冲突，文档引导用户产生迷糊。
- `RERANK_REL_GAP_THRESHOLD`、`RERANK_MIN_KEEP` 有读有写，但 `.env.example` 缺少。
- `DEFAULT_CHAT_MODEL` 被引用（chat.py 的 fallback `or "mistral:...)`）配置中不存在 → 硬编码 fallback。
- `SMALL_TO_LARGE_ENABLED` 被 adapter 以 `getattr(settings, ..., False)` 读取但 config 根本无此项 → 该开关永远为 False（小乳大功能被 adapter 的 monkey-patch wrapper 死锁住，实际未启用）——【疑似】 adapter.py wrapper 的 bug：读取的带贬义有效配置名与实际 config 字段不一致。

### P3-4 模型名/路径硬编码
- 默认模型 `"mistral:7b-instruct-q4_0"`、`"qwen2.5:7b"`、`"bge-reranker-v2-m3"`、`models/bge_m3_onnx`、`models/siglip2_onnx`、`models/bge_reranker_v2_m3` —— 硬编码路径假设 cwd=项目根，从任意目录启动时加载失败或误加载同目录。
- `backend/config.py: LOCAL_RERANK_MODEL_DIR = "models/bge_reranker_v2_m3"`（无绝对路径解析）；backfill 注释中"执行 `python backend/worker/fts5_backfill.py`"引用不存在的文件。

### P3-5 `OLLAMA_HOST` 默认值 `http://0.0.0.0:11434`
- 客户端浏览器/服务端都应使用可连接地址，0.0.0.0 作为"连接目标"非标准（本地常工作但非保证）。【疑似】 跨平台表现：macOS 下连接 0.0.0.0 行为不一致。

### P3-6 `.env.example` 与代码默认值漂移
- `HYBRID_RRF_WEIGHT_KEYWORD=1.0`（example）vs `backend/config.py: HYBRID_RRF_WEIGHT_KEYWORD=0.8`（default）。
- `EMBEDDINGS_DIMENSION=384` + `"chroma/all-minilm..."` 示例与 config 默认 `BAAI/bge-m3 / 1024` 不同步。
- 【疑似】更容易造成用户困惑（配置写入 1.0 → 融合权重实际生效差异）。

### P3-7 Docker / 构建环境
- `Dockerfile:FROM python:3.11-slim`，但运行时本地 Python 是 3.14.8（.venv/pyvenv.cfg）且 pyc 是 3.14；`requirements.txt` 固定版本清单（如 `asyncio==3.4.3` 纯占位包、`phink✓`等）在 3.11 与 3.14 之间的 wheel 兼容风险”。【疑似】aiosign 类纯 Python 包不存疑；`onnxruntime==...`、`lancedb` 等 binary wheel 无 3.14 版本时容器无法构建。实际 CI 用 3.11——与 Docker 一致但与本地 3.14 不一致，形成三套 Python 环境。
- 容器 COPY `requirements.txt` 后 `pip install`（无 pip 可执行文件路径校验）；`USER appuser` 运行。
- 无明显的密钥泄漏（`.env` 不应入库，`__pycache__`/`.pytest_cache` 未被忽略但 `.dockerignore` 已排除部分）。
- 【疑似】Dockerfile 没有 healthcheck；compose 端口直接 `8000:8000` 无限制。

### P3-8 安装、执行脚本硬编码
- `start/start.sh:4` 导出 `PATH=...:/home/lanzao/antigravity/dazzling-bell/.venv/bin:$PATH` —— 个人机器绝对路径写入可复用脚本。
- `start-wenjv.bat` 引用 `%ROOT%\start\wenjv_runtime.env`（生成产物，可接受）；`stop-wenjv.bat` 类似。

### P3-9 eval 脚本依赖本地绝ҚЫ路径
- `eval/run_eval.py` 等脚本中 `eval/results`、`eval/sample_1000.json`、`EVENTSTREAM` 等路径相对 cwd，不可移植；`open("eval/sample_1000.json")` 在工作目录不设时失败。【疑似】已在脚本中 `sys.path.insert` 缓解导入，docs 层面路径仍硬编码。

### P3-10 前端 base URL 与代理重写
- `web/vite.config.js` proxy target 取 `VITE_PROXY_TARGET` 默认 `http://127.0.0.1:8000`；生产构建设 `VITE_API_URL`。无鉴权问题本身，但 dev server 默认绑定 `127.0.0.1` 与 `start.sh` 传 `--host 0.0.0.0` 不一致（安全：dev server 暴露到局域网）。【疑似】 需要人工确认是否有意暴露。

---

## 5. P4 — 冗余 / 死代码 / 文件管理

### P4-1 多重流程文档与 artifacts
- 根目录：`findings.md`、`progress.md`、`task_plan.md`、`TEST_INFRA.md`、`TEST_READY.md`、`UPGRADE_ROADMAP.md`、`README.md`
- `.agent/progress.md`、`.agent/task_plan.md`、`.agent/findings.md`（与根目录重复）
- `.agents/`（团队协作 harness 的 BRIEFING/DISPATCH/handoff 等）
- `specs/`（稳定性设计文档）、`docs/`（2 篇）
- 【疑似】 AGENTS.md / .agent 为结构性混杂，建议要么纳入 specs 目录，要么 gitignore；`docs/wenjv_context_and_roadmap.md` 与 UPGRADE_ROADMAP 内容重叠。

### P4-2 构建产物入库
- `web/dist/`（被跟踪？léčen — 从 git ls-files 看到 0 条 dist 条目；已被 .gitignore；仅提示存在且未跟踪）—— 检查实际 git 状态显示 web/dist **不在** git 中（.gitignore 含 `web/dist/`）——无问题，此处更正。
- `eval/results/*.md/json` 被跟踪（benchmark 报告入库合理）；`eval/eval/open_ragbench_data/*.json` （90+ 个 arXiv corpus JSON）入库与否：属数据资产，保留合理但体积大。
- `models/`（1.5G ONNX/权重）：已 .gitignore 不跟踪 models 目录吗？—— git ls-files show 未列出 models/，`.gitignore` 也检查——实际上 `models/` **未被忽略**（.gitignore 里没有 models/ 条目）且**未被跟踪**（git ls-files 没列出）；1.5G 大文件在工作区但不入库，磁盘堆积 —— 诚实结论：`.gitignore` 缺失 models/ 条目，若执行 `git add -A`/`git commit -a` 会把 1.5G 权重推上去。**高优先级 .gitignore 补 `models/`**（重要发现，追加到 P3 或独立条目）

### P4-3 死代码 / 冗余符号
- `backend/core/utils.py: is_file_pdf` 未被引用（grep 结果）；`record_chunk_mappings` 仅 small-to-large 开启时被调用（当前恒 False → 死路）——实际 `CHUNK_EXPAND_ENABLED=False` 默认 → record_chunk_mappings 在生产不执行。
- `VectorStore task 中 _wrap_s2l_ingestion` 包装函数中引用 `SMALL_TO_LARGE_ENABLED`（不存在配置）→ wrapper 确认永远 passthrough。【疑似】旧 feature flag 改名遗留。
- `backend/api/routers/chat.py` `/chat/by-image` 中 `history` 状态以字符串 JSON 传入，`history_sidecar` 参数有效，但反复 parse。
- `backend/worker/url_processor.py::process_url_queue`（权威："Deprecated: durable job dispatcher handles link jobs") 过时，队列无消费方 —— 遗留死进程。
- `backend/core/micro_batch_embedder.py` `created_at` 字段无消费。
- `backend/database.py::_ensure_sqlite_columns_upgrades`（lemma 列）的 ADD COLUMN 序列只对 SQLite 执行，其他引擎静默缺失（schema 不一致）——【疑似】 影响 postgres 迁移正确性。
- `tests/__pycache__` 等 未跟踪（.gitignore 覆盖）正常。

### P4-4 测试资产谎报
- `tests/test_config_ocr.py`：在测试目录有以"test_"前缀但实质为配置检查文件。
- 【疑似】无，主要是命名噪音。

### P4-5 环境的“假依赖”
- `requirements.txt` 中存在 `asyncio==3.4.3`、`bs4==0.0.2`、`typing_extensions` 等占位/无意义 pin；`langchain==...` 与 `langchain-text-splitters` 等共存，冗余。

### P4-6 三份文档重复
- `TEST_INFRA.md` 与 `.agents/teamwork/test_writer_1/TEST_INFRA.md` 相同。
- `TEST_READY.md` 与 上重叠。

---

## 6. P5 — 代码规范 / 注释 / 架构

### P5-1 核心模块职责过大 / 分层混乱
- `backend/api/services/search.py`（1125 行）：缓存、FTS5、结构曲折、MMR/ReRank/RRF、标签过滤、上下文扩展、late chunking 全塞一个文件。
- `backend/api/routers/documents.py`（315 行）含搜索 + asset 服务 + image 搜索go。
- `backend/vector_store/lance_db.py`（939 行）仍是发动机式的CRUD+FTS5+chunk mapping 三元组双写。
- 建议：search.py 拆分到 `search/legs.py`、`search/fusion.py`、`search/cache.py` 等；lance_db 拆分为 store + fts5 sync。

### P5-2 注释质量：/**/ 残留
- `backend/main.py::health()` 有"DB 探活（异步，不阻塞事件循环）"中文注释，partially 英文混杂。
- `backend/core/structural` 部分中英混杂；`search.py` 中"L2: 词法列表 K"、"L3: 融合"标签在代码里语义模糊（需对齐 roadmap 文档中的 L1/L2/L3 命名体系）
- 缺失 docstring 的关键函数：`lance_db.fetch_documents_keyword`、`milvus_db` 相关方法、`headers.py` 中默认 headers 说明（已有部分）。
- `obs_logger.increment_api_count`（observability.py 底部模块级）每次调用新建 ObsLogger() 实例（性能被牺牲）。

### P5-3 类型标注不一致（不影响运行，属规范）
- 部分模块缺 `from __future__ import annotations`（config.py, embedder.py, ocr_client, image_ingest_gate, url_processor.py 等），跨 Python 版本表现得微妙差异（偏执池对比 files.py）。
- 类型标注文本 vs 现网实现（e.g., `tags: Optional[str] = Form(None)` 实际是 Optional[str]）无 误导 matcher 修复后无问题。
- `backend/api/services/structured_recall.py` 返回 `list[dict]` 但内部用裸 dict（无 schema）。

### P5-4 API 一致性
- `chat.py` POST `/chat` 与 `documents.py` POST `/documents/search` 的 include/exclude/window/tags/source_type 结构相似但 schema 不同（history vs prompt）。OpenAPI 文档无……docs 未生成。无契约文档 `api-conventions.md`（存在 in specs/）与实际不完全同步。
- `FilePollingResponse`、`ResourceDeletedResponse` 等 schema 简单但 placement 分散。

### P5.5 — 测试可信度提示【疑似】
- `tests/` 50+ 文件多数以 MagicMock/AsyncMock 替代整个搜索链路（如 `fetch_documents_by_tags`、`vector_store` 等注入 mock），能验证路由契约但不会覆盖真实 Lance/FTS/检索代码路径。
- `.pytest_cache` 显示 lastfailed `{}`（全过），但依赖大批 mock 时"通过"不等于实际集成正确。建议至少保留一个 e2e 冒烟（存在 `tests/test_e2e_real_models.py` 但依赖本地模型）。

---

## 7. 待办清单（按建议执行顺序）

### 立即处理（P0）
- [ ] T-P0-1 `backend/api/routers/files.py` 补 `from typing import Optional`（并回归 py3.11+py3.14 双环境验证）
- [ ] T-P0-2 `/admin` 端点增加认证（至少 token/HTTP Basic）或默认关闭 `ADMIN_ENABLED`
- [ ] T-P0-3 `stream_ollama_chat` 设置合理 timeout（建议 120s），`OLLAMA_HOST` 默认改 `http://127.0.0.1:11434`

### 短期（P1）
- [ ] T-P1-1 URL 抓取防 SSRF：scheme/host allowlist + 内网地址黑名单 + 禁用用户自定义 header
- [ ] T-P1-2 embedder 失败语义改为 raise（失败就重试/失败入库，禁止静默零向量）
- [ ] T-P1-3 删除流程加物理文件清理 + visual_store + chunk_mapping 清理
- [ ] T-P1-4 by-image 端点加文件大小上限
- [ ] T-P1-5 `_ocr_for_caption` 移出全局 mutable state（传参或 contextvar）
- [ ] T-P1-6 修正 `system_prompt` → 删除或改为 messages 拼接
- [ ] T-P1-7 OCR job polling 增加单次 poll timeout + 整体 deadline 在客户端侧
- [ ] T-P1-8 chat/search 错误 detail 去除 str(e)，改为稳定错误码
- [ ] T-P1-9 事件循环阻塞点：aiohttp 全部锁进 `asyncio.to_thread`

### 中期（P2/P3）
- [ ] T-P2-1 Note title 限长/截断，禁止超长文件名
- [ ] T-P2-6 asset path 校验改 `os.path.commonpath`；避免 `?token=` 走 public 访问 log
- [ ] T-P2-7 移除 `/search-by-image` alias（或文档化）
- T-P3-1 重命名 `LANCE_DB_VECTOR_STORE_PERSISTS_DIRECTOY`（全链路 + .env.example + specs）
- [ ] T-P3-2 `SECRET_KEY` 默认 insecure：启动阻断（raise）而非告警
- [ ] T-P3-3 清理 dead config（`RESET_PASSWORD_TOKEN_SECRET` 等）或接入实现
- [ ] T-P3-4 `adapter.py` `SMALL_TO_LARGE_ENABLED`：要么接入 config（`CHUNK_EXPAND_ENABLED`），要么删除孤儿 wrapper
- [ ] T-P3-6 `.env.example` 与默认值对齐
- [ ] T-P3-10 vite dev server 默认 host 固定 `0.0.0.0` 需文档说明/回退
- **[ ] T-P4-2 `.gitignore` 增加 `models/`（1.5GB 权限）**
- [ ] T-P5-1 search.py / documents.py 模块拆分（先写 spec，不动代码）

### 仓库/环境清理（低优先级）
- [ ] T-P4-1 合并 .agent/.agents/docs/specs 下重叠文档
- [ ] T-P4-2 清理 requirements 假包（asyncio==3.4.3 等）
- [ ] T-P5-5 补充核心模块 docstring / 统一中英注释风格
- [ ] T-P5-7 OpenAPI schema 导出（`docs/openapi.json`）
- [ ] T-P4-3 移除 dead code（`is_file_pdf`、`url_processing_queue`、micro_batch created_at 等）

---

## 8. 环境与运行风险备注

- `.venv` 由 uv 创建且 site-packages 为空，`uv run` 构建失败（pypika 冲突）→ 当前本地测试环境依赖其他 uv cache 注入，**新克隆/换机器会直接不可复现**。【疑似，替换属环境问题】
- CI（github workflows/test.yml）在 Python 3.11 上 `pip install -r requirements.txt` 执行；py3.11 下 P0-1 将直接让 pytest collection 失败 —— 意味着 CI 要么当前是红的，要么该文件最近才被删 import 行。【需 CI 运行确认】
- `docker-compose.yml` 将宿主机配置目录挂载到容器 `/home/appuser/.config/wenjv`；宿主机目录所有权（uid mismatch）会导致容器内 appuser 写权限问题。【疑似，常规坑】
- `docs/deployment-diagram.md`、`docs/wenjv_context_and_roadmap.md` 处于更新滞后状态。

---

## 9. 审计统计

| 维度 | 数量 |
|---|---|
| 后端 Python 文件 | 73（含 pyc 剔除后） |
| 前端文件 | 16 |
| 测试文件 | 52 个 pytest |
| eval 脚本 | 8 个行为脚本 + benchmark |
| 高置信问题 | 31 |
| 【疑似】问题 | 14 |
| 环境/文档问题 | 若干（P3/P4/P5） |

扫描覆盖率：后端核心代码 100% 逐文件阅读；测试/ eval 抽查高负载文件；前端全部 Vue 组件阅读。

---

**说明**：本报告为静态分析 + 关键路径运行时复现的结论；涉及【疑似】条目均给出了验证路径，建议实机验证后再采纳修复。
