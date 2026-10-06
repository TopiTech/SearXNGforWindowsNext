param(
    [switch]$SkipInstall
)

[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
$OutputEncoding = [System.Text.UTF8Encoding]::new()
$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONUTF8 = "1"
$ErrorActionPreference = "Stop"

# Determine workspace root directory
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Push-Location $repoRoot

$serverProcess = $null
$testExitCode = 0

function Stop-PortListeners {
    param([int]$Port = 8888)
    try {
        $conns = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
        if ($conns) {
            $pids = $conns.OwningProcess | Select-Object -Unique
            foreach ($p in $pids) {
                if ($p -gt 0) {
                    Stop-Process -Id $p -Force -ErrorAction SilentlyContinue
                }
            }
        }
    } catch {
        # Fallback if Get-NetTCPConnection fails
    }
}

try {
    Write-Host "========================================" -ForegroundColor Cyan
    Write-Host "SearXNG Test Runner: Initializing Setup" -ForegroundColor Cyan
    Write-Host "========================================" -ForegroundColor Cyan
    Write-Host ""

    # Ensure port 8888 is not held by a previous stale test run
    Stop-PortListeners -Port 8888

    # 1. Install dependencies
    if ($SkipInstall) {
        Write-Host "[1/6] Skipping Python dependency installation (-SkipInstall requested)..." -ForegroundColor Yellow
    } else {
        Write-Host "[1/6] Installing Python dependencies (including -Dev)..." -ForegroundColor Green
        & .\tools\install-requirements.ps1 -Dev
        if ($LASTEXITCODE -ne 0) {
            throw "Failed to install dependencies via install-requirements.ps1"
        }
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

    # 3.5 Ensure all patches are applied
    Write-Host "  -> Applying Windows compatibility and feature patches..." -ForegroundColor Green
    & ".\python\python.exe" "tools\apply-patches.py"
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to apply patches via apply-patches.py"
    }

    # 4. Run Unit Tests (patch idempotency, engine disabling, secret key generation, agent tools)
    Write-Host "[4/6] Running unit tests..." -ForegroundColor Green
    & ".\python\python.exe" "tools\test_patches.py"
    if ($LASTEXITCODE -ne 0) {
        throw "Unit tests in tools\test_patches.py failed with exit code $LASTEXITCODE"
    }
    & ".\python\python.exe" "tools\test_agent_tools.py"
    if ($LASTEXITCODE -ne 0) {
        throw "Unit tests in tools\test_agent_tools.py failed with exit code $LASTEXITCODE"
    }
    & ".\python\python.exe" "tools\test_agentic_search.py"
    if ($LASTEXITCODE -ne 0) {
        throw "Unit tests in tools\test_agentic_search.py failed with exit code $LASTEXITCODE"
    }
    & ".\python\python.exe" "tools\test_retrieval_pipeline.py"
    if ($LASTEXITCODE -ne 0) {
        throw "Unit tests in tools\test_retrieval_pipeline.py failed with exit code $LASTEXITCODE"
    }
    & ".\python\python.exe" "tools\test_webui.py"
    if ($LASTEXITCODE -ne 0) {
        throw "Unit tests in tools\test_webui.py failed with exit code $LASTEXITCODE"
    }
    Write-Host "  -> Running evaluation benchmark..." -ForegroundColor Green
    & ".\python\python.exe" "tests\evaluation\run_benchmark.py"
    if ($LASTEXITCODE -ne 0) {
        throw "Benchmark evaluation failed with exit code $LASTEXITCODE"
    }
    Write-Host "  -> Running static type check (Pyrefly)..." -ForegroundColor Green
    & ".\python\python.exe" "-m" "pyrefly" "check"
    if ($LASTEXITCODE -ne 0) {
        throw "Pyrefly type checker failed with exit code $LASTEXITCODE"
    }
    $ruffCmd = Get-Command "ruff" -ErrorAction SilentlyContinue
    if (-not $ruffCmd) {
        $fallbackRuff = Join-Path $repoRoot "python\Scripts\ruff.exe"
        if (Test-Path $fallbackRuff) {
            $ruffCmd = [PSCustomObject]@{ Source = $fallbackRuff }
        }
    }
    if ($ruffCmd) {
        Write-Host "  -> Running linter & code format check (Ruff)..." -ForegroundColor Green
        & $ruffCmd.Source "check" "."
        if ($LASTEXITCODE -ne 0) {
            throw "Ruff linter failed with exit code $LASTEXITCODE"
        }
        & $ruffCmd.Source "format" "--check" "."
        if ($LASTEXITCODE -ne 0) {
            throw "Ruff format check failed with exit code $LASTEXITCODE"
        }
    }
    else {
        Write-Warning "Ruff executable not found on PATH or at python\Scripts\ruff.exe. Skipping linter checks."
    }
    Write-Host "  [OK] Unit tests, benchmark, and static checks passed!" -ForegroundColor Green

    # 5. Start SearXNG server in the background
    Write-Host "[5/6] Starting SearXNG server in background..." -ForegroundColor Green
    $env:SEARXNG_SETTINGS_PATH = "$repoRoot\config\settings.yml"
    
    # Run the server under the embedded python
    $serverProcess = Start-Process -FilePath ".\python\python.exe" `
        -ArgumentList "-m granian --interface wsgi searx.webapp:application --host 127.0.0.1 --port 8888 --blocking-threads 4 --no-ws" `
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
            # Granian may spawn Python worker processes.  Stop-Process only
            # terminates the root process, so an exited root can otherwise
            # leave workers listening on port 8888 after the test run.
            $processIds = @([int]$serverProcess.Id)
            do {
                $previousCount = $processIds.Count
                $processTable = @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue)
                foreach ($candidate in $processTable) {
                    $candidateId = [int]$candidate.ProcessId
                    $parentId = [int]$candidate.ParentProcessId
                    if (($processIds -contains $parentId) -and -not ($processIds -contains $candidateId)) {
                        $processIds += $candidateId
                    }
                }
            } while ($processIds.Count -gt $previousCount)

            for ($index = $processIds.Count - 1; $index -ge 0; $index--) {
                Stop-Process -Id $processIds[$index] -Force -ErrorAction SilentlyContinue
            }
            Write-Host "  [OK] SearXNG server process tree stopped successfully." -ForegroundColor Green
        }
        catch {
            Write-Host "  [WARN] Failed to stop background server: $_" -ForegroundColor Yellow
        }
    }
    # Ensure any lingering listeners on 8888 are terminated
    Stop-PortListeners -Port 8888
    Pop-Location
    
    # Exit with the test exit code
    exit $testExitCode
}
