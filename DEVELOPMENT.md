# SearXNG for Windows — Development & Maintenance Guide

This document describes the architecture, patch system, and maintenance procedures for the SearXNG for Windows project.

---

## Architecture Overview

### Core Components

```
workspace/
├── python/                   # Embedded Python 3.11 (portable, no system dependency)
│   └── Lib/site-packages/   # Pre-installed packages (required)
│
├── config/                   # Configuration & upstream metadata
│   ├── settings.yml         # Main SearXNG config (user-customizable)
│   ├── requirements.txt      # Main Python dependencies
│   ├── requirements-server.upstream.txt  # Server-specific deps
│   └── *.upstream.txt       # Cached upstream files (reference only)
│
├── tools/                    # PowerShell automation scripts
│   ├── install-requirements.ps1   # Install Python packages
│   ├── sync-upstream.ps1          # Sync upstream repo + apply patches
│   ├── apply-windows-patches.ps1  # Idempotent patch application
│   └── smoke-test.ps1             # Integration test suite
│
├── SearXNG for Windows.bat   # Entry point (launcher)
├── UPSTREAM_VERSION.txt      # Sync metadata (commit hash, date)
└── changed_files.txt         # List of patched Python files
```

### Launch Flow

1. **SearXNG for Windows.bat** → Entry point (Windows native)
   - Validates embedded Python, webapp, config presence
   - Sets `SEARXNG_SETTINGS_PATH` environment variable
   - Launches `python\Lib\site-packages\searx\webapp.py`

2. **webb.py** → Flask server
   - Binds to `http://127.0.0.1:8888` (localhost only)
   - Handles `/search`, `/scrape` (custom), and standard SearXNG routes
   - Applies search engine filtering + output formatting

---

## Patch System: Idempotent Windows-Specific Modifications

### Design Principle

This project **stays synchronized with upstream SearXNG** while maintaining Windows compatibility via **idempotent patches**. Patches are applied after every upstream sync and are safe to run multiple times.

### Patch Targets (5 Core Python Files)

| # | File | Patch | Purpose |
|---|------|-------|---------|
| 1 | `valkeydb.py` | Windows `pwd` module fallback | Cache system compatibility |
| 2 | `settings_defaults.py` | Register `json_lite` format | Output format registration |
| 3 | `webutils.py` | `get_json_lite_response()` function | Lightweight GenAI-friendly responses |
| 4 | `webapp.py` (pt 1) | `json_lite` handler + `ipaddress` import | Route handler + SSRF libs |
| 5 | `webapp.py` (pt 2) | `/scrape` endpoint (SSRF-protected) | Content extraction API |

### Patch Execution Flow

```
sync-upstream.ps1
  ├─ Clone sparse checkout (only safe paths: /searx/, /requirements.txt, etc.)
  ├─ Checkout shallow clone at master HEAD
  ├─ Sync searx/ and searxng_extra/ packages
  ├─ Copy requirements.txt, setup.py, LICENSE
  ├─ Update UPSTREAM_VERSION.txt (metadata)
  └─ apply-windows-patches.ps1 (5 patches, idempotent)
       ├─ Patch 1: valkeydb.py ✓
       ├─ Patch 2: settings_defaults.py ✓
       ├─ Patch 3: webutils.py ✓
       ├─ Patch 4a: webapp.py (json_lite handler) ✓
       └─ Patch 4b: webapp.py (/scrape route) ✓
```

### Idempotency Strategy

Each patch:
1. **Checks if already applied** → returns `ALREADY_APPLIED` (no-op)
2. **Validates anchors/injection points** → regex-based, upstream-aware
3. **Reports errors explicitly** → all Python patches output `ERROR: {reason}` on failure
4. **Cleans stale code** → removes old duplicate patches before re-inserting

Example (valkeydb.py):
```python
if ('def _windows_safe_current_user():' in content
        and '_user_name, _user_uid = _windows_safe_current_user()' in content):
    print("ALREADY_APPLIED")
    sys.exit(0)
```

### Maintenance: Detecting Upstream Changes

If an upstream patch target changes (e.g., function signature, import changes):
1. `apply-windows-patches.ps1` will fail with `ERROR: anchor/injection point not found`
2. **Action required**: Update the patch regex/logic to match new upstream code
3. **Guide**: See "Patch Customization" below

