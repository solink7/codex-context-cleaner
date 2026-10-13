# 启动代理.app/Contents/Resources/
> L2 | 父级: ../CLAUDE.md
成员清单
runtime-manifest.tsv: 构建生成的固定下载清单，无 Python 时从应用包读取。
sanitizer.py: 构建生成的代理副本，新安装 Python 只读取应用包。
settings.py: 构建生成的本机设置服务入口，独立于代理端口。
control.py: 构建生成的共用配置和平台控制层。
ui/: 构建生成的设置页，只含离线 HTML、CSS 和 JavaScript。
config.json: 构建生成的发布配置，Mac 包根目录提供相对链接。
以上资源不提交到 Git，由 tools/release.py 在暂存目录中生成。
[PROTOCOL]: 变更时更新此头部，然后检查 CLAUDE.md
