#!/usr/bin/env python3
"""Tier 2: Boundary & Corner Cases E2E Tests for SearXNGforWindowsNext.

Covers:
- Empty & Whitespace inputs (empty query, whitespace query, missing url, empty url)
- Oversized queries & buffers (>2000 chars, ReDoS pathological inputs, huge max_length/count/tokens)
- Unicode edge cases & special characters (Japanese/CJK, exact-phrase quotes, HTML injection, emojis, regex meta-chars)
- SSRF boundaries & non-routable targets (loopback, 0.0.0.0, cloud metadata, RFC1918, IPv6, schemes, obfuscated IPs, unicode dots, invalid ports, reserved TLDs)
- Invalid input combinations (malformed JSON, invalid data types, unknown formats, negative pageno, invalid CLI args)
"""

from __future__ import annotations

import json
import os
import sys
import time
import unittest

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from tests.e2e.client import E2EClient, E2ECLIRunner


class TestTier2EmptyWhitespaceInputs(unittest.TestCase):
    """Tier 2: Verification of empty and whitespace-only input handling."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.client = E2EClient()

    def test_search_empty_query_rejected(self) -> None:
        """Verify GET /search?q=&format=json_lite returns 400 Bad Request."""
        resp = self.client.get("/search", params={"q": "", "format": "json_lite"})
        self.assertEqual(resp.status_code, 400)

    def test_search_whitespace_query_handled(self) -> None:
        """Verify GET /search with only whitespace is safely handled without 500 error."""
        resp = self.client.get("/search", params={"q": "     ", "format": "json_lite"})
        self.assertIn(resp.status_code, (200, 400))
        self.assertNotEqual(resp.status_code, 500)

    def test_client_whitespace_query_rejected(self) -> None:
        """Verify client-side validation rejects whitespace query with clear error."""
        import searxng_client

        res = searxng_client.search("   ", base_url=self.client.base_url)
        self.assertIn("error", res)

    def test_scrape_empty_url_rejected(self) -> None:
        """Verify GET /scrape with empty url returns 400 Bad Request."""
        resp = self.client.get("/scrape", params={"url": ""})
        self.assertEqual(resp.status_code, 400)

    def test_scrape_whitespace_url_rejected(self) -> None:
        """Verify POST /scrape with whitespace-only url returns 400 Bad Request."""
        resp = self.client.post("/scrape", json_data={"url": "   "})
        self.assertEqual(resp.status_code, 400)

    def test_deep_search_empty_query_rejected(self) -> None:
        """Verify GET /deep_search with empty query returns 400 Bad Request."""
        resp = self.client.get("/deep_search", params={"q": ""})
        self.assertEqual(resp.status_code, 400)

    def test_retrieval_empty_query_rejected(self) -> None:
        """Verify GET /api/retrieval with whitespace query returns 400 Bad Request."""
        resp = self.client.get("/api/retrieval", params={"q": "   "})
        self.assertEqual(resp.status_code, 400)

    def test_cli_search_empty_query_handled(self) -> None:
        """Verify CLI search with empty query outputs error or returns non-zero."""
        proc = E2ECLIRunner.run_searxng_cli(["search", "", "--json"])
        # Either non-zero exit or json output indicating error
        if proc.returncode == 0:
            data = json.loads(proc.stdout)
            self.assertTrue("error" in data or len(data.get("results", [])) == 0)


class TestTier2OversizedQueriesAndBuffers(unittest.TestCase):
    """Tier 2: Verification of oversized query handling and buffer bounds."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.client = E2EClient()

    def test_search_oversized_query_gracefully_handled(self) -> None:
        """Verify query exceeding 2,000 characters is handled without 500 error."""
        oversized = "python " * 400  # 2,800 characters
        resp = self.client.get("/search", params={"q": oversized, "format": "json_lite"})
        self.assertIn(resp.status_code, (200, 400))
        self.assertNotEqual(resp.status_code, 500)

    def test_redos_pathological_input_terminates_promptly(self) -> None:
        """Verify pathological input on comparison regex terminates promptly (F1.1 fix)."""
        # Pathological repetitive string that could trigger catastrophic backtracking
        pathological = "vs " * 2000 + "target"
        start_t = time.time()
        resp = self.client.get("/search", params={"q": pathological, "format": "json_lite"}, timeout=10.0)
        elapsed = time.time() - start_t
        self.assertLess(elapsed, 5.0, f"Query execution took {elapsed:.2f}s, potential ReDoS detected")
        self.assertIn(resp.status_code, (200, 400))

    def test_scrape_extreme_max_length_safely_bounded(self) -> None:
        """Verify extreme max_length value is safely processed without memory exhaustion."""
        resp = self.client.get("/api/scrape_analyze", params={"url": "https://example.com", "max_length": "99999999"})
        self.assertEqual(resp.status_code, 200)

    def test_retrieval_extreme_count_clamped(self) -> None:
        """Verify /api/retrieval clamps extreme count parameter safely."""
        resp = self.client.get("/api/retrieval", params={"q": "SearXNG", "count": 999999, "mode": "fast"})
        self.assertEqual(resp.status_code, 200)
        payload = resp.json()
        self.assertLessEqual(len(payload.get("results", [])), 50)

    def test_deep_search_extreme_tokens_clamped(self) -> None:
        """Verify /deep_search with huge max_tokens executes without crashing."""
        resp = self.client.get("/deep_search", params={"q": "SearXNG", "count": 2, "max_tokens": 1000000})
        self.assertEqual(resp.status_code, 200)


