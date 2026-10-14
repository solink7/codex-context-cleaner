# 启动代理.app/Contents/MacOS/
> L2 | 父级: ../CLAUDE.md
成员清单
launcher: 检查前代服务、串行化启停、准备环境并启动唯一 launchd 服务。
progress.js: 360×144 点的紧凑状态窗口。进度与结果复用，长错误可滚动。
status-ui.sh: 写入阶段/文本状态，复用原窗口；CODEX_CONTEXT_CLEANER_HEADLESS=1 用于 CI。
runtime.sh: 构建时生成的环境引导副本，不提交到 Git。Finder 从应用包读取。
legacy.sh: 构建时生成的前代服务检测副本；旧标识不参与新服务启动。
服务标签为 local.codex-context-cleaner，与停止应用共用。
运行环境源码位于 platform/mac/runtime.sh，清单位于项目根目录。
应用副本由 tools/release.py 同步。
[PROTOCOL]: 变更时更新此头部，然后检查 CLAUDE.md
