# Comprehensive Codebase Survey Report: Query Pipelines & Backend APIs

**Auditor**: Explorer 1 (Query Pipeline & Backend APIs)  
**Date**: 2026-10-04  
**Scope**: Core query pipelines, backend web endpoints, public API data contracts, security vulnerabilities (SSRF, secret exposure, command injection, resource exhaustion), concurrency, and test suites.  
**Repository**: `SearXNGforWindowsNext`

---

## 1. Executive Summary

This survey conducted an exhaustive source-level investigation of the query execution pipelines, server routing mechanisms, public API contracts, and security controls across `SearXNGforWindowsNext`. 

### Key Findings Summary
1. **Critical / High Severity Vulnerability — ReDoS in Query Processor**:
   A catastrophic regular expression backtracking vulnerability ($O(N^2)$ algorithmic complexity) exists in `tools/query_pipeline.py` within `COMPARISON_PATTERNS`. Submitting queries lacking whitespace or comparison keywords locks CPU execution for seconds to minutes, exposing `/deep_search` and `/api/retrieval` to Denial of Service.
2. **Robust Multi-Layered SSRF Defense**:
   SSRF mitigations across `/scrape` and `tools/url_normalizer.py` are robust: thread-safe DNS pinning hooks `socket.getaddrinfo` to eliminate DNS rebinding, and extensive IP validation blocks IPv4/IPv6 private ranges, loopback, link-local, multicast, 6to4, teredo, mapped addresses, and obfuscated decimal/octal/hex formats. Tested against 20+ attack vectors with 100% block rate.
3. **Secure Secrets and Configuration Management**:
   The application uses an out-of-tree secret key architecture (`tools/ensure-secret-key.py` and `config/secret.key`), strictly gitignored. Runtime environment variable `SEARXNG_SECRET` prevents key exposure in tracked files. Zero hardcoded secrets, API tokens, or remote credential leaks were detected.
4. **Command Injection Immunization**:
   Zero shell invocations (`os.system`, `subprocess`, `popen`, `exec`, `eval`) exist in runtime search, scrape, or agentic pipeline pathways.
5. **Data Contract Integrity & Backward Compatibility**:
   Native SearXNG `/search` outputs (`json`, `csv`, `rss`) and custom `json_lite` format operate cleanly. `/api/retrieval` strictly adheres to `schema_version: "1.0"`. A minor form loss issue was identified in browser POST fallback redirection.
6. **Test Suite Health**:
   All 4 automated unit test suites (`test_patches.py`: 161 tests, `test_agent_tools.py`: 57 tests, `test_agentic_search.py`: 41 tests, `test_retrieval_pipeline.py`: 44 tests), evaluation benchmark (10 queries, 100% precision@5), Ruff linter/format, and Pyrefly type checking pass cleanly.

---

## 2. Core Query Execution Pipelines

The backend features two complementary search architectures:
- **Agentic Search Pipeline** (`tools/agentic_search.py`): Focused on fast, one-pass meta-search with speculative page fetching, token budgeting, and AI Markdown packaging.
- **Deterministic Structured Retrieval Pipeline** (`tools/retrieval_service.py` & `tools/query_pipeline.py`): Focused on multi-query expansion, reciprocal rank fusion (RRF), multilingual BM25 reranking, heading passage chunking, and grounded citation generation.

```
                                  [ Incoming Query / Request ]
                                                │
                     ┌──────────────────────────┴──────────────────────────┐
                     ▼                                                     ▼
           [ mode='deep' / 'fast' ]                              [ mode='balanced' ]
          (tools/agentic_search.py)                           (tools/retrieval_service.py)
                     │                                                     │
        QueryOptimizer Intent Routing                         DeterministicQueryPipeline
   (code / academic / news / general)                       (8 canonical intent categories)
                     │                                                     │
         In-process Meta-Search                                Multi-Query Expansion
          (webapp.py / client)                                             │
                     │                                            Multi-Engine Search
       SpeculativeFetcher (Parallel)                                        │
           (Daemon worker threads)                            URL Normalization & Multi-Stage Dedup
                     │                                             (Levenshtein + CJK N-gram)
         BM25PassageExtractor                                              │
                     │                                            Reciprocal Rank Fusion (RRF)
        TokenBudgeter (Markdown Packing)                                   │
                     │                                            Multilingual BM25 Reranker
                     ▼                                             (Field-weighted: title/heading)
         [ Unified Search Result ]                                         │
                                                              Speculative Concurrent Scraping
                                                                (SSRF-pinned, daemon threads)
                                                                           │
                                                              HeadingPassageChunker & SecurityScan
                                                                           │
                                                                           ▼
                                                                [ RetrievalResponse v1.0 ]
```

