@echo off
rem Installs (or updates) yt-dlp into the app's own environment so the Watch page can fetch captions as text.
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (echo The app environment .venv was not found. Run start.bat once first.& pause & exit /b 1)
.venv\Scripts\python -m pip install --upgrade yt-dlp
echo.
echo Done. Restart the app (close its window, run start.bat). To update later, run this file again - YouTube changes often.
pause
