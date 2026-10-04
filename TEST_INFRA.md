# E2E Test Infrastructure & Methodology (`TEST_INFRA.md`)

This document details the architecture, design principles, test inventory, and execution guide for the end-to-end (E2E) opaque-box test infrastructure in `SearXNGforWindowsNext`.

---

## 1. Architecture & Testing Methodology

The E2E testing framework provides **opaque-box verification** of the entire application stack. Rather than mocking internal Python components, tests interact with public HTTP endpoints (`/search`, `/scrape`, `/deep_search`, `/api/retrieval`, `/healthz`, `/ai`, `/api/settings/engines`) and command-line interfaces (`tools/searxng_cli.py`, `tools/apply-patches.py`, `tools/ensure-secret-key.py`).

### 1.1 Dual-Mode Execution Architecture (`tests/e2e/client.py`)

The test harness operates seamlessly across two distinct runtime environments:

1. **Live Server Mode**:
   - Detects whether a live SearXNG instance is running via `SEARXNG_BASE_URL` or `http://127.0.0.1:8888` (verified by probing `/healthz`).
   - If active, issues real HTTP/HTTPS requests over TCP sockets.
2. **Autonomous Ephemeral Server Mode**:
   - If no external server is running, the client spins up an in-process threaded WSGI server on a dynamic localhost port (`http://127.0.0.1:0`).
   - Exports `SEARXNG_BASE_URL` so that subprocess CLI tools (`searxng_cli.py`) can target the ephemeral server over genuine network sockets.
   - Cleanly shuts down the ephemeral server when test execution finishes, guaranteeing zero port collisions or leaked background processes.

### 1.2 Core Components

- **`tests/e2e/client.py`**:
  - `E2EResponse`: Unified response wrapper encapsulating HTTP status codes, headers, body text, and JSON decoding.
  - `E2EClient`: Dual-mode HTTP request dispatcher for GET and POST (form-encoded and JSON bodies).
  - `E2ECLIRunner`: Subprocess execution wrapper for Python CLI commands with argument and environment propagation.
  - `start_test_server()` / `stop_test_server()`: Lifecycle management for ephemeral testing instances.
- **`tests/e2e/run_e2e_tests.py`**:
  - Unified command-line runner supporting tier selection (`--tier 1,2,3,4`), verbose output (`-v`), fail-fast mode (`--fail-fast`), and machine-readable JSON telemetry (`--json`).

---

## 2. 4-Tier Test Suite Structure

The test suite is partitioned into four distinct tiers adhering to rigorous quality standards:

```
tests/e2e/
├── __init__.py
├── client.py                                 # Opaque-box client & server manager
├── run_e2e_tests.py                          # Unified CLI test runner
├── test_tier1_feature_coverage.py            # Tier 1: 37 Feature Coverage tests
├── test_tier2_boundary_corner_cases.py       # Tier 2: 34 Boundary & Corner Case tests
├── test_tier3_cross_feature.py               # Tier 3: 9 Cross-Feature Interaction tests
└── test_tier4_real_world_scenarios.py        # Tier 4: 5 Real-World Workflow tests
```

### Tier 1: Feature Coverage (37 Tests)
Validates primary functional behavior across all public API endpoints and CLI utilities:
- **/search**: HTML UI rendering, standard SearXNG JSON schema, GenAI `json_lite` schema, category filtering (`categories=it`), time range filtering (`time_range=month`), engine selection (`engines=duckduckgo`), and autocompletion (`/autocompleter`).
- **/scrape**: HTTP GET query extraction, form POST (`application/x-www-form-urlencoded`), JSON POST (`application/json`), client-side `max_length` truncation, focus keyword analysis (`/api/scrape_analyze`), and missing URL rejection (400).
- **/deep_search**: JSON response structure (`markdown`, `rag_prompt`, `results`, `estimated_tokens`), raw Markdown format (`format=markdown`), search depth modes (`fast` vs `advanced`), token budget caps, and domain inclusion filtering (`include_domains`).
- **/api/retrieval**: Fast mode (snippet-based), balanced mode (page passages), deep mode (multi-query synthesis), GenAI `schema_version: "1.0"` contracts, and category filtering.
- **JSON Formats**: Content-Type validation (`application/json`), `json_lite` vs standard JSON compactness, NaN/Infinity sanitization, and `/api/ai_info` introspection.
- **CLI Tools**: `searxng_cli health`, `searxng_cli search`, `searxng_cli scrape`, `searxng_cli deep`, `searxng_cli retrieval`, `apply-patches.py --check --json`, and `ensure-secret-key.py`.

