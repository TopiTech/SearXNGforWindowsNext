# SearXNG for Windows — Cache & Temporary Files Cleaner
# Safely removes accumulated __pycache__ (.pyc), .tmp files, and test caches to free disk space.

[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
$OutputEncoding = [System.Text.UTF8Encoding]::new()
$ErrorActionPreference = "Stop"

$workspaceRoot = Split-Path -Parent $PSScriptRoot

Write-Host "SearXNG for Windows — Cache Cleaner" -ForegroundColor Cyan
Write-Host "====================================" -ForegroundColor Cyan
Write-Host "Target directory: $workspaceRoot" -ForegroundColor Gray
Write-Host ""

$initialBytes = 0
$cleanedFilesCount = 0
$cleanedDirsCount = 0

# Measure initial cache sizes
$targets = @(
    (Join-Path $workspaceRoot "python\Lib\site-packages"),
    (Join-Path $workspaceRoot "tools"),
    (Join-Path $workspaceRoot ".ruff_cache")
)

Write-Host "[1/3] Scanning for cache directories and bytecode..." -ForegroundColor Yellow

$pycacheDirs = Get-ChildItem -Path $workspaceRoot -Recurse -Directory -Filter "__pycache__" -ErrorAction SilentlyContinue |
    Where-Object { $_.FullName -notmatch '\\\.git\\' }

$pycFiles = Get-ChildItem -Path $workspaceRoot -Recurse -File -Include "*.pyc", "*.pyo" -ErrorAction SilentlyContinue |
    Where-Object { $_.FullName -notmatch '\\\.git\\' }

$tmpFiles = Get-ChildItem -Path $workspaceRoot -Recurse -File -Filter ".tmp_*" -ErrorAction SilentlyContinue

$ruffCache = Join-Path $workspaceRoot ".ruff_cache"

$totalBytes = 0
foreach ($f in $pycFiles) { $totalBytes += $f.Length }
foreach ($f in $tmpFiles) { $totalBytes += $f.Length }
if (Test-Path $ruffCache) {
    $ruffSize = (Get-ChildItem -Path $ruffCache -Recurse -File -ErrorAction SilentlyContinue | Measure-Object -Property Length -Sum).Sum
    if ($ruffSize) { $totalBytes += $ruffSize }
}

$initialMB = [math]::Round($totalBytes / 1MB, 2)
Write-Host "Found $($pycacheDirs.Count) __pycache__ directories and $($pycFiles.Count) bytecode files ($initialMB MB)." -ForegroundColor Gray
Write-Host ""

Write-Host "[2/3] Cleaning bytecode and cache..." -ForegroundColor Yellow

# 1. Remove __pycache__ directories
foreach ($dir in $pycacheDirs) {
    try {
        Remove-Item -LiteralPath $dir.FullName -Recurse -Force -ErrorAction SilentlyContinue
        $cleanedDirsCount++
    } catch {}
}

# 2. Remove any remaining .pyc / .pyo files
foreach ($f in $pycFiles) {
    try {
        if (Test-Path -LiteralPath $f.FullName) {
            Remove-Item -LiteralPath $f.FullName -Force -ErrorAction SilentlyContinue
            $cleanedFilesCount++
        }
    } catch {}
}

# 3. Remove .tmp files
foreach ($tmp in $tmpFiles) {
    try {
        if (Test-Path -LiteralPath $tmp.FullName) {
            Remove-Item -LiteralPath $tmp.FullName -Force -ErrorAction SilentlyContinue
            $cleanedFilesCount++
        }
    } catch {}
}

# 4. Remove .ruff_cache
if (Test-Path $ruffCache) {
    try {
        Remove-Item -LiteralPath $ruffCache -Recurse -Force -ErrorAction SilentlyContinue
        $cleanedDirsCount++
    } catch {}
}

Write-Host ""
Write-Host "[3/3] Done!" -ForegroundColor Green
Write-Host "====================================" -ForegroundColor Green
Write-Host "Cleaned directories : $cleanedDirsCount" -ForegroundColor Green
Write-Host "Cleaned files       : $cleanedFilesCount" -ForegroundColor Green
Write-Host "Freed disk space    : $initialMB MB" -ForegroundColor Green
Write-Host ""
Write-Host "SearXNG runtime will regenerate bytecode on-demand when launched." -ForegroundColor Cyan
