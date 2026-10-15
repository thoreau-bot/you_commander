@echo off
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (echo Run install.bat first. & pause & exit /b 1)
rem Stop any old copy still listening on port 8765
powershell -NoProfile -Command "Get-NetTCPConnection -LocalPort 8765 -State Listen -ErrorAction SilentlyContinue | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }"
set ORG_DB=organizer.db
start "" http://127.0.0.1:8765
.venv\Scripts\python -m uvicorn app:app --host 127.0.0.1 --port 8765
pause
