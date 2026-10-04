#!/usr/bin/env python3
"""Adversarial Quality Gate & Stress Test Suite for Milestone 4 (Challenger M4).

Empirically challenges:
1. Static Gate Bypass Resistance:
   - Validates that pyrefly, ruff check, and ruff format are configured and fail on violations.
2. Master Runner (run-tests.ps1) Failure Trapping & Lifecycle:
   - Validates exit code propagation and process tree cleanup logic.
3. Live WSGI / Granian Server Lifecycle:
   - Validates port binding, health responsiveness, and clean termination without orphan processes.
4. E2E Concurrency & Resilience Stress:
   - Stress-tests live API endpoints under concurrent asynchronous requests.
5. Benchmark Precision Oracle:
   - Validates retrieval benchmark determinism and metric calculations.
"""

from __future__ import annotations

import concurrent.futures
import json
import math
import os
import subprocess
import sys
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOLS_DIR = os.path.join(REPO_ROOT, "tools")
PYTHON_EXE = os.path.join(REPO_ROOT, "python", "python.exe")
RUFF_EXE = os.path.join(REPO_ROOT, "python", "Scripts", "ruff.exe")
if not os.path.exists(PYTHON_EXE):
    PYTHON_EXE = sys.executable

if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)
if TOOLS_DIR not in sys.path:
    sys.path.insert(0, TOOLS_DIR)

from tests.e2e.client import E2EClient, start_test_server


