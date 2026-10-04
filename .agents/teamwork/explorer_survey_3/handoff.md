# Handoff Report: WebUI, Accessibility & Test Harness Audit

**Agent**: Explorer 3 (WebUI, Accessibility & Test Harness Auditor)  
**Date**: 2026-10-04  
**Handoff Type**: Hard (Task Complete)  
**Survey Report Reference**: `c:\Users\mibu0\Documents\develop\SearXNGforWindowsNext\.agents\teamwork\explorer_survey_3\survey_report.md`

---

## 1. Observation

1. **Web Application & UI Delivery**:
   - `tools/webui_next.py`: 4,296 lines total.
   - Routing hook: `register_next_webui(app, webapp_mod)` hooked via `tools/apply-patches.py:2179` into `python/Lib/site-packages/searx/webapp.py:643`.
   - Browser interception: `tools/webui_next.py:3990–4014` (`sxng_ui_unification_guard` before_request hook) serves `AI_WORKSPACE_HTML` for `/` and redirects `/search`, `/preferences`, and `/about` to `/?...` when HTML is requested.
   - Dedicated SPA markup: `tools/webui_next.py:1424–3977` contains `AI_WORKSPACE_HTML` with 4 tabs (`deep`, `classic`, `agent`, `settings`).
   - Progressive enhancement assets: `tools/webui_next.py:881–1098` (`SIMPLE_EMBED_CSS`) and `1099–1423` (`SIMPLE_EMBED_JS`) injected into `templates/simple/base.html` via `tools/apply-patches.py:2221–2226`.

2. **Accessibility Observations in WebUI**:
   - `tools/webui_next.py:2628, 2642, 2656, 2672`: The General Settings section contains:
     ```html
     <div class="settings-row">
       <div class="settings-label-wrap">
         <h4>デフォルト検索モード</h4>
         <p>検索トップ画面にアクセスした際、または外部から検索時の初期モード</p>
       </div>
       <div>
         <select id="pref-default-mode" class="opt-select" style="min-width:14rem;">
     ```
     `<select id="pref-default-mode">`, `<select id="pref-safesearch">`, `<select id="pref-default-count">`, and `<select id="pref-default-tokens">` lack associated `<label for="...">` or `aria-labelledby`/`aria-label` tags.
   - `tools/webui_next.py:2352`: `<body>` opens directly into `<header class="topbar">` with no skip-to-content anchor link.
   - `tools/webui_next.py:2363–2366, 2534–2537, 2597–2598`: All tab elements have default `tabindex="0"`, omitting roving `tabindex="-1"` on inactive tabs.
   - `tools/webui_next.py:3289–3307`: In `renderClassicSearchResults()`, `scrapeBtn` toggles `.inline-scrape-drawer` without setting `aria-expanded` or `aria-controls`.
   - `tools/webui_next.py:2448–2455, 3627–3650`: `.cat-btn` filter chips toggle class `.active` without `aria-pressed="true/false"`.
   - `tools/webui_next.py:3885`: `executeCurrentAction()` executes `if (!qVal) return;`, yielding silent submission failure with no error alert when `#q` is empty.
   - `tools/webui_next.py:1468`: Light theme sets `--amber: #d97706;` which exhibits a ~3.5:1 contrast against white `#ffffff` (below WCAG AA 4.5:1).
   - `tools/webui_next.py:2152`: `.engines-grid` specifies `grid-template-columns: repeat(auto-fill, minmax(310px, 1fr));`, overflowing viewports narrower than ~339px (e.g. 320px with padding).

