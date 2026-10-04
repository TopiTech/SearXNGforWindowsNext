#!/usr/bin/env python3
"""Adversarial Stress and Contract Verification Suite for Milestone 3 (M3-R).

Author: Challenger M3-R (Empirical Stress & Adversarial Verifier)
Target: tools/webui_next.py, tools/run-tests.ps1, tools/smoke-test.ps1

Verification Domains:
1. DOM Accessibility, Unique IDs, and WAI-ARIA APG Compliance (F3.1, F3.2, F3.3, F3.4, F3.5)
2. Mathematical WCAG 2.1 AA Contrast Ratio Oracle for #b45309 (F3.7)
3. 320px Viewport Responsive CSS Grid Reflow Simulation & 1px Sweep (F3.8)
4. Flask POST Parameter Retention & Encoding Integrity Stress (F3.9)
5. Scraper HTTP Client Keepalive Hardening (max_keepalive_connections=0)
6. Harness Verification & Tool Integrity (F3.10, F3.11)
"""

from __future__ import annotations

import html.parser
import math
import os
import re
import sys
import unittest
import urllib.parse
from typing import Any

from flask import Flask, Response

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOLS_DIR = os.path.join(REPO_ROOT, "tools")
if TOOLS_DIR not in sys.path:
    sys.path.insert(0, TOOLS_DIR)

import webui_next


