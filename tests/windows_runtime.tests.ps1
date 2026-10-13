# [INPUT]: Windows 引导源码、固定清单与临时安装包夹具。
# [OUTPUT]: 原窗口提示、语法、探测、校验与安装回滚的分支回归结果。
# [POS]: 无额外测试依赖的控制层测试；模拟安装不代替 Windows 实机验收。
# [PROTOCOL]: 变更时更新此头部，然后检查 CLAUDE.md
param(
    [string]$WindowsDirectory,
    [Parameter(Mandatory=$true)][string]$Python
)
$ErrorActionPreference = 'Stop'
# Windows PowerShell 5.1 在脚本体中提供 PSScriptRoot。
if (-not $WindowsDirectory) {
    $WindowsDirectory = Join-Path (Split-Path $PSScriptRoot -Parent) 'platform\windows'
}
$testCount = 0
function Assert-Relay($Condition, [string]$Message) {
    if (-not $Condition) { throw $Message }
    $script:testCount++
}
function Expect-RelayFailure([scriptblock]$Action, [string]$Message) {
    $failed = $false
    try { & $Action | Out-Null } catch { $failed = $true }
    Assert-Relay $failed $Message
}
foreach ($file in (Get-ChildItem -LiteralPath $WindowsDirectory -Filter '*.ps1')) {
    $tokens = $null
    $errors = $null
    $null = [Management.Automation.Language.Parser]::ParseFile($file.FullName, [ref]$tokens, [ref]$errors)
    Assert-Relay ($errors.Count -eq 0) ('语法错误：' + $file.Name)
}
# ---- 原窗口内显示结果，不创建 COM 弹窗 ----
. (Join-Path $WindowsDirectory 'control.ps1')
$Notify = $true
$script:relayDelay = 0
$script:relayComCalls = 0
function Start-Sleep([int]$Seconds) { $script:relayDelay = $Seconds }
function New-Object { $script:relayComCalls++; throw '禁止测试创建额外弹窗' }
$messages = @(Show-Status '代理已在运行：127.0.0.1:8787' 6>&1)
Assert-Relay ($script:relayDelay -eq 2) '成功结果未保留 2 秒'
Assert-Relay (($messages -join "`n") -match '代理已在运行') '成功结果未在原窗口显示'
$script:relayDelay = 0
$messages = @(Show-Status '下载失败，请检查网络。' -Failure 6>&1)
Assert-Relay ($script:relayDelay -eq 0) '失败结果不应自动关闭'
Assert-Relay (($messages -join "`n") -match '下载失败') '失败原因未在原窗口显示'
Assert-Relay ($script:relayComCalls -eq 0) '结果提示创建了额外弹窗'
Remove-Item Function:\Start-Sleep
Remove-Item Function:\New-Object
$Notify = $false
. (Join-Path $WindowsDirectory 'runtime.ps1')
Assert-Relay ([bool](Test-RelayPython $Python)) '真实 Python 探测失败'
Assert-Relay (-not (Test-RelayPython (Join-Path $PSScriptRoot 'missing-python.exe'))) '缺失环境未被拒绝'
$projectRoot = Split-Path (Split-Path $WindowsDirectory -Parent) -Parent
$manifest = Join-Path $projectRoot 'runtime-manifest.tsv'
foreach ($arch in @('AMD64', 'X86', 'ARM64')) {
    $entry = Get-RelayRuntimeEntry $manifest $arch
    Assert-Relay ($entry.version -eq '3.13.16') ('架构清单无效：' + $arch)
}
Expect-RelayFailure { Get-RelayRuntimeEntry $manifest 'UNKNOWN' } '未知架构未被拒绝'

