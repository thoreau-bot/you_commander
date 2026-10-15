@echo off
cd /d "%~dp0"
rem Copies your database and voice-note audio into a dated folder under backups\
for /f %%i in ('powershell -NoProfile -Command "Get-Date -Format yyyy-MM-dd_HHmm"') do set STAMP=%%i
mkdir "backups\%STAMP%" >nul 2>nul
copy /y organizer.db "backups\%STAMP%\" >nul
if exist audio xcopy /e /i /y audio "backups\%STAMP%\audio" >nul
echo Backed up to backups\%STAMP%
pause
