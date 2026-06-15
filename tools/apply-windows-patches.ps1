$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path

function Write-PatchSection {
    param([string]$Message)
    Write-Host ""
    Write-Host $Message -ForegroundColor Cyan
}

function Assert-RequiredFile {
    param(
        [string]$FilePath,
        [string]$Description
    )
    if (-not (Test-Path -LiteralPath $FilePath)) {
        throw "Required file not found for ${Description}: ${FilePath}"
    }
}

# --- Helper: Apply a patch with robust error handling and status reporting ---
function Update-Patch {
    param(
        [string]$FilePath,
        [string]$Description,
        [scriptblock]$PatchLogic,
        [switch]$Required,
        [switch]$InPlace
    )

    if (-not (Test-Path -LiteralPath $FilePath)) {
        if ($Required) {
            throw "Required file not found for ${Description}: ${FilePath}"
        }
        Write-Host "⚠  File not found, skipping ${Description}: ${FilePath}" -ForegroundColor Yellow
        return
    }

    $content = Get-Content -LiteralPath $FilePath -Raw -Encoding UTF8
    $patchResult = &$PatchLogic $content

    if ($InPlace) {
        if ($patchResult -eq "ALREADY_APPLIED") {
            Write-Host "✓ Already applied: ${Description}" -ForegroundColor Gray
            return "ALREADY_APPLIED"
        }
        if ($patchResult -eq "PATCHED") {
            Write-Host "✓ Patched: ${Description}" -ForegroundColor Green
            return "PATCHED"
        }
        throw "Patch returned unexpected result for ${Description}: ${patchResult}"
    }

    $newContent = $patchResult

    if ($newContent -eq "ALREADY_APPLIED") {
        Write-Host "✓ Already applied: ${Description}" -ForegroundColor Gray
        return "ALREADY_APPLIED"
    }
    elseif ($content -eq $newContent) {
        throw "✗ Patch failed for ${Description}: Upstream code may have changed, could not find injection point (check UPSTREAM_VERSION.txt)."
    }
    else {
        Set-Content -LiteralPath $FilePath -Value $newContent -Encoding UTF8
        Write-Host "✓ Patched: ${Description}" -ForegroundColor Green
        return "PATCHED"
    }
}

# --- Helper: Assert that a pattern exists in a file (pre-flight check) ---
function Assert-Anchor {
    param(
        [string]$FilePath,
        [string]$Pattern,
        [string]$Description
    )
    $content = Get-Content -LiteralPath $FilePath -Raw -Encoding UTF8
    if ($content -notmatch $Pattern) {
        throw "✗ Anchor not found for ${Description} in ${FilePath}. Upstream code may have changed."
    }
}

# --- Helper: Execute Python patch script with error detection and cleanup ---
function Invoke-PythonPatch {
    param(
        [string]$PythonCode,
        [string]$TempName,
        [string]$TargetFile
    )
    $tmpPy = Join-Path ([System.IO.Path]::GetTempPath()) $TempName
    try {
        # Use explicit .NET API to write BOM-less UTF-8 to avoid encoding mismatches in Python.
        [System.IO.File]::WriteAllText($tmpPy, $PythonCode, (New-Object System.Text.UTF8Encoding($false)))
        $pythonExe = Join-Path $repoRoot "python\python.exe"
        if (-not (Test-Path -LiteralPath $pythonExe)) {
            throw "Embedded Python not found at: $pythonExe"
        }

        $output = & $pythonExe $tmpPy $TargetFile 2>&1
        $result = ($output | Out-String).Trim()

        # Monitor both non-zero exit codes and script-emitted ERROR messages.
        if ($LASTEXITCODE -ne 0 -or $result -match "(?m)^ERROR:") {
            throw "Python patch script failed (Exit Code: $LASTEXITCODE): $result"
        }
        return $result
    }
    finally {
        if (Test-Path -LiteralPath $tmpPy) { Remove-Item -LiteralPath $tmpPy -Force -ErrorAction SilentlyContinue }
    }
}


