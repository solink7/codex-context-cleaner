# [INPUT]: 同目录环境引导、根目录设置源码与运行环境清单。
# [OUTPUT]: 后台设置服务与默认浏览器界面。
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
    # 已有设置服务时直接打开原页面，避免重复进程与日志文件冲突。
    foreach ($entry in @(Get-ChildItem -LiteralPath $runtimeDir -Filter 'settings-*.json')) {
        $response = $null
        $reader = $null
        try {
            $saved = Get-Content -LiteralPath $entry.FullName -Raw -Encoding UTF8 | ConvertFrom-Json
            $uri = [Uri]$saved.url
            if ($uri.Scheme -ne 'http' -or $uri.Host -ne '127.0.0.1') { continue }
            $request = [Net.HttpWebRequest]::Create($uri.GetLeftPart([UriPartial]::Authority) + '/api/session')
            $request.Proxy = $null
            $request.Timeout = 1500
            $request.ReadWriteTimeout = 1500
            $request.Headers.Add('X-Settings-Token', $uri.Fragment.TrimStart('#'))
            $response = $request.GetResponse()
            $reader = [IO.StreamReader]::new($response.GetResponseStream(), [Text.Encoding]::UTF8)
            $session = $reader.ReadToEnd() | ConvertFrom-Json
            if ($session.service -eq 'cleaner-settings' -and $session.pid -eq $saved.pid) {
                Start-Process -FilePath $saved.url
                Show-Status '设置已在浏览器打开。'
                exit 0
            }
        } catch {} finally {
            if ($reader) { $reader.Dispose() }
            if ($response) { $response.Dispose() }
        }
    }
    $runtimeRoot = Join-Path ([Environment]::GetFolderPath('LocalApplicationData')) 'Relay-Sanitizer'
    $pythonExe = Get-RequiredRelayPython (Join-Path $projectRoot 'runtime-manifest.tsv') $runtimeRoot
    $settingsFile = Join-Path $projectRoot 'settings.py'
    $arguments = @('-I', '-X', 'utf8', ('"' + $settingsFile + '"'), '--root', ('"' + $projectRoot + '"'))
    Start-Process -FilePath $pythonExe -ArgumentList $arguments -WorkingDirectory $projectRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $runtimeDir 'settings.stdout.log') -RedirectStandardError (Join-Path $runtimeDir 'settings.stderr.log') | Out-Null
    $ready = $false
    for ($attempt = 0; $attempt -lt 30; $attempt++) {
        & $pythonExe -I -X utf8 $settingsFile --root $projectRoot --check-running
        if ($LASTEXITCODE -eq 0) { $ready = $true; break }
        Start-Sleep -Milliseconds 150
    }
    if (-not $ready) { throw '设置页启动失败，请查看 .runtime 下的 settings.stderr.log。' }
    Show-Status '设置已在浏览器打开。'
} catch {
    Show-Status ('打开设置失败：' + $_.Exception.Message) -Failure
    exit 1
}
