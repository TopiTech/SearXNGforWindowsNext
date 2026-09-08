param(
    [string]$UpstreamUrl = "https://github.com/searxng/searxng.git",
    [string]$Ref = "master",
    [string]$TempDir = ".upstream-tmp",
    [switch]$CleanTemp
)

[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
$OutputEncoding = [System.Text.UTF8Encoding]::new()
$ErrorActionPreference = "Stop"

function Assert-Command {
    param([string]$Name)
    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "Required command not found: $Name. Please install or add to PATH."
    }
}

function Initialize-Directory {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) {
        New-Item -ItemType Directory -Path $Path | Out-Null
    }
}

function Assert-UpstreamRef {
    param([string]$Value)

    if ([string]::IsNullOrWhiteSpace($Value)) {
        throw "Upstream ref must not be empty."
    }
    if ($Value -match '[\x00-\x1F\x7F]') {
        throw "Upstream ref contains control characters."
    }

    & git check-ref-format --branch $Value 2>$null | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "Invalid upstream ref: $Value"
    }
}

function Resolve-WorkspaceChildPath {
    param(
        [string]$Root,
        [string]$RelativePath,
        [string]$Label
    )

    if ([string]::IsNullOrWhiteSpace($RelativePath)) {
        throw "$Label must not be empty."
    }
    if ([System.IO.Path]::IsPathRooted($RelativePath)) {
        throw "$Label must be a path relative to the workspace: $RelativePath"
    }

    $rootFull = [System.IO.Path]::GetFullPath($Root).TrimEnd([System.IO.Path]::DirectorySeparatorChar, [System.IO.Path]::AltDirectorySeparatorChar)
    $candidate = [System.IO.Path]::GetFullPath((Join-Path $rootFull $RelativePath))
    $rootPrefix = $rootFull + [System.IO.Path]::DirectorySeparatorChar
    if (-not $candidate.StartsWith($rootPrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "$Label must stay inside the workspace: $RelativePath"
    }
    return $candidate
}

function Write-Section {
    param([string]$Message)
    Write-Host ""
    Write-Host $Message -ForegroundColor Cyan
}

function Sync-MirrorItem {
    param([string]$Src, [string]$Dst, [int]$MaxRetries = 5)
    Initialize-Directory (Split-Path -Parent $Dst)

    if (Test-Path -LiteralPath $Dst) {
        for ($retry = 1; $retry -le $MaxRetries; $retry++) {
            try {
                Remove-Item -LiteralPath $Dst -Recurse -Force -ErrorAction Stop
                break
            }
            catch {
                if ($retry -eq $MaxRetries) {
                    throw "Failed to remove $Dst after $MaxRetries attempts: $_"
                }
                Write-Host "  [WARN] File locked while removing $Dst. Retrying ($retry/$MaxRetries)..." -ForegroundColor Yellow
                Start-Sleep -Milliseconds (500 * $retry)
            }
        }
    }

    for ($retry = 1; $retry -le $MaxRetries; $retry++) {
        try {
            Copy-Item -LiteralPath $Src -Destination $Dst -Recurse -Force -ErrorAction Stop
            break
        }
        catch {
            if ($retry -eq $MaxRetries) {
                throw "Failed to copy $Src to $Dst after $MaxRetries attempts: $_"
            }
            Write-Host "  [WARN] File locked while copying to $Dst. Retrying ($retry/$MaxRetries)..." -ForegroundColor Yellow
            Start-Sleep -Milliseconds (500 * $retry)
        }
    }
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
Assert-UpstreamRef -Value $Ref
Write-Host "[OK] All required commands found" -ForegroundColor Green
Write-Host ""

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$tempRoot = Resolve-WorkspaceChildPath -Root $repoRoot -RelativePath $TempDir -Label "TempDir"

try {
    Write-Host "Workspace configuration:" -ForegroundColor Cyan
    Write-Host "  Repo root:     $repoRoot"
    Write-Host "  Temp staging:  $tempRoot"
    Write-Host "  Upstream ref:  $Ref"
    Write-Host "  Upstream URL:  $UpstreamUrl"
    Write-Host ""

    # Clean temp directory
    if (Test-Path -LiteralPath $tempRoot) {
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

    Write-Host "[OK] Upstream checkout successful" -ForegroundColor Green
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
    Write-Host "  -> searx/"

    # Validate engines referenced in configuration files: if an upstream sync removed
    # an engine module, mark the corresponding engine entry as disabled to avoid
    # runtime module-not-found errors.
    # Check both the tracked template (config\settings.yml.example) and the local
    # config (config\settings.yml, if present).
    Write-Host "Validating engine modules referenced in configuration files..." -ForegroundColor Green
    $enginesDir = Join-Path $sitePackages "searx\engines"
    $pythonExe = Join-Path $repoRoot "python\python.exe"
    if (-not (Test-Path $pythonExe)) {
        $cmd = Get-Command "python" -ErrorAction SilentlyContinue
        if ($cmd) {
            $pythonExe = $cmd.Source
        }
    }
    $disableScript = Join-Path $repoRoot "tools\disable-missing-engines.py"
    $targetSettingsFiles = @(
        (Join-Path $repoRoot "config\settings.yml.example"),
        (Join-Path $repoRoot "config\settings.yml")
    )
    foreach ($cfgPath in $targetSettingsFiles) {
        if (Test-Path $cfgPath) {
            try {
                if (Test-Path $pythonExe) {
                    & $pythonExe $disableScript $cfgPath $enginesDir
                    if ($LASTEXITCODE -ne 0) {
                        throw "Engine validation failed for $cfgPath with exit code $LASTEXITCODE"
                    }
                } else {
                    throw "Python executable not found at: $pythonExe"
                }
            }
            catch {
                throw "Could not validate $cfgPath : $_"
            }
        }
    }

    $srcExtra = Join-Path $tempRoot "searxng_extra"
    if (Test-Path $srcExtra) {
        Sync-MirrorItem -Src $srcExtra -Dst (Join-Path $sitePackages "searxng_extra")
        Write-Host "  -> searxng_extra/"
    }

    # Track requirements changes for user notification
    $oldReqPath = Join-Path $repoRoot "config\requirements.upstream.txt"
    $oldReqHash = ""
    if (Test-Path $oldReqPath) {
        $oldReqHash = (Get-FileHash $oldReqPath).Hash
    }

    # Copy requirements and other metadata
    Write-Host "Syncing configuration files..." -ForegroundColor Green
    Copy-Item -LiteralPath (Join-Path $tempRoot "requirements.txt") $oldReqPath -Force
    Write-Host "  -> requirements.txt"

    if (Test-Path -LiteralPath (Join-Path $tempRoot "requirements-server.txt")) {
        Copy-Item -LiteralPath (Join-Path $tempRoot "requirements-server.txt") `
            (Join-Path $repoRoot "config\requirements-server.upstream.txt") -Force
    }
    Copy-Item -LiteralPath (Join-Path $tempRoot "setup.py") (Join-Path $repoRoot "config\setup.upstream.py") -Force
    Copy-Item -LiteralPath (Join-Path $tempRoot "README.rst") (Join-Path $repoRoot "config\README.upstream.rst") -Force

    # Alert user if requirements changed
    $newReqHash = (Get-FileHash $oldReqPath).Hash
    if ($oldReqHash -ne "" -and ($oldReqHash -ne $newReqHash)) {
        Write-Host ""
        Write-Host "[WARN] NOTICE: Upstream requirements.txt has changed!" -ForegroundColor Yellow
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
    Write-Host "[OK] Upstream synchronization complete!" -ForegroundColor Green
}
finally {
    if ($CleanTemp -and (Test-Path -LiteralPath $tempRoot)) {
        Write-Host "Cleaning temporary directory..." -ForegroundColor Gray
        try {
            Remove-Item -LiteralPath $tempRoot -Recurse -Force
        }
        catch {
            Write-Host "[WARN] Could not remove temp directory: $_" -ForegroundColor Yellow
        }
    }
}
