# Dispatch: Worker M3 (Unified AI WebUI & Accessibility Compliance)

## Working Directory
`c:\Users\mibu0\Documents\develop\SearXNGforWindowsNext\.agents\teamwork\worker_m3\`

## Authoritative Context Documents
1. `ORIGINAL_REQUEST.md`: `c:\Users\mibu0\Documents\develop\SearXNGforWindowsNext\.agents\teamwork\ORIGINAL_REQUEST.md`
2. `PROJECT.md`: `c:\Users\mibu0\Documents\develop\SearXNGforWindowsNext\.agents\teamwork\orchestrator\PROJECT.md`
3. Explorer 3 Survey Report: `c:\Users\mibu0\Documents\develop\SearXNGforWindowsNext\.agents\teamwork\explorer_survey_3\survey_report.md`

## MANDATORY INTEGRITY WARNING
DO NOT CHEAT. All implementations must be genuine. DO NOT hardcode test results, create dummy/facade implementations, or circumvent the intended task. A teamwork_preview_auditor will independently verify your work. Integrity violations WILL be detected and your work WILL be rejected.

## Write Ownership Boundaries
You have EXCLUSIVE write ownership to:
- `tools/webui_next.py`
- `tools/run-tests.ps1`
- `tools/smoke-test.ps1`
- `tools/test_webui.py` (dedicated regression test suite for WebUI)

Do NOT touch any other source files.

## Assigned Technical Tasks

### 1. `tools/webui_next.py`: Accessibility & Responsiveness Remediations
- **F3.1 Settings Form Controls Labeling**:
  In lines 2623–2679, add explicit `<label for="...">` or `aria-label` / `aria-labelledby` to settings select controls:
  - `pref-default-mode`
  - `pref-safesearch`
  - `pref-default-count`
  - `pref-default-tokens`
- **F3.2 Skip-to-Content Link**:
  Immediately inside `<body>` (around line 2352), add:
  ```html
  <a href="#q" class="skip-link">検索入力へスキップ</a>
  ```
  Add `.skip-link` CSS styling (accessible, positioned offscreen, visible when focused).
- **F3.3 Tablist Roving Tabindex**:
  In tablists (`.nav-tabs`, `.ctx-tab`, `.settings-subtab`), initialize inactive tabs with `tabindex="-1"` and active tab with `tabindex="0"`. Update `tabindex` dynamically in tab switching functions (`setMode`, `selectCtxTab`, `selectSettingsSubtab`).
- **F3.4 Classic Mode Scrape Drawer ARIA Attributes**:
  In `renderClassicSearchResults()` (lines ~3289-3307), set `scrapeBtn.setAttribute('aria-expanded', 'false')` and `scrapeBtn.setAttribute('aria-controls', ...)` and toggle `aria-expanded` between `'true'` and `'false'` on click.
- **F3.5 Category Chips ARIA Pressed**:
  In category filter chips (`.cat-btn`), set `aria-pressed="true"` on the active chip and `aria-pressed="false"` on inactive chips, updating dynamically upon click.
- **F3.6 Empty Query User Notice**:
  In `executeCurrentAction()` (line ~3885), if query is empty, show user feedback:
  ```javascript
  if (!qVal) {
    showToast('検索キーワードまたはURLを入力してください');
    document.getElementById('q').focus();
    return;
  }
  ```
- **F3.7 Amber Contrast Ratio**:
  In `[data-theme="light"]` (line ~1468), darken `--amber` to `#b45309` (yielding >= 4.5:1 contrast against white).
- **F3.8 Responsive 320px Grid Reflow**:
  In `.engines-grid` (line ~2152), update column rule to:
  ```css
  grid-template-columns: repeat(auto-fill, minmax(min(100%, 280px), 1fr));
  ```
- **F3.9 Form POST Parameter Retention**:
  In `unified_search_view()` (line ~4031), retain POST parameters by merging `request.values` or `request.form` into `params`:
  ```python
  params = dict(request.values)
  # Remove sensitive or internal keys if any, keep q, category, etc.
  qs = urllib.parse.urlencode(params)
  return redirect(f"/?{qs}" if qs else "/", code=302)
  ```
- **Scraper Keepalive Hardening**:
  In line 241, update:
  ```python
  scrape_limits = httpx_mod.Limits(max_keepalive_connections=0, max_connections=50)
  ```

### 2. `tools/run-tests.ps1`: Ruff Executable Fallback (F3.10)
- In `tools/run-tests.ps1:110-121`:
  Add check for `$repoRoot\python\Scripts\ruff.exe` as fallback if `ruff` is not found on PATH. If neither is available, emit clear error / warning.

### 3. `tools/smoke-test.ps1`: Engine Settings Live Assertion (F3.11)
- Add live smoke test verifying that `GET /api/settings/engines` returns HTTP 200 with JSON payload containing `total_engines > 0` and `active_engines > 0`.

### 4. `tools/test_webui.py`: Comprehensive Unit & Regression Tests (F3.12)
- Create `tools/test_webui.py` testing:
  - Settings selects have `id` and corresponding `<label for="...">` or `aria-label`.
  - Skip link element exists and points to `#q`.
  - Tablists have `role="tablist"` and initial `tabindex` attributes.
  - Light theme `--amber` is `#b45309`.
  - 320px grid CSS uses `minmax(min(100%, 280px), 1fr)`.
  - `unified_search_view` retains POST form parameters (`q=test`) on 302 redirect.
  - In-process scraper limits specify `max_keepalive_connections=0`.
  - Empty query check invokes `showToast`.

### 5. Verification Requirements
- `python\python.exe -m ruff check tools/webui_next.py tools/test_webui.py`
- `python\python.exe -m ruff format --check tools/webui_next.py tools/test_webui.py`
- `python\python.exe -m pyrefly check`
- `python\python.exe tools/test_webui.py` (all tests pass)
- Run unit test suites: `test_patches.py`, `test_agent_tools.py`, `test_retrieval_pipeline.py`.

## Completion Criteria
1. All 12 items implemented cleanly.
2. All unit tests pass.
3. Update `progress.md` with `Last visited: [timestamp]` header.
4. Produce `handoff.md` with verification outputs and git diff summary.
5. Send a message to orchestrator upon completion.


## 2026-10-04T05:33:20Z
Received dispatch from parent (2da8fdd6-dc63-4790-a432-5c307d090996). Initiating Milestone 3 implementation.
