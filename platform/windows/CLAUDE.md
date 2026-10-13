# platform/windows/
> L2 | 父级: ../CLAUDE.md
成员清单
start.cmd: Windows 根目录启动入口模板，调用本模块的 start.ps1。
stop.cmd: Windows 根目录停止入口模板，失败时保留原窗口。
start.ps1: 从项目根目录读取配置和代理，核验环境并隐藏启动进程。
stop.ps1: 核对根目录运行记录中的 PID 与启动时间，仅停止身份匹配的代理。
control.ps1: 原命令窗口显示结果，核验进程身份并直连本机健康端点。
runtime.ps1: 检查标准库，使用 .NET SHA-256 校验官方包并安装专用 Python。
运行记录位于项目根目录 .runtime/，移动脚本不改变旧记录路径。
安装目录位于 %LOCALAPPDATA%\Relay-Sanitizer\python，不修改 PATH。
[PROTOCOL]: 变更时更新此头部，然后检查 CLAUDE.md
