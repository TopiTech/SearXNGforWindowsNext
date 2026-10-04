# Dispatch: Worker M2 (Patch Management & Windows Security Hardening)

## Working Directory
`c:\Users\mibu0\Documents\develop\SearXNGforWindowsNext\.agents\teamwork\worker_m2\`

## Authoritative Context Documents
1. `ORIGINAL_REQUEST.md`: `c:\Users\mibu0\Documents\develop\SearXNGforWindowsNext\.agents\teamwork\ORIGINAL_REQUEST.md`
2. `PROJECT.md`: `c:\Users\mibu0\Documents\develop\SearXNGforWindowsNext\.agents\teamwork\orchestrator\PROJECT.md`
3. Explorer 2 Survey Report: `c:\Users\mibu0\Documents\develop\SearXNGforWindowsNext\.agents\teamwork\explorer_survey_2\survey_report.md`

## MANDATORY INTEGRITY WARNING
DO NOT CHEAT. All implementations must be genuine. DO NOT hardcode test results, create dummy/facade implementations, or circumvent the intended task. A teamwork_preview_auditor will independently verify your work. Integrity violations WILL be detected and your work WILL be rejected.

## Write Ownership Boundaries
You have EXCLUSIVE write ownership to the following files:
- `tools/apply-patches.py`
- `tools/ensure-secret-key.py`
- `tools/sync-upstream.ps1`
- `tools/clean-cache.ps1`
- `python/Lib/site-packages/searx/settings_loader.py`
- `tools/test_patches.py`

Do NOT edit any other source code files.

## Assigned Technical Tasks

### 1. F2.1 Patch Cache Target Completeness (`tools/apply-patches.py`)
- In `_get_tracked_targets()` (around lines 237–264):
  Dynamically derive targets from `PATCH_SPECS`:
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
  Ensure `searx/preferences.py` and `searx/webadapter.py` are dynamically included so cache checks never falsely skip critical category patches.

### 2. F2.2 Rollback Path Traversal Hardening (`tools/apply-patches.py`)
- In `PatchTransaction.rollback()`:
  Validate that every `orig_path` in `manifest.json` resolves strictly within `REPO_ROOT` or `SITE_PACKAGES`:
  ```python
  norm_orig = os.path.abspath(orig_path)
  norm_bak = os.path.abspath(bak_path)
  norm_repo = os.path.abspath(REPO_ROOT)
  norm_sp = os.path.abspath(SITE_PACKAGES)
  norm_bak_dir = os.path.abspath(self.backup_dir)

  if not (norm_orig.startswith(norm_repo + os.sep) or norm_orig.startswith(norm_sp + os.sep)):
      logger.error("Security violation: rollback target %s outside permitted boundaries", orig_path)
      continue
  if not norm_bak.startswith(norm_bak_dir + os.sep):
      logger.error("Security violation: backup file %s outside backup directory", bak_path)
      continue
  ```

### 3. F2.3 CLI Report Path Traversal Validation (`tools/apply-patches.py`)
- In CLI `--report` argument handler:
  Enforce that the specified report path resides strictly within `REPO_ROOT`:
  ```python
  norm_report = os.path.abspath(report_path)
  if not (norm_report.startswith(os.path.abspath(REPO_ROOT) + os.sep) or norm_report == os.path.abspath(REPO_ROOT)):
      raise ValueError("Report output must reside within repository directory.")
  ```

### 4. F2.4 & F2.5 Windows NTFS ACL Lockdown & Secure Temp Files (`tools/ensure-secret-key.py`)
- Replace static `.tmp` filename creation with `tempfile.mkstemp(prefix=".tmp_key_", dir=os.path.dirname(path), text=True)`.
  Ensure descriptor is cleanly handled and temporary file is atomically replaced via `os.replace`.
- In `set_file_permissions(path: str)`:
  If `sys.platform == "win32"`:
  ```python
  username = os.environ.get("USERNAME")
  if username:
      try:
          subprocess.run(
              ["icacls", path, "/inheritance:r", "/grant:r", f"{username}:(R,W)"],
              check=False,
              capture_output=True,
          )
      except Exception:
          pass
  ```
  (Maintain existing `os.chmod` fallback for POSIX).

### 5. F2.6 Quoted Settings Path Handling (`python/Lib/site-packages/searx/settings_loader.py`)
- Around line 101, ensure quotes are stripped from `os.environ["SEARXNG_SETTINGS_PATH"]`:
  ```python
  settings_path = os.environ.get("SEARXNG_SETTINGS_PATH", "").strip('"\'')
  ```

### 6. F2.7 Automatic Upstream Sync Rollback (`tools/sync-upstream.ps1`)
- When invoking `apply-windows-patches.ps1` during upstream sync, pass `--rollback-on-failure`.

### 7. F2.8 Cache Cleaning Backup Retention (`tools/clean-cache.ps1`)
- In default execution, preserve `python\.patches_backup`. Only delete `python\.patches_backup` when `-Deep` parameter is explicitly passed.

### 8. F2.9 Scrape Keepalive Hardening (`tools/apply-patches.py`)
- In `patch_webapp_scrape_route`:
  Ensure the injected HTTP client in `/scrape` sets `max_keepalive_connections=0` in `httpx.Limits(max_keepalive_connections=0, max_connections=50)` so sockets are not reused across DNS resolutions.

### 9. F2.10 Dedicated Regression Unit Tests (`tools/test_patches.py`)
- Add comprehensive regression tests in `tools/test_patches.py` covering:
  - Cache target completeness (verifying all targets in `PATCH_SPECS` including `preferences.py` and `webadapter.py` are in `_get_tracked_targets()`).
  - Rollback path traversal rejection for out-of-boundary paths in `manifest.json`.
  - CLI `--report` path rejection for path traversal.
  - `ensure-secret-key.py` mkstemp usage and icacls ACL invocation on Windows.
  - `settings_loader.py` quote stripping.
  - `/scrape` client keepalive settings (`max_keepalive_connections=0`).

### 10. Verification Requirements
- Execute static checks and tests using the project's python interpreter:
  - `python\python.exe -m ruff check tools/apply-patches.py tools/ensure-secret-key.py tools/test_patches.py`
  - `python\python.exe -m ruff format --check tools/apply-patches.py tools/ensure-secret-key.py tools/test_patches.py`
  - `python\python.exe -m pyrefly check`
  - `python\python.exe tools/test_patches.py` (all tests passing, 0 failures)
- Ensure no regressions in existing 161 tests.

## Completion Criteria
1. All 10 tasks implemented cleanly.
2. All unit tests in `tools/test_patches.py` pass.
3. Ruff check and format pass.
4. Update `progress.md` with `Last visited: [timestamp]` header throughout execution.
5. Produce `handoff.md` with full execution outputs, git diff summary, and verification results.
6. Send a message to orchestrator upon completion.


## 2026-10-04T04:43:29Z
Received message from parent (2da8fdd6-dc63-4790-a432-5c307d090996):
Task assignment: Worker M2 (Patch Management & Windows Security Hardening).
All 10 technical tasks acknowledged.
