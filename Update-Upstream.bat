@echo off
setlocal

REM Usage:
REM   Update-Upstream.bat
REM   Update-Upstream.bat 74f1ca2

set REF=%1
if "%REF%"=="" set REF=master

powershell -ExecutionPolicy Bypass -File "%~dp0tools\sync-upstream.ps1" -Ref %REF% -CleanTemp

if errorlevel 1 (
    echo.
    echo Update failed.
    exit /b 1
)

echo.
echo Update completed successfully.
exit /b 0