# ---- 本地 ZIP 夹具与引导分支 ----
$tempRoot = Join-Path ([IO.Path]::GetTempPath()) ('relay 环境测试-' + [Guid]::NewGuid().ToString('N'))
$runtimeRoot = Join-Path $tempRoot 'runtime'
$fixture = Join-Path $tempRoot 'fixture'
$archive = Join-Path $tempRoot 'python.zip'
$originalProbe = (Get-Item Function:\Test-RelayPython).ScriptBlock
try {
    New-Item -ItemType Directory -Path $fixture, $runtimeRoot | Out-Null
    [IO.File]::WriteAllText((Join-Path $fixture 'python.exe'), 'healthy')
    $hashProbe = Join-Path $tempRoot 'hash.txt'
    [IO.File]::WriteAllBytes($hashProbe, [Text.Encoding]::ASCII.GetBytes('abc'))
    Assert-Relay ((Get-RelaySha256 $hashProbe) -eq 'ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad') '内置 SHA-256 校验结果不正确'
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    [IO.Compression.ZipFile]::CreateFromDirectory($fixture, $archive)
    $entry = [pscustomobject]@{ url='https://www.python.org/fixture.zip'; sha256=(Get-RelaySha256 $archive) }
    $script:relayFixtureArchive = $archive
    $script:relayFailFinalProbe = $false
    $script:relayProbeCount = 0
    function Test-RelayPython([string]$Executable, [string]$Prefix = '') {
        $script:relayProbeCount++
        if (Test-Path -LiteralPath $Executable) {
            if ((Get-Content -LiteralPath $Executable -Raw) -eq 'healthy') {
                if ($script:relayFailFinalProbe -and $Executable -notmatch 'install-') { return $null }
                return $Executable
            }
        }
        return $null
    }
    function Save-RelayRuntime([string]$Url, [string]$Destination) {
        Copy-Item -LiteralPath $script:relayFixtureArchive -Destination $Destination
    }
    $result = Install-RelayPython $entry $runtimeRoot
    Assert-Relay ((Get-Content -LiteralPath $result -Raw) -eq 'healthy') '缺少环境的安装分支失败'
    Assert-Relay (@(Get-ChildItem -LiteralPath $runtimeRoot -Filter 'install-*').Count -eq 0) '安装后未清理暂存目录'
    $result = Get-RequiredRelayPython $manifest $runtimeRoot
    Assert-Relay ([bool]$result) '已有环境未被复用'
    Remove-Item -LiteralPath (Join-Path $runtimeRoot 'python') -Recurse -Force

    $badEntry = [pscustomobject]@{ url=$entry.url; sha256=('0' * 64) }
    $script:relayProbeCount = 0
    Expect-RelayFailure { Install-RelayPython $badEntry $runtimeRoot } '错误 SHA-256 未被拒绝'
    Assert-Relay ($script:relayProbeCount -eq 0) '校验失败后仍执行了运行环境'
    Assert-Relay (@(Get-ChildItem -LiteralPath $runtimeRoot).Count -eq 0) '校验失败后留下文件'

    $private = Join-Path $runtimeRoot 'python'
    New-Item -ItemType Directory -Path $private | Out-Null
    [IO.File]::WriteAllText((Join-Path $private 'python.exe'), 'previous')
    $script:relayFailFinalProbe = $true
    Expect-RelayFailure { Install-RelayPython $entry $runtimeRoot } '安装后探测失败未被拒绝'
    Assert-Relay ((Get-Content -LiteralPath (Join-Path $private 'python.exe') -Raw) -eq 'previous') '失败时未恢复旧环境'
    Assert-Relay (@(Get-ChildItem -LiteralPath $runtimeRoot -Filter 'install-*').Count -eq 0) '回滚后未清理暂存目录'

    function Save-RelayRuntime([string]$Url, [string]$Destination) { throw '模拟网络断开' }
    Expect-RelayFailure { Install-RelayPython $entry $runtimeRoot } '下载失败未被拒绝'
    Assert-Relay ((Get-Content -LiteralPath (Join-Path $private 'python.exe') -Raw) -eq 'previous') '下载失败损坏旧环境'
    Assert-Relay (@(Get-ChildItem -LiteralPath $runtimeRoot -Filter 'install-*').Count -eq 0) '下载失败未清理暂存目录'
} finally {
    Set-Item Function:\Test-RelayPython $originalProbe
    if (Test-Path -LiteralPath $tempRoot) { Remove-Item -LiteralPath $tempRoot -Recurse -Force }
}
Write-Host ("Windows 控制层通过 $testCount 项断言；实际 Windows 进程启停需实机验证。")
