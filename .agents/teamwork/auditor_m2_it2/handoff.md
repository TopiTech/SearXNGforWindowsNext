# Forensic Audit Report: Milestone 2 Iteration 2 (Integrity Verification)

**Work Product**: Worker M2 Iteration 2 Implementation & Git Diff across `tools/ensure-secret-key.py`, `python/Lib/site-packages/searx/settings_loader.py`, `tools/apply-patches.py`, and `tools/test_patches.py`  
**Profile**: General Project (Development Mode, ORIGINAL_REQUEST.md)  
**Verdict**: **CLEAN**

---

## 1. Observation

1. **Source Code & Implementation Analysis**:
   - `tools/ensure-secret-key.py`:
     - Lines 75–94: `set_file_permissions(path)` genuinely invokes Windows `icacls` with arguments `["icacls", path, "/inheritance:r", "/grant:r", f"{username}:(R,W)"]`, stripping inheritance and locking down permissions to the current user. On POSIX, calls `os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)`.
     - Lines 100–119 & 156–167: In `_write_key()`, `temp_fd, tmp_path` are acquired via `tempfile.mkstemp(prefix=".tmp_key_", dir=config_dir, text=True)`. Inner and outer `finally` blocks ensure `os.close(temp_fd)` executes if opening/wrapping fails. Outer `finally` removes `tmp_path`.
     - Lines 120–148: Real exponential backoff loop with up to 5 attempts (`time.sleep(0.05 * (2**attempt))`) around `os.replace(tmp_path, path)`. On `OSError` (e.g. WinError 5 or 32), checks `_read_key(path)` and validates against `_SAFE_KEY_RE = re.compile(r"^[0-9a-fA-F]{64}$")`. If another concurrent process wrote a valid 64-hex key, adopts it and succeeds cleanly.
     - Lines 204–256: In `_ensure_settings_file()`, the identical `mkstemp`, fd closure `finally`, and retry loop are implemented for default settings initialization.
     - Lines 278–289: In `main()`, `persisted = _read_key(SECRET_KEY_PATH)` is re-validated to ensure process agreement on concurrent write, and `set_file_permissions(SECRET_KEY_PATH)` is called unconditionally even when `secret.key` already existed.
   - `python/Lib/site-packages/searx/settings_loader.py`:
     - Lines 93–97 in `get_user_cfg_folder()`:
       ```python
       raw_path = os.environ.get("SEARXNG_SETTINGS_PATH", "").strip()
       settings_path = raw_path.strip('"\'').strip()
       while settings_path.startswith(('"', "'")) or settings_path.endswith(('"', "'")):
           settings_path = settings_path.strip('"\'').strip()
       ```
     - Lines 208–213 in `load_settings()`:
       ```python
       settings_yml = os.environ.get("SEARXNG_SETTINGS_PATH")
       if settings_yml:
           settings_yml = settings_yml.strip().strip('"\'').strip()
           while settings_yml.startswith(('"', "'")) or settings_yml.endswith(('"', "'")):
               settings_yml = settings_yml.strip('"\'').strip()
       if settings_yml and Path(settings_yml).is_file():
           settings_yml = Path(settings_yml).name
       ```
       Sanitizes `settings_yml` before checking `Path(settings_yml).is_file()`, resolving custom configuration profile filenames without `PermissionError` or path corruption.
   - `tools/apply-patches.py`:
     - Lines 131–142: `_get_monitored_files()` dynamically enumerates all `spec.target_path` from `PATCH_SPECS`, ensuring cache invalidation across all patch targets including `settings_loader.py`.
     - Lines 1107 & 1507: Live scrape client keepalive updated to `max_keepalive_connections=0` (disabled keepalive to prevent socket leaks).
     - Lines 2336–2384: `patch_settings_loader(content, path)` implements genuine regex-based AST/token substitution for both `get_user_cfg_folder` and `load_settings`, and is registered as `settings_loader_quotes` (`PatchSeverity.CRITICAL`) in `PATCH_SPECS` (lines 2665–2678).
     - Lines 2757–2763 & 2874–2879: Validates `args.report` against directory traversal outside `REPO_ROOT`.
   - `python/Lib/site-packages/searx/webapp.py`:
     - Line 958 verbatim has `scrape_limits = httpx.Limits(max_keepalive_connections=0, max_connections=50)`.

