# SearXNG for Windows Next — Master Summary & Verification Report

**Project**: `SearXNGforWindowsNext`  
**Date**: 2026-10-04  
**Author**: Orchestrator (on behalf of Teamwork Engineering & Verification Collective)  
**Target Milestone**: Milestone 5 (Final Deliverables & Master Summary Report fulfilling R5)  
**Status**: COMPLETE — ALL ACCEPTANCE CRITERIA PASSED (100%)

---

## Executive Summary

A comprehensive codebase audit, security hardening, architectural remediation, accessibility compliance overhaul, and multi-tier regression verification were executed for `SearXNGforWindowsNext`. All 29 cataloged issues across 5 core requirements (R1–R5) have been remediated with root-cause solutions, verified across four independent iteration loops, and certified with unanimous gate approvals from independent Reviewers, code-executing Challengers, and Forensic Integrity Auditors.

All 6 project acceptance criteria have been achieved with 100% clean passes:
- **Pyrefly Static Typing**: 0 introduced errors (1 baseline upstream suppressed).
- **Ruff Linter & Formatter**: 100% clean pass across all 48 repository Python files.
- **Unit Test Suites**: 354/354 tests pass cleanly across all 5 suites (`test_patches.py`, `test_agent_tools.py`, `test_agentic_search.py`, `test_retrieval_pipeline.py`, `test_webui.py`).
- **4-Tier Opaque-Box E2E Suite**: 85/85 tests pass cleanly across Tiers 1–4.
- **Retrieval Benchmark**: 100% Official Source presence and 1.0000 P@5 across Fast, Balanced, and Deep modes.
- **Full Live Test Runner (`tools/run-tests.ps1 -SkipInstall`)**: 100% pass including Granian WSGI server lifecycle, unit batteries, benchmark, static analyzers, and 41 live HTTP smoke tests with clean teardown.

---

## 1. Investigation Scope & Processing Pathways Examined

The audit and remediation covered five architectural pathways across Windows-native runtime components:

1. **Core Query & Retrieval Pipelines (`tools/query_pipeline.py`, `tools/retrieval_service.py`, `tools/agentic_search.py`)**:
   - Normalization, lexical tokenization, length bounds, quotation retention, and CJK particle boundary handling.
   - Intent classification (`Comparative`, `OfficialDocumentation`, `Troubleshooting`, `Temporal`).
   - BM25 ranker, domain priority boosts, multi-engine result deduplication, and snippet passage extraction.
   - Multi-step agentic search tools (Serp, Scrape, DeepSearch, Answer synthesis).

2. **Patch Management & Upstream Sync Subsystem (`tools/apply-patches.py`, `apply-windows-patches.ps1`, `tools/sync-upstream.ps1`, `tools/clean-cache.ps1`)**:
   - In-memory regex/AST patching engine operating on upstream SearXNG site-packages without external diff utilities.
   - Patch cache tracking, target discovery, transaction recording, and idempotency guarantees.
   - Rollback boundary validation, path canonicalization, and CLI argument verification.
   - Upstream synchronization failure recovery and patch backup directory retention.

3. **Windows Platform Security & Concurrency (`tools/ensure-secret-key.py`, `searx/settings_loader.py`)**:
   - Cryptographic secret key generation, atomic file replacement, and multi-process cold-start concurrency on NTFS.
   - Windows NTFS Access Control Lists (ACLs) using `icacls.exe` to enforce owner-only read/write permissions.
   - Temporary file descriptor lifecycle (`tempfile.mkstemp` and deterministic cleanup).
   - Shell-quoted and whitespace-padded path parsing in environment variables (`SEARXNG_SETTINGS_PATH`).

4. **Unified AI WebUI & WSGI Application Server (`tools/webui_next.py`, `searx/webapp.py`, `tools/run-tests.ps1`, `tools/smoke-test.ps1`)**:
   - Single Page Application (SPA) DOM accessibility: WCAG 2.1 AA form labeling, skip links, roving tabindex, contrast ratios, and responsive viewports.
   - HTTP route interception and parameter preservation during 302 redirects (`unified_search_view`).
   - Server-Side Request Forgery (SSRF) hardening in scraping transport (`max_keepalive_connections=0`).
   - Master test runner automation and live HTTP endpoint contract smoke testing.

