@echo off
chcp 65001 >nul
title 清洗代理
rem [INPUT]: Windows PowerShell 与 platform/windows/stop.ps1。
rem [OUTPUT]: 原窗口显示结果，成功自动关闭，失败等待按键。
rem [POS]: Windows 双击入口，仅对本次进程放宽脚本执行策略。
rem [PROTOCOL]: 变更时更新此头部，然后检查 CLAUDE.md
setlocal
set "cleanerScript=%~dp0platform\windows\stop.ps1"
if not exist "%cleanerScript%" set "cleanerScript=%~dp0stop.ps1"
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%cleanerScript%" -Notify
set "cleanerExit=%errorlevel%"
if not "%cleanerExit%"=="0" (
    echo.
    echo 查看原因后，按任意键关闭窗口。
    pause >nul
)
exit /b %cleanerExit%
