#!/usr/bin/env python3
"""Unit tests for the Agentic Deep Search orchestrator (Exa/Tavily-like logic)."""

from __future__ import annotations

import os
import sys
import threading
import time
import unittest
from unittest.mock import MagicMock

# Ensure tools directory is in sys.path
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

import agentic_search


class TestQueryOptimizer(unittest.TestCase):
    """Test query normalization, domain filter parsing, and intent routing."""

    def test_parse_query_with_domain_operators(self) -> None:
        query = "asyncio tutorial site:docs.python.org -site:spam.com"
        clean_q, inc, exc = agentic_search.QueryOptimizer.parse_query(query)
        self.assertEqual(clean_q, "asyncio tutorial")
        self.assertEqual(inc, ["docs.python.org"])
        self.assertEqual(exc, ["spam.com"])

    def test_classify_intent_code(self) -> None:
        intents = [
            agentic_search.QueryOptimizer.classify_intent("FastAPI lifespan context manager syntax error"),
            agentic_search.QueryOptimizer.classify_intent(
                "Python traceback TypeError: NoneType object is not callable"
            ),
            agentic_search.QueryOptimizer.classify_intent("React 19 useActionState hook migration"),
        ]
        for intent in intents:
            self.assertEqual(intent, "code")

    def test_classify_intent_academic(self) -> None:
        intent = agentic_search.QueryOptimizer.classify_intent(
            "diffusion model transformer attention mechanism paper arxiv"
        )
        self.assertEqual(intent, "academic")

    def test_classify_intent_news(self) -> None:
        intent = agentic_search.QueryOptimizer.classify_intent("SearXNG latest release announced today")
        self.assertEqual(intent, "news")

    def test_classify_intent_general(self) -> None:
        intent = agentic_search.QueryOptimizer.classify_intent("capital of France history")
        self.assertEqual(intent, "general")

    def test_get_routing(self) -> None:
        cat_code, eng_code = agentic_search.QueryOptimizer.get_routing("code")
        self.assertEqual(cat_code, "it")
        self.assertIn("github", eng_code)

        cat_acad, eng_acad = agentic_search.QueryOptimizer.get_routing("academic")
        self.assertIn("science", cat_acad)
        self.assertIn("arxiv", eng_acad)


class TestDomainScorer(unittest.TestCase):
    """Test domain scoring, filtering, and anti-spam."""

    def setUp(self) -> None:
        self.scorer = agentic_search.DomainScorer()

    def test_extract_domain(self) -> None:
        self.assertEqual(agentic_search.extract_domain("https://www.github.com/torvalds/linux"), "github.com")
        self.assertEqual(agentic_search.extract_domain("http://docs.python.org:8080/3/library"), "docs.python.org")
        self.assertEqual(agentic_search.extract_domain("invalid-url"), "")

    def test_boost_and_penalized_weights(self) -> None:
        # Boosted
        self.assertGreater(self.scorer.get_domain_weight("docs.python.org"), 2.0)
        self.assertGreater(self.scorer.get_domain_weight("github.com"), 2.0)
        self.assertGreater(self.scorer.get_domain_weight("myproject.readthedocs.io"), 1.5)

        # Penalized / Spam
        self.assertLess(self.scorer.get_domain_weight("geeksforgeeks.org"), 1.0)
        self.assertLessEqual(self.scorer.get_domain_weight("copypastetutorials.com"), 0.2)

        # Neutral
        self.assertEqual(self.scorer.get_domain_weight("randomblog.xyz"), 1.0)

    def test_score_results_filtering(self) -> None:
        raw_results = [
            {"title": "Low Quality Mirror", "url": "https://copypaste-coding.com/p", "content": "spam content"},
            {
                "title": "Python Docs",
                "url": "https://docs.python.org/3/asyncio.html",
                "content": "Official asyncio docs",
            },
            {"title": "Other Blog", "url": "https://example.com/blog", "content": "Example post"},
        ]

        # Standard score: Python Docs should be ranked top due to authority boost
        scored = self.scorer.score_results(raw_results)
        self.assertEqual(len(scored), 3)
        self.assertEqual(scored[0].domain, "docs.python.org")

        # Include filter
        filtered_inc = self.scorer.score_results(raw_results, include_domains=["python.org"])
        self.assertEqual(len(filtered_inc), 1)
        self.assertEqual(filtered_inc[0].domain, "docs.python.org")

        # Exclude filter
        filtered_exc = self.scorer.score_results(raw_results, exclude_domains=["docs.python.org"])
        domains = [r.domain for r in filtered_exc]
        self.assertNotIn("docs.python.org", domains)


