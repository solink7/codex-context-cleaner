# [INPUT]: 固定下载清单、已安装 Python 与系统网络/ZIP 能力。
# [OUTPUT]: 可用的 Python 路径；缺少环境时安装当前用户专用运行环境。
# [POS]: Windows 环境引导层；无管理员权限依赖，不修改 PATH 或系统 Python。
# [PROTOCOL]: 变更时更新此头部，然后检查 CLAUDE.md

# ---- 环境探测 ----
function Test-RelayPython([string]$Executable, [string]$Prefix = '') {
    if (-not (Test-Path -LiteralPath $Executable -PathType Leaf)) { return $null }
    $process = $null
    try {
        $info = [Diagnostics.ProcessStartInfo]::new()
        $info.FileName = $Executable
        $code = 'import sys, ssl, http.client, urllib.request, json, pathlib; ssl.create_default_context(); sys.exit(1) if sys.version_info < (3,11) else print(sys.executable)'
        $info.Arguments = $Prefix + '-I -X utf8 -c "' + $code + '"'
        $info.UseShellExecute = $false
        $info.CreateNoWindow = $true
        $info.RedirectStandardOutput = $true
        $info.RedirectStandardError = $true
        $info.StandardOutputEncoding = [Text.Encoding]::UTF8
        $info.StandardErrorEncoding = [Text.Encoding]::UTF8
        $process = [Diagnostics.Process]::new()
        $process.StartInfo = $info
        $null = $process.Start()
        if (-not $process.WaitForExit(5000)) { $process.Kill(); return $null }
        if ($process.ExitCode -ne 0) { return $null }
        $result = $process.StandardOutput.ReadToEnd().Trim()
        if ($result -and (Test-Path -LiteralPath $result -PathType Leaf)) { return $result }
    } catch { return $null } finally {
        if ($process) { $process.Dispose() }
    }
    return $null
}

function Find-RelayPython([string]$PrivateExecutable) {
    $found = Test-RelayPython $PrivateExecutable
    if ($found) { return $found }
    foreach ($name in @('py.exe', 'python.exe', 'python3.exe')) {
        $command = Get-Command $name -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
        if (-not $command -or $command.Source -like '*\Microsoft\WindowsApps\*') { continue }
        $prefix = ''
        if ($name -eq 'py.exe') { $prefix = '-3 ' }
        $found = Test-RelayPython $command.Source $prefix
        if ($found) { return $found }
    }
    # 官方安装器不一定加入 PATH；按 Python 注册位置继续查找。
    foreach ($registryRoot in @('HKCU:\Software\Python\PythonCore', 'HKLM:\Software\Python\PythonCore', 'HKLM:\Software\WOW6432Node\Python\PythonCore')) {
        foreach ($version in @(Get-ChildItem -LiteralPath $registryRoot -ErrorAction SilentlyContinue)) {
            $key = Get-Item -LiteralPath ($version.PSPath + '\InstallPath') -ErrorAction SilentlyContinue
            if (-not $key) { continue }
            $candidate = $key.GetValue('ExecutablePath')
            if (-not $candidate) { $candidate = Join-Path $key.GetValue('') 'python.exe' }
            $found = Test-RelayPython $candidate
            if ($found) { return $found }
        }
    }
    return $null
}

# ---- 下载与校验 ----
function Get-RelayRuntimeEntry([string]$Manifest, [string]$Architecture) {
    $key = switch ($Architecture.ToUpperInvariant()) {
        'AMD64' { 'windows-x64' }
        'X86' { 'windows-x86' }
        'ARM64' { 'windows-arm64' }
        default { throw '不支持这台电脑的芯片类型。需要 x64、x86 或 ARM64 Windows。' }
    }
    $entries = @(Import-Csv -LiteralPath $Manifest -Delimiter "`t" -Encoding UTF8 | Where-Object { $_.platform -eq $key })
    if ($entries.Count -ne 1 -or $entries[0].sha256 -notmatch '^[0-9a-f]{64}$' -or
        $entries[0].url -notmatch '^https://www\.python\.org/ftp/python/[0-9.]+/python-[0-9.]+-embed-(amd64|win32|arm64)\.zip$') {
        throw '运行环境下载清单无效，请重新解压完整的工具文件夹。'
    }
    return $entries[0]
}