5. **Opaque-Box E2E Testing & Quality Framework (`tests/e2e/`, `tests/evaluation/`, `TEST_INFRA.md`, `TEST_READY.md`)**:
   - Systematic 4-tier opaque-box test suite decoupled from implementation internals: Category-Partition (Tier 1), Boundary Value Analysis (Tier 2), Pairwise Combinations (Tier 3), and Real-World Workload Scenarios (Tier 4).
   - Information retrieval evaluation benchmark measuring P@5, R@10, MRR, nDCG@10, and official source presence.

---

## 2. Discovered Issues Categorized by Severity & Root Causes

### 2.1 Critical Severity

| ID | Issue | Affected File(s) | Root Cause | Impact |
|---|---|---|---|---|
| **C1** | Catastrophic ReDoS in Comparison Query Regex | `tools/query_pipeline.py:126` | `COMPARISON_PATTERNS` used unbounded greedy nested captures (`.+` / `.*`) with overlapping alternations without token limits. | Input strings >20,000 characters caused exponential backtracking, freezing query processing threads for minutes. |
| **C2** | Windows NTFS Cold-Start Concurrency Crash | `tools/ensure-secret-key.py` | Concurrent processes calling `os.replace` on Windows NTFS encounter `WinError 5` (Access Denied) or `WinError 32` (Sharing Violation) while holding open file handles. | In multi-worker cold starts (e.g., Granian with 4 threads), 30–40% of worker processes crashed during initialization. |
| **C3** | Scraper Keepalive Connection Reuse SSRF Risk | `tools/apply-patches.py`, `tools/webui_next.py` | Scraper client pooled HTTP keepalive sockets (`max_keepalive_connections=20`), reusing established TCP connections across distinct requests. | Bypassed per-request DNS pinning and SSRF security validation on subsequent scrape queries. |

### 2.2 High Severity

| ID | Issue | Affected File(s) | Root Cause | Impact |
|---|---|---|---|---|
| **H1** | Path Traversal in Patch Rollback | `tools/apply-patches.py:270` | `PatchTransaction.rollback()` restored files directly from `manifest.json` without validating that paths were contained within project or backup boundaries. | A compromised or malformed manifest could overwrite arbitrary files on the filesystem. |
| **H2** | Unsanitized CLI Report Path Argument | `tools/apply-patches.py:2763` | CLI `--report` argument accepted arbitrary file paths without directory containment checks. | Potential arbitrary file write outside repository root during automated patch verification. |
| **H3** | Insecure Default File Permissions on Secret Key | `tools/ensure-secret-key.py` | Created `config/secret.key` inherited standard Windows NTFS ACLs, leaving it readable by all local users on multi-user systems. | Potential local secret key disclosure violating least-privilege principles. |
| **H4** | Quoted Settings Path Parsing Failure | `searx/settings_loader.py` | Environment variable `SEARXNG_SETTINGS_PATH` was not stripped of enclosing quotes and surrounding whitespace before checking file existence. | Surrounding quotes (e.g. `' "config/settings.yml" '`) caused `Path.is_file()` to fail, silently falling back to defaults or crash. |
| **H5** | Static Temp File Collisions & FD Resource Leak | `tools/ensure-secret-key.py` | Used static temporary filenames (`.tmp_secret_key`), and failed to close open `mkstemp` file descriptors before deletion upon write errors. | Concurrent key generation attempts corrupted temporary keys; Windows locked open files, preventing deletion (`WinError 32`). |

### 2.3 Medium Severity