---

## Key Customizations (What's Different from Vanilla SearXNG)

### 1. Windows Compatibility (Patch #1: valkeydb.py)

**Problem:** Unix-only `pwd` module (user enumeration) doesn't exist on Windows.

**Solution:** Fallback to `os.environ` for username detection.

```python
def _windows_safe_current_user():
    if pwd is not None and hasattr(os, "getuid"):
        try:
            return pwd.getpwuid(os.getuid()).pw_name, os.getuid()
        except:
            pass
    # Windows fallback
    username = os.environ.get("USERNAME") or os.environ.get("USER") or "windows"
    return username, -1
```

### 2. GenAI-Friendly Output Format (Patches #2-3: json_lite)

**Problem:** Standard JSON responses include many fields (engines, queries, metadata), consuming LLM tokens.

**Solution:** Lightweight `json_lite` format with only essential fields:
- `title`: Result title
- `url`: Result URL
- `content`: Summary/snippet
- `source`: Engine name

**API:**
```
GET/POST /search?q=query&format=json_lite
```

**Response:**
```json
{
  "query": "SearXNG",
  "results": [
    {
      "title": "SearXNG - Metasearch Engine",
      "url": "https://docs.searxng.org",
      "content": "SearXNG is a privacy-friendly metasearch engine...",
      "source": "duckduckgo"
    }
  ],
  "answers": [...],
  "infoboxes": [...]
}
```

### 3. Web Content Extraction API (Patch #5: /scrape)

**Problem:** No built-in endpoint for extracting article text from arbitrary URLs.

**Solution:** `POST/GET /scrape?url=<url>` with SSRF protection + content extraction.

**SSRF Protection (Security-Critical):**
- Blocks loopback (127.x.x.x)
- Blocks private ranges (10.x, 172.16.x, 192.168.x, fc00::/7)
- Blocks link-local (169.254.x, fe80::/10)
- Blocks `file://` scheme
- Returns HTTP 400 for blocked URLs

**Implementation:**
```python
try:
    ip = ipaddress.ip_address(host)
    if ip.is_loopback or ip.is_private or ip.is_link_local:
        return jsonify({'error': 'Blocked: private/reserved IP'}), 400
except ValueError:
    pass  # hostname, not IP — continue
```

---

## Security Considerations

### ✓ What's Protected

- **SSRF attacks**: `/scrape` endpoint strictly validates URLs
- **HTTP spoofing**: User-Agent realistic but transparent (legitimate UX enhancement)
- **Script injection**: `trafilatura.extract()` sanitizes comments/scripts
- **Exposure mitigation**: Error messages truncated to 100 chars

### ⚠ What's Not Protected (By Design)

1. **No HTTPS/TLS Enforcement**
   - localhost-only binding (127.0.0.1:8888) makes HTTPS unnecessary
   - If deploying to network, add reverse proxy with TLS

2. **No Authentication/Authorization**
   - Assumes trusted local network
   - Not suitable for internet-facing deployment without authentication middleware

3. **SSL Verification Disabled in httpx**
   ```python
   httpx.Client(..., verify=False)
   ```
   - Safe for localhost (no MITM risk)
   - **Not safe for internet deployments** — add proper cert handling

4. **No Rate Limiting on /scrape**
   - Relies on upstream engine rate limits
   - Consider adding middleware if exposing to network

### Recommended Hardening for Internet Deployment

```nginx
# nginx reverse proxy + TLS + Auth
upstream searxng {
    server 127.0.0.1:8888;
}

server {
    listen 443 ssl http2;
    server_name searxng.example.com;
    
    ssl_certificate /path/to/cert.pem;
    ssl_certificate_key /path/to/key.pem;
    ssl_protocols TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;
    
    # HTTP Basic Auth (or OAuth2 proxy)
    auth_basic "SearXNG";
    auth_basic_user_file /etc/nginx/.htpasswd;
    
    # Rate limiting
    limit_req_zone $binary_remote_addr zone=general:10m rate=10r/s;
    limit_req_zone $binary_remote_addr zone=scrape:10m rate=2r/s;
    
    location / {
        limit_req zone=general burst=20;
        proxy_pass http://searxng;
    }
    
    location /scrape {
        limit_req zone=scrape burst=5;
        proxy_pass http://searxng;
    }
}
```

