$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$valkeydb = Join-Path $repoRoot "python\Lib\site-packages\searx\valkeydb.py"

if (-not (Test-Path $valkeydb)) {
    throw "File not found: $valkeydb"
}

$content = Get-Content $valkeydb -Raw -Encoding UTF8

# Check if already patched by looking for the helper function
if ($content -match 'def _windows_safe_current_user\(') {
    Write-Host "valkeydb.py already patched. Skipping." -ForegroundColor Yellow
    exit 0
}

Write-Host "Patching valkeydb.py for Windows compatibility..." -ForegroundColor Cyan

# Step 1: Replace "import pwd" with try/except block
$content = $content -replace '(?<=^|\r?\n)import pwd(?=\r?\n|$)', "try:`n    import pwd  # Unix only`nexcept ImportError:`n    pwd = None"

# Step 2: Add helper function after logger definition
$helperFunction = @"

def _windows_safe_current_user():
    if pwd is not None and hasattr(os, "getuid"):
        try:
            _pw = pwd.getpwuid(os.getuid())
            return _pw.pw_name, _pw.pw_uid
        except Exception:
            pass

    username = (
        os.environ.get("USERNAME")
        or os.environ.get("USER")
        or os.environ.get("LOGNAME")
        or "windows"
    )
    return username, -1

"@

# Insert helper function after "logger = logging.getLogger(__name__)"
$content = $content -replace (
    '(logger = logging\.getLogger\(__name__\))',
    "`$1$helperFunction"
)

# Step 3: Replace pwd.getpwuid call with helper function call
$content = $content -replace '_pw = pwd\.getpwuid\(os\.getuid\(\)\)', '_user_name, _user_uid = _windows_safe_current_user()'

# Step 4: Replace _pw.pw_name, _pw.pw_uid with _user_name, _user_uid
$content = $content -replace '_pw\.pw_name, _pw\.pw_uid', '_user_name, _user_uid'

Set-Content $valkeydb -Value $content -Encoding UTF8

Write-Host "Patched: $valkeydb" -ForegroundColor Green
Write-Host "  - import pwd wrapped in try/except" -ForegroundColor DarkGray
Write-Host "  - _windows_safe_current_user() helper added" -ForegroundColor DarkGray
Write-Host "  - pwd.getpwuid call replaced with helper" -ForegroundColor DarkGray
Write-Host "  - logger.exception updated" -ForegroundColor DarkGray
