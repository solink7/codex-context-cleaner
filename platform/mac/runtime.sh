#!/bin/zsh
# [INPUT]: 下载清单、PATH/环境索引、curl 与状态显示函数。
# [OUTPUT]: 限时探测后的 PYTHON_BIN；缺少环境时互斥安装专用 Python。
# [POS]: Mac 环境引导层；不修改系统 Python、PATH 或客户端配置。
# [PROTOCOL]: 变更时更新此头部，然后检查 CLAUDE.md

# ---- 环境探测 ----
probe_python() {
 local executable="$1" worker='' began=$SECONDS result
 [[ -f "$executable" && -x "$executable" ]] || return 1
 zmodload zsh/zselect || return 1
 {
  "$executable" -I -c 'import sys, ssl, http.client, urllib.request, json, pathlib; ssl.create_default_context(); sys.exit(1) if sys.version_info < (3,9) else print(sys.executable)' 2>/dev/null &
  worker=$!
  while kill -0 "$worker" 2>/dev/null; do
   (( SECONDS - began < 5 )) || return 1
   zselect -t 5
  done
  wait "$worker"
  result=$?
  worker=''
  return "$result"
 } always {
  if [[ -n "$worker" ]]; then
   kill -KILL "$worker" 2>/dev/null
   wait "$worker" 2>/dev/null
  fi
 }
}