# --- 1. valkeydb.py (Windows compatibility: pwd → os.environ fallback) ---
Update-Patch `
    -FilePath    (Join-Path $repoRoot "python\Lib\site-packages\searx\valkeydb.py") `
    -Description "valkeydb.py (Windows pwd compatibility)" `
    -Required `
    -InPlace `
    -PatchLogic  {
    param($c)
    $pyCode = @'
import sys, re
path = sys.argv[1]
with open(path, 'r', encoding='utf-8') as f:
    content = f.read()

# Idempotency check: if both marker present, already applied
if ('def _windows_safe_current_user():' in content
        and '_user_name, _user_uid = _windows_safe_current_user()' in content):
    print("ALREADY_APPLIED")
    sys.exit(0)

# 1. Wrap Unix-only `import pwd` in try/except
content = re.sub(
    r'^import pwd$',
    "try:\n    import pwd  # Unix only\nexcept ImportError:\n    pwd = None",
    content, flags=re.M
)

# 2. Inject Windows fallback function after logger (PEP 8: 2 blank lines)
helper = '''


def _windows_safe_current_user():
    """Get current user safely on Windows (where pwd module is unavailable)."""
    if pwd is not None and hasattr(os, "getuid"):
        try:
            _pw = pwd.getpwuid(os.getuid())
            return _pw.pw_name, _pw.pw_uid
        except Exception:
            pass
    # Windows fallback
    username = (
        os.environ.get("USERNAME")
        or os.environ.get("USER")
        or os.environ.get("LOGNAME")
        or "windows"
    )
    return username, -1
'''

if 'def _windows_safe_current_user():' in content:
    content = re.sub(
        r'\n{1,3}def _windows_safe_current_user\(\):.*?return username, -1',
        helper.rstrip(), content, flags=re.S
    )
else:
    content = re.sub(
        r'(logger = logging\.getLogger\(__name__\))',
        r'\1' + helper, content
    )

# 3. Replace call-site (indent-aware, exclude nested blocks)
content = re.sub(
    r'^(\s{1,8})_pw = pwd\.getpwuid\(os\.getuid\(\)\)',
    r'\1_user_name, _user_uid = _windows_safe_current_user()',
    content, flags=re.M
)

# 4. Update logger.exception call with new variables
content = re.sub(
    r'^(\s{1,8})logger\.exception\(".*?can\'t connect valkey DB \.\.\..*?\)',
    r'\1logger.exception("[%s (%s)] can\'t connect valkey DB ...", _user_name, _user_uid)',
    content, flags=re.M
)

with open(path, 'w', encoding='utf-8', newline='\n') as f:
    f.write(content)
print("PATCHED")
'@
    $output = Invoke-PythonPatch -PythonCode $pyCode -TempName "patch_valkeydb.py" `
        -TargetFile (Join-Path $repoRoot "python\Lib\site-packages\searx\valkeydb.py")

    if ($output -match "ALREADY_APPLIED") { return "ALREADY_APPLIED" }
    return "PATCHED"
}


# --- 2. settings_defaults.py (register json_lite output format) ---
Update-Patch `
    -FilePath    (Join-Path $repoRoot "python\Lib\site-packages\searx\settings_defaults.py") `
    -Description "settings_defaults.py (json_lite format)" `
    -Required `
    -InPlace `
    -PatchLogic  {
    param($c)
    $pyCode = @'
import sys, re
path = sys.argv[1]
with open(path, 'r', encoding='utf-8') as f:
    content = f.read()

if "'json_lite'" in content:
    print("ALREADY_APPLIED")
    sys.exit(0)

match = re.search(r"(?ms)(OUTPUT_FORMATS\s*=\s*\[)(.*?)(\])", content)
if not match:
    print("ERROR: OUTPUT_FORMATS patch failed (anchor not found)")
    sys.exit(1)

body = match.group(2)
if re.search(r"(?m)^\s*['\"]json_lite['\"]\s*,?\s*$", body):
    print("ALREADY_APPLIED")
    sys.exit(0)

if re.search(r"(?m)^\s*['\"]json['\"]\s*,?\s*$", body):
    body = body.rstrip()
    if not body.endswith(","):
        body += ","
    body += "\n    'json_lite'"
else:
    body = body.rstrip() + ", 'json_lite'"

content = content[:match.start()] + match.group(1) + body + match.group(3) + content[match.end():]
with open(path, 'w', encoding='utf-8', newline='\n') as f:
    f.write(content)
print("PATCHED")
'@
    $output = Invoke-PythonPatch -PythonCode $pyCode -TempName "patch_settings_defaults_json_lite.py" `
        -TargetFile (Join-Path $repoRoot "python\Lib\site-packages\searx\settings_defaults.py")

    if ($output -match "ALREADY_APPLIED") { return "ALREADY_APPLIED" }
    return "PATCHED"
}


