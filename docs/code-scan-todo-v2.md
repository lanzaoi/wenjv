# wenjv 全量代码扫描 · 待办清单（v2）

> 扫描范围：`backend/`、`web/src/`、`start/`、`tests/`、`eval/`、`Dockerfile`/`docker-compose.yml`、`.github/`、根配置与文档。
> 方式：全量静态阅读 + 关键疑点运行时/语义复现（Python 注解求值语义、git 历史、requirements 核对、测试覆盖分析）。
> 原则：**只报告，不含修复代码**；不确定项标注【疑似】。
> 说明：本文档取代并纠正 `docs/code-scan-todo.md`（其 P0-1「files.py 缺 Optional」已不成立——该文件第 2 行已导入 `Optional`）。

## 0. 结论摘要

| 级别 | 数量 | 说明 |
|---|---|---|
| P0 阻断级 | 4 | 不修则后端无法启动 / 登录完全不可⽤ |
| P1 高危隐患 | 10 | SSRF、零认证面板、路径穿越、不安全默认值等 |
| P2 竞态/一致性/异步 | 12 | 双认领、毒缓存、事件循环阻塞、孤儿 future 等 |
| P3 资源泄漏 | 9 | 无上限响应、渲染无页数封顶、句柄不释放、blob 泄漏等 |
| P4 异常分支/逻辑缺陷 | 19 | 吞异常、双重解析、转义空转、隐式局部变量探测等 |
| P5 依赖/配置 | 15 | asyncio 后移植包、jose CVE、transformers 缺失、环境矛盾等 |
| P6 前端缺陷 | 8 | 死代码且契约错位、SSE 无心跳、注册即登录断裂等 |
| P7 死代码/冗余/魔法常量 | 9 | legacy 队列、mock 兼容代码、注释路径漂移等 |
| P8 测试/eval/工程卫生 | 8 | 缺失数据文件、mock 掩盖真实链路、会话文稿入库等 |
| **合计** | **约 93（含【疑似】14）** | |

代码规模：后端约 15k 行 Python，前端约 4k 行 Vue/JS，测试约 6k 行 Python，eval 约 2.3k 行。

---

## 1. P0 — 阻断级

### P0-1 `backend/core/embedder.py:285` `Optional` 未导入 — Docker/CI 环境导入即崩【确定性】

- 模块级注解 `_local_bge_m3_instance: Optional[LocalBGEM3OnnxEmbeddings] = None`，但文件仅 `from typing import List`。
- Python ≤3.13 注解**即时求值** → `NameError`；`lance_db.py`/`adapter.py` 顶层 `from backend.core.embedder import get_embedder` → 整个后端无法启动。
- **本地 Python 3.14.8 因 PEP 649 延迟求值不崩**（`tests/__pycache__` 里的 cpython-314 产物证实测试在 3.14 上跑且全绿），恰好掩盖此 bug。
- 影响面：Docker `python:3.11-slim`、CI `python-version: '3.11'` → 生产部署形态必崩。
- 待办：补导入；并在 CI 中用 3.11 跑一次真实 import smoke（当前测试全部 mock 掉了导入链）。

### P0-2 `backend/api/dependencies.py` `UserManager` 未实现 `hash_password`/`verify_password` — 注册/登录 500【确定性】

- 全仓库 grep 零处实现（`passlib`/`CryptContext`/`bcrypt` 均未被代码引用）。
- fastapi-users `BaseUserManager` 对这两个方法抛 `NotImplementedError` → `/auth/jwt/login`、`/auth/register`、PUT `/users/me`（改密码）全部 500。
- 影响：Web 登录视图永远报错；首用户创建无入口；多用户场景不可用。
- 测试盲区：所有 router 测试用 `dependency_overrides[current_active_user]` 替换认证，真实认证路径零覆盖。
- 待办：实现密码哈希/校验；增加一条走真实 `UserManager` 的注册→登录契约测试。

### P0-3 `backend/vector_store/chroma_db.py:30,82` `Document` 未导入 — Chroma 后端写入即 `NameError`【确定性（潜伏）】

- 文件使用 `Document(...)` 但从未 `from langchain... import Document`。
- 当前 `DEFAULT_VECTOR_DB=LANCE` 不触发；切 Chroma 即崩。

### P0-4 注册后自动登录流程断裂【高置信】

