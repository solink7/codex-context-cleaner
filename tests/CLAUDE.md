# tests/
> L2 | 父级: ../CLAUDE.md
成员清单
test_sanitizer.py: 本地 HTTP 上游回归。验证清洗、认证、SSE、错误边界和配置。
test_settings.py: 空配置可打开、接口鉴权、端口冲突、请求保护与保存失败恢复。
test_release.py: 干净检出、默认配置隔离、平台筛选与 ZIP 链接权限回归。
test_docs.py: Markdown 与包内 HTML 的中文、代码、链接和转义回归。
test_runtime.py: Mac 环境检查、安装、下载失败和校验失败的分支回归。
test_status_ui.py: 固定 UTF-8 字节传输的文本协议及原生窗口生命周期，验证失败保留与成功关闭；GUI 测试在 CI 跳过。
windows_runtime.tests.ps1: PowerShell 语法、原窗口结果与环境安装回滚的分支回归。
测试只使用模拟凭据与临时目录，不连接真实上游。
[PROTOCOL]: 变更时更新此头部，然后检查 CLAUDE.md
