# 工程卫生扫描清单 — wenjv (jolly-hawking)

> 扫描日期：2026-11（基于 `git status` 工作树快照）
> 范围：backend / web / eval / tests / start / models / specs / docs / .agent / .agents
> 方式：静态扫描（AST 启发式 + grep + 引用计数），**未修改任何内容**。
> 【疑似】= 自动扫描结论需人工复核；未标注的为多证据确认项。

---

## 1. 无用文件 / 孤儿文件

| 文件/目录 | 问题描述 | 状态 |
|---|---|---|
| `start/launcher.py` (135 行) vs `start/wenjv_launcher.py` (195 行) | 两套 launcher 并存且互不为包装。`launcher.py` 是 pyproject 定义的入口（`wenjv` / `wenjv-start` / `wenjv-start-ui` → `start.launcher:*`），而 `start-wenjv.bat` 直接调用 `wenjv_launcher.py` | 【疑似】双入口长期并存易漂移 |
| `start/kb_launcher.py` | 仅 5 行的 `from start.wenjv_launcher import *` shim，全仓库零引用 | 【疑似】可废弃 |
| `start/__init__.py` | 0 字节空文件 | 低风险 |
| 根目录 `findings.md` / `progress.md` / `task_plan.md` vs `.agent/` 同名文件 | 同一任务日志的两个版本，内容不一致；根目录版还引用了旧项目 venv（`dazzling-bell/.venv`） | 【疑似】应保留一套 |
| `.agents/teamwork/` (452K，17 个子目录 BRIEFING/DISPATCH/handoff/progress) | 已 gitignore，git status 存在 73 个 `D` 删除条目；磁盘残留旧 agent 编排历史 | 确认无用 |
| `.agents/skills/` (260K) | 同上，gitignored 的 agent 技能遗留 | 确认无用 |
| `eval/eval/` 嵌套目录 | open_ragbench_data 数据位于 `eval/eval/open_ragbench_data/`，与 `eval/` 顶层脚本层级混乱 | 命名混乱 |
| `eval/run_gemma_55_benchmark.py` | 全仓库零引用（无 md / 其他 py 提及） | 【疑似】一次性评测残留 |
| `eval/run_spark_55_benchmark.py` | 全仓库零引用 | 【疑似】一次性评测残留 |
| `eval/run_weight_matrix_grid.py` | 全仓库零引用 | 【疑似】一次性评测残留 |
| `.agents/teamwork/explorer_m1_2/proposed_run_gemma_55_benchmark.py` | agent 草稿脚本，与 `eval/run_gemma_55_benchmark.py` 并存 | 【疑似】 |
| `.agents/teamwork/test_writer_1/TEST_INFRA.md` vs 根目录 `TEST_INFRA.md` | 同名不同内容两份 | 【疑似】 |
| `tests/test_adversarial_m2.py` (500+ 行) | Milestone-2 agent 团队对抗测试混入主 `tests/` | 【疑似】归属待定 |
| `.pytest_cache/`、各处 `__pycache__/` | gitignore 但磁盘残留的缓存目录 | 低风险 |
| `web/dist/` | 构建产物残留磁盘（gitignored） | 低风险 |
| `eval/results/` | 评测结果文件残留磁盘（gitignored） | 低风险 |
| `models/*/.cache/huggingface/**` | 模型下载的 lock / metadata 缓存文件（gitignored） | 低风险 |

---

## 2. 废弃代码块 / 死代码

### 2.1 确认死代码

- **`backend/worker/url_processor.py`**
  - `url_processing_queue` + `process_url_queue()` + `_legacy_safe_process()`：整个 deprecated 旧内存队列。模块内自述 "Deprecated: durable job dispatcher handles link jobs"，其他模块零引用（link 业务已走 `durable_jobs.py` / `url_processor_recursive.py`），仅保留排空 legacy put 的 warning 逻辑。
- **`backend/core/utils.py`** — 5 个函数在 backend + tests + eval 全部 0 引用：
  - `is_file_pdf`
  - `read_text_file_content`
  - `extract_text_from_pdf`
  - `chunk_pdf_content`
  - `chunk_non_pdf_content`
- **`backend/core/ocr_client.py:175 ocr_file()`** — 0 引用。
- **`backend/core/fts5_utils.py:236 delete_by_chunk_id()`** — 0 引用。

### 2.2 【疑似】死 API

- `backend/vector_store/lance_db.py:925 remove_visual_documents()` — 生产代码零引用，仅 `tests/test_l2_visual_retrieval.py` 调用。
- `backend/api/router.py:41 validate_token`、`:47 get_user_by_username` — 无引用。该文件整体为旧 auth-only router，与新 `routers/` 体系功能重复。

### 2.3 注释掉的代码块

- `backend/vector_store/chroma_db.py:192-201` — 大段注释掉的 mmr retriever 代码（含 `TODO: Add mmr search later`）。

---

## 3. 注释垃圾

