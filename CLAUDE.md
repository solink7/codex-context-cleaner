# codex-context-cleaner - Codex 本机会话上下文清洗工具
Python 3.11+ 标准库 + HTML/CSS/JavaScript + macOS launchd/JXA + Windows PowerShell 5.1+ + GitHub Actions

## 目录
platform/: Mac 与 Windows 的环境安装、启动、停止适配。
ui/: 共用本机设置页，提供黑白灰表单和代理控制。
tests/: 协议、引导、提示、文档与发布回归。
tools/: Markdown 渲染、双端打包与系统验收。
.github/: 自动测试、打包、版本标签发布流程。
dist/: 自动生成的压缩包，不是源码目录。

## 成员清单
sanitizer.py: 唯一代理源码，校验配置，清洗历史并转发 HTTP/SSE。
control.py: 配置原子写入、运行身份核验与平台启停；设置失败恢复旧配置。
settings.py: 独立回环端口的设置服务，以会话令牌保护读写和启停。
runtime-manifest.tsv: 固定运行环境版本、架构、下载地址和 SHA-256。
config.example.json: 上游地址留空的首次配置，不含 API Key。
README.md: 面向用户的唯一使用说明，GitHub 直接展示，包内生成 HTML。
AGENTS.md: 协作者入口与修改规则。
CLAUDE.md: 全局地图与发布契约。
.gitignore: 排除私有配置、生成副本、发布包、日志与缓存。
.gitattributes: 固定跨平台文本换行，PowerShell/CMD 保留 CRLF。

## 构建与发布
仓库为 solink7/codex-context-cleaner，初始版本 v0.1.0。
只维护一份源码，发布器不修改源码树。
运行 python -B tools/release.py 在 dist/ 生成两个系统包。
--target macOS 或 Windows 只构建单个平台。
默认读取 config.example.json；--config 显式指定本地定制配置。
Mac 应用中的代理、清单、运行时脚本与停止提示副本只在构建时生成。
本机已有 config.json、调试应用快捷入口和旧副本被 Git 忽略。
普通 push 与 PR 在双端运行测试、构建及真实首次安装验收。
只有 v* 标签的双端检查全部通过，才发布 GitHub Release。
发布任务先上传完整草稿，再将其公开，不提交 ZIP 到 Git。

## 平台边界
Mac 包含启动、停止、设置三个应用，以及配置快捷入口与 HTML 说明。
Windows 包只含代理、配置、清单、控制脚本与生成的 HTML 说明。
新安装的 Mac Python 只读取应用包与 Library，不读取桌面普通文件。
为兼容旧运行记录，服务标签与后台目录继续使用 Relay-Sanitizer。
Mac 后台目录为 ~/Library/Application Support/Relay-Sanitizer/。
Windows 在包内 .runtime/ 保存状态，在用户 LocalAppData 安装 Python。
安装前校验 SHA-256，不改系统 PATH，不设置开机自启。
Mac 单窗口显示进度与结果；Windows 在原命令窗口显示结果。
RELAY_HEADLESS=1 只供验收脚本使用，不打开 Mac 状态窗口。
GUI 生命周期测试只在本地桌面运行，CI 验证实际后台服务链路。

## 设置边界
设置页独立监听系统分配的回环端口，不依赖代理已启动。
所有配置接口验证 Host、Origin 与本机会话令牌。
两个系统共用 ui/，只使用本地资源，不保存 API Key。
设置启停复用平台入口，不建立第二套代理进程身份记录。
保存先校验配置和端口；运行中应用失败则恢复旧配置。
检测到聊天请求仍在转发时，拒绝保存与停止操作。
高级设置折叠；普通用户只填写上游地址和端口。
UI 沿用 Folune 字体、间距与控件规则，配色独立使用灰阶。

## 协议边界
仅监听回环地址，不保存 API Key，不记录聊天正文。
客户端认证头转发给上游，不修改客户端配置，不自动重试请求。
支持 HTTP Responses/SSE，不支持 WebSocket。
移除 reasoning 与顶层 id，保留 call_id、文件引用和消息内容。
删除推理历史会丢失对应的推理连续性，不解密数据，不删除本地会话文件。
远端会话、引用和压缩历史无法还原，必须明确拒绝。
本机健康检查不证明真实上游认证成功。
[PROTOCOL]: 变更时更新此头部，然后检查 CLAUDE.md
