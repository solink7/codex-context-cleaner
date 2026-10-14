# platform/mac/
> L2 | 父级: ../CLAUDE.md
成员清单
runtime.sh: Mac 环境引导的唯一源码，验证版本和标准库并安装专用 Python。
legacy.sh: 前代服务检测；启动拒绝重复，停止兼容前代服务，不移动用户数据。
settings.sh: 自包含设置入口；查询隔离原路径，核验服务后打开浏览器。
settings.plist: 设置应用身份模板；发布器生成设置代理.app。
启动代理.app/: 自包含启动应用，读取应用包资源，再交由 launchd 运行代理。
停止代理.app/: 停止唯一服务，共用启动应用的提示实现。
应用包内环境脚本、兼容脚本、代理与配置由发布器生成。
设置应用资源由发布器生成；配置仅存在启动应用内。
设置入口日志为 settings-launcher.log；服务日志为 settings.log。
新服务与后台目录统一使用 codex-context-cleaner。
生成副本不进入 Git，源模板在干净检出后可直接打包。
[PROTOCOL]: 变更时更新此头部，然后检查 CLAUDE.md
