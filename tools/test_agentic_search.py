#!/usr/bin/env python3
"""Unit tests for the Agentic Deep Search orchestrator (Exa/Tavily-like logic)."""

from __future__ import annotations

import os
import sys
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
            agentic_search.QueryOptimizer.classify_intent("Python traceback TypeError: NoneType object is not callable"),
            agentic_search.QueryOptimizer.classify_intent("React 19 useActionState hook migration"),
        ]
        for intent in intents:
            self.assertEqual(intent, "code")

    def test_classify_intent_academic(self) -> None:
        intent = agentic_search.QueryOptimizer.classify_intent("diffusion model transformer attention mechanism paper arxiv")
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
            {"title": "Python Docs", "url": "https://docs.python.org/3/asyncio.html", "content": "Official asyncio docs"},
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
            agentic_search.SearchResultItem(title="Page 1", url="https://site1.com", domain="site1.com", content="snip1"),
            agentic_search.SearchResultItem(title="Page 2", url="https://site2-fail.com", domain="site2.com", content="snip2"),
        ]

        updated = fetcher.fetch_pages(items, max_fetch=2)
        self.assertEqual(len(updated), 2)
        self.assertTrue(updated[0].is_scraped)
        self.assertEqual(updated[0].full_content, "Content of https://site1.com")
        self.assertFalse(updated[1].is_scraped)
        self.assertIn("Connection error", updated[1].scrape_error)


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


if __name__ == "__main__":
    unittest.main()
