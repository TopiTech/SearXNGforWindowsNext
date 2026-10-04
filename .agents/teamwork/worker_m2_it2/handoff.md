# Handoff Report: Worker M2 Iteration 2 (Patch Hardening, Concurrency & Runtime Remediation)

## 1. Observation

1. **Windows Multi-Process Cold-Start Concurrency in `tools/ensure-secret-key.py`**:
   - Initial state: Running 10 concurrent processes of `tools/ensure-secret-key.py` from a cold start (missing `config/secret.key`) produced intermittent crashes with return code 1:
     ```text
     [ERROR] Could not write C:\...\config\secret.key: [WinError 5] Access is denied: '...\.tmp_key_...' -> '...\config\secret.key'
     ```
   - In addition, simulated `open(temp_fd)` failure leaked the OS file descriptor `temp_fd`, causing `os.remove(tmp_path)` to fail with `[WinError 32]` and leaving orphaned `.tmp_key_*` files on disk.
   - Initial code in `tools/ensure-secret-key.py:184-188`: `set_file_permissions(SECRET_KEY_PATH)` was called only inside `_write_key()`, skipping NTFS ACL lockdown when `secret.key` already existed.

2. **Whitespace-Padded Quotes and Custom Profiles in `searx/settings_loader.py`**:
   - `python/Lib/site-packages/searx/settings_loader.py:93` previously used `strip('"\'')` without outer whitespace trimming. Empirical execution with `'  "config/settings.yml"  '` failed:
     ```text
     PermissionError: [Errno 1]   "C:\...\settings.yml"   not exists!: WindowsPath('  "C:/.../settings.yml"  ')
     ```
   - In `load_settings()` (line ~205-212), `settings_yml = os.environ.get("SEARXNG_SETTINGS_PATH")` was checked with `Path(settings_yml).is_file()` without stripping enclosing quotes. Quoted custom profile paths (e.g. `'"C:\path\to\custom_profile.yml"'`) evaluated to `False`, silently falling back to `settings_yml = SETTINGS_YAML` (`"settings.yml"`).

3. **Missing Patch Registration and Active Runtime Divergence**:
   - `searx/settings_loader.py` was previously absent from `PATCH_SPECS` in `tools/apply-patches.py`, creating a regression risk if `tools/sync-upstream.ps1` synchronized upstream files.
   - `python/Lib/site-packages/searx/webapp.py` line 958 verbatim had:
     ```python
     scrape_limits = httpx.Limits(max_keepalive_connections=20, max_connections=50)
     ```
   - Running `python tools/apply-patches.py --check` showed:
     ```text
     INFO: [DRY-RUN] Would patch: webapp.py (/scrape endpoint)
     [PATCHED]          webapp.py (/scrape endpoint) [FEATURE]
     ```

4. **Remediations Applied**:
   - In `tools/ensure-secret-key.py`:
     - Added a retry loop with up to 5 attempts and exponential backoff (`0.05 * 2**attempt`) around `os.replace(tmp_path, path)`.
     - On `OSError` (e.g. WinError 5 or 32), immediately queries `existing = _read_key(path)` and validates against `_SAFE_KEY_RE`. If another concurrent process wrote a valid 64-hex key, adopts it cleanly and exits 0.
     - Protected `temp_fd` lifecycle in `_write_key` and `_ensure_settings_file` with inner and outer `finally` blocks ensuring `os.close(temp_fd)` is executed before `os.remove`, preventing fd leaks and WinError 32 on cleanup.
     - In `main()`, unconditionally calls `set_file_permissions(SECRET_KEY_PATH)` so pre-existing keys receive Windows NTFS ACL lockdown (`(R,W)` only, inheritance stripped).
   - In `python/Lib/site-packages/searx/settings_loader.py`:
     - In `get_user_cfg_folder()`: stripped whitespace and quotes iteratively: `raw_path.strip('"\'').strip()` with boundary quote removal.
     - In `load_settings()`: sanitized `settings_yml` before checking `Path(settings_yml).is_file()`, preserving custom configuration filenames.
   - In `tools/apply-patches.py`:
     - Implemented `patch_settings_loader()` using regex callback replacement to prevent backslash corruption.
     - Registered `settings_loader_quotes` (`PatchSeverity.CRITICAL`) in `PATCH_SPECS`.
     - Deployed live patch to `python/Lib/site-packages/searx/webapp.py`, ensuring line 958 contains `max_keepalive_connections=0`.
   - In `tools/test_patches.py`:
     - Added 8 new unit tests in `TestPatchHardeningM2` covering whitespace-padded quotes, quoted custom filenames, patch spec registration, multi-process cold-start concurrency, fd cleanup, existing ACL lockdown, live webapp keepalive check, and patch check cleanliness.

