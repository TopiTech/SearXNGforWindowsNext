# Handoff Report: Reviewer M2-2 (Windows Integration & Patch Conformance Reviewer)

## 1. Observation

1. **Unapplied Scrape Keepalive Patch in Active Runtime (`python/Lib/site-packages/searx/webapp.py:958`)**:
   - `python/Lib/site-packages/searx/webapp.py` line 958 verbatim:
     ```python
     scrape_limits = httpx.Limits(max_keepalive_connections=20, max_connections=50)
     ```
   - Running `python\python.exe tools/apply-patches.py --check` produces:
     ```text
     INFO: [DRY-RUN] Would patch: webapp.py (/scrape endpoint)
     ...
     [PATCHED]          webapp.py (/scrape endpoint) [FEATURE]
     ```
   - Running `python\python.exe tools/apply-patches.py` without arguments produces:
     ```text
     INFO: All patches already verified (cached).
     ```
   - Because `python/.patches_cache.json` holds the updated timestamp for `tools/apply-patches.py` while retaining `searx/webapp.py`'s old hash, the caching layer falsely reports all patches verified, silently leaving `webapp.py` unpatched with `max_keepalive_connections=20` in the live server runtime.

2. **Facade Unit Test in `tools/test_patches.py:3629-3635`**:
   - In `tools/test_patches.py`:
     ```python
     def test_scrape_client_keepalive_hardening(self):
         """F2.9: Verify patch_webapp_scrape_route sets max_keepalive_connections=0."""
         sample = "import warnings\nfrom flask import Flask\n\n@app.route('/search')\ndef search():\n    pass\n"
         patched = apply_patches.patch_webapp_scrape_route(sample, "webapp.py")
         self.assertIn("max_keepalive_connections=0", patched)
         self.assertNotIn("max_keepalive_connections=20", patched)
     ```
   - The test only verifies in-memory string output of the patch generator against a 4-line dummy string. It does not check that `python/Lib/site-packages/searx/webapp.py` actually has `max_keepalive_connections=0`, nor does it verify that `apply-patches.py --check` passes cleanly without pending patches.

3. **`settings_loader.py` Fails on Surrounding Whitespace (`python/Lib/site-packages/searx/settings_loader.py:93`)**:
   - Line 93 verbatim:
     ```python
     settings_path = os.environ.get("SEARXNG_SETTINGS_PATH", "").strip('"\'')
     ```
   - When tested empirically with surrounding whitespace:
     ```powershell
     python\python.exe -c "import os; from searx import settings_loader; os.environ['SEARXNG_SETTINGS_PATH'] = '  \"config/settings.yml.example\"  '; settings_loader.get_user_cfg_folder()"
     ```
   - Result:
     ```text
     PermissionError: [Errno 1]   "C:\Users\mibu0\Documents\develop\SearXNGforWindowsNext\config\settings.yml.example"   not exists!: WindowsPath('  "C:/Users/mibu0/Documents/develop/SearXNGforWindowsNext/config/settings.yml.example"  ')
     ```
   - `strip('"\'')` only strips quotes if they are at the outermost character boundaries. Surrounding spaces prevent quote stripping, and internal spaces after quote stripping cause Windows path resolution to fail.