---

## Maintenance Procedures

### Regular Upstream Sync

```powershell
# In project directory
.\tools\sync-upstream.ps1 -CleanTemp

# Output will show:
#   ✓ Upstream checkout successful
#   ⚠ NOTICE: requirements.txt has changed!
#   ✓ All Windows patches applied successfully
```

**After sync:**
1. If requirements changed, run: `.\tools\install-requirements.ps1`
2. Restart server: `SearXNG for Windows.bat`
3. Run smoke tests: `.\tools\smoke-test.ps1`

### Smoke Testing

```powershell
.\tools\smoke-test.ps1
```

Validates:
- ✓ Root page accessible
- ✓ JSON API responds
- ✓ json_lite format produces results
- ✓ /scrape extracts content
- ✓ SSRF protection blocks loopback/private IPs

### Patch Customization (If Upstream Changes)

If `apply-windows-patches.ps1` fails with `ERROR: anchor not found`:

1. **Identify which patch failed** (e.g., "webapp.py (json_lite handler)")
2. **Find the new anchor point** in the updated source file:
   ```powershell
   # Inspect the file
   & ".\python\python.exe" -c "
       with open('python\Lib\site-packages\searx\webapp.py', 'r') as f:
           lines = f.readlines()
           for i, line in enumerate(lines[100:200], start=100):
               print(f'{i}: {line}', end='')
   "
   ```
3. **Update the regex** in `apply-windows-patches.ps1`:
   ```powershell
   # Old:
   r"(?m)^(    if output_format == 'json':\n\n        response = webutils\.get_json_response)"
   
   # New (example if structure changed):
   r"(# JSON format handler\r?\n.*?if output_format == 'json':)"
   ```
4. **Re-run sync**: `.\tools\sync-upstream.ps1`

### Monitoring / Logging

- **UPSTREAM_VERSION.txt**: Last successful sync date + commit hash
- **changed_files.txt**: List of patched files (informational)
- **Console output**: Patches show status (Already Applied / Patched / ERROR)

---

## File Organization: What Gets Overwritten on Sync

| Path | Behavior | Notes |
|------|----------|-------|
| `python/Lib/site-packages/searx/` | **Overwritten** | Upstream code (patched immediately after) |
| `python/Lib/site-packages/searxng_extra/` | **Overwritten** | If present upstream |
| `config/requirements.txt` | **User-editable** (not sync'd) | Merged from upstream manually if needed |
| `config/settings.yml` | **User-customizable** | Not touched by sync |
| `config/*.upstream.txt` | **Overwritten** | Reference copies for auditing |
| `tools/*.ps1` | **User-controlled** | Never overwritten by sync |
| `UPSTREAM_VERSION.txt` | **Updated** | Metadata only |
| `changed_files.txt` | **Reference** | Lists patched files |

---

## Development Tips

### Testing Patches Without Full Sync

```powershell
# Apply patches to existing searx (if already installed)
.\tools\apply-windows-patches.ps1

# Should show "Already applied" for patches already in place
```

### Inspecting Patched Code

```powershell
# View valkeydb.py Windows fallback
& ".\python\python.exe" -c "
    import sys
    sys.path.insert(0, '.\python\Lib\site-packages')
    from searx import valkeydb
    import inspect
    print(inspect.getsource(valkeydb._windows_safe_current_user))
"
```

### Debugging Patch Failures

```powershell
# Run patch with verbose Python output
$Error = @(); 
try { 
    .\tools\apply-windows-patches.ps1 
} 
catch { 
    $_ | Select-Object -Property * | Format-List 
}
```

---

## Summary: Why This Design?

✅ **Pros:**
- Stays synchronized with upstream bug fixes & security updates
- Idempotent patches safe for automation
- Windows-native (no Docker, WSL, or system dependencies)
- GenAI-optimized (token-efficient responses)
- SSRF-protected content extraction
- Clear separation: tools/ for automation, patches never in sync scope

✅ **Not suitable for:**
- Public internet deployment without auth/TLS/rate-limiting
- Production use as-is (localhost-only assumption)
- Deployment to restricted networks without security review

---

**Last Updated:** 2026-05-02  
**Upstream:** https://github.com/searxng/searxng.git (master branch)  
**Installed Version:** Check `UPSTREAM_VERSION.txt` for commit hash