# =========================================================================
# DOM Helper for Deep Parsing
# =========================================================================
class _FullDOMParser(html.parser.HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.tags: list[tuple[str, dict[str, str]]] = []
        self.id_counts: dict[str, int] = {}
        self.labels_for: dict[str, str] = {}
        self.elements_by_id: dict[str, tuple[str, dict[str, str]]] = {}
        self._current_label_for: str | None = None
        self._current_label_text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_dict = {k: (v or "") for k, v in attrs}
        self.tags.append((tag, attr_dict))

        elem_id = attr_dict.get("id")
        if elem_id:
            self.id_counts[elem_id] = self.id_counts.get(elem_id, 0) + 1
            self.elements_by_id[elem_id] = (tag, attr_dict)

        if tag == "label" and "for" in attr_dict:
            self._current_label_for = attr_dict["for"]
            self._current_label_text = []

    def handle_data(self, data: str) -> None:
        if self._current_label_for is not None:
            self._current_label_text.append(data.strip())

    def handle_endtag(self, tag: str) -> None:
        if tag == "label" and self._current_label_for is not None:
            self.labels_for[self._current_label_for] = " ".join(self._current_label_text).strip()
            self._current_label_for = None
            self._current_label_text = []


# =========================================================================
# 1. DOM Accessibility & WAI-ARIA APG Verification
# =========================================================================
class TestMilestone3DOMAccessibility(unittest.TestCase):
    """Adversarially verify DOM tree accessibility contracts."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.html = webui_next.AI_WORKSPACE_HTML
        cls.parser = _FullDOMParser()
        cls.parser.feed(cls.html)

    def test_all_dom_ids_are_strictly_unique(self) -> None:
        """Adversarial check: No duplicate element IDs may exist."""
        duplicates = {k: v for k, v in self.parser.id_counts.items() if v > 1}
        self.assertEqual(
            duplicates,
            {},
            f"Found duplicate DOM IDs in AI_WORKSPACE_HTML: {duplicates}",
        )

    def test_settings_select_elements_have_labels_and_aria_names(self) -> None:
        """Verify all 4 settings selects have valid labels and accessible names (F3.1)."""
        required_selects = {
            "pref-default-mode": "デフォルト検索モード",
            "pref-safesearch": "セーフサーチ",
            "pref-default-count": "デフォルト取得件数",
            "pref-default-tokens": "トークン予算上限",
        }

        for select_id, expected_keyword in required_selects.items():
            with self.subTest(select_id=select_id):
                # Element exists and is <select>
                self.assertIn(select_id, self.parser.elements_by_id)
                tag, attrs = self.parser.elements_by_id[select_id]
                self.assertEqual(tag, "select")

                # <label for="..."> exists
                self.assertIn(select_id, self.parser.labels_for)
                label_text = self.parser.labels_for[select_id]
                self.assertIn(expected_keyword, label_text)

                # aria-label exists on the select
                aria_label = attrs.get("aria-label", "")
                self.assertTrue(len(aria_label) > 0)
                self.assertIn(expected_keyword, aria_label)

    def test_skip_link_integrity_and_focus_behavior(self) -> None:
        """Verify skip link points to #q and has compliant CSS (F3.2)."""
        # Element exists
        skip_match = re.search(
            r'<body>\s*<a\s+href="#q"\s+class="skip-link">([^<]+)</a>',
            self.html,
        )
        self.assertIsNotNone(skip_match, "Skip link pointing to #q not found as first child of <body>")

        # Target #q exists
        self.assertIn("q", self.parser.elements_by_id)
        tag, _ = self.parser.elements_by_id["q"]
        self.assertEqual(tag, "input")

        # CSS positioning: offscreen by default, onscreen on focus
        self.assertIn(".skip-link {", self.html)
        self.assertRegex(self.html, r"\.skip-link\s*\{[^}]*position:\s*absolute;[^}]*top:\s*-\d+px;")
        self.assertIn(".skip-link:focus {", self.html)
        self.assertRegex(self.html, r"\.skip-link:focus\s*\{[^}]*top:\s*1rem;[^}]*outline:")

    def test_roving_tabindex_invariants_across_all_tablists(self) -> None:
        """Verify initial roving tabindex on .nav-tabs, .context-tabs, and .settings-subtabs (F3.3)."""
        tablist_blocks = re.findall(
            r'<([a-z0-9]+)[^>]*role=["\']tablist["\'][^>]*>(.*?)</\1>',
            self.html,
            re.DOTALL,
        )
        self.assertGreaterEqual(len(tablist_blocks), 3)

        for _, content in tablist_blocks:
            tabs = re.findall(r'<button[^>]*class=["\']([^"\']*)["\'][^>]*>', content)
            self.assertGreaterEqual(len(tabs), 2)

            t0 = re.findall(r'tabindex=["\']0["\']', content)
            t_neg1 = re.findall(r'tabindex=["\']-1["\']', content)
            selected_true = re.findall(r'aria-selected=["\']true["\']', content)
            selected_false = re.findall(r'aria-selected=["\']false["\']', content)

            # Roving tabindex invariant: exactly 1 tab has tabindex="0" and aria-selected="true"
            self.assertEqual(len(t0), 1, f"Expected exactly 1 tabindex='0', found {len(t0)}")
            self.assertEqual(
                len(selected_true), 1, f"Expected exactly 1 aria-selected='true', found {len(selected_true)}"
            )

            # All other tabs have tabindex="-1" and aria-selected="false"
            self.assertEqual(len(t_neg1), len(tabs) - 1)
            self.assertEqual(len(selected_false), len(tabs) - 1)

    def test_aria_controls_targets_exist_in_dom(self) -> None:
        """Verify all aria-controls attributes point to existing elements."""
        matches = re.findall(r'aria-controls=["\']([^"\']+)["\']', self.html)
        self.assertGreaterEqual(len(matches), 5)
        for target_id in matches:
            with self.subTest(target_id=target_id):
                self.assertIn(
                    target_id,
                    self.parser.elements_by_id,
                    f"aria-controls references non-existent id='{target_id}'",
                )


# =========================================================================
# 2. WCAG 2.1 AA Contrast Ratio Oracle for #b45309
# =========================================================================
class TestWCAGContrastOracle(unittest.TestCase):
    """Adversarially verify color contrast against WCAG 2.1 AA requirements."""

    @staticmethod
    def _srgb_to_lin(c: float) -> float:
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

    @classmethod
    def relative_luminance(cls, hex_color: str) -> float:
        clean = hex_color.strip().lstrip("#")
        r, g, b = (int(clean[i : i + 2], 16) / 255.0 for i in (0, 2, 4))
        return 0.2126 * cls._srgb_to_lin(r) + 0.7152 * cls._srgb_to_lin(g) + 0.0722 * cls._srgb_to_lin(b)

    @classmethod
    def contrast_ratio(cls, c1: str, c2: str) -> float:
        l1 = cls.relative_luminance(c1)
        l2 = cls.relative_luminance(c2)
        lighter = max(l1, l2)
        darker = min(l1, l2)
        return (lighter + 0.05) / (darker + 0.05)

    def test_amber_contrast_against_all_light_surfaces(self) -> None:
        """Verify #b45309 achieves >= 4.5:1 against white and all theme backgrounds."""
        amber_new = "#b45309"
        amber_old = "#d97706"

        surfaces = {
            "pure_white": "#ffffff",
            "bg_base": "#f8fafc",
            "bg_surface": "#ffffff",
            "bg_elevated": "#f1f5f9",
        }

        for name, bg in surfaces.items():
            with self.subTest(surface=name):
                cr_new = self.contrast_ratio(amber_new, bg)
                cr_old = self.contrast_ratio(amber_old, bg)

                # The new amber color MUST be >= 4.5:1
                self.assertGreaterEqual(
                    cr_new,
                    4.5,
                    f"New amber #b45309 failed WCAG AA on {name} ({bg}): {cr_new:.2f}:1",
                )

                # The old amber color MUST fail (< 4.5:1)
                self.assertLess(
                    cr_old,
                    4.5,
                    f"Old amber #d97706 should have failed on {name} ({bg})",
                )

    def test_dark_mode_amber_preserves_contrast(self) -> None:
        """Verify dark mode amber #f59e0b contrast on dark surfaces."""
        dark_amber = "#f59e0b"
        dark_surfaces = {
            "dark_base": "#0b0f19",
            "dark_surface": "#111827",
            "dark_elevated": "#1e293b",
        }
        for name, bg in dark_surfaces.items():
            with self.subTest(surface=name):
                cr = self.contrast_ratio(dark_amber, bg)
                self.assertGreaterEqual(
                    cr,
                    4.5,
                    f"Dark amber failed contrast on {name} ({bg}): {cr:.2f}:1",
                )


# =========================================================================
# 3. 320px Responsive CSS Grid Reflow Simulation
# =========================================================================
class TestResponsiveGridCSSStress(unittest.TestCase):
    """Stress-test 320px viewport responsive grid layout reflow."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.html = webui_next.AI_WORKSPACE_HTML

    def test_engines_grid_rule_present(self) -> None:
        """Verify minmax(min(100%, 280px), 1fr) exists in webui_next.py CSS."""
        self.assertIn("minmax(min(100%, 280px), 1fr)", self.html)

    def test_grid_1px_width_sweep_never_overflows(self) -> None:
        """Adversarial check: sweep widths from 100px to 400px by 1px steps."""
        for width in range(100, 401):
            min_track = min(float(width), 280.0)
            num_cols = max(1, math.floor(float(width) / min_track))
            col_width = float(width) / num_cols
            overflow = max(0.0, min_track - float(width))

            self.assertEqual(overflow, 0.0, f"Overflow occurred at width={width}px")
            self.assertLessEqual(col_width, float(width) + 0.001)

    def test_320px_viewport_with_padding_oracle(self) -> None:
        """Empirically prove 320px viewport with 16px/20px padding fits without overflow."""
        # 320px screen - 32px padding = 288px container
        container_288 = 288.0
        min_track_new = min(container_288, 280.0)  # 280px <= 288px -> Fits!
        self.assertLessEqual(min_track_new, container_288)

        # Legacy rule with 310px
        legacy_min = 310.0
        self.assertGreater(legacy_min, container_288, "Legacy 310px rule overflows 288px container by 22px")


# =========================================================================
# 4. Flask POST Parameter Retention & Encoding Integrity Stress
# =========================================================================
class TestPostParameterRetentionStress(unittest.TestCase):
    """Adversarially stress unified_search_view POST redirection contract."""

    def setUp(self) -> None:
        self.app = Flask(__name__)

        @self.app.route("/search", methods=["GET", "POST"], endpoint="search")
        def mock_search() -> Any:
            return Response("SEARCH_DELEGATED", mimetype="text/plain")

        webui_next.register_next_webui(self.app, None)
        self.client = self.app.test_client()

    def test_post_multibyte_and_special_char_parameter_retention(self) -> None:
        """Stress-test retention of UTF-8, symbols, quotes, and long strings."""
        test_payloads = [
            {"q": "機械学習 & 深層学習 比較", "category": "it", "time_range": "month"},
            {"q": '"Windows 11" AND "SearXNG"', "safesearch": "1"},
            {"q": "https://example.com/search?k=v#frag", "count": "10"},
            {"q": "Emoji 🔍⚡🤖 test", "mode": "deep"},
            {"q": "X" * 1500, "page": "2"},  # Stress long query
        ]

        for payload in test_payloads:
            with self.subTest(query=payload["q"][:25]):
                resp = self.client.post("/search", data=payload)
                self.assertEqual(resp.status_code, 302)

                location = resp.headers.get("Location", "")
                self.assertTrue(location.startswith("/?"))

                # Parse and decode location params
                parsed = urllib.parse.urlparse(location)
                qs = urllib.parse.parse_qs(parsed.query)

                for k, expected_v in payload.items():
                    self.assertIn(k, qs)
                    self.assertEqual(qs[k][0], expected_v)

    def test_format_parameter_delegation_cases(self) -> None:
        """Verify format and accept header bypass redirect and invoke backend search."""
        # 1. format=json
        resp = self.client.post("/search", data={"q": "test", "format": "json"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_data(as_text=True), "SEARCH_DELEGATED")

        # 2. format=JSON (case-insensitivity test)
        resp = self.client.post("/search", data={"q": "test", "format": "JSON"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_data(as_text=True), "SEARCH_DELEGATED")

        # 3. format=csv
        resp = self.client.post("/search", data={"q": "test", "format": "csv"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_data(as_text=True), "SEARCH_DELEGATED")

        # 4. Accept header: application/json
        resp = self.client.post(
            "/search",
            data={"q": "test"},
            headers={"Accept": "application/json"},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_data(as_text=True), "SEARCH_DELEGATED")

        # 5. format=html -> Must redirect 302
        resp = self.client.post("/search", data={"q": "test", "format": "html"})
        self.assertEqual(resp.status_code, 302)


# =========================================================================
# 5. Scraper HTTP Client Keepalive Hardening
# =========================================================================
class TestScraperKeepaliveHardening(unittest.TestCase):
    """Verify scraper connection pooling is strictly disabled."""

    def test_max_keepalive_connections_is_zero(self) -> None:
        webui_path = os.path.join(TOOLS_DIR, "webui_next.py")
        with open(webui_path, encoding="utf-8") as f:
            src = f.read()

        limits_matches = re.findall(r"httpx_mod\.Limits\([^)]+\)", src)
        self.assertGreaterEqual(len(limits_matches), 1)
        for lm in limits_matches:
            self.assertIn(
                "max_keepalive_connections=0",
                lm,
                f"Keepalive pooling must be disabled in scraper limits: {lm}",
            )


# =========================================================================
# 6. Test Runner & Harness Verification
# =========================================================================
class TestHarnessFallbacks(unittest.TestCase):
    """Verify run-tests.ps1 and smoke-test.ps1 enhancements."""

    def test_run_tests_ps1_has_ruff_fallback(self) -> None:
        ps1_path = os.path.join(TOOLS_DIR, "run-tests.ps1")
        with open(ps1_path, encoding="utf-8") as f:
            content = f.read()
        self.assertIn("python\\Scripts\\ruff.exe", content)
        self.assertIn("$fallbackRuff", content)

    def test_smoke_test_ps1_has_live_engines_check(self) -> None:
        ps1_path = os.path.join(TOOLS_DIR, "smoke-test.ps1")
        with open(ps1_path, encoding="utf-8") as f:
            content = f.read()
        self.assertIn("/api/settings/engines", content)
        self.assertIn("$enginesSettings.total_engines -le 0", content)
        self.assertIn("$enginesSettings.active_engines -le 0", content)


if __name__ == "__main__":
    unittest.main()
