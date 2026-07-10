@echo off
setlocal
cd /d "%~dp0"
title SearXNG for Windows Server
REM === Pre-flight checks ===
echo Checking prerequisites...
if not exist ".\python\python.exe" (
  echo [ERROR] Embedded Python not found: .\python\python.exe
  echo.
  echo Make sure you have the complete SearXNG for Windows directory structure.
  echo Please refer to README.md or DEVELOPMENT.md to set up the embedded Python environment.
  pause
  exit /b 1
)

if not exist ".\python\Lib\site-packages\searx\webapp.py" (
  echo [ERROR] SearXNG webapp not found: .\python\Lib\site-packages\searx\webapp.py
  echo.
  echo You need to sync from upstream and install requirements first.
  echo Please run: PowerShell -File .\tools\install-requirements.ps1
  echo Refer to DEVELOPMENT.md for step-by-step setup guides.
  pause
  exit /b 1
)

if not exist ".\config\settings.yml" (
  echo [ERROR] Configuration missing: .\config\settings.yml
  echo.
  echo Copy config\settings.yml.bak to config\settings.yml and customize as needed.
  echo Refer to README.md for more detail on configuration.
  pause
  exit /b 1
)

REM === Configure environment ===
set "SEARXNG_SETTINGS_PATH=%CD%\config\settings.yml"

REM === Automated security: generate secret_key if default ===
echo Checking security settings...
".\python\python.exe" "tools\ensure-secret-key.py"

REM === Start server ===
echo.
echo [INFO] Starting SearXNG for Windows...
echo [INFO] Server: Granian (High Performance)
echo [INFO] Settings: %SEARXNG_SETTINGS_PATH%
echo [INFO] Web server: http://127.0.0.1:8888
echo.

".\python\python.exe" -m granian --interface wsgi searx.webapp:application --host 127.0.0.1 --port 8888 --blocking-threads 16

pause
