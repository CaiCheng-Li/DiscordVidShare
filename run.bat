@echo off
REM DiscordVidShare launcher: sets up a local venv with deps, then runs the app.
setlocal
cd /d "%~dp0"

set "VENV_PY=.venv\Scripts\python.exe"

REM Prefer the py launcher; fall back to python on PATH.
where py >nul 2>nul && (set "PY=py") || (set "PY=python")

REM Create the virtual environment on first run.
if not exist "%VENV_PY%" (
    echo Creating virtual environment ^(first run^)...
    %PY% -m venv .venv || goto :error
)

REM Ensure PySide6 is present inside the venv.
"%VENV_PY%" -c "import PySide6" >nul 2>nul || (
    echo Installing dependencies ^(first run^)...
    "%VENV_PY%" -m pip install --upgrade pip >nul 2>nul
    "%VENV_PY%" -m pip install -r requirements.txt || goto :error
)

"%VENV_PY%" -m discordvidshare %*
goto :eof

:error
echo.
echo Setup failed. Make sure Python 3.9+ is installed and on PATH.
pause
