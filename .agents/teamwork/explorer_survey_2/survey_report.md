# Comprehensive Survey Report: Patch Management & Windows Integration

**Author**: Explorer 2 (Patch Management & Windows Integration)  
**Date**: 2026-10-04  
**Project**: SearXNGforWindowsNext  
**Repository Root**: `c:\Users\mibu0\Documents\develop\SearXNGforWindowsNext`  

---

## 1. Executive Summary

This survey provides an exhaustive code review, architecture analysis, and security evaluation of the **Patch Management System**, **Configuration & Secrets Handling**, and **Windows Integration Layers** in the `SearXNGforWindowsNext` project.

SearXNG is fundamentally built for POSIX-compliant environments (Linux containers, systemd). In `SearXNGforWindowsNext`, Windows compatibility and AI enhancement features are achieved via an embedded Python runtime, a programmatic patching subsystem (`tools/apply-patches.py`), PowerShell launcher scripts, and in-process middleware extensions (`tools/webui_next.py`).

Our investigation confirmed that the core patching engine and SSRF defense architecture are sophisticated and robust (161 passing unit tests in `tools/test_patches.py`). However, our static audit uncovered **several high- and medium-severity vulnerabilities and architectural gaps** in:
1. **Patch Cache Incompleteness**: `_get_tracked_targets()` misses critical patched targets (`preferences.py` and `webadapter.py`), allowing patch application to be falsely skipped.
2. **Arbitrary File Overwrite via Rollback Manifest**: `PatchTransaction.rollback()` trusts unvalidated absolute paths in `manifest.json`.
3. **Unvalidated `--report` Path Traversal**: Arbitrary write capability via CLI report path argument.
4. **Incomplete NTFS File Permissions on Windows**: `os.chmod` in `ensure-secret-key.py` is a no-op on Windows NTFS ACLs, leaving `config/secret.key` readable by all local users.
5. **Predictable Temporary File Race Conditions**: `ensure-secret-key.py` writes to static `.tmp` filenames without `tempfile.mkstemp`.
6. **Quoted Environment Variable Path Breakage**: `SEARXNG_SETTINGS_PATH` with quotes crashes `settings_loader.py`.
7. **Connection Pooling Rebinding Edge Case**: Global `httpx.Client` keepalive in `/scrape` allows socket reuse across DNS resolutions.

Below is the detailed technical survey and catalog of all findings.

---

## 2. Patch Management System Architecture

### 2.1 Patch Execution Model (`tools/apply-patches.py`)

Unlike traditional patch tools that invoke `patch.exe` or `git apply`, `SearXNGforWindowsNext` uses an in-memory, Python-native transformation pipeline:
- **Location**: `tools/apply-patches.py` (2,838 lines).
- **Core Function**: `update_file(file_path, description, patch_func, ...)`
- **Workflow**:
  1. Reads target file using `encoding="utf-8-sig"` (safely stripping any UTF-8 BOM).
  2. Normalizes `\r\n` (CRLF) line endings to `\n` (LF) for consistent regex matching.
  3. Records original content in `PatchTransaction` for rollback.
  4. Executes `patch_func(normalized_content, file_path)`.
  5. Evaluates return status:
     - Returns `"ALREADY_APPLIED"`: Marked idempotent success.
     - Returns unchanged content: If marked `_noop_when_unchanged`, counts as `ALREADY_APPLIED`; otherwise triggers `diagnose_patch_failure()` and fails.
     - Returns modified content: Validated via Python AST parser (`ast.parse()`) if target is `.py`. If valid, written atomically using `_atomic_write()`.

### 2.2 Patch Specifications Catalog (26 Registered Patches)

The `PATCH_SPECS` registry defines 26 patch rules across 3 severity categories:

