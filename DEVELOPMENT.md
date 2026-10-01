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
│   ├── settings.yml.example # Tracked template (placeholder secret_key)
│   ├── settings.yml         # Local user config (gitignored, seeded from .example)
│   ├── secret.key           # Per-install Flask secret_key (gitignored)
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
   - Validates embedded Python and webapp presence
   - Seeds `config\settings.yml` from `config\settings.yml.example` if missing
   - Runs `tools\ensure-secret-key.py`, which writes/reads `config\secret.key`
     and emits `set SEARXNG_SECRET=<key>` on stdout; the launcher captures
     this into the local environment
   - Sets `SEARXNG_SETTINGS_PATH` and `SEARXNG_SECRET` environment variables
   - Launches `python\Lib\site-packages\searx\webapp.py`

2. **webapp.py** → Flask server
   - Binds to `http://127.0.0.1:8888` (localhost only)
   - Serves unified AI-First WebUI (`/` and `/ai`) with 4 modes (Deep Search, Classic Search, Agent & MCP Hub, Settings Dashboard)
   - Intercepts legacy browser routes (`/search` (HTML), `/preferences`, `/about`) via dual-tier routing (Tier A `before_request`, Tier B `view_functions`)
   - Preserves 100% backward compatibility for API queries (`/search?format=json`, `/search?format=json_lite`, `/deep_search`, `/api/retrieval`, `/scrape`)
   - Applies search engine filtering + output formatting

---

## Patch System: Idempotent Windows-Specific Modifications

### Design Principle

This project **stays synchronized with upstream SearXNG** while maintaining Windows compatibility and AI-first unification via **idempotent patches**. Patches are applied after every upstream sync and are safe to run multiple times.
The `webapp_ai_webui` patch is elevated to `CRITICAL` severity to guarantee that any upstream modification that breaks UI unification halts the sync process immediately rather than silently reviving the legacy Jinja2 UI.

### Patch Targets (26 Patch Specs across Target Files)

| # | File | Patch Spec | Severity | Purpose |
|---|------|------------|:---:|---------|
| 1 | `valkeydb.py` | `valkeydb_compat` | CRITICAL | Windows `pwd` module fallback & Valkey DB initialization |
| 2 | `webutils.py` | `webutils_windows_paths` | CRITICAL | Normalize Windows paths to forward slashes for static/template lookups |
| 3 | `webapp.py` | `webapp_json_handler` | CRITICAL | Register `json_lite` handler & enforce `WindowsSelectorEventLoopPolicy` |
| 4 | `settings_defaults.py` | `settings_defaults_json_lite` | FEATURE | Register `json_lite` format in `OUTPUT_FORMATS` |
| 5 | `webutils.py` | `webutils_json_lite` | FEATURE | Lightweight GenAI-friendly response serializer (`get_json_lite_response`) |
| 6 | `webapp.py` | `webapp_scrape_route` | FEATURE | `/scrape` endpoint with SSRF guard, streaming size/duration caps |
| 7 | `webapp.py` | `webapp_ai_webui` | CRITICAL | Dedicated AI Studio, Classic search mode, Settings API, legacy UI abolition |
| 8 | `search/processors/online.py` | `online_captcha` | FEATURE | Respect HTTP Retry-After hints & CAPTCHA logging |
| 9 | `network/raise_for_httperror.py` | `raise_for_httperror` | FEATURE | Attach HTTP response to `SearxEngineCaptchaException` for header inspection |
| 10 | `templates/simple/search.html` | `search_html_accessibility` | OPTIONAL | Accessible search input `aria-label` |
| 11 | `templates/simple/simple_search.html` | `simple_search_html_accessibility` | OPTIONAL | Accessible search input `aria-label` |
| 12 | `templates/simple/preferences/cookies.html` | `cookies_html_accessibility` | OPTIONAL | Accessible cookie hash input `aria-label` |
| 13 | `templates/simple/base.html` | `simple_base_ai_webui` | FEATURE | AI Workspace navigation link & embed assets |
| 14 | `templates/simple/index.html` | `simple_index_ai_webui` | FEATURE | AI Quick Actions bar injection |
| 15 | `templates/simple/results.html` | `simple_results_ai_webui` | FEATURE | AI Agent Toolkit bar injection |
| 16 | `engines/__init__.py` | `engines_init` | OPTIONAL | Remove legacy `disabled` engine short-circuit |
| 17 | `engines/__init__.py` | `engines_fast_load` | FEATURE | Fast-path skip inactive & unconfigured onion engines |
| 18 | `search/processors/__init__.py` | `processors_init` | OPTIONAL | Remove legacy `disabled` processor skip |
| 19 | `engines/google.py` | `google_captcha` | OPTIONAL | Reduce spurious CAPTCHA suspensions on Google |
| 20 | `engines/sogou.py` | `sogou_captcha` | OPTIONAL | Robust Sogou antispider/captcha detection |
| 21 | `search/processors/abstract.py` | `abstract_suspend` | OPTIONAL | Remove legacy global suspension cap, honoring `suspended_times` |
| 22 | `searx/settings.yml` | `settings_yml_suspended_times` | OPTIONAL | Reduce engine suspended_times defaults for single-user instance |
| 23 | `config/settings.yml` | `config_settings_yml_suspended_times` | OPTIONAL | Reduce engine suspended_times while preserving custom user overrides |
| 24 | `preferences.py` | `preferences_validation` | CRITICAL | Safe category validation & graceful non-fatal `parse_dict` handling |
| 25 | `webadapter.py` | `webadapter_categories` | CRITICAL | Safe categories lookup using `.get()` to prevent KeyError |
| 26 | `webapp.py` | `webapp_preferences_validation` | CRITICAL | Tab categories in Preferences & safe pre_request validation handling |

