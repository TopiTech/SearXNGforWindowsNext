@echo off
title SearXNG for Windows
echo Starting SearXNG for Windows...

:: Check embedded python
if not exist ".\python\python.exe" (
  echo Error: python.exe not found in the current directory.
  pause
  exit /b
)

:: Check webapp
if not exist ".\python\Lib\site-packages\searx\webapp.py" (
  echo Error: webapp.py not found in the specified path.
  pause
  exit /b
)

:: Check custom config
if not exist ".\config\settings.yml" (
  echo Error: .\config\settings.yml not found.
  pause
  exit /b
)

:: IMPORTANT: tell SearXNG which settings.yml to use
set "SEARXNG_SETTINGS_PATH=%CD%\config\settings.yml"

:: Start SearXNG with embedded python
.\python\python.exe .\python\Lib\site-packages\searx\webapp.py

pause