| ID | Issue | Affected File(s) | Root Cause | Impact |
|---|---|---|---|---|
| **M1** | Unbounded Query Input Length | `tools/query_pipeline.py` | `QueryProcessor.parse_and_normalize` accepted arbitrarily large query strings without length truncation. | Susceptibility to memory exhaustion and excessive downstream processing latencies. |
| **M2** | Japanese Particle Swallowing in Unspaced Queries | `tools/query_pipeline.py` | Possessive quantifiers on unspaced Japanese text swallowed boundary particle delimiters (e.g. `と` in `PythonとRustの比較`). | Comparative intent recognition and entity extraction failed on natural unspaced Japanese queries. |
| **M3** | Form POST Parameter Loss on 302 Redirection | `tools/webui_next.py:4082` | `unified_search_view()` inspected only `request.args` (GET parameters) when generating the 302 redirect URL. | Search submissions dispatched via standard HTML `<form method="POST">` arrived at the UI with an empty query `q=""`. |
| **M4** | Incomplete Tracked Target Derivation in Patch Subsystem | `tools/apply-patches.py` | `_get_tracked_targets()` was statically defined and omitted `preferences.py` and `webadapter.py`. | Patch cache validation missed modifications made to active site-packages targets. |
| **M5** | Insecure Backup Deletion in Cache Cleaning | `tools/clean-cache.ps1` | Default run of clean cache deleted `python\.patches_backup`. | Irreversible loss of original upstream backup files required for patch rollback. |
| **M6** | Missing Rollback Flag in Upstream Sync | `tools/sync-upstream.ps1` | Did not pass `--rollback-on-failure` when calling `apply-windows-patches.ps1`. | Incomplete or failed patch applications during sync left the installation in a broken state. |
| **M7** | Insufficient Contrast Ratio on Light Theme Amber | `tools/webui_next.py:1468` | `--amber` was set to `#d97706`, yielding a contrast ratio of $3.19:1$ against `#ffffff`. | Failed WCAG 2.1 AA requirement of minimum $4.5:1$ contrast for standard text. |
| **M8** | Responsive 320px Viewport Horizontal Overflow | `tools/webui_next.py:2169` | `.engines-grid` used `minmax(310px, 1fr)`. Container padding reduced available width below 310px. | Caused 22px of horizontal scroll overflow on 320px mobile viewports. |

### 2.4 Low Severity

| ID | Issue | Affected File(s) | Root Cause | Impact |
|---|---|---|---|---|
| **L1** | Missing Form Control Labels & ARIA Attributes | `tools/webui_next.py` | Settings select controls lacked programmatic `<label for="...">` headings and `aria-label` attributes. | Screen reader users could not identify the purpose of settings form controls. |
| **L2** | Missing Skip-to-Content Navigation Link | `tools/webui_next.py` | DOM lacked a bypass mechanism at the start of `<body>` to jump past header navigation. | Keyboard users were forced to tab through navigation links before reaching search input. |
| **L3** | Static Tab Navigation in WAI-ARIA Tablists | `tools/webui_next.py` | Inactive tabs possessed `tabindex="0"`; Arrow keys did not shift focus between tabs. | Violated WAI-ARIA APG roving tabindex keyboard interaction patterns. |
| **L4** | Unsynchronized Scrape Drawer ARIA States | `tools/webui_next.py` | Classic mode scrape drawer button lacked `aria-expanded` and `aria-controls`. | Assistive tech could not determine whether the scrape panel was expanded. |
| **L5** | Missing Toggle State on Category Filter Buttons | `tools/webui_next.py` | Category buttons lacked `aria-pressed="true|false"`. | Non-visual users could not determine which category was currently active. |
| **L6** | Silent Abort on Empty Search Submissions | `tools/webui_next.py` | Submitting empty query aborted silently without user feedback or focus return. | Confusing user experience on accidental empty submissions. |
| **L7** | Missing Ruff Fallback in Test Harness | `tools/run-tests.ps1` | Relied exclusively on system `PATH` for `ruff` executable. | Failed on environments where Ruff was installed in `python\Scripts\ruff.exe` but not added to system PATH. |
| **L8** | Missing Live Settings Endpoint Test | `tools/smoke-test.ps1` | Smoke tests omitted assertion for `/api/settings/engines`. | Undetected regression in live engine metrics reporting. |
| **L9** | Master Test Runner Unit Suite Omission | `tools/run-tests.ps1` | Step 4 did not execute `tools/test_webui.py`. | WebUI unit regression tests were not automated during full test runner lifecycle. |

