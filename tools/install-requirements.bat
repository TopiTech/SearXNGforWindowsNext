@echo off
SETLOCAL
set "PY=%~dp0..\python\python.exe"
IF NOT EXIST "%PY%" (
  echo Embedded python not found at %PY%
  exit /b 1
)
"%PY%" -m pip install --prefer-binary --upgrade pip setuptools wheel
if errorlevel 1 (
  echo [ERROR] Failed to upgrade pip, setuptools, wheel.
  exit /b 1
)
"%PY%" -m pip install --prefer-binary -r "%~dp0..\config\requirements.txt"
if errorlevel 1 (
  echo [ERROR] Failed to install main requirements.
  exit /b 1
)
IF EXIST "%~dp0..\config\requirements-server.upstream.txt" (
  "%PY%" -m pip install --prefer-binary -r "%~dp0..\config\requirements-server.upstream.txt"
  if errorlevel 1 (
    echo [ERROR] Failed to install server requirements.
    exit /b 1
  )
)

echo Done. Run "SearXNG for Windows.bat" to start the server.
ENDLOCAL
