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
& $pythonExe $patchPy

if ($LASTEXITCODE -ne 0) {
    throw "Python patch tool failed with exit code $LASTEXITCODE"
}

Write-Host "✓ Windows patches applied successfully." -ForegroundColor Green