### Tier 2: Boundary & Corner Cases (34 Tests)
Validates resilience against adversarial, pathological, and edge-case inputs:
- **Empty & Whitespace Inputs**: Empty query (`q=`), whitespace query (`q=%20%20`), empty scrape URL, whitespace scrape URL, empty deep search query, empty retrieval query, and CLI empty query handling.
- **Oversized Queries & Buffers**: Inputs exceeding 2,000 characters gracefully bounded, ReDoS resistance on pathological comparison queries terminating in $< 5\text{s}$, extreme `max_length` buffer bounds, count clamping to safe limits ($\le 50$), and large `max_tokens` handling.
- **Unicode & Special Characters**: Japanese CJK queries (`検索エンジンのテスト`), exact-phrase quotation retention (`"machine learning"`), HTML/XSS injection escaping, emojis and surrogate pairs (`🔍 AI 🚀`), regex meta-characters (`(a+)+ [0-9] *? $ \ / |`).
- **SSRF Defense Boundary**: Exhaustive validation of over 20 SSRF attack vectors:
  - IPv4 loopback (`127.0.0.1`, `127.0.0.2`)
  - Reserved hostnames (`localhost`, `nip.io`, `local`, `internal`)
  - Unspecified addresses (`0.0.0.0`)
  - Cloud metadata & link-local (`169.254.169.254`, `[fe80::1]`)
  - Private RFC 1918 ranges (`10.0.0.1`, `172.16.0.1`, `192.168.1.1`)
  - IPv6 loopback variants (`[::1]`, `[::ffff:127.0.0.1]`, `[::1]:80`)
  - Disallowed schemes (`file://`, `gopher://`, `ftp://`, `ws://`, `javascript:`, `data:`)
  - Obfuscated representations (decimal `2130706433`, shorthand `127.1`, octal `0177.0.0.1`, `017700000001`, overflow `999999999999`)
  - Unicode dots (ideographic `127。0。0。1`, fullwidth `127．0．0．1`, halfwidth `127｡0｡0｡1`)
  - Invalid ports (port `0`, port `70000`)
  - Reserved TLDs (`.localdomain`, `.intranet`, `.private`, `.arpa`)
- **Invalid Input Combinations**: Malformed JSON bodies, non-string URL types, unknown output format parameters, negative page numbers (`pageno=-5`), and invalid CLI subcommands.

### Tier 3: Cross-Feature Interactions (9 Tests)
Validates subsystem coupling and pairwise feature interactions:
- `json_lite` combined simultaneously with category and engine filtering.
- `deep_search` speculative page scraping with BM25 highlight extraction and graceful fallback when individual pages fail.
- CLI unified search auto-detecting URL strings and dynamically switching execution to page scraping.
- CLI search with domain inclusion constraints (`--site`).
- Secret key rotation preserving committed templates (`settings.yml.example`) while generating cryptographically secure 64-character hex keys in `config/secret.key`.
- Patch subsystem dry-run reporting writing valid diagnostic files without file mutation.
- WebUI route aliases (`/ai` and `/next`) serving identical workspace experiences.
- Form POST search redirect retaining user query parameters.

### Tier 4: Real-World Application Scenarios (5 Tests)
Validates realistic end-to-end production workloads:
- **Multi-Step AI Agent Research Workflow**: Retrieval query $\rightarrow$ citation extraction $\rightarrow$ deep scrape of primary citation $\rightarrow$ LLM RAG prompt construction.
- **Multi-Engine Aggregation & Deduplication**: Multi-engine retrieval synthesis validating rank normalization and strict URL deduplication.
- **Complete Operational Maintenance Lifecycle**: Sequential verification of secret key $\rightarrow$ patch validation $\rightarrow$ `/healthz` runtime check $\rightarrow$ `/api/settings/engines` inspection $\rightarrow$ CLI health status.
- **Concurrent Multi-Client Load**: Thread-pool concurrency executing simultaneous requests to `/search`, `/scrape`, and `/api/retrieval` without 500 errors, deadlocks, or socket exhaustion.
- **External Network Error Resilience**: Handling unreachable public domains without process aborts or unhandled exceptions.

---

## 3. How to Run the Test Suite

### 3.1 Standard Test Runner (Recommended)

Run the full 4-tier test suite using the embedded Python runtime:

```powershell
python\python.exe tests/e2e/run_e2e_tests.py
```

### 3.2 Selective Tier Execution

Execute specific tiers individually or in combination:

```powershell
# Run only Tier 1 (Feature Coverage)
python\python.exe tests/e2e/run_e2e_tests.py --tier 1

# Run Tiers 2 and 3 (Boundaries and Interactions)
python\python.exe tests/e2e/run_e2e_tests.py --tier 2,3

# Run Tier 4 (Real-World Scenarios)
python\python.exe tests/e2e/run_e2e_tests.py --tier 4
```

### 3.3 Verbose & JSON Machine-Readable Modes

```powershell
# Verbose execution with per-test reporting
python\python.exe tests/e2e/run_e2e_tests.py -v

# Emit JSON summary for CI/CD integration
python\python.exe tests/e2e/run_e2e_tests.py --json
```

### 3.4 Direct unittest Execution

Individual test files can also be run directly via `unittest`:

```powershell
python\python.exe tests/e2e/test_tier1_feature_coverage.py
python\python.exe tests/e2e/test_tier2_boundary_corner_cases.py
python\python.exe tests/e2e/test_tier3_cross_feature.py
python\python.exe tests/e2e/test_tier4_real_world_scenarios.py
```

---

## 4. Test Pass/Fail Semantics & Exit Codes

- **Exit Code `0`**: All executed test cases passed with zero failures and zero errors.
- **Exit Code `1`**: One or more test cases failed or encountered an uncaught exception.
- **Deterministic Teardown**: The test runner guarantees ephemeral background servers are stopped and ports released upon exit (including on keyboard interrupt or error).

---

## 5. Maintenance & Contribution Rules

1. **Test-Only Modifications**: Tests must interact through external interfaces and assert against observable behavior. Do not patch or bypass application logic inside tests.
2. **Deterministic Outputs**: Where external networks are queried, tests assert on status code sets and graceful error payloads rather than specific third-party page contents.
3. **Encoding Discipline**: Test files and runners must remain compatible with Windows CP932 and UTF-8 console output.
4. **Clean Static Validation**: All test files must pass Pyrefly (`python -m pyrefly check`), Ruff lint (`ruff check tests/e2e`), and Ruff formatting (`ruff format --check tests/e2e`).
