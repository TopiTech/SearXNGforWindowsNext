@echo off
setlocal
set "SCRIPT_DIR=%~dp0"
set "REPO_ROOT=%SCRIPT_DIR%.."

if exist "%REPO_ROOT%\python\python.exe" (
    "%REPO_ROOT%\python\python.exe" "%SCRIPT_DIR%searxng_cli.py" %*
) else (
    python "%SCRIPT_DIR%searxng_cli.py" %*
)
exit /b %ERRORLEVEL%
