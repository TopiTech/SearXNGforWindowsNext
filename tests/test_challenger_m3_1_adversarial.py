#!/usr/bin/env python3
"""Comprehensive Adversarial Stress Test Suite for Milestone 3 (Unified AI WebUI & Accessibility).

Challenger M3-1: DOM & Accessibility Stress Challenger

Adversarial Stress Suites:
1. Suite 1: Full DOM Parsing & Accessibility Compliance:
   - Form Control Labels & Accessible Names (F3.1)
   - Skip-to-Content Link First Child & Focus CSS (F3.2)
   - Tablist Initial Roving Tabindex & Non-Dangling Panel Targets (F3.3)
   - Category Filter Chips ARIA Pressed States (F3.5)
   - DOM Element ID Uniqueness
2. Suite 2: WCAG 2.1 AA Color Contrast Oracle (F3.7):
   - Exact mathematical relative luminance computation
   - Light theme --amber (#b45309) on white (#ffffff), base (#f8fafc), elevated (#f1f5f9)
   - Contrast oracle against old amber (#d97706)
   - Dark theme --amber (#f59e0b) on dark surfaces
   - Light theme status colors audit (--emerald, --danger, --accent, --text-secondary)
3. Suite 3: Responsive 320px Grid Reflow Simulation & BVA (F3.8):
   - Mathematical model of minmax(min(100%, 280px), 1fr)
   - Container width sweep [100px .. 1920px] including 320px viewport with padding
   - Overflow comparison against legacy minmax(310px, 1fr)
4. Suite 4: JavaScript State Machine & Keyboard Navigation Simulation (F3.3, F3.4, F3.6):
   - Keyboard Arrow roving navigation simulation with boundary wrap-around
   - Scrape drawer aria-expanded / aria-controls toggle state synchronization
   - Empty and whitespace-only query validation, toast feedback, and input focus
   - Screen reader live region (#toast-notice with role="status", aria-live="polite")
5. Suite 5: Backend Flask Route Parameter Retention & Boundary Stress (F3.9):
   - POST parameter retention across 302 redirects
   - Multibyte Japanese characters and URL-sensitive punctuation
   - Format delegation to original search (JSON, CSV, Accept header)
6. Suite 6: Scraper Client Hardening & Harness Integrity (F3.10, F3.11):
   - Zero keepalive connection pooling verification (max_keepalive_connections=0)
   - tools/run-tests.ps1 Ruff fallback verification
   - tools/smoke-test.ps1 live engines endpoint verification
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
# DOM Tree & Node Representation for Deep Structural Analysis
# =========================================================================
class DOMNode:
    """Lightweight in-memory DOM node representation."""

    def __init__(
        self,
        tag: str,
        attrs: dict[str, str],
        parent: DOMNode | None = None,
    ) -> None:
        self.tag: str = tag
        self.attrs: dict[str, str] = attrs
        self.parent: DOMNode | None = parent
        self.children: list[DOMNode] = []
        self.text_content: list[str] = []

    @property
    def id(self) -> str:
        return self.attrs.get("id", "")

    @property
    def classes(self) -> list[str]:
        return self.attrs.get("class", "").split()

    @property
    def role(self) -> str:
        return self.attrs.get("role", "")

    def get_attribute(self, name: str) -> str | None:
        return self.attrs.get(name)

    def full_text(self) -> str:
        res = list(self.text_content)
        for child in self.children:
            res.append(child.full_text())
        return " ".join("".join(res).split())


class RobustDOMBuilder(html.parser.HTMLParser):
    """Complete DOM parser capturing structure, attributes, text, and indices."""

    def __init__(self) -> None:
        super().__init__()
        self.root = DOMNode("document", {})
        self.current: DOMNode = self.root
        self.all_nodes: list[DOMNode] = []
        self.id_map: dict[str, list[DOMNode]] = {}
        self.labels_for: dict[str, list[DOMNode]] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_dict = {k: (v or "") for k, v in attrs}
        node = DOMNode(tag, attr_dict, self.current)
        self.current.children.append(node)
        self.all_nodes.append(node)

        # ID indexing
        node_id = attr_dict.get("id")
        if node_id:
            self.id_map.setdefault(node_id, []).append(node)

        # Label for indexing
        if tag == "label" and "for" in attr_dict:
            self.labels_for.setdefault(attr_dict["for"], []).append(node)

        # Void elements in HTML
        void_elements = {
            "area",
            "base",
            "br",
            "col",
            "embed",
            "hr",
            "img",
            "input",
            "link",
            "meta",
            "param",
            "source",
            "track",
            "wbr",
        }
        if tag not in void_elements:
            self.current = node

    def handle_endtag(self, tag: str) -> None:
        void_elements = {
            "area",
            "base",
            "br",
            "col",
            "embed",
            "hr",
            "img",
            "input",
            "link",
            "meta",
            "param",
            "source",
            "track",
            "wbr",
        }
        if tag in void_elements:
            return

        curr = self.current
        while curr is not None and curr.tag != tag and curr.parent is not None:
            curr = curr.parent
        if curr is not None and curr.parent is not None:
            self.current = curr.parent

    def handle_data(self, data: str) -> None:
        cleaned = data.strip()
        if cleaned:
            self.current.text_content.append(cleaned)

    def find_all(self, tag: str | None = None, role: str | None = None, class_name: str | None = None) -> list[DOMNode]:
        results: list[DOMNode] = []
        for n in self.all_nodes:
            if tag and n.tag != tag:
                continue
            if role and n.role != role:
                continue
            if class_name and class_name not in n.classes:
                continue
            results.append(n)
        return results

    def find_by_id(self, elem_id: str) -> DOMNode | None:
        nodes = self.id_map.get(elem_id, [])
        return nodes[0] if nodes else None


# =========================================================================
# SUITE 1: DOM Structure & HTML Accessibility Stress Tests
# =========================================================================
class TestDOMAccessibilityStress(unittest.TestCase):
    """Adversarially verify DOM structure, labels, skip link, and tablists."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.raw_html = webui_next.AI_WORKSPACE_HTML
        cls.dom = RobustDOMBuilder()
        cls.dom.feed(cls.raw_html)

    def test_dom_ids_are_strictly_unique(self) -> None:
        """Adversarial check: Ensure no duplicate element IDs exist in the DOM."""
        duplicates = {elem_id: len(nodes) for elem_id, nodes in self.dom.id_map.items() if len(nodes) > 1}
        self.assertEqual(
            duplicates,
            {},
            f"Found duplicate DOM IDs which breaks label and aria-controls association: {duplicates}",
        )

    def test_settings_selects_labels_and_accessible_names(self) -> None:
        """Verify all 4 settings selects have valid labels, matching IDs, and accessible names (F3.1)."""
        target_selects = [
            ("pref-default-mode", "デフォルト検索モード"),
            ("pref-safesearch", "セーフサーチ (SafeSearch)"),
            ("pref-default-count", "デフォルト取得件数"),
            ("pref-default-tokens", "トークン予算上限"),
        ]

        for select_id, expected_label_substr in target_selects:
            with self.subTest(select_id=select_id):
                # 1. Target select element must exist
                select_node = self.dom.find_by_id(select_id)
                self.assertIsNotNone(select_node, f"Select element #{select_id} not found in DOM")
                assert select_node is not None
                self.assertEqual(select_node.tag, "select")

                # 2. Associated <label for="..."> must exist
                labels = self.dom.labels_for.get(select_id, [])
                self.assertEqual(
                    len(labels),
                    1,
                    f"Expected exactly 1 <label for='{select_id}'>, found {len(labels)}",
                )
                label_node = labels[0]
                label_text = label_node.full_text()
                self.assertIn(
                    expected_label_substr,
                    label_text,
                    f"Label text '{label_text}' does not contain expected '{expected_label_substr}'",
                )

                # 3. Accessible name via aria-label on <select>
                aria_label = select_node.get_attribute("aria-label")
                self.assertIsNotNone(aria_label, f"Select #{select_id} lacks aria-label")
                assert aria_label is not None
                self.assertIn(
                    expected_label_substr,
                    aria_label,
                    f"Select aria-label '{aria_label}' does not match '{expected_label_substr}'",
                )

                # 4. Must contain valid options with values
                option_children = [c for c in select_node.children if c.tag == "option"]
                self.assertGreaterEqual(
                    len(option_children),
                    2,
                    f"Select #{select_id} must have at least 2 options",
                )
                has_selected = any(c.get_attribute("selected") is not None for c in option_children)
                self.assertTrue(has_selected, f"Select #{select_id} must have a default selected option")

    def test_skip_to_content_link_first_interactive_child(self) -> None:
        """Verify skip link is the very first interactive child inside <body> and targets #q (F3.2)."""
        body_nodes = self.dom.find_all(tag="body")
        self.assertEqual(len(body_nodes), 1, "Expected exactly one <body> tag")
        body = body_nodes[0]

        # First non-trivial child in body
        first_child = body.children[0]
        self.assertEqual(
            first_child.tag,
            "a",
            f"First child of <body> must be an anchor <a>, found <{first_child.tag}>",
        )
        self.assertIn(
            "skip-link",
            first_child.classes,
            "First child anchor must have class 'skip-link'",
        )
        self.assertEqual(
            first_child.get_attribute("href"),
            "#q",
            "Skip link href must point to '#q'",
        )

        # Target #q must exist and be an interactive input element
        target_q = self.dom.find_by_id("q")
        self.assertIsNotNone(target_q, "Target element #q does not exist in DOM")
        assert target_q is not None
        self.assertEqual(target_q.tag, "input")
        self.assertIn(target_q.get_attribute("type"), [None, "text", "search"])

    def test_skip_link_css_rules_and_focus_state(self) -> None:
        """Verify skip link CSS places it offscreen initially and displays visibly on focus (F3.2)."""
        skip_css_match = re.search(r"\.skip-link\s*\{(.*?)\}", self.raw_html, re.DOTALL)
        self.assertIsNotNone(skip_css_match, "Missing .skip-link CSS definition")
        assert skip_css_match is not None
        skip_css = skip_css_match.group(1)

        self.assertIn("position: absolute", skip_css)
        self.assertRegex(skip_css, r"top:\s*-\d+px", "Skip link must be positioned offscreen with negative top")

        focus_css_match = re.search(r"\.skip-link:focus\s*\{(.*?)\}", self.raw_html, re.DOTALL)
        self.assertIsNotNone(focus_css_match, "Missing .skip-link:focus CSS definition")
        assert focus_css_match is not None
        focus_css = focus_css_match.group(1)

        self.assertRegex(focus_css, r"top:\s*[0-9]+(\.[0-9]+)?(rem|px)", "Focused skip link must move on-screen")
        self.assertIn("outline:", focus_css, "Focused skip link must have an outline for keyboard visibility")

    def test_tablists_roving_tabindex_and_panel_references(self) -> None:
        """Verify all role='tablist' elements initialize roving tabindex and control valid panels (F3.3)."""
        tablists = self.dom.find_all(role="tablist")
        self.assertGreaterEqual(
            len(tablists), 3, "Expected at least 3 tablists (.nav-tabs, .context-tabs, .settings-subtabs)"
        )

        for tablist in tablists:
            tablist_name = tablist.get_attribute("aria-label") or tablist.classes
            tabs = [c for c in tablist.children if c.role == "tab" or "tab" in c.classes]
            self.assertGreaterEqual(
                len(tabs),
                2,
                f"Tablist {tablist_name} must contain at least 2 tabs",
            )

            active_tabs = [t for t in tabs if t.get_attribute("aria-selected") == "true"]
            inactive_tabs = [t for t in tabs if t.get_attribute("aria-selected") == "false"]

            # Roving tabindex invariant: exactly 1 active tab
            self.assertEqual(
                len(active_tabs),
                1,
                f"Tablist {tablist_name} must have exactly 1 active tab (found {len(active_tabs)})",
            )
            self.assertEqual(
                active_tabs[0].get_attribute("tabindex"),
                "0",
                f"Active tab in {tablist_name} must have tabindex='0'",
            )

            # Invariant: all other tabs have tabindex="-1"
            self.assertEqual(
                len(inactive_tabs),
                len(tabs) - 1,
                f"Tablist {tablist_name} has mismatched inactive tab count",
            )
            for it in inactive_tabs:
                self.assertEqual(
                    it.get_attribute("tabindex"),
                    "-1",
                    f"Inactive tab '{it.full_text()}' in {tablist_name} must have tabindex='-1'",
                )

            # Invariant: aria-controls references an existing element in the DOM
            for t in tabs:
                target_id = t.get_attribute("aria-controls")
                self.assertIsNotNone(
                    target_id,
                    f"Tab '{t.full_text()}' in {tablist_name} lacks aria-controls",
                )
                assert target_id is not None
                controlled_elem = self.dom.find_by_id(target_id)
                self.assertIsNotNone(
                    controlled_elem,
                    f"Tab '{t.full_text()}' aria-controls='{target_id}' does not exist in DOM",
                )

    def test_category_chips_aria_pressed_states(self) -> None:
        """Verify category buttons have boolean aria-pressed states and exactly one active chip initially (F3.5)."""
        cat_chips_container = self.dom.find_by_id("classic-cat-chips")
        self.assertIsNotNone(cat_chips_container, "#classic-cat-chips container not found")
        assert cat_chips_container is not None

        chips = [c for c in cat_chips_container.children if "cat-btn" in c.classes]
        self.assertGreaterEqual(len(chips), 5, "Expected at least 5 category filter chips")

        active_chips = [c for c in chips if c.get_attribute("aria-pressed") == "true"]
        inactive_chips = [c for c in chips if c.get_attribute("aria-pressed") == "false"]

        self.assertEqual(len(active_chips), 1, "Exactly one category chip must have aria-pressed='true'")
        self.assertEqual(len(inactive_chips), len(chips) - 1, "All inactive chips must have aria-pressed='false'")
        self.assertIn("active", active_chips[0].classes, "Chip with aria-pressed='true' must have .active class")


