# Exhaustive Survey & Audit Report: WebUI, Accessibility & Test Harness

**Auditor**: Explorer 3 (WebUI, Accessibility & Test Harness Auditor)  
**Date**: 2026-10-04  
**Workspace**: `c:\Users\mibu0\Documents\develop\SearXNGforWindowsNext`  
**Working Directory**: `.agents\teamwork\explorer_survey_3\`  
**Target Components**: Unified AI WebUI (`tools/webui_next.py`, static assets, templates), Accessibility & Responsiveness, Test Harness & Static Quality (`tools/run-tests.ps1`, `tests/evaluation/run_benchmark.py`, `pyproject.toml`, Pyrefly, Ruff), Baseline Test Execution Status.

---

## 1. Executive Summary & Audit Scope

This investigation conducted an exhaustive audit of the front-end user experience, accessibility compliance (WCAG 2.1 AA), static verification tooling, test infrastructure, and baseline execution status for the **SearXNG for Windows Next** project.

### Key Audit Findings Summary
1. **Unified AI WebUI Architecture**: `tools/webui_next.py` provides an all-in-one, zero-dependency embedded SPA (`AI_WORKSPACE_HTML`, 2,551 lines of HTML/CSS/JS) and progressive enhancement assets (`SIMPLE_EMBED_CSS`, `SIMPLE_EMBED_JS`) without external CDN or node dependencies. Routing cleanly intercepts browser requests to `/`, `/search`, `/preferences`, and `/about` into the Unified Studio while preserving backward compatibility for JSON/REST/MCP API callers.
2. **Current Baseline Quality**: All existing static quality checks and unit/smoke tests pass cleanly:
   - **Pyrefly Type Checker**: 0 errors (1 suppressed in `tools/disable-missing-engines.py:8` for `yaml`).
   - **Ruff Linter & Formatter**: 100% clean across all 46 Python files (120 char line limit).
   - **Unit Test Suites**: 303 unit tests pass across 4 suites (`test_patches.py`, `test_agent_tools.py`, `test_agentic_search.py`, `test_retrieval_pipeline.py`) in < 2.5s.
   - **Offline Retrieval Benchmark**: 10 queries evaluated across 3 modes (`fast`, `balanced`, `deep`), achieving 100% official source presence, 1.0000 P@5, and 0.9766 nDCG@10.
   - **End-to-End Live Harness (`run-tests.ps1`)**: Complete lifecycle passes, executing all 40 smoke tests against a live Granian WSGI server on port 8888.
3. **Accessibility & Usability Defects Identified**: 8 accessibility defects were uncovered, including unlabelled form controls in General Settings (`pref-default-mode`, `pref-safesearch`, `pref-default-count`, `pref-default-tokens`), absence of a skip-to-content link, missing roving `tabindex` on tablists, missing `aria-expanded` on classic mode scrape drawers, missing `aria-pressed` on category toggle chips, silent failure on empty query submission, low contrast for `--amber` in light mode, and a minor 320px viewport card grid reflow overflow.
4. **Test Infrastructure Gaps Identified**: 4 test harness gaps were identified, including conditional (potentially bypassable) Ruff execution in `run-tests.ps1`, omission of `/api/settings/engines` in live smoke tests, absence of an automated headless DOM test runner for client-side JavaScript, and limited sample size (10 queries) in the offline benchmark.

---

## 2. Unified AI WebUI Architecture & Source Breakdown

### 2.1 Server-Side Integration & Route Interception (`tools/webui_next.py`)

The WebUI server integration is initialized via `register_next_webui(app, webapp_mod)` hooked inside `python/Lib/site-packages/searx/webapp.py:643` (patched by `tools/apply-patches.py:2179`).

```
                              [Incoming HTTP Request]
                                         │
                   ┌─────────────────────┴─────────────────────┐
                   │                                           │
         Method == GET?                              Method == POST / Other
                   │                                           │
         [Tier A: before_request]                              │
     ┌─────────────┼─────────────┬─────────────┐               │
     ▼             ▼             ▼             ▼               │