3. **Test Infrastructure & Baseline Execution Observations**:
   - `tools/run-tests.ps1:110–121`:
     ```powershell
     $ruffCmd = Get-Command "ruff" -ErrorAction SilentlyContinue
     if ($ruffCmd) { ... }
     ```
     Ruff is bypassed without failure or warning if not in global `PATH`.
   - `tools/smoke-test.ps1`: Contains 40 smoke tests covering root, JSON, json_lite, scrape, 21 SSRF attacks, CLI, and /ai. Does not execute an integration test for `/api/settings/engines`.
   - `python\python.exe -m pyrefly check` executed with exit code 0:
     `INFO 0 errors (1 suppressed)`. Suppression confirmed at `tools/disable-missing-engines.py:8: import yaml # type: ignore[untyped-import]`.
   - `ruff check .` executed with exit code 0: `All checks passed!`.
   - `ruff format --check .` executed with exit code 0: `46 files already formatted`.
   - `python tools/test_patches.py` passed 161 tests in 1.140s.
   - `python tools/test_agent_tools.py` passed 57 tests in 0.353s.
   - `python tools/test_agentic_search.py` passed 41 tests in 0.830s.
   - `python tools/test_retrieval_pipeline.py` passed 44 tests in 0.020s.
   - `python tests/evaluation/run_benchmark.py` passed across `fast`, `balanced`, and `deep` modes (10 queries: 1.0000 P@5, 100% official sources, 0.0% failures).
   - `powershell -ExecutionPolicy Bypass -File tools/run-tests.ps1 -SkipInstall` passed all stages (Exit code: 0).

---

## 2. Logic Chain

1. **Step 1 (Form Input Accessibility)**:
   - *From Observation 2*: In `webui_next.py:2623–2679`, the General Settings dropdowns are preceded by `<h4>` headings in a sibling container.
   - *Reasoning*: Assistive technologies (screen readers) rely on `<label for="id">` or `aria-labelledby` to associate text with form controls (WCAG 1.3.1, 4.1.2). Without these attributes, screen reader users only hear "combobox unlabelled", preventing accessibility compliance.
   - *Inference*: Remediation requires adding explicit `<label for="...">` wrappers or `aria-labelledby` attributes to `pref-default-mode`, `pref-safesearch`, `pref-default-count`, and `pref-default-tokens`.

2. **Step 2 (Keyboard Usability & Roving Tabindex)**:
   - *From Observation 2*: `webui_next.py` implements keyboard Arrow key listeners on tablists (`nav-tabs`, `ctx-tabs`, `settings-subtabs`), but all tab buttons are rendered with default `tabindex="0"`.
   - *Reasoning*: The WAI-ARIA APG Tabs Pattern requires inactive tabs to have `tabindex="-1"` and the active tab to have `tabindex="0"`. Furthermore, without a skip link (WCAG 2.4.1), keyboard users must tab sequentially through the entire header before reaching input `#q`.
   - *Inference*: Remediation requires adding a visually hidden `.skip-link` and setting/updating `tabindex="-1"` on inactive tabs during tab selection.

3. **Step 3 (Collapsible Disclosure States)**:
   - *From Observation 2*: In `renderSearchResults` (deep mode), `scrapeBtn` sets `aria-expanded`, but in `renderClassicSearchResults` (classic mode), `scrapeBtn` toggles the drawer without setting `aria-expanded` or `aria-controls`.
   - *Reasoning*: WCAG 4.1.2 mandates that the expanded/collapsed state of interactive disclosure widgets must be programmatically determinable.
   - *Inference*: Both buttons must maintain synchronized `aria-expanded="false"|"true"` states.

4. **Step 4 (Test Harness Robustness)**:
   - *From Observation 3*: `tools/run-tests.ps1` checks for `ruff` via `Get-Command "ruff" -ErrorAction SilentlyContinue`. If ruff is not on PATH, the check is skipped without failing the test runner.
   - *Reasoning*: If Ruff is uninstalled or a developer runs the runner without activated environment variables, lint and formatting failures can be silently committed into source control.
   - *Inference*: The runner should look for `python\Scripts\ruff.exe` as a fallback, and emit an explicit warning or error if Ruff cannot be located.