### Component Analysis

| Module | Core Responsibilities | Key Design Patterns | Potential Issues / Observations |
|---|---|---|---|
| `tools/query_pipeline.py` | NFKC normalization, search operator extraction (`site:`, `+site:`, `-site:`, `filetype:`), exact phrase extraction, intent classification (8 types), deterministic query expansion. | Rule-based regex token classification without external LLM dependencies. | **ReDoS in `COMPARISON_PATTERNS`** (line 126); double-quote stripping removes exact-phrase quotes; hardcoded year freshness (2024–2029). |
| `tools/retrieval_service.py` | End-to-end retrieval coordinator; multi-query dispatch; candidate pool filtering; composite scoring (fusion 40%, lexical 35%, quality 15%, freshness 10%); passage evidence assembly. | Shared stateless component singletons; thread-local DNS pinning delegation; daemon worker threads for scraping. | Graceful partial failure reporting (`is_partial=True`); clean warning accumulation. |
| `tools/agentic_search.py` | Unified search entrypoint (`mode="auto"\|"deep"\|"fast"\|"scrape"`); speculative fetching; BM25 highlight extraction; token budgeting and RAG prompt synthesis. | Dynamic mode resolution; semaphore-bounded parallel fetcher; token estimation heuristics for Japanese and English. | Delegates to `retrieval_service` when `mode="balanced"`; robust fallback if engines fail. |
| `tools/url_normalizer.py` | URL canonicalization, tracking parameter stripping (preserving cryptographically signed URLs), IDN punycode, SSRF URL pre-validation. | `lru_cache` accelerated normalization; RFC 3986 percent-encoding normalization; static host blocking. | `is_safe_retrieval_url` defaults to `resolve_dns=False` for speed, delegating live DNS resolution and pinning to the HTTP client layer. |
| `tools/deduplication.py` | 6-stage deduplication: exact normalized URL, canonical URL, exact title, near-duplicate title (Levenshtein), snippet similarity, domain grouping. | Dynamic programming Levenshtein with optional `rapidfuzz` acceleration; character N-gram Jaccard for CJK. | Retains alternate URLs in `duplicate_urls` and merges engine attribution. |
| `tools/rank_fusion.py` | Reciprocal Rank Fusion ($1 / (k + \text{rank})$) with multi-query and engine consensus bonuses; explainable `ScoreComponents`. | Additive bonus scaling with configurable saturation ceilings (`max_consensus_bonus=0.45`, `max_multi_query_bonus=0.40`). | Normalizes ranks across disparate engine result distributions. |
| `tools/lexical_rerank.py` | Multilingual BM25 document and passage reranking without external dictionary dependencies. | Latin alphanumeric tokenization + CJK contiguous character 2-grams and 3-grams; strictly positive IDF ($1.0 + \dots$). | Field-weighted scoring (title 1.5x, headings 1.2x, content 1.0x). |
| `tools/passage_chunker.py` | Heading-aware HTML and Markdown passage chunking; HTML metadata extraction via `trafilatura`/`lxml`; adversarial prompt injection detection. | Context window chunking with sliding overlap; boundary preservation at sentence breaks. | `SecurityScanner` catches jailbreaks, leak directives, and exfiltration attempts. |
| `tools/cross_encoder_rerank.py` | Optional semantic reranker using `sentence-transformers`. | Lazy loader with graceful no-op fallback (`enabled=False` by default). | Zero runtime dependency overhead when unused. |

---

## 3. Web Application Server Endpoints & Routing

### Integration Mechanism
SearXNG core routes are defined in `python/Lib/site-packages/searx/webapp.py`. During build/patch execution (`tools/apply-patches.py`), `patch_webapp_ai_webui` injects the integration hook:
```python
import webui_next as _webui_next
_webui_next.register_next_webui(app, sys.modules.get(__name__))
```

`tools/webui_next.py:register_next_webui` mounts the unified API routes and installs request interception guards:
1. **Tier A (`app.before_request`)**:
   - `GET /` -> Serves the modern AI-First Search & Context Studio (`AI_WORKSPACE_HTML`).
   - `GET /search` -> Redirects browser navigation to `/?q=...` unless programmatic data formats (`json`, `json_lite`, `csv`, `rss`) or `Accept: application/json` are requested.
   - `GET /preferences` -> Redirects browser navigation to `/?mode=settings`.
   - `GET /about` -> Redirects browser navigation to `/?mode=agent`.