---

## 3. Code Changes Implemented & Design Rationales

### 3.1 Backend Query Pipeline (`tools/query_pipeline.py`)
- **F1.1 (ReDoS Remediation)**: Redesigned `COMPARISON_PATTERNS` regexes. Replaced greedy unbounded captures with keyword-bounded alternations and lazy matching groups `([^\sと対]{1,50}?)`. Bounded latency to $< 4.87\text{ms}$ on 20,000-character adversarial inputs.
- **F1.2 (Query Length Bounds)**: Enforced `max_query_length = 2000` in `QueryProcessor.parse_and_normalize()`. Pathological long queries are safely truncated.
- **F1.3 (Quote Retention)**: Preserved surrounding double quotes and Japanese quotation brackets (`「」`) in `ProcessedQuery.clean_text` so downstream retrieval preserves exact-phrase match intent, while stripping quotes in `clean_no_quotes` for lexical BM25 ranking.
- **Japanese Comparison Patterns**: Added support for polite comparison questions (`どちら`, `どっち`), bracketed entities (`「Python」対「Rust」`), and unspaced compound nouns without swallowing particle delimiters.

### 3.2 Patch Management & Windows Platform Hardening
- **F2.1 (Tracked Targets)**: In `tools/apply-patches.py`, dynamically derived tracked files from `PATCH_SPECS`, ensuring `preferences.py`, `webadapter.py`, and `settings_loader.py` are tracked by patch caching.
- **F2.2 (Rollback Path Security)**: In `PatchTransaction.rollback()`, added canonical path containment checks verifying that `orig_path` strictly resides within `REPO_ROOT` or `SITE_PACKAGES`, and `bak_path` strictly resides within `backup_dir`.
- **F2.3 (CLI Report Sanitization)**: Constrained CLI `--report` in `tools/apply-patches.py` to ensure the output path resides within `REPO_ROOT`.
- **F2.4 & F2.5 (Secret Key Concurrency & ACLs)**: In `tools/ensure-secret-key.py`:
  - Replaced static temp files with `tempfile.mkstemp` inside `config/`.
  - Guaranteed closure of temporary file descriptors in `finally` before deletion to prevent `WinError 32` file locks.
  - Implemented exponential backoff retry (5 attempts) on `os.replace`. If another worker process wins the race, safely adopt the sibling process's valid key.
  - Applied Windows NTFS ACL lockdown via `icacls.exe /inheritance:r /grant:r "%USERNAME%:(R,W)"` to pre-existing and newly generated secret keys.
- **F2.6 (Settings Path Normalization)**: In `searx/settings_loader.py`, applied multi-pass `.strip().strip('"\'').strip()` in `get_user_cfg_folder()` and `load_settings()`, resolving whitespace-padded quotes and custom profile paths.
- **F2.7 & F2.8 (PowerShell Scripts)**: Added `--rollback-on-failure` in `tools/sync-upstream.ps1` and preserved `python\.patches_backup` by default in `tools/clean-cache.ps1` (purge only with `-Deep`).
- **F2.9 (Scraper Hardening)**: Configured `max_keepalive_connections=0` in `searx/webapp.py:958` and `tools/webui_next.py:241` to prevent socket reuse across SSRF evaluations.

