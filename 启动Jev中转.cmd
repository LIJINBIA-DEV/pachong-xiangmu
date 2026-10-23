@echo off
if /i "%~1" neq "--keep-open" (
    "%ComSpec%" /k ""%~f0" --keep-open"
    exit /b
)
setlocal
chcp 65001 >nul
title Jev 本机中转 - Spark
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo 未找到 Python 运行环境：.venv\Scripts\python.exe
    echo 请恢复本项目的运行环境后再启动。窗口保留，可查看错误。
    exit /b 1
)
where ssh >nul 2>&1
if errorlevel 1 (
    echo 未找到 SSH 程序，请检查 Windows OpenSSH 客户端。
    echo 窗口保留，可查看错误。
    exit /b 1
)
set "PYTHONIOENCODING=utf-8"
echo 正在启动 Jev 本机中转及 Spark SSH 通道。
echo 本机需保持开机联网；SSH 断线后会自动重连。
echo 本窗口启动的中转会随窗口关闭而停止；已运行的实例不会重复启动。
echo.
".venv\Scripts\python.exe" -u "scripts\jev_relay_session.py" start
set "JEV_RELAY_EXIT_CODE=%errorlevel%"
echo.
if not "%JEV_RELAY_EXIT_CODE%"=="0" (
    echo 启动或运行出现错误，请查看上面的提示。
) else (
    echo 启动命令已结束。若提示 already running，表示原有中转仍在运行。
)
echo 此窗口保持打开，可手动关闭。
exit /b %JEV_RELAY_EXIT_CODE%