class TestTier2UnicodeAndSpecialCharacters(unittest.TestCase):
    """Tier 2: Verification of Unicode, CJK, quotes, and special characters."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.client = E2EClient()

    def test_search_japanese_cjk_query(self) -> None:
        """Verify Japanese UTF-8 query returns 200 with proper encoding."""
        resp = self.client.get("/search", params={"q": "検索エンジンのテスト", "format": "json_lite"})
        self.assertEqual(resp.status_code, 200)
        payload = resp.json()
        self.assertIn("query", payload)
        self.assertEqual(payload["query"], "検索エンジンのテスト")

    def test_search_exact_phrase_quotes_retained(self) -> None:
        """Verify exact-phrase double quotes are retained (F1.3 fix)."""
        query_str = '"machine learning"'
        resp = self.client.get("/search", params={"q": query_str, "format": "json_lite"})
        self.assertEqual(resp.status_code, 200)
        payload = resp.json()
        self.assertIn("machine learning", payload.get("query", ""))

    def test_search_html_injection_escaped(self) -> None:
        """Verify HTML/XSS injection attempts are sanitized and do not trigger 500."""
        xss_query = '<script>alert("xss")</script><img src=x onerror=alert(1)>'
        resp = self.client.get("/search", params={"q": xss_query})
        self.assertEqual(resp.status_code, 200)
        self.assertNotIn('<script>alert("xss")</script>', resp.text)

    def test_search_emojis_and_surrogates(self) -> None:
        """Verify emoji characters in query do not cause encoding failures."""
        emoji_query = "🔍 AI search 🚀 2026 ✨"
        resp = self.client.get("/search", params={"q": emoji_query, "format": "json_lite"})
        self.assertEqual(resp.status_code, 200)
        payload = resp.json()
        self.assertEqual(payload.get("query"), emoji_query)

    def test_search_regex_and_shell_metacharacters(self) -> None:
        """Verify regex and shell special characters execute safely."""
        meta_query = "c++ regex (a+)+ [0-9] *? $ \\ / | & ; ` ~"
        resp = self.client.get("/search", params={"q": meta_query, "format": "json_lite"})
        self.assertEqual(resp.status_code, 200)


class TestTier2SSRFBoundaries(unittest.TestCase):
    """Tier 2: Comprehensive SSRF protection verification (20+ test vectors)."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.client = E2EClient()

    def _assert_blocked(self, url: str, label: str) -> None:
        """Helper to assert that a target URL is blocked with HTTP 400."""
        resp = self.client.get("/scrape", params={"url": url})
        self.assertEqual(
            resp.status_code,
            400,
            f"SSRF bypass detected for {label} ({url}): expected 400, got {resp.status_code}",
        )

    def test_ssrf_loopback_ipv4(self) -> None:
        """Verify IPv4 loopback addresses are blocked."""
        self._assert_blocked("http://127.0.0.1/", "127.0.0.1 loopback")
        self._assert_blocked("http://127.0.0.2/", "127.0.0.2 loopback")

    def test_ssrf_reserved_hostnames(self) -> None:
        """Verify localhost and reserved hostnames are blocked."""
        self._assert_blocked("http://localhost/", "localhost")
        self._assert_blocked("http://127.0.0.1.nip.io/", "nip.io loopback hostname")
        self._assert_blocked("http://local/", "bare reserved host local")
        self._assert_blocked("http://internal/", "bare reserved host internal")

    def test_ssrf_unspecified_address(self) -> None:
        """Verify 0.0.0.0 is blocked."""
        self._assert_blocked("http://0.0.0.0/", "0.0.0.0 unspecified")

    def test_ssrf_cloud_metadata_link_local(self) -> None:
        """Verify cloud metadata / link-local addresses are blocked."""
        self._assert_blocked("http://169.254.169.254/", "AWS/GCP metadata")
        self._assert_blocked("http://[fe80::1]/", "IPv6 link-local")

    def test_ssrf_private_rfc1918(self) -> None:
        """Verify RFC1918 private IPv4 ranges are blocked."""
        self._assert_blocked("http://10.0.0.1/", "10.0.0.0/8 private")
        self._assert_blocked("http://172.16.0.1/", "172.16.0.0/12 private")
        self._assert_blocked("http://192.168.1.1/", "192.168.0.0/16 private")

    def test_ssrf_ipv6_loopback(self) -> None:
        """Verify IPv6 loopback variants are blocked."""
        self._assert_blocked("http://[::1]/", "IPv6 ::1 loopback")
        self._assert_blocked("http://[::ffff:127.0.0.1]/", "IPv4-mapped IPv6 loopback")
        self._assert_blocked("http://[::1]:80/", "IPv6 loopback with port")

    def test_ssrf_disallowed_schemes(self) -> None:
        """Verify non-HTTP(S) schemes are blocked."""
        self._assert_blocked("file:///etc/passwd", "file:// scheme")
        self._assert_blocked("gopher://127.0.0.1:6379/", "gopher:// scheme")
        self._assert_blocked("ftp://example.com/test", "ftp:// scheme")
        self._assert_blocked("ws://example.com/socket", "ws:// scheme")
        self._assert_blocked("javascript:alert(1)", "javascript: scheme")
        self._assert_blocked("data:text/html,test", "data: scheme")

    def test_ssrf_obfuscated_numeric_hosts(self) -> None:
        """Verify decimal, octal, and shorthand IP representations are blocked."""
        self._assert_blocked("http://2130706433/", "decimal integer loopback")
        self._assert_blocked("http://127.1/", "shorthand loopback")
        self._assert_blocked("http://0177.0.0.1/", "octal dotted loopback")
        self._assert_blocked("http://017700000001/", "octal un-dotted loopback")
        self._assert_blocked("http://999999999999/", "invalid numeric host")

    def test_ssrf_unicode_dot_hosts(self) -> None:
        """Verify fullwidth, ideographic, and halfwidth Unicode dots are normalized and blocked."""
        self._assert_blocked("http://127%E3%80%820%E3%80%820%E3%80%821/", "ideographic dot loopback")
        self._assert_blocked("http://127%EF%BC%8E0%EF%BC%8E0%EF%BC%8E1/", "fullwidth dot loopback")
        self._assert_blocked("http://127%EF%BD%A10%EF%BD%A10%EF%BD%A11/", "halfwidth dot loopback")

    def test_ssrf_invalid_ports(self) -> None:
        """Verify port 0 and out-of-range ports are blocked."""
        self._assert_blocked("http://example.com:0/", "port 0")
        self._assert_blocked("http://example.com:70000/", "port 70000")

    def test_ssrf_reserved_tlds(self) -> None:
        """Verify special and reserved TLDs are blocked."""
        self._assert_blocked("http://router.localdomain/", ".localdomain")
        self._assert_blocked("http://gateway.intranet/", ".intranet")
        self._assert_blocked("http://nas.private/", ".private")
        self._assert_blocked("http://router.arpa/", ".arpa")


