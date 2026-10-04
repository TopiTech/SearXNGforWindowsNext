# BRIEFING — 2026-10-04T00:03:00Z

## Mission
Conduct an exhaustive survey and investigation of query pipelines, backend APIs, webapp endpoints, security vulnerabilities, correctness, concurrency, and tests.

## 🔒 My Identity
- Archetype: explorer
- Roles: codebase investigation, query pipeline audit, backend API audit, security audit
- Working directory: c:\Users\mibu0\Documents\develop\SearXNGforWindowsNext\.agents\teamwork\explorer_survey_1\
- Original parent: 2da8fdd6-dc63-4790-a432-5c307d090996
- Milestone: survey & investigation (Phase 1)

## 🔒 Key Constraints
- Read-only investigation — do NOT implement code changes in the project source tree
- Write only to my folder: c:\Users\mibu0\Documents\develop\SearXNGforWindowsNext\.agents\teamwork\explorer_survey_1\
- Produce survey_report.md and handoff.md
- Message parent agent upon completion

## Current Parent
- Conversation ID: 2da8fdd6-dc63-4790-a432-5c307d090996
- Updated: 2026-10-04T00:03:00Z

## Investigation State
- **Explored paths**:
  - `tools/query_pipeline.py` (audited normalization, intent classification, expansion, ReDoS)
  - `tools/retrieval_service.py` & `retrieval_models.py` (audited pipeline, concurrency, schema)
  - `tools/agentic_search.py` (audited speculative fetcher, token budgeting, unified search)
  - `tools/url_normalizer.py`, `passage_chunker.py`, `rank_fusion.py`, `lexical_rerank.py`
  - `searx/webapp.py` & `tools/webui_next.py` (endpoints, routing, SSRF, backward compatibility)
  - `tools/test_patches.py`, `test_agent_tools.py`, `test_agentic_search.py`, `test_retrieval_pipeline.py`
  - `tests/evaluation/run_benchmark.py`, `tools/run-tests.ps1`, `smoke-test.ps1`
- **Key findings**:
  1. High Severity ReDoS vulnerability discovered in `query_pipeline.py` line 126 (`COMPARISON_PATTERNS`).
  2. Unbounded query length in `query_pipeline.py:parse_and_normalize`.
  3. Stripping double quotes in `query_pipeline.py:clean_no_quotes` degrades exact-phrase search.
  4. POST form parameters dropped during redirect in `webui_next.py:unified_search_view`.
  5. Hardcoded freshness year range (2024–2029) in `query_pipeline.py`.
  6. SSRF protections in `webapp.py` and `url_normalizer.py` are robust (DNS pinning, extensive IP blocking).
  7. Secret key and credentials handling is safe (atomic generation into gitignored file).
  8. All 4 unit test suites, benchmark, and linter/type checks currently pass cleanly.
- **Unexplored areas**: None within scope. Ready for final reports.

## Key Decisions Made
- Confirmed ReDoS via independent benchmarking.
- Documenting all issues by severity (High, Medium, Low) with concrete remediation proposals.

## Artifact Index
- `DISPATCH.md` — Inbound instructions
- `BRIEFING.md` — Situational awareness
- `progress.md` — Liveness heartbeat and status
- `survey_report.md` — Comprehensive survey report (generating)
- `handoff.md` — 5-component handoff report (generating)
