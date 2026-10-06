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
from unittest.mock import patch

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

    def test_light_theme_muted_text_contrast(self) -> None:
        """Light theme --text-muted must meet WCAG AA (>= 4.5:1) against light backgrounds."""
        html = webui_next.AI_WORKSPACE_HTML
        light_theme_match = re.search(r'\[data-theme=["\']light["\']\]\s*\{(.*?)\}', html, re.DOTALL)
        self.assertIsNotNone(light_theme_match, "Light theme CSS block not found")
        assert light_theme_match is not None
        theme_css = light_theme_match.group(1)

        muted_match = re.search(r"--text-muted:\s*(#[0-9a-fA-F]{6});", theme_css)
        self.assertIsNotNone(muted_match, "--text-muted variable not defined in light theme")
        assert muted_match is not None
        muted_hex = muted_match.group(1).lower()
        self.assertEqual(muted_hex, "#475569", f"Expected #475569, got {muted_hex}")

        for bg in ("#ffffff", "#f8fafc", "#f1f5f9"):
            ratio = self._contrast_ratio(muted_hex, bg)
            self.assertGreaterEqual(
                ratio,
                4.5,
                f"--text-muted {muted_hex} on {bg} contrast ratio {ratio:.2f}:1 must meet WCAG AA (>= 4.5:1)",
            )

        # The old value must stay non-compliant on #f1f5f9 so a regression is detectable.
        old_ratio = self._contrast_ratio("#64748b", "#f1f5f9")
        self.assertLess(old_ratio, 4.5, f"Old muted #64748b on #f1f5f9 should fail AA, got {old_ratio:.2f}:1")

    def test_dark_theme_muted_text_contrast(self) -> None:
        """Dark theme --text-muted must meet WCAG AA (>= 4.5:1) against dark backgrounds."""
        html = webui_next.AI_WORKSPACE_HTML
        dark_match = re.search(r':root,\s*\[data-theme=["\']dark["\']\]\s*\{(.*?)\}', html, re.DOTALL)
        self.assertIsNotNone(dark_match, "Dark theme CSS block not found")
        assert dark_match is not None
        theme_css = dark_match.group(1)

        muted_match = re.search(r"--text-muted:\s*(#[0-9a-fA-F]{6});", theme_css)
        self.assertIsNotNone(muted_match, "--text-muted variable not defined in dark theme")
        assert muted_match is not None
        muted_hex = muted_match.group(1).lower()
        self.assertEqual(muted_hex, "#8494ac", f"Expected #8494ac, got {muted_hex}")

        for bg in ("#0b0f19", "#111827", "#1e293b"):
            ratio = self._contrast_ratio(muted_hex, bg)
            self.assertGreaterEqual(
                ratio,
                4.5,
                f"--text-muted {muted_hex} on {bg} contrast ratio {ratio:.2f}:1 must meet WCAG AA (>= 4.5:1)",
            )

        # The old value must stay non-compliant on #1e293b so a regression is detectable.
        old_ratio = self._contrast_ratio("#64748b", "#1e293b")
        self.assertLess(old_ratio, 4.5, f"Old muted #64748b on #1e293b should fail AA, got {old_ratio:.2f}:1")

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


class TestWebUIEmojiElimination(unittest.TestCase):
    """Test elimination of visual emoji clutter across AI_WORKSPACE_HTML."""

    def test_no_emojis_in_workspace_html(self) -> None:
        html = webui_next.AI_WORKSPACE_HTML
        emoji_pattern = re.compile(
            "["
            "\U0001f1e0-\U0001f1ff"
            "\U0001f300-\U0001f5ff"
            "\U0001f600-\U0001f64f"
            "\U0001f680-\U0001f6ff"
            "\U0001f700-\U0001f77f"
            "\U0001f780-\U0001f7ff"
            "\U0001f800-\U0001f8ff"
            "\U0001f900-\U0001f9ff"
            "\U0001fa00-\U0001fa6f"
            "\U0001fa70-\U0001faff"
            "\U00002702-\U000027b0"
            "\U00002600-\U000026ff"
            "]+",
            flags=re.UNICODE,
        )
        found = emoji_pattern.findall(html)
        self.assertEqual(
            found,
            [],
            f"AI_WORKSPACE_HTML should not contain visual emojis; found: {set(found)}",
        )