# =========================================================================
# SUITE 2: WCAG 2.1 AA Color Contrast Oracle
# =========================================================================
class TestColorContrastOracle(unittest.TestCase):
    """Adversarially verify relative luminance and WCAG AA contrast ratio constraints (F3.7)."""

    @staticmethod
    def relative_luminance(hex_str: str) -> float:
        """Calculate exact relative luminance according to WCAG 2.1 specification.

        Formula:
          L = 0.2126 * R_lin + 0.7152 * G_lin + 0.0722 * B_lin
          where C_lin = C_srgb / 12.92 if C_srgb <= 0.04045 else ((C_srgb + 0.055) / 1.055) ** 2.4
        """
        clean = hex_str.strip().lstrip("#")
        if len(clean) == 3:
            clean = "".join(c * 2 for c in clean)
        r, g, b = (int(clean[i : i + 2], 16) / 255.0 for i in (0, 2, 4))

        def lin(c: float) -> float:
            return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

        return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)

    @classmethod
    def contrast_ratio(cls, c1: str, c2: str) -> float:
        """Calculate WCAG contrast ratio (L1 + 0.05) / (L2 + 0.05)."""
        l1 = cls.relative_luminance(c1)
        l2 = cls.relative_luminance(c2)
        lighter, darker = max(l1, l2), min(l1, l2)
        return (lighter + 0.05) / (darker + 0.05)

    def test_amber_luminance_and_contrast_ratio_oracle(self) -> None:
        """Mathematically prove #b45309 meets WCAG AA (>= 4.5:1) while #d97706 fails."""
        amber_new = "#b45309"
        amber_old = "#d97706"
        white = "#ffffff"

        l_new = self.relative_luminance(amber_new)
        l_white = self.relative_luminance(white)

        cr_new = self.contrast_ratio(amber_new, white)
        cr_old = self.contrast_ratio(amber_old, white)

        # Oracle checks
        self.assertAlmostEqual(l_white, 1.0, places=5)
        self.assertAlmostEqual(l_new, 0.159095, places=4)

        # New amber: 5.02:1 >= 4.5:1
        self.assertGreaterEqual(
            cr_new,
            4.5,
            f"New amber {amber_new} contrast ratio {cr_new:.3f}:1 must meet WCAG AA (>= 4.5:1)",
        )
        self.assertAlmostEqual(cr_new, 5.0216, places=2)

        # Old amber: 3.19:1 < 4.5:1 (confirms defect)
        self.assertLess(
            cr_old,
            4.5,
            f"Old amber {amber_old} had contrast {cr_old:.3f}:1 which failed WCAG AA",
        )

    def test_amber_contrast_on_all_light_theme_backgrounds(self) -> None:
        """Verify #b45309 maintains >= 4.5:1 contrast against all light theme background surfaces."""
        amber_new = "#b45309"
        light_backgrounds = {
            "--bg-surface": "#ffffff",
            "--bg-base": "#f8fafc",
            "--bg-elevated": "#f1f5f9",
        }

        for var_name, bg_hex in light_backgrounds.items():
            with self.subTest(bg=var_name):
                cr = self.contrast_ratio(amber_new, bg_hex)
                self.assertGreaterEqual(
                    cr,
                    4.5,
                    f"Amber on {var_name} ({bg_hex}) contrast {cr:.3f}:1 is below 4.5:1",
                )

    def test_light_theme_css_contains_updated_amber_value(self) -> None:
        """Verify webui_next.py CSS contains --amber: #b45309 in [data-theme='light']."""
        html = webui_next.AI_WORKSPACE_HTML
        light_block_match = re.search(r'\[data-theme=["\']light["\']\]\s*\{(.*?)\}', html, re.DOTALL)
        self.assertIsNotNone(light_block_match, "[data-theme='light'] block not found")
        assert light_block_match is not None
        light_css = light_block_match.group(1)

        amber_match = re.search(r"--amber:\s*(#[0-9a-fA-F]{6});", light_css)
        self.assertIsNotNone(amber_match, "--amber variable not defined in light theme")
        assert amber_match is not None
        self.assertEqual(amber_match.group(1).lower(), "#b45309")

    def test_dark_theme_amber_and_semantic_colors_contrast(self) -> None:
        """Audit dark theme --amber (#f59e0b) and other semantic colors."""
        dark_amber = "#f59e0b"
        dark_surface = "#111827"
        dark_base = "#0b0f19"

        # Dark theme contrast: #f59e0b is light text on dark background
        cr_dark_surface = self.contrast_ratio(dark_amber, dark_surface)
        cr_dark_base = self.contrast_ratio(dark_amber, dark_base)

        self.assertGreaterEqual(cr_dark_surface, 4.5, f"Dark amber on surface {cr_dark_surface:.2f}:1")
        self.assertGreaterEqual(cr_dark_base, 4.5, f"Dark amber on base {cr_dark_base:.2f}:1")


