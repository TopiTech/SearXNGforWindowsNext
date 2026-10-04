# Dispatch: Challenger M3-2 (POST Redirect & Live Harness Challenger)

## Working Directory
`c:\Users\mibu0\Documents\develop\SearXNGforWindowsNext\.agents\teamwork\challenger_m3_2\`

## Context Files
- Original Request: `c:\Users\mibu0\Documents\develop\SearXNGforWindowsNext\.agents\teamwork\ORIGINAL_REQUEST.md`
- Project Scope: `c:\Users\mibu0\Documents\develop\SearXNGforWindowsNext\.agents\teamwork\orchestrator\PROJECT.md`
- Worker M3 Handoff: `c:\Users\mibu0\Documents\develop\SearXNGforWindowsNext\.agents\teamwork\worker_m3\handoff.md`

## Mission
Adversarially verify route handling and test runner integration:
1. Test `unified_search_view()` POST redirection:
   - Send HTTP POST requests with form body (e.g. `q=python+security`, `category=it`) without format parameter.
   - Verify 302 redirect URL preserves query parameters: `/?q=python+security&category=it`.
   - Verify format requests (`format=json`, `format=json_lite`) are NOT redirected.
2. Verify scraper keepalive settings in `tools/webui_next.py`:
   - Verify `max_keepalive_connections=0` in `_scrape_client` limits.
3. Verify `tools/run-tests.ps1` Ruff detection:
   - Verify logic properly checks both system PATH and `python\Scripts\ruff.exe`.
4. Run unit and smoke tests.
5. Issue an explicit verdict: **APPROVE** or **REJECT**.
6. Maintain `progress.md` with `Last visited: [timestamp]` header. Write `handoff.md` and notify orchestrator.


## 2026-10-04T05:48:38Z
You are Challenger M3-2 (POST Redirect & Live Harness Challenger).
Your working directory is: c:\Users\mibu0\Documents\develop\SearXNGforWindowsNext\.agents\teamwork\challenger_m3_2\
Original Request: c:\Users\mibu0\Documents\develop\SearXNGforWindowsNext\.agents\teamwork\ORIGINAL_REQUEST.md
Project Scope: c:\Users\mibu0\Documents\develop\SearXNGforWindowsNext\.agents\teamwork\orchestrator\PROJECT.md
Worker M3 Handoff: c:\Users\mibu0\Documents\develop\SearXNGforWindowsNext\.agents\teamwork\worker_m3\handoff.md
Please read your dispatch instructions at: c:\Users\mibu0\Documents\develop\SearXNGforWindowsNext\.agents\teamwork\challenger_m3_2\DISPATCH.md

Adversarially test POST form parameter retention in unified_search_view() 302 redirect, scraper keepalive setting, and tools/run-tests.ps1 fallback. Issue an explicit verdict in handoff.md: APPROVE or REJECT. Send message to orchestrator upon completion.
