@echo off
cd /d "%~dp0"
where python >nul 2>nul || (echo Python was not found. Install Python 3.12 from python.org and tick "Add python.exe to PATH", then run this again. & pause & exit /b 1)
if not exist .venv python -m venv .venv
.venv\Scripts\python -m pip install -q -r requirements.txt && echo Install finished. Now double-click start.bat
pause
