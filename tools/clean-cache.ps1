# SearXNG for Windows — Multi-Tier Cache & Storage Optimizer
# Safely removes temporary files, caches, unused translation sources, and development assets.
#
# Usage:
#   .\tools\clean-cache.ps1                  # Level 1: Safe cleanup (__pycache__, .po, .map, .tmp)
#   .\tools\clean-cache.ps1 -Deep            # Level 2: Deep cleanup (+ Babel locale pruning, pip cache)
#   .\tools\clean-cache.ps1 -GitGc           # Level 3: Compact .git objects database
#   .\tools\clean-cache.ps1 -UninstallDev    # Level 4: Remove development packages (pyrefly)

param(
    [switch]$Deep,
    [switch]$PruneBabel,
    [switch]$GitGc,
    [switch]$UninstallDev
)

[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
$OutputEncoding = [System.Text.UTF8Encoding]::new()
$ErrorActionPreference = "Continue"

$workspaceRoot = Split-Path -Parent $PSScriptRoot
$pythonExe = Join-Path $workspaceRoot "python\python.exe"

Write-Host "SearXNG for Windows — Cache & Storage Optimizer" -ForegroundColor Cyan
Write-Host "================================================" -ForegroundColor Cyan
Write-Host "Target directory : $workspaceRoot" -ForegroundColor Gray
Write-Host "Mode             : $(if ($Deep) { 'Deep Clean (-Deep)' } else { 'Standard Safe Clean' })" -ForegroundColor Gray
if ($GitGc) { Write-Host "Git Optimization : Enabled (-GitGc)" -ForegroundColor Gray }
if ($UninstallDev) { Write-Host "Dev Tools Clean  : Enabled (-UninstallDev)" -ForegroundColor Gray }
Write-Host ""

$cleanedFilesCount = 0
$cleanedDirsCount = 0
$freedBytes = 0

function Remove-FileSafe {
    param([string]$FilePath)
    if (Test-Path -LiteralPath $FilePath) {
        try {
            $item = Get-Item -LiteralPath $FilePath -Force -ErrorAction SilentlyContinue
            if ($item -and -not $item.PSIsContainer) {
                $script:freedBytes += $item.Length
                Remove-Item -LiteralPath $FilePath -Force -ErrorAction SilentlyContinue
                $script:cleanedFilesCount++
            }
        } catch {}
    }
}

function Remove-DirectorySafe {
    param([string]$DirPath)
    if (Test-Path -LiteralPath $DirPath) {
        try {
            $items = Get-ChildItem -LiteralPath $DirPath -Recurse -File -Force -ErrorAction SilentlyContinue
            foreach ($it in $items) {
                $script:freedBytes += $it.Length
                $script:cleanedFilesCount++
            }
            Remove-Item -LiteralPath $DirPath -Recurse -Force -ErrorAction SilentlyContinue
            $script:cleanedDirsCount++
        } catch {}
    }
}

# --- Stage 1: Bytecode & Temporary Caches ---
Write-Host "[1/5] Cleaning Python bytecode and temporary caches..." -ForegroundColor Yellow

# 1.1 Remove __pycache__ directories
$pycacheDirs = Get-ChildItem -Path $workspaceRoot -Recurse -Directory -Filter "__pycache__" -ErrorAction SilentlyContinue |
    Where-Object { $_.FullName -notmatch '\\\.git\\' }
foreach ($dir in $pycacheDirs) {
    Remove-DirectorySafe -DirPath $dir.FullName
}

# 1.2 Remove stray .pyc and .pyo files
$pycFiles = Get-ChildItem -Path $workspaceRoot -Recurse -File -Include "*.pyc", "*.pyo" -ErrorAction SilentlyContinue |
    Where-Object { $_.FullName -notmatch '\\\.git\\' }
foreach ($f in $pycFiles) {
    Remove-FileSafe -FilePath $f.FullName
}

# 1.3 Remove temporary files (.tmp_*)
$tmpFiles = Get-ChildItem -Path $workspaceRoot -Recurse -File -Filter ".tmp_*" -ErrorAction SilentlyContinue |
    Where-Object { $_.FullName -notmatch '\\\.git\\' }
foreach ($tmp in $tmpFiles) {
    Remove-FileSafe -FilePath $tmp.FullName
}

# 1.4 Remove Ruff cache
$ruffCache = Join-Path $workspaceRoot ".ruff_cache"
if (Test-Path $ruffCache) { Remove-DirectorySafe -DirPath $ruffCache }


# --- Stage 2: Unused Runtime Assets (PO sources & Source Maps) ---
Write-Host "[2/5] Cleaning unused translation sources (.po) & source maps (.map)..." -ForegroundColor Yellow

# 2.1 SearXNG translations: Remove .po files (Python gettext only reads compiled .mo at runtime)
$translationsDir = Join-Path $workspaceRoot "python\Lib\site-packages\searx\translations"
if (Test-Path $translationsDir) {
    $poFiles = Get-ChildItem -Path $translationsDir -Recurse -File -Filter "*.po" -ErrorAction SilentlyContinue
    foreach ($po in $poFiles) {
        Remove-FileSafe -FilePath $po.FullName
    }
}

# 2.2 Themes static: Remove JS/CSS source maps (*.js.map, *.css.map)
$staticDir = Join-Path $workspaceRoot "python\Lib\site-packages\searx\static"
if (Test-Path $staticDir) {
    $mapFiles = Get-ChildItem -Path $staticDir -Recurse -File -Include "*.map" -ErrorAction SilentlyContinue
    foreach ($m in $mapFiles) {
        Remove-FileSafe -FilePath $m.FullName
    }
}


# --- Stage 3: Deep Package Pruning (Optional / -Deep) ---
if ($Deep -or $PruneBabel) {
    Write-Host "[3/5] Performing deep pruning (Babel locale-data & pip cache)..." -ForegroundColor Yellow

    # 3.1 Prune unneeded Babel locale-data files (keep root + major languages: en, ja, zh, de, fr, es, it, ko, ru, pt)
    $babelLocaleDir = Join-Path $workspaceRoot "python\Lib\site-packages\babel\locale-data"
    if (Test-Path $babelLocaleDir) {
        $allowedPrefixes = @('root', 'en', 'ja', 'zh', 'de', 'fr', 'es', 'it', 'ko', 'ru', 'pt')
        $localeFiles = Get-ChildItem -Path $babelLocaleDir -File -Filter "*.dat" -ErrorAction SilentlyContinue
        $babelPrunedCount = 0
        foreach ($lf in $localeFiles) {
            $baseName = $lf.BaseName.Split('_')[0].ToLower()
            if ($allowedPrefixes -notcontains $baseName) {
                Remove-FileSafe -FilePath $lf.FullName
                $babelPrunedCount++
            }
        }
        if ($babelPrunedCount -gt 0) {
            Write-Host "      Pruned $babelPrunedCount unused Babel locale definitions." -ForegroundColor Gray
        }
    }

    # 3.2 Purge pip download wheel cache
    if (Test-Path $pythonExe) {
        Write-Host "      Purging pip local wheel cache..." -ForegroundColor Gray
        & $pythonExe -m pip cache purge --quiet 2>$null
    }

    # 3.3 Purge patch rollback backups (only with -Deep)
    if ($Deep) {
        $patchBackup = Join-Path $workspaceRoot "python\.patches_backup"
        if (Test-Path $patchBackup) {
            Remove-DirectorySafe -DirPath $patchBackup
            Write-Host "      Purged patch rollback backups." -ForegroundColor Gray
        }
    }
} else {
    Write-Host "[3/5] Skipping deep pruning (run with -Deep to prune unused Babel locales & pip cache)." -ForegroundColor Gray
}


# --- Stage 4: Dev Tools Trimming (Optional / -UninstallDev) ---
if ($UninstallDev) {
    Write-Host "[4/5] Removing optional development tools..." -ForegroundColor Yellow
    if (Test-Path $pythonExe) {
        Write-Host "      Uninstalling pyrefly..." -ForegroundColor Gray
        & $pythonExe -m pip uninstall -y pyrefly --quiet 2>$null
        $pyreflyExe = Join-Path $workspaceRoot "python\Scripts\pyrefly.exe"
        if (Test-Path $pyreflyExe) {
            Remove-FileSafe -FilePath $pyreflyExe
        }
    }
} else {
    Write-Host "[4/5] Skipping dev tools trimming (run with -UninstallDev to uninstall pyrefly)." -ForegroundColor Gray
}


# --- Stage 5: Git Optimization (Optional / -GitGc) ---
if ($GitGc) {
    Write-Host "[5/5] Compacting git object database (git gc)..." -ForegroundColor Yellow
    $gitCmd = Get-Command "git" -ErrorAction SilentlyContinue
    if ($gitCmd) {
        & $gitCmd.Source "gc" "--prune=now" "--aggressive" "--quiet"
        Write-Host "      Git repository compacted." -ForegroundColor Gray
    }
} else {
    Write-Host "[5/5] Skipping Git optimization (run with -GitGc to compact .git repository)." -ForegroundColor Gray
}

# --- Summary ---
$freedMB = [math]::Round($freedBytes / 1MB, 2)
Write-Host ""
Write-Host "================================================" -ForegroundColor Green
Write-Host "Cache & Storage Optimization Complete!" -ForegroundColor Green
Write-Host "================================================" -ForegroundColor Green
Write-Host "Cleaned directories : $cleanedDirsCount" -ForegroundColor Green
Write-Host "Cleaned files       : $cleanedFilesCount" -ForegroundColor Green
Write-Host "Freed disk space    : $freedMB MB" -ForegroundColor Green
Write-Host ""
Write-Host "Runtime will automatically regenerate required bytecode on-demand." -ForegroundColor Cyan
