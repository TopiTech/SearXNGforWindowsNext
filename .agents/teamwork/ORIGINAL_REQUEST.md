# Original User Request

## Initial Request — 2026-10-03T23:48:54Z

Comprehensive codebase review, security and correctness remediation, UI/accessibility audit, and regression testing for the SearXNGforWindowsNext project.

Working directory: c:\Users\mibu0\Documents\develop\SearXNGforWindowsNext
Integrity mode: development

## Requirements

### R1. Comprehensive Architecture & Code Review
Conduct an exhaustive audit of the codebase covering core query execution pipelines (`tools/query_pipeline.py`, `retrieval_service.py`, `agentic_search.py`), patch management (`tools/apply-patches.py`, `apply-windows-patches.ps1`), web application server (`searx/webapp.py`, `webui_next.py`), and configuration/secrets handling. Evaluate correctness, security (SSRF, secret exposure, command injection), performance, and compatibility with upstream SearXNG.

### R2. Remediation of Critical Defects & Vulnerabilities
Address identified high-severity bugs, security vulnerabilities, and stability issues with root-cause fixes while preserving backward compatibility for public APIs (`/search`, `/scrape`, `/deep_search`, `/api/retrieval`) and data contracts. Ensure safe fallback and migration paths if breaking changes are unavoidable.

### R3. WebUI & Accessibility Verification
Review the unified AI WebUI for responsive layout integrity, rendering stability across desktop/mobile viewport widths, keyboard navigability, and core accessibility compliance (ARIA roles/labels, form inputs).

### R4. Regression Testing & Static Quality Validation
Execute project-standard verification commands (`tools/run-tests.ps1`, `ruff check`, `ruff format --check`, Pyrefly type checking, and unit/benchmark tests). Add dedicated regression tests for any bug fixed to prevent future recurrence. When checking library behavior or version-specific details, consult official documentation via web search.

### R5. Deliverables & Final Summary
Deliver a structured final summary reporting:
1. Investigation scope and major processing pathways examined.
2. Discovered issues categorized by severity (Critical / High / Medium / Low) with root causes.
3. Code changes implemented and design rationales.
4. Impact on backward compatibility and migration measures taken.
5. Verification and test execution results.
6. Unresolved items, risks, or unexecutable verifications (explicitly distinguished from existing baseline issues).

## Acceptance Criteria

### Quality & Static Checks
- [ ] Pyrefly type checking passes with zero unresolved type errors introduced (`python\python.exe -m pyrefly check`).
- [ ] Ruff linter and formatting checks pass cleanly (`ruff check .` and `ruff format --check .`).

### Functional & Regression Verification
- [ ] All unit tests pass cleanly:
  - `python\python.exe tools/test_patches.py`
  - `python\python.exe tools/test_agent_tools.py`
  - `python\python.exe tools/test_agentic_search.py`
  - `python\python.exe tools/test_retrieval_pipeline.py`
- [ ] The evaluation benchmark executes successfully:
  - `python\python.exe tests/evaluation/run_benchmark.py`
- [ ] Dedicated regression tests are added and pass for all fixed issues.
- [ ] Full test runner passes without failure:
  - `powershell -ExecutionPolicy Bypass -File tools/run-tests.ps1 -SkipInstall`

### Deliverables & Report
- [ ] Comprehensive summary report covering scope, issues by severity, change rationale, compatibility assessment, test results, and unresolved items is produced.
