#!/usr/bin/env python3
"""Comprehensive regression test suite for SearXNG Next WebUI & Accessibility Compliance.

Validates:
1. Form control labels & ARIA attributes on general settings selects (F3.1).
2. Skip-to-content link markup & CSS rules (F3.2).
3. Tablist roving tabindex pattern on .nav-tabs, .ctx-tab, and .settings-subtab (F3.3).
4. Classic mode scrape drawer button aria-expanded & aria-controls attributes (F3.4).
5. Category filter chips aria-pressed toggle state (F3.5).
6. Empty query user notice with toast & input focus (F3.6).
7. Light theme amber contrast ratio >= 4.5:1 (WCAG 2.1 AA) (F3.7).
8. Responsive 320px engines grid reflow CSS rule (F3.8).
9. Form POST parameter retention on 302 redirect (F3.9).
10. Scraper client keepalive connection pooling disabled (F3.10 / hardening).
11. Test runner Ruff executable fallback check (F3.10).
12. Smoke test harness /api/settings/engines live assertions (F3.11).
"""

from __future__ import annotations

import os
import re
import sys
import unittest
import urllib.parse
from html.parser import HTMLParser
from typing import Any

from flask import Flask, Response

# Ensure tools directory is in sys.path
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

import webui_next


class _HTMLTagCollector(HTMLParser):
    """Minimal HTML parser to collect tags, attributes, and relationships."""

    def __init__(self) -> None:
        super().__init__()
        self.tags: list[tuple[str, dict[str, str]]] = []
        self.labels: dict[str, str] = {}  # for_id -> text or element exists
        self.selects: dict[str, dict[str, str]] = {}  # id -> attrs
        self._current_label_for: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_dict = {k: (v or "") for k, v in attrs}
        self.tags.append((tag, attr_dict))

        if tag == "label" and "for" in attr_dict:
            self._current_label_for = attr_dict["for"]
            self.labels[attr_dict["for"]] = ""
        elif tag == "select" and "id" in attr_dict:
            self.selects[attr_dict["id"]] = attr_dict

    def handle_endtag(self, tag: str) -> None:
        if tag == "label":
            self._current_label_for = None


class TestWebUIAccessibilityFormControls(unittest.TestCase):
    """Test accessibility labeling and attributes on settings form controls (F3.1)."""

    def setUp(self) -> None:
        self.parser = _HTMLTagCollector()
        self.parser.feed(webui_next.AI_WORKSPACE_HTML)

    def test_settings_selects_have_explicit_labels_and_aria_labels(self) -> None:
        target_select_ids = [
            "pref-default-mode",
            "pref-safesearch",
            "pref-default-count",
            "pref-default-tokens",
        ]
        for select_id in target_select_ids:
            with self.subTest(select_id=select_id):
                # 1. Select element must exist with matching ID
                self.assertIn(
                    select_id,
                    self.parser.selects,
                    f"Select with id='{select_id}' not found in HTML",
                )
                select_attrs = self.parser.selects[select_id]

                # 2. An explicit <label for="<id>"> must exist
                self.assertIn(
                    select_id,
                    self.parser.labels,
                    f"No <label for='{select_id}'> found in HTML",
                )

                # 3. Select must have an aria-label for assistive tech
                self.assertTrue(
                    select_attrs.get("aria-label"),
                    f"Select #{select_id} lacks aria-label attribute",
                )

    def test_search_input_has_accessible_name(self) -> None:
        q_match = re.search(r'<input[^>]*id=["\']q["\'][^>]*>', webui_next.AI_WORKSPACE_HTML)
        self.assertIsNotNone(q_match, "Search input #q not found")
        assert q_match is not None
        tag_str = q_match.group(0)
        self.assertIn('aria-label="', tag_str)


