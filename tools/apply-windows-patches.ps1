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

    if ($newContent -eq "ALREADY_APPLIED") {
        Write-Host "Already applied ${Description}." -ForegroundColor Gray
    } elseif ($content -eq $newContent) {
        throw "Patch failed for ${Description}: Upstream code may have changed, could not find injection point."
    } else {
        Set-Content $FilePath -Value $newContent -Encoding UTF8
        Write-Host "Patched ${Description}: ${FilePath}" -ForegroundColor Green
    }
}

# --- 1. valkeydb.py (Windows compatibility) ---
Update-Patch -FilePath (Join-Path $repoRoot "python\Lib\site-packages\searx\valkeydb.py") -Description "valkeydb.py (pwd removal)" -PatchLogic {
    param($c)
    $pyCode = @"
import sys, re
path = sys.argv[1]
with open(path, 'r', encoding='utf-8') as f: content = f.read()

if 'def _windows_safe_current_user():' in content and '_user_name, _user_uid = _windows_safe_current_user()' in content:
    if '_pw = pwd.getpwuid(os.getuid())' in content.split('def _windows_safe_current_user():')[1].split('return')[0]:
        print("ALREADY_APPLIED")
        sys.exit(0)

# 1. Replace import pwd
content = re.sub(r'^import pwd$', "try:\n    import pwd  # Unix only\nexcept ImportError:\n    pwd = None", content, flags=re.M)

# 2. Add or fix helper function after logger definition
helper = """
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
"""

if 'def _windows_safe_current_user():' in content:
    # Overwrite existing helper to ensure it's not recursive
    content = re.sub(r'def _windows_safe_current_user\(\):.*?return username, -1', helper.strip(), content, flags=re.S)
else:
    content = re.sub(r'(logger = logging\.getLogger\(__name__\))', r'\1' + helper, content)

# 3. Replace the actual call OUTSIDE the helper function
# Original: _pw = pwd.getpwuid(os.getuid())
# We want to replace it only if it's not inside the _windows_safe_current_user definition.

def replace_call(match):
    indent = match.group(1)
    # If it's preceded by more than 4 spaces (inside helper), don't touch it
    if indent.count(' ') > 4:
        return match.group(0)
    return indent + '_user_name, _user_uid = _windows_safe_current_user()'

content = re.sub(r'^(\s+)_pw = pwd\.getpwuid\(os\.getuid\(\)\)', replace_call, content, flags=re.M)

# Replace usage only in the same scope (non-indented or standard indentation in initialize())
def replace_usage(match):
    indent = match.group(1)
    if indent.count(' ') > 4:
        return match.group(0)
    return indent + 'logger.exception("[%s (%s)] can\'t connect valkey DB ...", _user_name, _user_uid)'

content = re.sub(r'^(\s+)logger\.exception\("\[%s \(%s\)\] can\'t connect valkey DB \.\.\.", _pw\.pw_name, _pw\.pw_uid\)', replace_usage, content, flags=re.M)

with open(path, 'w', encoding='utf-8', newline='\n') as f: f.write(content)
print("PATCHED")
"@
    $tmpPy = Join-Path $env:TEMP "patch_valkeydb.py"
    $pyCode | Out-File -FilePath $tmpPy -Encoding utf8
    $output = & ".\python\python.exe" $tmpPy (Join-Path $repoRoot "python\Lib\site-packages\searx\valkeydb.py")
    Remove-Item $tmpPy

    if ($output -contains "ALREADY_APPLIED") {
        return "ALREADY_APPLIED"
    } else {
        return (Get-Content -Path (Join-Path $repoRoot "python\Lib\site-packages\searx\valkeydb.py") -Raw)
    }
}

# --- 2. settings_defaults.py (Add json_lite format) ---
Update-Patch -FilePath (Join-Path $repoRoot "python\Lib\site-packages\searx\settings_defaults.py") -Description "settings_defaults.py (json_lite format)" -PatchLogic {
    param($c)
    if ($c -match "'json_lite'") { return "ALREADY_APPLIED" }
    $c = $c -replace "OUTPUT_FORMATS = \['html', 'csv', 'json', 'rss'\]", "OUTPUT_FORMATS = ['html', 'csv', 'json', 'rss', 'json_lite']"
    return $c
}

# --- 3. webutils.py (Add get_json_lite_response) ---
Update-Patch -FilePath (Join-Path $repoRoot "python\Lib\site-packages\searx\webutils.py") -Description "webutils.py (get_json_lite_response)" -PatchLogic {
    param($c)
    if ($c -match "def get_json_lite_response") { return "ALREADY_APPLIED" }
    
    $liteFunc = @"

def get_json_lite_response(sq: "SearchQuery", rc: "ResultContainer") -> str:
    """Returns a simplified JSON string (GenAI friendly)"""
    data = {
        'query': sq.query,
        'results': [
            {
                'title': _.title,
                'url': _.url,
                'content': _.content,
                'source': _.engine
            } for _ in rc.get_ordered_results()
        ]
    }
    if rc.answers:
        data['answers'] = [a.as_dict().get('answer') for a in rc.answers]
    if rc.infoboxes:
        data['infoboxes'] = [
            {
                'infobox': getattr(i, 'infobox', ''),
                'content': getattr(i, 'content', ''),
                'urls': [{'title': u.get('title'), 'url': u.get('url')} for u in getattr(i, 'urls', [])]
            } for i in rc.infoboxes
        ]
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

already_1 = "if output_format in ('json', 'json_lite'):" in content
already_2 = "output_format == 'json_lite'" in content

if already_1 and already_2:
    print("ALREADY_APPLIED")
    sys.exit(0)

modified = False
if not already_1:
    new_content, count = re.subn(r"(?m)^(def index_error\(.*?\):\r?\n)(\s+)if output_format == 'json':", r"\1\2if output_format in ('json', 'json_lite'):", content)
    if count == 0:
        print("ERROR: index_error replacement failed")
        sys.exit(1)
    content = new_content
    modified = True

if not already_2:
    handler = "\n\n    if output_format == 'json_lite':\n        response = webutils.get_json_lite_response(search_query, result_container)\n        return Response(response, mimetype='application/json')\n"
    new_content, count = re.subn(r"(# 3\. formats without a template\r?\n)", r"\1" + handler, content)
    if count == 0:
        print("ERROR: formats without template replacement failed")
        sys.exit(1)
    content = new_content
    modified = True

if modified:
    with open(path, 'w', encoding='utf-8', newline='\n') as f: f.write(content)
print("PATCHED")
"@
    $tmpPy = Join-Path $env:TEMP "patch_webapp.py"
    $pyCode | Out-File -FilePath $tmpPy -Encoding utf8
    $output = & ".\python\python.exe" $tmpPy (Join-Path $repoRoot "python\Lib\site-packages\searx\webapp.py")
    Remove-Item $tmpPy
    
    if ($output -contains "ERROR: index_error replacement failed" -or $output -contains "ERROR: formats without template replacement failed") {
        throw "webapp.py patch failed: Upstream code changed and injection point was not found."
    } elseif ($output -contains "ALREADY_APPLIED") {
        return "ALREADY_APPLIED"
    } else {
        return (Get-Content -Path (Join-Path $repoRoot "python\Lib\site-packages\searx\webapp.py") -Raw)
    }
}

Write-Host "All Windows patches applied successfully." -ForegroundColor Green
