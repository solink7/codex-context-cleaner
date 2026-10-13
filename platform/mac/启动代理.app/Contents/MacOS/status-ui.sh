#!/bin/zsh
# [INPUT]: progress.js、后台目录与 UTF-8 状态；CI 可显式启用无窗口模式。
# [OUTPUT]: 唯一进度/结果窗口；成功自动关闭，失败在原窗口等待关闭。
# [POS]: Mac 共用提示层，tools/release.py 将本文件同步到停止应用。
# [PROTOCOL]: 变更时更新此头部，然后检查 CLAUDE.md

# ---- 状态写入与窗口生命周期 ----
UI_PID=''
STATUS_FILE=''
UI_SCRIPT="$APP_CONTENTS/MacOS/progress.js"
UI_ACTIVATE="$SERVICE/ui.activate"
ui_write() {
 local phase="$1" message="$2" staging="${STATUS_FILE}.tmp"
 print -rn -- "$phase"$'\n'"$message" > "$staging" && mv -f "$staging" "$STATUS_FILE"
}
ui_begin() {
 [[ "${RELAY_HEADLESS:-0}" != 1 ]] || { print -r -- "$1"; return 0; }
 STATUS_FILE=$(mktemp "$SERVICE/status.XXXXXX") || return 1
 rm -f "$UI_ACTIVATE"
 ui_write progress "$1" || return 1
 /usr/bin/osascript -l JavaScript "$UI_SCRIPT" "$STATUS_FILE" "$UI_ACTIVATE" &
 UI_PID=$!
}
ui_cleanup() {
 [[ -z "$STATUS_FILE" ]] || rm -f "$STATUS_FILE" "${STATUS_FILE}.tmp"
 [[ -z "$UI_PID" ]] || kill "$UI_PID" 2>/dev/null
 rm -f "$UI_ACTIVATE"
}
show_progress() {
 print -r -- "$1"
 [[ "${RELAY_HEADLESS:-0}" != 1 ]] || return 0
 ui_write progress "$1"
}
notice() {
 [[ "${RELAY_HEADLESS:-0}" != 1 ]] || { print -r -- "$1"; return 0; }
 local phase=success
 [[ "$2" != error ]] || phase=error
 print -r -- "$1"
 if [[ -n "$UI_PID" ]] && kill -0 "$UI_PID" 2>/dev/null && ui_write "$phase" "$1"; then
  wait "$UI_PID"
  UI_PID=''
 else
  # 目录不可写或进度窗口未能启动时，也只使用同一个原生窗口。
  if [[ -n "$UI_PID" ]]; then
   kill "$UI_PID" 2>/dev/null
   wait "$UI_PID" 2>/dev/null
   UI_PID=''
  fi
  /usr/bin/osascript -l JavaScript "$UI_SCRIPT" --result "$phase" "$1"
 fi
}