python_candidates() {
 local group="${1:-common}" user_root="${2:-$HOME}" directory executable prefix
 local -a candidates
 if [[ "$group" == common ]]; then
  candidates=(/opt/homebrew/bin/python3 /usr/local/bin/python3
   /Library/Frameworks/Python.framework/Versions/Current/bin/python3)
  # 未安装开发工具时，不执行会弹出安装提示的系统入口。
  if /usr/bin/xcode-select -p >/dev/null 2>&1; then candidates+=(/usr/bin/python3); fi
 else
  for directory in "${path[@]}"; do
   [[ "$directory" == /* && "$directory" != /usr/bin ]] || continue
   candidates+=("$directory/python3" "$directory/python" "$directory"/python3.<->(N))
  done
  candidates+=(/Library/Frameworks/Python.framework/Versions/*/bin/python3(N)
   "$user_root"/{miniforge3,miniconda3,anaconda3}/bin/python3(N)
   "$user_root/.local/bin"/python3(N) "$user_root/.local/bin"/python3.<->(N)
   "${UV_PYTHON_INSTALL_DIR:-$user_root/.local/share/uv/python}"/cpython-*-macos-*/bin/python3(N))
  for prefix in "${VIRTUAL_ENV:-}" "${CONDA_PREFIX:-}"; do
   [[ "$prefix" == /* ]] && candidates+=("$prefix/bin/python3")
  done
  if [[ -r "$user_root/.conda/environments.txt" ]]; then
   while IFS= read -r prefix || [[ -n "$prefix" ]]; do
    [[ "$prefix" == /* ]] && candidates+=("$prefix/bin/python3")
   done < "$user_root/.conda/environments.txt"
  fi
 fi
 for executable in "${(@u)candidates}"; do
  [[ -f "$executable" && -x "$executable" ]] && print -r -- "$executable"
 done
 return 0
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
runtime_http_request() {
 # 后台 PID 直接对应 curl，取消时不会留下孤立下载进程。
 exec /usr/bin/curl --disable --fail --location --silent --show-error --proto '=https' --proto-redir '=https' "$@"
}

check_runtime_download() {
 local url="$1" headers="$2" result
 show_progress $'未找到可用的 Python，正在检查下载连接…\n连接检查最多等待 20 秒。'
 (runtime_http_request --head --connect-timeout 8 --max-time 20 --dump-header "$headers" \
  --output /dev/null "$url") 2>"$headers.error"
 result=$?
 if (( result != 0 )); then
  RUNTIME_ERROR='无法连接 Python 下载地址，未开始下载。请检查网络能否访问 GitHub 后重试。'
  (( result != 22 )) || RUNTIME_ERROR='Python 下载地址不可用，未开始下载。请更新工具或检查网络后重试。'
  (( result != 23 )) || RUNTIME_ERROR='无法写入下载状态文件。请检查磁盘空间和目录权限。'
  return 1
 fi
 RUNTIME_DOWNLOAD_SIZE=$(/usr/bin/awk '
  /^HTTP\// { size=0 }
  tolower($1)=="content-length:" { size=$2+0 }
  END { printf "%.0f", size }
 ' "$headers")
}

download_progress() {
 local received="$1" total="$2" elapsed="$3"
 show_progress "$(/usr/bin/awk -v received="$received" -v total="$total" -v elapsed="$elapsed" 'BEGIN {
  rate=elapsed>0 ? received/elapsed : 0;
  if (total>0) printf "正在下载 Python：%.1f / %.1f MB（%.0f%%）\n", received/1048576, total/1048576, received*100/total;
  else printf "正在下载 Python：已下载 %.1f MB\n", received/1048576;
  if (rate>0) printf "速度 %.0f KB/s", rate/1024;
  else printf "正在等待数据";
  if (total>received && rate>0) {
   remaining=int((total-received)/rate+.5);
   if (remaining>=60) printf "，预计还需 %d 分 %d 秒", remaining/60, remaining%60;
   else printf "，预计还需 %d 秒", remaining;
  } else if (total>0 && received>=total) printf "，即将完成";
  else printf "，剩余时间待测速";
 }')"
}

download_runtime() {
 local url="$1" archive="$2" headers="${2}.headers" worker='' result received
 local began=$SECONDS elapsed
 {
  check_runtime_download "$url" "$headers" || return 1
  # 下载允许慢速前进；连续 20 秒没有数据时退出，不反复从零重试。
  runtime_http_request --connect-timeout 8 --max-time 1800 --speed-time 20 --speed-limit 1 \
   --output "$archive" "$url" 2>"$headers.error" &
  worker=$!
  began=$SECONDS
  while kill -0 "$worker" 2>/dev/null; do
   received=0
   [[ ! -f "$archive" ]] || received=$(/usr/bin/stat -f %z "$archive")
   elapsed=$(( SECONDS - began ))
   download_progress "$received" "$RUNTIME_DOWNLOAD_SIZE" "$elapsed"
   sleep 1
  done
  wait "$worker"
  result=$?
  worker=''
  if (( result != 0 )); then
   RUNTIME_ERROR='Python 下载中断。连接失败或连续 20 秒未收到数据，请检查网络后重试。'
   (( result != 28 )) || RUNTIME_ERROR='Python 下载超时。连续 20 秒未收到数据或下载超过 30 分钟，请检查网络后重试。'
   (( result != 23 )) || RUNTIME_ERROR='无法写入 Python 下载文件。请检查磁盘空间和目录权限。'
   return 1
  fi
 } always {
  if [[ -n "$worker" ]]; then
   kill "$worker" 2>/dev/null
   wait "$worker" 2>/dev/null
  fi
  rm -f "$headers" "$headers.error"
 }
}

install_python() {
 local manifest="$1" runtime_root="$2" platform_key="$3" stage='' archive actual_digest
 select_runtime "$manifest" "$platform_key" || { RUNTIME_ERROR='没有适用于这台 Mac 的运行环境。请查看 README.html 中的系统要求。'; return 1; }
 mkdir -p "$runtime_root" || { RUNTIME_ERROR='无法创建运行环境目录，请检查当前用户的文件权限。'; return 1; }
 /usr/bin/shlock -f "$runtime_root/install.lock" -p $$ || {
  RUNTIME_ERROR='另一个启动或设置窗口正在安装运行环境，请等待完成后重试。'
  return 1
 }
 {
  # 获取锁前另一个入口已完成安装时，直接复用。
  if PYTHON_BIN=$(probe_python "$runtime_root/python/bin/python3"); then return 0; fi
  stage=$(mktemp -d "$runtime_root/.install.XXXXXX") || return 1
  archive="$stage/python.tar.gz"
  RUNTIME_ERROR='运行环境下载失败。请检查网络能否访问 GitHub，再双击启动。'
  download_runtime "$RUNTIME_URL" "$archive" || return 1
  show_progress '下载完成，正在校验文件…'
  actual_digest=$(/usr/bin/shasum -a 256 "$archive")
  actual_digest="${actual_digest%% *}"
  [[ "$actual_digest" == "$RUNTIME_SHA256" ]] || { RUNTIME_ERROR='下载文件校验失败，已取消安装。请检查网络后重新启动。'; return 1; }
  show_progress '校验通过，正在安装专用运行环境…'
  /usr/bin/tar -xzf "$archive" --no-same-owner -C "$stage" || { RUNTIME_ERROR='运行环境解压失败。请检查剩余磁盘空间后重试。'; return 1; }
  probe_python "$stage/python/bin/python3" >/dev/null || { RUNTIME_ERROR='新运行环境未通过检查。这台 Mac 的系统版本或芯片不受支持。'; return 1; }
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
  [[ -z "$stage" ]] || rm -rf "$stage"
  rm -f "$runtime_root/install.lock"
 }
}

ensure_python() {
 local manifest="$1" runtime_root="$2" platform_key="$3" executable group resolved
 local -a candidates
 local -A checked
 shift 3
 RUNTIME_ERROR='运行环境准备失败。请查看 launcher.log 中的原因。'
 show_progress '正在检查本机运行环境…'
 # 专用环境可离线复用；已有的外部环境也必须能导入代理所需标准库。
 candidates=("$runtime_root/python/bin/python3" "$@")
 for group in private common fallback; do
  [[ "$group" == private ]] || candidates=("${(@f)$(python_candidates "$group")}")
  for executable in "${candidates[@]}"; do
   [[ -f "$executable" && -x "$executable" ]] || continue
   resolved="${executable:A}"
   [[ -z "${checked[$resolved]}" ]] || continue
   checked[$resolved]=1
   if PYTHON_BIN=$(probe_python "$executable"); then
    print -r -- "已选择 Python：$PYTHON_BIN"
    return 0
   fi
  done
 done
 install_python "$manifest" "$runtime_root" "$platform_key"
}
