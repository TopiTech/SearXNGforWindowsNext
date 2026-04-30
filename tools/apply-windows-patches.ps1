$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path

# --- Helper function for patching ---
function Update-Patch {
    param(
        [string]$FilePath,
        [string]$Description,
        [scriptblock]$PatchLogic
    )

    if (-not (Test-Path $FilePath)) {
        Write-Host "Warning: File not found, skipping ${Description}: ${FilePath}" -ForegroundColor Yellow
        return
    }

    $content = Get-Content $FilePath -Raw -Encoding UTF8
    $newContent = &$PatchLogic $content

    if ($content -eq $newContent) {
        Write-Host "No changes needed for ${Description}." -ForegroundColor Gray
    } else {
        Set-Content $FilePath -Value $newContent -Encoding UTF8
        Write-Host "Patched ${Description}: ${FilePath}" -ForegroundColor Green
    }
}

# --- 1. valkeydb.py (Windows compatibility) ---
Update-Patch -FilePath (Join-Path $repoRoot "python\Lib\site-packages\searx\valkeydb.py") -Description "valkeydb.py (pwd removal)" -PatchLogic {
    param($c)
    if ($c -match 'def _windows_safe_current_user\(') { return $c }
    
    # Replace "import pwd" with try/except block
    $c = $c -replace '(?<=^|\r?\n)import pwd(?=\r?\n|$)', "try:`n    import pwd  # Unix only`nexcept ImportError:`n    pwd = None"
    
    $helper = @"

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
    $c = $c -replace '(logger = logging\.getLogger\(__name__\))', "`$1$helper"
    $c = $c -replace '_pw = pwd\.getpwuid\(os\.getuid\(\)\)', '_user_name, _user_uid = _windows_safe_current_user()'
    $c = $c -replace '_pw\.pw_name, _pw\.pw_uid', '_user_name, _user_uid'
    return $c
}

# --- 2. settings_defaults.py (Add json_lite format) ---
Update-Patch -FilePath (Join-Path $repoRoot "python\Lib\site-packages\searx\settings_defaults.py") -Description "settings_defaults.py (json_lite format)" -PatchLogic {
    param($c)
    if ($c -match "'json_lite'") { return $c }
    $c = $c -replace "OUTPUT_FORMATS = \['html', 'csv', 'json', 'rss'\]", "OUTPUT_FORMATS = ['html', 'csv', 'json', 'rss', 'json_lite']"
    return $c
}

# --- 3. webutils.py (Add get_json_lite_response) ---
Update-Patch -FilePath (Join-Path $repoRoot "python\Lib\site-packages\searx\webutils.py") -Description "webutils.py (get_json_lite_response)" -PatchLogic {
    param($c)
    if ($c -match "def get_json_lite_response") { return $c }
    
    $liteFunc = @"

def get_json_lite_response(sq: "SearchQuery", rc: "ResultContainer") -> str:
    """Returns a simplified JSON string (GenAI friendly)"""
    data = {
        'query': sq.query,
        'results': [
            {
                'title': _.title,
                'url': _.url,
                'content': _.content
            } for _ in rc.get_ordered_results()
        ]
    }
    return json.dumps(data, cls=JSONEncoder)

"@
    # Insert before get_themes
    $c = $c -replace '(def get_themes)', "$liteFunc`$1"
    return $c
}

# --- 4. webapp.py (Handle json_lite in search) ---
Update-Patch -FilePath (Join-Path $repoRoot "python\Lib\site-packages\searx\webapp.py") -Description "webapp.py (json_lite handler)" -PatchLogic {
    param($c)
    # Use embedded Python for robust indentation handling
    $pyCode = @"
import sys, re
path = sys.argv[1]
with open(path, 'r', encoding='utf-8') as f: content = f.read()
modified = False
if \"if output_format in ('json', 'json_lite'):\" not in content:
    content = re.sub(r\"(?m)^(def index_error\(.*?\):\r?\n)(\s+)if output_format == 'json':\", r\"\\1\\2if output_format in ('json', 'json_lite'):\", content)
    modified = True
if \"output_format == 'json_lite'\" not in content:
    handler = \"\\n\\n    if output_format == 'json_lite':\\n        response = webutils.get_json_lite_response(search_query, result_container)\\n        return Response(response, mimetype='application/json')\\n\"
    content = re.sub(r\"(# 3\. formats without a template\r?\n)\", r\"\\1\" + handler, content)
    modified = True
if modified:
    with open(path, 'w', encoding='utf-8', newline='\n') as f: f.write(content)
"@
    $tmpPy = Join-Path $env:TEMP "patch_webapp.py"
    $pyCode | Out-File -FilePath $tmpPy -Encoding utf8
    & ".\python\python.exe" $tmpPy (Join-Path $repoRoot "python\Lib\site-packages\searx\webapp.py")
    Remove-Item $tmpPy
    return (Get-Content -Path (Join-Path $repoRoot "python\Lib\site-packages\searx\webapp.py") -Raw)
}

Write-Host "All Windows patches applied successfully." -ForegroundColor Green
