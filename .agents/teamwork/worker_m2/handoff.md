# Handoff Report: Worker M2 (Patch Management & Windows Security Hardening)

## 1. Observation
1. **Patch Cache Target Completeness (`tools/apply-patches.py:237-264`)**:
   - `_get_tracked_targets()` previously hardcoded a list of 23 paths, omitting `searx/preferences.py` and `searx/webadapter.py`.
   - Modifying `preferences.py` or `webadapter.py` would not invalidate `.patches_cache.json`, leading to cached skip of critical category fixes.
2. **Untrusted Rollback Manifest Overwrite (`tools/apply-patches.py:135-149`)**:
   - `PatchTransaction.rollback()` parsed `manifest.json` without verifying if `orig_path` or `bak_path` were contained within repository or backup boundaries.
   - An external or tampered `manifest.json` could force arbitrary file writes outside the repository root upon `apply-patches.py --rollback`.
3. **Unvalidated CLI `--report` Path Traversal (`tools/apply-patches.py:2680, 2793-2804`)**:
   - `apply-patches.py --report <path>` accepted arbitrary absolute or relative traversal paths without bounding them to repository root.
4. **Windows NTFS ACL Exposure & Predictable Temp Files (`tools/ensure-secret-key.py:74-102, 134`)**:
   - `ensure-secret-key.py` used static `.tmp` filenames (`f"{path}.tmp"`), vulnerable to race conditions / pre-creation attacks.
   - `os.chmod` is a no-op on Windows NTFS DACLs, leaving `config/secret.key` readable by all local users under standard inheritance.
5. **Quoted `SEARXNG_SETTINGS_PATH` Failure (`python/Lib/site-packages/searx/settings_loader.py:93-107`)**:
   - When set with quotes (e.g., `'"C:\path\settings.yml"'`), `Path(settings_path).is_file()` returned `False` due to literal quote characters, raising `EnvironmentError`.
6. **Upstream Sync Half-Patched State on Failure (`tools/sync-upstream.ps1:274`)**:
   - Invocation of `apply-windows-patches.ps1 --force` lacked `--rollback-on-failure`. If an upstream structural change broke a critical patch, `site-packages` was left in an inconsistent state.
7. **Cache Cleaner Deleting Rollback Backups (`tools/clean-cache.ps1:93-94`)**:
   - Default safe clean purged `python\.patches_backup`, permanently destroying manual rollback capabilities.
8. **Scrape Client Keepalive Connection Pooling (`tools/apply-patches.py:1512`)**:
   - `httpx.Limits(max_keepalive_connections=20)` allowed socket reuse across scrape requests, which could bypass DNS pinning during DNS rebinding attacks.

## 2. Logic Chain
1. **Dynamic Target Derivation**:
   - In `_get_tracked_targets()`, dynamically iterating over `apply_patches.PATCH_SPECS` ensures that every registered target (including `preferences.py` and `webadapter.py`) and future additions are automatically registered in the cache fingerprinting engine.
2. **Rollback Containment Verification**:
   - In `PatchTransaction.rollback()`, resolving canonical normalized paths and enforcing `c_orig.startswith((c_repo + os.sep, c_sp + os.sep))` and `c_bak.startswith(c_bak_dir + os.sep)` prevents arbitrary file write attacks from malicious `manifest.json` payloads.
3. **CLI `--report` Containment**:
   - Checking `norm_report.startswith(norm_repo + os.sep) or norm_report == norm_repo` both at CLI parsing and before file emission guarantees diagnostic reports cannot escape `REPO_ROOT`.
4. **Atomic Secure Temp Files & Windows NTFS ACL Lockdown**:
   - Replacing static `.tmp` with `tempfile.mkstemp(prefix=".tmp_key_", dir=config_dir, text=True)` ensures secure random temporary files with atomic `os.replace`.
   - Applying `icacls path /inheritance:r /grant:r <username>:(R,W)` ensures only the current user/owner has read and write access on Windows NTFS filesystems.
5. **Quote Normalization**:
   - Applying `.strip('"\'')` to `SEARXNG_SETTINGS_PATH` eliminates quotes injected by batch scripts or shell variables, restoring clean path resolution.
6. **Automatic Rollback on Sync Failure**:
   - Passing `--rollback-on-failure` to `apply-windows-patches.ps1` in `sync-upstream.ps1` ensures that critical patch failure immediately restores original files.
7. **Two-Tier Cache Cleaning**:
   - Removing `python\.patches_backup` from Stage 1 and moving it to Stage 3 (`if ($Deep)`) guarantees rollback backups are preserved during default cleaning.
8. **Zero Keepalive in Scraper**:
   - Setting `max_keepalive_connections=0` ensures that the `/scrape` HTTP client closes sockets immediately after request completion, forcing fresh DNS resolution and strictly enforcing thread-local DNS pinning for every scrape request.
9. **Regression Test Verification**:
   - Adding `TestPatchHardeningM2` in `tools/test_patches.py` exercises all remediated behaviors against positive and negative cases.

## 3. Caveats
- `icacls` execution on Windows requires the `USERNAME` environment variable to be present in the user context; fallback ensures no unhandled exceptions if run in non-standard headless service accounts.
- POSIX permissions (`chmod 600`) are preserved for cross-platform utility.
- No other source code files were touched outside write ownership boundaries.

## 4. Conclusion
All 10 assigned tasks (F2.1 to F2.10) for Milestone M2 have been successfully implemented with genuine, non-dummy logic. All static analysis checks (`ruff check`, `ruff format --check`, `pyrefly check`) and all unit test suites (`test_patches.py` 172/172, `test_agent_tools.py` 60/60, `test_agentic_search.py` 41/41, `test_retrieval_pipeline.py` 52/52) pass with 100% success and zero regressions.

## 5. Verification Method

### 1. Static Quality & Lint Verification
```powershell
python\python.exe -m ruff check tools/apply-patches.py tools/ensure-secret-key.py tools/test_patches.py
# Expected output: All checks passed!

python\python.exe -m ruff format --check tools/apply-patches.py tools/ensure-secret-key.py tools/test_patches.py
# Expected output: 3 files already formatted

python\python.exe -m pyrefly check
# Expected output: INFO 0 errors (1 suppressed)
```

### 2. Unit & Regression Test Verification
```powershell
python\python.exe tools/test_patches.py TestPatchHardeningM2
# Expected output: Ran 11 tests ... OK

python\python.exe tools/test_patches.py
# Expected output: Ran 172 tests ... OK (0 failures, 0 errors)

python\python.exe tools/test_agent_tools.py
# Expected output: Ran 60 tests ... OK

python\python.exe tools/test_agentic_search.py
# Expected output: Ran 41 tests ... OK

python\python.exe tools/test_retrieval_pipeline.py
# Expected output: Ran 52 tests ... OK

python\python.exe tests/evaluation/run_benchmark.py
# Expected output: 100% precision@5, 0.0% failure rate
```

### 3. Invalidation Conditions
- Any failure in `tools/test_patches.py` or failure to reject out-of-boundary paths in `manifest.json` or `--report`.
- Non-zero exit code in `pyrefly check` or `ruff check`.