2. **Tier B (`app.view_functions` replacement)**:
   - Preserves original handlers (`orig_search`, `orig_preferences`) while intercepting UI calls.
3. **Tier C (Dedicated API Routes)**:
   - Registers `/ai`, `/next`, `/ai/embed.css`, `/ai/embed.js`, `/api/ai_info`, `/api/settings/engines`, `/api/scrape_analyze`, `/deep_search`, `/api/search` (alias), and `/api/retrieval`.

---

## 4. Public APIs and Data Contracts

### 4.1. `/search`
- **Route**: `GET /search`, `POST /search`
- **Supported Formats**: `html` (redirects to AI Studio in browser), `json` (upstream SearXNG schema), `json_lite` (compact GenAI schema), `csv`, `rss`.
- **Query Parameters**: `q`, `format`, `categories`, `engines`, `pageno`, `time_range`, `language`, `safesearch`.
- **`json_lite` Contract**:
  ```json
  {
    "query": "fastapi lifespan",
    "results": [
      {
        "title": "Lifespan Events - FastAPI",
        "url": "https://fastapi.tiangolo.com/advanced/events/",
        "content": "...",
        "source": "duckduckgo",
        "score": 1.25,
        "published_date": "2024-01-15T00:00:00Z",
        "author": "",
        "category": "it"
      }
    ],
    "suggestions": [],
    "corrections": []
  }
  ```
  Scores are sanitized against `NaN` and `Infinity` to guarantee valid JSON serialization.

### 4.2. `/scrape`
- **Route**: `GET /scrape`, `POST /scrape`
- **Parameters**: `url` (via query string, form parameter, or JSON `{"url": "..."}`).
- **Success Response (200)**:
  ```json
  {
    "url": "https://example.com",
    "content": "Clean extracted plain-text content..."
  }
  ```
- **Error Status Codes**:
  - `400 Bad Request`: Missing URL or SSRF block (e.g., `{"error": "Blocked: 127.0.0.1 is a private/reserved IP"}`).
  - `422 Unprocessable Entity`: Scrape completed but article content extraction failed.
  - `502 Bad Gateway`: Response exceeded 5MB size limit or network fetch failure.
  - `504 Gateway Timeout`: Upstream site timed out.

### 4.3. `/deep_search` (and alias `/api/search`)
- **Route**: `GET /deep_search`, `POST /deep_search`
- **Parameters**:
  - `q` / `query` / `url`: Search query or URL.
  - `mode`: `auto` (default), `deep`, `fast`, `classic`, `scrape`, `balanced`, `retrieval`.
  - `depth` / `search_depth`: `basic`, `advanced`, `code`, `fast`.
  - `count` / `max_results`: 1–50 (default 5).
  - `format`: `json` (default), `markdown` / `md`, `json_ai`.
  - `max_tokens`: Context token budget (500–20000, default 3000).
  - `include_highlights`: Boolean (default true).
  - `site` / `include_domains`: Whitelisted domains.
  - `exclude_site` / `exclude_domains`: Blacklisted domains.
- **Contract**:
  Returns comprehensive metadata, scraped page extracts, BM25 highlighted snippets, and copy-ready `rag_prompt` formatted for direct LLM system prompt injection.