| 位置 | 内容 |
|---|---|
| `backend/api/service.py:8` | `# import logging` 注释掉的导入 |
| `backend/worker/url_processor_recursive.py:15` | `# import logging` 注释掉的导入 |
| `backend/worker/url_processor_recursive.py:40` | `# recursive_url_processing_queue.task_done()` 注释掉的调用 |
| `backend/worker/url_processor_recursive.py:42` | 截断残留注释 `# P` |
| `backend/core/image_ingest.py:35-39` | 5 行散文式思维过程注释（"We bypass the dual OCR attempt ... if we wanted, or we just call ..."），表述与实际调用（直接调 `_gemini_caption`）混杂 |

> 低风险说明：`backend/core/auto_tagger.py:39-40` 的 `# tags: - foo - bar` 是正则示例注释，可接受；`inquisitive` 旧品牌字样出现在 config/paths/specs/README 中是有意的 legacy 回退兼容（均有文档说明），不计为问题。

---

## 4. 重复代码

| 重复项 | 位置 | 说明 |
|---|---|---|
| `get_base_url()` | `backend/worker/url_processor.py:22` 与 `backend/worker/url_processor_recursive.py:25` | 完全重复的 URL base 解析函数 |
| launcher 启动逻辑 | `start/launcher.py`（`start_backend` / `is_backend_ready` / `start_all`）vs `start/wenjv_launcher.py`（`pick_port` / `prepare` / `wait_health`） | 两套各自完整的进程启动/健康等待实现，互不包装 |
| 任务日志 md | 根目录 `findings.md` / `progress.md` / `task_plan.md` vs `.agent/` 同名文件 | 同一任务的两个版本 |
| `TEST_INFRA.md` | 根目录 vs `.agents/teamwork/test_writer_1/` | 同名不同内容 |

> 说明：`lance_db.py` / `chroma_db.py` / `milvus_db.py` 三个 adapter 的同名方法（`remove_documents` / `add_documents` / `search_documents` 等）是适配器模式的预期结构重复，不计为问题。

---

## 5. 无效导入（未使用 import）

> 扫描方式：AST 启发式（import 名在源码 Name 节点中未出现即标记）。字符串注解中的引用可能造成误报，**全部条目需人工复核**。

### backend/

| 文件 | 未使用导入 |
|---|---|
| `backend/parsers/text_parser.py:6` | `DocumentParser` 【疑似：`class TextParser` 并未继承它】 |
| `backend/parsers/pptx_parser.py:4` | `Tuple` |
| `backend/worker/durable_jobs.py:15` | `Any` |
| `backend/worker/durable_jobs.py:372` | 函数级导入的 `ASRError`（导入后从未提及） |
| `backend/vector_store/lance_db.py:2` | `Dict` |
| `backend/vector_store/lance_db.py:347` | `struct` |
| `backend/core/visual_embedder.py:15` | `json` |
| `backend/core/visual_embedder.py:17` | `Any`、`Union` |
| `backend/core/structure_chunker.py:9` | `Optional` |
| `backend/core/image_ingest.py:5` | `generate_caption`（实际调用的是 `_gemini_caption`） |
| `backend/core/multimodal.py:4` | `re` |
| `backend/core/multimodal.py:5` | `Optional` |
| `backend/api/routers/links.py:6` | `queue_link` |
| `backend/api/routers/links.py:8` | `vector_store` |
| `backend/api/routers/files.py:8` | `queue_document` |
| `backend/api/routers/files.py:10` | `vector_store` |
| `backend/api/services/jobs.py:5` | `Optional` |
| `backend/api/services/notes.py:17` | `tags_from_json` |

### start/

| 文件 | 未使用导入 |
|---|---|
| `start/launcher.py:7` | `signal` |

### tests/（约 20+ 处，抽查样例）

| 文件 | 未使用导入 |
|---|---|
| `tests/test_durable_jobs_ocr.py:2,6,7` | `asyncio`、`ProcessingStatus`、`JobStatus` |
| `tests/test_rag_refuse.py:2,3` | `asyncio`、`AsyncMock` |
| `tests/test_image_text_extract.py:2` | `MagicMock` |
| `tests/test_embedder_ocr_lance_fixes.py:4,5,8` | `json`、`call`、`pytest` |
| `tests/test_eval_pipeline.py:2,3` | `os`、`AsyncMock` |
| `tests/test_eval_matrix.py:4` | `MagicMock` |
| `tests/test_isolation_vector.py:1` | `pytest` |
| `tests/test_adversarial_m2.py:18` | `Note` |
| `tests/test_scoring.py:2` | `pytest` |
| `tests/test_ocr_client.py:4` | `OCRError` |
| `tests/test_image_isolation.py:7` | `ImageExtractionError` |
| `tests/test_benchmark_pipeline.py:26,30` | `tempfile`、`MagicMock`、`call` |

### eval/

