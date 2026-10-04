# Project: SearXNGforWindowsNext

## Architecture
`SearXNGforWindowsNext` provides a high-performance Windows-native meta-search runtime, AI workspace UI, and agentic retrieval engine built on upstream SearXNG.
The core architectural layers comprise:
1. **Core Query & Retrieval Pipelines**:
   - `tools/query_pipeline.py`: Query normalization, intent detection, query expansion, comparative search parsing.
   - `tools/retrieval_service.py`: Multi-source aggregation, ranking, deduplication, content snippet extraction.
   - `tools/agentic_search.py`: Autonomous tool-augmented iterative search workflows.
2. **Patch Management & Windows Integration**:
   - `tools/apply-patches.py`: In-memory AST/regex patch subsystem modifying upstream packages without external diff tools.
   - `tools/ensure-secret-key.py`: Cryptographically secure key generation and Windows ACL permissions management.
   - `apply-windows-patches.ps1` & `tools/sync-upstream.ps1`: Automated patch orchestrator and upstream SearXNG synchronizer.
3. **Unified AI WebUI & Application Server**:
   - `tools/webui_next.py`: Single Page Application (AI workspace, Deep Search, Classic Search, Agent mode, Settings) and HTTP route interception.
   - `searx/webapp.py`: Flask WSGI application serving `/search`, `/scrape`, `/deep_search`, `/api/retrieval`.
4. **Validation, Testing & Quality Infrastructure**:
   - `tools/run-tests.ps1`: End-to-end integration and smoke test runner with Granian server lifecycle.
   - Static analysis: Ruff linter & formatter, Pyrefly type checking.
   - Unit & benchmark test suites: `tools/test_patches.py`, `tools/test_agent_tools.py`, `tools/test_agentic_search.py`, `tools/test_retrieval_pipeline.py`, `tests/evaluation/run_benchmark.py`.

---

## Feature Inventory
Every feature, finding, and requirement from Survey and ORIGINAL_REQUEST is inventoried here with assigned milestones:

