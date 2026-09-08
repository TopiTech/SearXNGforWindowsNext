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

REM === Configure environment ===
set "SEARXNG_SETTINGS_PATH=%CD%\config\settings.yml"

REM === Automated security: provision a per-install secret_key ===
REM The Python tool seeds config\settings.yml from the tracked example if it
REM is missing, generates (or reuses) a random key in config\secret.key, and
REM prints a single `set SEARXNG_SECRET=<key>` line that we capture below.
REM The real key never lives in any tracked file, so rotating it produces
REM no git diff.
echo Checking security settings...
set "SEARXNG_SECRET="
for /f "delims=" %%K in ('"".\python\python.exe" "tools\ensure-secret-key.py""') do %%K
if not defined SEARXNG_SECRET (
  echo [ERROR] Failed to obtain or generate SEARXNG_SECRET.
  pause
  exit /b 1
)
REM Validate the secret key format: must be a 64-character hex string.
REM This is a defense-in-depth check to prevent command injection if the
REM Python script output is ever compromised.
REM Use PowerShell for reliable regex validation (findstr has regex length limits).
powershell -NoProfile -Command "$v = $env:SEARXNG_SECRET; if ($v -notmatch '^[0-9a-fA-F]{64}$') { exit 1 }"
if errorlevel 1 (
  echo [ERROR] SEARXNG_SECRET format validation failed. Key must be a 64-char hex string.
  pause
  exit /b 1
)

REM === Start server ===
echo.
echo [INFO] Starting SearXNG for Windows...
echo [INFO] Server: Granian (High Performance)
echo [INFO] Settings: %SEARXNG_SETTINGS_PATH%
echo [INFO] Web server: http://127.0.0.1:8888
echo.

".\python\python.exe" -m granian --interface wsgi searx.webapp:application --host 127.0.0.1 --port 8888 --blocking-threads 16

pause
