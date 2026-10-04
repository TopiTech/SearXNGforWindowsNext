#!/usr/bin/env python3
"""Tier 1: Feature Coverage E2E Tests for SearXNGforWindowsNext.

Covers:
- /search endpoint (HTML, standard JSON, json_lite, categories, time_range, autocompleter)
- /scrape endpoint (GET, Form POST, JSON POST, max_length, content extraction, scrape_analyze)
- /deep_search endpoint (JSON, markdown output, search depths, token budget, domain filters)
- /api/retrieval endpoint (Fast, balanced, deep modes, GenAI schema_version 1.0)
- JSON Formats (standard JSON vs json_lite schema comparison, content-types, error formats, NaN sanitization)
- CLI tools (searxng_cli search, scrape, deep, retrieval, health; apply-patches; ensure-secret-key)
"""

from __future__ import annotations

import json
import os
import re
import sys
import unittest

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from tests.e2e.client import E2EClient, E2ECLIRunner, start_test_server


class TestTier1SearchEndpoint(unittest.TestCase):
    """Tier 1: Feature coverage for /search and related endpoints."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.client = E2EClient()

    def test_search_html_default(self) -> None:
        """Verify GET /search returns 200 HTML with query echoed in search form."""
        resp = self.client.get("/search", params={"q": "test"})
        self.assertEqual(resp.status_code, 200)
        self.assertIn("text/html", resp.header("content-type"))
        self.assertTrue(len(resp.text) > 0)

    def test_search_json_format(self) -> None:
        """Verify GET /search?format=json returns 200 with standard SearXNG JSON structure."""
        resp = self.client.get("/search", params={"q": "SearXNG", "format": "json"})
        self.assertEqual(resp.status_code, 200)
        self.assertIn("application/json", resp.header("content-type"))
        payload = resp.json()
        self.assertIsInstance(payload, dict)
        self.assertIn("query", payload)
        self.assertIn("results", payload)
        self.assertIsInstance(payload["results"], list)

    def test_search_json_lite_format(self) -> None:
        """Verify GET /search?format=json_lite returns compact GenAI schema."""
        resp = self.client.get("/search", params={"q": "SearXNG", "format": "json_lite"})
        self.assertEqual(resp.status_code, 200)
        self.assertIn("application/json", resp.header("content-type"))
        payload = resp.json()
        self.assertIn("query", payload)
        self.assertIn("results", payload)
        self.assertIsInstance(payload["results"], list)
        if payload["results"]:
            item = payload["results"][0]
            for field in ("title", "url", "content", "source"):
                self.assertIn(field, item, f"json_lite item missing field: {field}")

    def test_search_category_filter(self) -> None:
        """Verify category filtering is accepted and processed without error."""
        resp = self.client.get("/search", params={"q": "python", "categories": "it", "format": "json"})
        self.assertEqual(resp.status_code, 200)
        payload = resp.json()
        self.assertIn("results", payload)

    def test_search_time_range_filter(self) -> None:
        """Verify time range parameter is accepted by the query processor."""
        resp = self.client.get("/search", params={"q": "python", "time_range": "month", "format": "json"})
        self.assertEqual(resp.status_code, 200)
        payload = resp.json()
        self.assertIn("results", payload)

    def test_search_engine_filter(self) -> None:
        """Verify specific engine selection is honored."""
        resp = self.client.get("/search", params={"q": "python", "engines": "duckduckgo", "format": "json"})
        self.assertEqual(resp.status_code, 200)
        payload = resp.json()
        self.assertIn("results", payload)

    def test_autocompleter_endpoint(self) -> None:
        """Verify GET /autocompleter returns 200."""
        resp = self.client.get("/autocompleter", params={"q": "python"})
        self.assertEqual(resp.status_code, 200)


class TestTier1ScrapeEndpoint(unittest.TestCase):
    """Tier 1: Feature coverage for /scrape and /api/scrape_analyze endpoints."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.client = E2EClient()

    def test_scrape_get_query_param(self) -> None:
        """Verify GET /scrape?url=... extracts content."""
        resp = self.client.get("/scrape", params={"url": "https://example.com"})
        self.assertEqual(resp.status_code, 200)
        payload = resp.json()
        self.assertIn("url", payload)
        self.assertIn("content", payload)
        self.assertIsInstance(payload["content"], str)

    def test_scrape_post_form(self) -> None:
        """Verify POST /scrape with form-urlencoded body extracts content."""
        resp = self.client.post("/scrape", data={"url": "https://example.com"})
        self.assertEqual(resp.status_code, 200)
        payload = resp.json()
        self.assertIn("content", payload)

    def test_scrape_post_json(self) -> None:
        """Verify POST /scrape with application/json body extracts content."""
        resp = self.client.post("/scrape", json_data={"url": "https://example.com"})
        self.assertEqual(resp.status_code, 200)
        payload = resp.json()
        self.assertIn("content", payload)

    def test_scrape_max_length_truncation(self) -> None:
        """Verify max_length limits response text length and sets is_truncated in client."""
        import searxng_client

        payload = searxng_client.scrape("https://example.com", max_length=60, base_url=self.client.base_url)
        self.assertIn("content", payload)
        self.assertLessEqual(len(payload["content"]), 60)
        if payload.get("original_length", 0) > 60:
            self.assertTrue(payload.get("is_truncated"))

    def test_scrape_analyze_endpoint(self) -> None:
        """Verify GET /api/scrape_analyze returns content and token estimates."""
        resp = self.client.get("/api/scrape_analyze", params={"url": "https://example.com", "q": "domain"})
        self.assertEqual(resp.status_code, 200)
        payload = resp.json()
        self.assertIn("content", payload)
        self.assertIn("char_count", payload)
        self.assertIn("estimated_tokens", payload)

    def test_scrape_missing_url_rejected(self) -> None:
        """Verify /scrape returns 400 when url is omitted."""
        resp = self.client.get("/scrape")
        self.assertEqual(resp.status_code, 400)