class TestWebUISVGAccessibility(unittest.TestCase):
    """Test SVG icons accessibility and class definitions."""

    def test_all_svg_icons_have_aria_hidden(self) -> None:
        html = webui_next.AI_WORKSPACE_HTML
        svg_tags = re.findall(r"<svg[^>]*>", html)
        self.assertGreater(len(svg_tags), 5, "Should define inline SVG icons")
        for tag in svg_tags:
            self.assertIn(
                'aria-hidden="true"',
                tag,
                f"SVG icon missing aria-hidden='true': {tag}",
            )

    def test_ui_icon_css_rules_exist(self) -> None:
        html = webui_next.AI_WORKSPACE_HTML
        self.assertIn(".ui-icon {", html)
        self.assertIn("stroke: currentColor;", html)
        self.assertIn("fill: none;", html)


class TestWebUIBrowserHistorySync(unittest.TestCase):
    """Test browser URL and history state synchronization."""

    def test_url_sync_and_popstate_bindings_in_js(self) -> None:
        html = webui_next.AI_WORKSPACE_HTML
        self.assertIn("function updateUrlState(", html)
        self.assertIn("history.pushState(", html)
        self.assertIn("history.replaceState(", html)
        self.assertIn("window.addEventListener('popstate'", html)


class TestWebUIAbortController(unittest.TestCase):
    """Test AbortController for cancelable requests to prevent race conditions."""

    def test_abort_controller_management_in_js(self) -> None:
        html = webui_next.AI_WORKSPACE_HTML
        self.assertIn("var currentAbortController = null;", html)
        self.assertIn("function cancelPendingRequest()", html)
        self.assertIn("currentAbortController.abort()", html)
        self.assertIn("new AbortController()", html)
        self.assertIn("signal: signal", html)


class TestWebUISkeletonLoading(unittest.TestCase):
    """Test skeleton loading cards and pulse animation."""

    def test_skeleton_markup_and_css(self) -> None:
        html = webui_next.AI_WORKSPACE_HTML
        self.assertIn(".skeleton-card {", html)
        self.assertIn("skeleton-pulse", html)
        self.assertIn("function renderSkeletonCards(", html)


class TestWebUIAutocompleter(unittest.TestCase):
    """Test autocompleter suggestion dropdown and aria attributes."""

    def test_suggest_box_markup_and_attributes(self) -> None:
        html = webui_next.AI_WORKSPACE_HTML
        self.assertIn('id="suggest-box"', html)
        self.assertIn('role="listbox"', html)
        self.assertIn('aria-autocomplete="list"', html)
        self.assertIn('aria-controls="suggest-box"', html)
        self.assertIn("fetch('/autocompleter?q='", html)
        self.assertIn("extractSuggestions(", html)
        self.assertIn("'X-Requested-With': 'XMLHttpRequest'", html)

    def test_combobox_aria_pattern(self) -> None:
        """Input must expose combobox pattern with expand state and activedescendant sync (F3.x)."""
        html = webui_next.AI_WORKSPACE_HTML
        self.assertIn('role="combobox"', html)
        self.assertIn('aria-expanded="false"', html)
        self.assertIn("aria-expanded', 'true'", html)
        self.assertIn("aria-activedescendant", html)
        self.assertIn("'suggest-opt-'", html)
        self.assertIn("aria-selected", html)
        self.assertIn("function setActiveSuggestAria()", html)
        self.assertGreaterEqual(html.count("setActiveSuggestAria()"), 3)

    def test_autocomplete_general_settings_markup(self) -> None:
        html = webui_next.AI_WORKSPACE_HTML
        self.assertIn('id="pref-autocomplete"', html)
        self.assertIn('value="duckduckgo"', html)
        self.assertIn('value="google"', html)
        self.assertIn('value="off"', html)
        self.assertIn("sxng_pref_autocomplete", html)

    def test_autocompleter_endpoint_with_app(self) -> None:
        app = Flask("test_autocompleter_app")
        webui_next.register_next_webui(app, None)
        client = app.test_client()

        # Empty query returns []
        resp_empty = client.get("/autocompleter?q=")
        self.assertEqual(resp_empty.status_code, 200)
        self.assertEqual(resp_empty.get_json(), [])

        # Disabled via cookie returns []
        client.set_cookie("autocomplete", "off")
        resp_off = client.get("/autocompleter?q=claude", headers={"X-Requested-With": "XMLHttpRequest"})
        self.assertEqual(resp_off.status_code, 200)
        self.assertEqual(resp_off.get_json(), [])

        # Disabled via backend query param returns []
        resp_param_off = client.get(
            "/autocompleter?q=claude&backend=off", headers={"X-Requested-With": "XMLHttpRequest"}
        )
        self.assertEqual(resp_param_off.status_code, 200)
        self.assertEqual(resp_param_off.get_json(), [])


