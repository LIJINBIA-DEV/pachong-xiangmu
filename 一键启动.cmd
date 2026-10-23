@echo off
chcp 65001 >nul
setlocal EnableExtensions
cd /d "%~dp0"
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\bootstrap_windows.ps1" %*
set "launchResult=%errorlevel%"
if not "%launchResult%"=="0" (
    echo.
    echo 启动未完成，请保留上方错误信息。检查网络后可以重新双击此脚本。
    pause
    exit /b %launchResult%
)
echo 项目已停止。
exit /b 0
