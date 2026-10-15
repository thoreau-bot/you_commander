@echo off
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (echo Run install.bat first. & pause & exit /b 1)
rem Builds a throwaway demo library (invented videos) and runs it on its own port. Your real organizer.db is never touched.
set ORG_DB=demo_data\organizer.db
set ORG_AUDIO_DIR=demo_data\audio
if not exist demo_data\organizer.db .venv\Scripts\python tools\make_demo.py
start "" http://127.0.0.1:8766
.venv\Scripts\python -m uvicorn app:app --host 127.0.0.1 --port 8766
pause
