# Handoff Report — Challenger M2-1 (Patch Traversal & Rollback Stress Challenger)

**Verdict**: **APPROVE**

---

## 1. Observation

Direct empirical stress testing was conducted against the implementation of `PatchTransaction.rollback()`, CLI `--report` argument validation, and `_get_tracked_targets()` using our automated adversarial harness `tests/adversarial_m2_stress_runner.py` on Python 3.11.9 (`python\python.exe`):

### 1.1 Manifest `orig_path` Traversal & Boundary Stress (Suite 1: 13 Payloads)
Evaluated `PatchTransaction.rollback()` against an untrusted/crafted `manifest.json` pointing to targets outside repository boundaries (`tools/apply-patches.py:155-157`):
- Relative upward escape `../outside_file.txt`: **REJECTED** (restored=0, file untouched).
- Double relative escape `../../outside_file.txt`: **REJECTED** (restored=0, file untouched).
- Triple relative escape `../../../escape.txt`: **REJECTED** (restored=0, file untouched).
- System root executable `C:\Windows\System32\cmd.exe`: **REJECTED** (restored=0, file untouched).
- System driver configuration `C:\Windows\System32\drivers\etc\hosts`: **REJECTED** (restored=0, file untouched).
- System Windows directory `C:\Windows\win.ini`: **REJECTED** (restored=0, file untouched).
- User profile SSH directory `C:\Users\...\.ssh\authorized_keys`: **REJECTED** (restored=0, file untouched).
- Localhost UNC path `\\127.0.0.1\c$\exploit.txt`: **REJECTED** (restored=0, file untouched).
- Remote attacker UNC share `\\attacker\share\payload.dll`: **REJECTED** (restored=0, file untouched).
- Root-relative path `\Windows\System32\calc.exe`: **REJECTED** (restored=0, file untouched).
- Alternate drive root `D:\outside\evil.txt`: **REJECTED** (restored=0, file untouched).
- Repo prefix confusion collision `C:\...\repo_fake\file.txt`: **REJECTED** (restored=0, file untouched).
- Subdirectory escape within repo targeting root `tools\..\..\outside.txt`: **REJECTED** (restored=0, file untouched).
- DOS device names `NUL`, `CON`, `COM1`: **REJECTED** (`Security violation: rollback target outside permitted boundaries`).
- NTFS Alternate Data Streams `target.py:hidden`: **REJECTED** (`WinError 123` caught and handled safely).

### 1.2 Manifest `bak_path` Traversal & Boundary Stress (Suite 2: 6 Payloads)
Evaluated `PatchTransaction.rollback()` against crafted `manifest.json` with out-of-boundary backup source paths (`tools/apply-patches.py:158-160`):
- Relative upward escape `../outside.bak`: **REJECTED** (restored=0).
- Double relative upward escape `../../outside.bak`: **REJECTED** (restored=0).
- Triple relative upward escape `../../../outside.bak`: **REJECTED** (restored=0).
- System file read attempt `C:\Windows\win.ini`: **REJECTED** (restored=0).
- UNC share backup source `\\attacker\share\fake.bak`: **REJECTED** (restored=0).
- Backup directory prefix confusion `backups_fake\file.bak`: **REJECTED** (restored=0).
- Authorized legitimate rollback: **PASSED** (restored 1 file, matching original content verbatim).

### 1.3 CLI `--report` Path Traversal Containment (Suite 3: 9 Payloads)
Evaluated CLI argument `--report` validation in `apply-patches.py:2692-2699`:
- Relative upward escape `../report.json`: **REJECTED** (`ValueError: Report output must reside within repository directory.`).
- Double relative upward escape `../../report.json`: **REJECTED** (`ValueError` raised).
- Absolute outside directory `C:\temp\report.json`: **REJECTED** (`ValueError` raised).
- System root `C:\Windows\report.json`: **REJECTED** (`ValueError` raised).
- Alternate drive `D:\report.json`: **REJECTED** (`ValueError` raised).
- UNC share `\\attacker\share\report.json`: **REJECTED** (`ValueError` raised).
- Repo prefix confusion `C:\...\SearXNGforWindowsNext_evil\report.json`: **REJECTED** (`ValueError` raised).
- In-repo root `test_cli_rep.json`: **ACCEPTED** (`exit_code = 0`, report generated cleanly).
- In-repo subfolder `python/test_rep.json`: **ACCEPTED** (`exit_code = 0`).