| # | Spec Name | Target File | Severity | Purpose |
|---|---|---|---|---|
| 1 | `valkeydb_pwd` | `searx/valkeydb.py` | `CRITICAL` | Replaces Unix `pwd` module with Windows username/UID fallback. |
| 2 | `webutils_windows_paths` | `searx/webutils.py` | `CRITICAL` | Normalizes `os.sep` to `/` in template and static file lookups. |
| 3 | `webapp_json_handler` | `searx/webapp.py` | `CRITICAL` | Adds `json_lite` output handler & sets `WindowsSelectorEventLoopPolicy`. |
| 4 | `settings_defaults_json_lite` | `searx/settings_defaults.py` | `FEATURE` | Appends `'json_lite'` to `OUTPUT_FORMATS`. |
| 5 | `webutils_json_lite` | `searx/webutils.py` | `FEATURE` | Injects `get_json_lite_response` serializer with score sanitization. |
| 6 | `webapp_scrape_route` | `searx/webapp.py` | `FEATURE` | Injects `/scrape` endpoint with DNS pinning and SSRF protection. |
| 7 | `webapp_ai_webui` | `searx/webapp.py` | `CRITICAL` | Injects dynamic import of `webui_next.py` and registers `/ai` & `/deep_search`. |
| 8 | `online_captcha` | `searx/search/processors/online.py` | `FEATURE` | Implements HTTP `Retry-After` header parsing & CAPTCHA suspension. |
| 9 | `raise_for_httperror` | `searx/network/raise_for_httperror.py` | `FEATURE` | Attaches response object to `SearxEngine*Exception` instances. |
| 10 | `search_html_accessibility` | `templates/simple/search.html` | `OPTIONAL` | Adds `aria-label` to primary search field. |
| 11 | `simple_search_html_accessibility` | `templates/simple/simple_search.html` | `OPTIONAL` | Adds `aria-label` to simple search input. |
| 12 | `cookies_html_accessibility` | `templates/simple/preferences/cookies.html` | `OPTIONAL` | Adds `aria-label` to cookie preferences hash input. |
| 13 | `simple_base_ai_webui` | `templates/simple/base.html` | `FEATURE` | Injects AI Workspace navigation link & embed assets (`/ai/embed.css`, `.js`). |
| 14 | `simple_index_ai_webui` | `templates/simple/index.html` | `FEATURE` | Injects AI Quick Actions bar on homepage. |
| 15 | `simple_results_ai_webui` | `templates/simple/results.html` | `FEATURE` | Injects AI Agent Toolkit bar on search results page. |
| 16 | `engines_init` | `searx/engines/__init__.py` | `OPTIONAL` | Restores upstream disabled vs inactive engine semantics. |
| 17 | `engines_fast_load` | `searx/engines/__init__.py` | `FEATURE` | Skips importing inactive engines & unconfigured onion engines. |
| 18 | `processors_init` | `searx/search/processors/__init__.py` | `OPTIONAL` | Removes legacy disabled engine processor bypass. |
| 19 | `google_captcha` | `searx/engines/google.py` | `OPTIONAL` | Eliminates false-positive 302 CAPTCHA detections. |
| 20 | `sogou_captcha` | `searx/engines/sogou.py` | `OPTIONAL` | Adds robust Sogou antispider/captcha pattern detection. |
| 21 | `abstract_suspend` | `searx/search/processors/abstract.py` | `OPTIONAL` | Restores configured engine suspension times from `settings.yml`. |
| 22 | `settings_yml_suspended_times` | `searx/settings.yml` | `OPTIONAL` | Reduces default suspension times for single-user Windows instances. |
| 23 | `config_settings_yml_suspended_times` | `config/settings.yml` | `OPTIONAL` | Reduces suspension times in local config while preserving overrides. |
| 24 | `preferences_validation` | `searx/preferences.py` | `CRITICAL` | Filters `MultipleChoiceSetting` and catches `ValidationException`. |
| 25 | `webadapter_categories` | `searx/webadapter.py` | `CRITICAL` | Uses `categories.get(categ, [])` to avoid `KeyError` on custom categories. |
| 26 | `webapp_preferences_validation` | `searx/webapp.py` | `CRITICAL` | Integrates `categories_as_tabs` in Preferences choices & safe pre-request. |

