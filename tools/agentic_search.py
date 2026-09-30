#!/usr/bin/env python3
"""Agentic Search Orchestrator for SearXNG for Windows Next.

Provides deep, intelligent, one-pass web search inspired by Exa and Tavily.
Features:
- Speculative parallel fetching & scraping (ThreadPoolExecutor)
- BM25 passage scoring and highlight extraction
- Domain authority scoring & anti-SEO spam filtering
- Query intent classification & optimal engine routing
- Context token budgeting and structured citations
"""

from __future__ import annotations

import concurrent.futures
import math
import re
import threading
import time
import urllib.error
import urllib.parse
from collections.abc import Callable
from concurrent.futures import Future
from dataclasses import dataclass, field
from typing import Any, ClassVar

# High-authority primary domains (Documentation, Source Repositories, Standards)
DEFAULT_BOOST_DOMAINS: dict[str, float] = {
    # Tech documentation
    "docs.python.org": 2.5,
    "peps.python.org": 2.5,
    "pypi.org": 2.0,
    "developer.mozilla.org": 2.5,
    "react.dev": 2.2,
    "nextjs.org": 2.0,
    "vuejs.org": 2.0,
    "go.dev": 2.2,
    "golang.org": 2.2,
    "rust-lang.org": 2.2,
    "docs.rs": 2.2,
    "crates.io": 2.0,
    "fastapi.tiangolo.com": 2.2,
    "learn.microsoft.com": 2.0,
    "kubernetes.io": 2.2,
    "nodejs.org": 2.0,
    "typescriptlang.org": 2.2,
    "docker.com": 2.0,
    # Primary sources & communities
    "github.com": 2.3,
    "gitlab.com": 2.0,
    "stackoverflow.com": 2.2,
    "stackexchange.com": 2.0,
    "superuser.com": 1.8,
    "askubuntu.com": 1.8,
    "serverfault.com": 1.8,
    # Academic & encyclopedic
    "arxiv.org": 2.5,
    "wikipedia.org": 2.0,
    "rfc-editor.org": 2.5,
    "ietf.org": 2.5,
    "w3.org": 2.2,
}

# Domains penalised or excluded (known scraper farms, low-value spam)
DEFAULT_PENALIZED_DOMAINS: dict[str, float] = {
    "geeksforgeeks.org": 0.5,
    "w3schools.com": 0.7,
    "tutorialspoint.com": 0.6,
    "javatpoint.com": 0.4,
}

# Domain substrings indicating spam/scraper copies
DEFAULT_SPAM_PATTERNS: list[str] = [
    r"copypaste",
    r"scraper",
    r"mirror\.",
    r"chegg\.com",
]

# Common English and Japanese stopwords for light distillation
STOP_WORDS: set[str] = {
    "a",
    "an",
    "the",
    "and",
    "or",
    "but",
    "if",
    "then",
    "of",
    "to",
    "for",
    "in",
    "on",
    "at",
    "by",
    "with",
    "from",
    "about",
    "how",
    "what",
    "why",
    "when",
    "where",
    "which",
    "who",
    "is",
    "are",
    "was",
    "were",
    "be",
    "been",
    "being",
    "do",
    "does",
    "did",
    "have",
    "has",
    "had",
    "it",
    "its",
    "this",
    "that",
    "these",
    "those",
    "can",
    "could",
    "should",
    "would",
    "please",
    "tell",
    "me",
    "show",
    "find",
    "search",
    "give",
    "の",
    "に",
    "は",
    "を",
    "た",
    "が",
    "で",
    "て",
    "と",
    "し",
    "れ",
    "さ",
    "ある",
    "いる",
    "も",
    "する",
    "から",
    "な",
    "こと",
    "として",
    "い",
    "や",
    "れる",
    "など",
    "なっ",
    "ない",
    "この",
    "ため",
    "その",
    "について",
    "教えて",
    "方法",
    "どうやって",
}


@dataclass
class SearchResultItem:
    """Standardized search item with scoring and highlights."""

    title: str
    url: str
    domain: str
    content: str
    source: str = ""
    score: float = 0.0
    published_date: str = ""
    highlights: list[str] = field(default_factory=list)
    full_content: str = ""
    scrape_error: str = ""
    is_scraped: bool = False

    def to_dict(self) -> dict[str, Any]:
        """Convert item to serializable dictionary."""
        data: dict[str, Any] = {
            "title": self.title,
            "url": self.url,
            "domain": self.domain,
            "content": self.content,
            "source": self.source,
            "score": round(self.score, 4),
            "highlights": self.highlights,
            "is_scraped": self.is_scraped,
        }
        if self.published_date:
            data["published_date"] = self.published_date
        if self.scrape_error:
            data["scrape_error"] = self.scrape_error
        return data


def extract_domain(url: str) -> str:
    """Extract lowercase netloc/domain from a URL."""
    try:
        parsed = urllib.parse.urlparse(url)
        host = (parsed.hostname or "").lower()
        # Remove leading www.
        return host.removeprefix("www.")
    except (ValueError, AttributeError):
        return ""