class TestWebUIQueryHistory(unittest.TestCase):
    """Test search query history persistence via localStorage."""

    def test_recent_searches_markup_and_storage(self) -> None:
        html = webui_next.AI_WORKSPACE_HTML
        self.assertIn('id="recent-searches-wrap"', html)
        self.assertIn("sxng_query_history", html)
        self.assertIn("saveQueryHistory(", html)
        self.assertIn("renderQueryHistory(", html)


class TestWebUIUnsavedChangesAlert(unittest.TestCase):
    """Test unsaved changes banner and beforeunload alert."""

    def test_unsaved_banner_and_listener(self) -> None:
        html = webui_next.AI_WORKSPACE_HTML
        self.assertIn('id="unsaved-bar"', html)
        self.assertIn('id="btn-discard-unsaved"', html)
        self.assertIn('id="btn-save-unsaved"', html)
        self.assertIn("window.addEventListener('beforeunload'", html)


class TestWebUIMarkdownPreview(unittest.TestCase):
    """Test Markdown preview tab and renderer."""

    def test_preview_tab_and_container(self) -> None:
        html = webui_next.AI_WORKSPACE_HTML
        self.assertIn('data-ctx="preview"', html)
        self.assertIn('id="ctx-preview"', html)
        self.assertIn("function renderSimpleMarkdown(", html)

    def test_markdown_preview_link_sanitization_and_bracket_escaping(self) -> None:
        """Verify markdown link sanitization prevents quote breakout and citations escape brackets."""
        html = webui_next.AI_WORKSPACE_HTML
        # Double-backslash bracket escaping regression
        self.assertIn(r"split('[').join('\\[').split(']').join('\\]')", html)
        # Markdown link sanitization routing through safeHttpUrl
        self.assertIn(r"safeHttpUrl(rawUrl.replace(/&amp;/g, '&'))", html)

    def test_markdown_preview_code_block_tokenization_and_list_grouping(self) -> None:
        """Verify code blocks and inline code are protected by placeholders and list items are grouped."""
        html = webui_next.AI_WORKSPACE_HTML
        self.assertIn("@@CODE_BLOCK_", html)
        self.assertIn("@@INLINE_CODE_", html)
        self.assertIn("'<ul>' + listItems.join('') + '</ul>'", html)


class TestWebUIClassicPaginationAndListenerHygiene(unittest.TestCase):
    """Test classic pagination state synchronization and resilient listener attachment."""

    def test_pagination_state_sync_on_init(self) -> None:
        html = webui_next.AI_WORKSPACE_HTML
        self.assertIn("state.classicPage = initPage", html)
        self.assertIn("runClassicSearch(initQ, initPage)", html)

    def test_add_listener_null_guard_helper(self) -> None:
        html = webui_next.AI_WORKSPACE_HTML
        self.assertIn("function addListener(id, event, fn)", html)
        self.assertIn("el.addEventListener(event, fn)", html)


