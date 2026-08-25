[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
$OutputEncoding = [System.Text.UTF8Encoding]::new()
$ErrorActionPreference = "Stop"

# Determine workspace root directory
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Push-Location $repoRoot

$serverProcess = $null
$testExitCode = 0

try {
    Write-Host "========================================" -ForegroundColor Cyan
    Write-Host "SearXNG Test Runner: Initializing Setup" -ForegroundColor Cyan
    Write-Host "========================================" -ForegroundColor Cyan
    Write-Host ""

    # 1. Install dependencies
    Write-Host "[1/5] Installing Python dependencies..." -ForegroundColor Green
    & .\tools\install-requirements.ps1
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to install dependencies via install-requirements.ps1"
    }

    # 2. Ensure settings.yml is present
    Write-Host "[2/5] Checking configuration files..." -ForegroundColor Green
    if (-not (Test-Path "config\settings.yml")) {
        if (Test-Path "config\settings.yml.bak") {
            Write-Host "  -> config\settings.yml not found. Copying from backup..." -ForegroundColor Yellow
            Copy-Item -Path "config\settings.yml.bak" -Destination "config\settings.yml"
        } else {
            throw "config\settings.yml does not exist and backup config\settings.yml.bak is missing."
        }
    } else {
        Write-Host "  -> config\settings.yml is present." -ForegroundColor Gray
    }

    # 3. Ensure a secure secret key is configured
    Write-Host "[3/5] Securing instance secret key..." -ForegroundColor Green
    & ".\python\python.exe" "tools\ensure-secret-key.py"
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to verify or generate secure secret key."
    }

    # 4. Start SearXNG server in the background
    Write-Host "[4/5] Starting SearXNG server in background..." -ForegroundColor Green
    $env:SEARXNG_SETTINGS_PATH = "$repoRoot\config\settings.yml"
    
    # Run the server under the embedded python
    $serverProcess = Start-Process -FilePath ".\python\python.exe" `
        -ArgumentList "-m granian --interface wsgi searx.webapp:application --host 127.0.0.1 --port 8888 --blocking-threads 4" `
        -PassThru -NoNewWindow

    # 5. Wait for the server to become responsive
    Write-Host "[5/5] Waiting for server to respond at http://127.0.0.1:8888 ..." -ForegroundColor Green
    $maxRetries = 30
    $serverReady = $false
    for ($i = 1; $i -le $maxRetries; $i++) {
        # Check if the process has exited unexpectedly
        if ($serverProcess.HasExited) {
            throw "SearXNG server process terminated unexpectedly. Exit code: $($serverProcess.ExitCode)"
        }

        try {
            # Attempt to connect to the server
            $response = Invoke-WebRequest -Uri "http://127.0.0.1:8888" -UseBasicParsing -TimeoutSec 1 -ErrorAction Stop
            if ($response.StatusCode -eq 200) {
                $serverReady = $true
                break
            }
        }
        catch {
            # Expected connection failures while server starts up
        }
        Write-Host "  Wait attempt $i/$maxRetries..." -ForegroundColor Gray
        Start-Sleep -Seconds 1
    }

    if (-not $serverReady) {
        throw "SearXNG server did not start successfully or did not respond within $maxRetries seconds."
    }
    Write-Host "SearXNG server is ready and responding!" -ForegroundColor Green
    Write-Host ""

    # Run the smoke tests
    Write-Host "========================================" -ForegroundColor Cyan
    Write-Host "Executing Smoke Tests" -ForegroundColor Cyan
    Write-Host "========================================" -ForegroundColor Cyan
    Write-Host ""
    
    # Run smoke-test.ps1 and capture the result
    & .\tools\smoke-test.ps1
    $testExitCode = $LASTEXITCODE
}
catch {
    Write-Host ""
    Write-Host "Test Run Error: $_" -ForegroundColor Red
    $testExitCode = 1
}
finally {
    # Always ensure that the background process is terminated cleanly
    if ($serverProcess) {
        Write-Host ""
        Write-Host "Cleaning up: Terminating background SearXNG server..." -ForegroundColor Cyan
        try {
            if (-not $serverProcess.HasExited) {
                # Stop the process tree to ensure all workers are terminated
                Stop-Process -Id $serverProcess.Id -Force -ErrorAction Stop
                Write-Host "  ✓ SearXNG server process stopped successfully." -ForegroundColor Green
            } else {
                Write-Host "  -> Server process was already stopped." -ForegroundColor Gray
            }
        }
        catch {
            Write-Host "  ⚠ Warning: Failed to stop background server: $_" -ForegroundColor Yellow
        }
    }
    Pop-Location
    
    # Exit with the test exit code
    exit $testExitCode
}