def is_url_input(text: str) -> bool:
    """Return True if text is a single HTTP/HTTPS URL rather than a search query."""
    s = (text or "").strip()
    if not s or " " in s or "\n" in s or "\t" in s:
        return False
    if not (s.lower().startswith("http://") or s.lower().startswith("https://")):
        return False
    try:
        parsed = urllib.parse.urlparse(s)
        return bool(parsed.scheme in ("http", "https") and parsed.netloc)
    except ValueError:
        return False


def parse_domain_list(val: Any) -> list[str]:
    """Normalize a comma-separated string or iterable of domain names/URLs."""
    if not val:
        return []
    raw_items: list[str] = []
    if isinstance(val, (list, tuple, set)):
        for item in val:
            if item:
                raw_items.extend(str(item).split(","))
    elif isinstance(val, str):
        raw_items.extend(val.split(","))
    cleaned: list[str] = []
    for d in raw_items:
        dom = (
            d.strip()
            .strip("\"'")
            .lower()
            .removeprefix("https://")
            .removeprefix("http://")
            .split("/")[0]
            .split(":")[0]
            .removeprefix("www.")
        )
        if dom and dom not in cleaned:
            cleaned.append(dom)
    return cleaned


class QueryOptimizer:
    """Analyzes and optimizes natural language search queries for AI agents."""

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
    }

    ACADEMIC_KEYWORDS: ClassVar[set[str]] = {
        "paper",
        "arxiv",
        "theorem",
        "proof",
        "dataset",
        "benchmark",
        "survey",
        "algorithm",
        "evaluation",
        "ablation",
        "transformer",
        "neural",
        "deep learning",
        "model",
        "parameters",
        "citation",
    }

    NEWS_KEYWORDS: ClassVar[set[str]] = {
        "news",
        "announcement",
        "announced",
        "release",
        "released",
        "vulnerability",
        "cve",
        "breaking",
        "update",
        "latest",
        "today",
        "yesterday",
        "launch",
    }

    @classmethod
    def parse_query(cls, query: str) -> tuple[str, list[str], list[str]]:
        """Extract explicit domain filters (site:xxx, -site:yyy) and clean query text.

        Returns:
            tuple: (cleaned_query, include_domains, exclude_domains)
        """
        include_domains: list[str] = []
        exclude_domains: list[str] = []

        tokens = query.strip().split()
        remaining_tokens: list[str] = []

        for token in tokens:
            lower = token.lower()
            if lower.startswith("site:") and len(token) > 5:
                for domain in parse_domain_list(token[5:]):
                    if domain not in include_domains:
                        include_domains.append(domain)
            elif lower.startswith("-site:") and len(token) > 6:
                for domain in parse_domain_list(token[6:]):
                    if domain not in exclude_domains:
                        exclude_domains.append(domain)
            else:
                remaining_tokens.append(token)

        cleaned_query = " ".join(remaining_tokens).strip()
        return cleaned_query, include_domains, exclude_domains

    @classmethod
    def classify_intent(cls, query: str) -> str:
        """Classify search intent into 'code', 'academic', 'news', or 'general'."""
        lower = query.lower()
        words = set(re.findall(r"\b[a-z0-9_+#.-]+\b", lower))

        code_matches = len(words & cls.CODE_KEYWORDS)
        academic_matches = len(words & cls.ACADEMIC_KEYWORDS)
        news_matches = len(words & cls.NEWS_KEYWORDS)

        # Check for stacktrace or code patterns
        if "traceback" in lower or "line " in lower or "error:" in lower or "exception" in lower:
            return "code"

        if code_matches >= 1 and code_matches >= academic_matches:
            return "code"
        if academic_matches >= 1:
            return "academic"
        if news_matches >= 1:
            return "news"

        return "general"

    @classmethod
    def get_routing(cls, intent: str) -> tuple[str, str]:
        """Return recommended categories and engines for a given intent.

        Returns:
            tuple[str, str]: (categories, engines)
        """
        if intent == "code":
            return "it", "bing,brave,github"
        elif intent == "academic":
            return "science,general", "bing,brave,arxiv,google_scholar"
        elif intent == "news":
            return "news,general", "bing,brave,google"
        return "general", "bing,brave,google"

    @classmethod
    def extract_keywords(cls, query: str) -> list[str]:
        """Extract meaningful keywords removing common stopwords."""
        raw_tokens = re.findall(r"[A-Za-z0-9_+#.-]+|[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff]+", query)
        keywords: list[str] = []
        for t in raw_tokens:
            low = t.lower()
            if low not in STOP_WORDS and len(low) > 1:
                keywords.append(low)
        return keywords or [query.lower()]