class TestWebUIRouteParameterForwarding(unittest.TestCase):
    """Test query and payload parameter forwarding (base_url, timeout) in API routes."""

    def setUp(self) -> None:
        self.app = Flask(__name__)
        webui_next.register_next_webui(self.app, None)
        self.client = self.app.test_client()

    def test_deep_search_forwards_base_url_and_timeout(self) -> None:
        recorded_args: dict[str, Any] = {}

        def mock_deep(*args: Any, **kwargs: Any) -> dict[str, Any]:
            recorded_args.update(kwargs)
            return {"query": kwargs.get("query"), "results": []}

        with patch.object(webui_next, "execute_server_deep_search", side_effect=mock_deep):
            resp = self.client.get("/deep_search?q=test_query&base_url=http://127.0.0.1:9999&timeout=12.5")
            self.assertEqual(resp.status_code, 200)
            self.assertEqual(recorded_args.get("base_url"), "http://127.0.0.1:9999")
            self.assertEqual(recorded_args.get("timeout"), 12.5)

    def test_retrieval_api_forwards_base_url_and_timeout(self) -> None:
        recorded_args: dict[str, Any] = {}

        def mock_ret(*args: Any, **kwargs: Any) -> dict[str, Any]:
            recorded_args.update(kwargs)
            return {"query": kwargs.get("query"), "schema_version": "1.0", "results": []}

        with patch.object(webui_next, "execute_server_retrieval_search", side_effect=mock_ret):
            resp = self.client.post(
                "/api/retrieval",
                json={"q": "rag test", "base_url": "http://127.0.0.1:7777", "timeout": 8.0},
            )
            self.assertEqual(resp.status_code, 200)
            self.assertEqual(recorded_args.get("base_url"), "http://127.0.0.1:7777")
            self.assertEqual(recorded_args.get("timeout"), 8.0)

    def test_scrape_analyze_forwards_timeout(self) -> None:
        recorded_args: dict[str, Any] = {}

        def mock_sc(*args: Any, **kwargs: Any) -> dict[str, Any]:
            recorded_args.update(kwargs)
            return {"url": kwargs.get("url"), "content": "mock text", "error": ""}

        with patch.object(webui_next, "execute_scrape_analyze", side_effect=mock_sc):
            resp = self.client.get("/api/scrape_analyze?url=https://example.com/article&timeout=14.0")
            self.assertEqual(resp.status_code, 200)
            self.assertEqual(recorded_args.get("timeout"), 14.0)


