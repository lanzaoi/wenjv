# Vue SPA (wenjv 知识库前端)

wenjv 前端采用 Vue 3 + Vite + Vue Router + Pinia 构建，为自托管知识库提供轻量级响应式交互界面。

## 开发环境启动

启动前端开发服务前，需确保后端 API 服务已正常运行（默认地址 `http://127.0.0.1:8000`）。

```bash
cd web
npm install
npm run dev
```

在浏览器中打开 `http://127.0.0.1:5173`。前端 API 请求统一路由至 `/api/*`，由 Vite 开发服务器反向代理至后端服务（通过 `VITE_PROXY_TARGET` 配置，默认指向 `http://127.0.0.1:8000`）。

Windows 环境也可直接运行项目根目录下的 `start-wenjv.bat` 脚本（一键启动 FastAPI 后端与 Vite 前端）。

## 生产构建

```bash
npm run build
npm run preview
```

生产环境 API 地址配置：在构建阶段设置 `VITE_API_URL=https://your-api`，静态资源将直接请求指定的目标后端。

## 核心接口映射

| 前端模块 | 对应后端 API |
|----------|--------------|
| 用户注册与登录认证 | `POST /auth/jwt/login`, `POST /auth/register` |
| 文件与图片上传 | `POST /file/upload` |
| 笔记创建与编辑 | `POST /file/note` |
| 网页链接提交与抓取 | `POST /links/submit` |
| 知识库流式问答 | `POST /chat` (SSE) |
| 图片语义检索 | `POST /documents/search/by-image` |
| 基于图片的问答 | `POST /chat/by-image` |
| 知识库资源列表 | `GET /file/`, `GET /file/note`, `GET /links/` |