class DomainScorer:
    """Scores search results based on domain reputation and authority."""

    def __init__(
        self,
        boost_domains: dict[str, float] | None = None,
        penalized_domains: dict[str, float] | None = None,
        spam_patterns: list[str] | None = None,
    ) -> None:
        self.boost_domains = boost_domains if boost_domains is not None else dict(DEFAULT_BOOST_DOMAINS)
        self.penalized_domains = penalized_domains if penalized_domains is not None else dict(DEFAULT_PENALIZED_DOMAINS)
        self.spam_patterns = [re.compile(p, re.IGNORECASE) for p in (spam_patterns or DEFAULT_SPAM_PATTERNS)]

    def get_domain_weight(self, domain: str) -> float:
        """Calculate authority multiplier for a domain."""
        if not domain:
            return 1.0

        # Check spam patterns
        for pat in self.spam_patterns:
            if pat.search(domain):
                return 0.1

        # Check exact or suffix domain match for boost
        for boost_domain, weight in self.boost_domains.items():
            if domain == boost_domain or domain.endswith("." + boost_domain):
                return weight

        # Check penalized domains
        for pen_domain, weight in self.penalized_domains.items():
            if domain == pen_domain or domain.endswith("." + pen_domain):
                return weight

        # General documentation domains (.docs, docs.*, doc.*)
        if domain.startswith(("docs.", "doc.")) or ".readthedocs." in domain:
            return 1.8

        return 1.0

    def score_results(
        self,
        raw_results: list[dict[str, Any]],
        include_domains: list[str] | None = None,
        exclude_domains: list[str] | None = None,
    ) -> list[SearchResultItem]:
        """Filter and score raw search results, returning ordered items."""
        inc_set = {d.lower() for d in (include_domains or [])}
        exc_set = {d.lower() for d in (exclude_domains or [])}

        items: list[SearchResultItem] = []
        total = len(raw_results)

        for rank, r in enumerate(raw_results):
            if not isinstance(r, dict):
                continue
            url = str(r.get("url") or "").strip()
            if not url:
                continue

            dom = extract_domain(url)

            # Apply explicit include filters
            if inc_set and not any(dom == target or dom.endswith("." + target) for target in inc_set):
                continue

            # Apply explicit exclude filters
            if exc_set and any(dom == target or dom.endswith("." + target) for target in exc_set):
                continue

            # Base score inversely proportional to original rank: 1.0 down to 0.1
            base_score = 1.0 - (rank / max(total, 1)) * 0.7

            # Engine score if provided by SearXNG
            raw_score = r.get("score")
            if (
                isinstance(raw_score, (int, float))
                and not math.isnan(raw_score)
                and not math.isinf(raw_score)
                and raw_score > 0
            ):
                base_score = (base_score + min(float(raw_score), 5.0) / 5.0) / 2.0

            dom_weight = self.get_domain_weight(dom)
            final_score = base_score * dom_weight

            item = SearchResultItem(
                title=str(r.get("title") or "").strip() or "Untitled",
                url=url,
                domain=dom,
                content=str(r.get("content") or "").strip(),
                source=str(r.get("source") or "").strip(),
                score=final_score,
                published_date=str(r.get("published_date") or r.get("publishedDate") or "").strip(),
            )
            items.append(item)

        # Sort by final score descending
        items.sort(key=lambda x: x.score, reverse=True)
        return items


