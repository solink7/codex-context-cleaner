# [INPUT]: 同目录 control.ps1 与根目录 .runtime/process.json 的进程身份。
# [OUTPUT]: 停止身份匹配的代理，核验退出后清除记录。
# [POS]: Windows 停止入口；与启动入口共用互斥锁，不按进程名批量停止。
# [PROTOCOL]: 变更时更新此头部，然后检查 CLAUDE.md
param([switch]$Notify)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'control.ps1')
$projectRoot = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$runtimeDir = Join-Path $projectRoot '.runtime'
$stateFile = Join-Path $runtimeDir 'process.json'
$lock = $null
try {
    New-Item -ItemType Directory -Force -Path $runtimeDir | Out-Null
    try { $lock = [IO.File]::Open((Join-Path $runtimeDir 'control.lock'), 'OpenOrCreate', 'ReadWrite', 'None') }
    catch { throw '正在启动或停止代理，请等待当前启动窗口完成后重试。' }
    if (-not (Test-Path -LiteralPath $stateFile)) {
        Show-Status '代理未在运行。'
        exit 0
    }
    $state = Get-Content -LiteralPath $stateFile -Raw -Encoding UTF8 | ConvertFrom-Json
    $running = Get-CleanerProcess $state
    if ($running) {
        $running.Kill()
        if (-not $running.WaitForExit(5000)) { throw '代理尚未退出，请稍后重试。' }
    }
    Remove-Item -LiteralPath $stateFile
    Show-Status '代理已停止。'
} catch {
    Show-Status ('停止失败：' + $_.Exception.Message) -Failure
    exit 1
} finally {
    if ($lock) { $lock.Dispose() }
}