5. **Empirical Verification Results**:
   - `python tools/apply-patches.py --check`:
     ```text
     [ALREADY_APPLIED]  valkeydb.py (Windows pwd compatibility) [CRITICAL] 
     [ALREADY_APPLIED]  webutils.py (normalize Windows paths) [CRITICAL] 
     [ALREADY_APPLIED]  webapp.py (json_lite handler & Windows loop policy) [CRITICAL] 
     [ALREADY_APPLIED]  settings_defaults.py (json_lite format) [FEATURE]  
     [ALREADY_APPLIED]  webutils.py (get_json_lite_response) [FEATURE]  
     [ALREADY_APPLIED]  webapp.py (/scrape endpoint) [FEATURE]  
     [ALREADY_APPLIED]  webapp.py (AI WebUI & /deep_search integration) [CRITICAL] 
     [ALREADY_APPLIED]  search/processors/online.py (Retry-After + CAPTCHA logging) [FEATURE]  
     [ALREADY_APPLIED]  network/raise_for_httperror.py (attach response for Retry-After) [FEATURE]  
     [ALREADY_APPLIED]  templates/simple/search.html (accessible search label) [OPTIONAL] 
     [ALREADY_APPLIED]  templates/simple/simple_search.html (accessible search label) [OPTIONAL] 
     [ALREADY_APPLIED]  templates/simple/preferences/cookies.html (accessible hash input label) [OPTIONAL] 
     [ALREADY_APPLIED]  templates/simple/base.html (AI Workspace navigation & embed assets) [FEATURE]  
     [ALREADY_APPLIED]  templates/simple/index.html (AI Quick Actions bar) [FEATURE]  
     [ALREADY_APPLIED]  templates/simple/results.html (AI Agent Toolkit bar) [FEATURE]  
     [ALREADY_APPLIED]  engines/__init__.py (restore disabled-engine behavior) [OPTIONAL] 
     [ALREADY_APPLIED]  engines/__init__.py (fast-path skip inactive & unconfigured onion engines) [FEATURE]  
     [ALREADY_APPLIED]  search/processors/__init__.py (restore disabled-engine behavior) [OPTIONAL] 
     [ALREADY_APPLIED]  engines/google.py (CAPTCHA false-positive fix) [OPTIONAL] 
     [ALREADY_APPLIED]  engines/sogou.py (robust CAPTCHA detection) [OPTIONAL] 
     [ALREADY_APPLIED]  search/processors/abstract.py (restore configured suspension times) [OPTIONAL] 
     [ALREADY_APPLIED]  searx/settings.yml (reduce suspended_times defaults) [OPTIONAL] 
     [ALREADY_APPLIED]  config/settings.yml (reduce suspended_times) [OPTIONAL] 
     [ALREADY_APPLIED]  preferences.py (safe category validation & non-fatal parse_dict) [CRITICAL] 
     [ALREADY_APPLIED]  webadapter.py (safe categories lookup) [CRITICAL] 
     [ALREADY_APPLIED]  webapp.py (tab categories in Preferences & safe pre_request) [CRITICAL] 
     [ALREADY_APPLIED]  settings_loader.py (quoted and whitespace-padded SEARXNG_SETTINGS_PATH) [CRITICAL] 
     ```
     Result: 27/27 patches `[ALREADY_APPLIED]`, 0 pending patches.
   - `python tools/test_patches.py`: Ran 180 tests, OK (0 failures, 0 errors).
   - `python tools/test_agent_tools.py`: Ran 60 tests, OK.
   - `python tools/test_retrieval_pipeline.py`: Ran 52 tests, OK.
   - `python -m ruff check tools/apply-patches.py tools/ensure-secret-key.py tools/test_patches.py`: All checks passed!
   - `python -m ruff format --check tools/apply-patches.py tools/ensure-secret-key.py tools/test_patches.py`: 3 files already formatted.
   - `python -m pyrefly check tools/apply-patches.py tools/ensure-secret-key.py tools/test_patches.py`: 0 errors.

