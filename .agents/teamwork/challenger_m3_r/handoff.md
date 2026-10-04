# Milestone 3 Adversarial Verification Report (M3-R)

**Agent**: Challenger M3-R (Empirical Stress & Adversarial Verifier)  
**Date**: 2026-10-04  
**Working Directory**: `c:\Users\mibu0\Documents\develop\SearXNGforWindowsNext\.agents\teamwork\challenger_m3_r\`  
**Target Code**: `tools/webui_next.py`, `tools/run-tests.ps1`, `tools/smoke-test.ps1`, `tools/test_webui.py`  
**Verdict**: **APPROVE**

---

## 1. Observation

Direct empirical observations obtained by independent inspection, test execution, and mathematical verification:

### 1.1 DOM Accessibility & Form Control Labels (F3.1, F3.2, F3.3, F3.4, F3.5)
- **Settings Selects & Labels (`tools/webui_next.py:2642-2696`)**:
  - `pref-default-mode`: `<label for="pref-default-mode"><h4>デフォルト検索モード</h4></label>` matches `<select id="pref-default-mode" ... aria-label="デフォルト検索モード">`.
  - `pref-safesearch`: `<label for="pref-safesearch"><h4>セーフサーチ (SafeSearch)</h4></label>` matches `<select id="pref-safesearch" ... aria-label="セーフサーチ (SafeSearch)">`.
  - `pref-default-count`: `<label for="pref-default-count"><h4>デフォルト取得件数</h4></label>` matches `<select id="pref-default-count" ... aria-label="デフォルト取得件数">`.
  - `pref-default-tokens`: `<label for="pref-default-tokens"><h4>トークン予算上限</h4></label>` matches `<select id="pref-default-tokens" ... aria-label="トークン予算上限">`.
  - DOM inspection confirmed zero duplicate element IDs in `webui_next.AI_WORKSPACE_HTML`.
- **Skip-to-Content Link (`tools/webui_next.py:2370, 1486-1502`)**:
  - Element: `<a href="#q" class="skip-link">検索入力へスキップ</a>` is the first interactive child immediately after `<body>`.
  - Default CSS: `.skip-link { position: absolute; top: -999px; left: 1rem; z-index: 1000; ... }` (offscreen).
  - Focus CSS: `.skip-link:focus { top: 1rem; outline: 2px solid var(--accent); outline-offset: 2px; }` (onscreen with distinct focus outline).
  - Target: `<input id="q" name="q" ...>` exists and is focusable.
- **WAI-ARIA APG Roving Tabindex (`tools/webui_next.py:2380-2385, 2551-2556, 2614-2617, 2865-2870, 2901-2914, 2974-2995, 3707-3748`)**:
  - Initial HTML state across `.nav-tabs`, `.context-tabs`, and `.settings-subtabs` enforces exactly one tab with `tabindex="0"` and `aria-selected="true"`; all inactive tabs have `tabindex="-1"` and `aria-selected="false"`.
  - JavaScript handlers (`setMode`, `selectCtxTab`, `selectSettingsSubtab`) synchronize `tabindex` and `aria-selected` dynamically.
  - Arrow key navigation (`ArrowRight`, `ArrowLeft`, `ArrowDown`, `ArrowUp`) with boundary wrap-around is registered on all three tablists.
- **Scrape Drawer & Category Chips (`tools/webui_next.py:2466-2474, 3317-3330`)**:
  - Classic mode scrape drawer button initializes `aria-expanded="false"` and `aria-controls` pointing to drawer ID. Toggling dynamically updates `aria-expanded` to `'true'` or `'false'`.
  - Category buttons have explicit `aria-pressed="true"` for active and `aria-pressed="false"` for inactive chips.

### 1.2 Mathematical WCAG 2.1 AA Contrast Ratio Oracle (F3.7)
- Variable in `tools/webui_next.py:1468`: `--amber: #b45309;`.
- Linearized sRGB Luminance Formula:
  $$\text{lin}(c) = \begin{cases} c / 12.92 & c \le 0.04045 \\ ((c + 0.055) / 1.055)^{2.4} & c > 0.04045 \end{cases}$$
  $$L = 0.2126 \cdot \text{lin}(R) + 0.7152 \cdot \text{lin}(G) + 0.0722 \cdot \text{lin}(B)$$
- Calculation for `#b45309`:
  - $R = 180 / 255 \approx 0.70588 \implies \text{lin}(R) \approx 0.45785$
  - $G = 83 / 255 \approx 0.32549 \implies \text{lin}(G) \approx 0.08643$
  - $B = 9 / 255 \approx 0.03529 \implies \text{lin}(B) \approx 0.00273$
  - $L_{\text{amber}} = 0.2126(0.45785) + 0.7152(0.08643) + 0.0722(0.00273) = 0.15933$
