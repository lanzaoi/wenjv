#!/usr/bin/env bash
# 禁止空壳代码：业务源码里不允许出现占位标记。
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
pattern='TODO|FIXME|XXX|\bstub\b|\bmock\b|not implemented|NotImplemented|placeholder'
# 过滤掉 HTML 输入框属性 placeholder="..." 和 CSS ::placeholder 伪类
hits="$(grep -rnEi "$pattern" "$ROOT"/packages/*/src 2>/dev/null | grep -vEi 'placeholder="|placeholder=|::placeholder' || true)"
if [[ -n "$hits" ]]; then
  echo "no-stubs: 发现占位代码："
  echo "$hits"
  exit 1
fi
echo "no-stubs: 通过（packages/*/src 无占位标记）"