- fastapi-users 注册 router 默认要求邮箱验证（项目未配置 verify router，`is_verified` 默认 False）；前端 `auth.register()` 注册成功后立即调用 `login()`。
- 叠加 P0-2（注册本身 500），新用户无任何可用登录路径。
- 待办：明确单用户自托管策略（注册即 verified + 自动建首用户，或关闭注册）。

---

## 2. P1 — 安全暴露面

### P1-1 SSRF（链接抓取）【确定性】

- `backend/worker/url_processor.py`：aiohttp 直取用户提交 URL（`allow_redirects=True, max_redirects=10`），无 scheme 白名单、无内网 IP/169.254 元数据防护、无响应大小上限。
- `backend/worker/url_processor_recursive.py`：`RecursiveUrlLoader(max_depth=2)` 跟随站内任意链接递归，可将内网服务整棵抓进库。
- 入口：`POST /links/submit`、`POST /links/crawl`（任何登录用户可驱动服务器访问内网/云元数据）。
- 待办：SSRF 防护（协议白名单 + 解析后 IP 段黑名单 + 重定向后复检 + 响应体上限）。

### P1-2 `/admin` 面板零认证【确定性】

- `backend/api/routers/admin.py`：router 仅挂 `Depends(check_admin_enabled)`（默认 True），无任何用户检查。
- 暴露面：所有用户的查询全文（`query_logs`）、命中率/延迟统计、API 调用计数；`POST /admin/reset-counts` 为无鉴权状态变更入口。
- docker-compose 将 `8000:8000` 直接映射，页面文案自述"无需认证，勿暴露公网"——默认配置即违反该警告。
- 待办：加超管鉴权或默认关闭并文档化；至少对 reset-counts 加保护。

### P1-3 `/documents/assets/image?pdf=` 路径穿越【确定性】

- `backend/api/routers/documents.py:155-166`：`pdf` 参数只校验 `.pdf` 后缀，`upload_root / pdf` 未归一化 → `pdf="../../home/x/secret.pdf"` 可读取 uploads 之外任意 `.pdf` 文件。
- 同接口 `path=` 模式只校验"位于 upload 目录内"，**不校验归属** → 任意登录用户可读他人资产。
- 待办：`Path.resolve()` + `is_relative_to(upload_root)` 校验（path 模式已有，pdf 模式补齐）；资产访问绑定资源归属或签名 URL。

### P1-4 JWT 走 URL（`?token=`）【确定性】

- 后端支持 `assets/image?token=` 认证（documents.py）；前端 `getCitationImageUrl`（ChatView.vue）把完整 JWT 拼进图片 URL。
- 泄漏面：浏览器历史、Referer、代理/访问日志、`<img>` 预加载缓存。
- 待办：改用一次性签名短令牌或 Cookie；至少缩短有效期并文档化。

### P1-5 不安全默认值被放行【确定性】

- `SECRET_KEY`/`RESET_PASSWORD_TOKEN_SECRET`/`VERIFICATION_TOKEN_SECRET` 默认 `"YOUR_SECRET_KEY_CHANGE_THIS"`；`main.py` 仅 warning，仍以该密钥签发/校验 JWT（任何人可伪造令牌）。
- `SERVER_LOG_LEVEL` 默认 `debug`；`ADMIN_ENABLED` 默认 True（见 P1-2）。
- 待办：不安全密钥时拒绝启动（fail-fast）而非仅告警；日志级别默认 INFO。

### P1-6 监听面过宽【确定性】

- `OLLAMA_HOST` 默认 `http://0.0.0.0:11434`、`SERVER_HOST` 默认 `0.0.0.0`；`start/start.sh`、`start/launcher.py`、Dockerfile 均绑 `0.0.0.0`。
- 本地开发直接暴露局域网；Ollama 若同机监听则间接暴露模型 API。
- 待办：默认 `127.0.0.1`，暴露文档化；`OLLAMA_HOST` 用 `127.0.0.1` 而非 `0.0.0.0`。

### P1-7 CORS 宽口径组合【疑似（取决于部署配置）】

- `allow_credentials=True` + `allow_methods/headers=["*"]`；用户在 env 设 `CORS_ORIGINS=["*"]` 时 Starlette 会回显任意 Origin 并带凭证 → 全站跨站可携带身份请求。
- 待办：生产环境 CORS 白名单校验/告警。

