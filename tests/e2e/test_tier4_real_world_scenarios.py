#!/usr/bin/env python3
"""Tier 4: Real-World Application Scenarios E2E Tests for SearXNGforWindowsNext.

Covers:
- Scenario 1: Multi-step AI agent research workflow (retrieval -> citation analysis -> deep scrape -> RAG prompt synthesis)
- Scenario 2: Multi-engine aggregation, ranking, and deduplication synthesis
- Scenario 3: Complete operational maintenance and lifecycle verification
- Scenario 4: Concurrent multi-client agent workload stress test
- Scenario 5: Fault-tolerance and external network error resilience
"""

from __future__ import annotations

import concurrent.futures
import json
import os
import sys
import unittest

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from tests.e2e.client import E2EClient, E2ECLIRunner


class TestTier4RealWorldScenarios(unittest.TestCase):
    """Tier 4: End-to-end verification of realistic production workflows."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.client = E2EClient()

    def test_scenario_multi_step_agent_research_pipeline(self) -> None:
        """Scenario 1: End-to-end multi-step AI coding agent research pipeline."""
        # Step 1: Agent performs structured retrieval
        ret_resp = self.client.get(
            "/api/retrieval",
            params={"q": "FastAPI lifespan async contextmanager", "mode": "fast", "count": 3},
        )
        self.assertEqual(ret_resp.status_code, 200)
        ret_data = ret_resp.json()
        self.assertEqual(ret_data.get("schema_version"), "1.0")
        results = ret_data.get("results", [])

        # Step 2: Agent inspects results and chooses a citation URL to explore further
        target_url = "https://example.com"
        if results and results[0].get("url"):
            candidate = results[0]["url"]
            if candidate.startswith(("http://", "https://")):
                target_url = candidate

        # Step 3: Agent performs deep scrape of the targeted source
        scrape_resp = self.client.get("/scrape", params={"url": target_url})
        self.assertIn(scrape_resp.status_code, (200, 422, 502, 504))

        # Step 4: Agent constructs synthesized RAG prompt using agentic_search utilities
        import agentic_search

        context_text = scrape_resp.json().get("content", "") if scrape_resp.status_code == 200 else "Fallback text"
        rag_prompt = agentic_search.build_rag_prompt("FastAPI lifespan async contextmanager", context_text)
        self.assertIn("FastAPI lifespan async contextmanager", rag_prompt)
        self.assertIn(context_text[:20], rag_prompt)

    def test_scenario_multi_engine_aggregation_and_deduplication(self) -> None:
        """Scenario 2: Multi-engine aggregation produces unique deduplicated results."""
        resp = self.client.get(
            "/search",
            params={"q": "Python asyncio tutorial", "format": "json_lite"},
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        results = data.get("results", [])

        # Check for URL deduplication across the results list
        seen_urls = set()
        duplicates = []
        for r in results:
            u = r.get("url", "").rstrip("/")
            if u:
                if u in seen_urls:
                    duplicates.append(u)
                seen_urls.add(u)

        self.assertEqual(
            len(duplicates),
            0,
            f"Found duplicate URLs in search results: {duplicates}",
        )

    def test_scenario_complete_maintenance_lifecycle(self) -> None:
        """Scenario 3: Complete maintenance lifecycle (secret -> patches -> health -> settings -> CLI)."""
        # 1. Verify instance secret key
        key_proc = E2ECLIRunner.run_ensure_secret_key()
        self.assertEqual(key_proc.returncode, 0)

        # 2. Verify patch status
        patch_proc = E2ECLIRunner.run_apply_patches(["--check", "--json"])
        self.assertEqual(patch_proc.returncode, 0)
        patch_data = json.loads(patch_proc.stdout)
        self.assertEqual(patch_data.get("summary", {}).get("failed_critical", 0), 0)

        # 3. Verify server health
        health_resp = self.client.get("/healthz")
        self.assertEqual(health_resp.status_code, 200)
        self.assertEqual(health_resp.text.strip(), "OK")

        # 4. Verify engines configuration endpoint
        engines_resp = self.client.get("/api/settings/engines")
        self.assertEqual(engines_resp.status_code, 200)
        engines_data = engines_resp.json()
        self.assertIsInstance(engines_data, (dict, list))

        # 5. Verify CLI health check
        cli_proc = E2ECLIRunner.run_searxng_cli(["health", "--json"], base_url=self.client.base_url)
        self.assertEqual(cli_proc.returncode, 0)
        cli_data = json.loads(cli_proc.stdout)
        self.assertTrue(cli_data.get("healthy"))

    def test_scenario_concurrent_multi_client_requests(self) -> None:
        """Scenario 4: Multi-threaded concurrent client traffic load."""

        def _make_req(idx: int) -> int:
            if idx % 3 == 0:
                resp = self.client.get("/search", params={"q": f"test {idx}", "format": "json_lite"})
            elif idx % 3 == 1:
                resp = self.client.get("/scrape", params={"url": "https://example.com"})
            else:
                resp = self.client.get("/api/retrieval", params={"q": f"retrieval {idx}", "mode": "fast", "count": 2})
            return resp.status_code

        # Run 9 concurrent requests simultaneously across 4 worker threads
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
            futures = [executor.submit(_make_req, i) for i in range(9)]
            results = [f.result() for f in concurrent.futures.as_completed(futures)]

        self.assertEqual(len(results), 9)
        for code in results:
            self.assertIn(code, (200, 422, 502, 504))
            self.assertNotEqual(code, 500, "Server returned 500 under concurrent load")

    def test_scenario_external_network_resilience(self) -> None:
        """Scenario 5: External non-existent domain yields clean error without crashing."""
        # Non-existent public domain (must not trigger unhandled internal server error)
        resp = self.client.get("/scrape", params={"url": "https://this-domain-does-not-exist-123456789.com"})
        self.assertIn(resp.status_code, (400, 422, 502, 504))
        self.assertNotEqual(resp.status_code, 500)
        payload = resp.json()
        self.assertIn("error", payload)


if __name__ == "__main__":
    unittest.main()