class BM25PassageExtractor:
    """Extracts the most relevant text highlights from scraped pages using BM25."""

    def __init__(self, k1: float = 1.5, b: float = 0.75) -> None:
        self.k1 = k1
        self.b = b

    def _tokenize(self, text: str) -> list[str]:
        """Tokenize text into lowercase words and CJK fragments."""
        words = re.findall(r"[A-Za-z0-9_+#.-]+|[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff]", text.lower())
        return [w for w in words if w not in STOP_WORDS]

    def split_passages(self, text: str, min_chars: int = 40, max_chars: int = 800) -> list[str]:
        """Split text into coherent paragraphs and code blocks."""
        if not text:
            return []

        # Split preserving code blocks
        raw_blocks = re.split(r"(\n```[\s\S]*?```\n|\n\n+)", text)
        passages: list[str] = []
        buffer = ""

        for block in raw_blocks:
            b = block.strip()
            if not b:
                continue

            # Code block preserves its structure
            if b.startswith("```") and b.endswith("```"):
                if buffer:
                    passages.append(buffer.strip())
                    buffer = ""
                passages.append(b)
                continue

            # Normal text block
            if len(buffer) + len(b) < max_chars:
                buffer = f"{buffer}\n\n{b}" if buffer else b
            else:
                if buffer:
                    passages.append(buffer.strip())
                buffer = b

        if buffer and len(buffer.strip()) >= min_chars:
            passages.append(buffer.strip())

        # If passages are still empty, fallback to sentence chunks
        if not passages and len(text) >= min_chars:
            passages = [text[:max_chars].strip()]

        return [p for p in passages if len(p) >= min_chars]

    def extract_highlights(self, text: str, query: str, top_k: int = 2) -> list[str]:
        """Extract top_k most relevant passages from text for a query."""
        passages = self.split_passages(text)
        if not passages:
            return []
        if len(passages) <= top_k:
            return passages

        query_tokens = self._tokenize(query)
        if not query_tokens:
            return passages[:top_k]

        doc_tokens_list = [self._tokenize(p) for p in passages]
        doc_lens = [len(dt) for dt in doc_tokens_list]
        avgdl = sum(doc_lens) / max(len(doc_lens), 1)
        num_docs = len(passages)

        # Calculate document frequency for each query term
        df: dict[str, int] = {}
        for qt in set(query_tokens):
            df[qt] = sum(1 for dt in doc_tokens_list if qt in dt)

        # BM25 Scoring
        scores: list[tuple[float, int]] = []
        for i, dt in enumerate(doc_tokens_list):
            doc_len = doc_lens[i]
            if doc_len == 0:
                scores.append((0.0, i))
                continue

            # Term frequencies in this document
            tf: dict[str, int] = {}
            for token in dt:
                tf[token] = tf.get(token, 0) + 1

            score = 0.0
            for qt in query_tokens:
                if qt not in tf:
                    continue
                q_df = df.get(qt, 0)
                # BM25 IDF with smoothing
                idf = math.log(1.0 + (num_docs - q_df + 0.5) / (q_df + 0.5))
                freq = tf[qt]
                numerator = freq * (self.k1 + 1.0)
                denominator = freq + self.k1 * (1.0 - self.b + self.b * (doc_len / max(avgdl, 1.0)))
                score += idf * (numerator / max(denominator, 0.001))

            # Bonus for containing exact continuous query string
            if query.lower() in passages[i].lower():
                score += 3.0

            scores.append((score, i))

        # Sort passages by BM25 score descending
        scores.sort(key=lambda x: x[0], reverse=True)

        chosen: list[str] = []
        for score, idx in scores[:top_k]:
            if score > 0.0 or not chosen:
                chosen.append(passages[idx])

        return chosen or passages[:top_k]


class SpeculativeFetcher:
    """Performs parallel speculative fetching of top search result URLs."""

    def __init__(self, scrape_func: Callable[..., dict[str, Any]], max_workers: int = 5) -> None:
        self.scrape_func = scrape_func
        self.max_workers = max_workers

    def fetch_pages(
        self,
        items: list[SearchResultItem],
        max_fetch: int = 5,
        scrape_length: int = 12000,
        timeout: float = 6.0,
        base_url: str | None = None,
    ) -> list[SearchResultItem]:
        """Concurrently scrape top items and populate full_content without blocking on hung threads."""
        to_fetch = items[:max_fetch]
        if not to_fetch:
            return items

        eff_timeout = float(timeout) if timeout is not None and timeout > 0 else 6.0

        def _do_scrape(target_url: str) -> dict[str, Any]:
            try:
                if base_url is not None:
                    try:
                        res = self.scrape_func(
                            target_url,
                            max_length=scrape_length,
                            timeout=eff_timeout,
                            base_url=base_url,
                        )
                    except TypeError:
                        res = self.scrape_func(target_url, max_length=scrape_length, timeout=eff_timeout)
                else:
                    res = self.scrape_func(target_url, max_length=scrape_length, timeout=eff_timeout)
                err = res.get("error") if isinstance(res, dict) else "Invalid scrape response"
                content = (res.get("content") or "").strip() if isinstance(res, dict) else ""
                if err:
                    return {"is_scraped": False, "full_content": "", "scrape_error": str(err)}
                if content:
                    return {"is_scraped": True, "full_content": content, "scrape_error": ""}
                return {"is_scraped": False, "full_content": "", "scrape_error": "本文が見つかりませんでした"}
            except Exception as e:  # noqa: BLE001
                return {"is_scraped": False, "full_content": "", "scrape_error": str(e)}

        # Daemon threads are essential here: futures that exceed the wall-clock
        # budget are abandoned, but their underlying scrapes keep running. With the
        # standard ThreadPoolExecutor (non-daemon workers) the interpreter's atexit
        # join would block process exit - e.g. a CLI deep search could hang for the
        # full per-page scrape timeout (10-15s) after results were already printed.
        # Daemon workers let the process exit immediately; the stale scrape simply
        # dies with it. Each scrape runs on a dedicated daemon thread whose outcome
        # is marshalled back through a plain Future, keeping concurrent.futures.wait
        # semantics (and the public behaviour of this method) unchanged.
        def _daemonized_run(fut: Future, target_url: str) -> None:
            try:
                fut.set_result(_do_scrape(target_url))
            except BaseException as exc:  # noqa: BLE001 - mirror Future.result() semantics
                try:
                    fut.set_exception(exc)
                except concurrent.futures.InvalidStateError:
                    pass

        future_to_item: dict[Future, SearchResultItem] = {}
        for it in to_fetch:
            fut: Future = Future()
            worker = threading.Thread(
                target=_daemonized_run,
                args=(fut, it.url),
                name=f"sxng-speculative-{it.url[:40]}",
                daemon=True,
            )
            worker.start()
            future_to_item[fut] = it
        done, not_done = concurrent.futures.wait(
            future_to_item.keys(),
            timeout=eff_timeout,
        )
        for fut in done:
            item = future_to_item[fut]
            try:
                outcome = fut.result()
                item.is_scraped = bool(outcome.get("is_scraped", False))
                item.full_content = str(outcome.get("full_content") or "")
                item.scrape_error = str(outcome.get("scrape_error") or "")
            except Exception as exc:  # noqa: BLE001
                item.is_scraped = False
                item.scrape_error = str(exc)
        for fut in not_done:
            fut.cancel()
            item = future_to_item[fut]
            item.is_scraped = False
            item.scrape_error = "Scrape timed out"

        return items


