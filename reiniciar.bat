@echo off
echo Encerrando servidor anterior...
for /f "tokens=5" %%a in ('netstat -aon ^| findstr ":8000" ^| findstr "LISTENING"') do (
    taskkill /PID %%a /F >nul 2>&1
)
timeout /t 1 /nobreak >nul
echo Iniciando servidor...
cd /d %~dp0
.venv\Scripts\python main.py