Path == "/"   Path == "/search"  Path ==       Path ==         │
(Serve SPA    (Check format/     "/preferences""/about"        │
 AI Studio)    Accept header)    (Redirect     (Redirect       │
                   │             /?mode=       /?mode=         │
             Format requested?   settings)     agent)          │
             ├─ Yes: Continue                                  │
             └─ No:  302 -> /?q=                               │
                   │                                           │
                   ▼                                           ▼
         [Tier B: view_functions & Custom Registered Routes]
         ├─ /ai & /next               ──> AI_WORKSPACE_HTML
         ├─ /ai/embed.css             ──> SIMPLE_EMBED_CSS
         ├─ /ai/embed.js              ──> SIMPLE_EMBED_JS
         ├─ /api/ai_info              ──> JSON capability introspection
         ├─ /api/settings/engines     ──> GET/POST engine states & cookies
         ├─ /api/scrape_analyze       ──> In-process SSRF-hardened scraper
         ├─ /deep_search, /api/search ──> Unified deep/fast/classic search
         └─ /api/retrieval            ──> GenAI Retrieval API (schema 1.0)
```

#### Dual-Tier Interception Mechanics:
1. **Tier A (`app.before_request`)**:
   - `path == "/"`: Serves `AI_WORKSPACE_HTML` directly as `text/html`.
   - `path == "/search"`: Inspects `request.args.get("format")` and `Accept` header. If no data format (`json`, `json_lite`, `csv`, `rss`) and no `application/json` header is requested, redirects 302 to `/?{querystring}`.
   - `path == "/preferences"`: Redirects browser requests to `/?mode=settings` (302).
   - `path == "/about"`: Redirects browser requests to `/?mode=agent` (302).
2. **Tier B (`app.view_functions` overrides)**:
   - Overrides `app.view_functions["index"]`, `["search"]`, `["preferences"]`, and `["about"]` to guard against internal route dispatches. POST requests to `/preferences` continue to delegate to the upstream preferences handler for backward compatibility.

### 2.2 Dedicated AI Workspace SPA (`AI_WORKSPACE_HTML`)

Lines 1424–3977 of `tools/webui_next.py` contain the entire SPA implementation:
- **Zero External Dependencies**: Pure CSS3 and vanilla ES6/DOM JavaScript with no external CDNs, fonts, or libraries, ensuring full offline functionality and zero supply-chain risk.
- **Color Theming**: Dynamic theme switching via `[data-theme="dark"]` and `[data-theme="light"]`, stored in `localStorage.getItem('sxng_ai_theme')`.
- **Four Integrated Working Modes**:
  1. `deep` (**AI Deep Search**): Split grid layout (`.split-grid`). Left column displays ranked results with score badges, authoritativeness indicators, and BM25 highlights. Right column displays the sticky **LLM Context Inspector** with real-time token budgeting bar and tabs for Markdown, RAG Prompt, JSON, and cURL/CLI.
  2. `classic` (**Classic Search**): Centered single-column layout (`.classic-view-wrap`), category pills (All, IT, News, Science, Files, Social, Images, Videos), time-range filter, and pagination. Includes a 1-click **⚡ AIで深掘り** button on every card to escalate to Deep Search.
  3. `agent` (**Agent & MCP Hub**): Ready-to-copy configurations for Claude Code MCP, Cursor/Windsurf (`mcp.json`), OpenCode (`opencode.json`), CLI (`searxng_cli.py`), and GenAI Retrieval API.
  4. `settings` (**Settings Dashboard**): Real-time telemetry cards (Active Engines, Suspended Engines, Average Latency, Overall Reliability), engine search filter, category bulk-toggle actions (Enable All, Disable All, Restore Defaults), and General Preferences persistence.

### 2.3 Progressive Enhancement Assets for SearXNG Simple Theme

Injected into upstream `searx/templates/simple/base.html` via `tools/apply-patches.py`:
- `SIMPLE_EMBED_CSS` (lines 881–1098): Styles the topbar AI badge, Quick Actions bar on the homepage, AI Agent Toolkit bar on search results, token pill counter, and expandable inline scrape drawers.
- `SIMPLE_EMBED_JS` (lines 1099–1423): Progressively enhances standard SearXNG results pages by attaching:
  - 1-click **📋 AI用Markdownをコピー** and **💬 プロンプト形式でコピー**.
  - Dynamic token estimation pill (`~X tokens`) calculated via CJK-aware weighting.
  - Per-result **📄 本文抽出** button triggering `/api/scrape_analyze` inline.
  - 1-click **⚡ Deep Search** expandable drawer executing `/deep_search`.

---

## 3. Accessibility & Responsiveness Audit (WCAG 2.1 AA Compliance)

### 3.1 Viewport Responsiveness Across Widths

| Viewport Width | Tested Breakpoint | Layout Behavior | Audit Assessment |
|---|---|---|---|
| **Desktop (≥ 1280px)** | `1440px`, `1280px` | `.split-grid`: `1.25fr 0.95fr`. Left side displays result cards, right side displays sticky LLM Context Inspector (`top: 4.8rem`, `max-height: calc(100vh - 6rem)`). Topbar elements horizontal. | **Pass**: Clean visual hierarchy, no overflow. |
| **Tablet / Narrow Laptop (< 1024px)** | `1024px`, `768px` | `@media (max-width: 1024px)` collapses `.split-grid` to `1fr`. Context Inspector un-sticks (`position: static`) and stacks beneath result cards. | **Pass**: Smooth reflow, natural vertical scrolling. |
| **Mobile (< 640px)** | `640px`, `375px` | `@media (max-width: 640px)` wraps `.search-bar-row`, makes `#run-btn` full width (`100%`), hides `.kbd-hint` (`display: none`), expands `.preset-chips` to `100%`, reduces topbar/workspace padding. | **Pass**: Touch targets exceed 44×44px, inputs expand to full width. |
| **Narrow Mobile (320px)** | `320px` (iPhone SE) | Most components reflow cleanly. However, `.engines-grid` specifies `minmax(310px, 1fr)`. Container padding is 0.9rem (~14.4px each side = 28.8px), leaving ~291.2px available width, causing a minor ~19px horizontal scrollbar on the settings tab. | **Defect (A11Y-08)**: Needs `minmax(min(100%, 280px), 1fr)`. |