class TokenBudgeter:
    """Manages token budgeting and packs structured Markdown for AI agents."""

    @staticmethod
    def estimate_tokens(text: str) -> int:
        """Roughly estimate token count (English ~4 chars/token, CJK ~1.5 chars/token)."""
        if not text:
            return 0
        cjk_chars = len(re.findall(r"[\u3000-\u303f\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uff00-\uffef]", text))
        other_chars = len(text) - cjk_chars
        return int(cjk_chars / 1.5 + other_chars / 4.0)

    @staticmethod
    def build_rag_prompt(query: str, markdown_context: str) -> str:
        """Wrap packed search or scrape markdown into a ready-to-paste LLM RAG prompt."""
        q = (query or "").strip()
        md = (markdown_context or "").strip()
        return (
            "以下のWeb検索結果および抽出された本文ハイライト（引用番号 [1]〜）を根拠として、"
            "質問に対して正確・体系的に回答してください。\n"
            "回答内で事実やコード・数値を参照する際は、対応する引用元 `[1]` などを明記してください。\n\n"
            f"## 質問・調査テーマ\n{q}\n\n"
            f"## 検索コンテキスト\n{md}\n"
        )

    @classmethod
    def pack_scrape_markdown(
        cls,
        url: str,
        content: str,
        query: str = "",
        highlights: list[str] | None = None,
        is_truncated: bool = False,
        original_length: int = 0,
    ) -> str:
        """Format scraped URL content and optional BM25 highlights into AI-friendly Markdown."""
        clean_url = (url or "").strip()
        dom = extract_domain(clean_url)
        orig_len = original_length or len(content or "")
        md_lines = [f"## 抽出本文: [{dom or clean_url}]({clean_url})\n"]
        if not content or not content.strip():
            md_lines.append("抽出可能な本文が見つかりませんでした。")
            return "\n".join(md_lines).strip()

        if is_truncated:
            md_lines.append(
                f"> ⚠️ *コンテキスト長制限のため、先頭 {len(content)} 文字を表示しています (全 {orig_len} 文字)。*\n"
            )
        if highlights:
            q_label = f" (`{query}`)" if query else ""
            md_lines.append(f"### 🎯 BM25 ハイライト{q_label}\n")
            for idx, h in enumerate(highlights, 1):
                if h.startswith("```"):
                    md_lines.append(f"**[{idx}]**\n{h}\n")
                else:
                    quoted = "\n".join(f"> {line}" for line in h.split("\n"))
                    md_lines.append(f"**[{idx}]**\n{quoted}\n")
            md_lines.append("---\n### 📄 抽出本文\n")

        md_lines.append(content.strip())
        return "\n".join(md_lines).strip()

    @classmethod
    def pack_markdown(
        cls,
        query: str,
        items: list[SearchResultItem],
        max_tokens: int = 3000,
        direct_answers: list[str] | None = None,
        intent: str = "general",
        header_label: str = "Deep Search Results",
    ) -> str:
        """Pack search highlights and sources into concise, high-density Markdown."""
        lines: list[str] = [f"## {header_label}: `{query}` (Intent: `{intent}`)\n"]

        if direct_answers:
            for ans in direct_answers:
                if ans.strip():
                    lines.append(f"> 💡 **Direct Answer**: {ans.strip()}\n")

        if not items:
            lines.append("検索結果が見つかりませんでした。別の検索クエリをお試しください。")
            return "\n".join(lines)

        current_tokens = cls.estimate_tokens("".join(lines))
        sources_summary: list[str] = []

        for i, item in enumerate(items, 1):
            title = item.title or "Untitled"
            url = item.url
            source_tag = f" `[{item.source}]`" if item.source else ""
            score_str = f" `[relevance: {item.score:.2f}]`" if item.score > 0 else ""

            item_header = f"### [{i}] [{title}]({url}){source_tag}{score_str}\n"

            body_chunks: list[str] = []
            if item.highlights:
                for h in item.highlights:
                    # If highlight is a code block, keep it raw, otherwise format as quote
                    if h.startswith("```"):
                        body_chunks.append(f"{h}\n")
                    else:
                        quoted = "\n".join(f"> {line}" for line in h.split("\n"))
                        body_chunks.append(f"{quoted}\n")
            elif item.content:
                body_chunks.append(f"> {item.content}\n")

            rendered_item = item_header + "\n".join(body_chunks)
            item_tokens = cls.estimate_tokens(rendered_item)

            if current_tokens + item_tokens <= max_tokens or i == 1:
                lines.append(rendered_item)
                current_tokens += item_tokens
                sources_summary.append(f"- [{i}] [{title}]({url}) ({item.domain})")
            else:
                # Add as reference-only if budget is exhausted
                sources_summary.append(f"- [{i}] [{title}]({url}) *(omitted due to token budget)*")

        lines.append("\n---\n**Citations & Sources:**")
        lines.extend(sources_summary)

        return "\n".join(lines).strip()


