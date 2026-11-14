#!/usr/bin/env bash
# S11 单端口生产模式启动脚本：
# - 默认数据目录：$WENJV_BASE_DIR（未设置时使用 $HOME/.config/wenjv，保留原有 backend.env 与密钥）
# - 自动构建前端（若 dist 不存在或传入 --build）
# - 启动本地 CPU OCR Sidecar (8788) 与单端口 Hono 全栈服务 (8787)
set -uo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
source "$ROOT/scripts/env.sh"

export NODE_ENV="production"
export WENJV_BASE_DIR="${WENJV_BASE_DIR:-$HOME/.config/wenjv}"
export HOST="${HOST:-0.0.0.0}"
export PORT="${PORT:-8787}"
mkdir -p "$WENJV_BASE_DIR"

if [[ "${1:-}" == "--build" || ! -f "$ROOT/packages/web/dist/index.html" ]]; then
  echo "正在构建 @wenjv/web 前端静态资源..."
  (cd "$ROOT" && pnpm --filter @wenjv/web build) || exit 1
fi

echo "============================================="
echo "  问据 wenjv 生产服务启动 (单端口模式)"
echo "  数据目录: $WENJV_BASE_DIR"
echo "  访问地址: http://127.0.0.1:$PORT"
echo "============================================="

pids=()
cleanup() {
  echo
  echo "正在停止生产服务..."
  for pid in "${pids[@]}"; do
    if kill -0 "$pid" 2>/dev/null; then
      kill "$pid" 2>/dev/null || true
    fi
  done
  wait 2>/dev/null || true
  echo "生产服务已退出。"
  exit 0
}
trap cleanup SIGINT SIGTERM EXIT

if [[ "${OCR_ENABLED:-true}" != "false" && -x "$ROOT/sidecar/.venv/bin/python" ]]; then
  echo "  OCR Sidecar: http://127.0.0.1:${OCR_PORT:-8788}"
  (
    cd "$ROOT/sidecar"
    exec "$ROOT/sidecar/.venv/bin/python" ocr_server.py
  ) &
  pids+=($!)
fi

(
  cd "$ROOT/packages/server"
  exec pnpm start
) &
pids+=($!)

wait