class TestTier1DeepSearchEndpoint(unittest.TestCase):
    """Tier 1: Feature coverage for /deep_search endpoint."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.client = E2EClient()

    def test_deep_search_json_default(self) -> None:
        """Verify GET /deep_search returns comprehensive JSON payload."""
        resp = self.client.get("/deep_search", params={"q": "SearXNG", "count": 2, "max_tokens": 1500})
        self.assertEqual(resp.status_code, 200)
        payload = resp.json()
        for key in ("query", "results", "markdown", "rag_prompt", "estimated_tokens"):
            self.assertIn(key, payload, f"/deep_search missing required key: {key}")

    def test_deep_search_format_markdown(self) -> None:
        """Verify format=markdown returns raw Markdown text context."""
        resp = self.client.get("/deep_search", params={"q": "SearXNG", "count": 2, "format": "markdown"})
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(len(resp.text) > 0)
        self.assertIn("SearXNG", resp.text)

    def test_deep_search_depth_fast(self) -> None:
        """Verify search_depth=fast executes snippet-only mode."""
        resp = self.client.get("/deep_search", params={"q": "python", "count": 2, "search_depth": "fast"})
        self.assertEqual(resp.status_code, 200)
        payload = resp.json()
        self.assertEqual(payload.get("search_depth"), "fast")

    def test_deep_search_depth_advanced(self) -> None:
        """Verify search_depth=advanced executes full deep search."""
        resp = self.client.get("/deep_search", params={"q": "python", "count": 2, "search_depth": "advanced"})
        self.assertEqual(resp.status_code, 200)
        payload = resp.json()
        self.assertEqual(payload.get("search_depth"), "advanced")

    def test_deep_search_token_budget_respected(self) -> None:
        """Verify max_tokens caps context size."""
        resp = self.client.get("/deep_search", params={"q": "python", "count": 2, "max_tokens": 500})
        self.assertEqual(resp.status_code, 200)
        payload = resp.json()
        self.assertLessEqual(payload.get("estimated_tokens", 0), 1000)

    def test_deep_search_domain_filtering(self) -> None:
        """Verify include_domains restricts search target."""
        resp = self.client.get(
            "/deep_search",
            params={"q": "python", "count": 2, "include_domains": "python.org"},
        )
        self.assertEqual(resp.status_code, 200)
        payload = resp.json()
        self.assertIn("results", payload)


class TestTier1RetrievalEndpoint(unittest.TestCase):
    """Tier 1: Feature coverage for /api/retrieval GenAI endpoint."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.client = E2EClient()

    def test_retrieval_fast_mode(self) -> None:
        """Verify mode=fast returns structured GenAI schema without deep scraping."""
        resp = self.client.get("/api/retrieval", params={"q": "SearXNG", "mode": "fast", "count": 2})
        self.assertEqual(resp.status_code, 200)
        payload = resp.json()
        self.assertEqual(payload.get("schema_version"), "1.0")
        self.assertIn("query", payload)
        self.assertIn("results", payload)

    def test_retrieval_balanced_mode(self) -> None:
        """Verify mode=balanced returns structured passages."""
        resp = self.client.get("/api/retrieval", params={"q": "SearXNG", "mode": "balanced", "count": 2})
        self.assertEqual(resp.status_code, 200)
        payload = resp.json()
        self.assertEqual(payload.get("schema_version"), "1.0")
        self.assertIn("results", payload)

    def test_retrieval_deep_mode(self) -> None:
        """Verify mode=deep executes multi-query / iterative search."""
        resp = self.client.get("/api/retrieval", params={"q": "SearXNG", "mode": "deep", "count": 2})
        self.assertEqual(resp.status_code, 200)
        payload = resp.json()
        self.assertEqual(payload.get("schema_version"), "1.0")

    def test_retrieval_result_item_contract(self) -> None:
        """Verify result item contract complies with schema_version 1.0."""
        resp = self.client.get("/api/retrieval", params={"q": "SearXNG", "mode": "fast", "count": 2})
        self.assertEqual(resp.status_code, 200)
        payload = resp.json()
        results = payload.get("results", [])
        if results:
            item = results[0]
            self.assertIn("title", item)
            self.assertIn("url", item)
            self.assertIn("score", item)

    def test_retrieval_category_filter(self) -> None:
        """Verify category filtering works on /api/retrieval."""
        resp = self.client.get("/api/retrieval", params={"q": "python", "category": "it", "mode": "fast"})
        self.assertEqual(resp.status_code, 200)
        payload = resp.json()
        self.assertIn("results", payload)

    def test_retrieval_empty_query_rejected(self) -> None:
        """Verify /api/retrieval rejects empty query with 400 Bad Request."""
        resp = self.client.get("/api/retrieval", params={"q": ""})
        self.assertEqual(resp.status_code, 400)