### 1.4 `_get_tracked_targets()` Completeness & Dynamic Tracking (Suite 4)
Inspected `_get_tracked_targets()` implementation (`tools/apply-patches.py:257-269`):
- Total registered `PATCH_SPECS`: 26 specifications.
- Total tracked paths returned: 25 unique canonical targets (deduplicated via `set`).
- Coverage rate: **100.0%** of all `PATCH_SPECS` target paths are included.
- Category targets specifically verified:
  - `searx/preferences.py`: **CONFIRMED** tracked.
  - `searx/webadapter.py`: **CONFIRMED** tracked.
- Dynamic mutation test: Adding a mock `PatchSpec` dynamically caused `_get_tracked_targets()` to immediately track the new spec target without hardcoded code modifications.

### 1.5 Cache Invalidation Mechanics (Suite 5)
Evaluated cache invalidation logic in `is_patch_cache_valid()` (`tools/apply-patches.py:283-295`):
- Fresh cache baseline: **VALID**.
- Modifying `preferences.py`: Immediately returns `is_patch_cache_valid() == False`.
- Modifying `webadapter.py`: Immediately returns `is_patch_cache_valid() == False`.
- Adding new target to `PATCH_SPECS`: Immediately returns `is_patch_cache_valid() == False`.

### 1.6 Full Test Suite & Static Analysis Results
- `python\python.exe tests/adversarial_m2_stress_runner.py`: **PASS** (100% of adversarial payloads rejected).
- `python\python.exe tools/test_patches.py TestPatchHardeningM2`: **Ran 11 tests ... OK** in 0.163s.
- `python\python.exe tools/test_patches.py`: **Ran 172 tests ... OK** in 1.455s.
- `python\python.exe tools/test_agent_tools.py`: **Ran 60 tests ... OK** in 0.033s.
- `python\python.exe tools/test_agentic_search.py`: **Ran 41 tests ... OK** in 0.833s.
- `python\python.exe tools/test_retrieval_pipeline.py`: **Ran 52 tests ... OK** in 0.023s.
- `python\python.exe tests/evaluation/run_benchmark.py`: **100% Precision@5, 0.0% Failure Rate**.
- `python\python.exe -m ruff check tools/apply-patches.py tools/ensure-secret-key.py tools/test_patches.py tests/adversarial_m2_stress_runner.py`: **All checks passed!**
- `python\python.exe -m ruff format --check tools/apply-patches.py tools/ensure-secret-key.py tools/test_patches.py tests/adversarial_m2_stress_runner.py`: **4 files already formatted**.
- `python\python.exe -m pyrefly check tools/apply-patches.py tools/ensure-secret-key.py tools/test_patches.py tests/adversarial_m2_stress_runner.py`: **INFO 0 errors**.

---

## 2. Logic Chain

1. **Path Traversal Containment via Canonical Normalization & Suffix Enclosure**:
   - In `tools/apply-patches.py:125-131, 150-160`:
     - Base boundaries are canonicalized using `os.path.abspath()` and lowercased/backslash-normalized using `os.path.normcase()`.
     - Boundary prefixes append `os.sep` explicitly: `c_repo + os.sep`, `c_sp + os.sep`, and `c_bak_dir + os.sep`.
     - This design mathematically guarantees that prefix collisions (e.g., `repo_fake` or `backups_fake`) fail the prefix test because the directory separator boundary is strictly enforced.
     - Relative traversals (`../`, `../../`, etc.) are resolved prior to comparison via `os.path.abspath()`.
   - Result: 100% of out-of-boundary `orig_path` and `bak_path` injections are safely caught and rejected without file system mutations.

