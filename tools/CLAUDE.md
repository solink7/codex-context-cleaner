# tools/
> L2 | 父级: ../CLAUDE.md
成员清单
docs.py: 将唯一 README.md 渲染为离线 HTML，转义代码与正文。
release.py: 从首次配置、设置页与单一源码构建双端 ZIP，不修改本机配置。
smoke.py: 验收安装、清洗、设置鉴权和端口切换；隔离新旧服务标签并保存启动错误。
隔离模式忽略 Python 环境变量；设置子进程显式传入 -X utf8。
构建产物只写 dist/，Mac 符号链接由 ZIP 元数据表达。
[PROTOCOL]: 变更时更新此头部，然后检查 CLAUDE.md
