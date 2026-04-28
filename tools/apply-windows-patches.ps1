$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$valkeydb = Join-Path $repoRoot "python\Lib\site-packages\searx\valkeydb.py"

if (-not (Test-Path $valkeydb)) {
    throw "File not found: $valkeydb"
}

$lines = Get-Content $valkeydb -Encoding UTF8
$alreadyPatched = ($lines -match 'def _windows_safe_current_user\(').Count -gt 0

if ($alreadyPatched) {
    Write-Host "valkeydb.py already patched. Skipping." -ForegroundColor Yellow
    exit 0
}

$helperLines = @(
    "def _windows_safe_current_user():"
    "    if pwd is not None and hasattr(os, ""getuid""):"
    "        try:"
    "            _pw = pwd.getpwuid(os.getuid())"
    "            return _pw.pw_name, _pw.pw_uid"
    "        except Exception:"
    "            pass"
    ""
    "    username = ("
    "        os.environ.get(""USERNAME"")"
    "        or os.environ.get(""USER"")"
    "        or os.environ.get(""LOGNAME"")"
    "        or ""windows"""
    "    )"
    "    return username, -1"
    ""
)

$out = New-Object System.Collections.Generic.List[string]
$insertedHelper = $false
$patchedImport = $false
$patchedUserLookup = $false
$patchedLogger = $false

foreach ($line in $lines) {
    $trimmed = $line.Trim()

    # 1) import pwd を Windows-safe に置換
    if ($trimmed -eq "import pwd") {
        $out.Add("try:")
        $out.Add("    import pwd  # Unix only")
        $out.Add("except ImportError:")
        $out.Add("    pwd = None")
        $patchedImport = $true
        continue
    }

    # 2) logger 定義の直後に helper を挿入
    $out.Add($line)

    if (-not $insertedHelper -and $trimmed -eq "logger = logging.getLogger(__name__)") {
        $out.Add("")
        foreach ($h in $helperLines) {
            $out.Add($h)
        }
        $insertedHelper = $true
        continue
    }
}

# 3) 置換をもう一段やるために文字列化
$content = ($out -join "`r`n")

# 3-a) _pw = pwd.getpwuid(os.getuid()) を Windows-safe 関数に置換
if ($content -match [regex]::Escape('_pw = pwd.getpwuid(os.getuid())')) {
    $content = $content.Replace(
        '_pw = pwd.getpwuid(os.getuid())',
        '_user_name, _user_uid = _windows_safe_current_user()'
    )
    $patchedUserLookup = $true
}

# 3-b) logger.exception(... _pw.pw_name, _pw.pw_uid) を置換
$oldLoggerLine = 'logger.exception(" [%s (%s)] can''t connect valkey DB ...", _pw.pw_name, _pw.pw_uid)'
$newLoggerLine = 'logger.exception(" [%s (%s)] can''t connect valkey DB ...", _user_name, _user_uid)'

if ($content -match [regex]::Escape($oldLoggerLine)) {
    $content = $content.Replace($oldLoggerLine, $newLoggerLine)
    $patchedLogger = $true
}

Set-Content $valkeydb -Value $content -Encoding UTF8

Write-Host "Patched: $valkeydb" -ForegroundColor Green
Write-Host ("  import pwd patched      : " + $patchedImport) -ForegroundColor DarkGray
Write-Host ("  helper inserted         : " + $insertedHelper) -ForegroundColor DarkGray
Write-Host ("  user lookup patched     : " + $patchedUserLookup) -ForegroundColor DarkGray
Write-Host ("  logger.exception patched: " + $patchedLogger) -ForegroundColor DarkGray