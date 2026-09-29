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
  echo Please run: Update-Upstream.bat
  echo Then run:   PowerShell -File .\tools\install-requirements.ps1
  echo Refer to DEVELOPMENT.md for step-by-step setup guides.
  pause
  exit /b 1
)

REM === Configure environment ===
set "SEARXNG_SETTINGS_PATH=%CD%\config\settings.yml"
if not defined SEARXNG_PORT set "SEARXNG_PORT=8888"
if not defined SEARXNG_BIND_ADDRESS set "SEARXNG_BIND_ADDRESS=127.0.0.1"

REM === Automated security: provision a per-install secret_key ===
REM The Python tool seeds config\settings.yml from the tracked example if it
REM is missing, generates (or reuses) a random key in config\secret.key, and
REM prints a single `set SEARXNG_SECRET=<key>` line that we capture below.
REM The real key never lives in any tracked file, so rotating it produces
REM no git diff.
echo Checking security settings...
set "SEARXNG_SECRET="
for /f "tokens=1* delims==" %%A in ('"".\python\python.exe" "tools\ensure-secret-key.py""') do (
  if "%%A"=="set SEARXNG_SECRET" set "SEARXNG_SECRET=%%B"
)
if not defined SEARXNG_SECRET (
  echo [ERROR] Failed to obtain or generate SEARXNG_SECRET.
  pause
  exit /b 1
)
REM Validate the secret key format: ensure key length is exactly 64 hex characters.
REM (Full regex verification is already guaranteed by tools\ensure-secret-key.py)
if "%SEARXNG_SECRET:~63,1%"=="" (
  echo [ERROR] SEARXNG_SECRET is too short. Key must be a 64-char hex string.
  pause
  exit /b 1
)
if not "%SEARXNG_SECRET:~64,1%"=="" (
  echo [ERROR] SEARXNG_SECRET is too long. Key must be a 64-char hex string.
  pause
  exit /b 1
)

REM === Verify and apply Windows compatibility patches ===
echo Verifying Windows compatibility patches...
".\python\python.exe" "tools\apply-patches.py"
if errorlevel 1 (
  echo [ERROR] Failed to apply Windows compatibility patches.
  pause
  exit /b 1
)

REM === Start server ===
if not defined SEARXNG_BLOCKING_THREADS set "SEARXNG_BLOCKING_THREADS=16"
echo.
echo [INFO] Starting SearXNG for Windows...
echo [INFO] Server: Granian (High Performance WSGI)
echo [INFO] Settings: %SEARXNG_SETTINGS_PATH%
echo [INFO] Web server: http://%SEARXNG_BIND_ADDRESS%:%SEARXNG_PORT%
echo [INFO] Blocking threads: %SEARXNG_BLOCKING_THREADS%
echo.

".\python\python.exe" -m granian --interface wsgi searx.webapp:application --host %SEARXNG_BIND_ADDRESS% --port %SEARXNG_PORT% --blocking-threads %SEARXNG_BLOCKING_THREADS% --no-ws

pause