### 4.4. `/api/retrieval`
- **Route**: `GET /api/retrieval`, `POST /api/retrieval`
- **Parameters**: `q` / `query`, `mode` (`fast`, `balanced`, `deep`), `count` (1–50), `categories`, `engines`, `time_range`, `site`, `exclude_site`, `format` (`json` or `markdown`).
- **Contract (`schema_version: "1.0"`)**:
  ```json
  {
    "schema_version": "1.0",
    "query": {
      "original": "Python 3.12 新機能",
      "normalized": "Python 3.12 新機能",
      "intent": "research",
      "language": "ja",
      "freshness": "2024"
    },
    "search": {
      "mode": "balanced",
      "expanded_queries": ["Python 3.12 新機能 architecture"],
      "engines_used": ["duckduckgo", "google"],
      "partial": false,
      "elapsed_ms": 2.8
    },
    "results": [
      {
        "id": "src_01",
        "title": "Python 3.12 の新機能 — Python ドキュメント",
        "url": "https://docs.python.org/ja/3/whatsnew/3.12.html",
        "canonical_url": "https://docs.python.org/ja/3/whatsnew/3.12.html",
        "domain": "docs.python.org",
        "published_at": "2023-10-02T00:00:00Z",
        "updated_at": null,
        "date_source": "meta_article_published",
        "date_confidence": "high",
        "source_type": "documentation",
        "score": 0.8842,
        "score_components": {
          "fusion": 0.65,
          "lexical_relevance": 0.92,
          "freshness": 0.8,
          "source_quality": 0.95,
          "engine_consensus": 0.15
        },
        "matched_queries": ["Python 3.12 新機能"],
        "engines": ["duckduckgo"],
        "snippet": "...",
        "evidence": [
          {
            "id": "src_01_p01",
            "heading": "新機能の概要",
            "text": "より明確なエラーメッセージ、PEP 695 型パラメータ構文...",
            "score": 0.84,
            "security_flags": []
          }
        ],
        "security_flags": [],
        "duplicate_urls": [],
        "raw_content": "...",
        "is_scraped": true
      }
    ],
    "warnings": [],
    "answers": [],
    "infoboxes": [],
    "markdown": "## Search Retrieval..."
  }
  ```

---

## 5. Security Vulnerabilities & Findings

### Vulnerability Findings Matrix

| ID | Title | Severity | Component | Root Cause | Impact |
|---|---|:---:|---|---|---|
| **SEC-01** | Catastrophic ReDoS in Comparison Query Intent Classification | **HIGH** | `tools/query_pipeline.py:126` | Quadratic backtracking in `re.compile(r"([^\s]+)\s*(と\|VS\|対)\s*([^\s]+)\s*(比較\|違い\|どっち)")` when evaluated against non-whitespace strings | CPU exhaustion / worker thread freeze (20k chars = 4.2s, 100k chars = minutes) |
| **SEC-02** | Unbounded Query Input Length | **MEDIUM** | `tools/query_pipeline.py:240` | `parse_and_normalize` processes unbounded input strings without truncation before running NFKC and regex passes | Memory bloat, CPU amplification for maliciously long query strings |
| **SEC-03** | Double Quotes Stripping from Search Query | **MEDIUM** | `tools/query_pipeline.py:307` | `clean_no_quotes = re.sub(r'"([^"]+)"', r"\1", clean_text)` strips quotes before sending query to search engines | Destroys exact-phrase matching intent, degrading search precision |
| **SEC-04** | Form Parameters Dropped in Browser POST Redirection | **MEDIUM** | `tools/webui_next.py:4031` | `unified_search_view` reads only `request.args` instead of `request.values` or `request.form` when redirecting unformatted POST | Query parameters submitted via HTML form POST are lost during redirect |
| **SEC-05** | Hardcoded Freshness Years (2024–2029) | **LOW** | `tools/query_pipeline.py:183` | `re.search(r"\b(202[4-9])\b", low)` only accounts for 2024 through 2029 | Fails to detect freshness for year 2030+ or historical reference years |

---

### Detailed Vulnerability Analysis

#### SEC-01: Catastrophic ReDoS in Comparison Query Intent Classification
- **Location**: `tools/query_pipeline.py`, line 126:
  ```python
  COMPARISON_PATTERNS: ClassVar[list[re.Pattern]] = [
      re.compile(r"\b([a-z0-9_+#.-]+)\s+(vs|versus|compared to)\s+([a-z0-9_+#.-]+)\b", re.IGNORECASE),
      re.compile(r"([^\s]+)\s*(と|VS|対)\s*([^\s]+)\s*(比較|違い|どっち)", re.IGNORECASE),
  ]
  ```
- **Mechanics**:
  The subexpression `([^\s]+)\s*(と|VS|対)` features a greedy non-whitespace match `[^\s]+` immediately followed by an optional whitespace match `\s*` and Japanese delimiter characters `(と|VS|対)`. Because `[^\s]` matches all characters except whitespace (including `と`), on any long input string that lacks the delimiter or comparison keyword, Python's NFA regex engine attempts to match `[^\s]+` to the entire string, backtracks character by character, and then re-attempts matching starting at index 1, index 2, and so on ($O(N^2)$ iterations: $\sum_{k=1}^N k \approx \frac{N^2}{2}$).
- **Observed Behavior**:
  - 1,000 characters: 0.01s
  - 20,000 characters: **4.22 seconds**
  - 100,000 characters: **Over 100 seconds (process lock)**