5. **Step 5 (Smoke Test Completeness)**:
   - *From Observation 3*: `tools/smoke-test.ps1` runs 40 tests, but lacks an E2E test for `/api/settings/engines`.
   - *Reasoning*: While unit tests verify the endpoint using Flask's test client, live server regression testing ensures Granian WSGI headers, cookie parsing, and multi-process persistence work correctly.
   - *Inference*: An assertion testing `GET /api/settings/engines` and `POST /api/settings/engines` should be added to `smoke-test.ps1`.

---

## 3. Caveats

1. **Client-Side Browser Execution Environment**: No automated headless browser (such as Playwright, Selenium, or Puppeteer) is currently present in the repository dependencies. Client-side JavaScript syntax was verified via `node --check` and Python mock harnesses, but interactive in-browser DOM event loops have not been executed in an automated headless browser runner.
2. **Upstream SearXNG Engine Availability**: Live engine search results from external providers (e.g. Google, Brave, Mojeek) may be rate-limited or return 403/429 during live tests (as logged in `smoke-test.ps1`), which is normal SearXNG behavior and handled via fallback and suspension logic.
3. **No Code Implementation in Explorer Milestone**: As an explorer subagent, all remediation measures are documented and specified as actionable proposals; no source code files outside `.agents/teamwork/explorer_survey_3/` were modified.

---

## 4. Conclusion

1. **WebUI Quality Assessment**: The Unified AI WebUI (`tools/webui_next.py`) is well-structured, fast, zero-dependency, and securely sandboxed (SSRF-hardened with DNS pinning, URL normalization, and XSS escaping).
2. **Defect Catalog**: 8 accessibility/usability defects (**A11Y-01** through **A11Y-08**) and 4 test infrastructure gaps (**TEST-01** through **TEST-04**) were identified and cataloged with exact file locations, line numbers, and concrete remediation snippets.
3. **Actionable Remediation Scope**:
   - Update `tools/webui_next.py` to add `<label for="...">` to settings controls, add `.skip-link`, implement roving `tabindex`, add `aria-expanded` to classic scrape buttons, add `aria-pressed` to category chips, provide feedback on empty queries, darken light-theme `--amber` to `#b45309`, and reflow `.engines-grid` for 320px screens.
   - Update `tools/smoke-test.ps1` to test `/api/settings/engines` and WebUI accessibility markers.
   - Update `tools/run-tests.ps1` to check `python\Scripts\ruff.exe` fallback.
   - Add unit regression tests in `tools/test_patches.py` ensuring accessibility attributes cannot regress.

---

## 5. Verification Method

To independently reproduce and verify all findings:

### 1. Static Quality & Type Checking
```powershell
# Run from repository root:
.\python\python.exe -m pyrefly check
ruff check .
ruff format --check .
```
*Expected*: Exit code 0, 0 errors in Pyrefly (1 suppressed in disable-missing-engines.py), all 46 files formatted.

### 2. Unit & Benchmark Test Execution
```powershell
.\python\python.exe tools/test_patches.py
.\python\python.exe tools/test_agent_tools.py
.\python\python.exe tools/test_agentic_search.py
.\python\python.exe tools/test_retrieval_pipeline.py
.\python\python.exe tests/evaluation/run_benchmark.py
```
*Expected*: All 303 unit tests pass, benchmark reports 1.0000 P@5 across fast/balanced/deep.

### 3. Full E2E Test Runner Lifecycle
```powershell
powershell -ExecutionPolicy Bypass -File tools/run-tests.ps1 -SkipInstall
```
*Expected*: Passes stages 1 through 6, executes 40 smoke tests, shuts down Granian cleanly with exit code 0.

### 4. Accessibility Code Inspection
Inspect the reported lines in `tools/webui_next.py`:
- Form labels: lines 2623–2679
- Skip link: line 2352
- Classic scrape button: lines 3289–3307
- Amber color: line 1468
- Engine grid minmax: line 2152
- Ruff runner check: `tools/run-tests.ps1` lines 110–121

### Invalidation Conditions
If a future commit adds `<label for="pref-default-mode">`, roving tabindex, or fixes the light theme amber contrast, the corresponding accessibility finding in this report will be marked resolved.