class TestWebUISkipToContentLink(unittest.TestCase):
    """Test presence and styling of skip-to-content link (F3.2)."""

    def test_skip_link_element_in_body(self) -> None:
        body_match = re.search(
            r"<body>\s*(<a[^>]+class=[\"'][^\"']*skip-link[^\"']*[\"'][^>]*>.*?</a>)",
            webui_next.AI_WORKSPACE_HTML,
            re.DOTALL,
        )
        self.assertIsNotNone(body_match, "Skip link not found immediately inside <body>")
        assert body_match is not None
        link_html = body_match.group(1)
        self.assertIn('href="#q"', link_html, "Skip link must point to #q")

    def test_skip_link_css_positioning_and_focus(self) -> None:
        html = webui_next.AI_WORKSPACE_HTML
        self.assertIn(".skip-link {", html)
        self.assertIn("top: -999px", html)
        self.assertIn(".skip-link:focus {", html)
        self.assertIn("top: 1rem", html)


class TestWebUITablistRovingTabindex(unittest.TestCase):
    """Test WAI-ARIA tablist roving tabindex initialization and JS handling (F3.3)."""

    def test_nav_tabs_markup_roving_tabindex(self) -> None:
        html = webui_next.AI_WORKSPACE_HTML
        nav_tablist_match = re.search(
            r'<nav[^>]*class=["\'][^"\']*nav-tabs[^"\']*["\'][^>]*role=["\']tablist["\'][^>]*>(.*?)</nav>',
            html,
            re.DOTALL,
        )
        self.assertIsNotNone(nav_tablist_match, "nav-tabs tablist not found")
        assert nav_tablist_match is not None
        tabs_html = nav_tablist_match.group(1)

        active_tab_match = re.search(
            r'<button[^>]*class=["\'][^"\']*active[^"\']*["\'][^>]*tabindex=["\']0["\']',
            tabs_html,
        )
        self.assertIsNotNone(active_tab_match, "Active nav-tab must have tabindex='0'")

        inactive_tab_matches = re.findall(
            r'<button[^>]*class=["\']nav-tab(?!\s*active)[^"\']*["\'][^>]*tabindex=["\']-1["\']',
            tabs_html,
        )
        self.assertGreaterEqual(len(inactive_tab_matches), 3, "All inactive nav-tabs must have tabindex='-1'")

    def test_context_tabs_markup_roving_tabindex(self) -> None:
        html = webui_next.AI_WORKSPACE_HTML
        ctx_tablist_match = re.search(
            r'<div[^>]*class=["\'][^"\']*context-tabs[^"\']*["\'][^>]*role=["\']tablist["\'][^>]*>(.*?)</div>',
            html,
            re.DOTALL,
        )
        self.assertIsNotNone(ctx_tablist_match, "context-tabs tablist not found")
        assert ctx_tablist_match is not None
        tabs_html = ctx_tablist_match.group(1)

        self.assertRegex(tabs_html, r'<button[^>]*class=["\'][^"\']*active[^"\']*["\'][^>]*tabindex=["\']0["\']')
        inactive_matches = re.findall(
            r'<button[^>]*class=["\']ctx-tab(?!\s*active)[^"\']*["\'][^>]*tabindex=["\']-1["\']',
            tabs_html,
        )
        self.assertGreaterEqual(len(inactive_matches), 3)

    def test_settings_subtabs_markup_roving_tabindex(self) -> None:
        html = webui_next.AI_WORKSPACE_HTML
        subtabs_match = re.search(
            r'<div[^>]*class=["\'][^"\']*settings-subtabs[^"\']*["\'][^>]*role=["\']tablist["\'][^>]*>(.*?)</div>',
            html,
            re.DOTALL,
        )
        self.assertIsNotNone(subtabs_match, "settings-subtabs tablist not found")
        assert subtabs_match is not None
        subtabs_html = subtabs_match.group(1)

        self.assertRegex(
            subtabs_html,
            r'id=["\']subtab-engines-btn["\']',
        )
        self.assertRegex(
            subtabs_html,
            r'class=["\'][^"\']*settings-subtab active[^"\']*["\'][^>]*tabindex=["\']0["\']',
        )
        self.assertRegex(
            subtabs_html,
            r'id=["\']subtab-general-btn["\']',
        )
        self.assertRegex(
            subtabs_html,
            r'id=["\']subtab-general-btn["\'][^>]*tabindex=["\']-1["\']|tabindex=["\']-1["\'][^>]*id=["\']subtab-general-btn["\']',
        )

    def test_javascript_tab_switching_updates_roving_tabindex(self) -> None:
        html = webui_next.AI_WORKSPACE_HTML

        # 1. setMode updates tabindex
        set_mode_match = re.search(r"function setMode\(mode\)\s*\{(.*?)\n\s{6}\}", html, re.DOTALL)
        self.assertIsNotNone(set_mode_match, "setMode function not found in JS")
        assert set_mode_match is not None
        set_mode_body = set_mode_match.group(1)
        self.assertIn("t.setAttribute('tabindex', isSelected ? '0' : '-1')", set_mode_body)

        # 2. selectCtxTab updates tabindex
        select_ctx_match = re.search(r"function selectCtxTab\(ctxName\)\s*\{(.*?)\n\s{6}\}", html, re.DOTALL)
        self.assertIsNotNone(select_ctx_match, "selectCtxTab function not found in JS")
        assert select_ctx_match is not None
        select_ctx_body = select_ctx_match.group(1)
        self.assertIn("t.setAttribute('tabindex', isSelected ? '0' : '-1')", select_ctx_body)

        # 3. selectSettingsSubtab updates tabindex
        select_subtab_match = re.search(r"function selectSettingsSubtab\(name\)\s*\{(.*?)\n\s{6}\}", html, re.DOTALL)
        self.assertIsNotNone(select_subtab_match, "selectSettingsSubtab function not found in JS")
        assert select_subtab_match is not None
        subtab_body = select_subtab_match.group(1)
        self.assertIn("engBtn.setAttribute('tabindex', '0')", subtab_body)
        self.assertIn("genBtn.setAttribute('tabindex', '-1')", subtab_body)
        self.assertIn("genBtn.setAttribute('tabindex', '0')", subtab_body)
        self.assertIn("engBtn.setAttribute('tabindex', '-1')", subtab_body)


