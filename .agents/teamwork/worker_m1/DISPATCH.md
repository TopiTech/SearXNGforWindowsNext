# Dispatch: Worker M1 (Backend Query Pipeline & Search Remediation)

**Working Directory**: `c:\Users\mibu0\Documents\develop\SearXNGforWindowsNext\.agents\teamwork\worker_m1\`
**Original Request**: `c:\Users\mibu0\Documents\develop\SearXNGforWindowsNext\.agents\teamwork\ORIGINAL_REQUEST.md`
**Project Scope**: `c:\Users\mibu0\Documents\develop\SearXNGforWindowsNext\.agents\teamwork\orchestrator\PROJECT.md`
**Explorer Findings**: `c:\Users\mibu0\Documents\develop\SearXNGforWindowsNext\.agents\teamwork\explorer_survey_1\survey_report.md` and `c:\Users\mibu0\Documents\develop\SearXNGforWindowsNext\.agents\teamwork\explorer_survey_1\handoff.md`

## Mandatory Integrity Warning
DO NOT CHEAT. All implementations must be genuine. DO NOT hardcode test results, create dummy/facade implementations, or circumvent the intended task. A teamwork_preview_auditor will independently verify your work. Integrity violations WILL be detected and your work WILL be rejected.

## Write Ownership Boundaries
You have EXCLUSIVE write ownership to:
- `tools/query_pipeline.py`
- `tools/retrieval_service.py`
- `tools/test_retrieval_pipeline.py`
- `tools/test_agent_tools.py`
Do NOT write to any other source files.

## Assigned Features & Tasks (Milestone 1)
1. **F1.1 ReDoS Remediation (`tools/query_pipeline.py:126`)**:
   - Fix catastrophic backtracking in `COMPARISON_PATTERNS` (`([^\s]+)\s*(と|VS|対)\s*([^\s]+)\s*(比較|違い|どっち)`).
   - Implement keyword pre-filters and bounded character ranges (e.g. `[^\s]{1,50}`) so regex execution completes in $< 5\text{ms}$ even on 20,000+ non-matching character strings.
2. **F1.2 Query Length Bound (`tools/query_pipeline.py`)**:
   - In `QueryProcessor.parse_and_normalize(raw_query)`, enforce a maximum query length limit of 2,000 characters to prevent resource exhaustion attacks.
3. **F1.3 Exact-Phrase Quote Retention**:
   - In `tools/query_pipeline.py`, ensure surrounding double quotes for exact-phrase queries (e.g. `"FastAPI lifespan"`) are preserved in `ProcessedQuery.clean_text`.
   - In `tools/retrieval_service.py`, ensure quotes are retained when dispatching queries to search engines.
4. **F1.4 Dedicated Regression Tests**:
   - Add unit tests in `tools/test_retrieval_pipeline.py` and/or `tools/test_agent_tools.py` testing:
     - ReDoS safety: Verify `COMPARISON_PATTERNS` search on 20,000-char string completes in $< 50\text{ms}$.
     - Query length bounds: Verify inputs $> 2,000$ characters are gracefully handled.
     - Quote retention: Verify quotes in `"query text"` are preserved in `clean_text`.
5. **Static Quality & Test Execution**:
   - Run `python\python.exe -m ruff check tools/query_pipeline.py tools/retrieval_service.py tools/test_retrieval_pipeline.py tools/test_agent_tools.py`
   - Run `python\python.exe -m ruff format --check tools/query_pipeline.py tools/retrieval_service.py tools/test_retrieval_pipeline.py tools/test_agent_tools.py`
   - Run `python\python.exe -m pyrefly check`
   - Run `python\python.exe tools/test_retrieval_pipeline.py`
   - Run `python\python.exe tools/test_agent_tools.py`
   - Run `python\python.exe tools/test_agentic_search.py`

## Instructions
1. Read `ORIGINAL_REQUEST.md`, `PROJECT.md`, and Explorer 1's survey report.
2. Maintain liveness in `progress.md` with `Last visited: [timestamp]`.
3. Implement clean, minimal, backward-compatible fixes.
4. Execute build/tests and document results in `handoff.md`.
5. Send message to orchestrator when completed.


## 2026-10-04T00:05:45Z
You are Worker M1 (Backend Query Pipeline & Search Remediation).
Your working directory is: c:\Users\mibu0\Documents\develop\SearXNGforWindowsNext\.agents\teamwork\worker_m1\
Original Request is located at: c:\Users\mibu0\Documents\develop\SearXNGforWindowsNext\.agents\teamwork\ORIGINAL_REQUEST.md
Project Scope is located at: c:\Users\mibu0\Documents\develop\SearXNGforWindowsNext\.agents\teamwork\orchestrator\PROJECT.md
Explorer 1 findings are at: c:\Users\mibu0\Documents\develop\SearXNGforWindowsNext\.agents\teamwork\explorer_survey_1\survey_report.md and c:\Users\mibu0\Documents\develop\SearXNGforWindowsNext\.agents\teamwork\explorer_survey_1\handoff.md
Please read your dispatch instructions at: c:\Users\mibu0\Documents\develop\SearXNGforWindowsNext\.agents\teamwork\worker_m1\DISPATCH.md
