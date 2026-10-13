# 启动代理.app/Contents/MacOS/
> L2 | 父级: ../CLAUDE.md
成员清单
launcher: 串行化启停，准备运行环境，核验配置并启动唯一 launchd 服务。
progress.js: 360×144 点的紧凑状态窗口。进度与结果复用，长错误可滚动。
status-ui.sh: 写入阶段/文本状态，复用原窗口；RELAY_HEADLESS=1 用于 CI。
runtime.sh: 构建时生成的环境引导副本，不提交到 Git。Finder 从应用包读取。
服务标签为 local.relay-sanitizer，与停止应用共用。
运行环境源码位于 platform/mac/runtime.sh，清单位于项目根目录。
应用副本由 tools/release.py 同步。
[PROTOCOL]: 变更时更新此头部，然后检查 CLAUDE.md