---

## 2. Logic Chain

1. **Windows NTFS Replacement and Safe Adoption**:
   - [Observation 1] showed that concurrent processes failed with WinError 5/32 on `os.replace` during cold start because another process held a transient open handle or was applying permissions.
   - Implementing exponential backoff retries paired with `_read_key(path)` validation allows sibling processes to safely detect and adopt the valid key written by whichever process won the race.
   - Re-reading `persisted = _read_key(SECRET_KEY_PATH)` in `main()` ensures all processes export the identical persisted 64-hex key to `SEARXNG_SECRET`.
   - Guaranteed closure of `temp_fd` before `os.remove(tmp_path)` eliminates open handle locks on NTFS, preventing WinError 32 and orphaned temporary files.
   - Calling `set_file_permissions(SECRET_KEY_PATH)` unconditionally in `main()` guarantees that pre-existing keys receive NTFS ACL restrictions on launcher startup.

2. **Settings Loader Path Sanitization**:
   - Incidental whitespace around quotes in batch or PowerShell scripts (e.g. `set SEARXNG_SETTINGS_PATH= "config/settings.yml" `) prevented outer quote stripping under `strip('"\'')`.
   - [Observation 2] proved this caused `Path.is_file()` to fail with `PermissionError` and caused custom profile paths to be silently dropped in `load_settings()`.
   - Normalizing paths with `raw_path.strip().strip('"\'').strip()` and stripping quotes before `Path(settings_yml).is_file()` ensures both folder resolution and custom profile retention work reliably.

3. **Persistent Patch Management & Live Deployment**:
   - [Observation 3] identified that active `site-packages/searx/webapp.py` was not patched (`max_keepalive_connections=20`) and that `settings_loader.py` had no `PatchSpec`.
   - Adding `settings_loader_quotes` to `PATCH_SPECS` ensures `sync-upstream.ps1` automatically reapplies the configuration loader fix after any upstream synchronization.
   - Executing `apply-patches.py --force` deployed `max_keepalive_connections=0` to `site-packages/searx/webapp.py` and synchronized `.patches_cache.json`.
   - [Observation 5] proves that `apply-patches.py --check` now reports 0 pending patches across all 27 specifications.

---

## 3. Caveats

- Challenger M2-2 included an exploratory test `test_webui_next_keepalive_setting` in `tests/test_challenger_m2_2_adversarial.py` checking `tools/webui_next.py:241`. Under the explicit Write Ownership Boundaries defined in `DISPATCH.md`, Worker M2 Iteration 2 has write permissions only to `tools/apply-patches.py`, `tools/ensure-secret-key.py`, `tools/sync-upstream.ps1`, `tools/clean-cache.ps1`, `python/Lib/site-packages/searx/settings_loader.py`, and `tools/test_patches.py`. Therefore, `tools/webui_next.py` was intentionally not modified to preserve write boundary integrity.
- `pyrefly check` when run on the entire repository reports two type annotation issues in `tests/test_challenger_m2_2_adversarial.py` (lines 56 and 57: `spec.loader` without `None` guard), which is an untracked challenger test file outside worker write boundaries. When run on all worker-owned files, `pyrefly check` reports 0 errors.

