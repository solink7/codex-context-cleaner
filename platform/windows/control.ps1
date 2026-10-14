# [INPUT]: Windows 进程信息、运行记录与本机 /health 响应。
# [OUTPUT]: 原窗口内的结果、身份核验与健康检查，不创建弹窗。
# [POS]: Windows 控制层；不启动进程，不修改客户端或代理配置。
# [PROTOCOL]: 变更时更新此头部，然后检查 CLAUDE.md

# ---- UTF-8 输出与状态提示 ----
[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
function Show-Status([string]$Message, [switch]$Failure) {
    Write-Host ''
    if ($Failure) {
        Write-Host $Message -ForegroundColor Red
        Write-Host '请根据上方原因重试。此窗口会保留提示。'
    } else {
        Write-Host $Message -ForegroundColor Green
        if ($Notify) {
            Write-Host '完成，此窗口即将自动关闭。'
            Start-Sleep -Seconds 2
        }
    }
}

# ---- 进程身份与健康检查 ----
function Get-CleanerProcess($State) {
    $processId = 0
    $ticks = 0L
    if (-not [int]::TryParse([string]$State.processId, [ref]$processId) -or $processId -le 0 -or
        -not [long]::TryParse([string]$State.startedTicks, [ref]$ticks) -or $ticks -le 0) {
        throw 'process.json 已损坏。请先确认代理已退出，再删除该文件并启动。'
    }
    $running = Get-Process -Id $processId -ErrorAction SilentlyContinue
    if ($running -and $running.StartTime.ToUniversalTime().Ticks -eq $ticks) { return $running }
    return $null
}

function Test-CleanerHealth([int]$Port, [int]$ProcessId, [int]$Timeout = 500) {
    $response = $null
    $reader = $null
    try {
        $request = [Net.HttpWebRequest]::Create("http://127.0.0.1:$Port/health")
        $request.Proxy = $null
        $request.Timeout = $Timeout
        $request.ReadWriteTimeout = $Timeout
        $response = $request.GetResponse()
        $reader = [IO.StreamReader]::new($response.GetResponseStream(), [Text.Encoding]::UTF8)
        $health = $reader.ReadToEnd() | ConvertFrom-Json
        return ($health.service -eq 'codex-context-cleaner' -and $health.pid -eq $ProcessId)
    } catch { return $false } finally {
        if ($reader) { $reader.Dispose() }
        if ($response) { $response.Dispose() }
    }
}