### 3.2 Keyboard Navigation & Focus Management

- **Focus Indicators**: Explicitly defined in lines 1647–1656:
  ```css
  .btn:focus-visible, .nav-tab:focus-visible, .settings-subtab:focus-visible,
  .chip:focus-visible, .cat-btn:focus-visible, .ctx-tab:focus-visible, .brand-logo:focus-visible {
    outline: 2px solid var(--accent);
    outline-offset: 2px;
  }
  ```
- **Tablist Keyboard Handling**:
  - `nav-tabs` (lines 2887–2894): Listens for `ArrowRight` and `ArrowLeft` to navigate and activate tabs with circular wrap-around.
  - `context-tabs` (lines 2964–2971): Listens for `ArrowRight` and `ArrowLeft` to navigate output formats.
  - `settings-subtabs` (lines 3691–3704): Listens for `ArrowRight`/`ArrowDown` and `ArrowLeft`/`ArrowUp` to switch subtabs.
- **Global Shortcuts**:
  - `/` (slash) focuses search input `#q` unless active element is an input, textarea, or contentEditable.
  - `Ctrl+K` / `Cmd+K` focuses and selects `#q`.
  - `Escape` dismisses toasts and closes open scrape drawers.
- **Gaps Identified**:
  - Inactive tabs do not specify `tabindex="-1"`, violating the WAI-ARIA APG roving tabindex pattern (**A11Y-03**).
  - No skip link exists to bypass the header and land directly on `#q` or `#results-container` (**A11Y-02**).

### 3.3 Form Input Accessibility & ARIA Roles

- **Search Inputs**:
  - `#q` has `aria-label="Search query or target URL"`.
  - `#engine-search-input` has `aria-label="検索エンジンの絞り込み"`.
  - `#ctx-output` has `aria-label="Generated AI Context"`.
- **Search Option Controls**:
  - `<select id="opt-depth">`, `<select id="opt-count">`, `<select id="opt-tokens">`, `<input id="opt-site">`, `<select id="classic-time-range">`, `<select id="classic-count">`, `<select id="opt-scrape-len">`, `<input id="opt-scrape-query">` all have explicit `<label for="...">` elements.
- **Settings Form Defect**:
  - General Settings dropdowns (`pref-default-mode`, `pref-safesearch`, `pref-default-count`, `pref-default-tokens`) are only preceded by sibling `<h4>` headings with no `label` or `aria-label` (**A11Y-01**).

### 3.4 Color Contrast Analysis

- **Dark Theme (`[data-theme="dark"]`)**:
  - Main text `#f1f5f9` on background `#0b0f19`: **16.5:1** (WCAG AAA passes).
  - Secondary text `#94a3b8` on background `#0b0f19`: **8.6:1** (WCAG AAA passes).
  - Muted text `#64748b` on background `#0b0f19`: **4.7:1** (WCAG AA passes).
  - Primary button `#ffffff` on `#6366f1`: **4.6:1** (WCAG AA passes).
  - Emerald badge `#10b981` on `#0b0f19`: **8.0:1** (WCAG AAA passes).