def build_rag_prompt(query: str, markdown_context: str) -> str:
    """Module-level helper for building an LLM RAG prompt from search/scrape Markdown."""
    return TokenBudgeter.build_rag_prompt(query, markdown_context)


def execute_scrape_pipeline(
    url: str,
    scrape_func: Callable[..., dict[str, Any]],
    focus_query: str = "",
    max_length: int = 8000,
    base_url: str | None = None,
    timeout: float | None = None,
) -> dict[str, Any]:
    """Execute unified URL scraping with token estimation, BM25 highlights, and RAG prompt."""
    t0 = time.perf_counter()
    clean_url = (url or "").strip()
    clean_q = (focus_query or "").strip()
    try:
        max_len = max(500, min(int(max_length), 50000))
    except (ValueError, TypeError):
        max_len = 8000

    if not clean_url:
        err_msg = "URL が指定されていません。"
        return {
            "mode": "scrape",
            "url": "",
            "domain": "",
            "query": clean_q,
            "content": "",
            "highlights": [],
            "results": [],
            "results_count": 0,
            "scraped_count": 0,
            "char_count": 0,
            "estimated_tokens": 0,
            "elapsed_ms": 0.0,
            "error": err_msg,
            "markdown": f"### 本文抽出エラー\n\n{err_msg}",
            "rag_prompt": "",
        }

    scrape_kwargs: dict[str, Any] = {"max_length": max_len}
    if timeout is not None:
        scrape_kwargs["timeout"] = timeout
    try:
        if base_url is not None:
            try:
                scrape_res = scrape_func(clean_url, base_url=base_url, **scrape_kwargs)
            except TypeError:
                scrape_res = scrape_func(clean_url, **scrape_kwargs)
        else:
            scrape_res = scrape_func(clean_url, **scrape_kwargs)
    except (OSError, ValueError, RuntimeError, TypeError, KeyError, AttributeError) as exc:
        scrape_res = {"error": str(exc)}
    except BaseException as exc:  # noqa: BLE001 - never let a scraper crash the HTTP pipeline
        scrape_res = {"error": f"scrape backend failed: {exc}"}

    elapsed_ms = round((time.perf_counter() - t0) * 1000.0, 1)
    dom = extract_domain(clean_url)

    if scrape_res.get("error"):
        err_msg = str(scrape_res["error"])
        return {
            "mode": "scrape",
            "url": clean_url,
            "domain": dom,
            "query": clean_q,
            "content": "",
            "highlights": [],
            "results": [],
            "results_count": 0,
            "scraped_count": 0,
            "char_count": 0,
            "estimated_tokens": 0,
            "elapsed_ms": elapsed_ms,
            "error": err_msg,
            "markdown": f"### 本文抽出エラー\n\n{err_msg}",
            "rag_prompt": "",
        }

    content = scrape_res.get("content", "")
    is_truncated = bool(scrape_res.get("is_truncated", False))
    orig_len = int(scrape_res.get("original_length", len(content)))

    highlights: list[str] = []
    if clean_q and content:
        extractor = BM25PassageExtractor()
        highlights = extractor.extract_highlights(content, clean_q, top_k=3)

    markdown_out = TokenBudgeter.pack_scrape_markdown(
        url=clean_url,
        content=content,
        query=clean_q,
        highlights=highlights,
        is_truncated=is_truncated,
        original_length=orig_len,
    )
    est_tokens = TokenBudgeter.estimate_tokens(markdown_out)
    rag_prompt = TokenBudgeter.build_rag_prompt(clean_q or clean_url, markdown_out)

    result_item = SearchResultItem(
        title=dom or clean_url,
        url=clean_url,
        domain=dom,
        content=content[:400] + ("..." if len(content) > 400 else ""),
        source="scrape",
        score=1.0,
        highlights=highlights or ([content[:600]] if content else []),
        full_content=content,
        is_scraped=True,
    )

    return {
        "mode": "scrape",
        "url": clean_url,
        "domain": dom,
        "query": clean_q or clean_url,
        "intent": "scrape",
        "content": content,
        "highlights": highlights,
        "results": [result_item.to_dict()],
        "results_count": 1 if content else 0,
        "scraped_count": 1 if content else 0,
        "is_truncated": is_truncated,
        "original_length": orig_len,
        "char_count": len(content),
        "estimated_tokens": est_tokens,
        "elapsed_ms": elapsed_ms,
        "markdown": markdown_out,
        "rag_prompt": rag_prompt,
    }


