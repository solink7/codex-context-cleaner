# tools/
> L2 | 父级: ../CLAUDE.md
成员清单
docs.py: 将唯一 README.md 渲染为离线 HTML，转义代码与正文。
release.py: 构建双端 ZIP；生成自包含 Mac 设置应用，保留唯一配置。
smoke.py: 从空配置调用双端设置入口；安装验收禁用外部环境发现。
首次安装验收等待上限覆盖下载时限和服务就绪。
验收覆盖页面、保存、重复打开、鉴权、端口切换和停止。
隔离模式忽略 Python 环境变量；设置子进程显式传入 -X utf8。
构建产物只写 dist/，Mac 符号链接由 ZIP 元数据表达。
[PROTOCOL]: 变更时更新此头部，然后检查 CLAUDE.md
