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
    Write-Host "[1/6] Installing Python dependencies..." -ForegroundColor Green
    & .\tools\install-requirements.ps1
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to install dependencies via install-requirements.ps1"
    }

    # 2. Ensure settings.yml is present. The Python tool seeds it from the
    # tracked settings.yml.example on its own, so we just run it here.
    Write-Host "[2/6] Checking configuration files..." -ForegroundColor Green
    if (-not (Test-Path "config\settings.yml")) {
        Write-Host "  -> config\settings.yml not found; tools\ensure-secret-key.py will seed it from settings.yml.example." -ForegroundColor Yellow
    } else {
        Write-Host "  -> config\settings.yml is present." -ForegroundColor Gray
    }

    # 3. Ensure a secure secret key is configured. The tool seeds
    # config\settings.yml from the example if missing and prints
    # `set SEARXNG_SECRET=<key>` on stdout (info goes to stderr).
    Write-Host "[3/6] Securing instance secret key..." -ForegroundColor Green
    $secretKeyLine = & ".\python\python.exe" "tools\ensure-secret-key.py"
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to verify or generate secure secret key."
    }
    if ($secretKeyLine -notmatch '^set SEARXNG_SECRET=(.+)$') {
        throw "tools\ensure-secret-key.py did not emit a SEARXNG_SECRET line. Got: $secretKeyLine"
    }
    $env:SEARXNG_SECRET = $Matches[1]

    # 4. Run Unit Tests (patch idempotency, engine disabling, secret key generation)
    Write-Host "[4/6] Running unit tests..." -ForegroundColor Green
    & ".\python\python.exe" "tools\test_patches.py"
    if ($LASTEXITCODE -ne 0) {
        throw "Unit tests in tools\test_patches.py failed with exit code $LASTEXITCODE"
    }
    Write-Host "  [OK] Unit tests passed!" -ForegroundColor Green

    # 5. Start SearXNG server in the background
    Write-Host "[5/6] Starting SearXNG server in background..." -ForegroundColor Green
    $env:SEARXNG_SETTINGS_PATH = "$repoRoot\config\settings.yml"
    
    # Run the server under the embedded python
    $serverProcess = Start-Process -FilePath ".\python\python.exe" `
        -ArgumentList "-m granian --interface wsgi searx.webapp:application --host 127.0.0.1 --port 8888 --blocking-threads 4" `
        -PassThru -NoNewWindow

    # 6. Wait for the server to become responsive
    Write-Host "[6/6] Waiting for server to respond at http://127.0.0.1:8888 ..." -ForegroundColor Green
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
                Write-Host "  [OK] SearXNG server process stopped successfully." -ForegroundColor Green
            } else {
                Write-Host "  -> Server process was already stopped." -ForegroundColor Gray
            }
        }
        catch {
            Write-Host "  [WARN] Failed to stop background server: $_" -ForegroundColor Yellow
        }
    }
    Pop-Location
    
    # Exit with the test exit code
    exit $testExitCode
}