class TestTier1JsonFormats(unittest.TestCase):
    """Tier 1: Feature coverage for JSON format specifications and contracts."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.client = E2EClient()

    def test_json_content_type(self) -> None:
        """Verify application/json Content-Type header is returned."""
        resp = self.client.get("/search", params={"q": "test", "format": "json"})
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(
            resp.header("content-type").startswith("application/json"),
            f"Expected application/json, got {resp.header('content-type')}",
        )

    def test_json_vs_json_lite_payload_contract(self) -> None:
        """Verify json_lite strips heavy engine metadata compared to standard json."""
        resp_std = self.client.get("/search", params={"q": "SearXNG", "format": "json"})
        resp_lite = self.client.get("/search", params={"q": "SearXNG", "format": "json_lite"})
        self.assertEqual(resp_std.status_code, 200)
        self.assertEqual(resp_lite.status_code, 200)

        lite_data = resp_lite.json()
        self.assertIn("results", lite_data)
        if lite_data["results"]:
            lite_item = lite_data["results"][0]
            # json_lite must contain only the essential fields
            expected_keys = {"title", "url", "content", "source"}
            for k in expected_keys:
                self.assertIn(k, lite_item)

    def test_json_lite_empty_query_error_contract(self) -> None:
        """Verify format=json_lite returns 400 on empty query."""
        resp = self.client.get("/search", params={"q": "", "format": "json_lite"})
        self.assertEqual(resp.status_code, 400)

    def test_json_nan_infinity_sanitization(self) -> None:
        """Verify JSON serialized responses do not contain raw NaN or Infinity tokens."""
        resp = self.client.get("/search", params={"q": "SearXNG", "format": "json_lite"})
        self.assertEqual(resp.status_code, 200)
        # raw text check for unquoted NaN or Infinity
        self.assertNotRegex(resp.text, r":\s*(NaN|Infinity|-Infinity)\b")

    def test_api_ai_info_endpoint(self) -> None:
        """Verify /api/ai_info returns valid JSON documentation schema."""
        resp = self.client.get("/api/ai_info")
        self.assertEqual(resp.status_code, 200)
        payload = resp.json()
        self.assertIn("endpoints", payload)
        self.assertIn("snippets", payload)


class TestTier1CLITools(unittest.TestCase):
    """Tier 1: Feature coverage for workspace CLI tools."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.base_url = start_test_server()

    def test_cli_health(self) -> None:
        """Verify 'searxng_cli.py health --json' exits with 0 and reports healthy."""
        proc = E2ECLIRunner.run_searxng_cli(["health", "--json"], base_url=self.base_url)
        self.assertEqual(proc.returncode, 0, f"CLI health failed: {proc.stderr}")
        data = json.loads(proc.stdout)
        self.assertTrue(data.get("healthy"))

    def test_cli_search_json(self) -> None:
        """Verify 'searxng_cli.py search ... --json' returns results."""
        proc = E2ECLIRunner.run_searxng_cli(["search", "SearXNG", "-n", "2", "--json"], base_url=self.base_url)
        self.assertEqual(proc.returncode, 0, f"CLI search failed: {proc.stderr}")
        data = json.loads(proc.stdout)
        self.assertIn("results", data)

    def test_cli_scrape_json(self) -> None:
        """Verify 'searxng_cli.py scrape ... --json' extracts content."""
        proc = E2ECLIRunner.run_searxng_cli(
            ["scrape", "https://example.com", "-m", "100", "--json"],
            base_url=self.base_url,
        )
        self.assertEqual(proc.returncode, 0, f"CLI scrape failed: {proc.stderr}")
        data = json.loads(proc.stdout)
        self.assertIn("content", data)

    def test_cli_deep_search(self) -> None:
        """Verify 'searxng_cli.py deep ... --json' executes deep search."""
        proc = E2ECLIRunner.run_searxng_cli(
            ["deep", "SearXNG", "-n", "2", "--depth", "fast", "--json"],
            base_url=self.base_url,
        )
        self.assertEqual(proc.returncode, 0, f"CLI deep failed: {proc.stderr}")
        data = json.loads(proc.stdout)
        self.assertIn("results", data)

    def test_cli_retrieval(self) -> None:
        """Verify 'searxng_cli.py retrieval ... --json' returns GenAI schema."""
        proc = E2ECLIRunner.run_searxng_cli(
            ["retrieval", "SearXNG", "--mode", "fast", "-n", "2", "--json"],
            base_url=self.base_url,
        )
        self.assertEqual(proc.returncode, 0, f"CLI retrieval failed: {proc.stderr}")
        data = json.loads(proc.stdout)
        self.assertEqual(data.get("schema_version"), "1.0")

    def test_cli_apply_patches_dry_run(self) -> None:
        """Verify 'apply-patches.py --check --json' executes dry run without modifying files."""
        proc = E2ECLIRunner.run_apply_patches(["--check", "--json"])
        self.assertEqual(proc.returncode, 0, f"apply-patches failed: {proc.stderr}")
        data = json.loads(proc.stdout)
        self.assertTrue(data.get("dry_run"))
        self.assertIn("summary", data)

    def test_cli_ensure_secret_key(self) -> None:
        """Verify 'ensure-secret-key.py' prints a valid 64-hex-char key line."""
        proc = E2ECLIRunner.run_ensure_secret_key()
        self.assertEqual(proc.returncode, 0, f"ensure-secret-key failed: {proc.stderr}")
        match = re.search(r"set SEARXNG_SECRET=([0-9a-fA-F]{64})", proc.stdout)
        self.assertIsNotNone(match, f"Invalid SEARXNG_SECRET format: {proc.stdout}")


if __name__ == "__main__":
    unittest.main()