### P1-8 JWT 双实现并存【确定性】

- `backend/api/service.py` 用 `python-jose`（停维护、CVE-2024-3160），fastapi-users 用 PyJWT；两套校验逻辑（含 audience/exp 处理）可能漂移。
- 待办：统一到 PyJWT 或 fastapi-users 的策略；删除 python-jose 依赖。

### P1-9 `milvus_db.py:267,278` 残留 debug print【确定性】

- `print(query_embedding, "qb")` / `print(search_results, "sr..")` 完整输出 1024 维向量与搜索结果到 stdout → 日志膨胀 + 向量/内容泄漏。
- 待办：删除；如需调试走 logger.debug 且脱敏。

### P1-10 `.env.example` 占位符非空【轻微】

- `EMBEDDING_API_KEY="sk-your-embedding-key-here"` 等非空占位值会被 pydantic 当作合法 key 使用，复制示例后报错难懂。
- 待办：占位符留空或改为注释示例。

---

## 3. P2 — 竞态 / 一致性 / 异步陷阱

### P2-1 `claim_next_job` 非原子认领【确定性】

- `backend/worker/durable_jobs.py`：`SELECT pending` 后在应用层置 `running`，无 `UPDATE ... WHERE status='pending'` 乐观锁。
- 当前单 dispatcher 安全；引入多 worker/多实例（Docker `--workers`、横向扩容）即重复认领、重复嵌入。
- 待办：原子认领或乐观锁 + 冲突重试。

### P2-2 零向量毒化持久缓存【确定性】

- embedder 失败路径（401/超时/非 200/重试耗尽）fail-soft 返回 `[0.0]*dims`；`CachedEmbedder` 将零向量写入**持久** SQLite 缓存。
- 后果：同文本永久命中毒缓存；零向量破坏 Lance cosine/IVF_PQ 行为（代码注释自认 PQ 遇零向量会崩）。
- 待办：失败不写缓存；缓存写入前校验范数；存量毒缓存清理脚本。

### P2-3 `update_file_with_backup` 并发摧毁【确定性】

- `backend/core/utils.py`：`{path}.bak` 无锁，两并发更新同一笔记互相覆盖，恢复逻辑交叉执行。
- 待办：原子写（临时文件 + rename）或按文件加锁。

### P2-4 PERSISTED checkpoint 重跑导致重复条目【确定性】

- job 在 `_save_checkpoint(PERSISTED)` 后、标记 SUCCEEDED 前崩溃 → reclaim 重置 PENDING → `_execute_document` 跳过嵌入但**再次执行 multimodal 与 auto-tagging** → `visual_store`/FTS 重复。
- 待办：checkpoint 语义细化（SUCCEEDED 幂等标记先于重资源步骤，或 multimodal 步骤去重）。

### P2-5 删除链路非原子【确定性】

- `delete_file_service`/`delete_note_service`/`delete_link_service`：先删向量库再 commit DB（或反之），任一步失败留下孤儿向量/DB 行；FTS5 同步删除失败仅 log。
- 待办：删除编排统一 + 对账清理任务。

### P2-6 `_wake` Event 漏唤醒【低】

- `notify_workers()` 发生在 dispatcher `clear()` 与 `wait_for()` 之间会丢事件，靠 2s 轮询兜底 → 上传后状态刷新延迟放大。
- 待办：接受现状或改条件变量。

### P2-7 `MicroBatchEmbedder` 超时孤儿与挂起【确定性】

- 同步入口 `embed_documents` 用 `fut.result(timeout=60)`：超时抛错但队列条目与 future 残留。
- `_aggregator_loop` 遇 `CancelledError` 直接 break，**不 resolve 队列中全部 future** → `embed_documents_async` 的 `gather` 永久挂起，进程关闭时 hang。
- 待办：超时/取消路径统一 reject 未决 future；关闭时 drain 队列。

### P2-8 async 路由中同步阻塞调用【确定性（多点）】

