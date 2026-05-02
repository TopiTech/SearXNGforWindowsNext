$ErrorActionPreference = "Stop"

# Locate embedded Python in workspace
$scriptDir = Split-Path -Parent $PSScriptRoot
$pythonExe = Join-Path $scriptDir "python\python.exe"

Write-Host "Python Dependencies Installer" -ForegroundColor Cyan
Write-Host "==============================" -ForegroundColor Cyan
Write-Host ""

if (-not (Test-Path $pythonExe)) {
    Write-Host "✗ Embedded Python not found at: $pythonExe" -ForegroundColor Red
    Write-Host ""
    Write-Host "Make sure you have the complete SearXNG for Windows directory with embedded Python." -ForegroundColor Yellow
    exit 1
}

Write-Host "Python: $pythonExe" -ForegroundColor Gray
Write-Host ""

try {
    Write-Host "Upgrading pip, setuptools, wheel..." -ForegroundColor Green
    & $pythonExe -m pip install --quiet --upgrade pip setuptools wheel
    if ($LASTEXITCODE -ne 0) {
        throw "pip upgrade failed with code $LASTEXITCODE"
    }

    $mainReqs = Join-Path $scriptDir "config\requirements.txt"
    Write-Host "Installing main requirements..." -ForegroundColor Green
    & $pythonExe -m pip install --quiet -r $mainReqs
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to install main requirements from $mainReqs"
    }

    $serverReqs = Join-Path $scriptDir "config\requirements-server.upstream.txt"
    if (Test-Path $serverReqs) {
        Write-Host "Installing server-specific requirements..." -ForegroundColor Green
        & $pythonExe -m pip install --quiet -r $serverReqs
        if ($LASTEXITCODE -ne 0) {
            throw "Failed to install server requirements from $serverReqs"
        }
    }

    Write-Host ""
    Write-Host "✓ Installation complete!" -ForegroundColor Green
    Write-Host ""
    Write-Host "Next: Run '.\SearXNG for Windows.bat' to start the server." -ForegroundColor Cyan
}
catch {
    Write-Host ""
    Write-Host "✗ Installation failed: $_" -ForegroundColor Red
    exit 1
}
