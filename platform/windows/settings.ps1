# [INPUT]: 同目录环境引导、根目录设置源码与运行环境清单。
# [OUTPUT]: 核验后台设置服务，再确认默认浏览器打开请求。
# [POS]: Windows 设置入口；独立于代理配置和监听端口。
# [PROTOCOL]: 变更时更新此头部，然后检查 CLAUDE.md
param([switch]$Notify)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'control.ps1')
. (Join-Path $PSScriptRoot 'runtime.ps1')
$projectRoot = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
try {
    $runtimeDir = Join-Path $projectRoot '.runtime'
    New-Item -ItemType Directory -Force -Path $runtimeDir | Out-Null
    $runtimeRoot = Join-Path ([Environment]::GetFolderPath('LocalApplicationData')) 'codex-context-cleaner'
    $pythonExe = Get-RequiredCleanerPython (Join-Path $projectRoot 'runtime-manifest.tsv') $runtimeRoot
    $settingsFile = Join-Path $projectRoot 'settings.py'
    & $pythonExe -I -X utf8 $settingsFile --root $projectRoot --check-running
    if ($LASTEXITCODE -ne 0) {
        $arguments = @('-I', '-X', 'utf8', ('"' + $settingsFile + '"'), '--root', ('"' + $projectRoot + '"'), '--no-browser')
        Start-Process -FilePath $pythonExe -ArgumentList $arguments -WorkingDirectory $projectRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $runtimeDir 'settings.stdout.log') -RedirectStandardError (Join-Path $runtimeDir 'settings.stderr.log') | Out-Null
    }
    $ready = $false
    for ($attempt = 0; $attempt -lt 30; $attempt++) {
        & $pythonExe -I -X utf8 $settingsFile --root $projectRoot --check-running
        if ($LASTEXITCODE -eq 0) { $ready = $true; break }
        Start-Sleep -Milliseconds 150
    }
    if (-not $ready) { throw '设置页启动失败，请查看 .runtime 下的 settings.stderr.log。' }
    if ($env:CODEX_CONTEXT_CLEANER_HEADLESS -ne '1') {
        & $pythonExe -I -X utf8 $settingsFile --root $projectRoot --open-running
        if ($LASTEXITCODE -ne 0) { throw '无法打开默认浏览器，请检查系统浏览器设置。' }
    }
    Show-Status '设置服务已就绪。'
} catch {
    Show-Status ('打开设置失败：' + $_.Exception.Message) -Failure
    exit 1
}