### Patch Execution Flow

```
sync-upstream.ps1
  ├─ Clone sparse checkout (only safe paths: /searx/, /requirements.txt, etc.)
  ├─ Checkout shallow clone at master HEAD
  ├─ Sync searx/ and searxng_extra/ packages
  ├─ Copy requirements.txt, setup.py, LICENSE
  ├─ Update UPSTREAM_VERSION.txt (metadata)
  ├─ apply-patches.py (idempotent, halts on CRITICAL failure)
  │    ├─ Patch 1: valkeydb_compat (valkeydb.py) [CRITICAL] ✓
  │    ├─ Patch 2: webutils_windows_paths (webutils.py) [CRITICAL] ✓
  │    ├─ Patch 3: webapp_json_handler (webapp.py) [CRITICAL] ✓
  │    ├─ Patch 4: settings_defaults_json_lite (settings_defaults.py) [FEATURE] ✓
  │    ├─ Patch 5: webutils_json_lite (webutils.py) [FEATURE] ✓
  │    ├─ Patch 6: webapp_scrape_route (webapp.py) [FEATURE] ✓
  │    ├─ Patch 7: webapp_ai_webui (webapp.py) [CRITICAL] ✓
  │    ├─ Patch 8: online_captcha (search/processors/online.py) [FEATURE] ✓
  │    ├─ Patch 9: raise_for_httperror (network/raise_for_httperror.py) [FEATURE] ✓
  │    ├─ Patch 10: search_html_accessibility (templates/simple/search.html) [OPTIONAL] ✓
  │    ├─ Patch 11: simple_search_html_accessibility (templates/simple/simple_search.html) [OPTIONAL] ✓
  │    ├─ Patch 12: cookies_html_accessibility (templates/simple/preferences/cookies.html) [OPTIONAL] ✓
  │    ├─ Patch 13: simple_base_ai_webui (templates/simple/base.html) [FEATURE] ✓
  │    ├─ Patch 14: simple_index_ai_webui (templates/simple/index.html) [FEATURE] ✓
  │    ├─ Patch 15: simple_results_ai_webui (templates/simple/results.html) [FEATURE] ✓
  │    ├─ Patch 16: engines_init (engines/__init__.py) [OPTIONAL] ✓
  │    ├─ Patch 17: engines_fast_load (engines/__init__.py) [FEATURE] ✓
  │    ├─ Patch 18: processors_init (search/processors/__init__.py) [OPTIONAL] ✓
  │    ├─ Patch 19: google_captcha (engines/google.py) [OPTIONAL] ✓
  │    ├─ Patch 20: sogou_captcha (engines/sogou.py) [OPTIONAL] ✓
  │    ├─ Patch 21: abstract_suspend (search/processors/abstract.py) [OPTIONAL] ✓
  │    ├─ Patch 22: settings_yml_suspended_times (searx/settings.yml) [OPTIONAL] ✓
  │    ├─ Patch 23: config_settings_yml_suspended_times (config/settings.yml) [OPTIONAL] ✓
  │    ├─ Patch 24: preferences_validation (preferences.py) [CRITICAL] ✓
  │    ├─ Patch 25: webadapter_categories (webadapter.py) [CRITICAL] ✓
  │    └─ Patch 26: webapp_preferences_validation (webapp.py) [CRITICAL] ✓
  └─ Post-Sync Verification (tools/test_patches.py)
       └─ Validates root AI Studio, legacy redirects, API passthrough, and Settings API
```