- `backend/api/services/search.py` MMR 分支直接调 `embeddings.embed_query/embed_documents`（同步网络+ONNX）→ 阻塞事件循环。
- `_late_chunking_search` 全程同步（嵌入 + 全表 DB 循环 + 逐 chunk 嵌入），且在 async `search_documents` 体内直接调用。
- `backend/core/auto_tagger.py` → `get_user_tags_summary_sync` 同步 SQLAlchemy。
- `backend/core/utils.py record_chunk_mappings` 同步引擎 + 循环 merge（ingestion 路径）。
- `embedder._call_api` 内 `time.sleep` 重试（同步 httpx）。
- 待办：统一 `asyncio.to_thread` 包裹或改异步客户端；对 rerank/embed 延迟埋点。

### P2-9 Observability 告警永不触发【确定性】

- `observability.increment_api_count` 模块函数每次调用新建 `ObsLogger()` → streak 计数器即时重置 → FTS5 零命中/延迟/错误三套告警阈值永远达不到。
- 另：模块级 `ObsLogger()` 实例（search.py/admin.py）各自持有独立 streak，告警归属混乱。
- 待办：模块级单例；streak 语义按实例文档化。

### P2-10 dispatcher 错误死循环【确定性】

- `job_dispatcher_loop` 对持久性异常（如 DB 不可用）固定 1s 报复循环，无退火/熔断 → CPU/日志风暴。
- 待办：指数退避 + 最大重试后降级。

### P2-11 `process_recursive_url_queue` 无监督【确定性】

- `main.py` 裸 `asyncio.create_task(...)`，内部循环死亡即静默（无异常日志、无重启）。
- 待办：任务包装 + 崩溃重启。

### P2-12 递归爬取队列无界【确定性】

- `enqueue_recursive_crawl_service` 直接 `put`，无背压；crawl 每页建 Link + 全量嵌入，宽站点内存/库容量爆炸。
- 待办：队列上限 + 每用户并发上限 + 总页数上限。

---

## 4. P3 — 内存 / 句柄泄漏

### P3-1 aiohttp 响应无大小上限【确定性】

- `url_processor.process_single_url`：`await response.text()` 全量读入 + `BeautifulSoup.get_text()` 无截断 → 超大页面内存放大。
- 待办：流式读取 + 上限 + 截断入库。

### P3-2 多模态 PDF 渲染无页数上限【确定性】

- `multimodal.extract_images_from_pdf`/`process_pdf_tables` 渲染**每一页**（scale=2 PNG 全量驻留）；OCR 路径有 `OCR_MAX_PAGES=30`，multimodal 路径没有。
- 待办：统一页数封顶。

### P3-3 PDF 句柄泄漏【确定性】

- `pdf_render.render_pdf_pages` 渲染中途异常不执行 `pdf.close()`；`pdf_parser` 的 `PdfReader` 从不显式关闭；`multimodal`/`visual_assets` 多处 `PdfDocument` 异常路径不 close。
- 待办：try/finally 统一 close。

### P3-4 ChatView blob URL 泄漏【确定性】

- `t0PreviewUrl()` 每次调用 `URL.createObjectURL` 且从不 revoke（FileDrop 组件会 revoke，ChatView 不会）；消息保留 `imageUrl` 使泄漏随轮次累积。
- 待办：统一 revoke 时机。

### P3-5 缓存无上限/无清理【确定性】

- `embed_cache` 只增不删；`query_result_cache` 过期行仅在命中时删除，无定期清理；`DocEmbeddingTable`/`ChunkMappingTable` 不随资源删除清理。
- 待办：定期清理任务 + 容量上限。

### P3-6 `mm_assets` 快照永不清理【确定性】

- PDF 页快照按 `{resource_id}` 目录落盘，删除源文件后资产残留。
- 待办：随资源删除联动清理。

### P3-7 vector store 客户端不释放【确定性】

- lancedb/chromadb/milvus 模块级单例，lifespan 无任何 dispose。
- `_lance_write_lock` 跨线程持锁期间做 FTS5/SQLAlchemy 同步 IO（长锁放大阻塞面）。
- 待办：shutdown 钩子 dispose；锁内只做最小必要操作。

### P3-8 HTTP 连接 churn【确定性】

- `embedder.HTTPOpenAIEmbeddings` 构造 `self._client`（keep-alive 池）但 `_call_api` 每次新建 `httpx.Client` → `_client` 死代码 + 连接复用完全失效。
- GoogleEmbeddings/visual_embedder 同模式。
- 待办：复用客户端或删除死代码。

### P3-9 Observability 内存态【记录】

- streak 计数器在内存，重启清零（可接受，需文档化）。