def execute_unified_search(
    query: str,
    search_func: Callable[..., dict[str, Any]],
    scrape_func: Callable[..., dict[str, Any]],
    mode: str = "auto",
    search_depth: str = "advanced",
    max_results: int = 5,
    include_highlights: bool = True,
    include_domains: list[str] | None = None,
    exclude_domains: list[str] | None = None,
    categories: str = "",
    engines: str = "",
    time_range: str = "",
    focus_query: str = "",
    max_tokens: int = 3000,
    max_scrape_length: int = 8000,
    base_url: str | None = None,
    timeout: float | None = None,
) -> dict[str, Any]:
    """Execute the unified search & scrape pipeline.

    Supports:
    - Automatic URL vs Query detection (`mode='auto'`)
    - Direct URL extraction with BM25 highlights (`mode='scrape'`)
    - Fast `json_lite` search with domain scoring & Markdown packing (`mode='fast'` or `search_depth='fast'`)
    - Deep Agentic Search with parallel scraping & BM25 highlights (`mode='deep'`)
    """
    t0 = time.perf_counter()
    raw_input = (query or "").strip()
    norm_mode = (mode or "auto").strip().lower()
    norm_depth = (search_depth or "advanced").strip().lower()

    # Resolve mode when set to 'auto'
    if norm_mode == "auto":
        if is_url_input(raw_input):
            norm_mode = "scrape"
        elif norm_depth in ("fast", "json_lite"):
            norm_mode = "fast"
        else:
            norm_mode = "deep"
    elif norm_mode == "fast":
        norm_depth = "fast"
    elif norm_mode not in ("deep", "fast", "scrape"):
        norm_mode = "deep"

    # 1. URL Scrape Pipeline
    if norm_mode == "scrape":
        return execute_scrape_pipeline(
            url=raw_input,
            scrape_func=scrape_func,
            focus_query=focus_query,
            max_length=max_scrape_length,
            base_url=base_url,
            timeout=timeout,
        )

    # 2. Search Pipeline (Fast json_lite or Deep BM25 + Parallel Scrape)
    clean_q, explicit_inc, explicit_exc = QueryOptimizer.parse_query(raw_input)
    if not clean_q:
        return {
            "mode": norm_mode,
            "search_depth": norm_depth,
            "query": "",
            "intent": "general",
            "results": [],
            "results_count": 0,
            "scraped_count": 0,
            "estimated_tokens": 0,
            "max_tokens": max_tokens,
            "elapsed_ms": 0.0,
            "error": "検索クエリが空です。検索したいキーワードを指定してください。",
            "markdown": "検索クエリが空です。",
            "rag_prompt": "",
        }

    try:
        max_res = max(1, min(int(max_results), 50))
    except (ValueError, TypeError):
        max_res = 5

    try:
        max_tok = max(500, min(int(max_tokens), 16000))
    except (ValueError, TypeError):
        max_tok = 3000

    try:
        scrape_len = max(500, min(int(max_scrape_length), 50000))
    except (ValueError, TypeError):
        scrape_len = 8000

    # Merge explicit domain filters deterministically
    final_inc = sorted(set(parse_domain_list(include_domains) + explicit_inc))
    final_exc = sorted(set(parse_domain_list(exclude_domains) + explicit_exc))

    intent = QueryOptimizer.classify_intent(clean_q)
    routed_cats, routed_engs = QueryOptimizer.get_routing(intent)

    # In fast mode, only use explicit categories/engines unless none are specified
    if norm_mode == "fast" and not (categories.strip() or engines.strip()):
        target_cats = ""
        target_engs = ""
        fetch_count = max_res if not (final_inc or final_exc) else max(max_res * 2, 10)
    else:
        target_cats = categories.strip() or routed_cats
        target_engs = engines.strip() or routed_engs
        fetch_count = max(max_res * 3, 15)

    search_kwargs: dict[str, Any] = {
        "query": clean_q,
        "count": fetch_count,
        "categories": target_cats,
        "engines": target_engs,
        "base_url": base_url,
        "timeout": timeout,
    }
    if time_range.strip():
        search_kwargs["time_range"] = time_range.strip()

    try:
        search_res = search_func(**search_kwargs)
    except TypeError:
        search_kwargs.pop("time_range", None)
        try:
            search_res = search_func(**search_kwargs)
        except (OSError, ValueError, RuntimeError, TypeError, KeyError, AttributeError) as exc:
            search_res = {"error": str(exc)}
        except BaseException as exc:  # noqa: BLE001 - never let a search backend crash the HTTP pipeline
            search_res = {"error": f"search backend failed: {exc}"}
    except (OSError, ValueError, RuntimeError, KeyError, AttributeError) as exc:
        search_res = {"error": str(exc)}
    except BaseException as exc:  # noqa: BLE001 - never let a search backend crash the HTTP pipeline
        search_res = {"error": f"search backend failed: {exc}"}

    elapsed_ms = round((time.perf_counter() - t0) * 1000.0, 1)

    if search_res.get("error"):
        err_text = str(search_res["error"])
        return {
            "mode": norm_mode,
            "search_depth": norm_depth,
            "query": clean_q,
            "intent": intent,
            "results": [],
            "results_count": 0,
            "scraped_count": 0,
            "estimated_tokens": 0,
            "max_tokens": max_tok,
            "elapsed_ms": elapsed_ms,
            "error": err_text,
            "markdown": f"### 検索エラー\n\n{err_text}",
            "rag_prompt": "",
        }

    raw_results = search_res.get("results", [])
    direct_answers = search_res.get("answers", [])
    infoboxes = search_res.get("infoboxes", [])

    if not raw_results:
        empty_md = f"## Deep Search Results: `{clean_q}`\n\n該当する検索結果が見つかりませんでした。"
        return {
            "mode": norm_mode,
            "search_depth": norm_depth,
            "query": clean_q,
            "intent": intent,
            "results": [],
            "results_count": 0,
            "scraped_count": 0,
            "answers": direct_answers,
            "infoboxes": infoboxes,
            "estimated_tokens": TokenBudgeter.estimate_tokens(empty_md),
            "max_tokens": max_tok,
            "elapsed_ms": elapsed_ms,
            "markdown": empty_md,
            "rag_prompt": TokenBudgeter.build_rag_prompt(clean_q, empty_md),
        }

    # Domain authority & spam filtering
    scorer = DomainScorer()
    scored_items = scorer.score_results(
        raw_results,
        include_domains=final_inc,
        exclude_domains=final_exc,
    )
    top_candidates = scored_items[:max_res]

    # Speculative fetching & BM25 highlight extraction (for deep advanced/code modes)
    should_scrape = norm_mode == "deep" and norm_depth in ("advanced", "code") and include_highlights
    if should_scrape:
        fetcher = SpeculativeFetcher(scrape_func=scrape_func)
        extractor = BM25PassageExtractor()
        fetcher.fetch_pages(
            top_candidates,
            max_fetch=max_res,
            scrape_length=scrape_len,
            timeout=float(timeout) if timeout is not None and timeout > 0 else 6.0,
            base_url=base_url,
        )

        for item in top_candidates:
            if item.is_scraped and item.full_content:
                item.highlights = extractor.extract_highlights(item.full_content, clean_q, top_k=2)
            else:
                item.highlights = [item.content] if item.content else []
    else:
        for item in top_candidates:
            item.highlights = [item.content] if item.content else []

    header_label = "Fast Search Results" if norm_mode == "fast" else "Deep Search Results"
    packed_markdown = TokenBudgeter.pack_markdown(
        query=clean_q,
        items=top_candidates,
        max_tokens=max_tok,
        direct_answers=direct_answers,
        intent=intent,
        header_label=header_label,
    )
    elapsed_ms = round((time.perf_counter() - t0) * 1000.0, 1)
    est_tokens = TokenBudgeter.estimate_tokens(packed_markdown)
    scraped_count = sum(1 for it in top_candidates if it.is_scraped)

    return {
        "mode": norm_mode,
        "search_depth": norm_depth,
        "query": clean_q,
        "intent": intent,
        "results_count": len(top_candidates),
        "scraped_count": scraped_count,
        "results": [it.to_dict() for it in top_candidates],
        "answers": direct_answers,
        "infoboxes": infoboxes,
        "max_tokens": max_tok,
        "estimated_tokens": est_tokens,
        "elapsed_ms": elapsed_ms,
        "markdown": packed_markdown,
        "rag_prompt": TokenBudgeter.build_rag_prompt(clean_q, packed_markdown),
    }


def execute_deep_search(
    query: str,
    search_func: Callable[..., dict[str, Any]],
    scrape_func: Callable[..., dict[str, Any]],
    search_depth: str = "advanced",
    max_results: int = 5,
    include_highlights: bool = True,
    include_domains: list[str] | None = None,
    exclude_domains: list[str] | None = None,
    max_tokens: int = 3000,
    base_url: str | None = None,
    timeout: float | None = None,
) -> dict[str, Any]:
    """Execute the deep search pipeline (delegates to the unified search pipeline)."""
    depth_norm = (search_depth or "advanced").strip().lower()
    mode = "fast" if depth_norm in ("fast", "json_lite") else "deep"
    return execute_unified_search(
        query=query,
        search_func=search_func,
        scrape_func=scrape_func,
        mode=mode,
        search_depth=depth_norm,
        max_results=max_results,
        include_highlights=include_highlights,
        include_domains=include_domains,
        exclude_domains=exclude_domains,
        max_tokens=max_tokens,
        base_url=base_url,
        timeout=timeout,
    )
