#!/bin/zsh
# [INPUT]: 既有 Mac 环境引导与启动应用内的设置源码。
# [OUTPUT]: 安装或复用 Python，后台打开独立设置页。
# [POS]: 设置应用入口；配置为空或代理端口冲突时仍可打开。
# [PROTOCOL]: 变更时更新此头部，然后检查 CLAUDE.md
SCRIPT="${0:A}"
if [[ "${SCRIPT:t}" == launcher ]]; then
 ROOT="${SCRIPT:h:h:h:h}"
 APP_CONTENTS="$ROOT/启动代理.app/Contents"
 RESOURCES="$APP_CONTENTS/Resources"
 RUNTIME="$APP_CONTENTS/MacOS/runtime.sh"
else
 ROOT="${SCRIPT:h:h:h}"
 APP_CONTENTS="$ROOT/platform/mac/启动代理.app/Contents"
 RESOURCES="$ROOT"
 RUNTIME="$ROOT/platform/mac/runtime.sh"
fi
SERVICE="$HOME/Library/Application Support/codex-context-cleaner"
umask 077
mkdir -p "$SERVICE" || exit 1
source "$APP_CONTENTS/MacOS/status-ui.sh" || exit 1
source "$RUNTIME" || exit 1
# 设置入口使用独立状态文件，不占用代理启停的状态窗口。
SERVICE="$SERVICE/settings-launcher"
mkdir -p "$SERVICE" || exit 1
ui_begin '正在准备设置界面…' || exit 1
trap ui_cleanup EXIT
MAC_VERSION=$(/usr/bin/sw_vers -productVersion)
if (( ${MAC_VERSION%%.*} < 11 )); then
 notice '需要 macOS 11 或更新版本。' error
 exit 1
fi
case $(/usr/bin/uname -m) in
 arm64) PLATFORM=macos-arm64 ;;
 x86_64) PLATFORM=macos-x64 ;;
 *) notice '不支持这台 Mac 的芯片类型。' error; exit 1 ;;
esac
PYTHON_CANDIDATES=(/opt/homebrew/bin/python3 /usr/local/bin/python3 /Library/Frameworks/Python.framework/Versions/Current/bin/python3)
if /usr/bin/xcode-select -p >/dev/null 2>&1; then PYTHON_CANDIDATES+=(/usr/bin/python3); fi
RUNTIME_ROOT="$HOME/Library/Application Support/codex-context-cleaner"
export SSL_CERT_FILE=/etc/ssl/cert.pem
if ! ensure_python "$RESOURCES/runtime-manifest.tsv" "$RUNTIME_ROOT" "$PLATFORM" "${PYTHON_CANDIDATES[@]}"; then
 notice "$RUNTIME_ERROR" error
 exit 1
fi
# 配置校验由页面保存时完成；此处无需已填写的上游地址。
BROWSER_ARGS=()
[[ "${CODEX_CONTEXT_CLEANER_HEADLESS:-0}" != 1 ]] || BROWSER_ARGS=(--no-browser)
/usr/bin/nohup "$PYTHON_BIN" -I -X utf8 "$RESOURCES/settings.py" --root "$ROOT" --config "$RESOURCES/config.json" "${BROWSER_ARGS[@]}" \
 >"$RUNTIME_ROOT/settings.log" 2>&1 </dev/null &
READY=0
for attempt in {1..30}; do
 if "$PYTHON_BIN" -I -X utf8 "$RESOURCES/settings.py" --root "$ROOT" --check-running; then
  READY=1
  break
 fi
 sleep .15
done
if (( READY == 0 )); then
 notice '设置页启动失败，请查看 settings.log 后重试。' error
 exit 1
fi
notice '设置已在浏览器打开。' ok
