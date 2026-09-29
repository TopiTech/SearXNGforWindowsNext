[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
$OutputEncoding = [System.Text.UTF8Encoding]::new()
$ErrorActionPreference = "Stop"

# Locate embedded Python in workspace
$scriptDir = Split-Path -Parent $PSScriptRoot
$pythonExe = Join-Path $scriptDir "python\python.exe"

Write-Host "Python Dependencies Installer" -ForegroundColor Cyan
Write-Host "==============================" -ForegroundColor Cyan
Write-Host ""

if (-not (Test-Path $pythonExe)) {
    Write-Host "[ERROR] Embedded Python not found at: $pythonExe" -ForegroundColor Red
    Write-Host ""
    Write-Host "Make sure you have the complete SearXNG for Windows directory with embedded Python." -ForegroundColor Yellow
    exit 1
}

Write-Host "Python: $pythonExe" -ForegroundColor Gray
Write-Host ""

try {
    Write-Host "Upgrading pip, setuptools, wheel..." -ForegroundColor Green
    & $pythonExe -m pip install --quiet --prefer-binary --upgrade pip setuptools wheel
    if ($LASTEXITCODE -ne 0) {
        throw "pip upgrade failed with code $LASTEXITCODE"
    }

    $mainReqs = Join-Path $scriptDir "config\requirements.txt"
    $serverReqs = Join-Path $scriptDir "config\requirements-server.upstream.txt"

    $pipArgs = @("install", "--quiet", "--prefer-binary", "-r", $mainReqs)
    if (Test-Path $serverReqs) {
        $pipArgs += @("-r", $serverReqs)
    }

    Write-Host "Installing requirements (--prefer-binary)..." -ForegroundColor Green
    & $pythonExe -m pip @pipArgs
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to install requirements"
    }

    Write-Host ""
    Write-Host "[OK] Installation complete!" -ForegroundColor Green
    Write-Host ""
    Write-Host "Next: Run '.\SearXNG for Windows.bat' to start the server." -ForegroundColor Cyan
}
catch {
    Write-Host ""
    Write-Host "[ERROR] Installation failed: $_" -ForegroundColor Red
    exit 1
}
