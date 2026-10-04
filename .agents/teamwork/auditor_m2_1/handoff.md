# Forensic Audit Report: Milestone M2 (Patch Management & Windows Security Hardening)

**Work Product**: Worker M2 code changes across `tools/apply-patches.py`, `tools/ensure-secret-key.py`, `tools/sync-upstream.ps1`, `tools/clean-cache.ps1`, `python/Lib/site-packages/searx/settings_loader.py`, and `tools/test_patches.py`  
**Profile**: General Project  
**Integrity Mode**: Development (per `ORIGINAL_REQUEST.md:8`)  
**Verdict**: **CLEAN**

---

## 1. Observation

### 1.1 Source Code Analysis (Phase 1 & Phase 2)
1. **Dynamic Patch Target Derivation (`tools/apply-patches.py:257-270`)**:
   - Replaced static 23-element list with dynamic generator iterating over `apply_patches.PATCH_SPECS`:
     ```python
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
   - Zero hardcoded target counts or dummy static checks. Automatically tracks `preferences.py` and `webadapter.py`.

2. **Rollback Path Traversal Hardening (`tools/apply-patches.py:122-169`)**:
   - In `PatchTransaction.rollback()`, enforced canonical boundary containment:
     ```python
     norm_orig = os.path.abspath(orig_path)
     norm_bak = os.path.abspath(bak_path)
     c_orig = os.path.normcase(norm_orig)
     c_bak = os.path.normcase(norm_bak)

     if not c_orig.startswith((c_repo + os.sep, c_sp + os.sep)):
         logger.error("Security violation: rollback target %s outside permitted boundaries", orig_path)
         continue
     if not c_bak.startswith(c_bak_dir + os.sep):
         logger.error("Security violation: backup file %s outside backup directory", bak_path)
         continue
     ```
   - Both destination (`norm_orig`) and source (`norm_bak`) are checked before `_atomic_write` is invoked.

3. **CLI `--report` Boundary Enforcement (`tools/apply-patches.py:2692-2699, 2808-2815`)**:
   - Both at CLI parsing time and report write time, checked:
     ```python
     if not (c_report.startswith(c_repo + os.sep) or c_report == c_repo):
         raise ValueError("Report output must reside within repository directory.")
     ```
   - Prohibits path traversal attacks directing reports outside `REPO_ROOT`.

4. **Cryptographic Key & Settings Atomic Creation with NTFS ACL Lockdown (`tools/ensure-secret-key.py:74-126, 158-169`)**:
   - Replaced predictable `.tmp` paths with `tempfile.mkstemp(prefix=".tmp_key_", dir=config_dir, text=True)` and `tempfile.mkstemp(prefix=".tmp_settings_", dir=CONFIG_DIR, text=True)`.
   - Implemented `set_file_permissions(path: str)`:
     ```python
     if sys.platform == "win32":
         username = os.environ.get("USERNAME")
         if username:
             subprocess.run(
                 ["icacls", path, "/inheritance:r", "/grant:r", f"{username}:(R,W)"],
                 check=False,
                 capture_output=True,
             )
     ```
   - Live test confirmed: `icacls` successfully set `DESKTOP-EIUL89C\mibu0:(R,W)` with inheritance disabled (`0` failures).

5. **Settings Path Quote Normalization (`python/Lib/site-packages/searx/settings_loader.py:93`)**:
   - Strips single and double quotes from `SEARXNG_SETTINGS_PATH`:
     ```python
     settings_path = os.environ.get("SEARXNG_SETTINGS_PATH", "").strip('"\'')
     ```
   - Resolves valid configuration directory without raising `EnvironmentError` when paths are quoted.

6. **Upstream Sync Rollback Integration (`tools/sync-upstream.ps1:274`)**:
   - Added `--rollback-on-failure` to `apply-windows-patches.ps1 --force`.
   - Passed cleanly through to `apply-patches.py` which triggers `transaction.rollback()` upon critical patch failure.

7. **Two-Tier Cache Clean Rollback Retention (`tools/clean-cache.ps1:90-93, 145-151`)**:
   - Removed `python\.patches_backup` deletion from default Stage 1 cleaning.
   - Preserves rollback capability in normal runs, only deleting backups under `-Deep` mode (Stage 3.3).

8. **Scrape Client Keepalive Socket Disabling (`tools/apply-patches.py:1107, 1507`)**:
   - Configured `httpx.Limits(max_keepalive_connections=0, max_connections=50)` in both patch verification strings and patch replacement body.

### 1.2 Test Suite Audit (`tools/test_patches.py:3438-3635`)
1. **Zero Test Skips / Commented-Out Tests**:
   - Grep search for `skip`, `skipIf`, and `unittest.skip` yielded 0 results in `tools/test_patches.py`.
2. **Zero Mock Bypasses**:
   - Mocks in `TestPatchHardeningM2` are used exclusively for cross-platform isolation (`sys.platform`), temporary filesystem roots (`REPO_ROOT`), and error logging verification (`logger.error`).
   - `tempfile.mkstemp` is inspected via `wraps=tempfile.mkstemp`, preserving real filesystem execution.
3. **11 Genuine Unit Tests Added**:
   - `test_cache_tracked_targets_completeness`: Validates dynamic tracking of all `PATCH_SPECS` targets.
   - `test_rollback_path_traversal_orig_path_rejected`: Validates rollback aborts on untrusted target.
   - `test_rollback_path_traversal_bak_path_rejected`: Validates rollback aborts on out-of-boundary backup source.
   - `test_rollback_legitimate_target_restored`: Validates authorized files are accurately restored.
   - `test_cli_report_path_traversal_rejected`: Validates `ValueError` on traversal `--report`.
   - `test_cli_report_path_valid_accepted`: Validates valid `--report` generation.
   - `test_ensure_secret_key_mkstemp_usage`: Validates random temp file creation and atomic replacement.
   - `test_ensure_secret_key_icacls_permissions_on_windows`: Validates Windows `icacls` call pattern.
   - `test_ensure_secret_key_posix_permissions`: Validates POSIX `0o600` permissions.
   - `test_settings_loader_quoted_path_stripped`: Validates single and double quote stripping.
   - `test_scrape_client_keepalive_hardening`: Validates `max_keepalive_connections=0` in scrape patch.

### 1.3 Behavioral Execution Proof
- **Ruff linter**:
  `python\python.exe -m ruff check tools/apply-patches.py tools/ensure-secret-key.py tools/test_patches.py` -> `All checks passed!`
- **Ruff formatter**:
  `python\python.exe -m ruff format --check tools/apply-patches.py tools/ensure-secret-key.py tools/test_patches.py` -> `3 files already formatted`
- **Pyrefly type checker**:
  `python\python.exe -m pyrefly check` -> `INFO 0 errors (1 suppressed)`
- **M2 Regression Tests**:
  `python\python.exe tools/test_patches.py TestPatchHardeningM2` -> `Ran 11 tests in 0.180s ... OK`
- **Full Test Suite `test_patches.py`**:
  `Ran: 172, Failures: 0, Errors: 0, Skipped: 0` -> 100% PASS
- **All Adjacent Suites**:
  - `tools/test_agent_tools.py`: `Ran 60 tests ... OK`
  - `tools/test_agentic_search.py`: `Ran 41 tests ... OK`
  - `tools/test_retrieval_pipeline.py`: `Ran 52 tests ... OK`
  - `tests/evaluation/run_benchmark.py`: `100% precision@5, 0.0% failure rate`

---

## 2. Logic Chain
1. **Dynamic Target Derivation** in `_get_tracked_targets()` references the authoritative `PATCH_SPECS` data structure directly, eliminating synchronization lag between registered patches and cache fingerprints.
2. **Boundary Containment** in `PatchTransaction.rollback()` and `--report` resolves canonical paths and enforces prefix containment with directory separator bounding (`+ os.sep`), which mathematically prevents prefix collision attacks and directory traversal (`..`) exploits.
3. **Atomic File Creation & Access Control** in `ensure-secret-key.py` uses OS kernel random descriptors (`mkstemp`) in the target directory, preventing symbolic link / race exploits, followed by `icacls` which strips inherited permissions and locks the DACL to the executing user.
4. **Quote Normalization** in `settings_loader.py` uses `.strip('"\'')`, which correctly normalizes string inputs without altering valid Windows path delimiters.
5. **Regression Test Integrity**: The 11 new tests in `tools/test_patches.py` execute the real functions under positive and hostile conditions, proving genuine defect remediation with zero mocks bypassing core logic.
6. **No Regressions**: All 172 patch tests and 153 adjacent unit tests pass cleanly with zero errors and zero skipped tests.

---

## 3. Caveats
- No caveats. The audit directly tested and verified every change against live system execution on Windows NTFS.

---

## 4. Conclusion
Worker M2's implementation exhibits complete technical integrity, adheres strictly to write boundaries, contains zero facade patterns or hardcoded test shortcuts, introduces zero test suppressions, and passes all static and empirical behavioral checks. The verdict is **CLEAN**.

---

## 5. Verification Method

To independently reproduce the forensic verification findings:

```powershell
# 1. Static Linting & Type Analysis
python\python.exe -m ruff check tools/apply-patches.py tools/ensure-secret-key.py tools/test_patches.py
python\python.exe -m ruff format --check tools/apply-patches.py tools/ensure-secret-key.py tools/test_patches.py
python\python.exe -m pyrefly check

# 2. Targeted M2 Regression Tests (11 tests)
python\python.exe tools/test_patches.py TestPatchHardeningM2

# 3. Full Patches Test Suite (172 tests)
python\python.exe -c "import sys, io; sys.path.insert(0, 'tools'); import unittest, test_patches; loader = unittest.TestLoader(); suite = loader.loadTestsFromModule(test_patches); runner = unittest.TextTestRunner(verbosity=1); res = runner.run(suite); sys.exit(0 if res.wasSuccessful() else 1)"

# 4. Adjacent Suites & Evaluation Benchmark
python\python.exe tools/test_agent_tools.py
python\python.exe tools/test_agentic_search.py
python\python.exe tools/test_retrieval_pipeline.py
python\python.exe tests/evaluation/run_benchmark.py
```

### Invalidation Conditions
- Any test failure in `TestPatchHardeningM2` or regression in `test_patches.py` (172 tests).
- Any failure of `PatchTransaction.rollback` to reject out-of-boundary paths in `manifest.json`.
- Any failure of `apply-patches.py` to reject `--report` paths outside `REPO_ROOT`.