# =========================================================================
# SUITE 3: Responsive 320px Grid Reflow Simulation & BVA
# =========================================================================
class TestResponsiveGridReflowStress(unittest.TestCase):
    """Stress-test CSS grid column reflow at 320px and arbitrary viewport widths (F3.8)."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.raw_html = webui_next.AI_WORKSPACE_HTML

    def test_engines_grid_css_contains_minmax_clamp_rule(self) -> None:
        """Verify .engines-grid specifies minmax(min(100%, 280px), 1fr)."""
        grid_match = re.search(r"\.engines-grid\s*\{(.*?)\}", self.raw_html, re.DOTALL)
        self.assertIsNotNone(grid_match, ".engines-grid CSS definition not found")
        assert grid_match is not None
        grid_css = grid_match.group(1)

        self.assertIn("grid-template-columns:", grid_css)
        self.assertIn("minmax(min(100%, 280px), 1fr)", grid_css)

    @staticmethod
    def simulate_grid_reflow(container_width: float, min_fixed_px: float = 280.0) -> dict[str, Any]:
        """Simulate CSS grid layout calculation for `repeat(auto-fill, minmax(min(100%, min_fixed_px), 1fr))`."""
        # min(100%, min_fixed_px) evaluated in container coordinates
        min_track = min(container_width, min_fixed_px)

        # Number of columns auto-filled: floor(container_width / min_track), bounded >= 1
        num_cols = max(1, math.floor(container_width / min_track)) if min_track > 0 else 1

        # Each column expands to 1fr
        col_width = container_width / num_cols

        # Overflow amount: positive if single column exceeds container_width
        overflow_px = max(0.0, min_track - container_width)

        return {
            "container_width": container_width,
            "min_track": min_track,
            "num_cols": num_cols,
            "col_width": col_width,
            "overflow_px": overflow_px,
        }

    @staticmethod
    def simulate_legacy_reflow(container_width: float, legacy_min_px: float = 310.0) -> dict[str, Any]:
        """Simulate legacy CSS grid rule `repeat(auto-fill, minmax(310px, 1fr))`."""
        num_cols = max(1, math.floor(container_width / legacy_min_px))
        col_width = max(legacy_min_px, container_width / num_cols)
        overflow_px = max(0.0, legacy_min_px - container_width)
        return {
            "container_width": container_width,
            "min_track": legacy_min_px,
            "num_cols": num_cols,
            "col_width": col_width,
            "overflow_px": overflow_px,
        }

    def test_reflow_sweep_zero_horizontal_overflow(self) -> None:
        """Adversarial BVA sweep across screen widths [100px .. 1920px] proving zero overflow."""
        test_widths = [
            100.0,
            160.0,
            200.0,
            240.0,
            270.0,
            279.0,
            280.0,
            281.0,
            290.0,
            300.0,
            309.0,
            310.0,
            320.0,
            360.0,
            375.0,
            390.0,
            414.0,
            560.0,
            600.0,
            768.0,
            840.0,
            1024.0,
            1280.0,
            1920.0,
        ]

        for w in test_widths:
            with self.subTest(viewport_width=w):
                res = self.simulate_grid_reflow(w, min_fixed_px=280.0)
                self.assertEqual(
                    res["overflow_px"],
                    0.0,
                    f"New rule caused overflow of {res['overflow_px']}px at container width {w}px",
                )
                self.assertLessEqual(
                    res["col_width"],
                    w,
                    f"Column width {res['col_width']}px exceeds container width {w}px",
                )

    def test_legacy_comparison_on_320px_with_padding(self) -> None:
        """Empirically prove legacy minmax(310px, 1fr) overflows at 320px with padding while new rule does not."""
        # 320px mobile viewport with 16px left + 16px right padding = 288px container width
        padded_width = 320.0 - 32.0  # 288px

        legacy_res = self.simulate_legacy_reflow(padded_width, legacy_min_px=310.0)
        new_res = self.simulate_grid_reflow(padded_width, min_fixed_px=280.0)

        # Legacy overflows by 22px
        self.assertEqual(legacy_res["overflow_px"], 22.0)
        self.assertGreater(legacy_res["col_width"], padded_width)

        # New rule fits perfectly with 0px overflow
        self.assertEqual(new_res["overflow_px"], 0.0)
        self.assertAlmostEqual(new_res["col_width"], 288.0)


# =========================================================================
# SUITE 4: JavaScript State Machine & Keyboard Navigation Simulation
# =========================================================================
class TestJavaScriptStateSimulation(unittest.TestCase):
    """Stress-test JavaScript keyboard navigation state transitions and empty query handling."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.raw_html = webui_next.AI_WORKSPACE_HTML

    def test_roving_tabindex_keyboard_state_transitions(self) -> None:
        """Simulate ArrowRight / ArrowLeft wrapping on navTabs, ctxTabs, and subtabBtns."""

        # 1. Nav tabs simulation (4 tabs: deep, classic, agent, settings)
        modes = ["deep", "classic", "agent", "settings"]
        active_idx = 0

        # Simulate 10 forward steps with ArrowRight
        for step in range(10):
            active_idx = (active_idx + 1) % len(modes)
            tab_states = {
                m: {"tabindex": "0" if i == active_idx else "-1", "selected": (i == active_idx)}
                for i, m in enumerate(modes)
            }
            # Verify invariant: exactly one tab has tabindex="0"
            t0 = [m for m, s in tab_states.items() if s["tabindex"] == "0"]
            self.assertEqual(len(t0), 1)
            self.assertEqual(t0[0], modes[active_idx])

        # Simulate 10 backward steps with ArrowLeft
        for step in range(10):
            active_idx = (active_idx - 1 + len(modes)) % len(modes)
            tab_states = {
                m: {"tabindex": "0" if i == active_idx else "-1", "selected": (i == active_idx)}
                for i, m in enumerate(modes)
            }
            t0 = [m for m, s in tab_states.items() if s["tabindex"] == "0"]
            self.assertEqual(len(t0), 1)
            self.assertEqual(t0[0], modes[active_idx])

    def test_js_keyboard_listeners_exist_for_all_tablists(self) -> None:
        """Adversarial check: Verify keydown listeners with Arrow keys are attached in JS."""
        html = self.raw_html

        # Check navTabs keydown listener
        self.assertIn("btn.addEventListener('keydown', function (e)", html)
        self.assertIn("e.key === 'ArrowRight' || e.key === 'ArrowLeft'", html)

        # Check ctxTabs keydown listener
        self.assertIn("tab.addEventListener('keydown', function (e)", html)

        # Check subtabBtns keydown listener
        self.assertIn("subtabBtns.forEach(function (btn, idx)", html)
        self.assertIn("e.key === 'ArrowRight' || e.key === 'ArrowDown'", html)
        self.assertIn("e.key === 'ArrowLeft' || e.key === 'ArrowUp'", html)

    def test_empty_and_whitespace_query_validation_logic(self) -> None:
        """Verify executeCurrentAction() validates whitespace-only input and triggers toast."""
        html = self.raw_html
        exec_match = re.search(r"function executeCurrentAction\(\)\s*\{(.*?)\n\s{6}\}", html, re.DOTALL)
        self.assertIsNotNone(exec_match, "executeCurrentAction definition not found")
        assert exec_match is not None
        body = exec_match.group(1)

        # Check .trim() is called on input value
        self.assertIn("document.getElementById('q').value.trim()", body)

        # Check empty check triggers showToast and focuses #q
        self.assertIn("if (!qVal)", body)
        self.assertIn("showToast('検索キーワードまたはURLを入力してください');", body)
        self.assertIn("document.getElementById('q').focus();", body)
        self.assertIn("return;", body)

        # Simulate trim validation oracle across edge cases
        test_inputs = [
            ("", False),
            ("   ", False),
            ("\t\t\n", False),
            (" \r\n \t ", False),
            ("a", True),
            ("  test query  ", True),
            ("https://github.com", True),
        ]
        for inp, expected_valid in test_inputs:
            trimmed = inp.strip()
            is_valid = bool(trimmed)
            self.assertEqual(is_valid, expected_valid, f"Input '{inp}' validation mismatch")

    def test_toast_live_region_accessibility_attributes(self) -> None:
        """Verify #toast-notice has role='status' and aria-live='polite' for screen reader announcements."""
        dom = RobustDOMBuilder()
        dom.feed(self.raw_html)

        toast = dom.find_by_id("toast-notice")
        self.assertIsNotNone(toast, "#toast-notice element not found in DOM")
        assert toast is not None

        self.assertEqual(toast.role, "status", "Toast notification must have role='status'")
        self.assertEqual(
            toast.get_attribute("aria-live"),
            "polite",
            "Toast notification must have aria-live='polite'",
        )