class TestWebUIClassicScrapeDrawer(unittest.TestCase):
    """Test classic mode scrape drawer ARIA attributes (F3.4)."""

    def test_classic_scrape_button_aria_attributes_in_js(self) -> None:
        html = webui_next.AI_WORKSPACE_HTML
        render_classic_match = re.search(
            r"function renderClassicSearchResults\(.*?\{(.*?)\n\s{6}function",
            html,
            re.DOTALL,
        )
        self.assertIsNotNone(render_classic_match, "renderClassicSearchResults not found")
        assert render_classic_match is not None
        body = render_classic_match.group(1)

        # Initial ARIA setup
        self.assertIn("scrapeBtn.setAttribute('aria-expanded', 'false')", body)
        self.assertIn("scrapeBtn.setAttribute('aria-controls', drawerId)", body)
        self.assertIn("d.id = drawerId", body)

        # On toggle
        self.assertIn("scrapeBtn.setAttribute('aria-expanded', isHidden ? 'true' : 'false')", body)
        self.assertIn("scrapeBtn.setAttribute('aria-expanded', 'true')", body)


class TestWebUICategoryChips(unittest.TestCase):
    """Test category chips aria-pressed attributes (F3.5)."""

    def test_initial_html_category_chips_aria_pressed(self) -> None:
        html = webui_next.AI_WORKSPACE_HTML
        chips_container_match = re.search(
            r'<div[^>]*id=["\']classic-cat-chips["\'][^>]*>(.*?)</div>',
            html,
            re.DOTALL,
        )
        self.assertIsNotNone(chips_container_match, "#classic-cat-chips container not found")
        assert chips_container_match is not None
        chips_html = chips_container_match.group(1)

        active_chip = re.search(
            r'<button[^>]*class=["\'][^"\']*active[^"\']*["\'][^>]*aria-pressed=["\']true["\']',
            chips_html,
        )
        self.assertIsNotNone(active_chip, "Active cat-btn must have aria-pressed='true'")

        inactive_chips = re.findall(
            r'<button[^>]*class=["\']cat-btn(?!\s*active)[^"\']*["\'][^>]*aria-pressed=["\']false["\']',
            chips_html,
        )
        self.assertGreaterEqual(len(inactive_chips), 7, "All inactive cat-btns must have aria-pressed='false'")

    def test_js_category_chips_aria_pressed_updates(self) -> None:
        html = webui_next.AI_WORKSPACE_HTML

        # Click handler in classic mode
        self.assertIn("b.setAttribute('aria-pressed', 'false');", html)
        self.assertIn("btn.setAttribute('aria-pressed', 'true');", html)

        # Settings dynamic category chips
        self.assertIn("allBtn.setAttribute('aria-pressed', 'true');", html)
        self.assertIn("b.setAttribute('aria-pressed', 'false');", html)

        # URL initialization
        self.assertIn("b.setAttribute('aria-pressed', isCurrent ? 'true' : 'false');", html)


