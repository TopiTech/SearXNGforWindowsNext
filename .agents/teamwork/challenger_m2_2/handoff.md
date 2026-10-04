# Handoff Report: Challenger M2-2 (Windows ACL & Concurrency Stress Challenger)

## Challenge Summary

**Overall risk assessment**: **HIGH**
**Verdict**: **REJECT**

Milestone M2 cannot be approved in its current state due to five reproducible empirical defects across Windows file concurrency, settings loader environment variable handling, temp file resource management, and unapplied patch deployment in `site-packages`.

---

## 1. Observation

### Observation 1: Whitespace-Padded Quoted Paths in `settings_loader.py`
- **File**: `python/Lib/site-packages/searx/settings_loader.py:93`
- **Code**:
  ```python
  settings_path = os.environ.get("SEARXNG_SETTINGS_PATH", "").strip('"\'')
  ```
- **Execution**: When `SEARXNG_SETTINGS_PATH` contains whitespace surrounding quotes (e.g. ` "C:\path\to\settings.yml" ` or ` 'C:\path\to\settings.yml' `):
- **Verbatim Error**:
  ```text
  PermissionError: [Errno 1]   "C:\Users\mibu0\AppData\Local\Temp\tmpcdrsg54x\settings.yml"   not exists!: WindowsPath('  "C:/Users/mibu0/AppData/Local/Temp/tmpcdrsg54x/settings.yml"  ')
  ```
- `.strip('"\'')` only strips characters from the string boundaries. Because the outer characters are spaces, the quotes are not stripped, and the path fails resolution.

### Observation 2: Quoted Custom Filename Profiles Silently Ignored in `settings_loader.py`
- **File**: `python/Lib/site-packages/searx/settings_loader.py:205-211`
- **Code**:
  ```python
  settings_yml = os.environ.get("SEARXNG_SETTINGS_PATH")
  if settings_yml and Path(settings_yml).is_file():
      # see get_user_cfg_folder() --> SEARXNG_SETTINGS_PATH points to a file
      settings_yml = Path(settings_yml).name
  else:
      # see get_user_cfg_folder() --> SEARXNG_SETTINGS_PATH points to a folder
      settings_yml = SETTINGS_YAML
  ```
- **Execution**: When `SEARXNG_SETTINGS_PATH` points to a quoted custom file profile (e.g. `SEARXNG_SETTINGS_PATH = '"C:\path\to\custom_profile.yml"'`):
- `get_user_cfg_folder()` successfully resolves the folder `C:\path\to`, but `load_settings()` reads raw unstripped `os.environ.get("SEARXNG_SETTINGS_PATH")`.
- `Path('"C:\path\to\custom_profile.yml"').is_file()` returns `False` due to literal quotation marks.
- The execution unconditionally branches into `else: settings_yml = SETTINGS_YAML` (`"settings.yml"`), silently disregarding the user's custom configuration file!
- **Verbatim Error**:
  ```text
  AssertionError: 'custom_profile.yml' not found in 'merge the default settings (.../searx/settings.yml) and the user settings (.../settings.yml)'
  ```

### Observation 3: Multi-Process Cold-Start Concurrency Crash in `ensure-secret-key.py`
- **File**: `tools/ensure-secret-key.py:108, 189-190`
- **Code**:
  ```python
  os.replace(tmp_path, path)
  ...
  if not _write_key(SECRET_KEY_PATH, key):
      return 1
  ```
- **Execution**: When 10 concurrent processes run `tools/ensure-secret-key.py` from cold start (`secret.key` does not yet exist):
- **Verbatim Error**:
  ```text
  [DEBUG] Multiprocess results: exit codes=[0, 1, 0, 1, 0, 0, 0, 1, 0, 0]
  [ERROR] Could not write C:\...\config\secret.key: [WinError 5] Access is denied: 'C:\...\.tmp_key_zb933ogc' -> 'C:\...\config\secret.key'
  ```