- Contrast Ratio against White (`#ffffff`, $L = 1.0$):
  $$\text{CR} = \frac{1.0 + 0.05}{0.15933 + 0.05} = \frac{1.05}{0.20933} \approx 5.016:1 \ge 4.5:1 \quad (\text{PASS})$$
- Contrast against `--bg-base` (`#f8fafc`, $L = 0.9576$): $4.81:1 \ge 4.5:1$ ($\text{PASS}$).
- Contrast of legacy `#d97706` against `#ffffff` was $3.19:1 < 4.5:1$ ($\text{FAIL}$).

### 1.3 320px Viewport Responsive CSS Grid Reflow (F3.8)
- Rule in `tools/webui_next.py:2169`:
  `grid-template-columns: repeat(auto-fill, minmax(min(100%, 280px), 1fr));`
- 1px sweep simulation across container widths $[100\text{px} \dots 400\text{px}]$ confirmed 0px horizontal overflow.
- At 320px screen width with 16px lateral padding (288px container width):
  - Track minimum: $\min(288\text{px}, 280\text{px}) = 280\text{px} \le 288\text{px}$.
  - Result: 1 column, 288px width, 0px overflow.
  - Legacy rule `minmax(310px, 1fr)` caused 22px horizontal overflow ($310\text{px} - 288\text{px} = 22\text{px}$).

### 1.4 Backend POST Parameter Retention & Scraper Hardening (F3.9, F2.9)
- `unified_search_view()` in `tools/webui_next.py:4075-4085`:
  - `params = dict(request.values)` captures both GET query arguments and POST form payloads.
  - 302 redirection preserves multi-byte UTF-8 Japanese characters (`機械学習 & 深層学習 比較`), URL-special characters, exact quotes, and emoji in `Location: /?...`.
  - Requests specifying `format=json`, `format=json_lite`, `format=csv`, `format=rss`, or header `Accept: application/json` delegate directly to `orig_search()` returning HTTP 200.
- Scraper Keepalive in `tools/webui_next.py:241`:
  - `scrape_limits = httpx_mod.Limits(max_keepalive_connections=0, max_connections=50)` strictly disables connection pooling.

### 1.5 Execution Results of Test Harnesses
- `.\python\python.exe tools/test_webui.py`:
  `Ran 21 tests in 0.021s -- OK`
- `.\python\python.exe tools/test_patches.py`:
  `Ran 180 tests in 1.567s -- OK`
- `.\python\python.exe tools/test_agent_tools.py`:
  `Ran 60 tests in 0.030s -- OK`
- `.\python\python.exe tools/test_retrieval_pipeline.py`:
  `Ran 52 tests in 0.024s -- OK`
- `.\python\python.exe tools/test_agentic_search.py`:
  `Ran 41 tests in 0.824s -- OK`
- `.\python\python.exe tests/evaluation/run_benchmark.py`:
  `100% official source, 1.0000 P@5, 0.9766 nDCG@10 across all modes -- OK`
- `.\python\python.exe -m ruff check tools/`:
  `All checks passed!`
- `.\python\python.exe -m ruff format --check tools/`:
  `23 files already formatted`
- `.\python\python.exe -m pyrefly check tools/webui_next.py tools/test_webui.py`:
  `INFO 0 errors`
- `.\python\python.exe tests/test_challenger_m3_1_adversarial.py`:
  `Ran 23 tests in 0.022s -- OK`
- `.\python\python.exe tests/test_challenger_m3_r_adversarial.py`:
  `Ran 15 tests in 0.018s -- OK`
- Live WSGI server (Granian) + `tools/smoke-test.ps1`:
  `Test 41: /api/settings/engines returned 21 engines (15 active) -- [OK] All smoke tests PASSED`

---

## 2. Logic Chain

1. **Accessibility Compliance (Observations 1.1, 1.2, 1.3)**:
   - WCAG 1.3.1 (Info and Relationships) and 4.1.2 (Name, Role, Value) require form controls to have programmatic labels and unique IDs. The 4 settings selects have matching `<label for="...">` and explicit `aria-label` tags with unique element IDs throughout the DOM.
   - WCAG 2.4.1 (Bypass Blocks) mandates a mechanism to skip repetitive navigation. The `<a href="#q" class="skip-link">` anchor is the initial interactive child of `<body>` and shifts on-screen with an accessible focus outline when focused.
   - WAI-ARIA APG roving tabindex requires a single tab stop per tablist with Arrow key navigation. Verification confirmed exact initial `tabindex="0"` on the active tab and `-1` on all inactive tabs, with bidirectional wrap-around Arrow key handlers.
   - WCAG 1.4.3 (Contrast Minimum) requires a 4.5:1 ratio for standard text. Mathematical luminance calculation proves `#b45309` achieves 5.02:1 against pure white and 4.81:1 against base backgrounds, resolving the defect in legacy `#d97706` (3.19:1).
   - Responsive design mandates no horizontal scrolling on 320px viewports (WCAG 1.4.10 Reflow). The dynamic track rule `minmax(min(100%, 280px), 1fr)` guarantees single-column adaptation on screens $\le 320\text{px}$ even with padding.