- **Remediation**:
  1. Add an upfront guard check: `if not any(k in low for k in ("と", "vs", "対", "versus", "compared to")): return False` before executing regex search.
  2. Constrain token length using explicit length bounds, e.g.:
     `re.compile(r"(\S{1,64})\s*(と|VS|対)\s*(\S{1,64})\s*(比較|違い|どっち)", re.IGNORECASE)`
  3. Enforce maximum input query length before intent classification.

#### SEC-02: Unbounded Query Input Length
- **Location**: `tools/query_pipeline.py:240` (`QueryProcessor.parse_and_normalize`) and `tools/agentic_search.py:1097` (`execute_unified_search`).
- **Mechanics**:
  When queries are received via HTTP GET/POST, `query` is passed directly into Unicode NFKC normalization and regex splitting without a length ceiling. Malicious users or misconfigured agents can pass multi-megabyte payloads, causing excessive allocation and CPU burn.
- **Remediation**:
  Truncate `raw_query` to a reasonable operational boundary (e.g., `raw_query[:2000].strip()`).

#### SEC-03: Double Quotes Stripping from Search Query
- **Location**: `tools/query_pipeline.py:307`:
  ```python
  clean_no_quotes = re.sub(r'"([^"]+)"', r"\1", clean_text)
  ```
- **Mechanics**:
  While `parse_and_normalize` correctly extracts `exact_phrases`, it assigns `clean_text = clean_no_quotes`. In `retrieval_service.py` line 247, `all_search_queries = [processed_q.clean_text] + expanded_q_list` sends the unquoted string to underlying search engines. Exact phrase searches like `"FastAPI lifespan"` are transformed into unquoted keyword searches `FastAPI lifespan`.
- **Remediation**:
  Preserve `clean_text` with original double quotes for search engine dispatch, using `clean_no_quotes` solely for internal linguistic analysis.

#### SEC-04: Form Parameters Dropped in Browser POST Redirection
- **Location**: `tools/webui_next.py:4031`:
  ```python
  def unified_search_view() -> Any:
      ...
      params = dict(request.args)
      qs = urllib.parse.urlencode(params)
      return redirect(f"/?{qs}" if qs else "/", code=302)
  ```
- **Mechanics**:
  If a user or browser submits a native HTML search form using `POST /search` without specifying a data format, `request.args` contains only URL query string parameters. Form data present in `request.form` (such as `q=myquery`) is ignored, redirecting the user to `/` with an empty query.
- **Remediation**:
  Combine `request.values` or check `request.form` if `request.args` is empty:
  `params = dict(request.values)` (excluding sensitive fields).

---

### Security Audits with Clean Bill of Health

1. **SSRF Mitigation**:
   - Validated: `python/Lib/site-packages/searx/webapp.py` lines 693–795, 950–1120.
   - Mechanism: Reusable `httpx.Client` with connection pooling, `trust_env=False` to prevent HTTP_PROXY bypass, `_safe_getaddrinfo` thread-local DNS pinning, static IP blocking via `ipaddress` library, and full resolution checking before socket connect.
   - Redirect Safety: Each HTTP 3xx redirect re-resolves and validates the target IP and repins the destination host.
   - Result: Fully verified; robust against DNS rebinding, IP encoding tricks, and IPv6 transitions.
2. **Secret Exposure & Logging**:
   - Validated: `tools/ensure-secret-key.py`, `python/Lib/site-packages/searx/webapp.py`.
   - Mechanism: Random 32-byte hex keys generated on first boot; stored in `config/secret.key` (in `.gitignore`); passed via `SEARXNG_SECRET` environment variable; placeholder `"ultrasecretkey"` causes fatal exit if used in production.
   - Result: Zero credential leaks detected.
3. **Command Injection**:
   - Validated across all runtime code in `tools/` and `python/Lib/site-packages/searx/`.
   - Result: No command execution functions present in request-handling code.

---

## 6. Concurrency, Correctness, and Error Handling

1. **Concurrency Architecture**:
   - `retrieval_service.py` uses `threading.Thread(daemon=True)` combined with a `threading.Semaphore(5)` to bound speculative scraping concurrency.
   - Speculative scrape threads are monitored with `concurrent.futures.wait(..., timeout=timeout)`. Expired futures are cancelled immediately, and daemon threads are allowed to terminate without blocking Python process exit.
   - `_thread_local_dns` ensures that multiple concurrent scrape requests within the same process maintain isolated DNS pinning contexts without race conditions.