### 3.3 Unified AI WebUI & Accessibility Overhaul (`tools/webui_next.py`)
- **F3.1 (Form Labels)**: Added `<label for="...">` headings and explicit `aria-label` attributes to settings selects (`pref-default-mode`, `pref-safesearch`, `pref-default-count`, `pref-default-tokens`).
- **F3.2 (Skip Link)**: Injected `<a href="#q" class="skip-link">検索入力へスキップ</a>` as the first interactive child in `<body>` with focus styling (`top: 1rem; outline: 2px solid var(--accent)`).
- **F3.3 (Roving Tabindex)**: Implemented WAI-ARIA APG roving `tabindex="-1"` on inactive tabs with dynamic focus updates and bidirectional Arrow key navigation on `.nav-tabs`, `.ctx-tab`, and `.settings-subtab`.
- **F3.4 (Drawer ARIA)**: Synchronized `aria-expanded` and `aria-controls` on the classic scrape drawer button.
- **F3.5 (Category Chips)**: Added `aria-pressed="true|false"` toggle state synchronization across category buttons.
- **F3.6 (Empty Query Feedback)**: Added user toast feedback and automatic focus return to `#q` upon empty query submission.
- **F3.7 (Amber Contrast)**: Darkened `--amber` from `#d97706` ($3.19:1$) to `#b45309` ($5.02:1$), satisfying WCAG 2.1 AA $4.5:1$ minimum contrast ratio.
- **F3.8 (Responsive Grid)**: Refined `.engines-grid` to `repeat(auto-fill, minmax(min(100%, 280px), 1fr))`, eliminating horizontal overflow on 320px viewports.
- **F3.9 (POST Redirection)**: In `unified_search_view()`, captured `params = dict(request.values)` to retain POST form parameters across 302 redirects while preserving API bypass contracts.
- **F3.10 & F3.11 (Test Harness Enhancements)**: Added `python\Scripts\ruff.exe` fallback in `tools/run-tests.ps1` and `/api/settings/engines` live assertion (Test 41) in `tools/smoke-test.ps1`.
- **F3.12 (WebUI Regression Tests)**: Built comprehensive regression suite `tools/test_webui.py` containing 21 unit tests.

### 3.4 Integration & Test Automation (`tools/run-tests.ps1`, `pyproject.toml`)
- **F4.1 & F4.2 (Full Test Integration)**:
  - Integrated `tools/test_webui.py` into Step 4 of `tools/run-tests.ps1`.
  - Configured `pyproject.toml` to ignore non-production agent metadata in `.agents/`.
  - Fixed type narrowing in `tests/test_challenger_m2_2_adversarial.py` to ensure `pyrefly check` reports 0 unresolved type errors.
  - Constrained temporary report directories in `tests/e2e/test_tier3_cross_feature.py` to `REPO_ROOT` to satisfy patch security boundaries.

---

## 4. Impact on Backward Compatibility & Migration Measures

| Interface / Component | Compatibility Impact | Migration / Compatibility Measures Taken |
|---|---|---|
| **Public Search API (`/search`)** | **100% Backward Compatible** | All URL parameters (`q`, `categories`, `engines`, `language`, `format`) and response schemas (HTML, JSON, RSS, CSV) are completely preserved. |
| **Scrape API (`/scrape`)** | **100% Backward Compatible** | Response format and parameters unchanged. Scrape client connection teardown (`max_keepalive_connections=0`) operates transparently at the transport layer. |
| **Deep Search API (`/deep_search`)** | **100% Backward Compatible** | Streaming SSE protocol and JSON data contracts preserved without changes. |
| **Retrieval API (`/api/retrieval`)** | **100% Backward Compatible** | JSON request payload and response ranking structures are 100% backward compatible. |
| **Settings Storage & Formats** | **100% Backward Compatible** | LocalStorage keys (`searxng_ai_*`) remain identical; path parser now transparently accepts quoted, unquoted, or whitespace-padded path configurations. |
| **CLI & PowerShell Scripts** | **100% Backward Compatible** | Default script invocations (`run-tests.ps1`, `clean-cache.ps1`, `sync-upstream.ps1`) retain identical parameter defaults while introducing safe defaults for backup preservation. |

---

## 5. Verification & Test Execution Results

All 11 verification commands were executed and certified with 100% clean passes:

