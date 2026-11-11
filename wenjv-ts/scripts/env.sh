#!/usr/bin/env bash
# 统一工具链环境。所有脚本都 source 这个文件，保证无论从哪种 shell 启动，
# 用的都是同一份 Node / pnpm，并且不会混入 Windows 的 PATH（/mnt/c/...）。
#
# 用法：source scripts/env.sh

WENJV_NODE_HOME="${WENJV_NODE_HOME:-$HOME/.local/node-v22.23.4-linux-x64}"

# 去掉 PATH 中所有 /mnt/<盘符> 条目和 nvm 的 node（避免两份 Node 混用）
_clean_path=""
IFS=':' read -r -a _parts <<< "${PATH:-}"
for _p in "${_parts[@]}"; do
  case "$_p" in
    /mnt/[a-z]/*|"$HOME"/.nvm/*|"") continue ;;
  esac
  case ":$_clean_path:" in
    *":$_p:"*) ;;
    *) _clean_path="${_clean_path:+$_clean_path:}$_p" ;;
  esac
done

# 确保标准 Linux 工具目录存在于 PATH 中
for _sysdir in /usr/local/bin /usr/bin /bin /usr/local/sbin /usr/sbin /sbin; do
  if [[ -d "$_sysdir" ]]; then
    case ":$_clean_path:" in
      *":$_sysdir:"*) ;;
      *) _clean_path="${_clean_path:+$_clean_path:}$_sysdir" ;;
    esac
  fi
done

export PATH="$WENJV_NODE_HOME/bin:$_clean_path"
unset _clean_path _parts _p _sysdir

export COREPACK_NPM_REGISTRY="https://registry.npmmirror.com"
export COREPACK_ENABLE_DOWNLOAD_PROMPT=0
