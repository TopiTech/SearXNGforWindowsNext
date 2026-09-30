[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
$OutputEncoding = [System.Text.UTF8Encoding]::new()
$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$pythonExe = Join-Path $repoRoot "python\python.exe"
$patchPy = Join-Path $repoRoot "tools\apply-patches.py"

if (-not (Test-Path -LiteralPath $pythonExe)) {
    throw "Embedded Python not found at: $pythonExe"
}

if (-not (Test-Path -LiteralPath $patchPy)) {
    throw "Patch script not found at: $patchPy"
}

Write-Host "Running Python patch tool..." -ForegroundColor Cyan
& $pythonExe $patchPy @args
$exitCode = $LASTEXITCODE

if ($exitCode -eq 0) {
    Write-Host "[OK] Windows patches applied or verified successfully." -ForegroundColor Green
    exit 0
}
elseif ($exitCode -eq 2) {
    Write-Host ""
    Write-Host "[WARN] Some non-critical patches could not be applied due to upstream changes." -ForegroundColor Yellow
    Write-Host "  The SearXNG server will run, but some optional features or tweaks may be inactive." -ForegroundColor Yellow
    Write-Host "  Check diagnostic report at: python\.patches_report.json" -ForegroundColor Yellow
    Write-Host "  To diagnose, run: .\python\python.exe tools\apply-patches.py --check" -ForegroundColor Yellow
    exit 0
}
else {
    Write-Host ""
    Write-Host "[ERROR] Critical Windows patch failure detected (exit code: $exitCode)." -ForegroundColor Red
    Write-Host "  Upstream SearXNG code has likely undergone breaking changes." -ForegroundColor Red
    Write-Host "  Detailed failure analysis saved to: python\.patches_report.json" -ForegroundColor Red
    Write-Host "  To inspect failure details, run:" -ForegroundColor Yellow
    Write-Host "    .\python\python.exe tools\apply-patches.py --check" -ForegroundColor Yellow
    Write-Host "  To roll back files to their pre-patch state, run:" -ForegroundColor Yellow
    Write-Host "    .\python\python.exe tools\apply-patches.py --rollback" -ForegroundColor Yellow
    throw "Python patch tool failed with exit code $exitCode"
}