---

## 5. P4 — 异常分支遗漏 / 逻辑缺陷

### P4-1 `parse_document` 双重解析【确定性】

- `parsers/registry.py`：cache-miss 分支内 `registry.parse()` 抛错被外层 `except: pass` 吞掉后再调一次 → 大文件解析两遍且异常语义混乱。
- 待办：异常直接冒泡，删除兜底重调。

### P4-2 `text_parser` 严格 utf-8【确定性】

- 非 UTF-8 的 txt/md（GBK 等）→ `UnicodeDecodeError` 使整个 job 失败；auto-tagger 读文件却用 `errors="ignore"`，策略不一致。
- 待办：解码探测 + ignore 回退。

### P4-3 `embedder.py` 402 分支异常逃逸【确定性】

- 402 余额不足回退本地 BGE：`get_local_bge_m3_embedder()` 模型缺失抛 `FileNotFoundError`，不属 ValueError/RequestError → 冒泡至 MicroBatchEmbedder 整批 set_exception。
- 待办：回退失败需显式降级策略（记录 + 用零向量或抛错，二选一统一）。

### P4-4 LIKE 通配符转义空转【确定性】

- `lance_db.fetch_documents_keyword`：先 `\\%`/`\\_` 再立即 `replace` 去掉转义 → 用户查询中的 `%`/`_` 仍作通配符；FTS5 fallback 的 LIKE 无 ESCAPE 子句。
- 待办：统一 LIKE 转义策略（ESCAPE '\'）。

### P4-5 `"parsed" in locals()` 隐式局部变量探测【确定性】

- `durable_jobs._execute_document` 用 locals() 探测变量存在性 → 脆弱，重构即坏。
- 待办：显式状态变量。

### P4-6 `multimodal._extract_markdown_tables` 逻辑错【确定性】

- 跳过分隔行后应检查 `lines[j]` 是否为数据行，实际重复检查 `lines[i]` → 误判/漏判表格。
- 待办：修正判定逻辑并补边界单测。

### P4-7 rerank 索引越界被吞【确定性】

- `search.py` 消费 `item["index"]` 未校验 `< len(docs)`，IndexError 落入外层 except → 静默保留旧排序（现象：rerank"无效"且无区分性日志）。
- 待办：显式校验 + 告警日志。

### P4-8 非-hybrid+视觉分支默认权重不一致【疑似】

- `search.py` 该分支 `w_vis` 回退默认 1.0，与 `settings.HYBRID_RRF_WEIGHT_VISUAL`（默认 0.5）不一致，无注释说明。
- 待办：统一读取 settings 或注释设计意图。

### P4-9 MMR `same_resource` rid 兜底用 title【疑似】

- 无 `resource_id` 的 chunk 以 title 去重 → 同标题不同资源的 chunk 被误合并。
- 待办：去重键定义文档化 + 数据分布核查。

### P4-10 `deoverlap` 链式合并【疑似】

- `any(|order 差|≤1)` 对 cluster 全体比较 → 结果列表中不相邻的 chunk 也可能链式合并成大块。
- 待办：合并策略与上限核查。

### P4-11 `ChunkString.metadata: dict = {}` 类级可变默认【确定性（模式危险）】

- 当前靠实例赋值掩盖；任何人直接读 `ChunkString("x").metadata` 拿到共享 dict。
- 待办：`metadata=None` + 惰性初始化或 dataclass。

### P4-12 `IngestionJob.status` 默认塞 enum 对象【疑似】

- `default=JobStatus.PENDING` 直接给 enum 实例而非 `.value`；sqlite3 可绑定 str 子类，其他数据库方言不保证。
- 待办：统一存字符串值。

### P4-13 历史图片 blob: URL 静默丢弃【确定性】

- 前端 `historyForApi` 把 blob: URL 塞进历史图 → 后端 `resolve_image_from_identifier` 不处理 `blob:` → 多轮视觉上下文实际不生效。
- 待办：前端 history 仅传可解析标识；后端明确拒绝并记录。

### P4-14 `chat.py` 默认模型回退链断裂【确定性】

- `getattr(settings, "DEFAULT_CHAT_MODEL", None)` —— 该配置项在 `config.py` 从未定义 → 永远回退魔法值 `"mistral:7b-instruct-q4_0"`。
- 待办：定义配置项或删除回退。