- **Light Theme (`[data-theme="light"]`)**:
  - Main text `#0f172a` on background `#ffffff`: **18.2:1** (WCAG AAA passes).
  - Secondary text `#475569` on background `#ffffff`: **7.5:1** (WCAG AAA passes).
  - Primary button `#ffffff` on `#4f46e5`: **5.9:1** (WCAG AA passes).
  - Amber badge `--amber: #d97706` on `#ffffff`: **~3.5:1** (**Defect A11Y-07**, fails WCAG AA 4.5:1 for normal text). Darkening to `#b45309` gives 4.8:1.

---

### 3.5 Detailed Accessibility & Usability Findings Catalog

```
┌──────────┬────────────────────────────────────────────────────────┬──────────┬─────────────────────────────┐
│ ID       │ Finding Summary                                        │ Severity │ Standard / Guideline        │
├──────────┼────────────────────────────────────────────────────────┼──────────┼─────────────────────────────┤
│ A11Y-01  │ General Settings form controls lack label associations │ Medium   │ WCAG 1.3.1 & 4.1.2 Level A  │
│ A11Y-02  │ Absence of Skip-to-Content Link                        │ Low/Med  │ WCAG 2.4.1 Level A          │
│ A11Y-03  │ Roving tabindex not implemented on tablists            │ Low      │ WAI-ARIA APG Tabs Pattern   │
│ A11Y-04  │ Classic mode scrape button missing aria-expanded       │ Low      │ WCAG 4.1.2 Level A          │
│ A11Y-05  │ Category toggle chips lack aria-pressed attribute      │ Low      │ WCAG 4.1.2 Level A          │
│ A11Y-06  │ Empty query submission produces no user error notice   │ Low      │ WCAG 3.3.1 & 3.3.3 Level A  │
│ A11Y-07  │ Light theme amber contrast ratio below WCAG AA         │ Low      │ WCAG 1.4.3 Level AA         │
│ A11Y-08  │ Engine grid card width overflow on 320px viewport      │ Low      │ WCAG 1.4.10 Level AA        │
└──────────┴────────────────────────────────────────────────────────┴──────────┴─────────────────────────────┘
```

#### Detailed Defect Breakdown:

#### 1. A11Y-01: General Settings Form Controls Lack Explicit Label Associations
- **Severity**: Medium
- **Location**: `tools/webui_next.py`: lines 2623–2679
- **Observation**:
  ```html
  <div class="settings-row">
    <div class="settings-label-wrap">
      <h4>デフォルト検索モード</h4>
      <p>検索トップ画面にアクセスした際、または外部から検索時の初期モード</p>
    </div>
    <div>
      <select id="pref-default-mode" class="opt-select" style="min-width:14rem;">
  ```
  The `<select id="pref-default-mode">`, `<select id="pref-safesearch">`, `<select id="pref-default-count">`, and `<select id="pref-default-tokens">` controls have no associated `<label for="...">` or `aria-labelledby`/`aria-label` attribute.
- **Impact**: Screen readers announce the controls as "unlabelled combobox", leaving users unable to determine what setting they are adjusting.
- **Recommended Remediation**:
  Wrap the heading text in `<label for="pref-default-mode"><h4>デフォルト検索モード</h4></label>` or add `aria-labelledby` linking to heading IDs.

#### 2. A11Y-02: Absence of Skip-to-Content Link
- **Severity**: Low / Medium
- **Location**: `tools/webui_next.py`: line 2352
- **Observation**:
  `<body>` immediately opens `<header class="topbar">`. There is no `<a href="#q" class="skip-link">` or `<a href="#main-split-view">`.
- **Impact**: Keyboard-only users must Tab through the logo, badge, and 4 navigation tabs before reaching the primary input `#q` or search results on every page visit.
- **Recommended Remediation**:
  Add an accessible skip link immediately inside `<body>`:
  ```html
  <a href="#q" class="skip-link">検索入力へスキップ</a>
  ```
  with CSS:
  ```css
  .skip-link {
    position: absolute; top: -999px; left: 1rem; z-index: 1000;
    padding: 0.5rem 1rem; background: var(--accent); color: #fff;
    border-radius: 0.4rem; font-weight: 700;
  }
  .skip-link:focus { top: 1rem; }
  ```

