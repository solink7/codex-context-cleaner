#!/bin/zsh
# [INPUT]: 自身资源、runtime.sh 统一环境发现、原路径查询与唯一配置。
# [OUTPUT]: 安装或复用 Python，核验设置服务并打开浏览器。
# [POS]: 自包含设置入口；原目录保存配置，终止信号触发下载清理。
# [PROTOCOL]: 变更时更新此头部，然后检查 CLAUDE.md
SCRIPT="${0:A}"
if [[ "${SCRIPT:t}" == launcher ]]; then
 APP_CONTENTS="${SCRIPT:h:h}"
 ROOT="${SCRIPT:h:h:h:h}"
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
exec >>"$SERVICE/settings-launcher.log" 2>&1
print -r -- "设置入口：$SCRIPT"
source "$APP_CONTENTS/MacOS/status-ui.sh" || exit 1
source "$RUNTIME" || exit 1
# 设置入口使用独立状态文件，不占用代理启停的状态窗口。
SERVICE="$SERVICE/settings-launcher"
mkdir -p "$SERVICE" || exit 1
UI_ACTIVATE="$SERVICE/ui.activate"
ui_begin '正在准备设置界面…' || exit 1
trap ui_cleanup EXIT
trap 'exit 1' HUP INT TERM
# 系统允许打开后仍会隔离应用；从系统查询原路径，不扫描用户目录。
if [[ "$SCRIPT" == */AppTranslocation/* ]]; then
 ORIGINAL=$(/usr/bin/security translocate-original-path "${SCRIPT:h:h:h}") || {
  notice '无法定位解压目录，请在 Finder 中移动整个工具文件夹后重试。' error
  exit 1
 }
 ORIGINAL="${ORIGINAL#*$'\n\t'}"
 if [[ "$ORIGINAL" != /* || ! -d "$ORIGINAL" || "$ORIGINAL" == */AppTranslocation/* ]]; then
  notice '无法定位解压目录，请在 Finder 中移动整个工具文件夹后重试。' error
  exit 1
 fi
 ROOT="${ORIGINAL:h}"
 # 后台服务读取原应用资源，避免依赖临时隔离挂载的生命周期。
 RESOURCES="$ORIGINAL/Contents/Resources"
fi
if [[ "${SCRIPT:t}" == launcher ]]; then
 CONFIG="$ROOT/启动代理.app/Contents/Resources/config.json"
else
 CONFIG="$ROOT/config.json"
fi
if [[ ! -f "$CONFIG" || ! -f "$RESOURCES/settings.py" ]]; then
 notice '工具文件不完整，请完整解压后重试。' error
 exit 1
fi
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
RUNTIME_ROOT="$HOME/Library/Application Support/codex-context-cleaner"
export SSL_CERT_FILE=/etc/ssl/cert.pem
if ! ensure_python "$RESOURCES/runtime-manifest.tsv" "$RUNTIME_ROOT" "$PLATFORM"; then
 notice "$RUNTIME_ERROR" error
 exit 1
fi
# 配置校验由页面保存时完成；此处无需已填写的上游地址。
if ! "$PYTHON_BIN" -I -X utf8 "$RESOURCES/settings.py" --root "$ROOT" --check-running; then
 /usr/bin/nohup "$PYTHON_BIN" -I -X utf8 "$RESOURCES/settings.py" --root "$ROOT" --config "$CONFIG" --no-browser \
  >"$RUNTIME_ROOT/settings.log" 2>&1 </dev/null &
fi
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
MESSAGE='设置服务已就绪。'
if [[ "${CODEX_CONTEXT_CLEANER_HEADLESS:-0}" != 1 ]]; then
 if ! "$PYTHON_BIN" -I -X utf8 "$RESOURCES/settings.py" --root "$ROOT" --open-running; then
  notice '无法打开默认浏览器，请查看 settings-launcher.log。' error
  exit 1
 fi
 MESSAGE='设置已在浏览器打开。'
fi
notice "$MESSAGE" ok