function Save-RelayRuntime([string]$Url, [string]$Destination) {
    [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
    $response = $null
    $inputStream = $null
    $outputStream = $null
    try {
        $request = [Net.HttpWebRequest]::Create($Url)
        $request.Timeout = 15000
        $request.ReadWriteTimeout = 30000
        $response = $request.GetResponse()
        $inputStream = $response.GetResponseStream()
        $outputStream = [IO.File]::Create($Destination)
        $buffer = New-Object byte[] 65536
        $received = 0L
        $clock = [Diagnostics.Stopwatch]::StartNew()
        while (($count = $inputStream.Read($buffer, 0, $buffer.Length)) -gt 0) {
            if ($clock.Elapsed.TotalSeconds -gt 300) { throw '下载时间超过 5 分钟。' }
            $outputStream.Write($buffer, 0, $count)
            $received += $count
            $percent = -1
            if ($response.ContentLength -gt 0) { $percent = [Math]::Min(100, [int](100 * $received / $response.ContentLength)) }
            Write-Progress -Activity '正在下载 Python 运行环境' -Status ('已下载 {0:N1} MB，请保持窗口打开。' -f ($received / 1MB)) -PercentComplete $percent
        }
    } catch {
        throw '运行环境下载失败。请检查网络能否访问 python.org，再双击 start.cmd。'
    } finally {
        Write-Progress -Activity '正在下载 Python 运行环境' -Completed
        if ($outputStream) { $outputStream.Dispose() }
        if ($inputStream) { $inputStream.Dispose() }
        if ($response) { $response.Dispose() }
    }
}

function Install-RelayPython($Entry, [string]$RuntimeRoot) {
    $stage = Join-Path $RuntimeRoot ('install-' + [Guid]::NewGuid().ToString('N'))
    $destination = Join-Path $RuntimeRoot 'python'
    $previous = Join-Path $stage 'previous-python'
    $newRuntime = Join-Path $stage 'python'
    try {
        New-Item -ItemType Directory -Path $stage | Out-Null
        Write-Host "`n[2/5] 未找到可用的 Python，正在下载专用运行环境。首次启动需要联网。"
        $archive = Join-Path $stage 'python.zip'
        Save-RelayRuntime $Entry.url $archive
        Write-Host '[3/5] 下载完成，正在校验并安装运行环境…'
        if ((Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash.ToLowerInvariant() -ne $Entry.sha256) {
            throw '下载文件校验失败，已取消安装。请检查网络后重新启动。'
        }
        try {
            Add-Type -AssemblyName System.IO.Compression.FileSystem
            [IO.Compression.ZipFile]::ExtractToDirectory($archive, $newRuntime)
        } catch { throw '运行环境解压失败。请检查剩余磁盘空间和安全软件提示。' }
        if (-not (Test-RelayPython (Join-Path $newRuntime 'python.exe'))) {
            throw '新运行环境未通过检查。请确认系统为 Windows 10/11，且未被安全软件拦截。'
        }
        if (Test-Path -LiteralPath $destination) { Move-Item -LiteralPath $destination -Destination $previous }
        try {
            Move-Item -LiteralPath $newRuntime -Destination $destination
            $result = Test-RelayPython (Join-Path $destination 'python.exe')
            if (-not $result) { throw '安装后的运行环境未通过检查。' }
            return $result
        } catch {
            if (Test-Path -LiteralPath $destination) { Move-Item -LiteralPath $destination -Destination (Join-Path $stage 'failed-python') }
            if (Test-Path -LiteralPath $previous) { Move-Item -LiteralPath $previous -Destination $destination }
            throw '运行环境安装失败，已撤回本次安装。请检查文件权限和磁盘空间。'
        }
    } finally {
        if (Test-Path -LiteralPath $stage) { Remove-Item -LiteralPath $stage -Recurse -Force }
    }
}

function Get-RequiredRelayPython([string]$Manifest, [string]$RuntimeRoot) {
    Write-Host '[1/5] 正在检查本机运行环境…'
    $executable = Join-Path $RuntimeRoot 'python\python.exe'
    $found = Find-RelayPython $executable
    if ($found) { Write-Host '运行环境已就绪，无需安装。'; return $found }
    if ([Environment]::OSVersion.Version.Major -lt 10) { throw '自动安装需要 Windows 10 或更新版本。' }
    New-Item -ItemType Directory -Force -Path $RuntimeRoot | Out-Null
    $lock = $null
    try {
        try { $lock = [IO.File]::Open((Join-Path $RuntimeRoot 'install.lock'), 'OpenOrCreate', 'ReadWrite', 'None') }
        catch { throw '另一个启动窗口正在安装运行环境，请等待完成后重试。' }
        $found = Test-RelayPython $executable
        if ($found) { return $found }
        $architecture = $env:PROCESSOR_ARCHITEW6432
        if (-not $architecture) { $architecture = $env:PROCESSOR_ARCHITECTURE }
        $entry = Get-RelayRuntimeEntry $Manifest $architecture
        return (Install-RelayPython $entry $RuntimeRoot)
    } finally {
        if ($lock) { $lock.Dispose() }
    }
}