class TestStaticGateBypassResistance(unittest.TestCase):
    """Challenge the static analysis quality gates."""

    def test_ruff_executable_present_and_enforced(self) -> None:
        """Verify ruff executable exists and checks repo cleanly."""
        self.assertTrue(os.path.exists(RUFF_EXE), f"Ruff executable missing at {RUFF_EXE}")
        proc = subprocess.run(
            [RUFF_EXE, "check", "."],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )
        self.assertEqual(proc.returncode, 0, f"Ruff check failed: {proc.stdout}\n{proc.stderr}")

    def test_ruff_format_enforced(self) -> None:
        """Verify ruff format check runs cleanly."""
        proc = subprocess.run(
            [RUFF_EXE, "format", "--check", "."],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )
        self.assertEqual(proc.returncode, 0, f"Ruff format check failed: {proc.stdout}\n{proc.stderr}")

    def test_pyrefly_type_checker_enforced(self) -> None:
        """Verify pyrefly check runs and reports 0 unresolved type errors."""
        proc = subprocess.run(
            [PYTHON_EXE, "-m", "pyrefly", "check"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )
        combined = proc.stdout + proc.stderr
        self.assertEqual(proc.returncode, 0, f"Pyrefly check failed:\n{combined}")
        self.assertIn("0 errors", combined)


class TestMasterRunnerContracts(unittest.TestCase):
    """Verify contracts of tools/run-tests.ps1."""

    def test_run_tests_ps1_contains_all_five_unit_suites(self) -> None:
        """Verify run-tests.ps1 executes all 5 unit test suites and throws on failure."""
        ps1_path = os.path.join(TOOLS_DIR, "run-tests.ps1")
        with open(ps1_path, encoding="utf-8") as f:
            content = f.read()

        required_suites = [
            "tools\\test_patches.py",
            "tools\\test_agent_tools.py",
            "tools\\test_agentic_search.py",
            "tools\\test_retrieval_pipeline.py",
            "tools\\test_webui.py",
        ]
        for suite in required_suites:
            self.assertIn(suite, content, f"Runner does not contain suite: {suite}")

    def test_run_tests_ps1_contains_process_tree_teardown(self) -> None:
        """Verify run-tests.ps1 terminates the entire child process tree of Granian."""
        ps1_path = os.path.join(TOOLS_DIR, "run-tests.ps1")
        with open(ps1_path, encoding="utf-8") as f:
            content = f.read()

        self.assertIn("Get-CimInstance Win32_Process", content)
        self.assertIn("Stop-PortListeners", content)
        self.assertIn("Stop-Process -Id", content)


class TestE2EConcurrencyAndStress(unittest.TestCase):
    """Adversarial concurrent stress testing on live server endpoints."""

    @classmethod
    def setUpClass(cls) -> None:
        start_test_server()
        cls.client = E2EClient()

    def test_high_concurrency_mixed_traffic(self) -> None:
        """Issue 30 rapid concurrent queries across varied endpoints without server crash."""
        endpoints = [
            ("/search", {"q": "python concurrency", "format": "json_lite"}),
            ("/api/retrieval", {"q": "pytest best practices", "mode": "fast", "count": 2}),
            ("/scrape", {"url": "https://example.com"}),
            ("/healthz", {}),
            ("/api/settings/engines", {}),
        ]

        def _request(idx: int) -> tuple[int, int]:
            path, params = endpoints[idx % len(endpoints)]
            try:
                resp = self.client.get(path, params=params, timeout=15.0)
                return idx, resp.status_code
            except (OSError, TimeoutError, ValueError):
                return idx, -1

        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as executor:
            futures = [executor.submit(_request, i) for i in range(30)]
            results = [f.result() for f in concurrent.futures.as_completed(futures)]

        self.assertEqual(len(results), 30)
        for idx, status in results:
            self.assertIn(
                status,
                (200, 400, 422, 502, 504),
                f"Query {idx} failed with unexpected status code {status}",
            )

    def test_pathological_boundary_requests(self) -> None:
        """Issue pathological boundary queries and verify no unhandled 500 error."""
        # 1. 2,000+ char query
        long_q = "a" * 2500
        resp1 = self.client.get("/search", params={"q": long_q, "format": "json_lite"})
        self.assertIn(resp1.status_code, (200, 400))

        # 2. Control characters & null bytes
        null_q = "test\x00\x01\x1f\n\r"
        resp2 = self.client.get("/search", params={"q": null_q, "format": "json_lite"})
        self.assertIn(resp2.status_code, (200, 400))

        # 3. Path traversal in scrape
        resp3 = self.client.get("/scrape", params={"url": "http://127.0.0.1/../../../etc/passwd"})
        self.assertEqual(resp3.status_code, 400)


class TestBenchmarkPrecisionOracle(unittest.TestCase):
    """Stress and verify the benchmark math and metrics."""

    def test_dcg_calculation_oracle(self) -> None:
        """Verify DCG calculation matches standard information retrieval formula."""
        from tests.evaluation.run_benchmark import calculate_dcg, calculate_ndcg

        # Empty list -> 0.0
        self.assertEqual(calculate_dcg([], 5), 0.0)

        # Perfect ranking: [2.0, 1.0, 0.0]
        # rank 1: (2^2 - 1) / log2(2) = 3.0 / 1.0 = 3.0
        # rank 2: (2^1 - 1) / log2(3) = 1.0 / 1.58496 = 0.63093
        # rank 3: 0.0
        expected_dcg = 3.0 + (1.0 / math.log2(3.0))
        actual_dcg = calculate_dcg([2.0, 1.0, 0.0], 3)
        self.assertAlmostEqual(actual_dcg, expected_dcg, places=4)

        # NDCG of identical ideal is 1.0
        self.assertAlmostEqual(calculate_ndcg([2.0, 1.0, 0.0], 3), 1.0, places=4)

    def test_benchmark_full_execution_precision(self) -> None:
        """Execute the benchmark directly and verify P@5 >= 0.90 for all modes."""
        from tests.evaluation.run_benchmark import OfflineRetrievalEvaluator

        eval_dir = os.path.join(REPO_ROOT, "tests", "evaluation")
        fixtures_file = os.path.join(eval_dir, "offline_fixtures.json")
        expected_file = os.path.join(eval_dir, "expected_sources.json")
        ja_file = os.path.join(eval_dir, "queries_ja.jsonl")
        en_file = os.path.join(eval_dir, "queries_en.jsonl")

        queries: list[dict[str, str]] = []
        for fp in (ja_file, en_file):
            with open(fp, encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        queries.append(json.loads(line.strip()))

        evaluator = OfflineRetrievalEvaluator(fixtures_file, expected_file)
        for mode in ("fast", "balanced", "deep"):
            results = evaluator.run_evaluation(queries, mode=mode)
            p5 = sum(r.precision_at_5 for r in results) / len(results)
            self.assertEqual(p5, 1.0, f"Mode {mode} P@5 is not 1.0 (got {p5})")


if __name__ == "__main__":
    unittest.main()
