# platform/windows/
> L2 | 父级: ../CLAUDE.md
成员清单
start.cmd: Windows 根目录启动入口模板，调用本模块的 start.ps1。
stop.cmd: Windows 根目录停止入口模板，失败时保留原窗口。
settings.cmd: Windows 根目录设置入口模板，缺少配置时仍可打开。
settings.ps1: 复用环境引导与共用会话核验；服务就绪后打开浏览器。
start.ps1: 从项目根目录读取配置和代理，核验环境并隐藏启动进程。
stop.ps1: 核对根目录运行记录中的 PID 与启动时间，仅停止身份匹配的代理。
control.ps1: 原命令窗口显示结果，核验进程身份并直连本机健康端点。
runtime.ps1: 限时去重探测；下载估时、写入诊断与互斥安装。
运行记录位于解压根目录 .runtime/，使用 PID 和启动时间核验身份。
设置入口支持无浏览器验收；打开失败返回非零状态。
安装目录位于 %LOCALAPPDATA%\codex-context-cleaner\python，不修改 PATH。
下载连接最多等待 15 秒；无数据超时，不自动重试。
下载进度每秒最多刷新四次；磁盘写入错误单独报告。
[PROTOCOL]: 变更时更新此头部，然后检查 CLAUDE.md