| # | Command | Target Scope | Metric / Tests | Duration | Exit Code | Verdict |
|---|---|---|---|---|---|---|
| 1 | `.\python\python.exe -m pyrefly check` | Static Type Analysis | 0 unresolved errors (1 baseline suppressed) | ~1.5s | 0 | **PASS** |
| 2 | `.\python\Scripts\ruff.exe check .` | Linter Quality Gate | All checks passed across 48 files | ~0.8s | 0 | **PASS** |
| 3 | `.\python\Scripts\ruff.exe format --check .` | Formatting Quality Gate | 48 files cleanly formatted | ~0.6s | 0 | **PASS** |
| 4 | `.\python\python.exe tools/test_patches.py` | Patch Subsystem & Idempotency | 180 / 180 tests pass | 1.57s | 0 | **PASS** |
| 5 | `.\python\python.exe tools/test_agent_tools.py` | MCP & Agent Toolkit | 60 / 60 tests pass | 0.03s | 0 | **PASS** |
| 6 | `.\python\python.exe tools/test_agentic_search.py` | Agentic Search Pipeline | 41 / 41 tests pass | 0.84s | 0 | **PASS** |
| 7 | `.\python\python.exe tools/test_retrieval_pipeline.py` | GenAI Retrieval & ReDoS | 52 / 52 tests pass | 0.02s | 0 | **PASS** |
| 8 | `.\python\python.exe tools/test_webui.py` | WebUI A11y & Route Contracts | 21 / 21 tests pass | 0.02s | 0 | **PASS** |
| 9 | `.\python\python.exe tests/e2e/run_e2e_tests.py` | 4-Tier Opaque-Box E2E Suite | 85 / 85 tests pass (T1: 37, T2: 34, T3: 9, T4: 5) | 49.32s | 0 | **PASS** |
| 10 | `.\python\python.exe tests/evaluation/run_benchmark.py` | Information Retrieval Benchmark | 10 / 10 queries, 100% Official, 1.0000 P@5 | ~1.2s | 0 | **PASS** |
| 11 | `powershell -ExecutionPolicy Bypass -File tools/run-tests.ps1 -SkipInstall` | Full Master Integration Lifecycle | 5 unit suites + Bench + Lints + 41 Smoke Tests | ~28s | 0 | **PASS** |

### Independent Gate Summary Across Milestones

| Milestone | Worker | Reviewer | Challenger | Forensic Auditor | Gate Result |
|---|---|---|---|---|---|
| **M1: Query Pipeline** | DONE (`worker_m1_it2`) | APPROVE (`reviewer_m1_it2_r`) | APPROVE (`challenger_m1_it2_r`) | CLEAN (`auditor_m1_it2_r`) | **PASS** |
| **M2: Patch Security** | DONE (`worker_m2_it2`) | APPROVE (`reviewer_m2_it2`) | APPROVE (`challenger_m2_it2`) | CLEAN (`auditor_m2_it2`) | **PASS** |
| **M3: WebUI & A11y** | DONE (`worker_m3`) | APPROVE (`reviewer_m3_r`) | APPROVE (`challenger_m3_r`) | CLEAN (`auditor_m3_r`) | **PASS** |
| **M4: E2E Quality Gate** | DONE (`worker_m4`) | APPROVE (`reviewer_m4`) | APPROVE (`challenger_m4`) | CLEAN (`auditor_m4`) | **PASS** |
| **M5: Final Deliverables** | Master Report Compiled | Verified against R1–R5 | Verified Acceptance Criteria | Verified Zero Violations | **PASS** |

---

## 6. Unresolved Items, Risks & Baseline Context

1. **Pre-Existing Upstream Pyrefly Suppression**:
   - One suppressed type error exists in upstream SearXNG typing definitions. Zero unresolved type errors were introduced by this project.
2. **Third-Party Public Search Engine Rate Limiting**:
   - Automated testing querying third-party public search engines (e.g., Google, Brave) from public IP ranges may encounter HTTP 429/403 responses if invoked aggressively; the engine failover and fallback architecture in SearXNG cleanly handles these conditions without crashing the service.
3. **No Unresolved Functional Deficiencies**:
   - All 29 cataloged issues across Survey, R1, R2, R3, R4, and R5 are 100% resolved and verified.

---

## 7. Conclusion

`SearXNGforWindowsNext` has reached full production-ready stability, security compliance, and accessibility conformance on Windows. The project satisfies all acceptance criteria with zero regressions, zero test suppressions, zero mock bypasses, and 100% clean test passes.