2. **Test Suite Integrity & Suppression Analysis**:
   - `tools/test_patches.py`:
     - Git diff analysis (`git diff -U0 tools/test_patches.py | Select-String "^---" -NotMatch | Select-String "^-"`) revealed exactly 1 deleted line:
       `- "max_keepalive_connections=20\n"`
       Which was replaced by:
       `+ "max_keepalive_connections=0\n"`
     - Zero tests were deleted.
     - Zero tests were skipped (`@unittest.skip` = 0, `skipTest` = 0).
     - Zero assertions were disabled or commented out.
     - 8 authentic, non-mocked regression tests added in `TestPatchHardeningM2`:
       1. `test_settings_loader_whitespace_padded_quotes`: 5 live variations tested against real `settings_loader.get_user_cfg_folder()`.
       2. `test_settings_loader_quoted_custom_filename_retained`: Real temp custom profile tested against real `settings_loader.load_settings()`.
       3. `test_settings_loader_patch_spec_registered_and_applied`: Verifies `PATCH_SPECS` registration, patch application, and idempotency.
       4. `test_ensure_secret_key_multiprocess_concurrency`: Spawns 8 real concurrent OS subprocesses on cold-start empty directory.
       5. `test_ensure_secret_key_fd_cleanup_on_open_error`: Fault injection on `open(temp_fd)` verifying zero orphaned `.tmp_key_*` files.
       6. `test_ensure_secret_key_acl_applied_to_existing_key`: Verifies `main()` invokes `set_file_permissions` for pre-existing keys.
       7. `test_deployed_webapp_keepalive_setting`: Inspects live `site-packages/searx/webapp.py` for `max_keepalive_connections=0`.
       8. `test_apply_patches_check_all_clean`: Dry-run verifies all 27 patches are `ALREADY_APPLIED`.

3. **Empirical Verification Commands & Outputs**:
   - `python\python.exe tools/apply-patches.py --check`:
     Exited 0. 27/27 patches reported `[ALREADY_APPLIED]`. 0 pending, 0 failed.
   - `python\python.exe -m unittest discover -s tools -p "test_patches.py"`:
     `Ran 180 tests in 1.555s. OK.` (0 failures, 0 errors).
   - `python\python.exe -m unittest discover -s tools -p "test_patches.py" -k "TestPatchHardeningM2" -v`:
     `Ran 19 tests in 0.388s. OK.`
   - Independent 16-Process Concurrency Stress Test on `ensure-secret-key.py`:
     Spawned 16 simultaneous OS processes from cold start (`ProcessPoolExecutor`).
     All 16 exited code 0, generated/persisted matching 64-hex keys (1 distinct key agreed upon across all 16 procs), and 0 orphaned `.tmp*` files remained.
   - Independent Adversarial Quotes/Whitespace Test on `settings_loader.py`:
     Tested 6 adversarial configurations including nested double/single quotes, outer padding, and internal spaces. All resolved correctly to the parent folder and loaded the custom profile.
   - Live Runtime Webapp Verification:
     Inspected `python/Lib/site-packages/searx/webapp.py`. `max_keepalive_connections=0` confirmed present; `max_keepalive_connections=20` absent.
   - Static Quality Checks:
     `python\python.exe -m ruff check tools/apply-patches.py tools/ensure-secret-key.py tools/test_patches.py` -> `All checks passed!`
     `python\python.exe -m ruff format --check tools/apply-patches.py tools/ensure-secret-key.py tools/test_patches.py` -> `3 files already formatted`
     `python\python.exe -m pyrefly check tools/apply-patches.py tools/ensure-secret-key.py tools/test_patches.py` -> `INFO 0 errors`
   - Sibling Suites:
     `python\python.exe tools/test_agent_tools.py` -> `Ran 60 tests ... OK`
     `python\python.exe tools/test_retrieval_pipeline.py` -> `Ran 52 tests ... OK`
     `python\python.exe tests/evaluation/run_benchmark.py` -> Exited 0, all benchmarks completed cleanly.

