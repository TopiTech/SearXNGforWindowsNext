# Milestone 4 Adversarial Quality Gate & Stress Verification Report

**Author**: Challenger M4 (Adversarial Quality Gate & Stress Challenger)  
**Date**: 2026-10-04  
**Target Milestone**: Milestone 4 (E2E Testing Track & Final Quality Gate)  
**Verdict**: **APPROVE**  

---

## 1. Observation

### 1.1 Baseline Quality Gate Execution
1. **Pyrefly Type Checker**:
   - Command: `.\python\python.exe -m pyrefly check`
   - Output: `INFO Checking project configured at C:\Users\mibu0\Documents\develop\SearXNGforWindowsNext\pyproject.toml`
   - Result: `INFO 0 errors (1 suppressed)` (Exit code 0).
2. **Ruff Linter & Formatter**:
   - Command: `.\python\Scripts\ruff.exe check .`
   - Result: `All checks passed!` (Exit code 0).
   - Command: `.\python\Scripts\ruff.exe format --check .`
   - Result: `48 files already formatted` (Exit code 0).
3. **Master Test Runner (`tools/run-tests.ps1 -SkipInstall`)**:
   - Command: `powershell -ExecutionPolicy Bypass -File tools/run-tests.ps1 -SkipInstall`
   - Successfully executed all 5 unit suites (`test_patches.py` 180 tests, `test_agent_tools.py` 60 tests, `test_agentic_search.py` 41 tests, `test_retrieval_pipeline.py` 52 tests, `test_webui.py` 21 tests).
   - Executed retrieval benchmark (10 queries, P@5 1.0000).
   - Executed static analysis (Pyrefly 0 errors, Ruff check passed, Ruff format passed).
   - Spawned background Granian server on `http://127.0.0.1:8888` (Main PID: 43584, Worker PID: 44400).
   - Executed and passed all 41 live HTTP smoke tests in `tools/smoke-test.ps1`.
   - Cleanly terminated server process tree and exited with status code 0.
   - Verification of port 8888 listeners: `Get-NetTCPConnection -LocalPort 8888 -State Listen` returned 0 active listeners (exit code 1, port completely released).
4. **4-Tier E2E Opaque-Box Suite (`tests/e2e/run_e2e_tests.py`)**:
   - Command: `.\python\python.exe tests/e2e/run_e2e_tests.py --json`
   - Execution breakdown:
     - Tier 1 (Feature Coverage): 37/37 passed (26.15s)
     - Tier 2 (Boundary & Corner Cases): 34/34 passed (9.24s)
     - Tier 3 (Cross-Feature Interactions): 9/9 passed (4.81s)
     - Tier 4 (Real-World Application Scenarios): 5/5 passed (4.03s)
   - Total: 85 tests, 85 passed, 0 failures, 0 errors, duration 46.16s (Exit code 0).
5. **Retrieval Evaluation Benchmark (`tests/evaluation/run_benchmark.py`)**:
   - Command: `.\python\python.exe tests/evaluation/run_benchmark.py`
   - Results:
     - `fast`: P@5 = 1.0000, Recall@10 = 0.7683, MRR = 1.0000, nDCG@10 = 0.9766, Dedup = 2.5%, Official = 100.0%, Latency = 1.86ms
     - `balanced`: P@5 = 1.0000, Recall@10 = 0.7683, MRR = 1.0000, nDCG@10 = 0.9766, Dedup = 2.5%, Official = 100.0%, Passages = 58.3%, Latency = 2.98ms
     - `deep`: P@5 = 1.0000, Recall@10 = 0.7683, MRR = 1.0000, nDCG@10 = 0.9766, Dedup = 2.5%, Official = 100.0%, Passages = 58.3%, Latency = 3.59ms

### 1.2 Adversarial Mutation Testing
1. **Mutation Sensitivity in `tools/run-tests.ps1`**:
   - Target: Injected intentional assertion failure `self.assertEqual(1, 2, "Adversarial mutation test injection")` into `tools/test_webui.py:72`.
   - Executed: `powershell -ExecutionPolicy Bypass -File tools/run-tests.ps1 -SkipInstall`
   - Verbatim runner output:
     ```
     FAILED (failures=1)
     Test Run Error: Unit tests in tools\test_webui.py failed with exit code 1
     ```
   - Exit code: **1** (Process terminated immediately; server was NOT started; subsequent tests did NOT run; no orphan processes created).
   - Reversion: `tools/test_webui.py` reverted to clean state, confirmed with `git diff`.
2. **Pyrefly Type Enforcement Sensitivity**:
   - Injected type error `_temp_type_error: int = "this is not an int"` into a test file.
   - Result: `.\python\python.exe -m pyrefly check` failed with exit code 1:
     `ERROR Literal['this is not an int'] is not assignable to int [bad-assignment]`
   - Reverted immediately.
3. **Ruff Linter Enforcement Sensitivity**:
   - Injected unused import `import calendar` into a test file.
   - Result: `.\python\Scripts\ruff.exe check .` failed with exit code 1:
     `F401 [*] 'calendar' imported but unused`
   - Reverted immediately.