| # | Feature | Description | Milestone | Source |
|---|---------|-------------|-----------|--------|
| 1 | F1.1 ReDoS Remediation | Fix catastrophic backtracking regex in `tools/query_pipeline.py:126` (`COMPARISON_PATTERNS`) via keyword pre-filters and token bounding | M1 | Survey (Explorer 1) |
| 2 | F1.2 Query Length Bound | Enforce max input length limit (2000 chars) in `QueryProcessor.parse_and_normalize` to prevent resource exhaustion | M1 | Survey (Explorer 1) |
| 3 | F1.3 Exact-Phrase Quote Retention | Preserve surrounding double quotes in `clean_text` for exact-match retrieval dispatch | M1 | Survey (Explorer 1) |
| 4 | F1.4 Query Pipeline Regression Tests | Add dedicated regression tests for ReDoS, query length limits, and quote retention in `tools/test_retrieval_pipeline.py` & `tools/test_agent_tools.py` | M1 | Survey & AC |
| 5 | F2.1 Patch Cache Target Completeness | Dynamically derive tracked targets in `tools/apply-patches.py` to include `preferences.py` and `webadapter.py` | M2 | Survey (Explorer 2) |
| 6 | F2.2 Rollback Path Traversal Hardening | Validate `orig_path` and `bak_path` containment within repository/backup boundaries in `PatchTransaction.rollback()` | M2 | Survey (Explorer 2) |
| 7 | F2.3 CLI Report Path Validation | Restrict CLI `--report` argument in `tools/apply-patches.py` to repo root directory | M2 | Survey (Explorer 2) |
| 8 | F2.4 Windows NTFS ACL Lockdown | Enforce Windows NTFS ACL restriction via `icacls` on `config/secret.key` in `tools/ensure-secret-key.py` | M2 | Survey (Explorer 2) |
| 9 | F2.5 Secure Temp Files | Replace static `.tmp` filename creation with `tempfile.mkstemp` in `tools/ensure-secret-key.py` | M2 | Survey (Explorer 2) |
| 10 | F2.6 Quoted Settings Path Handling | Strip enclosing quotes from `SEARXNG_SETTINGS_PATH` in `searx/settings_loader.py` | M2 | Survey (Explorer 2) |
| 11 | F2.7 Automatic Upstream Sync Rollback | Pass `--rollback-on-failure` to `apply-windows-patches.ps1` in `tools/sync-upstream.ps1` | M2 | Survey (Explorer 2) |
| 12 | F2.8 Cache Cleaning Backup Retention | Preserve `python\.patches_backup` during default run of `tools/clean-cache.ps1` | M2 | Survey (Explorer 2) |
| 13 | F2.9 Scrape Keepalive Hardening | Disable keepalive connection pooling (`max_keepalive_connections=0` / `Connection: close`) in `/scrape` | M2 | Survey (Explorer 2) |
| 14 | F2.10 Patch System Regression Tests | Add dedicated unit regression tests for cache completeness, rollback security, and path containment in `tools/test_patches.py` | M2 | Survey & AC |
| 15 | F3.1 Settings Form Controls Labeling | Add explicit `<label for="...">` or `aria-label` to settings selects (`pref-default-mode`, `pref-safesearch`, `pref-default-count`, `pref-default-tokens`) in `webui_next.py` | M3 | Survey (Explorer 3) |
| 16 | F3.2 Skip-to-Content Link | Add visually hidden `.skip-link` pointing to primary search input `#q` in `tools/webui_next.py` | M3 | Survey (Explorer 3) |
| 17 | F3.3 Tablist Roving Tabindex | Implement WAI-ARIA roving `tabindex="-1"` on inactive tabs with Arrow key navigation in `tools/webui_next.py` | M3 | Survey (Explorer 3) |
| 18 | F3.4 Scrape Drawer ARIA Attributes | Synchronize `aria-expanded` and `aria-controls` on classic mode scrape drawer button in `tools/webui_next.py` | M3 | Survey (Explorer 3) |
| 19 | F3.5 Category Chips ARIA Pressed | Add `aria-pressed="true|false"` toggle state to category filter buttons in `tools/webui_next.py` | M3 | Survey (Explorer 3) |
| 20 | F3.6 Empty Query User Feedback | Display accessible validation feedback instead of silent abort on empty query submission in `tools/webui_next.py` | M3 | Survey (Explorer 3) |
| 21 | F3.7 Amber Contrast Adjustment | Darken light-theme `--amber` variable (to `#b45309`) ensuring WCAG 2.1 AA 4.5:1 minimum contrast | M3 | Survey (Explorer 3) |
| 22 | F3.8 Responsive 320px Grid Reflow | Refine `.engines-grid` auto-fill minmax rule to eliminate horizontal overflow on 320px viewports | M3 | Survey (Explorer 3) |
| 23 | F3.9 Form POST Parameter Retention | Retain form POST parameters during 302 redirect in `tools/webui_next.py:unified_search_view` | M3 | Survey (Explorer 1) |
| 24 | F3.10 Test Runner Ruff Fallback | Add `python\Scripts\ruff.exe` fallback check and explicit warning/error if Ruff is missing in `tools/run-tests.ps1` | M3 | Survey (Explorer 3) |
| 25 | F3.11 Live Settings Smoke Test | Add `/api/settings/engines` live assertion to `tools/smoke-test.ps1` | M3 | Survey (Explorer 3) |
| 26 | F3.12 WebUI Regression Tests | Add dedicated regression tests for WebUI accessibility attributes, POST redirect, and UI contracts in `tools/test_patches.py` | M3 | Survey & AC |
| 27 | F4.1 E2E Test Infrastructure | Design and execute comprehensive 4-tier E2E test suite (Category-Partition, BVA, Pairwise, Real-world workloads) | M4 | ORIGINAL_REQUEST |
| 28 | F4.2 Quality & Static Checks Gate | Verify Pyrefly (0 errors), Ruff lint, Ruff format, all unit test suites, evaluation benchmark, and live test runner pass 100% | M4 | ORIGINAL_REQUEST |
| 29 | F5.1 Master Summary Deliverable | Produce comprehensive report covering scope, issues by severity, design rationales, compatibility, and verification results | M5 | ORIGINAL_REQUEST (R5) |

