# Dispatch: Worker M1 Iteration 2 (Japanese Comparison Regex & Orthography Remediation)

**Working Directory**: `c:\Users\mibu0\Documents\develop\SearXNGforWindowsNext\.agents\teamwork\worker_m1_it2\`
**Original Request**: `c:\Users\mibu0\Documents\develop\SearXNGforWindowsNext\.agents\teamwork\ORIGINAL_REQUEST.md`
**Project Scope**: `c:\Users\mibu0\Documents\develop\SearXNGforWindowsNext\.agents\teamwork\orchestrator\PROJECT.md`
**Gate Failure Report**: `c:\Users\mibu0\Documents\develop\SearXNGforWindowsNext\.agents\teamwork\orchestrator\GATE_STATUS.md`
**Explorer Findings**:
- Explorer 1 Report: `c:\Users\mibu0\Documents\develop\SearXNGforWindowsNext\.agents\teamwork\explorer_m1_it2_1\survey_report.md`
- Explorer 2 Report: `c:\Users\mibu0\Documents\develop\SearXNGforWindowsNext\.agents\teamwork\explorer_m1_it2_2\survey_report.md`
- Explorer 3 Report: `c:\Users\mibu0\Documents\develop\SearXNGforWindowsNext\.agents\teamwork\explorer_m1_it2_3\survey_report.md`

## Mandatory Integrity Warning
DO NOT CHEAT. All implementations must be genuine. DO NOT hardcode test results, create dummy/facade implementations, or circumvent the intended task. A teamwork_preview_auditor will independently verify your work. Integrity violations WILL be detected and your work WILL be rejected.

## Write Ownership Boundaries
You have EXCLUSIVE write ownership to:
- `tools/query_pipeline.py`
- `tools/retrieval_service.py`
- `tools/test_retrieval_pipeline.py`
- `tools/test_agent_tools.py`
Do NOT write to any other source files.

## Assigned Remediation Tasks
1. **Fix `COMPARISON_PATTERNS[1]` in `tools/query_pipeline.py:138`**:
   Replace possessive pattern with lazy bounded pattern:
   ```python
   re.compile(
       r"([^\sと対]{1,50}+)\s*(と|VS|vs|対)\s*([^\sと対]{1,50}?)\s*(?:の\s*(?:[^\sと対の比較違いどっちどちら]{1,10}\s*)?)?(比較|違い|どっち|どちら)",
       re.IGNORECASE,
   )
   ```
2. **Fix `COMPARISON_PATTERNS[0]` in `tools/query_pipeline.py:137`**:
   Enhance Pattern 0 to support bracketed entities, CJK tokens, and optional `.` in `vs.`:
   ```python
   re.compile(
       r"(?:^|\s|[^\w])['\"「『【]?([a-z0-9_+#.\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff-]{1,50}+)['\"」』】]?\s*(?:vs\.?|versus|compared\s+to)\s*['\"「『【]?([a-z0-9_+#.\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff-]{1,50}+)['\"」』】]?(?:\s|[^\w]|$)",
       re.IGNORECASE,
   )
   ```
3. **Add `"どちら"` to `COMPARISON_KEYWORDS` in `tools/query_pipeline.py:133`**.
4. **Strip quotation/bracket characters in `QueryProcessor.expand_query` (`tools/query_pipeline.py:373`)**:
   ```python
   item_a, item_b = m.group(1).strip(), m.group(3 if len(m.groups()) >= 3 else 2).strip()
   item_a = item_a.strip('"\'「」『』【】()[]')
   item_b = item_b.strip('"\'「」『』【】()[]')
   ```
5. **Add Comprehensive Regression Tests in `tools/test_retrieval_pipeline.py`**:
   Add test methods verifying:
   - Unspaced queries: `"PythonとRustの比較"`, `"VueとReactの違い"`, `"TypeScriptとJavaScriptどっち"`, `"iPhone対Android比較"`, `"FastAPIとDjangoの比較"`, `"Mac対Windowsどっち"`
   - Entities containing `の`: `"呪術廻戦と鬼滅の刃の比較"`, `"風の谷のナウシカと天空の城ラピュタの比較"`
   - Bracketed queries: `"「Python」と「Rust」の比較"`, `"「Vue」と「React」の違い"`, `"「Python」 vs 「Rust」"`, `"'Python' vs 'Rust'"`
   - Polite forms: `"MacとWindowsどちら"`
   - Verify intent is `"comparison"` and extracted terms in `expand_query` are clean entities.
6. **Execute Verification Commands**:
   - `python\python.exe -m ruff check tools/query_pipeline.py tools/retrieval_service.py tools/test_retrieval_pipeline.py tools/test_agent_tools.py`
   - `python\python.exe -m ruff format --check tools/query_pipeline.py tools/retrieval_service.py tools/test_retrieval_pipeline.py tools/test_agent_tools.py`
   - `python\python.exe -m pyrefly check`
   - `python\python.exe tools/test_retrieval_pipeline.py`
   - `python\python.exe tools/test_agent_tools.py`
   - `python\python.exe tools/test_agentic_search.py`
   - `python\python.exe tools/test_patches.py`
   - `python\python.exe tests/evaluation/run_benchmark.py`
   - ReDoS check: 20k non-matching chars must complete in $< 10\text{ms}$.
7. Document results in `handoff.md`. Maintain `progress.md` with `Last visited: [timestamp]`. Send message to orchestrator upon completion.


## 2026-10-04T00:41:59Z
[Message] timestamp=2026-10-04T00:41:59Z sender=2da8fdd6-dc63-4790-a432-5c307d090996 priority=MESSAGE_PRIORITY_HIGH content=You are Worker M1 Iteration 2 (Japanese Comparison Regex & Orthography Remediation).
Your working directory is: c:\Users\mibu0\Documents\develop\SearXNGforWindowsNext\.agents\teamwork\worker_m1_it2\
Original Request: c:\Users\mibu0\Documents\develop\SearXNGforWindowsNext\.agents\teamwork\ORIGINAL_REQUEST.md
Project Scope: c:\Users\mibu0\Documents\develop\SearXNGforWindowsNext\.agents\teamwork\orchestrator\PROJECT.md
Gate Failure Report: c:\Users\mibu0\Documents\develop\SearXNGforWindowsNext\.agents\teamwork\orchestrator\GATE_STATUS.md
Please read your dispatch instructions at: c:\Users\mibu0\Documents\develop\SearXNGforWindowsNext\.agents\teamwork\worker_m1_it2\DISPATCH.md

MANDATORY INTEGRITY WARNING:
DO NOT CHEAT. All implementations must be genuine. DO NOT hardcode test results, create dummy/facade implementations, or circumvent the intended task. A teamwork_preview_auditor will independently verify your work. Integrity violations WILL be detected and your work WILL be rejected.

Write Ownership Boundaries:
You have EXCLUSIVE write ownership to:
- tools/query_pipeline.py
- tools/retrieval_service.py
- tools/test_retrieval_pipeline.py
- tools/test_agent_tools.py
Do NOT touch any other source files.

Assigned Tasks:
1. Update COMPARISON_PATTERNS[1] in tools/query_pipeline.py:138 with lazy bounded group matching unspaced and aspect queries:
   re.compile(r"([^\sと対]{1,50}+)\s*(と|VS|vs|対)\s*([^\sと対]{1,50}?)\s*(?:の\s*(?:[^\sと対の比較違いどっちどちら]{1,10}\s*)?)?(比較|違い|どっち|どちら)", re.IGNORECASE)
2. Update COMPARISON_PATTERNS[0] in tools/query_pipeline.py:137 to support bracketed/quoted entities and CJK tokens:
   re.compile(r"(?:^|\s|[^\w])['\"「『【]?([a-z0-9_+#.\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff-]{1,50}+)['\"」』】]?\s*(?:vs\.?|versus|compared\s+to)\s*['\"「『【]?([a-z0-9_+#.\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff-]{1,50}+)['\"」』】]?(?:\s|[^\w]|$)", re.IGNORECASE)
3. Add "どちら" to COMPARISON_KEYWORDS in tools/query_pipeline.py:133.
4. Strip quotation/bracket characters in QueryProcessor.expand_query (tools/query_pipeline.py:373).
5. Add dedicated regression unit tests in tools/test_retrieval_pipeline.py covering unspaced Japanese queries, entity names containing particle "の" (e.g. 鬼滅の刃), bracketed entities, and polite forms.
6. Verify with ruff check, ruff format --check, pyrefly check, and unit test suites.
7. Write handoff.md with passing build/test outputs. Send message to orchestrator upon completion.
