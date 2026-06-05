@echo off
setlocal

cd /d "%~dp0"

echo [Larry] Bootstrapping paths...
python -c "import larry_paths; larry_paths.bootstrap()" 2>nul

REM Prefer the project's own venv
set "VENV_PY=.venv\Scripts\python.exe"
if exist "%VENV_PY%" (
    set "PY=%VENV_PY%"
    echo [Larry] Using project venv: %PY%
) else (
    set "PY=C:\Users\LocalLarry\AppData\Local\Programs\Python\Python311\python.exe"
    echo [Larry] WARNING: No .venv detected - using system Python
    echo Run "python activate_runtime.py --venv-only" first for best results.
)

echo [Larry] Launching via manage_larry.py ...
if exist "%VENV_PY%" (
    "%VENV_PY%" manage_larry.py start-agent %*
) else (
    "%PY%" agent_v2.py %*
)

endlocal
