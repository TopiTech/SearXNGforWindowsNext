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
        throw "Required command not found: $Name"
    }
}

function Ensure-Dir {
    param([string]$Path)

    if (-not (Test-Path $Path)) {
        New-Item -ItemType Directory -Path $Path | Out-Null
    }
}

function Mirror-Copy {
    param(
        [string]$Src,
        [string]$Dst
    )

    Ensure-Dir (Split-Path -Parent $Dst)
    if (Test-Path $Dst) {
        Remove-Item -LiteralPath $Dst -Recurse -Force
    }
    Copy-Item -LiteralPath $Src -Destination $Dst -Recurse -Force
}

function Run-Git {
    param(
        [string[]]$GitArgs,
        [string]$WorkingDirectory
    )

    Write-Host ("git " + ($GitArgs -join " ")) -ForegroundColor Cyan

    Push-Location $WorkingDirectory
    try {
        & git @GitArgs
        if ($LASTEXITCODE -ne 0) {
            throw "git command failed with exit code $LASTEXITCODE"
        }
    }
    finally {
        Pop-Location
    }
}

Assert-Command "git"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$tempRoot = Join-Path $repoRoot $TempDir

Write-Host "Repo root: $repoRoot" -ForegroundColor Green
Write-Host "Temp root: $tempRoot" -ForegroundColor Green

if (Test-Path $tempRoot) {
    Remove-Item -LiteralPath $tempRoot -Recurse -Force
}
New-Item -ItemType Directory -Path $tempRoot | Out-Null

# temp repo
Run-Git -GitArgs @("init") -WorkingDirectory $tempRoot
Run-Git -GitArgs @("remote", "add", "upstream", $UpstreamUrl) -WorkingDirectory $tempRoot

# Windows invalid path 回避
Run-Git -GitArgs @("config", "--local", "core.protectNTFS", "false") -WorkingDirectory $tempRoot
Run-Git -GitArgs @("sparse-checkout", "init", "--no-cone") -WorkingDirectory $tempRoot

# Windows fork に必要な安全なパスだけ取り込む
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
[System.IO.File]::WriteAllLines(
    $scFile,
    $sparsePatterns,
    (New-Object System.Text.UTF8Encoding($false))
)

Run-Git -GitArgs @("fetch", "--depth", "1", "upstream", $Ref) -WorkingDirectory $tempRoot
Run-Git -GitArgs @("checkout", "FETCH_HEAD") -WorkingDirectory $tempRoot

$commitSha = (git -C $tempRoot rev-parse HEAD).Trim()
$commitDate = (git -C $tempRoot show -s --format=%cI HEAD).Trim()

Write-Host "Checked out upstream ref: $Ref" -ForegroundColor Yellow
Write-Host "Resolved commit: $commitSha ($commitDate)" -ForegroundColor Yellow

$sitePackages = Join-Path $repoRoot "python\Lib\site-packages"
$dstSearx = Join-Path $sitePackages "searx"
$dstExtra = Join-Path $sitePackages "searxng_extra"

$srcSearx = Join-Path $tempRoot "searx"
$srcExtra = Join-Path $tempRoot "searxng_extra"

if (-not (Test-Path $srcSearx)) {
    throw "Upstream checkout does not contain searx directory."
}

Write-Host "Syncing searx package..." -ForegroundColor Green
Mirror-Copy -Src $srcSearx -Dst $dstSearx

if (Test-Path $srcExtra) {
    Write-Host "Syncing searxng_extra package..." -ForegroundColor Green
    Mirror-Copy -Src $srcExtra -Dst $dstExtra
}

Copy-Item (Join-Path $tempRoot "requirements.txt") (Join-Path $repoRoot "config\requirements.upstream.txt") -Force
if (Test-Path (Join-Path $tempRoot "requirements-server.txt")) {
    Copy-Item (Join-Path $tempRoot "requirements-server.txt") (Join-Path $repoRoot "config\requirements-server.upstream.txt") -Force
}
Copy-Item (Join-Path $tempRoot "setup.py") (Join-Path $repoRoot "config\setup.upstream.py") -Force
Copy-Item (Join-Path $tempRoot "README.rst") (Join-Path $repoRoot "config\README.upstream.rst") -Force

@"
upstream_url=$UpstreamUrl
ref_requested=$Ref
resolved_commit=$commitSha
resolved_commit_date=$commitDate
synced_at=$(Get-Date -Format o)
"@ | Set-Content (Join-Path $repoRoot "UPSTREAM_VERSION.txt") -Encoding utf8

Write-Host "Applying Windows patches..." -ForegroundColor Green
& (Join-Path $repoRoot "tools\apply-windows-patches.ps1")

Write-Host "Done." -ForegroundColor Green

if ($CleanTemp) {
    Remove-Item -LiteralPath $tempRoot -Recurse -Force
    Write-Host "Temp directory removed." -ForegroundColor DarkGray
}