2. **Route and Security Invariants (Observation 1.4)**:
   - The contract between `tools/webui_next.py` and `searx/webapp.py` requires retaining form parameters when users submit via standard POST forms. Using `dict(request.values)` captures POST form payloads and passes them to the 302 redirection query string, preserving Japanese, punctuation, and query parameters.
   - Scraper keepalive connection pooling allowed potential host hijack/bypass in subsequent requests. Setting `max_keepalive_connections=0` ensures immediate connection teardown and fresh SSRF evaluation per request.

3. **Empirical Quality & Regression Verification (Observation 1.5)**:
   - All 21 unit tests in `tools/test_webui.py`, 180 unit tests in `tools/test_patches.py`, and 153 tests across adjacent pipelines execute cleanly with zero errors.
   - Both adversarial challenge suites (`test_challenger_m3_1_adversarial.py` and `test_challenger_m3_r_adversarial.py`) pass 100%.
   - Live Granian server smoke tests execute all 41 test scenarios to completion with zero failures.

---

## 3. Caveats

- **Scope Boundary**: Verification was conducted strictly via non-invasive testing, automated inspection, and adversarial test harnesses. No production code in `tools/webui_next.py` or `searx/webapp.py` was altered.
- **Screen Reader Software**: Accessibility was validated through rigorous DOM/AST parsing, WAI-ARIA APG structural compliance, and browser layout simulation rather than physical assistive audio device software (e.g., NVDA, JAWS).

---

## 4. Conclusion

All 12 items belonging to Milestone 3 (Unified AI WebUI & Accessibility Compliance) meet or exceed the architectural, accessibility, and functional requirements defined in `PROJECT.md` and `ORIGINAL_REQUEST.md`. Zero regressions exist in adjacent subsystems.

Explicit Milestone 3 Verdict: **APPROVE**.

---

## 5. Verification Method

To independently reproduce and verify this verdict:

1. **Milestone 3 Unit Regression Suite**:
   ```powershell
   .\python\python.exe tools\test_webui.py
   ```
   *Expected result*: 21 tests pass with `OK`.

2. **Challenger Adversarial Stress Suites**:
   ```powershell
   .\python\python.exe tests\test_challenger_m3_1_adversarial.py
   .\python\python.exe tests\test_challenger_m3_r_adversarial.py
   ```
   *Expected result*: 38 tests pass with `OK`.

3. **Core Subsystem Suites & Benchmark**:
   ```powershell
   .\python\python.exe tools\test_patches.py
   .\python\python.exe tools\test_agent_tools.py
   .\python\python.exe tools\test_retrieval_pipeline.py
   .\python\python.exe tools\test_agentic_search.py
   .\python\python.exe tests\evaluation\run_benchmark.py
   ```
   *Expected result*: 100% tests pass.

4. **Static Code Quality Checks**:
   ```powershell
   .\python\python.exe -m ruff check tools/ tests/
   .\python\python.exe -m ruff format --check tools/ tests/test_challenger_m3_r_adversarial.py
   .\python\python.exe -m pyrefly check tools/webui_next.py tools/test_webui.py tests/test_challenger_m3_r_adversarial.py
   ```
   *Expected result*: 0 errors, all files formatted.

5. **Live Granian Server Smoke Test**:
   ```powershell
   pwsh -ExecutionPolicy Bypass -Command {
       $repoRoot = (Get-Location).Path
       $secretLine = & ".\python\python.exe" "tools\ensure-secret-key.py"
       if ($secretLine -match '^set SEARXNG_SECRET=(.+)$') { $env:SEARXNG_SECRET = $Matches[1] }
       $env:SEARXNG_SETTINGS_PATH = "$repoRoot\config\settings.yml"
       $serverProcess = Start-Process -FilePath ".\python\python.exe" -ArgumentList "-m granian --interface wsgi searx.webapp:application --host 127.0.0.1 --port 8888 --blocking-threads 4 --no-ws" -PassThru -NoNewWindow
       try {
           Start-Sleep -Seconds 4
           & "powershell" "-ExecutionPolicy" "Bypass" "-File" "tools\smoke-test.ps1"
       }
       finally {
           if ($serverProcess) { Stop-Process -Id $serverProcess.Id -Force -ErrorAction SilentlyContinue }
           Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*granian*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
       }
   }
   ```
   *Expected result*: All 41 tests pass with `[OK] All smoke tests PASSED`.