class TestWebUIEmptyQueryNotice(unittest.TestCase):
    """Test user feedback on empty query submission (F3.6)."""

    def test_execute_current_action_empty_query_feedback(self) -> None:
        html = webui_next.AI_WORKSPACE_HTML
        exec_match = re.search(r"function executeCurrentAction\(\)\s*\{(.*?)\n\s{6}\}", html, re.DOTALL)
        self.assertIsNotNone(exec_match, "executeCurrentAction function not found")
        assert exec_match is not None
        body = exec_match.group(1)

        self.assertIn("showToast('検索キーワードまたはURLを入力してください');", body)
        self.assertIn("document.getElementById('q').focus();", body)
        self.assertIn("return;", body)


class TestWebUIColorContrast(unittest.TestCase):
    """Test light theme amber contrast ratio (F3.7)."""

    @staticmethod
    def _relative_luminance(hex_color: str) -> float:
        """Calculate relative luminance according to WCAG 2.1 specs."""
        hex_clean = hex_color.lstrip("#")
        r, g, b = (int(hex_clean[i : i + 2], 16) / 255.0 for i in (0, 2, 4))

        def _linearize(c: float) -> float:
            return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

        lr = _linearize(r)
        lg = _linearize(g)
        lb = _linearize(b)
        return 0.2126 * lr + 0.7152 * lg + 0.0722 * lb

    @classmethod
    def _contrast_ratio(cls, hex1: str, hex2: str) -> float:
        l1 = cls._relative_luminance(hex1)
        l2 = cls._relative_luminance(hex2)
        lighter = max(l1, l2)
        darker = min(l1, l2)
        return (lighter + 0.05) / (darker + 0.05)

    def test_light_theme_amber_value(self) -> None:
        html = webui_next.AI_WORKSPACE_HTML
        light_theme_match = re.search(r'\[data-theme=["\']light["\']\]\s*\{(.*?)\}', html, re.DOTALL)
        self.assertIsNotNone(light_theme_match, "Light theme CSS block not found")
        assert light_theme_match is not None
        theme_css = light_theme_match.group(1)

        amber_match = re.search(r"--amber:\s*(#[0-9a-fA-F]{6});", theme_css)
        self.assertIsNotNone(amber_match, "--amber variable not defined in light theme")
        assert amber_match is not None
        amber_hex = amber_match.group(1).lower()

        self.assertEqual(amber_hex, "#b45309", f"Expected #b45309, got {amber_hex}")

    def test_amber_contrast_ratio_against_white(self) -> None:
        amber_new = "#b45309"
        amber_old = "#d97706"
        white = "#ffffff"

        contrast_new = self._contrast_ratio(amber_new, white)
        contrast_old = self._contrast_ratio(amber_old, white)

        self.assertGreaterEqual(
            contrast_new,
            4.5,
            f"New amber {amber_new} contrast ratio {contrast_new:.2f}:1 must meet WCAG AA (>= 4.5:1)",
        )
        self.assertLess(
            contrast_old,
            4.5,
            f"Old amber {amber_old} should have failed WCAG AA (< 4.5:1)",
        )