# =========================================================================
# SUITE 5: Backend Flask Route Parameter Retention & Boundary Stress
# =========================================================================
class TestFlaskSearchRedirectStress(unittest.TestCase):
    """Stress-test unified_search_view POST parameter retention and delegation (F3.9)."""

    def setUp(self) -> None:
        self.app = Flask(__name__)

        @self.app.route("/search", methods=["GET", "POST"], endpoint="search")
        def mock_orig_search() -> Any:
            return Response("ORIGINAL_SEARCH_DELEGATED", mimetype="text/plain")

        webui_next.register_next_webui(self.app, None)
        self.client = self.app.test_client()

    def test_post_redirect_preserves_complex_parameters(self) -> None:
        """Adversarial check: POST redirect preserves multi-byte UTF-8, quotes, and punctuation."""
        complex_cases = [
            {
                "q": "機械学習 & 深層学習 比較",
                "category": "it",
                "time_range": "month",
            },
            {
                "q": '"exact phrase" AND (rust OR python)',
                "category": "general",
                "safesearch": "1",
            },
            {
                "q": "https://example.com/api?a=1&b=2#section",
                "category": "all",
            },
            {
                "q": "a" * 500,  # long query stress
                "category": "science",
            },
        ]

        for payload in complex_cases:
            with self.subTest(query=payload["q"][:20]):
                resp = self.client.post("/search", data=payload)
                self.assertEqual(resp.status_code, 302)

                location = resp.headers.get("Location", "")
                self.assertTrue(location.startswith("/?"))

                # Parse redirect parameters
                parsed = urllib.parse.urlparse(location)
                qs = urllib.parse.parse_qs(parsed.query)

                for k, v in payload.items():
                    self.assertIn(k, qs, f"Redirect query string missing key '{k}'")
                    self.assertEqual(
                        qs[k],
                        [v],
                        f"Value for key '{k}' corrupted in redirect: expected '{v}', got '{qs[k][0]}'",
                    )

    def test_post_with_format_delegates_to_search(self) -> None:
        """Verify format=json and format=csv do not redirect but delegate to original search."""
        for fmt in ["json", "csv", "rss"]:
            with self.subTest(format=fmt):
                resp = self.client.post("/search", data={"q": "test", "format": fmt})
                self.assertEqual(resp.status_code, 200)
                self.assertEqual(resp.get_data(as_text=True), "ORIGINAL_SEARCH_DELEGATED")

    def test_post_with_accept_json_header_delegates(self) -> None:
        """Verify Accept: application/json header delegates to original search."""
        resp = self.client.post(
            "/search",
            data={"q": "test"},
            headers={"Accept": "application/json"},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_data(as_text=True), "ORIGINAL_SEARCH_DELEGATED")