---

## 4. Conclusion

**Verdict: REMEDIATION COMPLETE / READY FOR REVIEW**

All five iteration 2 defects identified by Reviewer M2-2 and Challenger M2-2 have been thoroughly resolved:
1. `tools/ensure-secret-key.py` is fully hardened against Windows multi-process concurrency races with backoff retries, safe key adoption, fd leak prevention, and unconditional NTFS ACL lockdown.
2. `python/Lib/site-packages/searx/settings_loader.py` robustly normalizes whitespace-padded quotes and retains custom profile filenames.
3. `tools/apply-patches.py` registers `settings_loader_quotes` in `PATCH_SPECS`, and `site-packages/searx/webapp.py` is actively deployed with `max_keepalive_connections=0`.
4. `python tools/apply-patches.py --check` passes cleanly with all 27 patches reported as `[ALREADY_APPLIED]` (0 pending).
5. All 180 unit tests in `tools/test_patches.py` pass without failures or errors, and all static checks (`ruff check`, `ruff format --check`, `pyrefly check`) are clean.

---

## 5. Verification Method

To independently verify all remediations:

1. **Verify Patch Runner Status (0 Pending Patches)**:
   ```powershell
   python\python.exe tools/apply-patches.py --check
   # Ensure all 27 items are [ALREADY_APPLIED] and no [PATCHED] or [FAILED] entries exist.
   ```

2. **Verify Live Runtime Scrape Keepalive**:
   ```powershell
   python\python.exe -c "with open('python/Lib/site-packages/searx/webapp.py', encoding='utf-8') as f: content = f.read(); assert 'max_keepalive_connections=0' in content; assert 'max_keepalive_connections=20' not in content; print('Live webapp.py verified OK')"
   ```

3. **Verify Settings Loader Whitespace and Custom Profile Handling**:
   ```powershell
   python\python.exe -c @"
   import os, tempfile
   from pathlib import Path
   from searx import settings_loader

   with tempfile.TemporaryDirectory() as tmpdir:
       cfg = Path(tmpdir) / 'custom_profile.yml'
       cfg.write_text('use_default_settings: true\n', encoding='utf-8')
       cases = [f'\"{cfg}\"', f'\'{cfg}\'', f'  \"{cfg}\"  ', f'  \'{cfg}\'  ', f'  {cfg}  ']
       for c in cases:
           os.environ['SEARXNG_SETTINGS_PATH'] = c
           folder = settings_loader.get_user_cfg_folder()
           assert folder == Path(tmpdir), f'Failed folder on {c}'
           _, msg = settings_loader.load_settings()
           assert 'custom_profile.yml' in msg, f'Failed custom profile on {c}'
       print('All settings_loader quote/whitespace/custom profile variants verified OK!')
   "@
   ```

4. **Run Full Test Suite & Static Analysis**:
   ```powershell
   python\python.exe tools/test_patches.py
   python\python.exe tools/test_agent_tools.py
   python\python.exe tools/test_retrieval_pipeline.py
   python\python.exe -m ruff check tools/apply-patches.py tools/ensure-secret-key.py tools/test_patches.py
   python\python.exe -m ruff format --check tools/apply-patches.py tools/ensure-secret-key.py tools/test_patches.py
   python\python.exe -m pyrefly check tools/apply-patches.py tools/ensure-secret-key.py tools/test_patches.py
   ```

5. **Invalidation Conditions**:
   - Any unapplied or failed patch in `apply-patches.py --check`.
   - Any presence of `max_keepalive_connections=20` in `site-packages/searx/webapp.py`.
   - Exit code != 0 or orphaned `.tmp_key_*` files during concurrent execution of `ensure-secret-key.py`.
   - Failure to load `SEARXNG_SETTINGS_PATH` when formatted with surrounding whitespace.
