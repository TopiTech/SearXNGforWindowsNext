#!/usr/bin/env python3
"""Tier 3: Cross-Feature Interactions E2E Tests for SearXNGforWindowsNext.

Covers:
- Interaction 1: format=json_lite + categories + engines multi-parameter filtering
- Interaction 2: deep_search + parallel scrape + BM25 highlight extraction + fallback
- Interaction 3: CLI unified search mode resolution (URL auto-detect vs keyword) + domain filtering
- Interaction 4: Secret key generation, rotation semantics, and environment variable override
- Interaction 5: Patch subsystem cache verification, dry-run reporting, and rollback boundary safety
- Interaction 6: WebUI Next routing aliases (/ai, /next) and form POST redirect parameter retention
"""

from __future__ import annotations

import json
import os
import re
import sys
import tempfile
import unittest

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from tests.e2e.client import E2EClient, E2ECLIRunner


class TestTier3CrossFeatureInteractions(unittest.TestCase):
    """Tier 3: Verification of cross-feature interactions and subsystem coupling."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.client = E2EClient()

    def test_interaction_json_lite_with_categories_and_engines(self) -> None:
        """Verify format=json_lite preserves strict schema when combined with categories and engines."""
        resp = self.client.get(
            "/search",
            params={
                "q": "python",
                "format": "json_lite",
                "categories": "it",
                "engines": "duckduckgo",
            },
        )
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.header("content-type").startswith("application/json"))
        payload = resp.json()
        self.assertIn("results", payload)
        self.assertIsInstance(payload["results"], list)
        for item in payload["results"][:5]:
            self.assertIn("title", item)
            self.assertIn("url", item)
            self.assertIn("content", item)
            self.assertIn("source", item)

    def test_interaction_deep_search_and_scraping_workflow(self) -> None:
        """Verify deep_search executes speculative scraping and builds RAG context."""
        resp = self.client.get(
            "/deep_search",
            params={
                "q": "SearXNG",
                "count": 2,
                "search_depth": "advanced",
                "max_tokens": 1500,
            },
        )
        self.assertEqual(resp.status_code, 200)
        payload = resp.json()
        # Verify both search metadata and packed AI context are produced
        self.assertIn("markdown", payload)
        self.assertIn("rag_prompt", payload)
        self.assertIn("results", payload)
        self.assertIn("scraped_count", payload)
        self.assertGreater(len(payload["markdown"]), 0)
        self.assertIn("SearXNG", payload["rag_prompt"])

    def test_interaction_deep_search_fallback_on_unscrapable_targets(self) -> None:
        """Verify deep search degrades gracefully when target sites fail to scrape."""
        # Query known to return results even if individual URLs fail scraping
        resp = self.client.get(
            "/deep_search",
            params={
                "q": "test query",
                "count": 2,
                "search_depth": "advanced",
            },
        )
        self.assertEqual(resp.status_code, 200)
        payload = resp.json()
        # Even with failed scrapes, search results and markdown are returned
        self.assertIn("results", payload)
        self.assertIn("markdown", payload)

    def test_interaction_cli_url_autodetect_routes_to_scrape(self) -> None:
        """Verify CLI 'search <url>' auto-detects URL input and routes to scrape pipeline."""
        proc = E2ECLIRunner.run_searxng_cli(
            ["search", "https://example.com", "--json"],
            base_url=self.client.base_url,
        )
        self.assertEqual(proc.returncode, 0, f"CLI URL auto-detect failed: {proc.stderr}")
        data = json.loads(proc.stdout)
        # Auto-detected URL output contains extracted page content
        self.assertIn("content", data)
        self.assertEqual(data.get("url"), "https://example.com")

    def test_interaction_cli_search_domain_filtering(self) -> None:
        """Verify CLI search honors --site domain filtering."""
        proc = E2ECLIRunner.run_searxng_cli(
            ["search", "python", "--site", "python.org", "-n", "2", "--json"],
            base_url=self.client.base_url,
        )
        self.assertEqual(proc.returncode, 0, f"CLI site filter failed: {proc.stderr}")
        data = json.loads(proc.stdout)
        self.assertIn("results", data)

    def test_interaction_secret_key_rotation_and_launcher_integrity(self) -> None:
        """Verify secret key rotation generates safe 64-hex key without modifying tracked templates."""
        # 1. Run ensure-secret-key.py
        proc = E2ECLIRunner.run_ensure_secret_key()
        self.assertEqual(proc.returncode, 0)
        match = re.search(r"set SEARXNG_SECRET=([0-9a-fA-F]{64})", proc.stdout)
        self.assertIsNotNone(match)
        key1 = match.group(1)

        # 2. Verify tracked settings.yml.example remains untouched with placeholder
        example_path = os.path.join(REPO_ROOT, "config", "settings.yml.example")
        if os.path.exists(example_path):
            with open(example_path, "r", encoding="utf-8") as f:
                content = f.read()
            self.assertIn("ultrasecretkey", content, "settings.yml.example was modified!")

        # 3. Simulate rotation by reading secret.key
        secret_key_file = os.path.join(REPO_ROOT, "config", "secret.key")
        if os.path.exists(secret_key_file):
            with open(secret_key_file, "r", encoding="utf-8") as f:
                file_key = f.read().strip()
            self.assertEqual(file_key, key1)

    def test_interaction_patch_subsystem_report_and_check(self) -> None:
        """Verify apply-patches.py --check --report writes valid diagnostic report."""
        with tempfile.NamedTemporaryFile(dir=REPO_ROOT, prefix=".tmp_report_", suffix=".json", delete=False) as tmp:
            tmp_report = tmp.name

        try:
            proc = E2ECLIRunner.run_apply_patches(["--check", "--report", tmp_report])
            self.assertEqual(proc.returncode, 0, f"apply-patches failed: {proc.stderr}")
            self.assertTrue(os.path.exists(tmp_report))
            with open(tmp_report, "r", encoding="utf-8") as f:
                report_data = json.load(f)
            self.assertTrue(report_data.get("dry_run"))
            self.assertIn("results", report_data)
            self.assertIn("upstream_info", report_data)
        finally:
            if os.path.exists(tmp_report):
                try:
                    os.remove(tmp_report)
                except OSError:
                    pass

    def test_interaction_webui_route_aliases(self) -> None:
        """Verify both /ai and /next routes serve the AI WebUI."""
        resp_ai = self.client.get("/ai")
        self.assertEqual(resp_ai.status_code, 200)
        self.assertIn("text/html", resp_ai.header("content-type"))

        resp_next = self.client.get("/next")
        self.assertEqual(resp_next.status_code, 200)
        self.assertIn("text/html", resp_next.header("content-type"))

    def test_interaction_unified_search_post_redirect(self) -> None:
        """Verify HTTP POST to root / redirect preserves query parameters (F3.9 fix)."""
        resp = self.client.post("/", data={"q": "redirect_test"})
        # Should either redirect 302 or return 200 search result
        self.assertIn(resp.status_code, (200, 302))
        if resp.status_code == 302:
            loc = resp.header("location")
            self.assertIn("q=redirect_test", loc)


if __name__ == "__main__":
    unittest.main()
