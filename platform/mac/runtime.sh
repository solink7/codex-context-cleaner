#!/bin/zsh
# [INPUT]: 固定版本下载清单、候选 Python 路径与状态显示函数。
# [OUTPUT]: 可用的 PYTHON_BIN；缺少环境时安装用户目录中的专用 Python。
# [POS]: Mac 环境引导层；不修改系统 Python、PATH 或客户端配置。
# [PROTOCOL]: 变更时更新此头部，然后检查 CLAUDE.md

# ---- 环境探测 ----
probe_python() {
 local executable="$1"
 [[ -x "$executable" ]] || return 1
 "$executable" -I -c 'import sys, ssl, http.client, urllib.request, json, pathlib; ssl.create_default_context(); sys.exit(1) if sys.version_info < (3,11) else print(sys.executable)' 2>/dev/null
}

select_runtime() {
 local manifest="$1" platform_key="$2" entry_key version url digest
 while IFS=$'\t' read -r entry_key version url digest; do
  if [[ "$entry_key" == "$platform_key" ]]; then
   [[ "$url" == https://github.com/astral-sh/python-build-standalone/releases/download/* && ${#digest} == 64 && "$digest" != *[^0-9a-f]* ]] || return 1
   RUNTIME_URL="$url"
   RUNTIME_SHA256="$digest"
   return 0
  fi
 done < "$manifest"
 return 1
}

# ---- 下载与安装 ----
download_runtime() {
 /usr/bin/curl --fail --location --proto '=https' --proto-redir '=https' \
  --connect-timeout 15 --max-time 300 --retry 2 --retry-delay 1 --output "$2" "$1"
}

install_python() {
 local manifest="$1" runtime_root="$2" platform_key="$3" stage archive actual_digest candidate
 select_runtime "$manifest" "$platform_key" || { RUNTIME_ERROR='没有适用于这台 Mac 的运行环境。请查看 README.html 中的系统要求。'; return 1; }
 mkdir -p "$runtime_root" || { RUNTIME_ERROR='无法创建运行环境目录，请检查当前用户的文件权限。'; return 1; }
 stage=$(mktemp -d "$runtime_root/.install.XXXXXX") || return 1
 archive="$stage/python.tar.gz"
 {
  show_progress '未找到可用的 Python。正在下载专用运行环境…首次启动需要联网，请耐心等待。'
  download_runtime "$RUNTIME_URL" "$archive" || { RUNTIME_ERROR='运行环境下载失败。请检查网络能否访问 GitHub，再双击启动。'; return 1; }
  show_progress '下载完成，正在校验文件…'
  actual_digest=$(/usr/bin/shasum -a 256 "$archive")
  actual_digest="${actual_digest%% *}"
  [[ "$actual_digest" == "$RUNTIME_SHA256" ]] || { RUNTIME_ERROR='下载文件校验失败，已取消安装。请检查网络后重新启动。'; return 1; }
  show_progress '校验通过，正在安装专用运行环境…'
  /usr/bin/tar -xzf "$archive" --no-same-owner -C "$stage" || { RUNTIME_ERROR='运行环境解压失败。请检查剩余磁盘空间后重试。'; return 1; }
  candidate=$(probe_python "$stage/python/bin/python3") || { RUNTIME_ERROR='新运行环境未通过检查。这台 Mac 的系统版本或芯片不受支持。'; return 1; }
  if [[ -e "$runtime_root/python" ]]; then
   mv "$runtime_root/python" "$stage/previous-python" || return 1
  fi
  if ! mv "$stage/python" "$runtime_root/python"; then
   [[ ! -d "$stage/previous-python" ]] || mv "$stage/previous-python" "$runtime_root/python"
   RUNTIME_ERROR='无法写入运行环境目录，请检查文件权限。'
   return 1
  fi
  PYTHON_BIN=$(probe_python "$runtime_root/python/bin/python3") || {
   rm -rf "$runtime_root/python"
   [[ ! -d "$stage/previous-python" ]] || mv "$stage/previous-python" "$runtime_root/python"
   RUNTIME_ERROR='安装后的运行环境未通过检查，已撤回本次安装。'
   return 1
  }
 } always {
  rm -rf "$stage"
 }
}

ensure_python() {
 local manifest="$1" runtime_root="$2" platform_key="$3" executable
 shift 3
 RUNTIME_ERROR='运行环境准备失败。请查看 launcher.log 中的原因。'
 show_progress '正在检查本机运行环境…'
 # 专用环境可离线复用；已有的外部环境也必须能导入代理所需标准库。
 for executable in "$runtime_root/python/bin/python3" "$@"; do
  if PYTHON_BIN=$(probe_python "$executable"); then return 0; fi
 done
 install_python "$manifest" "$runtime_root" "$platform_key"
}
