@echo off
rem [INPUT]: 同目录 platform/windows/settings.ps1。
rem [OUTPUT]: 打开本机代理设置，失败时保留窗口。
rem [POS]: Windows 设置入口，不要求已有有效配置。
rem [PROTOCOL]: 变更时更新此头部，然后检查 CLAUDE.md
chcp 65001 >nul
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0platform\windows\settings.ps1" -Notify
if errorlevel 1 pause