# --- 3. webutils.py (add get_json_lite_response, optimised) ---
Update-Patch `
    -FilePath    (Join-Path $repoRoot "python\Lib\site-packages\searx\webutils.py") `
    -Description "webutils.py (get_json_lite_response)" `
    -PatchLogic  {
    param($c)
    # Check for presence and latest version (including score field in _r)
    if ($c -match "def get_json_lite_response" -and $c -match "'score': d\.get\('score', 0\)") { return "ALREADY_APPLIED" }

    $liteFunc = @'


def get_json_lite_response(sq: "SearchQuery", rc: "ResultContainer") -> str:
    """Returns a simplified JSON string (GenAI friendly)."""
    def _r(res):
        d = res.as_dict()
        return {
            'title': d.get('title', ''),
            'url': d.get('url', ''),
            'content': d.get('content', ''),
            'source': d.get('engine', ''),
            'score': d.get('score', 0),
            'published_date': d.get('pubdate') or d.get('publishedDate'),
            'author': d.get('author', ''),
            'category': d.get('category', ''),
        }
    data = {
        'query': sq.query,
        'results': [_r(r) for r in rc.get_ordered_results()[:20]],
        'suggestions': list(rc.suggestions),
        'corrections': list(rc.corrections),
    }
    if rc.answers:
        data['answers'] = [a.as_dict().get('answer') for a in rc.answers]
    if rc.infoboxes:
        data['infoboxes'] = [
            {
                'infobox': getattr(i, 'infobox', ''),
                'content': getattr(i, 'content', ''),
                'urls': [{'title': u.get('title'), 'url': u.get('url')}
                         for u in getattr(i, 'urls', [])],
            }
            for i in rc.infoboxes
        ]
    return json.dumps(data, cls=JSONEncoder)


'@
    # If old version exists, remove it first
    if ($c -match "def get_json_lite_response") {
        $c = $c -replace '(?s)\n+def get_json_lite_response.*?return json\.dumps\(data, cls=JSONEncoder\)\n+', "`n"
    }

    # Insert before get_themes while preserving a single blank-line boundary.
    $c = $c -replace '(\n)(def get_themes\b)', "$liteFunc`$1`$2"
    return $c
}