### Idempotency Strategy

Each patch:
1. **Checks if already applied** → returns `ALREADY_APPLIED` (no-op). Checks are robust, looking for specific markers via regex or substring.
2. **Validates anchors/injection points** → regex-based, upstream-aware. Uses multiple fallback patterns if function signatures change slightly.
3. **Reports errors explicitly** → all Python patches output `ERROR: {reason}` on failure.
4. **Cleans stale code** → removes old duplicate patches before re-inserting (where applicable).
5. **Pre-flight Check** (New) → Supports `Assert-Anchor` to verify injection points before modification.
6. **Staging-path containment** → `-TempDir` must be relative to, and resolve
   inside, the workspace before any recursive cleanup is attempted.

Example (engines/__init__.py):
```python
# Idempotency check: look for the complete scrape-route marker
if "v15-bulletproof-scrape-fix" in content:
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
- Blocks loopback (`127.0.0.0/8`, `::1`)
- Blocks private ranges (`10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`, `fc00::/7`)
- Blocks link-local (`169.254.0.0/16`, `fe80::/10`)
- Blocks multicast and reserved IP spaces (`224.0.0.0/4`, `ff00::/8`)
- Blocks IPv4-mapped IPv6 (`::ffff:127.0.0.1`) and IPv4-compatible IPv6 (`::127.0.0.1`)
- Blocks 6to4 tunneling (`2002::/16`) and Teredo tunneling (`2001:0000::/32`) embedding blocked IPs
- Blocks non-HTTP(S) schemes (`file://`, `gopher://`, `ftp://`, `data:`, `javascript:`)
- Blocks internal/reserved TLDs (`.local`, `.internal`, `.localhost`, `.arpa`, `.lan`, etc.)
- Enforces DNS pinning to prevent DNS rebinding attacks (TOCTOU)
- Stream deadline (`SEARXNG_SCRAPE_MAX_DURATION`) to defeat slowloris attacks
- Returns HTTP 400 for blocked or invalid URLs

---

## Security Considerations

### ✓ What's Protected

- **SSRF attacks**: `/scrape` endpoint strictly validates URLs
- **Proxy bypasses**: `/scrape` ignores HTTPX proxy and CA environment variables,
  so DNS validation and pinning are not delegated to an ambient proxy
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

3. **SSL Verification (httpx for /scrape)**
    ```python
    verify_ssl = os.environ.get("SEARXNG_SCRAPE_VERIFY_SSL", "true").lower() in ("true", "1", "yes")
    httpx.Client(..., verify=verify_ssl, trust_env=False)
    ```
    - Default is `true` (certificates verified); set `SEARXNG_SCRAPE_VERIFY_SSL=false` for localhost-only without CA issues.

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

### Automated Testing & Linting

```powershell
# Run Ruff lint checks
ruff check .

# Run unit tests (patch idempotency, edge cases, hardening regression tests, and agent tools)
.\python\python.exe tools\test_patches.py
.\python\python.exe tools\test_agent_tools.py
.\python\python.exe tools\test_agentic_search.py

# Run standalone smoke test (requires server running)
.\tools\smoke-test.ps1

# Run complete end-to-end test suite (unit tests + background server + all smoke tests)
.\tools\run-tests.ps1 -SkipInstall

# Clean bytecode and temporary caches (frees ~25-30MB)
PowerShell -File .\tools\clean-cache.ps1
```