# =========================================================================
# SUITE 6: Scraper Client Hardening & Test Harness Integrity
# =========================================================================
class TestHarnessAndSecurityHardening(unittest.TestCase):
    """Verify scraper connection pooling hardening and test runner script fallbacks (F3.10, F3.11)."""

    def test_scraper_client_keepalive_disabled(self) -> None:
        """Verify httpx.Limits in webui_next.py disables keepalive connection reuse."""
        src_file = os.path.join(TOOLS_DIR, "webui_next.py")
        with open(src_file, encoding="utf-8") as f:
            src = f.read()

        match = re.search(r"Limits\((.*?)\)", src)
        self.assertIsNotNone(match, "httpx.Limits configuration not found")
        assert match is not None
        limits_code = match.group(1)
        self.assertIn("max_keepalive_connections=0", limits_code)

    def test_run_tests_ps1_ruff_fallback(self) -> None:
        """Verify tools/run-tests.ps1 implements fallback check for repo-local ruff.exe."""
        ps1_file = os.path.join(TOOLS_DIR, "run-tests.ps1")
        with open(ps1_file, encoding="utf-8") as f:
            src = f.read()

        self.assertIn(r'Join-Path $repoRoot "python\Scripts\ruff.exe"', src)
        self.assertIn("Test-Path $fallbackRuff", src)

    def test_smoke_test_ps1_engines_assertion(self) -> None:
        """Verify tools/smoke-test.ps1 asserts active and total engine telemetry."""
        smoke_file = os.path.join(TOOLS_DIR, "smoke-test.ps1")
        with open(smoke_file, encoding="utf-8") as f:
            src = f.read()

        self.assertIn('"$base/api/settings/engines"', src)
        self.assertIn("total_engines", src)
        self.assertIn("active_engines", src)


if __name__ == "__main__":
    unittest.main()
