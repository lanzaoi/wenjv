# wenjv（问据）

自托管个人知识库与多模态 RAG 系统：**文件 / 手写公式图片 / 网页链接 / 碎片笔记 / 结构化 Wiki** 统一管理，本地 ONNX 混合检索 + 视觉匹配 + 带溯源流式问答。

> **架构状态说明**：当前主力生产与开发版本位于 **[`wenjv-ts/`](./wenjv-ts/)**（TypeScript Hono 单端口服务端 + Vue 3 SPA + 本地 CPU OCR Sidecar）。根目录旧版 Python 后端（`backend/`、`web/`）保留作历史归档，不再作为默认运行入口。

---

## 核心特性

- **统一资料库（Schema v2）**：支持文档（`pdf` / `docx` / `pptx` / `md` / `txt` / `csv` / `json` / `html`）、图片（`png` / `jpg` / `jpeg`）、网页链接与 Markdown 笔记；后台持久化任务队列自动完成解析、切片、FTS5 全文同步与向量写入。
- **本地 CPU OCR 与物理公式识别**：独立 Python Sidecar（`8788`）集成 **PP-OCRv5 Mobile + Pix2Text**，支持 `auto` / `general` / `formula` 三种识别策略，手写数学/物理公式自动转为 LaTeX 并纳入检索。
- **多模态混合检索与重排**：本地 **ONNX Runtime** 推理运行 `BGE-M3`（文本向量）+ SQLite FTS5 `trigram` + `BGE-Reranker` + `SigLIP2`（以图搜图与图文匹配）。
- **流式问答与思考过程分离**：`/chat` 与 `/chat/by-image` 通过 SSE 输出溯源引用、深度思考流与最终回答；思考过程隐藏至 `/thinking/:id` 二级页面按需查看，主对话气泡保持清爽。
- **笔记收件箱 ↔ Wiki 知识图谱（方案 A + B）**：随手记先入收件箱，可在资料库详情弹窗或 Wiki 左侧「笔记收件箱」一键转正为树状 Wiki 页面（继承标签与附件），支持 `[[双链]]`、反向链接、版本回滚、关系图谱与 Copilot。
- **系统观测与迁移工具**：内置管理员观测面板（`/admin`）以及旧版 v1 数据探测/压缩包导入迁移能力。

---

## 快速开始（3 步运行）

详细配置、Docker 部署与开发调试见 **[`wenjv-ts/docs/USER_GUIDE.md`](./wenjv-ts/docs/USER_GUIDE.md)** 与 **[`wenjv-ts/docs/ARCHITECTURE.md`](./wenjv-ts/docs/ARCHITECTURE.md)**。

### 1. 安装依赖与准备配置

```bash
cd wenjv-ts
pnpm install --frozen-lockfile
pnpm run doctor

# 如需开启本地 OCR Sidecar（可选，推荐）
python3 -m venv sidecar/.venv
sidecar/.venv/bin/pip install ./sidecar

# 复制环境变量模板到持久化数据目录并填写 CHAT_API_KEY / JWT_SECRET
mkdir -p ~/.config/wenjv
cp .env.example ~/.config/wenjv/backend.env
```

### 2. 单端口生产模式启动

```bash
cd wenjv-ts
bash scripts/start-prod.sh
```

访问 `http://127.0.0.1:8787`（Node 服务端单端口同时托管前端 SPA 与 API，数据默认保存至 `~/.config/wenjv`）。

### 3. Docker Compose 启动（可选）

```bash
# 确保宿主机 ./models 含本地 ONNX 模型且 ~/.config/wenjv/backend.env 已就绪
docker compose up -d --build
```

---

## 目录导航

| 路径 | 说明 |
| :--- | :--- |
| [`wenjv-ts/`](./wenjv-ts/) | 主力 TypeScript 全栈系统（服务端、Vue 前端、OCR Sidecar、E2E 测试） |
| [`wenjv-ts/docs/ARCHITECTURE.md`](./wenjv-ts/docs/ARCHITECTURE.md) | Schema v2、接口总览与系统架构文档 |
| [`wenjv-ts/docs/USER_GUIDE.md`](./wenjv-ts/docs/USER_GUIDE.md) | 环境安装、环境变量、功能使用与验收手册 |
| [`models/`](./models/) | 本地 ONNX 模型目录（`bge_m3_onnx`、`bge_reranker_base`、`siglip2_onnx`） |
| [`Dockerfile`](./Dockerfile) / [`docker-compose.yml`](./docker-compose.yml) | 适配 `wenjv-server` (`8787`) 与 `wenjv-sidecar` (`8788`) 的容器编排 |
| [`backend/`](./backend/) / [`web/`](./web/) | 旧版 Python FastAPI + Vue 原型（历史归档） |

---

## 验收与测试

```bash
cd wenjv-ts
pnpm run verify       # 快速门禁：no-stubs + 全仓 typecheck + Vitest 单测
pnpm run verify:all   # 全量验收：含前端构建、OCR Sidecar 实测与 Playwright E2E
```