#### 3. A11Y-03: Roving Tabindex Not Implemented on Tablists
- **Severity**: Low
- **Location**: `tools/webui_next.py`: lines 2363–2366, 2534–2537, 2597–2598, 2848–2850
- **Observation**:
  Tab buttons (`.nav-tab`, `.ctx-tab`, `.settings-subtab`) all retain default `tabindex="0"`.
- **Impact**: In standard WAI-ARIA tablists, tabbing should land on the currently active tab (`tabindex="0"`), while inactive tabs should have `tabindex="-1"` so a single Tab key moves into the tabpanel.
- **Recommended Remediation**:
  Initialize inactive tabs with `tabindex="-1"` and update `tabindex` dynamically alongside `aria-selected` in `setMode()`, `selectCtxTab()`, and `selectSettingsSubtab()`.

#### 4. A11Y-04: Classic Mode Scrape Button Missing `aria-expanded` and `aria-controls`
- **Severity**: Low
- **Location**: `tools/webui_next.py`: lines 3289–3307
- **Observation**:
  In `renderClassicSearchResults()`, `scrapeBtn` toggles the inline scrape drawer without setting or toggling `aria-expanded`. (In `renderSearchResults()` for Deep mode, `aria-expanded` is set, but omitted in classic mode).
- **Impact**: Screen reader users expanding the drawer in classic search mode are not informed that collapsible content has opened.
- **Recommended Remediation**:
  Initialize `scrapeBtn.setAttribute('aria-expanded', 'false')` and toggle it on click.

#### 5. A11Y-05: Category Filter Chips Lack `aria-pressed` State
- **Severity**: Low
- **Location**: `tools/webui_next.py`: lines 2448–2455, 3627–3650
- **Observation**:
  `.cat-btn` elements toggle category filters, indicating active state solely through `.classList.add('active')`.
- **Impact**: Screen reader users hear the category name but are not told whether it is currently filtered/active.
- **Recommended Remediation**:
  Initialize active chip with `aria-pressed="true"` and inactive chips with `aria-pressed="false"`, updating them in the click listeners.

#### 6. A11Y-06: Empty Query Submission Produces No User Error Notice
- **Severity**: Low
- **Location**: `tools/webui_next.py`: line 3885
- **Observation**:
  `executeCurrentAction()` executes `if (!qVal) return;`.
- **Impact**: Pressing Enter or clicking ⚡ 統合検索 when `#q` is empty produces no visible error or screen reader announcement.
- **Recommended Remediation**:
  Show a polite error notice:
  ```javascript
  if (!qVal) {
    showToast('検索キーワードまたはURLを入力してください');
    document.getElementById('q').focus();
    return;
  }
  ```

#### 7. A11Y-07: Light Theme Amber Color Contrast Below WCAG AA
- **Severity**: Low
- **Location**: `tools/webui_next.py`: line 1468
- **Observation**:
  `--amber: #d97706` in light theme has a ~3.5:1 contrast against white `#ffffff`.
- **Impact**: Suspended engine badges and warnings do not meet the 4.5:1 WCAG AA threshold for normal text.
- **Recommended Remediation**:
  Update `--amber: #b45309;` in `[data-theme="light"]` (yielding 4.8:1 contrast).

#### 8. A11Y-08: Engine Grid Card Width Reflow Overflow on 320px Viewport
- **Severity**: Low
- **Location**: `tools/webui_next.py`: line 2152
- **Observation**:
  `.engines-grid` uses `grid-template-columns: repeat(auto-fill, minmax(310px, 1fr));`.
- **Impact**: On a 320px viewport with 28.8px container padding (291.2px width available), 310px forces an unwanted horizontal scrollbar.
- **Recommended Remediation**:
  Update to `grid-template-columns: repeat(auto-fill, minmax(min(100%, 280px), 1fr));`.

---

## 4. Test Infrastructure & Static Quality Audit

### 4.1 Static Verification Configurations

#### 1. Pyrefly Configuration (`pyproject.toml:15–27`):
```toml
[tool.pyrefly]
python-interpreter-path = "python/python.exe"
python-version = "3.11"
python-platform = "windows"
project-includes = [
    "tools/**/*.py",
    "tests/**/*.py",
]
search-path = [
    "tools",
    "python/Lib/site-packages",
]
```
- **Evaluation**: Targets the embedded Python 3.11 Windows runtime. Inspects all scripts in `tools/` and `tests/`.
- **Suppression Audit**: Pyrefly reports `0 errors (1 suppressed)`. Investigation confirmed the single suppression is in `tools/disable-missing-engines.py:8`:
  ```python
  import yaml  # type: ignore[untyped-import]
  ```
  This is a legitimate untyped import ignore for `pyyaml`, which does not ship inline type stubs.