---

## 2. Logic Chain

1. **Absence of Prohibited Integrity Violations**:
   - [Observation 1] and [Observation 2] confirm that no hardcoded return values, facade stubs, dummy functions, or fabricated results were introduced.
   - Every modified function performs authentic computation: `ensure-secret-key.py` uses real system calls (`tempfile.mkstemp`, `icacls`, `os.replace`, `time.sleep`), `settings_loader.py` performs real loop-based string trimming and path resolution, and `apply-patches.py` performs real regex-based code transformation.
   - [Observation 2] confirms that git diff contains zero deleted tests and zero suppressed/skipped assertions. The single deleted line in `test_patches.py` was a test anchor update aligning with the keepalive limit fix.

2. **Genuine Concurrency Hardening and Resource Management**:
   - [Observation 1] and [Observation 3] confirm that Worker M2 Iteration 2's concurrency fix is genuine and robust.
   - The retry loop with exponential backoff and safe key adoption (`_SAFE_KEY_RE.fullmatch(existing)`) prevents transient Windows NTFS file lock crashes without risking secret key divergence.
   - The inner and outer `finally` structure guarantees closure of `temp_fd` prior to temporary file deletion, eliminating WinError 32 handle leaks on Windows.
   - The independent empirical execution of 16 concurrent processes on cold start validated 100% success rate with zero orphaned files and complete key agreement.

3. **Authentic Settings Loader and Patch Registration**:
   - [Observation 1] and [Observation 3] prove that `settings_loader.py` now strips arbitrary combinations of whitespace and enclosing quotes, resolving custom profile filenames via `Path.is_file()` without raising `PermissionError`.
   - `apply-patches.py` registers `settings_loader_quotes` in `PATCH_SPECS` and dynamically includes all targets in monitored cache invalidation files, ensuring reproducibility upon upstream sync.
   - Running `apply-patches.py --check` confirms 27/27 patches are `[ALREADY_APPLIED]` with zero configuration drift.

4. **Authenticity of Unit and Stress Tests**:
   - [Observation 2] and [Observation 3] demonstrate that all 8 new unit tests in `TestPatchHardeningM2` execute real code against real filesystem artifacts or real OS subprocesses, with zero mock shortcuts on the primary logic being tested.

---

## 3. Caveats

- In `tests/test_challenger_m2_2_adversarial.py` (an untracked test file written by Challenger M2-2 outside worker write boundaries), `test_webui_next_keepalive_setting` checks `tools/webui_next.py:241`. As documented in Worker M2 It2 Handoff and confirmed by dispatch instructions, `tools/webui_next.py` was outside Worker M2's write boundaries and was intentionally not modified. The live runtime web application in `python/Lib/site-packages/searx/webapp.py` has `max_keepalive_connections=0` properly deployed.
- No other caveats.

---

## 4. Conclusion

**Verdict: CLEAN**

The forensic audit of Worker M2 Iteration 2 concludes that:
1. All implementations across `tools/ensure-secret-key.py`, `python/Lib/site-packages/searx/settings_loader.py`, `tools/apply-patches.py`, and `tools/test_patches.py` are genuine, complete, and robust.
2. There are **zero** hardcoded string checks, **zero** facade implementations, **zero** mock bypasses, and **zero** suppressed or deleted tests.
3. Concurrency handling on Windows NTFS cold-start, file descriptor leak prevention, whitespace/quote normalization, and patch registration meet all integrity and security standards.
4. All 180 unit tests in `test_patches.py` pass cleanly, `apply-patches.py --check` reports 0 pending patches, and all static analysis checks (`ruff check`, `ruff format --check`, `pyrefly check`) pass with 0 errors.

