# codex-context-cleaner

为 Codex 提供的本机会话上下文清洗工具。清理发往上游的推理历史与历史项标识，缓解 Responses 中转服务的兼容问题。

这是第三方工具，不会解密数据，也不会删除本地聊天文件。

## 下载与启动

从 [Releases](https://github.com/solink7/codex-context-cleaner/releases/latest) 下载对应系统的 ZIP，完整解压后使用。不要下载 GitHub 自动生成的 Source code 压缩包来直接运行。

- Mac：下载 `codex-context-cleaner-macOS.zip`，双击“启动代理.app”。
- Windows：下载 `codex-context-cleaner-Windows.zip`，双击 `start.cmd`。

无需预先安装 Python。启动器会检查 Python 3.11+ 和所需标准库，缺少时自动下载、校验并安装专用环境。首次安装需要联网，不需要管理员权限，不修改系统 PATH。

看到“代理已启动”后，在客户端或 CC Switch 中填写：

- API 地址：`http://127.0.0.1:8787/v1`
- 协议：Responses
- API Key：你原来使用的上游 Key

新开一次聊天验证连接。本机启动成功只表示代理正常，不代表上游认证成功。

停止时，Mac 双击“停止代理.app”；Windows 双击 `stop.cmd`。关闭客户端不会停止代理，重复启动不会创建第二个代理进程。

## 启动提示

检查环境、下载、安装、检查配置、启动会依次显示进度。环境已就绪时自动跳过下载和安装。

- Mac：进度与结果使用同一个紧凑窗口。成功约 2 秒关闭；失败保留原因，查看后点击“关闭”。
- Windows：进度与结果显示在当前命令窗口。成功约 2 秒关闭；失败保留原因，按任意键关闭。

安装期间请保持窗口打开。停止代理会保留专用环境，后续可离线复用；真实聊天仍需要连接上游。

## 配置

打开解压目录中的 `config.json`，用文本编辑器修改并保存为 UTF-8，然后先停止、再启动。

- `upstream_base_url`：真正的上游 API 地址，默认 `https://agentrouter.org/v1`。不要填代理自身地址。
- `port`：本机端口，默认 `8787`。修改后也要修改客户端地址。
- `timeout_seconds`：每次网络读写的等待时间，默认 `600` 秒。
- `assume_full_history`：默认 `false`。只有确认客户端每次发送完整历史，才改为 `true`。

Mac 包中的 `config.json` 是应用内配置的快捷入口，请打开后编辑，不要删除或替换整个文件。也可右键“启动代理.app” → 显示包内容 → Contents → Resources，编辑其中的同名文件。

## 排错与日志

- 下载失败：Mac 检查能否访问 GitHub；Windows 检查能否访问 python.org，然后重新启动。
- 校验失败：本次安装已取消，检查网络后重试。
- 安装失败：检查磁盘空间、文件权限、系统版本和安全软件提示。
- 端口被占用：先停止旧代理，或修改端口并同步更新客户端地址。
- 能启动但聊天失败：检查 API Key、上游地址和网络。
- 旧会话提示历史不可用：新开会话重试。代理不能恢复只保存在上游的历史。

为兼容旧版运行记录，本地后台标识继续使用 `Relay-Sanitizer`：

- Mac 日志：`~/Library/Application Support/Relay-Sanitizer/` 中的 `stdout.log`、`stderr.log`、`launcher.log`。
- Windows 日志：解压目录 `.runtime/` 中的 `stdout.log`、`stderr.log`。
- Windows 专用 Python：`%LOCALAPPDATA%\Relay-Sanitizer\python`。

Mac 可在 Finder 按 Command + Shift + G，粘贴日志目录。Windows 用 PowerShell 查看日志时指定 UTF-8：

```powershell
Get-Content -LiteralPath .\.runtime\stderr.log -Encoding UTF8 -Tail 30
```

运行期间不要移动或删除工具目录。更新时先停止旧代理，再替换文件。

## 支持范围

- Mac：macOS 11+，Apple 与 Intel 芯片。
- Windows：Windows 10/11，x64、x86、ARM64。
- 协议：HTTP Responses 与流式输出（SSE）；不支持 WebSocket。
- 清洗：移除 `input` 中的 `reasoning` 项和顶层 `id`，保留工具 `call_id`、文件引用及消息内容。
- 边界：删除推理历史会丢失对应的推理连续性。`conversation`、`item_reference`、`compaction` 无法还原，会明确报错。
- `previous_response_id`：默认拒绝；开启 `assume_full_history` 后移除该字段。
- `compact`：路径可转发，但返回的压缩历史仍不能用于后续清洗。

只监听本机回环地址，不开机自启，不修改客户端配置，不读取或保存 API Key，不记录聊天正文。客户端认证头会转发给上游，网络错误不会自动重试。

缺少环境时安装 Python 3.13.16。Mac 使用 [Astral 便携发行版](https://github.com/astral-sh/python-build-standalone/releases/tag/20261009)，Windows 使用 [Python 官方嵌入式包](https://www.python.org/downloads/release/python-31316/)。下载地址和 SHA-256 固定在 `runtime-manifest.tsv`，校验通过后才执行。

## 开发与本地打包

只维护这个仓库。代理核心使用 Python 标准库，平台启动逻辑位于 `platform/mac` 和 `platform/windows`。

```bash
python -B -m unittest discover -s tests -v
python -B tools/release.py
```

两个发布包生成在 `dist/`。构建使用仓库中的 `config.example.json`，不会把本地配置、运行记录或缓存带入发布包。

只维护这一份 `README.md`。GitHub 直接展示 Markdown，发布包中的 `README.html` 在打包时自动生成。

## 自动打包与版本发布

- 每次 push：GitHub Actions 在 Mac、Windows 运行测试、构建 ZIP，并验证解压后的运行流程。可在对应 Actions 运行的 Artifacts 中下载测试包。
- Pull request：运行相同检查，不发布 Release。
- 推送 `v` 开头的版本标签：检查全部通过后，自动在 Releases 发布两个 ZIP。

发布 `v0.1.0` 的命令：

```bash
git tag -a v0.1.0 -m "Release v0.1.0"
git push origin main
git push origin v0.1.0
```

后续使用新的版本号，例如 `v0.1.1`，不要覆盖已经发布的标签。无需在本地手动上传压缩包。
