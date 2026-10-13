# tools/
> L2 | 父级: ../CLAUDE.md
成员清单
docs.py: 将唯一 README.md 渲染为离线 HTML，转义代码与正文。
release.py: 从默认配置和单一源码构建双端 ZIP，不修改源码或本机配置。
smoke.py: 在临时目录验收安装、启停和清洗转发，隔离端口与服务标签。
构建产物只写 dist/，Mac 符号链接由 ZIP 元数据表达。
[PROTOCOL]: 变更时更新此头部，然后检查 CLAUDE.md