#### 2. Ruff Configuration (`pyproject.toml:1–13`):
```toml
[tool.ruff]
line-length = 120
target-version = "py311"
extend-exclude = [
    "python",
    "config/*.upstream.py",
    "config/setup.upstream.py",
]

[tool.ruff.lint]
ignore = [
    "N999",  # Hyphenated script filenames in tools/
]
```
- **Evaluation**: Properly excludes the 134MB embedded `python/` directory and upstream boilerplate. Ignores PEP 8 module name convention `N999` to allow hyphenated CLI script names (`apply-patches.py`, `run-tests.ps1`, `disable-missing-engines.py`).

### 4.2 Test Runner Harness (`tools/run-tests.ps1`)

The runner executes a complete 6-stage lifecycle:
1. `Stop-PortListeners -Port 8888`: Automatically kills stale processes holding port 8888.
2. `install-requirements.ps1 -Dev` (skipped if `-SkipInstall` passed).
3. Configuration and secret validation: verifies `settings.yml` and generates secure key via `tools/ensure-secret-key.py`.
4. Patch verification: executes `tools/apply-patches.py` to ensure all 26 patches are applied idempotently.
5. Unit tests & static checks:
   - `tools/test_patches.py`
   - `tools/test_agent_tools.py`
   - `tools/test_agentic_search.py`
   - `tools/test_retrieval_pipeline.py`
   - `tests/evaluation/run_benchmark.py`
   - `python\python.exe -m pyrefly check`
   - `ruff check .` & `ruff format --check .`
6. Live server & smoke tests:
   - Spawns Granian WSGI background server: `python -m granian --interface wsgi searx.webapp:application --host 127.0.0.1 --port 8888 --blocking-threads 4 --no-ws`.
   - Polls `http://127.0.0.1:8888` for readiness up to 30 seconds.
   - Executes `tools/smoke-test.ps1` (40 comprehensive tests).
   - `finally` block: recursively discovers and terminates the Granian worker process tree and frees port 8888.

### 4.3 Retrieval Evaluation Benchmark Harness (`tests/evaluation/run_benchmark.py`)

- **Execution Model**: Deterministic offline benchmark consuming frozen search/scrape fixtures (`tests/evaluation/offline_fixtures.json`) against 10 queries (5 Japanese, 5 English) with ground truth domains (`tests/evaluation/expected_sources.json`).
- **Telemetry Evaluated**: Precision@5, Recall@10, MRR, nDCG@10, Deduplication Rate, Official Source Presence Rate, Evidence Passage Extraction Rate, Content Extraction Success Rate, Latency (mean, p95), Mean Payload Character Count, Partial Failure Rate.

---

### 4.4 Detailed Test Infrastructure Findings Catalog

```
┌──────────┬────────────────────────────────────────────────────────┬──────────┬─────────────────────────────┐
│ ID       │ Finding Summary                                        │ Severity │ Affected File               │
├──────────┼────────────────────────────────────────────────────────┼──────────┼─────────────────────────────┤
│ TEST-01  │ Ruff check conditionally bypassed if not on system PATH│ Low      │ tools/run-tests.ps1:110-121 │
│ TEST-02  │ /api/settings/engines lacks live test in smoke-test.ps1 │ Low      │ tools/smoke-test.ps1        │
│ TEST-03  │ Absence of headless DOM / browser test automation      │ Medium   │ Workspace Test Suites       │
│ TEST-04  │ Benchmark query sample size limited to 10 queries      │ Low      │ tests/evaluation/           │
└──────────┴────────────────────────────────────────────────────────┴──────────┴─────────────────────────────┘
```

#### Detailed Breakdown:

#### 1. TEST-01: Ruff Check Conditionally Bypassed if Not on System PATH
- **Severity**: Low
- **Location**: `tools/run-tests.ps1`: lines 110–121
- **Observation**:
  `$ruffCmd = Get-Command "ruff" -ErrorAction SilentlyContinue`
  If `ruff` is not found in the environment's `PATH`, the script skips linter checks without warning or exit code failure.
