#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
source "$ROOT/scripts/env.sh"

cd "$ROOT"
echo "=== [1/6] no-stubs 检查 ==="
pnpm run no-stubs

echo "=== [2/6] 全仓 TypeScript 类型检查 ==="
pnpm run typecheck

echo "=== [3/6] 前端生产构建 (vite build) ==="
pnpm --filter @wenjv/web build

echo "=== [4/6] 后端 Vitest 集成/单元测试 ==="
pnpm --filter @wenjv/server test

echo "=== [5/6] Python OCR Sidecar 单测 ==="
if [[ -x "$ROOT/sidecar/.venv/bin/python" ]]; then
  (cd "$ROOT/sidecar" && "$ROOT/sidecar/.venv/bin/python" -m unittest test_ocr_server.py)
else
  (cd "$ROOT/sidecar" && python3 -m unittest test_ocr_server.py)
fi

echo "=== [6/6] Playwright 端到端浏览器验收 ==="
pnpm run test:e2e

echo "=== verify:all 全部通过 ==="
