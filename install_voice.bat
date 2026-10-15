@echo off
setlocal EnableDelayedExpansion
cd /d "%~dp0"
set LOG=voice_install_log.txt
echo Voice install started %date% %time% > %LOG%
echo Running from folder: %cd% >> %LOG%
if exist .venv\Scripts\python.exe (echo .venv found >> %LOG%) else (echo .venv NOT found in this folder >> %LOG%)
if exist app.py (echo app.py found >> %LOG%) else (echo app.py NOT found in this folder >> %LOG%)
echo === 0/4  Checking your Python version ===
echo Step 0: python version check >> %LOG%
set NEEDREBUILD=0
if not exist .venv\Scripts\python.exe set NEEDREBUILD=1
if "!NEEDREBUILD!"=="0" (
  .venv\Scripts\python -c "import sys;print(sys.version);sys.exit(0 if (3,10)<=sys.version_info[:2]<=(3,13) and sys.maxsize>2**32 else 1)" >> %LOG% 2>&1
  if errorlevel 1 set NEEDREBUILD=1
)
if "!NEEDREBUILD!"=="1" (
  echo The app's Python environment needs to be rebuilt with Python 3.12 or 3.13. Your database and settings are NOT touched.
  echo Looking for Python 3.12 >> %LOG%
  set PY312=
  call :trypy "py -3.12"
  if not defined PY312 call :trypy "%LocalAppData%\Programs\Python\Python312\python.exe"
  if not defined PY312 call :trypy "C:\Program Files\Python312\python.exe"
  if not defined PY312 call :trypy "py -3.13"
  if not defined PY312 call :trypy "%LocalAppData%\Programs\Python\Python313\python.exe"
  if not defined PY312 (
    echo No suitable Python found. Asking the Python install manager for 3.12...
    py install 3.12 >> %LOG% 2>&1
    call :trypy "py -3.12"
  )
  if not defined PY312 (
    echo Trying winget for Python 3.12...
    winget install -e --id Python.Python.3.12 --accept-source-agreements --accept-package-agreements >> %LOG% 2>&1
    call :trypy "%LocalAppData%\Programs\Python\Python312\python.exe"
    if not defined PY312 call :trypy "C:\Program Files\Python312\python.exe"
  )
  if not defined PY312 (
    echo Trying Python 3.13 with the install manager...
    py install 3.13 >> %LOG% 2>&1
    call :trypy "py -3.13"
  )
  if not defined PY312 (
    echo Trying winget for Python 3.13...
    winget install -e --id Python.Python.3.13 --accept-source-agreements --accept-package-agreements >> %LOG% 2>&1
    call :trypy "%LocalAppData%\Programs\Python\Python313\python.exe"
    if not defined PY312 call :trypy "C:\Program Files\Python313\python.exe"
  )
  if not defined PY312 (
    echo Could not find or install a supported Python automatically. See %LOG%.
    echo Please install Python 3.13 from https://www.python.org/downloads/ ^(tick "Add python.exe to PATH"^), then run this file again.
    pause & exit /b 1
  )
  echo Using Python: !PY312! >> %LOG%
  echo Stopping the organizer if it is running...
  powershell -NoProfile -Command "Get-NetTCPConnection -LocalPort 8765 -State Listen -ErrorAction SilentlyContinue | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }; Get-CimInstance Win32_Process -Filter \"Name like 'python%%'\" | Where-Object { $_.CommandLine -match 'uvicorn|app\.py|\.venv' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }" >> %LOG% 2>&1
  timeout /t 3 /nobreak >nul
  if exist .venv rmdir /s /q .venv >> %LOG% 2>&1
  if exist .venv (
    set OLDV=.venv_old_%random%
    ren .venv !OLDV! >> %LOG% 2>&1
  )
  if exist .venv (
    echo Could not remove or rename the old .venv folder. Close every Command Prompt, PowerShell and start.bat window, then run this again. If it still fails, restart the computer and run this file first.
    pause & exit /b 1
  )
  !PY312! -m venv .venv >> %LOG% 2>&1
  if not exist .venv\Scripts\python.exe (echo Creating the new environment failed. See %LOG%. & pause & exit /b 1)
  .venv\Scripts\python -m pip install -q -r requirements.txt >> %LOG% 2>&1
  if errorlevel 1 (echo Installing the app requirements failed. See %LOG%. & pause & exit /b 1)
  echo Environment rebuilt.
)