class TestWebUIRateLimiting(unittest.TestCase):
    """Test per-client token-bucket rate limiting on expensive API routes (F3.12)."""

    LIMITED_DUMMY = "/_rl_limited_dummy"
    FREE_DUMMY = "/_rl_free_dummy"

    def setUp(self) -> None:
        self.app = Flask(__name__)
        self.app.route(self.LIMITED_DUMMY)(self._limited_view)
        self.app.route(self.FREE_DUMMY)(self._free_view)
        self._original_paths = webui_next._RATE_LIMITED_PATHS
        webui_next._RATE_LIMITED_PATHS = frozenset({self.LIMITED_DUMMY})
        self._original_buckets = dict(webui_next._RATE_BUCKETS)
        webui_next.register_next_webui(self.app, None)
        self.client = self.app.test_client()

    def _limited_view(self) -> str:
        return "ok"

    def _free_view(self) -> str:
        return "ok"

    def tearDown(self) -> None:
        webui_next._RATE_LIMITED_PATHS = self._original_paths
        webui_next._RATE_BUCKETS.clear()
        webui_next._RATE_BUCKETS.update(self._original_buckets)

    def test_rate_limited_paths_cover_expensive_routes(self) -> None:
        self.assertIn(
            "/deep_search",
            self._original_paths,
            "/deep_search must be rate limited (expensive network fan-out)",
        )
        self.assertIn(
            "/api/search",
            self._original_paths,
            "/api/search must be rate limited (expensive network fan-out)",
        )
        self.assertIn(
            "/api/retrieval",
            self._original_paths,
            "/api/retrieval must be rate limited (expensive network fan-out)",
        )
        self.assertIn(
            "/api/scrape_analyze",
            self._original_paths,
            "/api/scrape_analyze must be rate limited (expensive HTML scraping)",
        )

    def _exhaust_then_verify_429(self, path: str, max_requests: int) -> None:
        """Send requests until 429 appears, and assert it does within bounds."""
        codes = []
        for _ in range(max_requests):
            resp = self.client.get(path)
            codes.append(resp.status_code)
            if resp.status_code == 429:
                break
        self.assertIn(
            429,
            codes,
            f"Expected a 429 response within {max_requests} requests to {path}",
        )
        last_resp = self.client.get(path)
        self.assertEqual(last_resp.status_code, 429)
        self.assertIn("Retry-After", last_resp.headers)
        self.assertGreaterEqual(int(last_resp.headers["Retry-After"]), 1)

    def test_rate_limit_bounded_burst_then_429(self) -> None:
        self._exhaust_then_verify_429(self.LIMITED_DUMMY, 25)

    def test_rate_limit_recovers_after_refill(self) -> None:
        # Drain the bucket
        for _ in range(25):
            resp = self.client.get(self.LIMITED_DUMMY)
            if resp.status_code == 429:
                break
        # Force token refill by back-dating the bucket timestamp
        buckets = webui_next._RATE_BUCKETS
        self.assertTrue(buckets, "Expected at least one rate bucket to exist")
        for bucket in buckets.values():
            bucket.updated -= 100.0  # 100s * 0.5 tokens/s = +50 tokens (capped)
        resp = self.client.get(self.LIMITED_DUMMY)
        self.assertEqual(resp.status_code, 200)

    def test_rate_limit_scope_is_only_limited_routes(self) -> None:
        # Unlisted (cheap) routes must never be rate limited and must not consume tokens
        tokens_before = [bucket.tokens for bucket in webui_next._RATE_BUCKETS.values()]
        for _ in range(30):
            resp = self.client.get(self.FREE_DUMMY)
            self.assertEqual(resp.status_code, 200)
        tokens_after = [bucket.tokens for bucket in webui_next._RATE_BUCKETS.values()]
        self.assertEqual(tokens_before, tokens_after, "Free routes must not consume rate-limit tokens")

    def test_rate_limit_ignores_forwarded_for_header(self) -> None:
        # Forged X-Forwarded-For must not grant fresh buckets (identity = REMOTE_ADDR)
        seen_429 = False
        for i in range(30):
            resp = self.client.get(
                self.LIMITED_DUMMY,
                headers={"X-Forwarded-For": f"10.0.0.{i}"},
            )
            if resp.status_code == 429:
                seen_429 = True
                break
        self.assertTrue(seen_429, "Spoofed XFF headers must not bypass the limiter")


class TestWebUIImageGrid(unittest.TestCase):
    """Test responsive image gallery grid for image category."""

    def test_image_grid_css_and_handling(self) -> None:
        html = webui_next.AI_WORKSPACE_HTML
        self.assertIn(".image-results-grid {", html)
        self.assertIn(".image-card-thumb", html)
        self.assertIn("state.classicCategory === 'images'", html)


class TestWebUIVideoCards(unittest.TestCase):
    """Test dedicated video cards layout for video category."""

    def test_video_cards_css_and_handling(self) -> None:
        html = webui_next.AI_WORKSPACE_HTML
        self.assertIn(".video-results-list {", html)
        self.assertIn(".video-card {", html)
        self.assertIn(".video-thumb-wrap", html)
        self.assertIn("state.classicCategory === 'videos'", html)


class TestWebUIAccessibilityAndResponsiveHygiene(unittest.TestCase):
    """Test HTML5 validity, screen-reader compliance, and responsive touch layout."""

    def test_no_headings_nested_inside_labels(self) -> None:
        """HTML5 phrasing content rule: <label> elements must not wrap <h1-6> headings."""
        html = webui_next.AI_WORKSPACE_HTML
        # Match <label ...> ... <h[1-6]> pattern
        heading_inside_label = re.search(r"<label\b[^>]*>\s*<h[1-6]\b", html, re.IGNORECASE)
        self.assertIsNone(
            heading_inside_label,
            f"Found invalid heading nested inside <label>: {heading_inside_label.group(0) if heading_inside_label else ''}",
        )

    def test_mobile_tabs_horizontal_touch_scroll(self) -> None:
        """Verify nav-tabs and context-tabs have touch-friendly overflow-x scrolling for narrow viewports."""
        html = webui_next.AI_WORKSPACE_HTML
        # Verify overflow-x: auto and touch scrolling are present in tab styles
        self.assertIn("overflow-x: auto", html)
        self.assertIn("-webkit-overflow-scrolling: touch", html)