class TestWebUIResponsiveGrid(unittest.TestCase):
    """Test responsive 320px engines grid minmax CSS rule (F3.8)."""

    def test_engines_grid_minmax_rule(self) -> None:
        html = webui_next.AI_WORKSPACE_HTML
        grid_css_match = re.search(r"\.engines-grid\s*\{(.*?)\}", html, re.DOTALL)
        self.assertIsNotNone(grid_css_match, ".engines-grid CSS block not found")
        assert grid_css_match is not None
        css = grid_css_match.group(1)

        self.assertIn("minmax(min(100%, 280px), 1fr)", css)


class TestWebUIPostParameterRetention(unittest.TestCase):
    """Test retention of POST form parameters in unified_search_view 302 redirect (F3.9)."""

    def setUp(self) -> None:
        self.app = Flask(__name__)

        @self.app.route("/search", methods=["GET", "POST"])
        def search() -> Any:
            return Response("ORIGINAL_SEARCH_INVOKED", mimetype="text/plain")

        webui_next.register_next_webui(self.app, None)
        self.client = self.app.test_client()

    def test_post_search_redirects_302_and_retains_form_parameters(self) -> None:
        form_data = {
            "q": "rust async",
            "category": "it",
            "time_range": "month",
        }
        resp = self.client.post("/search", data=form_data)
        self.assertEqual(resp.status_code, 302)
        location = resp.headers.get("Location", "")
        self.assertTrue(location.startswith("/?"))

        # Parse query params from redirect Location
        parsed = urllib.parse.urlparse(location)
        qs = urllib.parse.parse_qs(parsed.query)

        self.assertEqual(qs.get("q"), ["rust async"])
        self.assertEqual(qs.get("category"), ["it"])
        self.assertEqual(qs.get("time_range"), ["month"])

    def test_post_search_with_format_json_delegates_to_orig_search(self) -> None:
        resp = self.client.post("/search", data={"q": "test", "format": "json"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_data(as_text=True), "ORIGINAL_SEARCH_INVOKED")

    def test_post_search_with_accept_json_header_delegates_to_orig_search(self) -> None:
        resp = self.client.post(
            "/search",
            data={"q": "test"},
            headers={"Accept": "application/json"},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_data(as_text=True), "ORIGINAL_SEARCH_INVOKED")


class TestWebUIScraperLimits(unittest.TestCase):
    """Test scraper HTTP keepalive pooling hardening (F3.10 / keepalive)."""

    def test_scraper_limits_max_keepalive_connections_is_zero(self) -> None:
        src_path = os.path.join(SCRIPT_DIR, "webui_next.py")
        with open(src_path, encoding="utf-8") as f:
            content = f.read()

        match = re.search(r"httpx_mod\.Limits\((.*?)\)", content)
        self.assertIsNotNone(match, "httpx_mod.Limits definition not found in webui_next.py")
        assert match is not None
        limits_args = match.group(1)
        self.assertIn(
            "max_keepalive_connections=0",
            limits_args,
            "In-process scraper client must disable keepalive connections",
        )


class TestRunTestsHarnessRuffFallback(unittest.TestCase):
    """Test tools/run-tests.ps1 Ruff executable fallback (F3.10)."""

    def test_run_tests_ps1_contains_ruff_fallback_path(self) -> None:
        ps1_path = os.path.join(SCRIPT_DIR, "run-tests.ps1")
        with open(ps1_path, encoding="utf-8") as f:
            content = f.read()

        self.assertIn(r'Join-Path $repoRoot "python\Scripts\ruff.exe"', content)
        self.assertIn("Test-Path $fallbackRuff", content)


class TestSmokeTestHarnessEnginesAssertion(unittest.TestCase):
    """Test tools/smoke-test.ps1 live /api/settings/engines assertion (F3.11)."""

    def test_smoke_test_ps1_contains_engines_settings_test(self) -> None:
        ps1_path = os.path.join(SCRIPT_DIR, "smoke-test.ps1")
        with open(ps1_path, encoding="utf-8") as f:
            content = f.read()

        self.assertIn('"$base/api/settings/engines"', content)
        self.assertIn("$enginesSettings.total_engines -le 0", content)
        self.assertIn("$enginesSettings.active_engines -le 0", content)


if __name__ == "__main__":
    unittest.main()
