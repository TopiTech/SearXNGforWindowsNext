# Dispatch: Worker M2 Iteration 2 (Patch Hardening, Concurrency & Runtime Remediation)

## Working Directory
`c:\Users\mibu0\Documents\develop\SearXNGforWindowsNext\.agents\teamwork\worker_m2_it2\`

## Authoritative Context Documents
1. `ORIGINAL_REQUEST.md`: `c:\Users\mibu0\Documents\develop\SearXNGforWindowsNext\.agents\teamwork\ORIGINAL_REQUEST.md`
2. `PROJECT.md`: `c:\Users\mibu0\Documents\develop\SearXNGforWindowsNext\.agents\teamwork\orchestrator\PROJECT.md`
3. Gate Failure Status: `c:\Users\mibu0\Documents\develop\SearXNGforWindowsNext\.agents\teamwork\orchestrator\GATE_STATUS.md`
4. Reviewer M2-2 Report: `c:\Users\mibu0\Documents\develop\SearXNGforWindowsNext\.agents\teamwork\reviewer_m2_2\handoff.md`
5. Challenger M2-2 Report: `c:\Users\mibu0\Documents\develop\SearXNGforWindowsNext\.agents\teamwork\challenger_m2_2\handoff.md`

## MANDATORY INTEGRITY WARNING
DO NOT CHEAT. All implementations must be genuine. DO NOT hardcode test results, create dummy/facade implementations, or circumvent the intended task. A teamwork_preview_auditor will independently verify your work. Integrity violations WILL be detected and your work WILL be rejected.

## Write Ownership Boundaries
You have EXCLUSIVE write ownership to:
- `tools/apply-patches.py`
- `tools/ensure-secret-key.py`
- `tools/sync-upstream.ps1`
- `tools/clean-cache.ps1`
- `python/Lib/site-packages/searx/settings_loader.py`
- `tools/test_patches.py`
Do NOT edit any other source code files. (Target files in `site-packages` may be updated via `apply-patches.py`).

## Assigned Technical Tasks for Iteration 2

### 1. `tools/ensure-secret-key.py`: Multi-Process Concurrency & Windows File Locking
- In `_write_key(path, key)`:
  - Add retry loop with exponential backoff around `os.replace(tmp_path, path)` (up to 5 attempts, `time.sleep(0.05 * 2**attempt)`).
  - If `os.replace` fails with `OSError` (`[WinError 5]` Access is denied or `[WinError 32]` Sharing violation):
    Immediately check if another concurrent process has already written a valid key by calling `existing = _read_key(path)`.
    If `existing and _SAFE_KEY_RE.fullmatch(existing)`: clean up `tmp_path` and return `True` (adoption of concurrent key).
- In `tempfile.mkstemp` descriptor handling in `_write_key` and `_ensure_settings_file`:
  - Track descriptor closure so that `os.close(temp_fd)` is guaranteed before `os.remove(tmp_path)` in `finally`, preventing WinError 32 and orphaned `.tmp_key_*` or `.tmp_settings_*` files.
- In `main()`:
  - Unconditionally invoke `set_file_permissions(SECRET_KEY_PATH)` even when reading an existing key, ensuring that pre-existing keys have their NTFS ACLs locked down.

### 2. `python/Lib/site-packages/searx/settings_loader.py`: Whitespace & Profile Normalization
- In `get_user_cfg_folder()`:
  - Normalize path with:
    ```python
    raw_path = os.environ.get("SEARXNG_SETTINGS_PATH", "").strip()
    settings_path = raw_path.strip('"\'').strip()
    ```
- In `load_settings()` (lines ~205-212):
  - Strip quotes and whitespace on `settings_yml` before checking `Path(settings_yml).is_file()`:
    ```python
    settings_yml = os.environ.get("SEARXNG_SETTINGS_PATH")
    if settings_yml:
        settings_yml = settings_yml.strip().strip('"\'').strip()
    if settings_yml and Path(settings_yml).is_file():
        settings_yml = Path(settings_yml).name
    else:
        settings_yml = SETTINGS_YAML
    ```

### 3. `tools/apply-patches.py`: Register Settings Loader Patch & Deploy Live Patches
- Register a patch spec in `PATCH_SPECS` for `searx/settings_loader.py` so that `sync-upstream.ps1` and automated patch workflows reapply the `SEARXNG_SETTINGS_PATH` quote and whitespace normalization automatically.
- Ensure `python/Lib/site-packages/searx/webapp.py` is actually patched so line ~958 contains `max_keepalive_connections=0`.
- Verify with `python\python.exe tools/apply-patches.py --check` that `[DRY-RUN] Would patch` is empty and all patches are verified clean.

### 4. `tools/test_patches.py`: Expand Regression Tests in `TestPatchHardeningM2`
- Add unit tests verifying:
  - Whitespace-padded quoted settings paths (e.g. `' "config/settings.yml" '`) resolve correctly without `PermissionError` or `EnvironmentError`.
  - Quoted custom filenames (e.g. `'"C:\path\to\custom.yml"'`) correctly retain `custom.yml` in `load_settings()`.
  - Multi-process concurrency simulation of `ensure-secret-key.py` exits 0 with 0 orphaned `.tmp_key_*` files.
  - Existing key permissions are updated by `ensure-secret-key.py`.
  - `python\python.exe tools/apply-patches.py --check` passes cleanly with zero unapplied patches.

### 5. Verification Requirements
- `python\python.exe -m ruff check tools/apply-patches.py tools/ensure-secret-key.py tools/test_patches.py`
- `python\python.exe -m ruff format --check tools/apply-patches.py tools/ensure-secret-key.py tools/test_patches.py`
- `python\python.exe -m pyrefly check`
- `python\python.exe tools/test_patches.py` (all tests pass)
- `python\python.exe tools/apply-patches.py --check` (0 pending patches)

## Completion Criteria
1. All 4 items implemented cleanly.
2. All unit tests pass.
3. Update `progress.md` with `Last visited: [timestamp]` header.
4. Produce `handoff.md` with detailed verification outputs and diff summary.
5. Send a message to orchestrator upon completion.

## 2026-10-04T05:09:52Z
Message received from parent (2da8fdd6-dc63-4790-a432-5c307d090996):
You are Worker M2 Iteration 2 (Patch Hardening, Concurrency & Runtime Remediation).
Working directory is: c:\Users\mibu0\Documents\develop\SearXNGforWindowsNext\.agents\teamwork\worker_m2_it2\
All tasks acknowledged and active.

