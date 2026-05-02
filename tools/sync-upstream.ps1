param(
    [string]$UpstreamUrl = "https://github.com/searxng/searxng.git",
    [string]$Ref = "master",
    [string]$TempDir = ".upstream-tmp",
    [switch]$CleanTemp
)

$ErrorActionPreference = "Stop"

function Assert-Command {
    param([string]$Name)
    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "Required command not found: $Name. Please install or add to PATH."
    }
}

function Initialize-Directory {
    param([string]$Path)
    if (-not (Test-Path $Path)) {
        New-Item -ItemType Directory -Path $Path | Out-Null
    }
}

function Sync-MirrorItem {
    param([string]$Src, [string]$Dst)
    Initialize-Directory (Split-Path -Parent $Dst)
    if (Test-Path $Dst) {
        Remove-Item -LiteralPath $Dst -Recurse -Force
    }
    Copy-Item -LiteralPath $Src -Destination $Dst -Recurse -Force
}

function Invoke-GitAction {
    param([string[]]$GitArgs, [string]$WorkingDirectory)
    Write-Host ("→ git " + ($GitArgs -join " ")) -ForegroundColor Cyan
    Push-Location $WorkingDirectory
    try {
        & git @GitArgs
        if ($LASTEXITCODE -ne 0) {
            throw "git failed with exit code $LASTEXITCODE"
        }
    }
    finally {
        Pop-Location
    }
}

# === PRE-FLIGHT CHECKS ===
Write-Host "Performing pre-flight checks..." -ForegroundColor Cyan
@("git") | ForEach-Object { Assert-Command $_ }
Write-Host "✓ All required commands found" -ForegroundColor Green
Write-Host ""

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$tempRoot = Join-Path $repoRoot $TempDir

try {
    Write-Host "Workspace configuration:" -ForegroundColor Cyan
    Write-Host "  Repo root:     $repoRoot"
    Write-Host "  Temp staging:  $tempRoot"
    Write-Host "  Upstream ref:  $Ref"
    Write-Host "  Upstream URL:  $UpstreamUrl"
    Write-Host ""

    # Clean temp directory
    if (Test-Path $tempRoot) {
        Remove-Item -LiteralPath $tempRoot -Recurse -Force
    }
    Initialize-Directory $tempRoot

    Write-Host "Cloning sparse checkout from upstream..." -ForegroundColor Green
    Invoke-GitAction -GitArgs @("init") -WorkingDirectory $tempRoot
    Invoke-GitAction -GitArgs @("remote", "add", "upstream", $UpstreamUrl) -WorkingDirectory $tempRoot
    Invoke-GitAction -GitArgs @("config", "--local", "core.protectNTFS", "false") -WorkingDirectory $tempRoot
    Invoke-GitAction -GitArgs @("sparse-checkout", "init", "--no-cone") -WorkingDirectory $tempRoot

    # Define sparse checkout patterns (safe, minimal sync)
    $sparsePatterns = @(
        "/searx/",
        "/searxng_extra/",
        "/requirements.txt",
        "/requirements-server.txt",
        "/setup.py",
        "/README.rst",
        "/LICENSE"
    )

    $scFile = Join-Path $tempRoot ".git\info\sparse-checkout"
    [System.IO.File]::WriteAllLines($scFile, $sparsePatterns, (New-Object System.Text.UTF8Encoding($false)))

    Invoke-GitAction -GitArgs @("fetch", "--depth", "1", "upstream", $Ref) -WorkingDirectory $tempRoot
    Invoke-GitAction -GitArgs @("checkout", "FETCH_HEAD") -WorkingDirectory $tempRoot

    $commitSha = (git -C $tempRoot rev-parse HEAD).Trim()
    $commitDate = (git -C $tempRoot show -s --format=%cI HEAD).Trim()

    Write-Host "✓ Upstream checkout successful" -ForegroundColor Green
    Write-Host "  Commit:  $commitSha"
    Write-Host "  Date:    $commitDate"
    Write-Host ""

    # Sync core packages
    $sitePackages = Join-Path $repoRoot "python\Lib\site-packages"
    Write-Host "Syncing packages..." -ForegroundColor Green

    $srcSearx = Join-Path $tempRoot "searx"
    if (-not (Test-Path $srcSearx)) {
        throw "ERROR: Upstream searx/ directory not found. Upstream structure may have changed."
    }
    Sync-MirrorItem -Src $srcSearx -Dst (Join-Path $sitePackages "searx")
    Write-Host "  ✓ searx/"

    $srcExtra = Join-Path $tempRoot "searxng_extra"
    if (Test-Path $srcExtra) {
        Sync-MirrorItem -Src $srcExtra -Dst (Join-Path $sitePackages "searxng_extra")
        Write-Host "  ✓ searxng_extra/"
    }

    # Track requirements changes for user notification
    $oldReqPath = Join-Path $repoRoot "config\requirements.upstream.txt"
    $oldReqHash = ""
    if (Test-Path $oldReqPath) {
        $oldReqHash = (Get-FileHash $oldReqPath).Hash
    }

    # Copy requirements and other metadata
    Write-Host "Syncing configuration files..." -ForegroundColor Green
    Copy-Item (Join-Path $tempRoot "requirements.txt") $oldReqPath -Force
    Write-Host "  ✓ requirements.txt"

    if (Test-Path (Join-Path $tempRoot "requirements-server.txt")) {
        Copy-Item (Join-Path $tempRoot "requirements-server.txt") `
            (Join-Path $repoRoot "config\requirements-server.upstream.txt") -Force
    }
    Copy-Item (Join-Path $tempRoot "setup.py") (Join-Path $repoRoot "config\setup.upstream.py") -Force
    Copy-Item (Join-Path $tempRoot "README.rst") (Join-Path $repoRoot "config\README.upstream.rst") -Force

    # Alert user if requirements changed
    $newReqHash = (Get-FileHash $oldReqPath).Hash
    if ($oldReqHash -ne "" -and ($oldReqHash -ne $newReqHash)) {
        Write-Host ""
        Write-Host "⚠  NOTICE: Upstream requirements.txt has changed!" -ForegroundColor Yellow
        Write-Host "   Run: .\tools\install-requirements.ps1" -ForegroundColor Yellow
    }

    Write-Host "Updating UPSTREAM_VERSION.txt..." -ForegroundColor Green
    @"
upstream_url=$UpstreamUrl
ref_requested=$Ref
resolved_commit=$commitSha
resolved_commit_date=$commitDate
synced_at=$(Get-Date -Format o)
"@ | Set-Content (Join-Path $repoRoot "UPSTREAM_VERSION.txt") -Encoding utf8

    Write-Host ""
    Write-Host "Applying Windows-specific patches..." -ForegroundColor Green
    & (Join-Path $repoRoot "tools\apply-windows-patches.ps1")

    Write-Host ""
    Write-Host "✓ Upstream synchronization complete!" -ForegroundColor Green
}
finally {
    if ($CleanTemp -and (Test-Path $tempRoot)) {
        Write-Host "Cleaning temporary directory..." -ForegroundColor Gray
        try {
            Remove-Item -LiteralPath $tempRoot -Recurse -Force
        }
        catch {
            Write-Host "⚠  Warning: Could not remove temp directory: $_" -ForegroundColor Yellow
        }
    }
}