### P4-15 OCR 提交文件名固定 `image.png`【疑似】

- PDF 渲染出的 PNG 字节以 `image.png` 提交 OCR 服务 → 服务端 MIME 推断错误风险。
- 待办：按真实扩展名/MIME 提交。

### P4-16 `health` 端点吞异常【确定性】

- `main.py` DB/lance 探活全部 `except: pass` → 恒返回 degraded/unreachable 无原因，误导监控。
- 待办：返回结构化原因。

### P4-17 `validate_jwt_token` 吞所有异常【确定性】

- 含 SECRET_KEY 配置错误在内一律返回 valid:false，排障困难。
- 待办：区分校验失败与内部错误（仅前者对用户返回 false）。

### P4-18 `retry_job_service` 不处理 stale RUNNING【确定性】

- 对 RUNNING 返回 409，UI 无"恢复卡死任务"入口（依赖 dispatcher 30 分钟 reclaim）。
- 待办：允许对超时 RUNNING 触发 reclaim/retry。

### P4-19 图片查询只校验扩展名【疑似】

- `validate_image_query_upload` 只查后缀，内容信任上游 PIL/OCR。
- 待办：至少校验 magic bytes。

---

## 6. P5 — 依赖 / 配置

### P5-1 `asyncio==3.4.3`【确定性，高危】

- requirements.txt 锁了 Python 2 时代的 asyncio 后移植包；3.11+ 安装可能遮蔽/污染标准库 asyncio，且完全没有必要。
- 待办：移除。

### P5-2 `python-jose==3.4.0`【确定性】

- 停维护，CVE-2024-3160；与 PyJWT 并存（见 P1-8）。
- 待办：迁移 PyJWT 后移除。

### P5-3 `passlib==1.7.4` + `bcrypt==4.3.0`【确定性】

- 已知 `__about__` 不兼容问题；且代码零处使用 passlib（P0-2 的根因之一），属死依赖。
- 待办：实现密码哈希时选一方案；删除死依赖。

### P5-4 `huggingface-hub==0.29.1`【疑似】

- < 0.34（符号链接遍历修复）。本项目直接用本地模型文件、无在线拉取，暴露面低。
- 待办：随 langchain 升级一并刷新。

### P5-5 `transformers` 未声明但被 import【确定性】

- `rerank_client.py:25` `from transformers import AutoTokenizer` 不在 requirements → 本地 ONNX rerank 必 ImportError → fail-open 静默降级（RERANK_ENABLED 默认 True 却永远不生效）。
- 待办：补依赖或改用 tokenizers 直接加载。

### P5-6 langchain 系版本偏旧【疑似】

- `langchain==0.3.19 / langchain-community==0.3.18 / langchain-chroma==0.2.2`；RecursiveUrlLoader 恰在被使用。
- 待办：对照安全通告升级并回归。

### P5-7 pinned 依赖与本地 Python 3.14 不兼容【确定性】

- `numpy==1.26.4 / pyarrow==19.0.1 / onnxruntime==1.20.1` 等不支持 3.14 → 本地 `pip install -r requirements.txt` 失败；requirements 实际只覆盖 3.11（Docker/CI）。
- 待办：明确支持矩阵或提供 dev 依赖集。

### P5-8 `bs4==0.0.2` 等冗余/传递依赖【确定性】

- `bs4`（元包冗余）、`Deprecated`、`build`、`pyproject_hooks`、`toml`、`makefun`、`jsonpatch`、`jsonpointer` 等编译期/传递依赖被全量手写 pin（手抄 lockfile，无上游约束保证）。
- 待办：改用 pip-compile 生成 lock。

### P5-9 可选解析器未锁上界【确定性】

- `pypdf>=5.0.0 / python-docx>=1.1.0 / python-pptx>=1.0.0 / pypdfium2>=4.30.0 / google-generativeai>=0.8.0 / pdfplumber>=0.11.0 / jieba` 无上界 → 未来大版本变更直接破坏 ingestion。
- 待办：锁上界。

### P5-10 `GEMINI_API_KEY` 校验器与 .env 脱节【确定性】

- `config.py` 校验器只读 `os.environ`；`backend.env` 里写 `GOOGLE_API_KEY` 不生效（pydantic-settings 不写回 os.environ），与注释宣称不符 → Gemini caption/multimodal 静默无 key。
- 待办：在 Settings 中显式声明 `GOOGLE_API_KEY` 字段或改文档。