- **Remediation**:
  Check for `python\Scripts\ruff.exe` as fallback, and issue a clear warning if Ruff cannot be located:
  ```powershell
  if (-not $ruffCmd) {
      $fallbackRuff = Join-Path $repoRoot "python\Scripts\ruff.exe"
      if (Test-Path $fallbackRuff) { $ruffCmd = @{ Source = $fallbackRuff } }
  }
  ```

#### 2. TEST-02: `/api/settings/engines` Lacks Live Test in `smoke-test.ps1`
- **Severity**: Low
- **Location**: `tools/smoke-test.ps1`
- **Observation**:
  `smoke-test.ps1` tests 40 endpoints, but does not test `/api/settings/engines` GET or POST against the live running server (it is only tested against a mock Flask app in unit tests).
- **Remediation**:
  Add an integration test in `tools/smoke-test.ps1` validating that `/api/settings/engines` returns HTTP 200 with `total_engines > 0` and `active_engines > 0`.

#### 3. TEST-03: Absence of Automated Headless DOM Test Runner for Client-Side JS
- **Severity**: Medium
- **Location**: Test Suites
- **Observation**:
  Client-side JavaScript syntax is tested via `node --check`, but interactive DOM state changes (tab switching, keyboard shortcuts `/` and `Ctrl+K`, token count recalculation, theme toggle, drawer collapse) are not verified in a headless browser test.
- **Remediation**:
  Add a lightweight JSDOM or Playwright test script to the test suite to verify client-side DOM interactions automatically.

#### 4. TEST-04: Benchmark Query Sample Size Limited to 10 Queries
- **Severity**: Low
- **Location**: `tests/evaluation/queries_ja.jsonl`, `queries_en.jsonl`
- **Observation**:
  The evaluation benchmark tests 10 queries (5 JA, 5 EN). While fast (runs in 0.05s), it has limited diversity for nuanced retrieval regressions.
- **Remediation**:
  Expand query datasets to 25 JA and 25 EN queries covering complex phrasing, operator searches (`site:`, `-site:`), and multi-lingual programming errors.

---

## 5. Baseline Test Execution Results (Empirical Verification)

All tests were executed on the active system. Results are summarized below:

### 5.1 Static Type Checking & Code Quality

```
Command: .\python\python.exe -m pyrefly check
Result:  EXIT 0
Output:  INFO Checking project configured at `...\pyproject.toml`
         INFO 0 errors (1 suppressed)

Command: ruff check .
Result:  EXIT 0
Output:  All checks passed!

Command: ruff format --check .
Result:  EXIT 0
Output:  46 files already formatted
```

### 5.2 Unit Test Execution

```
┌─────────────────────────────────┬──────────┬──────────┬──────────┐
│ Suite Name                      │ Tests    │ Duration │ Status   │
├─────────────────────────────────┼──────────┼──────────┼──────────┤
│ tools/test_patches.py           │ 161      │ 1.140s   │ PASSED   │
│ tools/test_agent_tools.py       │ 57       │ 0.353s   │ PASSED   │
│ tools/test_agentic_search.py    │ 41       │ 0.830s   │ PASSED   │
│ tools/test_retrieval_pipeline.py│ 44       │ 0.020s   │ PASSED   │
├─────────────────────────────────┼──────────┼──────────┼──────────┤
│ Total Unit Tests                │ 303      │ 2.343s   │ 100% OK  │
└─────────────────────────────────┴──────────┴──────────┴──────────┘
```

### 5.3 Offline Retrieval Benchmark Execution

```
Command: .\python\python.exe tests\evaluation\run_benchmark.py
Total Queries: 10 (JA: 5, EN: 5)
```

| Mode | P@5 | Recall@10 | MRR | nDCG@10 | Dedup Rate | Official Source | Evidence Passages | Mean Latency | Mean Payload |
|---|---|---|---|---|---|---|---|---|---|
| **fast** | 1.0000 | 0.7683 | 1.0000 | 0.9766 | 2.5% | 100.0% | 0.0% | 1.95 ms | 182 chars |
| **balanced** | 1.0000 | 0.7683 | 1.0000 | 0.9766 | 2.5% | 100.0% | 58.3% | 3.05 ms | 293 chars |
| **deep** | 1.0000 | 0.7683 | 1.0000 | 0.9766 | 2.5% | 100.0% | 58.3% | 3.24 ms | 293 chars |

