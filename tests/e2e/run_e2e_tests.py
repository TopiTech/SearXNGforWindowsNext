#!/usr/bin/env python3
"""SearXNG for Windows Next — Comprehensive 4-Tier E2E Test Suite Runner.

Executes all 4 test tiers:
- Tier 1: Feature Coverage (>=5 tests per feature covering /search, /scrape, /deep_search, /api/retrieval, JSON formats, CLI)
- Tier 2: Boundary & Corner Cases (empty inputs, oversized queries, special chars, SSRF boundaries, invalid combinations)
- Tier 3: Cross-Feature Interactions (format + categories, deep_search + scrape, secret key rotation, CLI mode resolution)
- Tier 4: Real-World Application Scenarios (end-to-end multi-step retrieval and search workflows, concurrency, resilience)

Usage:
    python tests/e2e/run_e2e_tests.py
    python tests/e2e/run_e2e_tests.py --tier 1,2
    python tests/e2e/run_e2e_tests.py --verbose
    python tests/e2e/run_e2e_tests.py --json
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import sys
import time
import unittest
from typing import Any

if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    with contextlib.suppress(Exception):
        reconfig_out = getattr(sys.stdout, "reconfigure", None)
        if callable(reconfig_out):
            reconfig_out(encoding="utf-8", errors="replace")
        reconfig_err = getattr(sys.stderr, "reconfigure", None)
        if callable(reconfig_err):
            reconfig_err(encoding="utf-8", errors="replace")

# Ensure workspace root is in sys.path
TESTS_E2E_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.abspath(os.path.join(TESTS_E2E_DIR, "..", ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from tests.e2e.client import start_test_server, stop_test_server

TIER_MODULES = {
    1: "tests.e2e.test_tier1_feature_coverage",
    2: "tests.e2e.test_tier2_boundary_corner_cases",
    3: "tests.e2e.test_tier3_cross_feature",
    4: "tests.e2e.test_tier4_real_world_scenarios",
}

TIER_NAMES = {
    1: "Tier 1: Feature Coverage",
    2: "Tier 2: Boundary & Corner Cases",
    3: "Tier 3: Cross-Feature Interactions",
    4: "Tier 4: Real-World Application Scenarios",
}


def build_suite(selected_tiers: list[int]) -> tuple[unittest.TestSuite, dict[int, unittest.TestSuite]]:
    """Build unified test suite and per-tier suites."""
    loader = unittest.defaultTestLoader
    master_suite = unittest.TestSuite()
    tier_suites: dict[int, unittest.TestSuite] = {}

    for tier_num in sorted(selected_tiers):
        mod_name = TIER_MODULES.get(tier_num)
        if not mod_name:
            continue
        try:
            tier_suite = loader.loadTestsFromName(mod_name)
            tier_suites[tier_num] = tier_suite
            master_suite.addTest(tier_suite)
        except Exception as exc:
            print(f"[ERROR] Failed to load {mod_name}: {exc}", file=sys.stderr)
            raise

    return master_suite, tier_suites


def run_e2e_tests(
    selected_tiers: list[int] | None = None,
    verbose: bool = False,
    failfast: bool = False,
    as_json: bool = False,
) -> int:
    """Run E2E test suite and return process exit code."""
    tiers = selected_tiers or [1, 2, 3, 4]
    start_time = time.time()

    if not as_json:
        print("=" * 80)
        print(" SearXNG for Windows Next -- 4-Tier E2E Opaque-Box Test Suite")
        print("=" * 80)
        print(f" Target Tiers: {', '.join(f'T{t}' for t in tiers)}")
        print(" Initializing test server environment...")

    base_url = start_test_server()
    if not as_json:
        print(f" Active Base URL: {base_url}")
        print("=" * 80)

    try:
        _, tier_suites = build_suite(tiers)
        total_tests = 0
        total_passed = 0
        total_failed = 0
        total_errors = 0
        tier_results: list[dict[str, Any]] = []

        for tier_num, suite in tier_suites.items():
            tier_title = TIER_NAMES.get(tier_num, f"Tier {tier_num}")
            if not as_json:
                print(f"\n--- Running {tier_title} ---")

            tier_start = time.time()
            verbosity = 2 if verbose else 1
            runner = unittest.TextTestRunner(
                verbosity=0 if as_json else verbosity,
                failfast=failfast,
            )
            result = runner.run(suite)
            tier_elapsed = time.time() - tier_start

            passed_count = result.testsRun - len(result.failures) - len(result.errors)
            failed_count = len(result.failures)
            error_count = len(result.errors)

            total_tests += result.testsRun
            total_passed += passed_count
            total_failed += failed_count
            total_errors += error_count

            tier_info = {
                "tier": tier_num,
                "name": tier_title,
                "tests_run": result.testsRun,
                "passed": passed_count,
                "failed": failed_count,
                "errors": error_count,
                "duration_seconds": round(tier_elapsed, 3),
                "failures": [{"test": f[0].id(), "message": f[1].strip()[:200]} for f in result.failures],
                "error_details": [{"test": e[0].id(), "message": e[1].strip()[:200]} for e in result.errors],
            }
            tier_results.append(tier_info)

            if not as_json:
                status_label = "[PASSED]" if (failed_count == 0 and error_count == 0) else "[FAILED]"
                print(f" {status_label} {tier_title}: {passed_count}/{result.testsRun} passed in {tier_elapsed:.2f}s")

        total_elapsed = time.time() - start_time
        all_passed = total_failed == 0 and total_errors == 0

        if as_json:
            report = {
                "success": all_passed,
                "total_tests": total_tests,
                "passed": total_passed,
                "failed": total_failed,
                "errors": total_errors,
                "duration_seconds": round(total_elapsed, 3),
                "base_url": base_url,
                "tiers": tier_results,
            }
            print(json.dumps(report, indent=2))
        else:
            print("\n" + "=" * 80)
            print(" E2E Test Suite Summary")
            print("=" * 80)
            for tr in tier_results:
                mark = "OK" if (tr["failed"] == 0 and tr["errors"] == 0) else "FAIL"
                print(
                    f" * [{mark}] {tr['name']:<40} : {tr['passed']}/{tr['tests_run']} passed ({tr['duration_seconds']}s)"
                )
            print("-" * 80)
            overall_status = "ALL TESTS PASSED" if all_passed else "TESTS FAILED"
            print(
                f" Status: {overall_status} | Total: {total_tests} | Passed: {total_passed} | Failed: {total_failed} | Errors: {total_errors}"
            )
            print(f" Total Duration: {total_elapsed:.2f}s")
            print("=" * 80)

        return 0 if all_passed else 1

    finally:
        stop_test_server()


def main() -> None:
    """Parse command line arguments and execute test runner."""
    parser = argparse.ArgumentParser(
        description="SearXNG for Windows Next -- 4-Tier E2E Test Suite Runner",
    )
    parser.add_argument(
        "--tier",
        dest="tiers",
        default="",
        help="Comma-separated tier numbers to execute (e.g. '1,2' or '4', default: all)",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable verbose test reporting",
    )
    parser.add_argument(
        "--fail-fast",
        dest="failfast",
        action="store_true",
        help="Stop on first failure",
    )
    parser.add_argument(
        "--json",
        dest="as_json",
        action="store_true",
        help="Output results as JSON summary",
    )

    args = parser.parse_args()
    selected_tiers = None
    if args.tiers:
        selected_tiers = [int(t.strip()) for t in args.tiers.split(",") if t.strip().isdigit()]

    exit_code = run_e2e_tests(
        selected_tiers=selected_tiers,
        verbose=args.verbose,
        failfast=args.failfast,
        as_json=args.as_json,
    )
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
