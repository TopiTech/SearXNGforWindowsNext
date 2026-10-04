# Handoff Report — Reviewer M1-2 (Retrieval Interface & Conformance Reviewer)

## 1. Observation

1. **Interface Contract Verification (`tools/query_pipeline.py` & `tools/retrieval_service.py`)**:
   - In `tools/query_pipeline.py:22,31`:
     ```python
     clean_text: str  # text stripped of operators (preserves exact-match double quotes)
     ...
     clean_no_quotes: str = ""
     ```
   - In `tools/query_pipeline.py:321-342`:
     `clean_text = " ".join(clean_tokens).strip()`
     `clean_no_quotes = re.sub(r'"([^"]+)"', r"\1", clean_text)`
     `clean_no_quotes = re.sub(r"\s+", " ", clean_no_quotes).strip()`
     `lang = cls.detect_language(clean_no_quotes)`
     `freshness = cls.detect_freshness(clean_no_quotes)`
     `intent = cls.classify_intent(clean_no_quotes)`
   - In `tools/query_pipeline.py:362-377`:
     `base = processed.clean_no_quotes or processed.clean_text`
     Correctly prevents quotation marks from corrupting regex token boundaries during comparison pattern expansion (e.g. `"FastAPI" vs "Django"` cleanly expands to `['FastAPI', 'Django']`).
   - In `tools/retrieval_service.py:247`:
     `all_search_queries = [processed_q.clean_text] + expanded_q_list`
     Dispatches `processed_q.clean_text` to external search backends, preserving user-supplied quotes for exact phrase retrieval.
   - In `tools/retrieval_service.py:346-347, 382-386, 430-435`:
     `ranking_query = processed_q.clean_no_quotes or processed_q.clean_text`
     `self.lexical_reranker.rerank(ranking_query, candidate_items)`
     `candidate_items = self.cross_encoder.rerank(ranking_query, candidate_items, top_k=min(5, len(candidate_items)))`
     `passages = self.passage_chunker.extract_evidence(content=raw_body, query=ranking_query, source_id=source_id, ...)`
     Uses `ranking_query` (`clean_no_quotes`) for BM25 reranking, neural cross-encoder scoring, and passage evidence extraction, preventing quotation marks from disabling substring containment bonuses (`q_clean in title.lower()` in `lexical_rerank.py:236` and `q_lower in p.text.lower()` in `passage_chunker.py:434`).

2. **ReDoS Elimination & Performance**:
   - `QueryProcessor.COMPARISON_PATTERNS` regexes:
     `re.compile(r"\b([a-z0-9_+#.-]{1,50}+)\s+(vs|versus|compared to)\s+([a-z0-9_+#.-]{1,50}+)\b", re.IGNORECASE)`
     `re.compile(r"([^\s]{1,50}+)\s*(と|VS|対)\s*([^\s]{1,50}+)\s*(?:の\s*)?(比較|違い|どっち)", re.IGNORECASE)`
   - Direct execution of `pat_japanese.search('a' * 20000)` completed in **3.336ms** ($< 5\text{ms}$ threshold).
   - Direct execution of `QueryProcessor.classify_intent('a' * 20000)` completed in **0.335ms** ($< 1\text{ms}$).
   - Adversarial stress tests on 50,000 non-matching characters: `pat_ja=8.31ms`, `pat_en=0.34ms`, `classify_intent=1.44ms`.
   - Repetitive delimiter tests (`('a'*20 + ' と ' + 'b'*20)*200`): `0.85ms`. Pathological 50,000 `と` delimiter chain: `23.84ms`.
   - Repetitive matches (`('a'*50 + ' と ' + 'b'*50 + ' の比較 ')*50`): **0.01ms**.

3. **Query Length Bounding**:
   - `tools/query_pipeline.py:47, 256-257`:
     `MAX_QUERY_LENGTH: ClassVar[int] = 2000`
     `if len(orig) > cls.MAX_QUERY_LENGTH: orig = orig[: cls.MAX_QUERY_LENGTH].strip()`
   - Tested queries of length 2000, 2001, 4000, and 5000: bounded to $\le 2000$ characters without uncaught exceptions.

4. **Agentic Search & Public APIs Conformance**:
   - In `tools/agentic_search.py:1382-1410`: `execute_retrieval_search` forwards to `RetrievalService.search(...)` and receives `RetrievalResponse`.
   - In `tools/webui_next.py:565-580`: `/api/retrieval` route invokes `svc.search(...)` and serializes via `resp.to_dict()` and `resp.to_markdown()`.
   - `ProcessedQuery.to_dict()` keys remain strictly `["original", "normalized", "intent", "language", "freshness"]`, maintaining 100% backward compatibility for public JSON schemas.
   - `clean_no_quotes: str = ""` has a default value, preserving compatibility with existing instantiations.

