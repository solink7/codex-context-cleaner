#!/bin/zsh
# [INPUT]: launchd 中前代代理的服务注册信息。
# [OUTPUT]: 阻止旧服务仍运行时重复启动；停止入口可退出该服务。
# [POS]: Mac 升级兼容边界；旧标识仅用于检测，不作为新服务身份。
# [PROTOCOL]: 变更时更新此头部，然后检查 CLAUDE.md

require_previous_service_stopped() {
 if /bin/launchctl list local.relay-sanitizer >/dev/null 2>&1; then
  notice '旧版代理仍在运行。请先打开停止代理，再启动当前版本。' error
  return 1
 fi
}

stop_previous_service() {
 local previous_pid=$(/bin/launchctl list local.relay-sanitizer 2>/dev/null | /usr/bin/awk '/"PID"/ {gsub(";", "", $3); print $3}')
 /bin/launchctl remove local.relay-sanitizer 2>/dev/null
 for attempt in {1..30}; do
  [[ -z "$previous_pid" ]] || ! kill -0 "$previous_pid" 2>/dev/null && return 0
  sleep .1
 done
 notice '旧版代理尚未退出，请稍后重试停止。' error
 return 1
}