class TestBM25PassageExtractor(unittest.TestCase):
    """Test passage segmentation and BM25 highlight extraction."""

    def setUp(self) -> None:
        self.extractor = agentic_search.BM25PassageExtractor()

    def test_split_passages_preserves_code_block(self) -> None:
        text = (
            "This is introduction paragraph that provides important context about the topic.\n\n"
            "```python\ndef lifespan(app):\n    yield\n```\n\n"
            "This is concluding paragraph after the code block explaining how it works."
        )
        passages = self.extractor.split_passages(text, min_chars=10)
        self.assertEqual(len(passages), 3)
        self.assertTrue(passages[1].startswith("```python"))
        self.assertTrue(passages[1].endswith("```"))

    def test_extract_highlights_matches_query(self) -> None:
        text = (
            "Chapter 1: The weather was sunny and warm in Paris during the month of May.\n\n"
            "Chapter 2: Implementing lifespan handlers in FastAPI requires defining an async context manager. "
            "The lifespan parameter in FastAPI replaces the deprecated on_event startup handlers.\n\n"
            "Chapter 3: Cooking pasta requires boiling water and a pinch of salt."
        )
        highlights = self.extractor.extract_highlights(text, query="FastAPI lifespan context manager", top_k=1)
        self.assertEqual(len(highlights), 1)
        self.assertIn("lifespan parameter in FastAPI", highlights[0])


class TestSpeculativeFetcher(unittest.TestCase):
    """Test parallel speculative scraping."""

    def test_fetch_pages_parallel(self) -> None:
        mock_scrape = MagicMock()

        def fake_scrape(url: str, **kwargs):
            if "fail" in url:
                return {"error": "Connection error"}
            return {"content": f"Content of {url}"}

        mock_scrape.side_effect = fake_scrape

        fetcher = agentic_search.SpeculativeFetcher(scrape_func=mock_scrape, max_workers=2)
        items = [
            agentic_search.SearchResultItem(
                title="Page 1", url="https://site1.com", domain="site1.com", content="snip1"
            ),
            agentic_search.SearchResultItem(
                title="Page 2", url="https://site2-fail.com", domain="site2.com", content="snip2"
            ),
        ]

        updated = fetcher.fetch_pages(items, max_fetch=2)
        self.assertEqual(len(updated), 2)
        self.assertTrue(updated[0].is_scraped)
        self.assertEqual(updated[0].full_content, "Content of https://site1.com")
        self.assertFalse(updated[1].is_scraped)
        self.assertIn("Connection error", updated[1].scrape_error)

    def test_fetch_pages_handles_urllib_error(self) -> None:
        import urllib.error

        def failing_scrape(url: str, **kwargs):
            raise urllib.error.URLError("Connection refused")

        fetcher = agentic_search.SpeculativeFetcher(scrape_func=failing_scrape, max_workers=2)
        items = [
            agentic_search.SearchResultItem(
                title="Page 1", url="https://site1.com", domain="site1.com", content="snip1"
            ),
        ]

        updated = fetcher.fetch_pages(items, max_fetch=1)
        self.assertEqual(len(updated), 1)
        self.assertFalse(updated[0].is_scraped)
        self.assertIn("Connection refused", updated[0].scrape_error)

    def test_fetch_pages_timeout_marks_items_and_returns_promptly(self) -> None:
        """Regression: scrapes exceeding the wall-clock budget must be marked as timed out
        without waiting for their internal completion."""
        release = threading.Event()

        def hung_scrape(url: str, **kwargs):
            # Simulate a backend that ignores its timeout argument (e.g. a stuck socket).
            release.wait(timeout=10.0)
            return {"content": "late"}

        fetcher = agentic_search.SpeculativeFetcher(scrape_func=hung_scrape, max_workers=2)
        items = [
            agentic_search.SearchResultItem(
                title="Slow", url="https://slow.example", domain="slow.example", content=""
            ),
        ]
        t0 = time.perf_counter()
        updated = fetcher.fetch_pages(items, max_fetch=1, timeout=0.5)
        elapsed = time.perf_counter() - t0
        try:
            self.assertLess(elapsed, 5.0, "fetch_pages must return near the wall-clock timeout")
            self.assertFalse(updated[0].is_scraped)
            self.assertEqual(updated[0].scrape_error, "Scrape timed out")
        finally:
            release.set()

    def test_fetch_pages_worker_threads_are_daemons(self) -> None:
        """Regression: abandoned scrapes ran on non-daemon ThreadPoolExecutor workers, so the
        interpreter's atexit join blocked process exit (CLI deep search hung for seconds after
        results were printed). Workers must be daemon threads so a hung scrape can never keep
        the process alive."""
        observed: list[bool] = []
        seen = threading.Event()

        def inspecting_scrape(url: str, **kwargs):
            observed.append(threading.current_thread().daemon)
            seen.set()
            return {"content": "ok"}

        fetcher = agentic_search.SpeculativeFetcher(scrape_func=inspecting_scrape, max_workers=1)
        items = [agentic_search.SearchResultItem(title="t", url="https://ok.example", domain="ok.example", content="")]
        updated = fetcher.fetch_pages(items, max_fetch=1, timeout=5.0)
        self.assertTrue(seen.wait(timeout=5.0))
        self.assertTrue(updated[0].is_scraped)
        self.assertEqual(observed, [True], "scrape workers must run as daemon threads")


