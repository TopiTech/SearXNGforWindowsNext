# Dispatch: Worker M4 (E2E Test Integration & Full Acceptance Criteria Quality Gate)

**Date**: 2026-10-04
**Role**: Quality Assurance & Harness Integration Worker
**Assigned Milestone**: Milestone 4 (E2E Testing Track & Final Quality Gate)

## Objectives
Execute the comprehensive end-to-end verification and quality gate for SearXNGforWindowsNext, ensuring that all 6 acceptance criteria from `ORIGINAL_REQUEST.md` pass 100% cleanly without bypasses or suppressions.

## Write Ownership Boundaries
You have exclusive write ownership to:
- `tools/run-tests.ps1` (to integrate `tools/test_webui.py` into step 4)
- `tests/test_challenger_m2_2_adversarial.py` (to resolve any typing/formatting issues so pyrefly and ruff check pass cleanly)
- `tests/e2e/` (if any test harness updates are needed)
- `pyproject.toml` or ruff configuration (only if needed to ignore non-production agent metadata)

Do NOT touch core source files in `tools/` or `searx/` unless an integration bug is detected.

## Tasks
1. **Integrate `tools/test_webui.py` into `tools/run-tests.ps1`**:
   - In Step 4 of `tools/run-tests.ps1`, add `tools/test_webui.py` to the list of unit test suites executed by the master test runner.
2. **Resolve any static analysis issues in `tests/`**:
   - Check `tests/test_challenger_m2_2_adversarial.py` for type annotations / narrowing issues in pyrefly (around line 56-57).
   - Ensure `python\python.exe -m pyrefly check` passes with 0 unresolved type errors.
   - Ensure `ruff check .` and `ruff format --check .` pass cleanly across the project.
3. **Execute the complete verification battery and collect full raw outputs**:
   - Static analysis:
     - `.\python\python.exe -m pyrefly check`
     - `.\python\Scripts\ruff.exe check .` (or `python -m ruff check`)
     - `.\python\Scripts\ruff.exe format --check .` (or `python -m ruff format --check`)
   - Unit test suites:
     - `.\python\python.exe tools/test_patches.py`
     - `.\python\python.exe tools/test_agent_tools.py`
     - `.\python\python.exe tools/test_agentic_search.py`
     - `.\python\python.exe tools/test_retrieval_pipeline.py`
     - `.\python\python.exe tools/test_webui.py`
   - E2E opaque-box test suite:
     - `.\python\python.exe tests/e2e/run_e2e_tests.py`
   - Evaluation benchmark:
     - `.\python\python.exe tests/evaluation/run_benchmark.py`
   - Master test runner:
     - `powershell -ExecutionPolicy Bypass -File tools/run-tests.ps1 -SkipInstall`
4. **Compile detailed report**:
   - Write `handoff.md` in your working directory containing all exact commands, execution times, pass/fail metrics, and outputs.
   - Update `progress.md` with `Last visited: [timestamp]`.
   - Send completion message to orchestrator.


## 2026-10-04T06:57:08Z
[Message] timestamp=2026-10-04T06:57:08Z sender=2da8fdd6-dc63-4790-a432-5c307d090996 priority=MESSAGE_PRIORITY_HIGH content=You are Worker M4 (E2E Integration & Quality Gate Worker).
Your working directory is: c:\Users\mibu0\Documents\develop\SearXNGforWindowsNext\.agents\teamwork\worker_m4\
Original Request is located at: c:\Users\mibu0\Documents\develop\SearXNGforWindowsNext\.agents\teamwork\ORIGINAL_REQUEST.md
Project Scope is located at: c:\Users\mibu0\Documents\develop\SearXNGforWindowsNext\.agents\teamwork\orchestrator\PROJECT.md
E2E Test Readiness: c:\Users\mibu0\Documents\develop\SearXNGforWindowsNext\TEST_READY.md
E2E Test Infrastructure: c:\Users\mibu0\Documents\develop\SearXNGforWindowsNext\TEST_INFRA.md
Please read your dispatch instructions at: c:\Users\mibu0\Documents\develop\SearXNGforWindowsNext\.agents\teamwork\worker_m4\DISPATCH.md

MANDATORY INTEGRITY WARNING:
DO NOT CHEAT. All implementations must be genuine. DO NOT hardcode test results, create dummy/facade implementations, or circumvent the intended task. A teamwork_preview_auditor will independently verify your work. Integrity violations WILL be detected and your work WILL be rejected.

Write Ownership Boundaries:
You have EXCLUSIVE write ownership to:
- tools/run-tests.ps1 (to integrate tools/test_webui.py into step 4)
- tests/test_challenger_m2_2_adversarial.py (to fix typing/formatting so pyrefly and ruff check pass cleanly)
- tests/e2e/ (if any test harness runner adjustments are needed)
Do NOT touch core source files in tools/ or searx/ unless an integration defect is discovered.

Assigned Tasks:
1. Integrate tools/test_webui.py into step 4 of tools/run-tests.ps1 so the full master test runner automatically executes test_webui.py alongside the other 4 unit test suites.
2. Fix typing/narrowing in tests/test_challenger_m2_2_adversarial.py (around lines 56-57) so that python\python.exe -m pyrefly check passes with 0 unresolved type errors.
3. Ensure ruff check . and ruff format --check . pass cleanly. If .agents/ has non-code files that trigger ruff, ensure pyproject.toml or ruff command ignores .agents/ or formats any relevant test files.
4. Execute the complete verification battery across all acceptance criteria and record full command outputs:
   - python\python.exe -m pyrefly check
   - python\Scripts\ruff.exe check .
   - python\Scripts\ruff.exe format --check .
   - python\python.exe tools/test_patches.py (180 tests)
   - python\python.exe tools/test_agent_tools.py (60 tests)
   - python\python.exe tools/test_agentic_search.py (41 tests)
   - python\python.exe tools/test_retrieval_pipeline.py (52 tests)
   - python\python.exe tools/test_webui.py (21 tests)
   - python\python.exe tests/e2e/run_e2e_tests.py (85 tests, Tiers 1-4)
   - python\python.exe tests/evaluation/run_benchmark.py (10 queries, 100% P@5)
   - powershell -ExecutionPolicy Bypass -File tools/run-tests.ps1 -SkipInstall (full server lifecycle + 41 smoke tests)
5. Write handoff.md in your working directory with full command outputs, test counts, execution durations, and exit codes. Maintain progress.md with `Last visited: [timestamp]`. Send a message to orchestrator upon completion.