# --- 4. webapp.py (json_lite handler + ipaddress import at module level) ---
Update-Patch `
    -FilePath    (Join-Path $repoRoot "python\Lib\site-packages\searx\webapp.py") `
    -Description "webapp.py (json_lite handler + ipaddress import)" `
    -Required `
    -InPlace `
    -PatchLogic  {
    param($c)
    $pyCode = @'
import sys, re
path = sys.argv[1]
with open(path, 'r', encoding='utf-8') as f:
    content = f.read()

# Idempotency: all 3 changes already in place?
checks = [
    "output_format in ('json', 'json_lite')" in content,
    "output_format == 'json_lite'" in content,
    bool(re.search(r'^import ipaddress', content, re.M))
]

if all(checks):
    print("ALREADY_APPLIED")
    sys.exit(0)

# 1. Widen index_error() to handle json_lite (include in json error path)
if "output_format in ('json', 'json_lite')" not in content:
    content, n = re.subn(
        r"(def index_error\b.*?\n\s+)if output_format == 'json':",
        r"\1if output_format in ('json', 'json_lite'):",
        content, flags=re.S
    )
    if n == 0:
        print("ERROR: index_error patch failed (anchor not found)")
        sys.exit(1)

# 2. Add top-level `import ipaddress` (remove any indented duplicates first)
if not re.search(r'^import ipaddress', content, re.M):
    content = re.sub(r'^\s+import ipaddress\n', '', content, flags=re.M)

    # Try to anchor after warnings
    subs = re.subn(r'(import warnings\n)', r'\1import ipaddress\n', content)
    if subs[1] == 0:
        subs = re.subn(r'(import httpx\n)', r'import ipaddress\n\1', content)

    if subs[1] == 0:
        print("ERROR: ipaddress import patch failed (no anchor points)")
        sys.exit(1)
    content = subs[0]

# 3. Inject json_lite handler before json handler (stable anchor point)
if "output_format == 'json_lite'" not in content:
    handler = (
        "\n    if output_format == 'json_lite':\n"
        "        response = webutils.get_json_lite_response(search_query, result_container)\n"
        "        return Response(response, mimetype='application/json')\n\n"
    )
    subs = re.subn(
        r"(?m)^(    if output_format == 'json':\n\n        response = webutils\.get_json_response)",
        handler + r"    if output_format == 'json':\n\n        response = webutils.get_json_response",
        content
    )
    if subs[1] == 0:
        subs = re.subn(r"(# 3\. formats without a template\r?\n)", r"\1" + handler, content)

    if subs[1] == 0:
        print("ERROR: json_lite handler patch failed (inject point not found)")
        sys.exit(1)
    content = subs[0]

with open(path, 'w', encoding='utf-8', newline='\n') as f:
    f.write(content)
print("PATCHED")
'@
    $output = Invoke-PythonPatch -PythonCode $pyCode -TempName "patch_webapp_json.py" `
        -TargetFile (Join-Path $repoRoot "python\Lib\site-packages\searx\webapp.py")

    if ($output -match "ALREADY_APPLIED") { return "ALREADY_APPLIED" }
    return "PATCHED"
}


