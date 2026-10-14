# [INPUT]: 同目录控制脚本、项目根目录固定清单与代理配置。
# [OUTPUT]: 环境安装进度、后台代理及 PID、启动时间和端口记录。
# [POS]: Windows 启动入口；共用互斥锁，不接管其他进程的端口。
# [PROTOCOL]: 变更时更新此头部，然后检查 CLAUDE.md
param([switch]$Notify)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'control.ps1')
. (Join-Path $PSScriptRoot 'runtime.ps1')
$projectRoot = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$runtimeDir = Join-Path $projectRoot '.runtime'
$stateFile = Join-Path $runtimeDir 'process.json'
$lock = $null
$child = $null
try {
    New-Item -ItemType Directory -Force -Path $runtimeDir | Out-Null
    # 同目录启停共用独占锁，避免覆盖身份记录。
    try { $lock = [IO.File]::Open((Join-Path $runtimeDir 'control.lock'), 'OpenOrCreate', 'ReadWrite', 'None') }
    catch { throw '正在启动或停止代理，请等待当前启动窗口完成后重试。' }
    if (Test-Path -LiteralPath $stateFile) {
        $state = Get-Content -LiteralPath $stateFile -Raw -Encoding UTF8 | ConvertFrom-Json
        $existing = Get-CleanerProcess $state
        if ($existing) {
            $activePort = $state.port
            if (-not $activePort) {
                # 兼容旧版记录；新版始终保存进程实际使用的端口。
                $config = Get-Content -LiteralPath (Join-Path $projectRoot 'config.json') -Raw -Encoding UTF8 | ConvertFrom-Json
                $activePort = $config.port
            }
            if (-not (Test-CleanerHealth $activePort $existing.Id 1500)) {
                throw '已有代理未通过健康检查。请双击 stop.cmd，再双击 start.cmd。'
            }
            Show-Status "代理已在运行：127.0.0.1:$activePort"
            exit 0
        }
        Remove-Item -LiteralPath $stateFile
    }
    $runtimeRoot = Join-Path ([Environment]::GetFolderPath('LocalApplicationData')) 'codex-context-cleaner'
    $pythonExe = Get-RequiredCleanerPython (Join-Path $projectRoot 'runtime-manifest.tsv') $runtimeRoot
    Write-Host '[4/5] 正在检查代理配置…'
    # 与代理共用配置校验，启动前即可指出错误字段。
    Push-Location -LiteralPath $projectRoot
    try {
        $configCheck = & $pythonExe -X utf8 (Join-Path $projectRoot 'sanitizer.py') --check-config 2>&1
        if ($LASTEXITCODE -ne 0) { throw ('配置检查失败：' + ($configCheck | Select-Object -Last 1)) }
        $port = [int]($configCheck | Select-Object -Last 1)
    } finally { Pop-Location }
    $listener = [Net.Sockets.TcpListener]::new([Net.IPAddress]::Loopback, $port)
    try { $listener.Start() } catch {
        throw "端口 $port 已被占用。请先停止旧代理，或在 config.json 中换一个端口。"
    } finally { $listener.Stop() }
    Write-Host '[5/5] 配置检查通过，正在启动代理…'
    $scriptFile = Join-Path $projectRoot 'sanitizer.py'
    $child = Start-Process -FilePath $pythonExe -ArgumentList @('-I', '-X', 'utf8', '-u', ('"' + $scriptFile + '"')) -WorkingDirectory $projectRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $runtimeDir 'stdout.log') -RedirectStandardError (Join-Path $runtimeDir 'stderr.log') -PassThru
    $ready = $false
    for ($attempt = 0; $attempt -lt 30; $attempt++) {
        Start-Sleep -Milliseconds 200
        $child.Refresh()
        if ($child.HasExited) { throw '代理启动失败。请查看 .runtime 下的 stdout.log 和 stderr.log。' }
        if (Test-CleanerHealth $port $child.Id) { $ready = $true; break }
    }
    if (-not $ready) { throw '启动检查超时。请查看 .runtime 下的日志。' }
    @{ processId = $child.Id; startedTicks = $child.StartTime.ToUniversalTime().Ticks.ToString(); port = $port } | ConvertTo-Json | Set-Content -LiteralPath $stateFile -Encoding UTF8
    Show-Status "代理已启动：127.0.0.1:$port"

} catch {
    if ($child) {
        try {
            $child.Refresh()
            if (-not $child.HasExited) { $child.Kill(); $null = $child.WaitForExit(5000) }
        } catch { Write-Host '新进程未能退出，请检查 .runtime 下的日志。' }
    }
    Show-Status ('启动失败：' + $_.Exception.Message) -Failure
    exit 1
} finally {
    if ($lock) { $lock.Dispose() }
}
