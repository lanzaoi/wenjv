# 问据（Wenjv）使用与运维指南

---

## 一、环境要求

- **Node.js**：`>=22.12 <23`（仓库根目录包含 `wenjv-ts/.nvmrc`）
- **pnpm**：`10.34.9`（见 `wenjv-ts/package.json` `packageManager`）
- **Python Sidecar（可选，推荐开启以支持图片/扫描 PDF OCR 与公式识别）**：Python `>=3.12`
- **本地 ONNX 模型目录**（默认读取上级目录 `../models` 或 `MODELS_DIR`）：
  - `bge_m3_onnx`（文本向量）
  - `bge_reranker_base`（文本重排）
  - `siglip2_onnx`（以图搜图 / 图文匹配）

---

## 二、快速启动

### 1. 初始化依赖与环境体检

```bash
cd wenjv-ts
pnpm install --frozen-lockfile
pnpm run doctor
```

`doctor.sh` 会自动检查 Node/pnpm 路径、原生依赖（`better-sqlite3`、`sharp`、`onnxruntime-node`、`@lancedb/lancedb`、`@node-rs/argon2`）是否编译就绪。

如需启用本地 OCR Sidecar（`8788`）：

```bash
cd wenjv-ts/sidecar
python3 -m venv .venv
.venv/bin/pip install .
```

### 2. 配置环境变量

服务默认读取 `$WENJV_BASE_DIR/backend.env`（默认 `~/.config/wenjv/backend.env`），模板见 `wenjv-ts/.env.example`。至少配置好对话模型密钥与 JWT 密钥：

```dotenv
JWT_SECRET=请替换为随机32位以上密钥
CHAT_PROVIDER=openai
CHAT_API_BASE=https://maas-api.cn-huabei-1.xf-yun.com/v2
CHAT_MODEL=spark-x2.6
CHAT_API_KEY=你的API_KEY
```

### 3. 启动服务

- **生产单端口模式（推荐日常使用）**：

```bash
cd wenjv-ts
bash scripts/start-prod.sh          # 若 dist 不存在会自动构建前端
bash scripts/start-prod.sh --build  # 强制重新打包前端后启动
```

启动后浏览器访问 `http://127.0.0.1:8787`（前端与 API 共用 `8787` 端口，数据默认持久化在 `~/.config/wenjv`）。

- **开发热更新模式**（后端 `8787` + Vite 前端 `5173` + Sidecar `8788`，数据默认写入 `wenjv-ts/.data`）：

```bash
cd wenjv-ts
bash scripts/dev.sh
```

---

## 三、核心功能使用说明

### 1. 图片 / 手写笔记 OCR 与公式识别

- 上传图片或扫描 PDF 时，`OCR_IMAGE_MODE` 控制本地 CPU Sidecar 解析策略：
  - `auto`（默认）：由 PP-OCRv5 Mobile 先行高速提取文字，若检测到数学公式符号或换行公式密度较高，自动联动 Pix2Text 补充 LaTeX 公式；
  - `general`：仅用 PP-OCRv5 Mobile 提取通用文本；
  - `formula`：强制走公式版面与 LaTeX 识别链路。
- 已入库资源可在**资料库 → 点击条目详情 → 「公式 OCR 重索引」或「重新索引」**重新入队处理。

### 2. 对话与深度思考二级页

- 在对话页支持三种模式：**综合解答**（混合检索 + 生成）、**自由对话**（纯模型问答）、**仅引用**（只返回检索匹配片段与来源，不调用生成模型）。
- 若上游模型开启深度推理，推理过程不会堆在对话气泡中，气泡底部会显示 **「思考过程 (N 字)」**（流式生成时为「查看实时思考」），点击可进入 `/thinking/:id` 二级页面查看、复制并随时一键返回主对话。

### 3. 笔记收集箱 ↔ Wiki 知识树（方案 A + B）

- **快速收集**：右侧栏「笔记」Tab 提交的随手记默认进入 `resources (type='note')` 并自动切块入库。
- **Wiki 内整理转正**：进入 **Wiki → 左侧目录底部「笔记收件箱」**，点击任意待整理笔记即可在工作台预览正文与标签、选择目标父目录，点击 **「一键转正为 Wiki 页面」** 直接落盘目录树（默认同时移出原收件箱条目，避免检索重复；可取消勾选保留副本）。
- **资料库升级**：在 **资料库** 打开任意笔记详情弹窗，同样可点击左下角 **「升级为 Wiki」**。

### 4. 系统管理与旧版 v1 数据迁移

- **管理端 `/admin`**：需 `is_superuser = 1` 的管理员账号访问。可查看 Sidecar / SigLIP2 / 数据库与向量库运行状态、近期检索耗时与命中日志，也可通过运维脚本一键清零统计计数。
- **旧版 v1 数据导入**：在资料库右上角点击 **「批量导入」→「旧版数据导入」**，支持自动探测本机 `~/.config/wenjv/wenjv.db` 旧版库或上传 v1 数据包并安全重建 Schema v2 索引与 Wiki。

---

## 四、常用环境变量参考

以下配置项均定义于 `wenjv-ts/packages/server/src/config.ts`：

| 变量名 | 默认值 | 说明 |
| :--- | :--- | :--- |
| `HOST` / `PORT` | `0.0.0.0` / `8787` | HTTP 监听地址与端口 |
| `WENJV_BASE_DIR` | `~/.config/wenjv` | 数据根目录（`wenjv.db`、`lance_db/`、`uploads/`、`wiki_vault/`） |
| `MODELS_DIR` | `../models` | 本地 ONNX 模型目录 |
| `JWT_SECRET` / `SECRET_KEY` | — | JWT 签名密钥（二者兼容，优先读取 `JWT_SECRET`） |
| `EMBEDDING_PROVIDER` | `local` | `local` 使用本地 `bge_m3_onnx`；可改为远端 OpenAI 兼容服务 |
| `RERANK_ENABLED` / `RERANK_PROVIDER` | `true` / `local_onnx` | 是否启用本地 `bge_reranker_base` 重排 |
| `OCR_ENABLED` / `OCR_SIDECAR_URL` | `true` / `http://127.0.0.1:8788` | 是否启用本地 OCR Sidecar |
| `OCR_IMAGE_MODE` | `auto` | `auto` / `general` / `formula` |
| `OCR_MIN_CHARS` | `40` | PDF 内嵌文本少于该字数时自动回退 Sidecar 页面 OCR |

---

## 五、全量验收命令

修改代码后建议执行全套端到端验收：

```bash
cd wenjv-ts
pnpm run verify:all
```

将依次执行：`no-stubs` 占位检查 → 全仓 `tsc`/`vue-tsc` 类型检查 → `@wenjv/web` 构建 → 后端 Vitest 集成/单测 → Python Sidecar 实图/PDF OCR 测试 → Playwright 浏览器全流程 E2E 测试。
