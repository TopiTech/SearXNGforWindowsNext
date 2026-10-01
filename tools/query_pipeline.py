#!/usr/bin/env python3
"""Deterministic Query Normalization, Intent Classification, and Expansion Module.

Processes search queries deterministically without external LLM API dependencies,
preserving search operators, versions, product names, and error codes.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any, ClassVar


@dataclass
class ProcessedQuery:
    """Represents a thoroughly normalized and classified query."""

    original: str
    normalized: str
    clean_text: str  # text stripped of operators
    intent: str  # navigation, factual, fresh, comparison, howto, research, code, local
    language: str  # ja, en, etc.
    freshness: str | None = None  # day, week, month, year, or specific year string
    expanded_queries: list[str] = field(default_factory=list)
    include_domains: list[str] = field(default_factory=list)
    exclude_domains: list[str] = field(default_factory=list)
    filetype: str = ""
    exact_phrases: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Convert query representation to GenAI Structured Response schema dict."""
        return {
            "original": self.original,
            "normalized": self.normalized,
            "intent": self.intent,
            "language": self.language,
            "freshness": self.freshness,
        }


class QueryProcessor:
    """Deterministic query normalizer, intent classifier, and expander."""

    CODE_KEYWORDS: ClassVar[set[str]] = {
        "error",
        "exception",
        "traceback",
        "syntax",
        "def",
        "class",
        "function",
        "api",
        "method",
        "bug",
        "crash",
        "segfault",
        "module",
        "import",
        "package",
        "npm",
        "pip",
        "cargo",
        "go",
        "python",
        "typescript",
        "javascript",
        "rust",
        "react",
        "fastapi",
        "docker",
        "k8s",
        "kubernetes",
        "async",
        "await",
        "null",
        "undefined",
        "pointer",
        "regex",
        "sql",
        "hook",
        "component",
        "lifespan",
        "panic",
        "runtime",
    }

    FRESH_KEYWORDS: ClassVar[set[str]] = {
        "news",
        "latest",
        "today",
        "yesterday",
        "breaking",
        "update",
        "release",
        "released",
        "launch",
        "announced",
        "速報",
        "最新",
        "今日",
        "ニュース",
    }

    HOWTO_KEYWORDS: ClassVar[set[str]] = {
        "how to",
        "howto",
        "tutorial",
        "guide",
        "step by step",
        "install",
        "setup",
        "configuration",
        "使い方",
        "手順",
        "導入",
        "設定",
        "方法",
        "やり方",
        "構築",
    }

    COMPARISON_PATTERNS: ClassVar[list[re.Pattern]] = [
        re.compile(r"\b([a-z0-9_+#.-]+)\s+(vs|versus|compared to)\s+([a-z0-9_+#.-]+)\b", re.IGNORECASE),
        re.compile(r"([^\s]+)\s*(と|VS|対)\s*([^\s]+)\s*(比較|違い|どっち)", re.IGNORECASE),
    ]

    RESEARCH_KEYWORDS: ClassVar[set[str]] = {
        "architecture",
        "deep dive",
        "survey",
        "benchmark",
        "paper",
        "arxiv",
        "internals",
        "comparison",
        "overview",
        "evaluation",
        "cve",
        "advisory",
        "security advisory",
        "vulnerability",
        "設計",
        "仕組み",
        "内部構造",
        "アーキテクチャ",
        "論文",
    }

    NAVIGATION_KEYWORDS: ClassVar[set[str]] = {
        "login",
        "signin",
        "portal",
        "homepage",
        "official site",
        "official",
        "docs",
        "documentation",
        "dashboard",
        "ログイン",
        "公式サイト",
        "ホームページ",
    }

    @classmethod
    def detect_language(cls, text: str) -> str:
        """Lightweight language detection based on script character ranges."""
        if not text:
            return "en"
        # Japanese Hiragana or Katakana
        if re.search(r"[\u3040-\u309f\u30a0-\u30ff]", text):
            return "ja"
        # Chinese Hanzi / Kanji (without Kana)
        if re.search(r"[\u4e00-\u9fff]", text):
            return "ja"  # Default CJK to ja in this workspace context
        return "en"

    @classmethod
    def detect_freshness(cls, text: str) -> str | None:
        """Detect explicit freshness indicators such as recent years or relative time words."""
        low = text.lower()
        year_match = re.search(r"\b(202[4-9])\b", low)
        if year_match:
            return year_match.group(1)
        if any(w in low for w in ("today", "今日", "latest", "最新", "速報")):
            return "week"
        if any(w in low for w in ("this month", "今月")):
            return "month"
        if any(w in low for w in ("this year", "今年")):
            return "year"
        return None

    @classmethod
    def classify_intent(cls, text: str) -> str:
        """Classify search intent into one of the 8 canonical categories."""
        low = text.lower()

        # Check comparisons
        for pat in cls.COMPARISON_PATTERNS:
            if pat.search(low):
                return "comparison"

        # Check navigation
        if any(w in low for w in cls.NAVIGATION_KEYWORDS) or low.endswith((".com", ".org", ".io", ".dev", ".net")):
            return "navigation"

        # Check research / security advisory
        if any(w in low for w in cls.RESEARCH_KEYWORDS):
            return "research"

        # Check code / stack trace
        if "traceback" in low or "error:" in low or "exception" in low or "line " in low:
            return "code"

        # Check fresh news (evaluated before generic language names in CODE_KEYWORDS)
        if any(w in low for w in cls.FRESH_KEYWORDS):
            return "fresh"

        # Check howto / tutorials
        if any(w in low for w in cls.HOWTO_KEYWORDS):
            return "howto"

        # Check code / programming languages
        words = set(re.findall(r"\b[a-z0-9_+#.-]+\b", low))
        if len(words & cls.CODE_KEYWORDS) >= 1:
            return "code"

        # Check local / geographic
        if any(w in low for w in ("near me", "近くの", "周辺", "in tokyo", "東京")):
            return "local"

        # Check factual / definitions
        if any(w in low for w in ("what is", "who is", "define", "とは", "意味")):
            return "factual"

        return "research"

    @classmethod
    def parse_and_normalize(cls, raw_query: str) -> ProcessedQuery:
        """Normalize query string while preserving operators, versions, and codes."""
        orig = (raw_query or "").strip()
        if not orig:
            return ProcessedQuery(
                original="",
                normalized="",
                clean_text="",
                intent="factual",
                language="en",
            )

        # 1. Unicode NFKC normalization
        norm = unicodedata.normalize("NFKC", orig)
        # Normalize double quotes
        norm = re.sub(r"[\u201c\u201d\u201e\u201f\u2033\u2036\uff02«»“”″]", '"', norm)
        # Normalize single quotes
        norm = re.sub(r"[\u2018\u2019\u201a\u201b\u2032\u2035\uff07‘’′]", "'", norm)
        # Normalize dashes/hyphens
        norm = re.sub(r"[\u2013\u2014\u2015\u2212\uff0d–—]", "-", norm)
        # Collapse multiple whitespace
        norm = re.sub(r"[ \t\u3000]+", " ", norm).strip()

        # 2. Extract exact phrase quotes: "exact phrase"
        exact_phrases = re.findall(r'"([^"]+)"', norm)

        # 3. Extract operators: site:..., +site:..., -site:..., filetype:...
        tokens = norm.split()
        clean_tokens: list[str] = []
        inc_domains: list[str] = []
        exc_domains: list[str] = []
        filetype = ""

        def _clean_operator_domain(raw_dom: str) -> str:
            return (
                raw_dom.strip()
                .strip("\"'")
                .lower()
                .removeprefix("https://")
                .removeprefix("http://")
                .split("/")[0]
                .split(":")[0]
                .removeprefix("www.")
                .strip(".")
            )

        for t in tokens:
            t_low = t.lower()
            if t_low.startswith("site:") and len(t) > 5:
                dom = _clean_operator_domain(t[5:])
                if dom and dom not in inc_domains:
                    inc_domains.append(dom)
            elif t_low.startswith("+site:") and len(t) > 6:
                dom = _clean_operator_domain(t[6:])
                if dom and dom not in inc_domains:
                    inc_domains.append(dom)
            elif t_low.startswith("-site:") and len(t) > 6:
                dom = _clean_operator_domain(t[6:])
                if dom and dom not in exc_domains:
                    exc_domains.append(dom)
            elif t_low.startswith("filetype:") and len(t) > 9:
                filetype = t[9:].strip().lower()
            else:
                clean_tokens.append(t)

        clean_text = " ".join(clean_tokens).strip()
        # Remove surrounding quotes from clean_text if any
        clean_no_quotes = re.sub(r'"([^"]+)"', r"\1", clean_text)
        clean_no_quotes = re.sub(r"\s+", " ", clean_no_quotes).strip()

        lang = cls.detect_language(clean_no_quotes)
        freshness = cls.detect_freshness(clean_no_quotes)
        intent = cls.classify_intent(clean_no_quotes)

        return ProcessedQuery(
            original=orig,
            normalized=norm,
            clean_text=clean_no_quotes,
            intent=intent,
            language=lang,
            freshness=freshness,
            include_domains=inc_domains,
            exclude_domains=exc_domains,
            filetype=filetype,
            exact_phrases=exact_phrases,
        )

    @classmethod
    def expand_query(
        cls,
        processed: ProcessedQuery,
        mode: str = "balanced",
    ) -> list[str]:
        """Generate conservative, deterministic auxiliary search queries based on intent.

        Args:
            processed: The ProcessedQuery object.
            mode: 'fast' (no expansion), 'balanced' (1 expansion), or 'deep' (1-2 expansions).

        Returns:
            List of expanded query strings (excluding the original).
        """
        if mode == "fast":
            return []

        base = processed.clean_text
        if not base or len(base) < 3:
            return []

        expansions: list[str] = []

        if processed.intent == "comparison":
            for pat in cls.COMPARISON_PATTERNS:
                m = pat.search(base)
                if m:
                    item_a, item_b = m.group(1).strip(), m.group(3).strip()
                    if item_a and item_b:
                        expansions.append(item_a)
                        expansions.append(item_b)
                        break

        elif processed.intent == "code":
            if "documentation" not in base.lower() and "docs" not in base.lower():
                expansions.append(f"{base} documentation")
            if mode == "deep" and "github" not in base.lower():
                expansions.append(f"{base} github")

        elif processed.intent == "fresh":
            if "cve" in base.lower() or "vulnerability" in base.lower():
                expansions.append(f"{base} advisory")
            elif processed.freshness and processed.freshness not in base:
                expansions.append(f"{base} {processed.freshness}")

        elif processed.intent == "howto":
            if "tutorial" not in base.lower() and "guide" not in base.lower():
                if processed.language == "ja":
                    expansions.append(f"{base} 使い方")
                else:
                    expansions.append(f"{base} tutorial")

        elif processed.intent == "research" and mode == "deep" and "architecture" not in base.lower():
            expansions.append(f"{base} architecture")

        # Cap according to mode
        max_exp = 1 if mode == "balanced" else 2
        return expansions[:max_exp]


def process_query(raw_query: str) -> ProcessedQuery:
    """Convenience helper to process a search query."""
    return QueryProcessor.parse_and_normalize(raw_query)


def normalize_query(raw_query: str) -> str:
    """Normalize query text, preserving operators and technical tokens."""
    return QueryProcessor.parse_and_normalize(raw_query).normalized


def classify_intent(raw_query: str) -> str:
    """Classify the search intent for a query."""
    return QueryProcessor.classify_intent(raw_query)


class DeterministicQueryPipeline:
    """Deterministic query normalization, intent classification, and expansion pipeline."""

    def process(self, raw_query: str, mode: str = "balanced") -> ProcessedQuery:
        """Process and expand query for the given mode."""
        proc = QueryProcessor.parse_and_normalize(raw_query)
        proc.expanded_queries = QueryProcessor.expand_query(proc, mode=mode)
        return proc


QueryContext = ProcessedQuery
