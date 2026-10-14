# 停止代理.app/Contents/MacOS/
> L2 | 父级: ../CLAUDE.md
成员清单
launcher: 取得启停互斥锁，核验代理退出，在原窗口显示停止结果。
progress.js: 构建时从启动应用复制的紧凑状态视图。成功约 2 秒关闭，长错误可滚动。
status-ui.sh: 构建时从启动应用复制的提示编排。共用阶段/文本状态协议。
legacy.sh: 构建时生成的升级兼容副本，停止入口也能退出前代服务。
服务标签为 local.codex-context-cleaner，与启动应用共用。
只修改启动应用中的提示源文件；本目录生成副本不进入 Git。
[PROTOCOL]: 变更时更新此头部，然后检查 CLAUDE.md