2. **Error Resilience**:
   - If an engine fails, `SearchWithPlugins` records the error in `warnings` and marks `partial: true` rather than aborting the pipeline.
   - If a page cannot be scraped or is blocked by SSRF checks, `is_scraped` is marked `false`, the error is stored in `scrape_error`, and the result is retained with its snippet.
   - In-process search (`_search_in_process`) retries once with default engines if specialized category/engine routing yields zero results.

---

## 7. Backward Compatibility with Upstream SearXNG

1. **API Endpoints**:
   - `/search?format=json`, `/search?format=csv`, `/search?format=rss` retain complete backward compatibility with upstream SearXNG schemas.
   - Third-party SearXNG clients (e.g. RSS readers, browser extensions, Raycast/Alfred plugins) function without modification when requesting data formats or providing `Accept: application/json`.
2. **Preferences & Settings**:
   - `/preferences` persists user settings and engine selections in cookies using upstream serialization formats.
   - Native themes (`simple`) continue to render with progressive enhancement CSS/JS injected via template patches.
3. **Engine Initialization**:
   - Patches in `engines/__init__.py` and `search/processors/__init__.py` gracefully skip inactive or unconfigured onion/Tor engines, preventing startup crashes on Windows.

---

## 8. Test Suites & Quality Verification

All existing tests were executed against the runtime environment:

| Test Command | Test Count | Result | Duration | Notes |
|---|:---:|:---:|:---:|---|
| `python\python.exe tools/test_patches.py` | 161 | **PASS** | 3.07s | Patch idempotency, syntax checks, engine disabling, secret key generation |
| `python\python.exe tools/test_agent_tools.py` | 57 | **PASS** | 0.35s | MCP server, CLI commands, SearXNG client, WebUI regression |
| `python\python.exe tools/test_agentic_search.py` | 41 | **PASS** | 0.85s | QueryOptimizer, DomainScorer, SpeculativeFetcher, TokenBudgeter |
| `python\python.exe tools/test_retrieval_pipeline.py` | 44 | **PASS** | 0.02s | URLNormalizer, Deduplicator, RRF, BM25 Lexical, Chunker, Schema v1.0 |
| `python\python.exe tests/evaluation/run_benchmark.py` | 10 | **PASS** | ~0.15s | Quality benchmark: 100% P@5, 100% official presence, 0% failure |
| `python\python.exe -m ruff check .` | Whole repo | **PASS** | 0.20s | 0 lint errors |
| `python\python.exe -m ruff format --check .` | Whole repo | **PASS** | 0.15s | 0 format errors |
| `python\python.exe -m pyrefly check` | Whole repo | **PASS** | 0.30s | 0 unresolved type errors |

---

## 9. Prioritized Remediation Recommendations

### Priority 1: High Severity (Remediation Required)
- **Fix ReDoS in `tools/query_pipeline.py`**:
  Replace vulnerable greedy regex in `COMPARISON_PATTERNS` with bounded pattern and fast keyword pre-check.
  ```python
  # Proposed fix for tools/query_pipeline.py lines 124-127 & 199-203:
  COMPARISON_PATTERNS: ClassVar[list[re.Pattern]] = [
      re.compile(r"\b([a-z0-9_+#.-]+)\s+(vs|versus|compared to)\s+([a-z0-9_+#.-]+)\b", re.IGNORECASE),
      re.compile(r"(\S{1,64})\s*(と|VS|対)\s*(\S{1,64})\s*(比較|違い|どっち)", re.IGNORECASE),
  ]

  # Inside classify_intent:
  if any(w in low for w in ("vs", "versus", "compared to", "と", "対", "比較", "違い", "どっち")):
      for pat in cls.COMPARISON_PATTERNS:
          if pat.search(low):
              return "comparison"
  ```
- **Bound query length in `parse_and_normalize`**:
  Clamp `raw_query` to `max_length = 2000` characters at entry to prevent CPU exhaustion on malformed queries.

### Priority 2: Medium Severity
- **Preserve exact-phrase quotes in `clean_text`**:
  Update `tools/query_pipeline.py` so that `processed.clean_text` preserves user-supplied double quotes for query dispatch, passing unquoted text only to internal tokenizers.
- **Preserve form parameters in `unified_search_view`**:
  In `tools/webui_next.py`, ensure `dict(request.values)` is inspected so POST form submissions are preserved on 302 redirection.

### Priority 3: Low Severity
- **Broaden freshness year detection**:
  Update `tools/query_pipeline.py:183` to match dynamic 4-digit years: `re.search(r"\b(20[2-3][0-9])\b", low)`.