- 3 to 4 out of 10 concurrent processes fail with exit code 1.
- In `SearXNG for Windows.bat`: `for /f "delims=" %%K in ('python tools\ensure-secret-key.py') do set "SEARXNG_SECRET=%%K"`. When the command exits 1, `SEARXNG_SECRET` is left empty or unassigned.

### Observation 4: File Descriptor Resource Leak and Orphaned Temp Files on Write Failure
- **File**: `tools/ensure-secret-key.py:99-120`
- **Code**:
  ```python
  temp_fd, tmp_path = tempfile.mkstemp(prefix=".tmp_key_", dir=config_dir, text=True)
  try:
      with open(temp_fd, "w", encoding="utf-8", newline="\n") as f:
          f.write(key + "\n")
          ...
      os.replace(tmp_path, path)
  finally:
      if os.path.exists(tmp_path):
          try:
              os.remove(tmp_path)
          except OSError:
              pass
  ```
- **Execution**: If opening `temp_fd` fails or raises an OS error, `temp_fd` is never closed.
- On Windows NTFS, an open file descriptor cannot be deleted. Calling `os.remove(tmp_path)` in the `finally` block raises `PermissionError: [WinError 32]`.
- The exception is silently ignored by `except OSError: pass`, leaving orphaned `.tmp_key_*` files permanently on disk.
- Identical pattern exists in `_ensure_settings_file:158` (`.tmp_settings_*`).

### Observation 5: Scrape Route Keepalive Fix Unapplied in Active `site-packages` Environment
- **File**: `python/Lib/site-packages/searx/webapp.py:958`
- **Active Code**:
  ```python
  scrape_limits = httpx.Limits(max_keepalive_connections=20, max_connections=50)
  ```
- **Execution**: Worker M2 edited `tools/apply-patches.py:1507` and anchor tests in `tools/test_patches.py:3630`, but never executed `tools/apply-patches.py` against `site-packages`.
- **Command Output** (`python tools/apply-patches.py --check`):
  ```text
  INFO: [DRY-RUN] Would patch: webapp.py (/scrape endpoint)
  ```
- In addition, `tools/webui_next.py:241` still specifies `max_keepalive_connections=20`.
- Socket behavior verification with `KeepaliveTrackingHandler`:
  - `max_keepalive_connections=20`: client ports `[53576, 53576]` (socket reused across requests).
  - `max_keepalive_connections=0`: client ports `[53577, 53578]` (socket closed after request).
  - The live application remains configured for socket reuse (`20`).

---

## 2. Logic Chain

1. **Settings Loader Incomplete Normalization**:
   - In `get_user_cfg_folder()`, `s.strip('"\'')` relies on exact string boundaries. Whitespace before/after quotes prevents stripping, directly contradicting task F2.6 and dispatch instructions.
   - In `load_settings()`, `os.environ.get("SEARXNG_SETTINGS_PATH")` is read without stripping quotes. `Path(quoted_string).is_file()` returns `False`, causing custom profile paths to silently fail and fall back to default `settings.yml`.
2. **Windows NTFS File Replacement Semantics**:
   - On Windows NTFS, `os.replace` is not non-blocking when other handles to the destination exist or when `icacls` is being executed. WinError 5 (`ERROR_ACCESS_DENIED`) or WinError 32 (`ERROR_SHARING_VIOLATION`) occurs when multiple processes attempt concurrent replacement.
   - `ensure-secret-key.py` treats any failure in `os.replace` as fatal and exits with code 1 instead of retrying `_read_key(SECRET_KEY_PATH)` with backoff to reuse the already-written key.
3. **Descriptor Lifecycle & Windows Deletion Semantics**:
   - `tempfile.mkstemp` returns a low-level OS file descriptor (`int`). If an error occurs before descriptor ownership is transferred or if `open()` fails, the descriptor remains open.
   - On Windows, POSIX unlinking is not supported while a handle is open. `os.remove` fails with WinError 32, leaving persistent orphaned `.tmp_key_*` and `.tmp_settings_*` files.
