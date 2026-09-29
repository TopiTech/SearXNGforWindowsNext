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
import urllib.parse
from dataclasses import dataclass, field
from typing import Any, Callable

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
    "a", "an", "the", "and", "or", "but", "if", "then", "of", "to", "for", "in", "on", "at",
    "by", "with", "from", "about", "how", "what", "why", "when", "where", "which", "who",
    "is", "are", "was", "were", "be", "been", "being", "do", "does", "did", "have", "has",
    "had", "it", "its", "this", "that", "these", "those", "can", "could", "should", "would",
    "please", "tell", "me", "show", "find", "search", "give",
    "の", "に", "は", "を", "た", "が", "で", "て", "と", "し", "れ", "さ", "ある", "いる", "も", "する",
    "から", "な", "こと", "として", "い", "や", "れる", "など", "なっ", "ない", "この", "ため", "その",
    "について", "教えて", "方法", "どうやって",
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
        netloc = parsed.netloc.lower().split(":")[0]
        # Remove leading www.
        if netloc.startswith("www."):
            netloc = netloc[4:]
        return netloc
    except Exception:
        return ""


class QueryOptimizer:
    """Analyzes and optimizes natural language search queries for AI agents."""

    CODE_KEYWORDS: set[str] = {
        "error", "exception", "traceback", "syntax", "def", "class", "function",
        "api", "method", "bug", "crash", "segfault", "module", "import", "package",
        "npm", "pip", "cargo", "go", "python", "typescript", "javascript", "rust",
        "react", "fastapi", "docker", "k8s", "kubernetes", "async", "await", "null",
        "undefined", "pointer", "regex", "sql", "hook", "component", "lifespan",
    }

    ACADEMIC_KEYWORDS: set[str] = {
        "paper", "arxiv", "theorem", "proof", "dataset", "benchmark", "survey",
        "algorithm", "evaluation", "ablation", "transformer", "neural", "deep learning",
        "model", "parameters", "citation",
    }

    NEWS_KEYWORDS: set[str] = {
        "news", "announcement", "announced", "release", "released", "vulnerability",
        "cve", "breaking", "update", "latest", "today", "yesterday", "launch",
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
                domain = token[5:].strip().lower()
                if domain.startswith("www."):
                    domain = domain[4:]
                if domain:
                    include_domains.append(domain)
            elif lower.startswith("-site:") and len(token) > 6:
                domain = token[6:].strip().lower()
                if domain.startswith("www."):
                    domain = domain[4:]
                if domain:
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
        if domain.startswith("docs.") or domain.startswith("doc.") or ".readthedocs." in domain:
            return 1.8

        return 1.0

    def score_results(
        self,
        raw_results: list[dict[str, Any]],
        include_domains: list[str] | None = None,
        exclude_domains: list[str] | None = None,
    ) -> list[SearchResultItem]:
        """Filter and score raw search results, returning ordered items."""
        inc_set = set(d.lower() for d in (include_domains or []))
        exc_set = set(d.lower() for d in (exclude_domains or []))

        items: list[SearchResultItem] = []
        total = len(raw_results)

        for rank, r in enumerate(raw_results):
            url = r.get("url", "").strip()
            if not url:
                continue

            dom = extract_domain(url)

            # Apply explicit include filters
            if inc_set:
                if not any(dom == target or dom.endswith("." + target) for target in inc_set):
                    continue

            # Apply explicit exclude filters
            if exc_set:
                if any(dom == target or dom.endswith("." + target) for target in exc_set):
                    continue

            # Base score inversely proportional to original rank: 1.0 down to 0.1
            base_score = 1.0 - (rank / max(total, 1)) * 0.7

            # Engine score if provided by SearXNG
            raw_score = r.get("score")
            if isinstance(raw_score, (int, float)) and raw_score > 0:
                base_score = (base_score + min(float(raw_score), 5.0) / 5.0) / 2.0

            dom_weight = self.get_domain_weight(dom)
            final_score = base_score * dom_weight

            item = SearchResultItem(
                title=r.get("title", "").strip(),
                url=url,
                domain=dom,
                content=r.get("content", "").strip(),
                source=str(r.get("source", "")).strip(),
                score=final_score,
                published_date=str(r.get("published_date") or "").strip(),
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
    ) -> list[SearchResultItem]:
        """Concurrently scrape top items and populate full_content."""
        to_fetch = items[:max_fetch]
        if not to_fetch:
            return items

        def _do_scrape(item: SearchResultItem) -> SearchResultItem:
            try:
                res = self.scrape_func(item.url, max_length=scrape_length, timeout=timeout)
                err = res.get("error")
                content = res.get("content", "").strip()
                if err:
                    item.scrape_error = err
                    item.is_scraped = False
                elif content:
                    item.full_content = content
                    item.is_scraped = True
                else:
                    item.scrape_error = "本文が見つかりませんでした"
                    item.is_scraped = False
            except Exception as e:
                item.scrape_error = str(e)
                item.is_scraped = False
            return item

        with concurrent.futures.ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures = [executor.submit(_do_scrape, it) for it in to_fetch]
            concurrent.futures.wait(futures, timeout=timeout + 2.0)

        return items


class TokenBudgeter:
    """Manages token budgeting and packs structured Markdown for AI agents."""

    @staticmethod
    def estimate_tokens(text: str) -> int:
        """Roughly estimate token count (English ~4 chars/token, CJK ~1.5 chars/token)."""
        cjk_chars = len(re.findall(r"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff]", text))
        other_chars = len(text) - cjk_chars
        return int(cjk_chars / 1.5 + other_chars / 4.0)

    @classmethod
    def pack_markdown(
        cls,
        query: str,
        items: list[SearchResultItem],
        max_tokens: int = 3000,
        direct_answers: list[str] | None = None,
        intent: str = "general",
    ) -> str:
        """Pack search highlights and sources into concise, high-density Markdown."""
        lines: list[str] = [f"## Deep Search Results: `{query}` (Intent: `{intent}`)\n"]

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
            score_str = f" `[relevance: {item.score:.2f}]`"

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
    """Execute the full deep search pipeline (Exa/Tavily-like one-pass search).

    Pipeline:
    1. Parse query and extract domain operators.
    2. Classify query intent and determine optimal engine routing.
    3. Perform SearXNG meta-search using json_lite.
    4. Score and filter results with DomainScorer.
    5. Speculatively fetch top N pages in parallel.
    6. Extract BM25 highlights from full page text.
    7. Return structured dictionary with packed markdown.
    """
    clean_q, explicit_inc, explicit_exc = QueryOptimizer.parse_query(query)
    if not clean_q:
        return {
            "query": "",
            "intent": "general",
            "results": [],
            "error": "検索クエリが空です。検索したいキーワードを指定してください。",
            "markdown": "検索クエリが空です。",
        }

    # Merge explicit domain filters
    final_inc = list(set((include_domains or []) + explicit_inc))
    final_exc = list(set((exclude_domains or []) + explicit_exc))

    intent = QueryOptimizer.classify_intent(clean_q)
    categories, engines = QueryOptimizer.get_routing(intent)

    # Perform initial meta-search
    # Fetch slightly more (e.g. 15) to allow domain filtering and reranking
    search_res = search_func(
        query=clean_q,
        count=max(max_results * 3, 15),
        categories=categories,
        engines=engines,
        base_url=base_url,
        timeout=timeout,
    )

    if search_res.get("error"):
        return {
            "query": clean_q,
            "intent": intent,
            "results": [],
            "error": search_res["error"],
            "markdown": f"### 検索エラー\n\n{search_res['error']}",
        }

    raw_results = search_res.get("results", [])
    direct_answers = search_res.get("answers", [])

    if not raw_results:
        return {
            "query": clean_q,
            "intent": intent,
            "results": [],
            "answers": direct_answers,
            "markdown": f"## Deep Search Results: `{clean_q}`\n\n該当する検索結果が見つかりませんでした。",
        }

    # Step 4: Domain authority & spam filtering
    scorer = DomainScorer()
    scored_items = scorer.score_results(
        raw_results,
        include_domains=final_inc,
        exclude_domains=final_exc,
    )

    # Select top candidates for deep scraping
    top_candidates = scored_items[:max_results]

    # Step 5 & 6: Speculative fetching & Highlight extraction
    if search_depth in ("advanced", "code") and include_highlights:
        fetcher = SpeculativeFetcher(scrape_func=scrape_func)
        extractor = BM25PassageExtractor()

        # Fetch in parallel
        fetcher.fetch_pages(top_candidates, max_fetch=max_results)

        for item in top_candidates:
            if item.is_scraped and item.full_content:
                # Extract 1-3 highlights using BM25
                item.highlights = extractor.extract_highlights(item.full_content, clean_q, top_k=2)
            else:
                # Fallback to search snippet
                item.highlights = [item.content] if item.content else []
    else:
        # Basic depth uses snippets only
        for item in top_candidates:
            item.highlights = [item.content] if item.content else []

    # Step 7: Pack results and Markdown
    packed_markdown = TokenBudgeter.pack_markdown(
        query=clean_q,
        items=top_candidates,
        max_tokens=max_tokens,
        direct_answers=direct_answers,
        intent=intent,
    )

    return {
        "query": clean_q,
        "intent": intent,
        "results_count": len(top_candidates),
        "results": [it.to_dict() for it in top_candidates],
        "answers": direct_answers,
        "markdown": packed_markdown,
    }