class TestTier2InvalidInputCombinations(unittest.TestCase):
    """Tier 2: Verification of invalid input combinations and error handling."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.client = E2EClient()

    def test_scrape_post_malformed_json_syntax(self) -> None:
        """Verify malformed JSON body returns 400."""
        resp = self.client.post("/scrape", headers={"Content-Type": "application/json"}, data=None)
        self.assertIn(resp.status_code, (400, 415))

    def test_scrape_post_non_string_url(self) -> None:
        """Verify non-string URL type (e.g. integer or list) returns 400."""
        resp = self.client.post("/scrape", json_data={"url": 12345})
        self.assertEqual(resp.status_code, 400)

        resp2 = self.client.post("/scrape", json_data={"url": ["http://example.com"]})
        self.assertEqual(resp2.status_code, 400)

    def test_search_unknown_format_handled(self) -> None:
        """Verify unknown format parameter does not crash the server with 500."""
        resp = self.client.get("/search", params={"q": "test", "format": "unknown_format_xyz"})
        self.assertNotEqual(resp.status_code, 500)

    def test_search_negative_pageno_handled(self) -> None:
        """Verify negative pageno parameter does not crash the server."""
        resp = self.client.get("/search", params={"q": "test", "pageno": "-5", "format": "json_lite"})
        self.assertIn(resp.status_code, (200, 400))
        self.assertNotEqual(resp.status_code, 500)

    def test_cli_unknown_subcommand_exits_nonzero(self) -> None:
        """Verify CLI exits with non-zero exit code on invalid subcommand."""
        proc = E2ECLIRunner.run_searxng_cli(["nonexistent_subcommand"])
        self.assertNotEqual(proc.returncode, 0)


if __name__ == "__main__":
    unittest.main()