# --- 5. webapp.py (/scrape route + trafilatura import for GenAI workflows) ---
Update-Patch `
    -FilePath    (Join-Path $repoRoot "python\Lib\site-packages\searx\webapp.py") `
    -Description "webapp.py (/scrape endpoint, SSRF-protected)" `
    -Required `
    -InPlace `
    -PatchLogic  {
    param($c)
    if ($c -match "def scrape\(\)" -and $c -match "request_url = redirected_url" -and $c -match "_is_blocked_scrape_host") {
        return "ALREADY_APPLIED"
    }

    $pyCode = @'
import sys, re
path = sys.argv[1]
with open(path, 'r', encoding='utf-8') as f:
    content = f.read()

# 1. Add `import trafilatura` module-level (before flask)
if 'import trafilatura' not in content:
    subs = re.subn(r'(import flask\b)', r'import trafilatura\n\1', content)
    if subs[1] == 0:
        print("ERROR: trafilatura import patch failed (flask anchor not found)")
        sys.exit(1)
    content = subs[0]

# 2. Clean stale /scrape route (idempotency).
#    The lookahead handles both old compact routes and the current blank-line style.
content = re.sub(
    r'\n@app\.route\(\'/scrape\'[^\n]*\)\ndef scrape\(\):.*?(?=\n\n@app\.route|\n@app\.route|\Z)',
    '\n', content, flags=re.S
)

# 3. Insert /scrape route before /search (most stable anchor point)
#    SECURITY: SSRF protection via ipaddress library and redirect validation.
scrape_route = '''

@app.route('/scrape', methods=['GET', 'POST'])
def scrape():
    """Extract main text content from URL (GenAI friendly, SSRF-protected).

    SECURITY: Blocks loopback, private/reserved IP ranges, link-local, and
    file:// scheme to prevent SSRF attacks and internal resource exposure.

    NOTE: SSL verification is disabled by default (safe for localhost-only deployment).
    Set SEARXNG_SCRAPE_VERIFY_SSL=true for internet-facing deployments.
    """
    url = sxng_request.values.get('url')
    if not url and sxng_request.is_json and sxng_request.json:
        url = sxng_request.json.get('url')
    if not url:
        return jsonify({'error': 'No URL provided'}), 400

    def _is_blocked_scrape_host(host):
        import socket
        host = (host or '').strip().rstrip('.').lower()
        if not host or host == 'localhost' or host.endswith('.localhost'):
            return True
        if '%' in host:
            host = host.split('%', 1)[0]
        try:
            ip = ipaddress.ip_address(host)
            if not ip.is_global:
                return True
        except ValueError:
            pass

        try:
            for res in socket.getaddrinfo(host, None):
                if not ipaddress.ip_address(res[4][0]).is_global:
                    return True
        except socket.gaierror:
            pass
        return False

    def _fetch_scrape_url(request_url):
        verify_ssl = os.environ.get('SEARXNG_SCRAPE_VERIFY_SSL', 'false').lower() in ('true', '1', 'yes')
        ua = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
              'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')

        with httpx.Client(timeout=10.0, follow_redirects=False,
                          verify=verify_ssl, headers={'User-Agent': ua}) as client:
            response = client.get(request_url)
            for _ in range(5):
                if response.status_code not in (301, 302, 303, 307, 308):
                    break
                location = response.headers.get('location')
                if not location:
                    break
                redirected_url = urllib.parse.urljoin(request_url, location)
                request_url = redirected_url
                redirected_host = urllib.parse.urlparse(redirected_url).hostname
                if _is_blocked_scrape_host(redirected_host):
                    raise RuntimeError('Blocked redirect to private/reserved host')
                response = client.get(redirected_url)
            else:
                raise RuntimeError('Too many redirects')

            response.raise_for_status()
            return response.text

    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ('http', 'https') or _is_blocked_scrape_host(parsed.hostname):
        return jsonify({'error': 'Invalid or blocked URL'}), 400

    try:
        downloaded = _fetch_scrape_url(url)

        # Extract content with sanitization (no scripts/comments).
        content_text = trafilatura.extract(
            downloaded, include_comments=False, include_tables=True
        )
        if not content_text:
            return jsonify({'error': 'Could not extract content'}), 422

        return jsonify({'url': url, 'content': content_text})
    except httpx.HTTPError as e:
        # Truncate error message (prevent info leakage).
        return jsonify({'error': f'Fetch failed: {str(e)[:100]}'}), 502
    except Exception as e:
        # Truncate error message (prevent info leakage).
        return jsonify({'error': f'Fetch failed: {str(e)[:100]}'}), 500

'''

subs = re.subn(r"(@app\.route\('/search')", scrape_route + r'\1', content)
if subs[1] == 0:
    print("ERROR: scrape route injection failed (search route anchor not found)")
    sys.exit(1)
content = subs[0]

with open(path, 'w', encoding='utf-8', newline='\n') as f:
    f.write(content)
print("PATCHED")
'@
    $output = Invoke-PythonPatch -PythonCode $pyCode -TempName "patch_webapp_scrape.py" `
        -TargetFile (Join-Path $repoRoot "python\Lib\site-packages\searx\webapp.py")

    if ($output -match "ALREADY_APPLIED") { return "ALREADY_APPLIED" }
    return "PATCHED"
}