class TestTokenBudgeter(unittest.TestCase):
    """Test token estimation and markdown packing."""

    def test_pack_markdown_within_budget(self) -> None:
        items = [
            agentic_search.SearchResultItem(
                title="Doc 1",
                url="https://doc1.com",
                domain="doc1.com",
                content="Snippet 1",
                score=0.95,
                highlights=["Important highlight 1"],
            ),
            agentic_search.SearchResultItem(
                title="Doc 2",
                url="https://doc2.com",
                domain="doc2.com",
                content="Snippet 2",
                score=0.80,
                highlights=["Important highlight 2"],
            ),
        ]
        md = agentic_search.TokenBudgeter.pack_markdown(
            query="test query",
            items=items,
            max_tokens=2000,
            direct_answers=["Direct answer test"],
            intent="code",
        )
        self.assertIn("Deep Search Results: `test query`", md)
        self.assertIn("**Direct Answer**: Direct answer test", md)
        self.assertIn("Doc 1", md)
        self.assertIn("Important highlight 1", md)
        self.assertIn("Citations & Sources:", md)


class TestExecuteDeepSearch(unittest.TestCase):
    """Test full execute_deep_search pipeline."""

    def test_execute_deep_search_end_to_end(self) -> None:
        mock_search = MagicMock()
        mock_search.return_value = {
            "query": "fastapi lifespan",
            "results": [
                {
                    "title": "FastAPI Lifespan Events",
                    "url": "https://fastapi.tiangolo.com/events",
                    "content": "Learn how to use lifespan events in FastAPI.",
                    "source": "duckduckgo",
                    "score": 1.0,
                }
            ],
            "answers": ["Use asynccontextmanager for lifespan events"],
        }

        mock_scrape = MagicMock()
        mock_scrape.return_value = {
            "url": "https://fastapi.tiangolo.com/events",
            "content": (
                "Header text\n\n"
                "You can define logic that should be executed before the application starts up.\n\n"
                "```python\n@asynccontextmanager\nasync def lifespan(app: FastAPI):\n    yield\n```"
            ),
        }

        res = agentic_search.execute_deep_search(
            query="fastapi lifespan syntax",
            search_func=mock_search,
            scrape_func=mock_scrape,
            search_depth="advanced",
            max_results=3,
        )

        self.assertNotIn("error", res)
        self.assertEqual(res["intent"], "code")
        self.assertEqual(res["results_count"], 1)
        self.assertEqual(len(res["results"]), 1)
        item = res["results"][0]
        self.assertEqual(item["domain"], "fastapi.tiangolo.com")
        self.assertTrue(item["is_scraped"])
        self.assertGreater(len(item["highlights"]), 0)
        self.assertIn("markdown", res)
        self.assertIn("Direct Answer", res["markdown"])

    def test_execute_deep_search_forwards_custom_timeout(self) -> None:
        mock_search = MagicMock()
        mock_search.return_value = {
            "query": "query",
            "results": [{"title": "T", "url": "https://example.com", "content": "C"}],
        }
        mock_scrape = MagicMock()
        mock_scrape.return_value = {"content": "Sample content"}

        agentic_search.execute_deep_search(
            query="test query",
            search_func=mock_search,
            scrape_func=mock_scrape,
            search_depth="advanced",
            timeout=8.5,
        )

        mock_search.assert_called_once()
        self.assertEqual(mock_search.call_args[1]["timeout"], 8.5)
        mock_scrape.assert_called_once()
        self.assertEqual(mock_scrape.call_args[1]["timeout"], 8.5)

    def test_is_url_input_and_parse_domain_list(self) -> None:
        self.assertTrue(agentic_search.is_url_input("https://docs.searxng.org/admin"))
        self.assertTrue(agentic_search.is_url_input("http://example.com"))
        self.assertFalse(agentic_search.is_url_input("FastAPI lifespan tutorial"))
        self.assertFalse(agentic_search.is_url_input("https://example.com with spaces"))

        domains = agentic_search.parse_domain_list(["https://www.github.com/foo, docs.python.org", "github.com"])
        self.assertEqual(domains, ["github.com", "docs.python.org"])

    def test_execute_unified_search_auto_scrape_url(self) -> None:
        mock_search = MagicMock()
        mock_scrape = MagicMock()
        mock_scrape.return_value = {
            "url": "https://docs.searxng.org/guide",
            "content": (
                "Introduction to SearXNG metasearch engine.\n\n"
                "The json_lite format returns compact token-optimized search results for AI agents."
            ),
        }

        res = agentic_search.execute_unified_search(
            query="https://docs.searxng.org/guide",
            search_func=mock_search,
            scrape_func=mock_scrape,
            mode="auto",
            focus_query="json_lite format",
        )
        mock_search.assert_not_called()
        mock_scrape.assert_called_once()
        self.assertEqual(res["mode"], "scrape")
        self.assertEqual(res["url"], "https://docs.searxng.org/guide")
        self.assertEqual(res["scraped_count"], 1)
        self.assertGreater(len(res["highlights"]), 0)
        self.assertIn("rag_prompt", res)

    def test_execute_unified_search_fast_mode(self) -> None:
        mock_search = MagicMock()
        mock_search.return_value = {
            "query": "python asyncio",
            "results": [
                {
                    "title": "Asyncio Docs",
                    "url": "https://docs.python.org/3/library/asyncio.html",
                    "content": "Asyncio is used as a foundation for multiple Python asynchronous frameworks.",
                    "source": "duckduckgo",
                    "score": 1.0,
                }
            ],
            "answers": [],
        }
        mock_scrape = MagicMock()

        res = agentic_search.execute_unified_search(
            query="python asyncio",
            search_func=mock_search,
            scrape_func=mock_scrape,
            mode="fast",
            max_results=3,
        )
        mock_search.assert_called_once()
        mock_scrape.assert_not_called()
        self.assertEqual(res["mode"], "fast")
        self.assertEqual(res["search_depth"], "fast")
        self.assertEqual(res["scraped_count"], 0)
        self.assertEqual(len(res["results"]), 1)
        self.assertIn("Fast Search Results", res["markdown"])
        self.assertIn("rag_prompt", res)

    def test_parse_query_normalizes_full_urls_in_site_operators(self) -> None:
        query = "kernel patch site:https://www.github.com/torvalds/linux -site:http://www.spam.example.com:8080/ads"
        clean_q, inc, exc = agentic_search.QueryOptimizer.parse_query(query)
        self.assertEqual(clean_q, "kernel patch")
        self.assertEqual(inc, ["github.com"])
        self.assertEqual(exc, ["spam.example.com"])

    def test_extract_domain_strips_credentials_and_brackets(self) -> None:
        self.assertEqual(
            agentic_search.extract_domain("https://user:secret@www.example.com:8443/path"),
            "example.com",
        )
        self.assertEqual(
            agentic_search.extract_domain("http://[::1]:8080/status"),
            "::1",
        )

    def test_domain_scorer_handles_none_fields_nan_score_and_published_date(self) -> None:
        scorer = agentic_search.DomainScorer()
        raw = [
            {
                "title": None,
                "url": "https://docs.python.org/3/library/asyncio.html",
                "content": None,
                "source": None,
                "score": float("nan"),
                "publishedDate": "2026-03-30",
            }
        ]
        scored = scorer.score_results(raw)
        self.assertEqual(len(scored), 1)
        self.assertEqual(scored[0].title, "Untitled")
        self.assertEqual(scored[0].content, "")
        self.assertEqual(scored[0].source, "")
        self.assertEqual(scored[0].published_date, "2026-03-30")
        self.assertGreater(scored[0].score, 0.0)

    def test_speculative_fetcher_timeout_does_not_block_on_hung_worker(self) -> None:
        import threading
        import time

        release_event = threading.Event()

        def hung_scrape(url: str, **kwargs):
            if "slow" in url:
                release_event.wait(timeout=5.0)
                return {"content": "Too late"}
            return {"content": "Fast page content"}

        fetcher = agentic_search.SpeculativeFetcher(scrape_func=hung_scrape, max_workers=2)
        items = [
            agentic_search.SearchResultItem(
                title="Fast", url="https://fast.example.com", domain="fast.example.com", content="s1"
            ),
            agentic_search.SearchResultItem(
                title="Slow", url="https://slow.example.com", domain="slow.example.com", content="s2"
            ),
        ]
        start = time.monotonic()
        try:
            updated = fetcher.fetch_pages(items, max_fetch=2, timeout=0.15)
            elapsed = time.monotonic() - start
            # Must not block for the full 5.0s hung thread duration
            self.assertLess(elapsed, 1.5)
            self.assertTrue(updated[0].is_scraped)
            self.assertEqual(updated[0].full_content, "Fast page content")
            self.assertFalse(updated[1].is_scraped)
            self.assertEqual(updated[1].scrape_error, "Scrape timed out")
        finally:
            release_event.set()

    def test_execute_unified_search_forwards_scrape_params_and_handles_exceptions(self) -> None:
        mock_search = MagicMock()
        mock_search.return_value = {
            "query": "rust tokio",
            "results": [
                {
                    "title": "Tokio Docs",
                    "url": "https://tokio.rs/tokio/tutorial",
                    "content": "Tokio is an asynchronous runtime for Rust.",
                    "source": "brave",
                    "score": 1.0,
                }
            ],
            "answers": [],
        }
        captured_kwargs = {}

        def spy_scrape(url: str, **kwargs):
            captured_kwargs.update(kwargs)
            return {"url": url, "content": "Tokio tutorial full body text for async Rust."}

        res = agentic_search.execute_unified_search(
            query="rust tokio",
            search_func=mock_search,
            scrape_func=spy_scrape,
            mode="deep",
            max_results=1,
            max_scrape_length=4321,
            timeout=9,
            base_url="http://127.0.0.1:9999",
        )
        self.assertEqual(res["scraped_count"], 1)
        self.assertEqual(captured_kwargs.get("max_length"), 4321)
        self.assertEqual(captured_kwargs.get("base_url"), "http://127.0.0.1:9999")
        self.assertLessEqual(captured_kwargs.get("timeout", 99), 9)

        # Verify exception resilience when search_func raises
        def raising_search(query: str, **kwargs):
            raise RuntimeError("search backend crashed")

        err_res = agentic_search.execute_unified_search(
            query="rust tokio",
            search_func=raising_search,
            scrape_func=spy_scrape,
            mode="fast",
        )
        self.assertIn("error", err_res)
        self.assertIn("search backend crashed", err_res["error"])

    def test_execute_unified_search_handles_unexpected_backend_errors(self) -> None:
        # Non-tuple exceptions (e.g. KeyboardInterrupt-style failures from a
        # backend) must become error dicts, never propagate out of the HTTP
        # pipeline. MemoryError/KeyboardInterrupt derive from BaseException,
        # not Exception, so the pipeline needs a BaseException fallback.
        def boom_search(query: str, **kwargs):
            raise MemoryError("backend exploded")

        def ok_scrape(url: str, **kwargs):
            return {"url": url, "content": "body"}

        err_res = agentic_search.execute_unified_search(
            query="rust tokio",
            search_func=boom_search,
            scrape_func=ok_scrape,
            mode="fast",
        )
        self.assertIn("error", err_res)
        self.assertIn("backend exploded", err_res["error"])

        def boom_scrape(url: str, **kwargs):
            raise MemoryError("scraper exploded")

        scrape_err = agentic_search.execute_scrape_pipeline(
            url="https://example.com/page",
            scrape_func=boom_scrape,
        )
        self.assertIn("error", scrape_err)
        self.assertIn("scraper exploded", scrape_err["error"])