### 2.3 Transaction Management, Backups, and Atomic Writes

- **Atomic Writes**: `_atomic_write` generates a temporary file via `tempfile.mkstemp(prefix=".tmp_patch_", dir=directory, text=True)`, writes content with `newline="\n"`, flushes and `os.fsync`s, then calls `os.replace`. To counter Windows file locking by antivirus or indexing services, it implements 5 retries with exponential backoff (`0.05 * (2**attempt)`).
- **Transaction Rollback**:
  - In-memory rollback (`transaction.originals`) is available during execution.
  - Disk persistence (`transaction.persist_backups()`) writes original file copies to `python/.patches_backup/<safe_rel>.bak` and writes `manifest.json`.
  - Manual CLI rollback is available via `--rollback`.
  - Automatic rollback on critical failure is supported via `--rollback-on-failure`.

### 2.4 Patch Caching Engine

- Target fingerprinting records `st_mtime_ns` and `st_size` for tracked files into `python/.patches_cache.json`.
- `is_patch_cache_valid()` performs a fast-path comparison, skipping patch runs if no tracked files changed.

---

## 3. Configuration & Secrets Handling

### 3.1 Architecture Overview

```
[config/settings.yml.example] (Tracked in Git, placeholder secret_key)
             │
             ▼ (Copied if missing on first run)
[config/settings.yml]         (Gitignored, user-customizable)
             │
             ▼ (Read at startup by searx/settings_loader.py)
[SearXNG Application Runtime] ◄── [SEARXNG_SECRET] (Env Var override)
                                          │
                                          ▲ (Read/Generated on launch)
                                  [config/secret.key] (Gitignored, 64-hex key)
```

1. **Separation of Secrets from Git Tracking**:
   - `config/settings.yml.example` contains the placeholder string `"ultrasecretkey"`.
   - `config/settings.yml` and `config/secret.key` are strictly ignored in `.gitignore`.
2. **`tools/ensure-secret-key.py`**:
   - Checks `config/secret.key`. If missing or invalid format (non-64 hex chars), generates 256 bits of cryptographically secure entropy (`secrets.token_hex(32)`).
   - Emits a single line: `set SEARXNG_SECRET=<hex_key>`.
3. **Launcher Integration (`SearXNG for Windows.bat`)**:
   - Parses `tools/ensure-secret-key.py` output via `for /f "tokens=1* delims==" %%A`.
   - Validates length (must be exactly 64 characters).
   - Exports `SEARXNG_SECRET` into the process environment.
4. **Upstream Schema Binding (`searx/settings_defaults.py`)**:
   - `SCHEMA['server']['secret_key'] = SettingsValue(str, environ_name='SEARXNG_SECRET')`.
   - When `apply_schema()` runs, `os.environ['SEARXNG_SECRET']` takes precedence over YAML content.
5. **Runtime Secret Usage**:
   - Flask session cookie signing: `app.secret_key = settings['server']['secret_key']`.
   - Image proxy HMAC signing: `webutils.new_hmac(settings['server']['secret_key'], url.encode())`.
   - Favicon proxy HMAC: `searx/favicons/proxy.py`.
   - Cache key namespace derivation: `searx/valkeylib.py` and `searx/cache.py`.

---

## 4. Windows Environment Compatibility

### 4.1 Path Separators & Normalization

