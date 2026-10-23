@echo off
chcp 65001 >nul
setlocal EnableExtensions
cd /d "%~dp0"
if not exist "%~dp0.venv\Scripts\python.exe" (
    echo 未找到项目 Python 环境，请检查 .venv。
    pause
    exit /b 1
)
"%~dp0.venv\Scripts\python.exe" -u "%~dp0scripts\project_session.py" --restart-backend %*
if errorlevel 1 (
    echo 重启未完成，请查看上方错误。
    pause
    exit /b 1
)
exit /b 0
