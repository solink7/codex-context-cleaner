# 协作者入口
进入项目后，先阅读 CLAUDE.md。
进入子目录后，先阅读该目录 CLAUDE.md 和目标文件头部契约。
只维护当前源码目录，发布器在 dist/ 生成双端 ZIP。
README.md 是唯一说明源；包内 HTML 自动生成，不手动维护副本。
本地 config.json、应用生成副本和 dist/ ZIP 不提交到 Git。
push 自动测试打包；v* 标签在双端检查通过后自动发布。
修改代码后检查文件契约、模块地图和全局地图。
[PROTOCOL]: 变更时更新此头部，然后检查 CLAUDE.md
