# Dispatch: E2E Testing Track (Comprehensive Test Suite & Infrastructure)

**Working Directory**: `c:\Users\mibu0\Documents\develop\SearXNGforWindowsNext\.agents\teamwork\test_writer_e2e\`
**Original Request**: `c:\Users\mibu0\Documents\develop\SearXNGforWindowsNext\.agents\teamwork\ORIGINAL_REQUEST.md`
**Project Scope**: `c:\Users\mibu0\Documents\develop\SearXNGforWindowsNext\.agents\teamwork\orchestrator\PROJECT.md`

## Mission
Design and implement the E2E Testing Track for `SearXNGforWindowsNext`:
1. Build an opaque-box, requirement-driven test suite based strictly on user-facing requirements (`ORIGINAL_REQUEST.md`) and public APIs (`/search`, `/scrape`, `/deep_search`, `/api/retrieval`), CLI tools, and patch management.
2. Structure test cases according to the 4-tier methodology:
   - **Tier 1 - Feature Coverage**: Minimum 5 test cases per feature covering representative inputs across all public endpoints and query modes.
   - **Tier 2 - Boundary & Corner Cases**: Minimum 5 test cases per feature covering empty inputs, oversized queries (>2000 chars), unicode edge cases, invalid URLs, non-routable IPs (SSRF), special characters.
   - **Tier 3 - Cross-Feature Combinations**: Pairwise interactions (e.g. format=json + categories, deep_search + scrape, secret key rotation + launcher).
   - **Tier 4 - Real-World Application Scenarios**: Multi-step realistic workflows (e.g. agentic search pipeline, multi-engine retrieval synthesis, offline patch rollback recovery).
3. Deliverables:
   - Create `TEST_INFRA.md` at project root (`c:\Users\mibu0\Documents\develop\SearXNGforWindowsNext\TEST_INFRA.md`).
   - Create tests under `tests/e2e/`.
   - Publish `TEST_READY.md` at project root (`c:\Users\mibu0\Documents\develop\SearXNGforWindowsNext\TEST_READY.md`).
   - Run the E2E test suite to verify runner execution.

## Instructions
1. Read `ORIGINAL_REQUEST.md` and `PROJECT.md`.
2. Maintain liveness in `progress.md` with `Last visited: [timestamp]`.
3. Implement test cases in `tests/e2e/`.
4. Publish `TEST_INFRA.md` and `TEST_READY.md`.
5. Send message to orchestrator when completed.

## 2026-10-04T00:05:45Z
Message from parent:
You are E2E Test Suite Architect (E2E Testing Track).
Your working directory is: c:\Users\mibu0\Documents\develop\SearXNGforWindowsNext\.agents\teamwork\test_writer_e2e\
Original Request is located at: c:\Users\mibu0\Documents\develop\SearXNGforWindowsNext\.agents\teamwork\ORIGINAL_REQUEST.md
Project Scope is located at: c:\Users\mibu0\Documents\develop\SearXNGforWindowsNext\.agents\teamwork\orchestrator\PROJECT.md
Please read your dispatch instructions at: c:\Users\mibu0\Documents\develop\SearXNGforWindowsNext\.agents\teamwork\test_writer_e2e\DISPATCH.md

Write Ownership:
You have EXCLUSIVE write ownership to:
- tests/e2e/ (all test files and fixtures)
- TEST_INFRA.md (at project root)
- TEST_READY.md (at project root)

Assigned Tasks:
1. Design and implement comprehensive 4-tier E2E opaque-box test suite:
   - Tier 1: Feature Coverage (>=5 tests per feature covering /search, /scrape, /deep_search, /api/retrieval, JSON formats, CLI)
   - Tier 2: Boundary & Corner Cases (empty inputs, oversized queries, special chars, SSRF boundaries)
   - Tier 3: Cross-Feature Interactions (format + categories, deep_search + scrape, secret key rotation)
   - Tier 4: Real-World Application Scenarios (end-to-end multi-step retrieval and search workflows)
2. Create TEST_INFRA.md at c:\Users\mibu0\Documents\develop\SearXNGforWindowsNext\TEST_INFRA.md following project test methodology.
3. Create test files in tests/e2e/ with a test runner executable via python/python.exe.
4. Execute tests to verify pass/fail semantics.
5. Publish TEST_READY.md at c:\Users\mibu0\Documents\develop\SearXNGforWindowsNext\TEST_READY.md when test suite is ready.
6. Write handoff.md. Maintain progress.md with `Last visited: [timestamp]`. Send message to orchestrator upon completion.