4. **`settings_loader.py` Omitted from `tools/apply-patches.py` (`tools/sync-upstream.ps1:184`)**:
   - In `tools/sync-upstream.ps1`:
     ```powershell
     Sync-MirrorItem -Src $srcSearx -Dst (Join-Path $sitePackages "searx")
     ```
   - `Sync-MirrorItem` purges `python\Lib\site-packages\searx\` and copies the upstream SearXNG repository contents.
   - `PATCH_SPECS` in `tools/apply-patches.py` has no entry for `settings_loader.py`.
   - Any execution of `sync-upstream.ps1` will permanently overwrite `settings_loader.py` with upstream's unpatched version, wiping out the `SEARXNG_SETTINGS_PATH` quote fix.

5. **Existing `secret.key` Permissions Untouched (`tools/ensure-secret-key.py:184-198`)**:
   - Line 184-188 verbatim:
     ```python
     existing = _read_key(SECRET_KEY_PATH)
     if existing and _SAFE_KEY_RE.fullmatch(existing):
         key = existing
     else:
         key = _generate_key()
         if not _write_key(SECRET_KEY_PATH, key):
             return 1
     ```
   - `set_file_permissions(SECRET_KEY_PATH)` is only called inside `_write_key()`.
   - If `config/secret.key` already exists, `set_file_permissions()` is never invoked, leaving pre-existing keys with loose NTFS ACLs readable by other local accounts.

6. **PowerShell Argument Forwarding & Rollback (`tools/sync-upstream.ps1:274`)**:
   - Line 274: `& (Join-Path $repoRoot "tools\apply-windows-patches.ps1") --force --rollback-on-failure`.
   - `tools/apply-windows-patches.ps1:18` forwards `@args` to `tools/apply-patches.py`.
   - `apply-patches.py:2760-2764` properly intercepts critical failure and invokes `transaction.rollback()`.

7. **Multi-Tier Cache Cleaner Retention (`tools/clean-cache.ps1:89, 145-151`)**:
   - Stage 1.4 no longer purges `python\.patches_backup`.
   - Stage 3.3 purges `python\.patches_backup` only when `-Deep` is supplied.
   - Tested empirically: creating `python\.patches_backup\manifest_test.json` and running `.\tools\clean-cache.ps1` confirmed that the backup directory is preserved on standard clean.

8. **Test Suite Execution**:
   - `python\python.exe tools/test_patches.py`: Ran 172 tests, OK (0 failures, 0 errors).
   - `python\python.exe tools/test_agent_tools.py`: Ran 60 tests, OK.
   - `python\python.exe tools/test_retrieval_pipeline.py`: Ran 52 tests, OK.
   - `ruff check`: All checks passed.
   - `ruff format --check`: 3 files already formatted.

---

## 2. Logic Chain

1. **Active SSRF Risk via Unapplied Patch**:
   - [Observation 1] shows that `python/Lib/site-packages/searx/webapp.py` still contains `max_keepalive_connections=20`.
   - [Observation 1] further shows that `apply-patches.py --check` flags `webapp.py (/scrape endpoint)` as needing to be patched (`[PATCHED]`), but default `apply-patches.py` skips it due to a cached fingerprint mismatch.
   - [Observation 2] shows that `test_scrape_client_keepalive_hardening` only tested an artificial string, creating false confidence while the live runtime remained unpatched.
   - Therefore, the requirement (F2.9) to disable keepalive pooling in `/scrape` was not effectively delivered to the runtime environment.

2. **Whitespace Fragility in Configuration Loading**:
   - Dispatch instruction 2 explicitly required: "verify quote stripping handles double quotes, single quotes, and surrounding whitespace."
   - [Observation 3] demonstrates that `settings_path = os.environ.get("SEARXNG_SETTINGS_PATH", "").strip('"\'')` fails when any whitespace surrounds the quotes or the path.
   - Batch scripts and PowerShell environment setups frequently introduce incidental whitespace (e.g. `set SEARXNG_SETTINGS_PATH= "C:\settings.yml" `).
   - Because `strip('"\'')` only strips quotes at character indices 0 and -1, whitespace causes quotes to remain intact, causing `Path.is_file()` to fail and crash server startup.
   - Applying `settings_path.strip().strip('"\'').strip()` eliminates leading/trailing whitespace, quotes, and internal whitespace reliably.

3. **Loss of Fix on Upstream Sync**:
   - [Observation 4] reveals that `settings_loader.py` was edited directly in `site-packages` without a corresponding `PatchSpec` in `apply-patches.py`.
   - When an administrator runs `sync-upstream.ps1`, `Sync-MirrorItem` wipes `site-packages/searx` and re-applies patches from `apply-patches.py`.
   - Because `settings_loader.py` is not in `PATCH_SPECS`, the fix will be permanently wiped on the next sync.
   - Therefore, `settings_loader.py` must either be patched programmatically via `apply-patches.py` or preserved during upstream sync.

4. **Security Gap in Existing Key Permissions**:
   - [Observation 5] shows that existing keys are read and accepted without running `set_file_permissions(SECRET_KEY_PATH)`.
   - Systems upgraded from previous versions will retain existing permissions on `config/secret.key`.
   - Moving `set_file_permissions(SECRET_KEY_PATH)` to run unconditionally in `main()` ensures all existing installations benefit from NTFS ACL lockdown.

5. **Operational Verification**:
   - [Observations 6 and 7] confirm that `sync-upstream.ps1` and `clean-cache.ps1` correctly implement their assigned specifications (F2.7 and F2.8).

---

## 3. Caveats

- The pyrefly type-check failure was caused by untracked exploratory test files created by peer agents (`tests/test_challenger_m2.py`), not by code under Worker M2 write ownership. Project files under `tools/` and `python/` pass lint and format cleanly.
- `icacls` lockdown requires Windows NTFS filesystem semantics; FAT32 or exFAT partitions will ignore ACL inheritance removal.

---

## 4. Conclusion

**Verdict: REQUEST_CHANGES**

Milestone M2 cannot be approved in its current state due to two high-impact defects and two integration gaps:

1. **[CRITICAL / CONFORMANCE DEFECT] Unapplied `/scrape` Keepalive Patch in Active Runtime**:
   - `python/Lib/site-packages/searx/webapp.py` was never patched with `max_keepalive_connections=0` (line 958 still has `20`).
   - `.patches_cache.json` falsely claims the patch state is cached, preventing default `apply-patches.py` from updating `webapp.py`.
   - `test_scrape_client_keepalive_hardening` must be updated to verify the live file in addition to the patch generator.
   - Worker M2 must run `apply-patches.py --force` (or apply the patch) to update `webapp.py` and synchronize `.patches_cache.json`.

2. **[MAJOR] Incomplete Whitespace Handling in `settings_loader.py`**:
   - `os.environ.get("SEARXNG_SETTINGS_PATH", "").strip('"\'')` crashes on surrounding whitespace.
   - Must be updated to `settings_path.strip().strip('"\'').strip()` and accompanied by test cases covering leading/trailing whitespace around quotes.

3. **[MAJOR] Missing Patch Registration for `settings_loader.py`**:
   - `settings_loader.py` must be added as a patch in `tools/apply-patches.py:PATCH_SPECS` so it survives `sync-upstream.ps1`.

4. **[MINOR] Existing Secret Key NTFS ACL Lockdown**:
   - Call `set_file_permissions(SECRET_KEY_PATH)` unconditionally in `tools/ensure-secret-key.py:main()` so existing keys are secured on launch.

---

## 5. Verification Method

To verify the remediations:

1. **Verify Live Runtime Scrape Keepalive**:
   ```powershell
   python\python.exe -c "with open('python/Lib/site-packages/searx/webapp.py', encoding='utf-8') as f: content = f.read(); assert 'max_keepalive_connections=0' in content; assert 'max_keepalive_connections=20' not in content; print('Live webapp.py verified OK')"
   ```
2. **Verify Patch Runner Status (No Pending Patches)**:
   ```powershell
   python\python.exe tools/apply-patches.py --check
   # Ensure zero [PATCHED] or [FAILED] entries are printed (all must be [ALREADY_APPLIED])
   ```
3. **Verify Settings Loader Whitespace Handling**:
   ```powershell
   python\python.exe -c @"
   import os, tempfile
   from unittest import mock
   from searx import settings_loader

   with tempfile.NamedTemporaryFile(suffix='.yml', delete=False) as f:
       f.write(b'use_default_settings: true\n')
       cfg_path = f.name
   try:
       cases = [f'\"{cfg_path}\"', f'\'{cfg_path}\'', f'  \"{cfg_path}\"  ', f'  \'{cfg_path}\'  ', f'  {cfg_path}  ']
       for c in cases:
           with mock.patch.dict(os.environ, {'SEARXNG_SETTINGS_PATH': c}):
               res = settings_loader.get_user_cfg_folder()
               assert res is not None, f'Failed on case: {c}'
       print('All quote and whitespace variants passed!')
   finally:
       os.remove(cfg_path)
   "@
   ```
4. **Run Project Test Suites**:
   ```powershell
   python\python.exe tools/test_patches.py
   python\python.exe tools/test_agent_tools.py
   python\python.exe tools/test_retrieval_pipeline.py
   ```
5. **Invalidation Conditions**:
   - Any instance of `max_keepalive_connections=20` remaining in `python/Lib/site-packages/searx/webapp.py`.
   - `apply-patches.py --check` reporting `[PATCHED]` instead of `[ALREADY_APPLIED]`.
   - Failure to load `SEARXNG_SETTINGS_PATH` when formatted with surrounding whitespace.