*Benchmark Observations*:
- All modes achieve perfect Top-1 official source presence (MRR 1.0000) and 0.9766 nDCG@10.
- `fast` mode omits heavy passage extraction for sub-2ms response latency.
- `balanced` and `deep` extract citable evidence passages in 58.3% of search items within 3.2ms.
- Partial failure rate across all queries is 0.0%.

### 5.4 End-to-End Test Harness Execution (`tools/run-tests.ps1 -SkipInstall`)

- **Execution Result**: PASSED (Exit Code: 0)
- **Lifecycle Verified**:
  1. Stale port listeners killed on port 8888.
  2. Secret key verified / generated.
  3. All 26 compatibility patches verified.
  4. All 303 unit tests passed.
  5. Benchmark passed across all modes.
  6. Pyrefly type checking passed.
  7. Ruff check and format passed.
  8. Granian WSGI server started on port 8888.
  9. **All 40 Smoke Tests Passed**:
     - Root page accessible search input (Test 1)
     - Standard JSON API & `json_lite` GenAI format (Tests 2–3)
     - `/scrape` endpoint (POST Form, POST JSON, GET) (Tests 4–6)
     - SSRF Protection: 21 comprehensive vectors blocked (Tests 7–27)
     - Autocompleter, error validation, healthcheck, preferences (Tests 28–32)
     - SearXNG CLI health check, search, unified search, scrape (Tests 33–35)
     - AI-First WebUI (`/ai`), `embed.css`, `embed.js` (Test 36)
     - `/api/ai_info`, `/deep_search`, `/api/scrape_analyze`, `/api/retrieval` (Tests 37–40)
  10. Background server process tree terminated cleanly with zero dangling processes.

---

## 6. Proposed E2E and Regression Testing Strategy

To permanently safeguard WebUI accessibility, user experience, and test infrastructure stability, the following testing strategy is proposed:

### 6.1 Dedicated WebUI Accessibility Regression Tests (Unit Level)

Add dedicated assertions to `tools/test_patches.py` within `TestWebUINextRegression`:
1. **Form Labels Assertion**:
   - Parse `AI_WORKSPACE_HTML` using `re` or `html.parser`.
   - Assert every `<select>` and `<input type="text">` inside `<section id="settings-view">` has an associated `<label for="...">` or `aria-label`/`aria-labelledby`.
2. **Skip Link Assertion**:
   - Assert `class="skip-link"` is present and points to `#q` or `#main-split-view`.
3. **Tablist Roving Tabindex Assertion**:
   - Assert inactive tab elements have `tabindex="-1"` and active tab has `tabindex="0"`.
4. **Disclosure Attribute Assertion**:
   - Assert all expandable drawer buttons in both `renderSearchResults` and `renderClassicSearchResults` initialize and toggle `aria-expanded`.
5. **Contrast Assertion**:
   - Assert `--amber` in `[data-theme="light"]` is `#b45309` or darker.
6. **Reflow Assertion**:
   - Assert `.engines-grid` does not use fixed `minmax(310px, 1fr)` without a `min(100%, ...)` clause.

### 6.2 Smoke Test Harness Enhancements (`tools/smoke-test.ps1`)

Add two dedicated smoke tests to `tools/smoke-test.ps1`:
1. **Test 41: `/api/settings/engines` Endpoint Integration**:
   - `GET /api/settings/engines`: verify HTTP 200, JSON properties `engines`, `categories`, `total_engines`, `active_engines`.
   - `POST /api/settings/engines`: send JSON payload with `disabled_engines`, verify `Set-Cookie` header contains `disabled_engines=`.
2. **Test 42: WebUI Skip Link & Form Accessibility Check**:
   - Fetch `/`: verify HTML content contains `class="skip-link"` and verify `<label for="pref-default-mode">` is present.

### 6.3 Test Runner Hardening (`tools/run-tests.ps1`)

Update `tools/run-tests.ps1` lines 110–121:
- Automatically check `python\Scripts\ruff.exe` if `ruff` is not found in global `PATH`.
- Throw or log a high-visibility warning if Ruff is unavailable, preventing silent linter bypass in CI or fresh clones.

---

## 7. Conclusion

The SearXNG for Windows Next WebUI and test infrastructure are functionally mature, highly performant, and stable. The 8 identified accessibility defects and 4 test harness gaps are precisely localized, fully understood, and straightforward to remediate without breaking changes. Implementing the recommended fixes will elevate the WebUI to full WCAG 2.1 AA compliance and harden the test infrastructure for continuous regression protection.
