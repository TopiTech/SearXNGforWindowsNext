#!/usr/bin/env python3
"""Data Models, Mode Budgets, and Response Serializers for SearXNG Retrieval.

Defines:
- ModeBudget specifications for 'fast', 'balanced', and 'deep' search modes
- RetrievalResultItem and RetrievalResponse conforming to the GenAI Structured Schema
- Source type and domain authority classifications
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from passage_chunker import EvidencePassage
from query_pipeline import ProcessedQuery
from rank_fusion import ScoreComponents
from url_normalizer import extract_domain


@dataclass(frozen=True)
class ModeBudget:
    """Explicit computational, concurrency, and time budgets for a search mode."""

    mode: str
    max_queries: int
    max_results_per_query: int
    max_candidate_results: int
    max_pages: int
    max_passages_per_page: int
    max_total_passages: int
    max_total_chars: int
    max_response_bytes: int
    request_deadline_ms: int
    per_engine_timeout_ms: int
    scrape_timeout_ms: int
    max_concurrency: int
    max_search_rounds: int


BUDGETS: dict[str, ModeBudget] = {
    "fast": ModeBudget(
        mode="fast",
        max_queries=1,
        max_results_per_query=10,
        max_candidate_results=10,
        max_pages=0,  # Never scrape in fast mode
        max_passages_per_page=0,
        max_total_passages=0,
        max_total_chars=4000,
        max_response_bytes=500_000,
        request_deadline_ms=5000,
        per_engine_timeout_ms=3000,
        scrape_timeout_ms=0,
        max_concurrency=4,
        max_search_rounds=1,
    ),
    "balanced": ModeBudget(
        mode="balanced",
        max_queries=2,
        max_results_per_query=15,
        max_candidate_results=20,
        max_pages=3,
        max_passages_per_page=3,
        max_total_passages=6,
        max_total_chars=12000,
        max_response_bytes=2_000_000,
        request_deadline_ms=10000,
        per_engine_timeout_ms=5000,
        scrape_timeout_ms=5000,
        max_concurrency=5,
        max_search_rounds=1,
    ),
    "deep": ModeBudget(
        mode="deep",
        max_queries=3,
        max_results_per_query=20,
        max_candidate_results=30,
        max_pages=6,
        max_passages_per_page=4,
        max_total_passages=12,
        max_total_chars=25000,
        max_response_bytes=5_000_000,
        request_deadline_ms=18000,
        per_engine_timeout_ms=8000,
        scrape_timeout_ms=7000,
        max_concurrency=6,
        max_search_rounds=2,
    ),
}


# High-authority domains for source type classification and quality scoring
DOC_DOMAINS: set[str] = {
    "docs.python.org",
    "peps.python.org",
    "developer.mozilla.org",
    "react.dev",
    "nextjs.org",
    "vuejs.org",
    "go.dev",
    "golang.org",
    "rust-lang.org",
    "docs.rs",
    "learn.microsoft.com",
    "kubernetes.io",
    "nodejs.org",
    "typescriptlang.org",
    "docker.com",
    "fastapi.tiangolo.com",
    "w3.org",
    "ietf.org",
    "rfc-editor.org",
}

SOURCE_CODE_DOMAINS: set[str] = {
    "github.com",
    "gitlab.com",
    "pypi.org",
    "crates.io",
    "npmjs.com",
}

ACADEMIC_DOMAINS: set[str] = {
    "arxiv.org",
    "wikipedia.org",
    "scholar.google.com",
    "acm.org",
    "ieee.org",
    "jst.go.jp",
}

COMMUNITY_DOMAINS: set[str] = {
    "stackoverflow.com",
    "stackexchange.com",
    "superuser.com",
    "serverfault.com",
    "askubuntu.com",
    "reddit.com",
}

SPAM_PATTERNS: list[re.Pattern] = [
    re.compile(r"copypaste", re.IGNORECASE),
    re.compile(r"scraper", re.IGNORECASE),
    re.compile(r"mirror\.", re.IGNORECASE),
    re.compile(r"geeksforgeeks\.org", re.IGNORECASE),
]


def classify_source_type(domain_or_url: str) -> str:
    """Classify domain or URL into documentation, source_code, academic, community, news, or general."""
    if not domain_or_url:
        return "general"
    domain = extract_domain(domain_or_url) if ("://" in domain_or_url or "/" in domain_or_url) else domain_or_url
    if not domain:
        return "general"
    dom = domain.lower().removeprefix("www.")
    if (
        any(dom == d or dom.endswith("." + d) for d in DOC_DOMAINS)
        or dom.startswith(("docs.", "doc."))
        or ".readthedocs." in dom
    ):
        return "documentation"
    if any(dom == d or dom.endswith("." + d) for d in SOURCE_CODE_DOMAINS):
        return "source_code"
    if any(dom == d or dom.endswith("." + d) for d in ACADEMIC_DOMAINS):
        return "academic"
    if any(dom == d or dom.endswith("." + d) for d in COMMUNITY_DOMAINS):
        return "community"
    if any(word in dom for word in ("news", "times", "post", "asahi", "nikkei", "reuters", "bloomberg")):
        return "news"
    return "general"


def get_mode_budget(mode: str) -> ModeBudget:
    """Retrieve mode budget configuration by name."""
    return BUDGETS.get(mode.lower().strip(), BUDGETS["balanced"])


def compute_source_quality(
    domain_or_url: str,
    source_type: str = "",
    has_canonical: bool = False,
) -> float:
    """Compute an auxiliary citation suitability score (0.1 to 1.0).

    NOTE: source_quality reflects structural citation appropriateness (e.g. primary docs),
    NOT a guarantee of factual truth.
    """
    if not domain_or_url:
        return 0.5
    domain = extract_domain(domain_or_url) if "://" in domain_or_url else domain_or_url
    if not domain:
        return 0.5
    dom = domain.lower().removeprefix("www.")

    for pat in SPAM_PATTERNS:
        if pat.search(dom):
            return 0.1

    score = 0.50
    if (
        source_type == "documentation"
        or any(dom == d or dom.endswith("." + d) for d in DOC_DOMAINS)
        or dom.startswith(("docs.", "doc."))
        or ".readthedocs." in dom
    ):
        score = 0.95
    elif source_type == "source_code" or any(dom == d or dom.endswith("." + d) for d in SOURCE_CODE_DOMAINS):
        score = 0.90
    elif source_type == "academic" or any(dom == d or dom.endswith("." + d) for d in ACADEMIC_DOMAINS):
        score = 0.92
    elif source_type == "community" or any(dom == d or dom.endswith("." + d) for d in COMMUNITY_DOMAINS):
        score = 0.75
    elif dom.endswith((".gov", ".edu", ".go.jp", ".ac.jp")):
        score = 0.95

    if has_canonical:
        score = min(score + 0.03, 1.0)

    return round(score, 2)


@dataclass
class QueryInfo:
    """Simplified query info matching GenAI query schema."""

    original: str
    normalized: str
    clean_text: str = ""
    intent: str = "factual"
    language: str = "en"
    freshness: str | None = None

    def __post_init__(self) -> None:
        if not self.clean_text:
            self.clean_text = self.normalized or self.original

    def to_dict(self) -> dict[str, Any]:
        return {
            "original": self.original,
            "normalized": self.normalized,
            "intent": self.intent,
            "language": self.language,
            "freshness": self.freshness,
        }


@dataclass
class SearchExecutionInfo:
    """Execution telemetry and query parameters matching GenAI schema."""

    mode: str = "balanced"
    expanded_queries: list[str] = field(default_factory=list)
    engines_used: list[str] = field(default_factory=list)
    partial: bool = False
    elapsed_ms: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "expanded_queries": self.expanded_queries,
            "engines_used": self.engines_used,
            "partial": self.partial,
            "elapsed_ms": round(self.elapsed_ms, 1),
        }


@dataclass
class RetrievalResultItem:
    """A single retrieved search result item matching the GenAI schema."""

    id: str  # e.g., 'src_01'
    title: str
    url: str
    canonical_url: str = ""
    domain: str = ""
    published_at: str | None = None
    updated_at: str | None = None
    date_source: str | None = None
    date_confidence: str | None = None
    source_type: str = "general"
    score: float = 0.0
    score_components: ScoreComponents = field(default_factory=ScoreComponents)
    matched_queries: list[str] = field(default_factory=list)
    engines: list[str] = field(default_factory=list)
    snippet: str = ""
    evidence: list[EvidencePassage] = field(default_factory=list)
    security_flags: list[str] = field(default_factory=list)
    duplicate_urls: list[str] = field(default_factory=list)
    raw_content: str = ""
    is_scraped: bool = False

    def to_dict(self) -> dict[str, Any]:
        """Convert item to the required GenAI JSON structure."""
        return {
            "id": self.id,
            "title": self.title,
            "url": self.url,
            "canonical_url": self.canonical_url or self.url,
            "domain": self.domain or extract_domain(self.url),
            "published_at": self.published_at,
            "updated_at": self.updated_at,
            "date_source": self.date_source,
            "date_confidence": self.date_confidence,
            "source_type": self.source_type,
            "score": round(self.score, 4),
            "score_components": self.score_components.to_dict(),
            "matched_queries": self.matched_queries,
            "engines": self.engines,
            "snippet": self.snippet,
            "evidence": [ev.to_dict() for ev in self.evidence],
            "security_flags": self.security_flags,
        }


@dataclass
class RetrievalResponse:
    """The complete structured response returned to GenAI/MCP/Agents."""

    schema_version: str = "1.0"
    query: ProcessedQuery | QueryInfo = field(default_factory=lambda: ProcessedQuery("", "", "", "factual", "en"))
    mode: str = "balanced"
    expanded_queries: list[str] = field(default_factory=list)
    engines_used: list[str] = field(default_factory=list)
    partial: bool = False
    elapsed_ms: float = 0.0
    results: list[RetrievalResultItem] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    answers: list[str] = field(default_factory=list)
    infoboxes: list[Any] = field(default_factory=list)
    search: SearchExecutionInfo = field(default_factory=SearchExecutionInfo)

    def __post_init__(self) -> None:
        if self.search.expanded_queries or self.search.mode != "balanced":
            self.mode = self.search.mode
            self.expanded_queries = self.search.expanded_queries
            self.engines_used = self.search.engines_used
            self.partial = self.search.partial
            self.elapsed_ms = self.search.elapsed_ms
        else:
            self.search = SearchExecutionInfo(
                mode=self.mode,
                expanded_queries=self.expanded_queries,
                engines_used=self.engines_used,
                partial=self.partial,
                elapsed_ms=self.elapsed_ms,
            )

    def to_dict(self) -> dict[str, Any]:
        """Serialize according to the GenAI Structured Response schema."""
        query_dict = self.query.to_dict() if hasattr(self.query, "to_dict") else vars(self.query)
        search_dict = self.search.to_dict()
        return {
            "schema_version": self.schema_version,
            "query": query_dict,
            "search": search_dict,
            "results": [r.to_dict() for r in self.results],
            "warnings": self.warnings,
        }

    def to_markdown(self) -> str:
        """Format the retrieval response into rich, citation-dense Markdown."""
        q_text = (
            getattr(self.query, "clean_text", "")
            or getattr(self.query, "normalized", "")
            or getattr(self.query, "original", "")
        )
        lines: list[str] = [f"## Search Retrieval: `{q_text}` (Mode: `{self.mode}`, Intent: `{self.query.intent}`)\n"]

        if self.answers:
            for ans in self.answers:
                if ans.strip():
                    lines.append(f"> 💡 **Direct Answer**: {ans.strip()}\n")

        if not self.results:
            lines.append("該当する検索結果が見つかりませんでした。別のキーワードをお試しください。")
            return "\n".join(lines)

        for item in self.results:
            source_tag = f" `[{', '.join(item.engines)}]`" if item.engines else ""
            score_tag = f" `[score: {item.score:.2f}]`" if item.score > 0 else ""
            item_header = f"### [{item.id}] [{item.title}]({item.url}){source_tag}{score_tag}\n"
            lines.append(item_header)

            if item.evidence:
                for ev in item.evidence:
                    heading_str = f"**{ev.heading}**: " if ev.heading and ev.heading != "General" else ""
                    quote_text = "\n".join(f"> {l}" for l in ev.text.split("\n"))
                    lines.append(f"- **[{ev.id}]** {heading_str}\n{quote_text}\n")
            elif item.snippet:
                lines.append(f"> {item.snippet}\n")
            else:
                lines.append("*(スニペットなし)*\n")

        lines.append("---\n**Citations & Sources:**")
        for item in self.results:
            dup_suffix = f" *(+ {len(item.duplicate_urls)} duplicates)*" if item.duplicate_urls else ""
            lines.append(f"- [{item.id}] [{item.title}]({item.url}) ({item.domain}){dup_suffix}")

        return "\n".join(lines).strip()