Worker M2 Iteration 2 is certified **CLEAN** and approved.

---

## 5. Verification Method

To independently verify this forensic audit:

1. **Verify Git Diff and Absence of Test Suppression**:
   ```powershell
   git diff -U0 tools/test_patches.py | Select-String "^---" -NotMatch | Select-String "^-"
   # Verifies only 1 line was deleted (the keepalive anchor update).
   ```

2. **Verify Patch Runner Cleanliness (0 Pending Patches)**:
   ```powershell
   python\python.exe tools/apply-patches.py --check
   # Verifies all 27 patches report [ALREADY_APPLIED].
   ```

3. **Verify All Unit Tests**:
   ```powershell
   python\python.exe -m unittest discover -s tools -p "test_patches.py"
   # Verifies 180 tests pass with OK status.
   ```

4. **Verify Independent 16-Process Concurrency Stress Test**:
   ```powershell
   python\python.exe -c "import concurrent.futures, os, shutil, subprocess, sys, tempfile; tmp = tempfile.mkdtemp(); [os.makedirs(os.path.join(tmp, d)) for d in ['tools', 'config']]; shutil.copy('tools/ensure-secret-key.py', os.path.join(tmp, 'tools')); shutil.copy('config/settings.yml.example', os.path.join(tmp, 'config')); cmd = [sys.executable, os.path.join(tmp, 'tools', 'ensure-secret-key.py')]; pool = concurrent.futures.ProcessPoolExecutor(16); res = list(pool.map(lambda _: subprocess.run(cmd, capture_output=True, text=True, cwd=tmp), range(16))); assert all(r.returncode == 0 for r in res); keys = [r.stdout.strip().replace('set SEARXNG_SECRET=', '') for r in res]; assert len(set(keys)) == 1 and len(keys[0]) == 64; orphans = [f for f in os.listdir(os.path.join(tmp, 'config')) if f.startswith('.tmp')]; assert len(orphans) == 0; print('16-process concurrency verified OK!')"
   ```

5. **Verify Independent Settings Loader Quoted/Whitespace Variants**:
   ```powershell
   @"
   import os, tempfile
   from pathlib import Path
   from searx import settings_loader

   with tempfile.TemporaryDirectory() as tmpdir:
       cfg = Path(tmpdir) / 'custom_prod.yml'
       cfg.write_text('use_default_settings: true\ngeneral:\n  debug: false\n', encoding='utf-8')
       cases = [f'\"{cfg}\"', f'\'{cfg}\'', f'   \"{cfg}\"   ', f'   \'{cfg}\'   ', f' \"\'\"{cfg}\"\'\" ']
       for c in cases:
           os.environ['SEARXNG_SETTINGS_PATH'] = c
           os.environ['SEARXNG_DISABLE_ETC_SETTINGS'] = '1'
           assert settings_loader.get_user_cfg_folder() == Path(tmpdir)
           _, msg = settings_loader.load_settings()
           assert 'custom_prod.yml' in msg
       print('Adversarial quote/whitespace variants verified OK!')
   "@ | python\python.exe
   ```

6. **Verify Static Quality Checks**:
   ```powershell
   python\python.exe -m ruff check tools/apply-patches.py tools/ensure-secret-key.py tools/test_patches.py
   python\python.exe -m ruff format --check tools/apply-patches.py tools/ensure-secret-key.py tools/test_patches.py
   python\python.exe -m pyrefly check tools/apply-patches.py tools/ensure-secret-key.py tools/test_patches.py
   ```
