@echo off
setlocal EnableExtensions

REM Usage:
REM   Update-Upstream.bat
REM   Update-Upstream.bat 74f1ca2

set "SYNC_SCRIPT=%~dp0tools\sync-upstream.ps1"
set "SYNC_REF=%~1"
if not defined SYNC_REF set "SYNC_REF=master"

powershell -NoProfile -ExecutionPolicy Bypass -Command "try { & $env:SYNC_SCRIPT -Ref $env:SYNC_REF -CleanTemp; exit $LASTEXITCODE } catch { Write-Error $_; exit 1 }"

if errorlevel 1 (
    echo.
    echo Update failed.
    exit /b 1
)

echo.
echo Update completed successfully.
exit /b 0