4. **Site-Packages Patch State Divergence**:
   - Merely editing patcher strings in `tools/apply-patches.py` does not alter the installed runtime in `python/Lib/site-packages/`.
   - Running `apply-patches.py --check` proves `webapp.py (/scrape endpoint)` is currently unpatched in the deployment environment.

---

## 3. Caveats

- In single-process sequential execution where `secret.key` already exists, `tools/ensure-secret-key.py` reuses the existing key without race conditions. The race condition manifests specifically during cold-start or key rotation when multiple instances are started simultaneously.
- When `USERNAME` is present and valid, `icacls` properly restricts permissions (`(R,W)` only, inheritance stripped). If `USERNAME` is an invalid SID, `icacls` fails with error 1332 and leaves default inheritance.

---

## 4. Conclusion & Actionable Recommendations

**Verdict**: **REJECT**

The following fixes must be implemented by the Milestone 2 worker:

1. **`python/Lib/site-packages/searx/settings_loader.py`**:
   - In `get_user_cfg_folder()`: strip whitespace before and after stripping quotes:
     ```python
     raw_path = os.environ.get("SEARXNG_SETTINGS_PATH", "").strip()
     settings_path = raw_path.strip('"\'').strip()
     ```
   - In `load_settings()`: apply the exact same sanitization to `settings_yml`:
     ```python
     settings_yml = os.environ.get("SEARXNG_SETTINGS_PATH", "").strip().strip('"\'').strip()
     ```
2. **`tools/ensure-secret-key.py`**:
   - Add concurrency retry logic in `_write_key` / `main()`: if `os.replace` fails with `OSError`, poll `_read_key(SECRET_KEY_PATH)` with short exponential backoff (e.g. 5 attempts with 50ms sleep). If a valid 64-character key was written by a sibling process, adopt it and return 0.
   - Wrap `temp_fd` lifecycle safely:
     ```python
     temp_fd, tmp_path = tempfile.mkstemp(prefix=".tmp_key_", dir=config_dir, text=True)
     try:
         try:
             with open(temp_fd, "w", encoding="utf-8", newline="\n") as f:
                 f.write(key + "\n")
                 f.flush()
                 try:
                     os.fsync(f.fileno())
                 except (AttributeError, OSError):
                     pass
         except Exception:
             try:
                 os.close(temp_fd)
             except OSError:
                 pass
             raise
         os.replace(tmp_path, path)
     finally:
         if os.path.exists(tmp_path):
             try:
                 os.remove(tmp_path)
             except OSError:
                 pass
     ```
   - Apply identical descriptor protection to `_ensure_settings_file`.
3. **Patch Application & Site-Packages Alignment**:
   - Run `python tools/apply-patches.py --force` to deploy `max_keepalive_connections=0` to `python/Lib/site-packages/searx/webapp.py`.
   - Update `tools/webui_next.py:241` to `max_keepalive_connections=0`.

---

## 5. Verification Method

Independent reproduction commands using the committed adversarial test suite:

```powershell
# 1. Run Challenger M2-2 Empirical Adversarial Suite (14 tests covering all dispatch areas)
python\python.exe tests/test_challenger_m2_2_adversarial.py

# Expected current result:
# FAILED (failures=5, errors=2)
# - test_whitespace_padded_double_quotes: ERROR (PermissionError / EnvironmentError)
# - test_whitespace_padded_single_quotes: ERROR (PermissionError / EnvironmentError)
# - test_custom_filename_with_quotes: FAIL (custom_profile.yml ignored)
# - test_multiprocess_concurrent_key_generation: FAIL (exit code 1, WinError 5)
# - test_fd_leak_on_open_failure_adversarial: FAIL (orphaned temp file leaked)
# - test_deployed_site_packages_webapp_keepalive_setting: FAIL (site-packages has 20, not 0)
# - test_webui_next_keepalive_setting: FAIL (webui_next.py has 20, not 0)

# 2. Invalidation Condition
# A pass condition requires all 14 tests in tests/test_challenger_m2_2_adversarial.py to succeed with 0 failures and 0 errors.
```
