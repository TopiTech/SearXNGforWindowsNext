@echo off
SETLOCAL
SET PY=%~dp0..\python\python.exe
IF NOT EXIST "%PY%" (
  echo Embedded python not found at %PY%
  exit /b 1
)
"%PY%" -m pip install --upgrade pip setuptools wheel
"%PY%" -m pip install -r "%~dp0..\config\requirements.txt"
IF EXIST "%~dp0..\config\requirements-server.upstream.txt" (
  "%PY%" -m pip install -r "%~dp0..\config\requirements-server.upstream.txt"
)

echo Done. Run "SearXNG for Windows.bat" to start the server.
ENDLOCAL