5. **Static Quality & Test Execution Results**:
   - `python\python.exe -m ruff check tools/query_pipeline.py tools/retrieval_service.py tools/test_retrieval_pipeline.py tools/test_agent_tools.py`: 0 errors.
   - `python\python.exe -m ruff format --check tools/query_pipeline.py tools/retrieval_service.py tools/test_retrieval_pipeline.py tools/test_agent_tools.py`: 4 files already formatted.
   - `python\python.exe -m pyrefly check`: 0 errors (1 suppressed baseline).
   - `python\python.exe tools/test_retrieval_pipeline.py`: 50/50 tests passed in 0.031s.
   - `python\python.exe tools/test_agent_tools.py`: 60/60 tests passed in 0.024s.
   - `python\python.exe tools/test_agentic_search.py`: 41/41 tests passed in 0.833s.
   - `python\python.exe tools/test_patches.py`: 161/161 tests passed in 1.162s.
   - `python\python.exe tests/evaluation/run_benchmark.py`: 10/10 queries executed with Precision@5 = 1.0000, MRR = 1.0000, 0.0% failure rate across fast, balanced, and deep modes.

6. **Integrity & Authenticity Audit**:
   - No hardcoded test outputs or mock bypasses detected in source code.
   - No facade or dummy implementations; all regex bounds, keyword pre-filters, quote handlers, and reranker queries implement genuine operational logic.
   - Verification was independently executed in the local shell.

## 2. Logic Chain

1. *Observation 1 & 4*: The division of responsibilities between `clean_text` (preserving double quotes) and `clean_no_quotes` (stripping surrounding quotes) resolves the tension between external search engine dispatch and internal scoring.
   - Search engines require `clean_text` to enforce exact phrase matching (`"FastAPI lifespan"`).
   - Internal BM25 and passage scoring require `clean_no_quotes` because web document bodies and headings almost never contain literal quotation marks. If quotes were retained in `ranking_query`, exact substring bonuses (`q_clean in title.lower()` in `lexical_rerank.py:236` and `q_lower in p.text.lower()` in `passage_chunker.py:434`) would fail, resulting in false penalties.
   - Query expansion for comparison queries requires `clean_no_quotes` so that regex word boundaries (`\b`) match cleanly.
2. *Observation 2*: The ReDoS mitigation successfully eliminates quadratic backtracking.
   - Bounding token lengths with `{1,50}` and possessive quantifiers `+` prevents the regex engine from backtracking into matched tokens upon mismatch.
   - The `COMPARISON_KEYWORDS` pre-filter short-circuits regex evaluation when no comparison keyword is present, achieving 0.335ms execution time on 20,000 characters.
   - Even under adversarial tests with pathological 50,000-character inputs, execution completes well within safety boundaries.
3. *Observation 3*: The 2,000-character ceiling prevents buffer bloat and memory pressure in NFKC normalization and tokenization without crashing or dropping valid user inputs.
4. *Observation 5 & 6*: Clean static checks (Ruff lint, Ruff format, Pyrefly) and 100% test pass rate across 312 unit tests and the evaluation benchmark confirm that zero regressions were introduced.

## 3. Caveats

- In queries with unclosed quotes (e.g. `'foo "bar baz'`), `re.sub(r'"([^"]+)"', r"\1", clean_text)` will not strip the unmatched quote, leaving `clean_no_quotes` as `'foo "bar baz'`. BM25 tokenization handles this gracefully via regex token extraction, but literal phrase bonus is not applied. This is expected behavior for malformed user inputs.
- External live search engine availability is subject to network connectivity; regression testing and verification properly relied on standard deterministic unit mocks and benchmark suites.

## 4. Conclusion

**Verdict: APPROVE**

Worker M1's remediation for Milestone 1 conforms 100% to all specifications in `PROJECT.md` and `ORIGINAL_REQUEST.md`:
- ReDoS vulnerability in `COMPARISON_PATTERNS` is resolved ($3.336\text{ms} < 5\text{ms}$).
- Query length limit of 2,000 characters is enforced safely.
- Exact-phrase double quotes are retained for search dispatch while `clean_no_quotes` is properly routed to BM25 reranking, cross-encoder scoring, and passage evidence extraction.
- Zero regressions were introduced to agentic search, WebUI, or public APIs.
- All 312 unit tests, evaluation benchmark, Pyrefly type checking, and Ruff lint/formatting checks pass cleanly.
- Zero integrity violations were detected.

## 5. Verification Method

To reproduce the verification independently:

```powershell
# 1. Static checks
python\python.exe -m ruff check tools/query_pipeline.py tools/retrieval_service.py tools/test_retrieval_pipeline.py tools/test_agent_tools.py
python\python.exe -m ruff format --check tools/query_pipeline.py tools/retrieval_service.py tools/test_retrieval_pipeline.py tools/test_agent_tools.py
python\python.exe -m pyrefly check

# 2. Unit and regression tests
python\python.exe tools/test_retrieval_pipeline.py
python\python.exe tools/test_agent_tools.py
python\python.exe tools/test_agentic_search.py
python\python.exe tools/test_patches.py

# 3. Quality evaluation benchmark
python\python.exe tests/evaluation/run_benchmark.py

# 4. Measure ReDoS safety (< 5ms)
python\python.exe -c "import sys, time; sys.path.insert(0, 'tools'); from query_pipeline import QueryProcessor; pat = QueryProcessor.COMPARISON_PATTERNS[1]; t0 = time.perf_counter(); pat.search('a' * 20000); print(f'Execution time: {(time.perf_counter() - t0)*1000:.3f}ms')"
```