echo === 1/4  Whisper (speech to text, runs on this computer) ===
.venv\Scripts\python -m pip install --upgrade pip >> %LOG% 2>&1
.venv\Scripts\python -m pip install "faster-whisper>=1.1.0" "av>=14,<19" >> %LOG% 2>&1
if errorlevel 1 (
  echo Whisper install failed. Last lines of the log:
  powershell -NoProfile -Command "Get-Content '%LOG%' -Tail 30"
  echo.
  echo Please send me the file %LOG% from this folder.
  pause & exit /b 1
)
where nvidia-smi >nul 2>nul
if not errorlevel 1 (
  echo NVIDIA GPU found: adding the CUDA libraries Whisper needs on the GPU...
  .venv\Scripts\python -m pip install nvidia-cublas-cu12 "nvidia-cudnn-cu12==9.*" >> %LOG% 2>&1
  if errorlevel 1 echo The GPU libraries did not install. Whisper will fall back to the CPU. See %LOG%.
) else (
  echo No NVIDIA GPU found: Whisper will use the CPU. For speed on a CPU, set ORG_WHISPER_MODEL=small before running start.bat.
)

echo === 2/4  Downloading the Whisper model (about 1.6 GB, once) ===
.venv\Scripts\python -c "from faster_whisper import WhisperModel; WhisperModel('large-v3-turbo', device='cpu', compute_type='int8'); print('Whisper model ready')"
if errorlevel 1 (echo The Whisper model did not download. Check your internet connection and run this again. & pause & exit /b 1)

echo === 3/4  Ollama (runs the tag-suggestion model locally) ===
where ollama >nul 2>nul
if errorlevel 1 (
  where winget >nul 2>nul
  if errorlevel 1 (
    echo Please install Ollama from https://ollama.com/download then run this file again.
    pause & exit /b 1
  )
  winget install -e --id Ollama.Ollama --accept-source-agreements --accept-package-agreements
  set "PATH=!PATH!;%LocalAppData%\Programs\Ollama"
)
where ollama >nul 2>nul
if errorlevel 1 (
  echo Ollama installed but this window cannot see it yet. Close this window, open a new one, and run install_voice.bat again.
  pause & exit /b 1
)

echo === 4/4  Downloading the tag model qwen2.5:14b-instruct (about 9 GB, once) ===
ollama pull qwen2.5:14b-instruct
if errorlevel 1 (echo The model did not download. Make sure Ollama is running ^(system tray^) and run this again. & pause & exit /b 1)
echo.
echo Done. Close this window, run start.bat, and press V in triage to record a note.
echo Nothing is sent anywhere: audio, transcripts and tags stay on this computer.
pause

goto :eof

:trypy
rem Runs the candidate for real and reads back the minor version (0 = unusable). Accepts 3.10 to 3.13, 64-bit.
set "CAND=%~1"
if /i "%CAND:~0,3%"=="py " (set "CALLER=%CAND%") else (set CALLER="%CAND%")
set "OUT=0"
for /f "delims=" %%A in ('%CALLER% -c "import sys;print(sys.version_info[1] if sys.version_info[0]==3 and sys.maxsize>2**32 else 0)" 2^>nul') do set "OUT=%%A"
echo candidate %CAND% reports minor version !OUT! >> %LOG%
if !OUT! GEQ 10 if !OUT! LEQ 13 set "PY312=%CALLER%"
goto :eof