### Performance & Patch Caching

- **Fast-Path Verification**: `tools\apply-patches.py` caches file fingerprints in `python\.patches_cache.json`. When files have not changed, patch verification runs in **~5ms** (down from ~465ms).
- **Forced Re-Verification**: To force a complete re-scan and validation of all patch anchors, run:
  ```powershell
  .\python\python.exe tools\apply-patches.py --force
  ```

Smoke tests validate:
- ✓ Root page accessible with proper ARIA attributes
- ✓ Standard JSON API responds
- ✓ GenAI-optimized `json_lite` format produces valid token-efficient results
- ✓ `/scrape` extracts web content safely (form, JSON, and GET params)
- ✓ SSRF protection blocks loopback/private/multicast IPs and non-HTTP schemes
- ✓ Autocomplete and healthcheck endpoints respond properly
- ✓ SearXNG CLI (`tools\searxng_cli.py`) health check, search, and scrape integration tests

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
| `config/settings.yml` | **User-customizable** (gitignored) | Not touched by sync |
| `config/secret.key` | **Per-install** (gitignored) | Holds Flask secret_key; delete to rotate |
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

## Retrieval API & Quality Evaluation Framework

### Modular Service Architecture

The Retrieval API is implemented as standalone, testable Python modules inside `tools/`:

- **`tools/url_normalizer.py`**: Deterministic URL normalization, tracking parameter stripping (preserving signed URLs), and SSRF validation.
- **`tools/deduplication.py`**: 6-phase progressive deduplication (exact URL, canonical, title, fuzzy title, snippet similarity, mirror clustering).
- **`tools/rank_fusion.py`**: Reciprocal Rank Fusion (RRF `1/(k+rank)`) with consensus and multi-query bonuses.
- **`tools/lexical_rerank.py`**: Multilingual BM25 reranking with English word tokens and Japanese/CJK character 2/3-grams.
- **`tools/passage_chunker.py`**: Heading-aware article chunking, metadata extraction (via `lxml` + `trafilatura`), and adversarial prompt injection scanning.
- **`tools/query_pipeline.py`**: Deterministic NFKC query normalization, 8-class intent classification, and budget-governed query expansion.
- **`tools/retrieval_models.py`**: GenAI schema serialization (`schema_version: "1.0"`), mode budget specifications (`fast`, `balanced`, `deep`), and citation quality scoring.
- **`tools/retrieval_service.py`**: Unified orchestrator unifying HTTP (`/api/retrieval`), WebUI (`/deep_search`), MCP (`searxng_retrieval`), and CLI.

### Running Quality Benchmarks

The benchmark suite in `tests/evaluation/` provides deterministic offline quality evaluation and optional live instance benchmarking:

```powershell
# Run benchmark across all modes (fast, balanced, deep)
.\python\python.exe tests\evaluation\run_benchmark.py --json

# Run unit and integration tests
.\python\python.exe tools\test_retrieval_pipeline.py
```

Benchmark output metrics include:
- **Precision@5**, **Recall@10**, **MRR**, **nDCG@10**
- **Deduplication Rate** in Top 10
- **Official Source Presence** in top results
- **Citable Evidence Passage Rate**
- **Content Extraction Success Rate**
- **Latency (Mean & p95)**
- **Payload Character Count**
- **Partial Failure Rate**

---

## Summary: Why This Design?

✅ **Pros:**
- Stays synchronized with upstream bug fixes & security updates
- Idempotent patches safe for automation
- Windows-native (no Docker, WSL, or system dependencies)
- GenAI-optimized (token-efficient responses, structured evidence passages)
- SSRF-protected content extraction with prompt injection defense
- Clear separation: tools/ for automation, patches never in sync scope

✅ **Not suitable for:**
- Public internet deployment without auth/TLS/rate-limiting
- Production use as-is (localhost-only assumption)
- Deployment to restricted networks without security review

---

**Last Updated:** 2026-05-02  
**Upstream:** https://github.com/searxng/searxng.git (master branch)  
**Installed Version:** Check `UPSTREAM_VERSION.txt` for commit hash