class TestWebUIMarkdownAndSanitization(unittest.TestCase):
    """Test Markdown preview rendering resilience and image URI sanitization."""

    def test_render_simple_markdown_preserves_dollar_signs_in_bundle(self) -> None:
        """Verify renderSimpleMarkdown uses function replacement to prevent $ pattern substitution."""
        html = webui_next.AI_WORKSPACE_HTML
        self.assertIn("function () { return codeBlocks[k]; }", html)
        self.assertIn("function () { return inlineCodes[j]; }", html)

    def test_safe_image_url_patterns_in_bundle(self) -> None:
        """Verify safeImageUrl helper handles raster data:image and rejects insecure schemes including SVG."""
        html = webui_next.AI_WORKSPACE_HTML
        self.assertIn("function safeImageUrl(url)", html)
        self.assertIn(r"data:image\/(?:png|jpeg|jpg|webp|gif);base64,[a-z0-9+/=]+", html)
        # Verify SVG data URI is explicitly excluded from allowed regex to prevent XSS
        self.assertNotIn(r"svg\+xml", html)

    def test_node_execution_markdown_and_image_safety(self) -> None:
        """If node is available, execute JS functions directly to verify edge-case outputs."""
        import json
        import shutil
        import subprocess

        node_bin = shutil.which("node")
        if not node_bin:
            self.skipTest("node runtime not found in PATH")

        js_code = """
        function escapeHtml(s) {
          return String(s == null ? '' : s)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#039;');
        }
        function safeHttpUrl(s) {
          if (!s) return '#';
          if (!/^https?:\\/\\//i.test(s)) return '#';
          try {
            var parsed = new URL(s);
            if (parsed.protocol === 'http:' || parsed.protocol === 'https:') {
              return parsed.href;
            }
          } catch (e) {}
          return '#';
        }
        function safeImageUrl(url) {
          var s = String(url == null ? '' : url).trim();
          if (!s) return '';
          if (/^data:image\\/(?:png|jpeg|jpg|webp|gif);base64,[a-z0-9+/=]+$/i.test(s)) {
            return s;
          }
          var http = safeHttpUrl(s);
          return (http === '#') ? '' : http;
        }
        function renderSimpleMarkdown(md) {
          if (!md) return '<p style="color:var(--text-muted);">(empty)</p>';
          var text = escapeHtml(md).replace(/\\r\\n/g, '\\n');
          var codeBlocks = [];
          text = text.replace(/```([a-zA-Z0-9_-]*)\\n([\\s\\S]*?)```/g, function (_, lang, code) {
            var token = '@@CODE_BLOCK_' + codeBlocks.length + '@@';
            codeBlocks.push('<pre><code class="lang-' + lang + '">' + code + '</code></pre>');
            return '\\n\\n' + token + '\\n\\n';
          });
          var inlineCodes = [];
          text = text.replace(/`([^`]+)`/g, function (_, code) {
            var token = '@@INLINE_CODE_' + inlineCodes.length + '@@';
            inlineCodes.push('<code>' + code + '</code>');
            return token;
          });
          var rawBlocks = text.split(/\\n{2,}/);
          var htmlBlocks = [];
          for (var i = 0; i < rawBlocks.length; i++) {
            var block = rawBlocks[i].trim();
            if (!block) continue;
            if (/^@@CODE_BLOCK_\\d+@@$/.test(block)) {
              htmlBlocks.push(block);
              continue;
            }
            htmlBlocks.push('<p>' + block.replace(/\\n/g, '<br>') + '</p>');
          }
          var fullHtml = htmlBlocks.join('\\n');
          for (var k = 0; k < codeBlocks.length; k++) {
            fullHtml = fullHtml.replace('@@CODE_BLOCK_' + k + '@@', function () { return codeBlocks[k]; });
          }
          for (var j = 0; j < inlineCodes.length; j++) {
            fullHtml = fullHtml.replace('@@INLINE_CODE_' + j + '@@', function () { return inlineCodes[j]; });
          }
          return fullHtml;
        }

        const outMd = renderSimpleMarkdown('```bash\\necho $1 $2 $& $$ $price\\n```\\nPrice is `$100` and `$PATH`');
        const imgSafe1 = safeImageUrl('https://example.com/pic.jpg');
        const imgSafe2 = safeImageUrl('data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=');
        const imgBad1 = safeImageUrl('javascript:alert(1)');
        const imgBad2 = safeImageUrl('data:text/html;base64,PHNjcmlwdD4=');

        console.log(JSON.stringify({
          md: outMd,
          imgSafe1: imgSafe1,
          imgSafe2: imgSafe2,
          imgBad1: imgBad1,
          imgBad2: imgBad2,
        }));
        """
        proc = subprocess.run([node_bin, "-e", js_code], capture_output=True, text=True, check=True)
        data = json.loads(proc.stdout)
        self.assertIn("echo $1 $2 $&amp; $$ $price", data["md"])
        self.assertIn("<code>$100</code>", data["md"])
        self.assertIn("<code>$PATH</code>", data["md"])
        self.assertEqual(data["imgSafe1"], "https://example.com/pic.jpg")
        self.assertTrue(data["imgSafe2"].startswith("data:image/png;base64,"))
        self.assertEqual(data["imgBad1"], "")
        self.assertEqual(data["imgBad2"], "")