| 文件 | 未使用导入 |
|---|---|
| `eval/run_e2e_verification.py:11,13` | `json`、`Dict`、`List`、`Any` |
| `eval/run_e2e_verification.py:107` | 函数内导入 `_process_chunks_with_mapping` |
| `eval/run_e2e_verification.py:239` | 函数内导入 `MicroBatchEmbedder` |
| `eval/run_gemma_55_benchmark.py:55` | `EXPECTED_CATEGORIES` |
| `eval/run_weight_matrix_grid.py:19` | `Optional`、`Tuple` |
| `eval/run_weight_matrix_grid.py:25` | `settings` |
| `eval/run_matrix.py:4` | `json` |
| `eval/run_mm_l2_l3_eval.py:17` | `Set` |
| `eval/run_mm_l2_l3_eval.py:23` | `fetch_documents`、`fetch_visual_documents` |

---

## 6. 遗留调试代码

- ✅ 未发现 `breakpoint()` / `pdb.set_trace()` / `debugger;`。

- ❌ **`backend/api/dependencies.py`** — fastapi-users 回调内 3 处裸 `print()` 走 stdout，绕过项目已有的 `backend/core/logging.py` 日志体系：
  - `:52` `print(f"User {user.id} has registered.")`
  - `:57` `print(... Reset token: {token})` ⚠️ **把 password reset token 打到标准输出**
  - `:62` `print(... Verification token: {token})` ⚠️ **把 verification token 打到标准输出**
- ❌ **`backend/api/service.py:38`** — `print(f"Token validation error: {e}")`，应走 logger。

---

## 7. 文件夹混乱

| 问题 | 位置 |
|---|---|
| 嵌套目录 | `eval/eval/`（数据放在二级 eval 下） |
| 过程文档与产品文档混放 | 根目录 7 份过程性 md（`findings.md` / `progress.md` / `task_plan.md` / `TEST_READY.md` / `TEST_INFRA.md` / `UPGRADE_ROADMAP.md`）与 `README.md` / `specs/` / `docs/` 混排 |
| 点目录职责重叠 | `.agent/`（当前工作区）与 `.agents/`（旧 agent 历史）并存，边界不清 |
| 测试命名混杂 | `tests/` 中 agent 里程碑风格命名（`test_adversarial_m2`、`test_l2_*`、`test_l3_*`）与常规业务测试混排 【疑似】缺少统一命名约定 |
| 启动入口分散 | 根目录 `start-wenjv.bat` / `stop-wenjv.bat` + `start/start.sh` + pyproject console scripts，三处入口 |
| 大体积非源码目录 | `models/` (1.5G，gitignored)、`web/` (83M，含 node_modules + dist) 残留磁盘 |

---

## 8. 命名杂乱 / 杂项遗留

| 位置 | 问题 | 状态 |
|---|---|---|
| `start/start.sh:7` | PATH 硬编码**另一个项目**的 venv：`/home/lanzao/antigravity/dazzling-bell/.venv/bin` | ⚠️ 确认：跨项目残留引用 |
| 根目录 `findings.md` | 正文引用同一旧项目 venv `dazzling-bell/.venv` | ⚠️ 跨项目残留引用 |
| `tests/test_image_query_t0.py:134` | 硬编码 `/home/lanzao/.config/wenjv/uploads/mm_assets/test/img-0.jpg` 绝对路径 | 【疑似】 |
| launcher 三名并存 | `launcher.py` / `wenjv_launcher.py` / `kb_launcher.py` | 【疑似】 |
| 同名不同内容 | 根目录 `findings.md` 等 vs `.agent/` 同名文件 | 【疑似】 |

> 说明：`inquisitive` 旧品牌字样（config.py / paths.py / main.py / specs / README 等）是有意的 legacy 回退兼容，README 与 specs 均有文档，不计为卫生问题。

---

## 附：git 工作树状态摘要

- `??`（未跟踪）：38 项，含 `backend/api/services/*.py`、`backend/core/*` 多组新文件、`eval/eval/`、`docs/wenjv_context_and_roadmap.md`、根目录 `TEST_*.md` 等
- `D`（已删除未提交）：73 项，主要为 `.agents/` 旧 agent 编排文件、`.hermes/plans/*`、`IDEA.md`
- `M`（修改未提交）：75 项，主要为后端 branding 迁移（inquisitive → wenjv）相关改动

> 提示：工作树存在大量未提交改动（branding 迁移），清理前建议先提交或归档现状，避免清理动作与未完成迁移混淆。

---

## 处理优先级建议（本轮未执行任何修改）

1. 🔴 **P0 — 安全相关**：`backend/api/dependencies.py` 中 print 泄露 reset/verify token
2. 🔴 **P0 — 环境相关**：`start/start.sh` 跨项目 venv 硬编码
3. 🟡 **P1 — 死代码**：`url_processor.py` deprecated 队列、`core/utils.py` 5 个 0 引用函数、`ocr_file()`、`delete_by_chunk_id()`
4. 🟡 **P1 — 无效导入**：按第 5 节清单批量清理（先跑 pytest 验证基线）
5. 🟡 **P1 — 注释掉的代码/导入**：第 3 节全部条目
6. 🟢 **P2 — 文件/目录治理**：`.agents/`、`eval/eval/`、根目录过程性 md、零引用 eval 脚本的删除或归档决策
7. 🟢 **P2 — 结构收敛**：launcher 双入口合一、`kb_launcher.py` shim 废弃、tests/ 命名约定统一
