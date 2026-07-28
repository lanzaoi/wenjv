# Vue SPA (personal knowledge base frontend)

Apple-light Vue 3 + Vite + Vue Router + Pinia.

## Dev

Backend must be running (default `http://127.0.0.1:8000`).

```bash
cd web
npm install
npm run dev
```

Open `http://127.0.0.1:5173`. API calls go to `/api/*` and Vite proxies to the backend
(`VITE_PROXY_TARGET`, default `http://127.0.0.1:8000`).

Or use repo root `start-kb.bat` (starts FastAPI + this Vite app).

## Build

```bash
npm run build
npm run preview
```

Production API base: set `VITE_API_URL=https://your-api` at build time (no `/api` prefix rewrite).

## Features wired

| UI | API |
|----|-----|
| Login / Register | `POST /auth/jwt/login`, `POST /auth/register` |
| Upload file/image | `POST /file/upload` |
| Note | `POST /file/note` |
| Link | `POST /links/submit` |
| Text chat SSE | `POST /chat` |
| T0 image search | `POST /documents/search/by-image` |
| T0 image chat | `POST /chat/by-image` |
| Library lists | `GET /file/`, `/file/note`, `/links/` |

Streamlit has been **removed**. Use Vue under `web/`.