4. **Benchmark Evaluator Non-Triviality / Oracle**:
   - Injected unmapped query ID `ja_1` into evaluator: P@5 fell to 0.0, MRR to 0.0, nDCG@10 to 0.0.
   - Injected perturbed search result with irrelevant domain `completely-unrelated-random-domain.com`: P@5 fell to 0.0.
   - Verified standard DCG/NDCG degradation on non-ideal ranking orders (`[0.0, 1.0, 2.0]` produced NDCG < 1.0).
5. **Live Process Tree Teardown Verification**:
   - Tested Granian background spawn (main PID + worker PID).
   - Verified recursive process tree killing via `Win32_Process` parent traversal.
   - Verified port 8888 listener termination with `Get-NetTCPConnection`. Both main and worker PIDs were terminated and port 8888 was completely freed.

---

## 2. Logic Chain

1. **Gate Enforceability**:
   - From 1.2.1, `tools/run-tests.ps1` strictly monitors `$LASTEXITCODE` for each unit test suite. When `tools/test_webui.py` fails, the runner triggers `throw`, enters `catch`, sets `$testExitCode = 1`, and exits with 1 via the `finally` block. It does not swallow errors, nor does it proceed to start the server.
   - From 1.2.2 and 1.2.3, static analyzers (`pyrefly` and `ruff`) fail with non-zero exit codes when violations exist, and `tools/run-tests.ps1` lines 111 and 124 check `$LASTEXITCODE -ne 0` and throw. They cannot be bypassed when running the gate.
2. **E2E Suite Stability & Concurrency**:
   - From 1.1.4, running the 85-test E2E suite across all 4 tiers succeeded with 100% pass rate in repeated runs.
   - From `tests/test_challenger_m4_adversarial.py` (30 rapid parallel requests under 6 worker threads across `/search`, `/api/retrieval`, `/scrape`, `/healthz`, `/api/settings/engines`), zero 500 errors were encountered, and pathological inputs (2,500+ character queries, control bytes, traversal in scrape) were safely rejected with 400.
3. **Retrieval Benchmark Authenticity**:
   - From 1.1.5 and 1.2.4, the 100% P@5 score across Fast, Balanced, and Deep modes is genuine and computed from authentic domain matches against `expected_sources.json`. Perturbing inputs drops the metric to 0.0 as expected.
4. **Server Lifecycle Integrity**:
   - From 1.1.3 and 1.2.5, Granian starts cleanly, binds port 8888, passes all 41 smoke tests, and the teardown logic kills the entire process hierarchy. No orphaned worker processes or lingering port bindings remain.

---

## 3. Caveats

- **External Network Latency / Rate Limits**: As noted in previous milestones, external search engine APIs (e.g. Brave, Mojeek) may return 403 or 429 during automated live testing. The system and test harnesses are designed to catch and handle these gracefully without failing the suites.
- **Suppressed Baseline Pyrefly Warning**: 1 pre-existing suppressed warning remains in the upstream baseline codebase; 0 unresolved type errors exist in the project code.
- No other caveats.

---

## 4. Conclusion

**Verdict: APPROVE**

Milestone 4 has met all acceptance criteria from `ORIGINAL_REQUEST.md`:
1. Static typing via Pyrefly is 100% clean (0 errors, 1 baseline suppressed).
2. Code quality & formatting via Ruff is 100% clean across all 48 files.
3. All 5 unit test suites pass 100% (354 unit tests).
4. The 4-tier E2E opaque-box suite passes 100% (85/85 tests across Tiers 1-4).
5. The retrieval evaluation benchmark maintains 100% P@5 (1.0000) across Fast, Balanced, and Deep modes with mathematically verified metric calculations.
6. The master runner (`tools/run-tests.ps1 -SkipInstall`) executes the full integration battery and smoke tests with robust process tree cleanup and failure trapping.

---

## 5. Verification Method

To independently reproduce and verify this verdict, run:

1. **Static Analysis Quality Gate**:
   ```powershell
   .\python\python.exe -m pyrefly check
   .\python\Scripts\ruff.exe check .
   .\python\Scripts\ruff.exe format --check .
   ```
2. **Adversarial & Regression Unit Suites**:
   ```powershell
   .\python\python.exe tools/test_patches.py
   .\python\python.exe tools/test_agent_tools.py
   .\python\python.exe tools/test_agentic_search.py
   .\python\python.exe tools/test_retrieval_pipeline.py
   .\python\python.exe tools/test_webui.py
   .\python\python.exe tests/test_challenger_m4_adversarial.py
   ```
3. **4-Tier E2E Opaque-Box Suite**:
   ```powershell
   .\python\python.exe tests/e2e/run_e2e_tests.py
   ```
4. **Retrieval Evaluation Benchmark**:
   ```powershell
   .\python\python.exe tests/evaluation/run_benchmark.py
   ```
5. **Full Master Test Runner**:
   ```powershell
   powershell -ExecutionPolicy Bypass -File tools/run-tests.ps1 -SkipInstall
   ```
6. **Port 8888 Teardown Check**:
   ```powershell
   Get-NetTCPConnection -LocalPort 8888 -State Listen -ErrorAction SilentlyContinue
   ```
   (Must return empty / null).