2. **CLI `--report` Boundary Enforcement**:
   - In `tools/apply-patches.py:2692-2699` and `2807-2815`:
     - Both at CLI parsing time and prior to atomic file writing, `args.report` is normalized via `os.path.abspath` and `os.path.normcase`.
     - Rejection via `ValueError("Report output must reside within repository directory.")` halts execution immediately if any escape payload is supplied.
   - Result: Traversal escapes via `--report` are completely prevented.

3. **Dynamic Cache Tracking & Invalidation**:
   - In `tools/apply-patches.py:257-269`:
     - Rather than hardcoding paths, `_get_tracked_targets()` iterates over `PATCH_SPECS` and builds a set containing `spec.target_path` for all registered patches.
     - Because `searx/preferences.py` and `searx/webadapter.py` are registered in `PATCH_SPECS`, they are automatically included in target fingerprinting (`_compute_fingerprints()`).
     - Modifying either file alters its `mtime_ns` and `size`, causing `cached.get("files") == current` to fail and forcing re-verification of all patches.
   - Result: Fixes to categories or upstream updates will never be skipped due to stale cache fingerprints.

---

## 3. Caveats

1. **Non-Dict JSON Manifest Format**:
   - If an external attacker supplies a `manifest.json` file containing a JSON top-level array `[]` instead of an object `{}`, calling `manifest.items()` raises `AttributeError`. The exception terminates the rollback operation without modifying any files. While safe from an overwrite perspective, wrapping `(OSError, json.JSONDecodeError, AttributeError)` in `rollback()` could make the error logging even cleaner.
2. **Review-Only Constraint**:
   - In accordance with challenger guidelines, no implementation files were altered. The stress harness was placed in `tests/adversarial_m2_stress_runner.py`.

---

## 4. Conclusion

**Verdict: APPROVE**

Worker M2's implementation of:
- F2.1 (`_get_tracked_targets()` dynamic completeness),
- F2.2 (`PatchTransaction.rollback()` path traversal hardening), and
- F2.3 (CLI `--report` path containment)
satisfies all security and architectural requirements. Under hostile adversarial stress testing, 100% of path traversal payloads, system escapes, UNC shares, and prefix confusion attacks were successfully rejected. Cache invalidation on modified files functions flawlessly with zero regressions across the codebase.

---

## 5. Verification Method

To independently verify these findings:

```powershell
# 1. Run the dedicated M2 adversarial stress harness
python\python.exe tests/adversarial_m2_stress_runner.py
# Expected output: ALL ADVERSARIAL STRESS SUITES PASSED (100% REJECTION OF TRAVERSALS)

# 2. Run unit regression tests for M2 hardening
python\python.exe tools/test_patches.py TestPatchHardeningM2
# Expected output: Ran 11 tests ... OK

# 3. Run full patch test suite
python\python.exe tools/test_patches.py
# Expected output: Ran 172 tests ... OK

# 4. Run static quality and type checks
python\python.exe -m ruff check tools/apply-patches.py tools/ensure-secret-key.py tools/test_patches.py tests/adversarial_m2_stress_runner.py
python\python.exe -m ruff format --check tools/apply-patches.py tools/ensure-secret-key.py tools/test_patches.py tests/adversarial_m2_stress_runner.py
python\python.exe -m pyrefly check tools/apply-patches.py tools/ensure-secret-key.py tools/test_patches.py tests/adversarial_m2_stress_runner.py
```

### Invalidation Conditions
- Any adversarial path payload in `tests/adversarial_m2_stress_runner.py` failing to be rejected.
- Any regression or non-zero exit code in `test_patches.py`.
- Static analysis failure on `tools/apply-patches.py` or `tools/test_patches.py`.