---

## Milestones

| # | Name | Scope | Dependencies | Status |
|---|------|-------|-------------|--------|
| M1 | Backend Query Pipeline & Search Remediation | F1.1, F1.2, F1.3, F1.4 | none | DONE |
| M2 | Patch Management & Windows Security Hardening | F2.1, F2.2, F2.3, F2.4, F2.5, F2.6, F2.7, F2.8, F2.9, F2.10 | none | DONE |
| M3 | AI WebUI & Accessibility Compliance | F3.1, F3.2, F3.3, F3.4, F3.5, F3.6, F3.7, F3.8, F3.9, F3.10, F3.11, F3.12 | none | DONE |
| M4 | E2E Testing Track & Final Quality Gate | F4.1, F4.2 (Full verification: Pyrefly, Ruff, Unit Tests, Benchmark, Live Runner) | M1, M2, M3 | DONE |
| M5 | Final Deliverables & Master Summary Report | F5.1 (Comprehensive report satisfying R5) | M4 | DONE |

---

## Interface Contracts

### `tools/query_pipeline.py` ↔ `tools/retrieval_service.py`
- `QueryProcessor.parse_and_normalize(raw_query: str) -> ProcessedQuery`:
  - `raw_query`: strings longer than 2,000 characters are gracefully truncated without raising uncaught exceptions.
  - `ProcessedQuery.clean_text`: retains exact-phrase quotes (e.g. `"machine learning"`) and Japanese brackets so that downstream retrieval dispatch preserves exact phrase queries.
  - `clean_no_quotes`: stripped of ASCII double quotes for lexical BM25 ranking and intent classification.
  - `COMPARISON_PATTERNS`: regex match terminates in $< 5\text{ms}$ on pathological non-matching inputs of 20,000+ characters, correctly extracting entities for both unspaced Japanese (`PythonとRustの比較`), bracketed (`「Python」 vs 「Rust」`), and polite forms (`どちら`).

### `tools/apply-patches.py` ↔ `python/Lib/site-packages/searx/`
- `_get_tracked_targets() -> list[str]`:
  - Must return all target paths registered in `PATCH_SPECS`, ensuring that cache validation checks every file modified by patches.
- `PatchTransaction.rollback(force_backup: bool = False) -> bool`:
  - Must validate that every `orig_path` in `manifest.json` resides strictly within `REPO_ROOT` or `SITE_PACKAGES` and that `bak_path` resides strictly within `backup_dir`.
- `_scrape_client`:
  - Must use non-pooling or keepalive-disabled HTTP transport (`Connection: close` / `max_keepalive_connections=0`) to ensure DNS pinning is evaluated for each scrape request.

### `tools/webui_next.py` ↔ `searx/webapp.py`
- `unified_search_view() -> Response`:
  - On 302 redirect to `/?...`, if the request is an HTTP POST without an explicit format parameter, query parameters from `request.form` (such as `q`) must be merged into the redirect URL parameters.
- Public APIs (`/search`, `/scrape`, `/deep_search`, `/api/retrieval`):
  - Must retain 100% backward compatibility for request schemas and JSON/JSON-Lite response data contracts.

---

## Code Layout & Write Ownership
Strict file boundaries to prevent concurrent write collisions:
- **Milestone 1 Worker**: Exclusive write access to `tools/query_pipeline.py`, `tools/retrieval_service.py`, `tools/test_retrieval_pipeline.py`, `tools/test_agent_tools.py`.
- **Milestone 2 Worker**: Exclusive write access to `tools/apply-patches.py`, `tools/ensure-secret-key.py`, `tools/sync-upstream.ps1`, `tools/clean-cache.ps1`, `python/Lib/site-packages/searx/settings_loader.py`, `tools/test_patches.py`.
- **Milestone 3 Worker**: Exclusive write access to `tools/webui_next.py`, `tools/run-tests.ps1`, `tools/smoke-test.ps1`.
- **Milestone 4 / E2E Track**: Exclusive write access to `tests/e2e/`, `TEST_INFRA.md`, `TEST_READY.md`.
- **Milestone 5**: Exclusive write access to final deliverables summary report.
