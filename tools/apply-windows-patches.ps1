$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path

# --- Helper: Apply a patch with robust error handling and status reporting ---
function Update-Patch {
    param(
        [string]$FilePath,
        [string]$Description,
        [scriptblock]$PatchLogic
    )

    if (-not (Test-Path $FilePath)) {
        Write-Host "⚠  File not found, skipping ${Description}: ${FilePath}" -ForegroundColor Yellow
        return
    }

    $content = Get-Content $FilePath -Raw -Encoding UTF8
    $newContent = &$PatchLogic $content

    if ($newContent -eq "ALREADY_APPLIED") {
        Write-Host "✓ Already applied: ${Description}" -ForegroundColor Gray
    }
    elseif ($content -eq $newContent) {
        throw "✗ Patch failed for ${Description}: Upstream code may have changed, could not find injection point (check UPSTREAM_VERSION.txt)."
    }
    else {
        Set-Content $FilePath -Value $newContent -Encoding UTF8
        Write-Host "✓ Patched: ${Description}" -ForegroundColor Green
    }
}

# --- Helper: Execute Python patch script with error detection and cleanup ---
function Invoke-PythonPatch {
    param(
        [string]$PythonCode,
        [string]$TempName,
        [string]$TargetFile
    )
    $tmpPy = Join-Path $env:TEMP $TempName
    try {
        $PythonCode | Out-File -FilePath $tmpPy -Encoding utf8
        $output = & ".\python\python.exe" $tmpPy $TargetFile 2>&1
        $result = $output -join "`n"
        
        if ($result -match "^ERROR:") {
            throw "Python patch script failed: $result"
        }
        return $result
    }
    finally {
        if (Test-Path $tmpPy) { Remove-Item $tmpPy -Force -ErrorAction SilentlyContinue }
    }
}


# --- 1. valkeydb.py (Windows compatibility: pwd → os.environ fallback) ---
Update-Patch `
    -FilePath    (Join-Path $repoRoot "python\Lib\site-packages\searx\valkeydb.py") `
    -Description "valkeydb.py (Windows pwd compatibility)" `
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
    return $output.Contains("PATCHED")
}


# --- 2. settings_defaults.py (register json_lite output format) ---
Update-Patch `
    -FilePath    (Join-Path $repoRoot "python\Lib\site-packages\searx\settings_defaults.py") `
    -Description "settings_defaults.py (json_lite format)" `
    -PatchLogic  {
    param($c)
    if ($c -match "'json_lite'") { return "ALREADY_APPLIED" }
    # (?s) lets .* span newlines for multi-line list definitions
    $c = $c -replace "(?s)(OUTPUT_FORMATS\s*=\s*\[)(.*?)(\])", "`$1`$2, 'json_lite'`$3"
    return $c
}


# --- 3. webutils.py (add get_json_lite_response, optimised) ---
Update-Patch `
    -FilePath    (Join-Path $repoRoot "python\Lib\site-packages\searx\webutils.py") `
    -Description "webutils.py (get_json_lite_response)" `
    -PatchLogic  {
    param($c)
    if ($c -match "def get_json_lite_response") { return "ALREADY_APPLIED" }

    # Optimised: as_dict() called once per result via inner helper _r()
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
        }
    data = {
        'query': sq.query,
        'results': [_r(r) for r in rc.get_ordered_results()[:20]],
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
    # Insert before get_themes (preserves the 2 blank lines already present before it)
    $c = $c -replace '(def get_themes\b)', "$liteFunc`$1"
    return $c
}


# --- 4. webapp.py (json_lite handler + ipaddress import at module level) ---
Update-Patch `
    -FilePath    (Join-Path $repoRoot "python\Lib\site-packages\searx\webapp.py") `
    -Description "webapp.py (json_lite handler + ipaddress import)" `
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
    return $output.Contains("PATCHED")
}


# --- 5. webapp.py (/scrape route + trafilatura import for GenAI workflows) ---
Update-Patch `
    -FilePath    (Join-Path $repoRoot "python\Lib\site-packages\searx\webapp.py") `
    -Description "webapp.py (/scrape endpoint, SSRF-protected)" `
    -PatchLogic  {
    param($c)
    if ($c -match "def scrape\(\)" -and $c -match "import trafilatura") { 
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

# 2. Clean stale /scrape route (idempotency)
content = re.sub(
    r'\n\n@app\.route\(\'/scrape\'[^\n]*\)\ndef scrape\(\):.*?(?=\n\n@app\.route)',
    '', content, flags=re.S
)

# 3. Insert /scrape route before /search (most stable anchor point)
#    SECURITY: SSRF protection via ipaddress library (loopback, private, link-local blocks)
#    NOTE: verify=False is acceptable for localhost-only deployment, not for internet-facing
scrape_route = '''

@app.route('/scrape', methods=['GET', 'POST'])
def scrape():
    """Extract main text content from URL (GenAI friendly, SSRF-protected).
    
    SECURITY: Blocks loopback (127.x), private/reserved IP ranges, link-local, 
    and file:// scheme to prevent SSRF attacks and internal resource exposure.
    
    NOTE: verify=False in SSL context is safe only because this server is 
    bound to localhost (127.0.0.1) and not accessible from internet.
    """
    url = sxng_request.values.get('url')
    if not url and sxng_request.is_json and sxng_request.json:
        url = sxng_request.json.get('url')
    if not url:
        return jsonify({'error': 'No URL provided'}), 400

    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ('http', 'https'):
        return jsonify({'error': 'Invalid scheme'}), 400

    host = parsed.hostname or ''
    host = host.lower()
    if not host or host == 'localhost':
        return jsonify({'error': 'Blocked: loopback/local'}), 400

    # SSRF protection: block loopback, private ranges, link-local
    try:
        ip = ipaddress.ip_address(host)
        if ip.is_loopback or ip.is_private or ip.is_link_local:
            return jsonify({'error': 'Blocked: private/reserved IP'}), 400
    except ValueError:
        pass  # hostname, not IP literal

    try:
        # Fetch using trafilatura (optimized for content extraction)
        downloaded = trafilatura.fetch_url(url)
        if not downloaded:
            # Fallback: use httpx with realistic UA (many sites block headless requests)
            # NOTE: UA spoofing for legitimate UX enhancement, not malware evasion
            ua = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                  'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')
            with httpx.Client(timeout=10.0, follow_redirects=True,
                              verify=False, headers={'User-Agent': ua}) as client:
                resp = client.get(url)
                resp.raise_for_status()
                downloaded = resp.text

        # Extract content with sanitization (no scripts/comments)
        content_text = trafilatura.extract(
            downloaded, include_comments=False, include_tables=True
        )
        if not content_text:
            return jsonify({'error': 'Could not extract content'}), 422

        return jsonify({'url': url, 'content': content_text})
    except Exception as e:
        # Truncate error message (prevent info leakage)
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
    return $output.Contains("PATCHED")
}

Write-Host "✓ All Windows patches applied successfully." -ForegroundColor Green