class TestQueryOptimizerEdgeCases(unittest.TestCase):
    """Test URL formats and edge cases in query parsing."""

    def test_parse_query_with_urls_and_trailing_slashes(self) -> None:
        query = "lifespan site:https://docs.python.org/3/ -site:spam.com/"
        clean_q, inc, exc = agentic_search.QueryOptimizer.parse_query(query)
        self.assertEqual(clean_q, "lifespan")
        self.assertEqual(inc, ["docs.python.org"])
        self.assertEqual(exc, ["spam.com"])

    def test_parse_domain_list_with_quotes(self) -> None:
        query = "fastapi site:\"fastapi.tiangolo.com\" -site:'spam.com'"
        clean_q, inc, exc = agentic_search.QueryOptimizer.parse_query(query)
        self.assertEqual(clean_q, "fastapi")
        self.assertEqual(inc, ["fastapi.tiangolo.com"])
        self.assertEqual(exc, ["spam.com"])

    def test_token_budgeter_cjk_punctuation(self) -> None:
        # Verify Japanese punctuation and symbols are counted in CJK token budget
        ja_text = "【重要】検索結果の確認、および検証を実施しました。"
        tok = agentic_search.TokenBudgeter.estimate_tokens(ja_text)
        self.assertGreater(tok, 0)
        # 26 chars of pure CJK text should roughly estimate around 17-18 tokens (~1.5 chars/tok)
        self.assertTrue(15 <= tok <= 20)

    def test_fetch_pages_handles_unexpected_exception(self) -> None:
        def crash_scrape(url: str, **kwargs):
            raise RuntimeError("Unexpected scraper crash")

        fetcher = agentic_search.SpeculativeFetcher(scrape_func=crash_scrape, max_workers=1)
        items = [
            agentic_search.SearchResultItem(
                title="Page 1", url="https://site1.com", domain="site1.com", content="snip1"
            ),
        ]
        updated = fetcher.fetch_pages(items, max_fetch=1)
        self.assertEqual(len(updated), 1)
        self.assertFalse(updated[0].is_scraped)
        self.assertIn("Unexpected scraper crash", updated[0].scrape_error)