# --- 6. engines/__init__.py (check disabled flag BEFORE loading module) ---
Update-Patch `
    -FilePath    (Join-Path $repoRoot "python\Lib\site-packages\searx\engines\__init__.py") `
    -Description "engines/__init__.py (check disabled before module load)" `
    -Required `
    -InPlace `
    -PatchLogic  {
    param($c)
    # Idempotency check: look for our debug message
    if ($c -match "skipping load'|inactive or disabled in config!") {
        return "ALREADY_APPLIED"
    }

    $pyCode = @'
import sys, re
path = sys.argv[1]
with open(path, 'r', encoding='utf-8') as f:
    content = f.read()

# 1. Patch load_engine (singular) - add early return for disabled/inactive
# Check if already patched
if "is disabled in config, skipping load" not in content:
    inject_code = """
    # Early return for engines that are intentionally disabled or inactive in config.
    if engine_data.get('inactive') is True:
        logger.debug('Engine "%s" is inactive in config, skipping load', engine_name)
        return None
    if engine_data.get('disabled') is True:
        logger.debug('Engine "%s" is disabled in config, skipping load', engine_name)
        return None
"""
    # Anchor: after the engine name lowercase conversion
    pattern = r"(if engine_name\.lower\(\) != engine_name:.*?engine_data\['name'\] = engine_name\n)"
    content, count = re.subn(pattern, r"\1" + inject_code, content, flags=re.S)
    if count == 0:
        print("ERROR: Could not find anchor in load_engine (singular)")
        sys.exit(1)

# 2. Patch load_engines (plural) - skip loading disabled engines to avoid noise
# Check if already patched
if "inactive or disabled in config!" not in content:
    inject_loop = """
        if engine_data.get("inactive") is True or engine_data.get("disabled") is True:
            logger.debug(
                "loading engine %s skipped: inactive or disabled in config!",
                engine_data.get("name", "???"),
            )
            continue"""

    # Anchor: find the start of the loop in load_engines
    # We look for 'for engine_data in engine_list:' and the next few lines to ensure we are in load_engines
    pattern = r"(def load_engines\(engine_list:.*?for engine_data in engine_list:)"
    content, count = re.subn(pattern, r"\1" + inject_loop, content, flags=re.S)
    if count == 0:
        # Fallback: just look for the loop if the function definition changed slightly
        pattern = r"(for engine_data in engine_list:)"
        content, count = re.subn(pattern, r"\1" + inject_loop, content, count=1)

    if count == 0:
        print("ERROR: Could not find anchor in load_engines (plural)")
        sys.exit(1)

with open(path, 'w', encoding='utf-8', newline='\n') as f:
    f.write(content)
print("PATCHED")
'@
    $output = Invoke-PythonPatch -PythonCode $pyCode -TempName "patch_engines_init_disabled.py" `
        -TargetFile (Join-Path $repoRoot "python\Lib\site-packages\searx\engines\__init__.py")

    if ($output -match "ALREADY_APPLIED") { return "ALREADY_APPLIED" }
    return "PATCHED"
}


# --- 7. search/processors/__init__.py (skip intentionally disabled engines) ---
Update-Patch `
    -FilePath    (Join-Path $repoRoot "python\Lib\site-packages\searx\search\processors\__init__.py") `
    -Description "search/processors/__init__.py (skip disabled engines)" `
    -Required `
    -InPlace `
    -PatchLogic  {
    param($c)
    if ($c -match "skipping processor init") {
        return "ALREADY_APPLIED"
    }

    $pyCode = @'
import sys, re
path = sys.argv[1]
with open(path, 'r', encoding='utf-8') as f:
    content = f.read()

if "skipping processor init" in content:
    print("ALREADY_APPLIED")
    sys.exit(0)

# Anchor: the start of the loop in ProcessorMap.init
# We look for the inactive check and inject the disabled check after it
pattern = r"(if eng_settings\.get\(\"inactive\", False\) is True:\s+continue)"
inject_code = """
            if eng_settings.get("disabled", False) is True:
                logger.debug("Engine '%s' is disabled in config, skipping processor init.", eng_name)
                continue"""

content, count = re.subn(pattern, r"\1" + inject_code, content)

if count == 0:
    print("ERROR: processor init patch failed (anchor not found)")
    sys.exit(1)

with open(path, 'w', encoding='utf-8', newline='\n') as f:
    f.write(content)
print("PATCHED")
'@
    $output = Invoke-PythonPatch -PythonCode $pyCode -TempName "patch_processors_init_disabled.py" `
        -TargetFile (Join-Path $repoRoot "python\Lib\site-packages\searx\search\processors\__init__.py")

    if ($output -match "ALREADY_APPLIED") { return "ALREADY_APPLIED" }
    return "PATCHED"
}

Write-Host "✓ All Windows patches applied successfully." -ForegroundColor Green