class TestWebUIAccessibilityDeepSearchAndKeybindings(unittest.TestCase):
    """Test accessibility patterns and keyboard shortcuts in WebUI."""

    def test_deep_search_drawer_has_aria_controls(self) -> None:
        """Deep search scrape drawer button must set aria-controls attribute to drawer id."""
        html = webui_next.AI_WORKSPACE_HTML
        self.assertIn("deep-scrape-drawer-", html)
        self.assertIn("scrapeBtn.setAttribute('aria-controls', drawerId)", html)

    def test_escape_key_resets_aria_expanded(self) -> None:
        """Escape key listener must reset aria-expanded to false on expanded buttons."""
        html = webui_next.AI_WORKSPACE_HTML
        self.assertIn("b.setAttribute('aria-expanded', 'false')", html)

    def test_enter_navigation_safe_window_open(self) -> None:
        """Opening card link via Enter key must use noopener,noreferrer."""
        html = webui_next.AI_WORKSPACE_HTML
        self.assertIn("window.open(link.href, '_blank', 'noopener,noreferrer')", html)

    def test_error_handlers_clear_telemetry_bar(self) -> None:
        """Unified, Classic, and Scrape error handlers must remove/hide telemetry bars while preserving static bar."""
        html = webui_next.AI_WORKSPACE_HTML
        self.assertIn("if (oldBar) oldBar.remove();", html)
        self.assertIn("telBar.classList.remove('visible');", html)
        self.assertIn(".telemetry-bar:not(#telemetry-bar)", html)

    def test_copy_buttons_have_aria_label_and_data_action(self) -> None:
        """Deep, classic, video, and image result actions must declare ARIA and data-action attributes."""
        html = webui_next.AI_WORKSPACE_HTML
        self.assertIn("copyItemBtn.setAttribute('aria-label', '引用をコピー')", html)
        self.assertIn("copyItemBtn.setAttribute('data-action', 'copy-citation')", html)
        self.assertIn("copyBtn.setAttribute('aria-label', '引用をコピー')", html)
        self.assertIn("copyBtn.setAttribute('data-action', 'copy-citation')", html)
        self.assertIn("copyBtn.setAttribute('aria-label', '動画URLをコピー')", html)
        self.assertIn("watchBtn.setAttribute('aria-label', '動画を新しいタブで再生')", html)
        self.assertIn("fullLink.setAttribute('aria-label', '元画像を別タブで開く')", html)

    def test_keyboard_shortcut_c_targets_copy_citation_button(self) -> None:
        """Pressing 'c' key must target copy-citation button specifically without hijacking domain filter buttons."""
        html = webui_next.AI_WORKSPACE_HTML
        self.assertIn(
            'querySelector(\'button[data-action="copy-citation"], button[aria-label*="コピー"]\')',
            html,
        )
        # Ensure the old fragile selector '.btn:last-of-type' is no longer used for 'c' key shortcut
        self.assertNotIn('button[aria-label*="コピー"], .btn:last-of-type', html)

    def test_classic_pagination_next_button_disabled_when_under_limit(self) -> None:
        """Classic search next page button must be disabled when fewer items than count are returned."""
        html = webui_next.AI_WORKSPACE_HTML
        self.assertIn("classic-next-btn').disabled = (items.length < countVal)", html)

    def test_responsive_options_row_reflow_css(self) -> None:
        """Mobile stylesheet must include width 100% reflow for .options-row .opt-group on <=640px viewports."""
        html = webui_next.AI_WORKSPACE_HTML
        self.assertIn(".options-row .opt-group { width: 100%; margin-left: 0 !important; }", html)
        self.assertIn(".options-row .opt-input { min-width: 0; width: 100%; }", html)

    def test_responsive_image_grid_mobile_css(self) -> None:
        """Mobile stylesheet must include narrow 2-column image gallery reflow on <=480px viewports."""
        html = webui_next.AI_WORKSPACE_HTML
        self.assertIn("@media (max-width: 480px)", html)
        self.assertIn("grid-template-columns: repeat(auto-fill, minmax(130px, 1fr))", html)

    def test_search_focus_shortcut_switches_mode_from_agent_or_settings(self) -> None:
        """Focusing search input via '/' or Ctrl+K from agent/settings tabs must switch to deep mode."""
        html = webui_next.AI_WORKSPACE_HTML
        self.assertIn("if (state.mode === 'agent' || state.mode === 'settings')", html)

    def test_url_scrape_switches_mode_to_deep(self) -> None:
        """Entering a URL to scrape must switch to deep mode so the split-view and drawer are visible."""
        html = webui_next.AI_WORKSPACE_HTML
        self.assertIn("if (state.mode !== 'deep')", html)
        self.assertIn("setMode('deep', true)", html)

    def test_ime_composition_guard_in_suggest(self) -> None:
        """Verify IME composition guard (e.isComposing || e.keyCode === 229) is present in suggest keydown."""
        html = webui_next.AI_WORKSPACE_HTML
        self.assertIn("if (e.isComposing || e.keyCode === 229) return;", html)

    def test_enter_key_selection_on_active_suggestion(self) -> None:
        """Verify Enter key explicitly commits and submits the active suggestion item."""
        html = webui_next.AI_WORKSPACE_HTML
        self.assertIn("activeSuggestIndex >= 0 && items[activeSuggestIndex]", html)

    def test_markdown_escaped_brackets_link_parsing(self) -> None:
        """Verify markdown link regex handles titles with escaped brackets from escape_markdown_link."""
        html = webui_next.AI_WORKSPACE_HTML
        self.assertIn(r"\[((?:\\\]|[^\]])+)\]", html)
        self.assertIn(r"label.replace(/\\([\[\]])/g, '$1')", html)

    def test_card_navigation_focus_and_aria_attributes(self) -> None:
        """Verify j/k card navigation activates ARIA selection and focuses the target card without scroll hijack."""
        html = webui_next.AI_WORKSPACE_HTML
        self.assertIn("c.setAttribute('aria-selected', isSel ? 'true' : 'false')", html)
        self.assertIn("targetCard.setAttribute('tabindex', '-1')", html)
        self.assertIn("targetCard.focus({ preventScroll: true })", html)

    def test_selected_card_video_and_image_styles(self) -> None:
        """Verify .video-card.selected-card and .image-card.selected-card styles exist in CSS."""
        html = webui_next.AI_WORKSPACE_HTML
        self.assertIn(".video-card.selected-card {", html)
        self.assertIn(".image-card.selected-card {", html)


if __name__ == "__main__":
    unittest.main()
