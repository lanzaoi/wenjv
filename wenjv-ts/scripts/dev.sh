#!/usr/bin/env bash
# 一键启动 TypeScript 后端 (8787) 与 Vue 前端 (5173)。
# 前端 Vite 自动将 /api 代理转发至后端 8787 端口。
set -uo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
source "$ROOT/scripts/env.sh"

export WENJV_BASE_DIR="${WENJV_BASE_DIR:-$ROOT/.data}"
mkdir -p "$WENJV_BASE_DIR"
if [[ ! -f "$WENJV_BASE_DIR/backend.env" && -f "$HOME/.config/wenjv/backend.env" ]]; then
  cp "$HOME/.config/wenjv/backend.env" "$WENJV_BASE_DIR/backend.env"
fi

echo "============================================="
echo "  问据 wenjv (TypeScript) 开发环境启动中..."
echo "  数据目录: $WENJV_BASE_DIR"
echo "  后端: http://127.0.0.1:8787"
echo "  前端: http://127.0.0.1:5173"
echo "============================================="

# 清理子进程
pids=()
cleanup() {
  echo
  echo "正在停止开发服务..."
  for pid in "${pids[@]}"; do
    if kill -0 "$pid" 2>/dev/null; then
      kill "$pid" 2>/dev/null || true
    fi
  done
  wait 2>/dev/null || true
  echo "开发服务已全部退出。"
  exit 0
}
trap cleanup SIGINT SIGTERM EXIT

# 启动本地 CPU OCR Sidecar (8788，可选)
if [[ "${OCR_ENABLED:-true}" != "false" && -x "$ROOT/sidecar/.venv/bin/python" ]]; then
  echo "  OCR:  http://127.0.0.1:${OCR_PORT:-8788} (PP-OCRv5 Mobile + Pix2Text)"
  (
    cd "$ROOT/sidecar"
    exec "$ROOT/sidecar/.venv/bin/python" ocr_server.py
  ) &
  pids+=($!)
fi

# 启动 TS 后端
(
  cd "$ROOT/packages/server"
  exec pnpm dev
) &
pids+=($!)

# 启动 Vue 前端
(
  cd "$ROOT/packages/web"
  exec pnpm dev
) &
pids+=($!)

# 等待子进程
wait