### P5-11 `.env.example` 与代码默认值矛盾【确定性】

- `EMBEDDINGS_MODEL=chroma/all-minilm-l6-v2-f32 + 384` vs 代码默认 `BAAI/bge-m3 + 1024`；`RERANK_ENABLED=false` vs 代码默认 True。直接复制 example 得到与文档不一致的混合配置。
- 待办：example 与默认值对齐。

### P5-12 Dockerfile【确定性】

- `build-essential` 留存镜像内；无 HEALTHCHECK；配了 `--proxy-headers` 但无 `--forwarded-allow-ips`。
- 待办：多阶段构建或删构建依赖；补健康检查。

### P5-13 docker-compose【确定性】

- 无 healthcheck/资源限制；配置目录挂载路径依赖 `USERPROFILE` 展开，Linux/CI 语义含糊。
- 待办：健康检查 + 文档化挂载路径。

### P5-14 pyproject【确定性】

- `license={text=...}` 为 PEP 639 弃用写法；`packages` 手工列举（新增子包易漏）；无 `[tool.pytest.ini_options]`。
- 待办：现代化 + 补 pytest 配置。

### P5-15 CI workflow【确定性】

- 裸 3.11 + `pip install -r requirements.txt`：会因 P5-1/P0-1 触发真实导入崩溃（当前测试全 mock 掩盖）；无 secrets/缓存/超时控制；tests 导入即对 `~/.config/wenjv` 产生目录副作用。
- 待办：CI 增加真实 import smoke；隔离 HOME。

---

## 7. P6 — 前端缺陷

### P6-1 删除三函数死代码且契约错位【确定性】

- `api/client.js` `deleteFile/deleteNote/deleteLink` 无任何调用方（LibraryView 无删除 UI）；且 `deleteFile(token, fileId)` 传 **id** 给后端 `DELETE /file/{filename}`（文件名路径参数）、`deleteNote` 同理 → 一旦接入 UI 即 404。
- 待办：删除死代码或修正契约并补删除 UI。

### P6-2 readSSE 静默吞 JSON 解析错误【确定性】

- 畸形帧/协议变更前端无感知，表现为"对话莫名中断"。
- 待办：记录并上报解析失败计数。

### P6-3 注册后自动登录必然失败【确定性，联动 P0-2/P0-4】

- `auth.register()` → `login()` 失败且错误文案指向密码错误，误导用户。
- 待办：见 P0-4。

### P6-4 引用图片 URL 拼 token【确定性，联动 P1-4】

- 见 P1-4。

### P6-5 SSE 无心跳/无超时控制【部分疑似】

- 检索阶段（可能数十秒）发出 `citations` 前若网络抖动无反馈；`AbortController` 换发新请求时旧流无取消清理。
- 待办：SSE 心跳事件 + 前端总超时。

### P6-6 `windowSize` 无边界钳制【疑似】

- `v-model.number min/max` 仅 HTML 约束，非数字以字符串透传后端（`window_size or 5` 兜底）。
- 待办：发送前 Number 钳制。

### P6-7 FileDrop 文件标签页无 accept 过滤【确定性】

- 仅图片/笔记标签页有 accept；拖拽多文件只取 `files[0]` 无提示。
- 待办：补 accept + 多文件提示。

### P6-8 LibraryView 不轮询处理状态【体验缺陷】

- 上传后 StatusDot 永远停在 pending，无自动刷新（只有手动刷新）。
- 待办：轮询或 WebSocket 推送。

---

## 8. P7 — 死代码 / 冗余 / 魔法常量

### P7-1 `url_processor.py` legacy 队列死代码【确定性】

- `url_processing_queue`/`process_url_queue`/`_legacy_safe_process` 无人 enqueue 无人启动（main.py 只启动 recursive 队列）。
- 待办：删除或标注保留原因。

### P7-2 `fetch_documents_by_resource` 含 mock 兼容代码【确定性】

- `is_mocked = ...to_pandas._mock_return_value...` 生产路径判断测试桩属性。
- 待办：删除。

### P7-3 `ChunkString` 类级可变默认【确定性】

- 见 P4-11。

