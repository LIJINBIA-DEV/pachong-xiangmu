@echo off
cd /d "%~dp0"
".venv\Scripts\python.exe" "scripts\jev_relay_session.py" stop
pause
