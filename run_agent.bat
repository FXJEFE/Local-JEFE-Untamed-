@echo off
setlocal

set "PYTHON=C:\Users\LocalLarry\AppData\Local\Programs\Python\Python311\python.exe"
if not exist "%PYTHON%" set "PYTHON=python"

echo Launching agent from clean GITHUB structure...
"%PYTHON%" "%~dp0\src\agent_v2.py" %*

endlocal