1. **Static Files & Result Templates**:
   - On Windows, `pathlib.Path.relative_to()` generates paths with `\` (`os.sep`).
   - In SearXNG, URLs requested by browsers are forward-slash delimited (`/static/themes/...`).
   - `patch_webutils_windows_paths` normalizes `os.sep` to `/` in `get_static_file_list()` and `get_result_templates()`, preventing 404 Not Found errors on static assets.
2. **Drive Boundary Relative Path Handling**:
   - Windows supports multiple drive letters (`C:`, `D:`).
   - In GitHub Actions or complex setups, temp files may reside on `C:` while workspace is on `D:`.
   - Standard `os.path.relpath()` throws `ValueError: path is on mount 'C:', start on mount 'D:'`.
   - `_safe_relpath()` catches `ValueError` and falls back cleanly to normalized absolute paths.

### 4.2 Encoding (UTF-8 vs ANSI / CP932)

- Default Windows Python installs on Japanese Windows use `cp932` (Shift-JIS) or Western Windows use `cp1252` when `open()` is called without an explicit `encoding`.
- In `tools/apply-patches.py` and `tools/ensure-secret-key.py`:
  - Input files are opened with `encoding="utf-8-sig"` (handles UTF-8 with or without BOM).
  - Output files are written with `encoding="utf-8"` and explicit `newline="\n"`.
- PowerShell scripts consistently initialize UTF-8 streams:
  ```powershell
  [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
  $OutputEncoding = [System.Text.UTF8Encoding]::new()
  ```

### 4.3 Async Event Loop Policy

- `curl_cffi` (used by SearXNG's `search/processors/online.py` for TLS fingerprinting) is incompatible with Windows default `ProactorEventLoop`.
- `patch_webapp_json_handler` injects:
  ```python
  if sys.platform == "win32":
    import asyncio

    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
```
  This resolves event loop crashes during concurrent curl requests.

### 4.4 Valkey / Redis User Compatibility

- Upstream `searx/valkeydb.py` relies on the Unix `pwd` module (`pwd.getpwuid(os.getuid())`), which does not exist on Windows.
- `patch_valkeydb` wraps `import pwd` in `try...except ImportError` and defines `_windows_safe_current_user()` querying `USERNAME`, `USER`, `LOGNAME`, or `"windows"`.

---

## 5. Security Vulnerability Analysis

### 5.1 Command Injection Audit

- **`tools/apply-patches.py`**: Contains zero subprocess invocations (`subprocess`, `os.system`, `os.popen`, `pty` are NOT used). All patch transformations are pure in-memory Python operations.
- **`tools/apply-windows-patches.ps1`**: Uses direct PowerShell array parameter invocation (`& $pythonExe $patchPy @args`). No shell string interpolation exists.
- **`tools/sync-upstream.ps1`**:
  - `Assert-UpstreamRef` rejects control characters `[\x00-\x1F\x7F]` and executes `git check-ref-format --branch $Value`.
  - Commands are run via `& git @GitArgs`.

### 5.2 SSRF & DNS Rebinding Protection in `/scrape`

The `/scrape` endpoint injected by `patch_webapp_scrape_route` implements rigorous defense-in-depth:
1. **Scheme Validation**: Strictly allows `http` and `https`; rejects `file://`, `gopher://`, `ftp://`, `data:`, `javascript:`, `ws:`.
2. **IP & Host Blacklisting**:
   - IPv4 loopback (`127.0.0.0/8`), private (`10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`), link-local (`169.254.0.0/16`), multicast (`224.0.0.0/4`), unspecified (`0.0.0.0`).
   - IPv6 loopback (`::1`), IPv6 link-local (`fe80::/10`), multicast (`ff00::/8`), unspecified (`::`).
   - IPv4-mapped IPv6 (`::ffff:127.0.0.1`), 6to4 (`2002:7f00:1::`), Teredo.
   - Alternate IP representations: integer IPs (`2130706433`), octal (`0177.0.0.1`), hex (`0x7f000001`), shorthand (`127.1`).
   - Unicode dot variants (`U+3002`, `U+FF0E`, `U+FF61`).
   - Reserved TLDs: `.localhost`, `.local`, `.internal`, `.lan`, `.home.arpa`, `.invalid`, `.test`, `.example`, `.onion`, `.corp`, `.home`, `.localdomain`, `.intranet`, `.private`, `.arpa`.
3. **DNS Pinning**:
   - Mitigates DNS Rebinding attacks using thread-local monkey patching on `socket.getaddrinfo`.
   - Host and IP resolution are validated once, and socket connections are pinned to the verified IP tuple within `with pinned_dns(...)`.
4. **Redirect Hardening**:
   - `follow_redirects=False` on the HTTP client.
   - Loop re-validates DNS and IP safety on every redirect hop (up to 5).
5. **Resource Limits**:
   - Max response size enforced at 5 MB (`_SCRAPE_MAX_RESPONSE_BYTES = 5 * 1024 * 1024`).
   - Streaming timeout enforced via `SEARXNG_SCRAPE_MAX_DURATION` (default 15s).

---

## 6. Discovered Defect & Vulnerability Catalog

### Summary Table

| ID | Category | Severity | File / Component | Summary Description |
|---|---|---|---|---|
| **ISSUE-01** | Patch Cache | **CRITICAL** | `tools/apply-patches.py` | `_get_tracked_targets()` omits `preferences.py` & `webadapter.py`, causing cache desync and skipped critical patches. |
| **ISSUE-02** | Security / Path Traversal | **HIGH** | `tools/apply-patches.py` | `PatchTransaction.rollback()` accepts arbitrary `orig_path` and `bak_path` from `manifest.json` without path boundary checks. |
| **ISSUE-03** | Security / Path Traversal | **MEDIUM** | `tools/apply-patches.py` | CLI `--report` argument allows arbitrary file write outside repository root. |
| **ISSUE-04** | Security / Windows ACLs | **MEDIUM** | `tools/ensure-secret-key.py` | `os.chmod` is a no-op on Windows NTFS; `config/secret.key` remains readable by all local users. |
| **ISSUE-05** | Security / Concurrency | **MEDIUM** | `tools/ensure-secret-key.py` | Uses predictable static `.tmp` filenames instead of `tempfile.mkstemp`, risking file overwrite / race conditions. |
| **ISSUE-06** | Windows Compatibility | **MEDIUM** | `searx/settings_loader.py` | Quoted `SEARXNG_SETTINGS_PATH` crashes with `EnvironmentError` on Windows. |
| **ISSUE-07** | Stability / Recovery | **MEDIUM** | `tools/sync-upstream.ps1` & `tools/apply-patches.py` | Upstream sync does not invoke `--rollback-on-failure`, leaving site-packages corrupted if a critical patch fails. |
| **ISSUE-08** | Tooling / Data Loss | **LOW** | `tools/clean-cache.ps1` | Silently removes `python\.patches_backup`, permanently destroying manual rollback capability. |
| **ISSUE-09** | Security / Edge Case | **LOW** | `tools/apply-patches.py` (`/scrape`) | Global `httpx.Client` connection pooling could theoretically reuse established sockets across DNS resolutions. |
| **ISSUE-10** | Testing Gap | **LOW** | `tools/test_patches.py` | Missing unit test to verify that all `PATCH_SPECS` targets are tracked by the cache fingerprinting engine. |

---

### Detailed Analysis of Discovered Issues

#### ISSUE-01 (CRITICAL): `_get_tracked_targets()` Omits `preferences.py` & `webadapter.py`
- **Location**: `tools/apply-patches.py`, lines 237–264.
- **Root Cause**: `_get_tracked_targets()` hardcodes a list of 23 paths. However, two recent critical patches were added to `PATCH_SPECS`:
  - Line 2573: `preferences.py (safe category validation & non-fatal parse_dict)`
  - Line 2586: `webadapter.py (safe categories lookup)`
- **Impact**: If upstream files or developer edits modify `preferences.py` or `webadapter.py`, `is_patch_cache_valid()` compares fingerprints only for the hardcoded list. The cache reports `True` (valid), and `tools/apply-patches.py` exits immediately with `"All patches already verified (cached)."`. The critical category safety patches are NEVER reapplied, leading to runtime unhandled exceptions and 500 errors when users search or select custom categories.
- **Remediation**:
  Dynamically derive tracked targets directly from `PATCH_SPECS`:
  ```python
  def _get_tracked_targets() -> list[str]:
      core_targets = {
          os.path.abspath(__file__),
          os.path.join(REPO_ROOT, "tools", "disable-missing-engines.py"),
          os.path.join(REPO_ROOT, "tools", "webui_next.py"),
          os.path.join(REPO_ROOT, "UPSTREAM_VERSION.txt"),
      }
      for spec in PATCH_SPECS:
          core_targets.add(os.path.abspath(spec.target_path))
      return sorted(core_targets)
  ```

---

#### ISSUE-02 (HIGH): Arbitrary File Overwrite via Untrusted Rollback Manifest
- **Location**: `tools/apply-patches.py`, lines 135–149 (`PatchTransaction.rollback`).
- **Root Cause**: `rollback()` parses `manifest.json`:
  ```python
  manifest = json.load(f)
  for orig_path, bak_path in manifest.items():
      if os.path.exists(bak_path):
          content = f.read()
          _atomic_write(orig_path, content, encoding="utf-8", newline="\n")
  ```
  It blindly takes `orig_path` and `bak_path` from JSON and writes the content of `bak_path` to `orig_path`.
- **Impact**: If `manifest.json` is modified by another process or malicious input (e.g. pointing `orig_path` to `C:\Windows\System32\...` or user startup directory), executing `apply-patches.py --rollback` will overwrite arbitrary files.
- **Remediation**:
  Enforce strict path containment before writing:
  1. `orig_path` must resolve strictly within `REPO_ROOT` or `SITE_PACKAGES` and match a known patch target.
  2. `bak_path` must resolve strictly within `self.backup_dir`.

---

#### ISSUE-03 (MEDIUM): Unrestricted CLI `--report` Path Traversal
- **Location**: `tools/apply-patches.py`, lines 2680 & 2793–2804.
- **Root Cause**: The CLI option `--report <path>` passes the argument directly to `_atomic_write(report_path, ...)` without path validation.
- **Impact**: Any arbitrary path on the system writable by the current user can be overwritten with diagnostic JSON data.
- **Remediation**:
  Ensure `report_path` resides within `REPO_ROOT` or an explicitly allowed reports directory:
  ```python
  norm_report = os.path.abspath(report_path)
  if not norm_report.startswith(REPO_ROOT + os.sep):
      raise ValueError("Report output must reside within repository directory.")
  ```

---

#### ISSUE-04 (MEDIUM): POSIX `os.chmod` Does Not Protect `config/secret.key` on Windows
- **Location**: `tools/ensure-secret-key.py`, lines 92–99.
- **Root Cause**:
  ```python
  if hasattr(os, "chmod"):
      os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
  ```
  On Windows NTFS filesystems, `os.chmod` sets or clears the file's read-only flag. It has **no effect** on NTFS access control lists (DACLs). By default, inherited permissions on Windows grant `Users` read permissions.
- **Impact**: On multi-user systems or non-user-profile installations (e.g., `C:\SearXNG`), other local accounts can read `config/secret.key`, compromising HMAC verification, session cookies, and cache authentication.
- **Remediation**:
  On `sys.platform == "win32"`, apply Windows ACL restriction using `icacls.exe`:
  ```python
  if sys.platform == "win32":
      username = os.environ.get("USERNAME")
      if username:
          subprocess.run(
              ["icacls", path, "/inheritance:r", "/grant:r", f"{username}:(R,W)"],
              check=False, capture_output=True,
          )
  ```

---

#### ISSUE-05 (MEDIUM): Predictable Temporary File Names in `ensure-secret-key.py`
- **Location**: `tools/ensure-secret-key.py`, lines 77 & 132.
- **Root Cause**:
  ```python
  tmp_path = f"{path}.tmp"
  with open(tmp_path, "w", encoding="utf-8", newline="\n") as f:
      f.write(key + "\n")
  ```
- **Impact**: Using a fixed `.tmp` name creates a TOCTOU race condition if multiple processes start simultaneously, and allows pre-creation attacks in shared writable directories.
- **Remediation**: Use `tempfile.mkstemp(prefix=".tmp_key_", dir=CONFIG_DIR, text=True)`.

---

#### ISSUE-06 (MEDIUM): Quoted `SEARXNG_SETTINGS_PATH` Crashes `settings_loader.py`
- **Location**: `python/Lib/site-packages/searx/settings_loader.py`, line 101.
- **Root Cause**: If a user or script sets `SEARXNG_SETTINGS_PATH='"C:\path with spaces\settings.yml"'`, `Path(settings_path)` includes the literal double quotes. `Path.is_file()` returns `False`, causing `raise EnvironmentError(1, f"{settings_path} not exists!", settings_path)`.
- **Remediation**: Strip quotes in `settings_loader.py` or launcher script: `settings_path = os.environ["SEARXNG_SETTINGS_PATH"].strip('"\'')`.

---

#### ISSUE-07 (MEDIUM): Upstream Sync Leaves Corrupted Runtime on Critical Patch Failure
- **Location**: `tools/sync-upstream.ps1`, lines 180–186 & lines 272–285.
- **Root Cause**: `sync-upstream.ps1` mirrors upstream files into `python\Lib\site-packages\searx`, then invokes `tools\apply-windows-patches.ps1 --force`. It does NOT pass `--rollback-on-failure`.
- **Impact**: If upstream has breaking changes that cause a `CRITICAL` patch to fail, the files in `site-packages` remain half-patched and half-raw upstream. The SearXNG server will fail to start until manual intervention or manual rollback is performed.
- **Remediation**: Pass `--rollback-on-failure` when invoking `apply-windows-patches.ps1` during automated upstream sync.

---

#### ISSUE-08 (LOW): `clean-cache.ps1` Silently Purges Rollback Backups
- **Location**: `tools/clean-cache.ps1`, line 93.
- **Root Cause**: `Remove-DirectorySafe -DirPath (Join-Path $workspaceRoot "python\.patches_backup")` runs during standard cache cleaning.
- **Impact**: Users running `clean-cache.ps1` lose their safety net. Subsequent `apply-patches.py --rollback` calls report `"no backup manifest found"`.
- **Remediation**: Keep `.patches_backup` during standard clean; only purge when `-Deep` or explicit clean flag is requested.

---

#### ISSUE-09 (LOW): Global `httpx.Client` Keepalive Rebinding Window in `/scrape`
- **Location**: `tools/apply-patches.py` (`patch_webapp_scrape_route`), line 1501.
- **Root Cause**: `_scrape_client = httpx.Client(..., limits=httpx.Limits(max_keepalive_connections=20))` pools keepalive sockets across requests.
- **Impact**: If a domain rapidly alters DNS records, `httpx` might reuse an existing pooled socket established to an earlier IP without invoking `socket.getaddrinfo`, bypassing the thread-local DNS pin for that specific connection.
- **Remediation**: For security-critical scraper requests, disable keepalive by sending `headers={'Connection': 'close'}` or setting `max_keepalive_connections=0` on the scrape client.

---

#### ISSUE-10 (LOW): Missing Unit Test for Cache Target Completeness
- **Location**: `tools/test_patches.py`, `TestPatchCache`.
- **Root Cause**: `test_patches.py` checks cache roundtrip and tampering, but does not verify that `set(spec.target_path for spec in PATCH_SPECS).issubset(_get_tracked_targets())`.
- **Remediation**: Add a unit test asserting that all `spec.target_path` in `PATCH_SPECS` are present in `_get_tracked_targets()`.

---

## 7. Concrete Remediation Proposals

### Proposal 1: Dynamic Cache Target Tracking in `tools/apply-patches.py`

```python
# tools/apply-patches.py

def _get_tracked_targets() -> list[str]:
    """Return all target file paths tracked by the patch cache.
    Dynamically includes all registered PATCH_SPECS targets plus core tools.
    """
    targets = {
        os.path.abspath(__file__),
        os.path.join(REPO_ROOT, "tools", "disable-missing-engines.py"),
        os.path.join(REPO_ROOT, "tools", "webui_next.py"),
        os.path.join(REPO_ROOT, "UPSTREAM_VERSION.txt"),
    }
    for spec in PATCH_SPECS:
        targets.add(os.path.abspath(spec.target_path))
    return sorted(targets)
```

### Proposal 2: Hardened Rollback Path Validation in `tools/apply-patches.py`

```python
# tools/apply-patches.py (inside PatchTransaction.rollback)

        manifest_file = os.path.join(self.backup_dir, "manifest.json")
        if os.path.exists(manifest_file):
            try:
                with open(manifest_file, "r", encoding="utf-8") as f:
                    manifest = json.load(f)
                real_backup_dir = os.path.realpath(self.backup_dir)
                real_repo_root = os.path.realpath(REPO_ROOT)
                allowed_targets = {os.path.realpath(t) for t in _get_tracked_targets()}

                for orig_path, bak_path in manifest.items():
                    norm_orig = os.path.realpath(orig_path)
                    norm_bak = os.path.realpath(bak_path)

                    # Security checks: bak_path must be in backup_dir, orig_path must be a tracked target
                    if not norm_bak.startswith(real_backup_dir + os.sep):
                        logger.error(f"Security error: backup path {bak_path} is outside backup directory. Skipping.")
                        continue
                    if norm_orig not in allowed_targets and not norm_orig.startswith(real_repo_root + os.sep):
                        logger.error(f"Security error: target path {orig_path} is not an authorized target. Skipping.")
                        continue

                    if os.path.exists(norm_bak):
                        with open(norm_bak, "r", encoding="utf-8") as f:
                            content = f.read()
                        _atomic_write(norm_orig, content, encoding="utf-8", newline="\n")
                        restored.append(norm_orig)
            except (OSError, json.JSONDecodeError) as exc:
                logger.error(f"Failed to restore from disk backups: {exc}")
```

### Proposal 3: Secure Temp File Creation in `tools/ensure-secret-key.py`

```python
# tools/ensure-secret-key.py

import tempfile

def _write_key(path: str, key: str) -> bool:
    try:
        config_dir = os.path.dirname(os.path.abspath(path))
        os.makedirs(config_dir, exist_ok=True)
        temp_fd, tmp_path = tempfile.mkstemp(prefix=".tmp_key_", dir=config_dir, text=True)
        with open(temp_fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(key + "\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
    except OSError as exc:
        print(f"[ERROR] Could not write {path}: {exc}", file=sys.stderr)
        return False

    # Lock down permissions
    if sys.platform == "win32":
        username = os.environ.get("USERNAME")
        if username:
            try:
                import subprocess
                subprocess.run(
                    ["icacls", path, "/inheritance:r", "/grant:r", f"{username}:(R,W)"],
                    check=False,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            except Exception:
                pass
    else:
        try:
            if hasattr(os, "chmod"):
                os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
        except OSError:
            pass
    return True
```

---

## 8. Conclusion

The investigation confirms that the Windows integration strategy of `SearXNGforWindowsNext` is fundamentally sound:
- Programmatic AST/regex patching completely avoids requiring Unix `patch` or git binary dependencies on end-user Windows machines.
- The SSRF mitigation engine in `/scrape` is comprehensive, defending against advanced IP encoding tricks and DNS rebinding.
- The 161 unit tests in `tools/test_patches.py` provide an excellent baseline for verifying patch idempotency and regression safety.

Remediating the **10 identified issues**—most critically fixing dynamic cache target tracking (`ISSUE-01`), securing the rollback manifest (`ISSUE-02`), and hardening Windows secret permissions (`ISSUE-04`)—will ensure long-term stability, tamper resilience, and security for the project.
