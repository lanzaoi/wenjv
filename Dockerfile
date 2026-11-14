# syntax=docker/dockerfile:1

# ==============================================================================
# Target 1: wenjv-server (TypeScript Hono API + Vue 3 SPA single-port runtime)
# ==============================================================================
FROM node:22-slim AS server

WORKDIR /app/wenjv-ts

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    curl \
    tini \
    && rm -rf /var/lib/apt/lists/*

RUN corepack enable && corepack prepare pnpm@10.34.9 --activate

COPY wenjv-ts/package.json wenjv-ts/pnpm-lock.yaml wenjv-ts/pnpm-workspace.yaml wenjv-ts/tsconfig.base.json ./
COPY wenjv-ts/packages ./packages
COPY wenjv-ts/tools ./tools

RUN pnpm install --frozen-lockfile && pnpm --filter @wenjv/web build

RUN mkdir -p /data/wenjv /app/models && chown -R node:node /app /data/wenjv

USER node

ENV NODE_ENV=production \
    HOST=0.0.0.0 \
    PORT=8787 \
    WENJV_BASE_DIR=/data/wenjv \
    MODELS_DIR=/app/models

EXPOSE 8787

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD curl -fsS http://127.0.0.1:8787/health || exit 1

ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["pnpm", "--filter", "@wenjv/server", "start"]

# ==============================================================================
# Target 2: wenjv-sidecar (Local CPU OCR Sidecar: PP-OCRv5 Mobile + Pix2Text)
# ==============================================================================
FROM python:3.12-slim AS sidecar

WORKDIR /app/sidecar

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    libgl1 \
    libglib2.0-0 \
    libgomp1 \
    tini \
    && rm -rf /var/lib/apt/lists/*

COPY wenjv-ts/sidecar/pyproject.toml wenjv-ts/sidecar/ocr_server.py ./

RUN pip install --no-cache-dir . && \
    useradd -m -u 1000 appuser && \
    chown -R appuser:appuser /app /home/appuser

USER appuser

ENV OCR_HOST=0.0.0.0 \
    OCR_PORT=8788 \
    TOKENIZERS_PARALLELISM=false

EXPOSE 8788

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD curl -fsS http://127.0.0.1:8788/health || exit 1

ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["python", "ocr_server.py"]