class TestRegressionHardening(unittest.TestCase):
    """Regression tests for code hardening and edge-case fixes."""

    def test_parse_query_with_plus_site_and_trailing_dots(self) -> None:
        query = "fastapi +site:.tiangolo.com. -site:spam.org."
        clean_q, inc, exc = agentic_search.QueryOptimizer.parse_query(query)
        self.assertEqual(clean_q, "fastapi")
        self.assertEqual(inc, ["tiangolo.com"])
        self.assertEqual(exc, ["spam.org"])

    def test_bm25_tokenize_nfkc_normalization(self) -> None:
        extractor = agentic_search.BM25PassageExtractor()
        # Fullwidth alphanumeric and zenkaku symbols
        tokens1 = extractor._tokenize("Ｐｙｔｈｏｎ　３．１１")
        tokens2 = extractor._tokenize("python 3.11")
        self.assertEqual(tokens1, tokens2)

    def test_bm25_split_passages_crlf_and_boundary(self) -> None:
        extractor = agentic_search.BM25PassageExtractor()
        text = "```python\r\ndef foo():\r\n    return 42\r\n```\r\n\r\nSome following text describing foo in detail."
        passages = extractor.split_passages(text, min_chars=10)
        self.assertEqual(len(passages), 2)
        self.assertTrue(passages[0].startswith("```python"))
        self.assertTrue(passages[0].endswith("```"))

    def test_speculative_fetcher_bounded_concurrency(self) -> None:
        active_workers = 0
        max_active = 0
        lock = threading.Lock()

        def bounded_scrape(url: str, **kwargs):
            nonlocal active_workers, max_active
            with lock:
                active_workers += 1
                max_active = max(max_active, active_workers)
            time.sleep(0.05)
            with lock:
                active_workers -= 1
            return {"content": f"data for {url}"}

        fetcher = agentic_search.SpeculativeFetcher(scrape_func=bounded_scrape, max_workers=2)
        items = [
            agentic_search.SearchResultItem(title=f"T{i}", url=f"https://ex{i}.com", domain=f"ex{i}.com", content="")
            for i in range(5)
        ]
        updated = fetcher.fetch_pages(items, max_fetch=5, timeout=2.0)
        self.assertEqual(len(updated), 5)
        self.assertLessEqual(max_active, 2, "Concurrent worker execution must not exceed max_workers")

    def test_execute_unified_search_none_parameters(self) -> None:
        mock_search = MagicMock()
        mock_search.return_value = {
            "query": "test",
            "results": [{"title": "T", "url": "https://example.com", "content": "C"}],
        }
        mock_scrape = MagicMock()
        mock_scrape.return_value = {"content": "Sample content"}

        res = agentic_search.execute_unified_search(
            query="test",
            search_func=mock_search,
            scrape_func=mock_scrape,
            categories=None,
            engines=None,
            time_range=None,
            mode="fast",
        )
        self.assertNotIn("error", res)
        self.assertEqual(res["results_count"], 1)


if __name__ == "__main__":
    unittest.main()