### P7-4 `fetch_documents_keyword` 转义逻辑空转【确定性】

- 见 P4-4。

### P7-5 魔法常量散落【确定性】

- `WINDOW_SIZE_MULTIPLIER=10`（链接窗口×10 无解释）；3 处 ONNX `intra_op_num_threads=14` 硬编码；1200/1500/150/512/64/224/1280/85/16/32/200/180/100 等截断阈值遍布无统一定义；SiliconFlow 输入截断 `t[:1200]`（bge-m3 支持 8192，长 chunk 语义被静默腰斩）；`run_coroutine_threadsafe` 硬编码 60s。
- 待办：收敛到 settings/常量模块 + 注释设计依据。

### P7-6 硬编码模型名【确定性】

- `"mistral:7b-instruct-q4_0"`、`"qwen2.5:7b"`、`"gemma-4-31b-it"`（该模型名可用性【疑似】）、`"Qwen/Qwen3-VL-8B-Instruct"` fallback 列表、`"image.png"` OCR 文件名、`"model_quantized.onnx"` 等。
- 待办：收敛到 settings；模型可用性核对。

### P7-7 头部注释路径漂移【确定性】

- `models.py/schemas.py/service.py/dependencies.py` 首行注释写 `backend/auth/...`，实际在 `backend/api/...`。
- 待办：修正。

### P7-8 复制粘贴错误【确定性】

- `delete_link_service` 404 detail 说 "File not found"。
- 待办：改为 "Link not found"。

### P7-9 `DocEmbeddingTable.dims` 默认 1024 失真【轻微】

- dims 由写入值决定，Schema 默认值与实际维度无关联。
- 待办：移除默认值或动态维护。

---

## 9. P8 — 测试 / eval / 工程卫生

### P8-1 `eval/run_eval.py` 引用缺失数据文件【确定性】

- `load_sample()` 打开 `eval/sample_1000.json`，该文件在 .gitignore 中被排除且仓库不存在 → eval 脚本开箱即崩。
- 待办：生成并入库（或改为参数化路径 + 文档）。

### P8-2 测试大量 mock 掩盖真实链路【确定性】

- 全仓 747 处 Mock/patch；P0-1/P0-2 均被 mock 掩盖；真实向量库/嵌入/认证零集成覆盖。
- 待办：补最小真实链路冒烟（import + register→login + upload→search）。

### P8-3 测试导入期副作用污染真实配置目录【确定性】

- tests 直接 import 生产 `backend.main` → 触发 Settings import 副作用（mkdir `~/.config/wenjv`、建 lance 目录、读真实 backend.env）。
- 待办：app-level 隔离 fixture（tmp HOME/config dir）。

### P8-4 `.agents/teamwork/` 会话文稿入库【确定性】

- 40+ 份 agent 会话文稿（BRIEFING/DISPATCH/progress/handoff）；根目录 `findings.md/progress.md/task_plan.md` 与 `.agent/` 重复；历史扫描报告 `docs/code-scan-todo.md` 与现状脱节（其 P0-1 不成立）。
- 待办：归档/清理；以本文档为唯一现行扫描基线。

### P8-5 `__pycache__` 未入库【已核实】

- `git ls-files` 为 0，.gitignore 覆盖，仅建议本地清理。

### P8-6 `eval/` 直接改写全局 settings 做矩阵【疑似】

- `run_eval.py` 等直接改 `settings.*` 单例开关，并发/顺序敏感，无 fixture 隔离。
- 待办：eval 内部配置隔离。

### P8-7 启动脚本路径漂移【轻微】

- `start-wenjv.bat` 用 `ROOT\venv`（Windows 习惯），仓库/文档实际为 `.venv`；`kb_launcher.py` 仅 shim 无文档指引。
- 待办：对齐或文档化。

### P8-8 CI 无超时/缓存【轻微】

- 见 P5-15。

---

## 附：建议处理顺序

1. **立即**：P0-1（补 `Optional` 导入）、P0-2（实现密码哈希）——否则生产不可用；
2. **本迭代**：P1-2（admin 鉴权）、P1-3（pdf 路径穿越）、P1-1（SSRF）、P2-2（毒缓存）、P2-7（挂起）；
3. **常规迭代**：P2/P3 其余、P5 依赖清理（asyncio/jose/transformers）；
4. **技术债排期**：P7/P8。
