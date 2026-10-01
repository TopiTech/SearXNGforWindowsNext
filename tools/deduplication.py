#!/usr/bin/env python3
"""Multi-stage Deduplication and Clustering Module for SearXNG Retrieval.

Implements phased deduplication:
1. Exact normalized URL matching
2. Canonical URL matching
3. Exact normalized title matching
4. Near-duplicate title matching (Levenshtein ratio / N-gram Jaccard)
5. Snippet and content similarity clustering
6. Mirror and reprint grouping into primary clusters
"""

from __future__ import annotations

import importlib
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any

from url_normalizer import extract_domain, get_dedup_key, normalize_url

try:
    _rf_fuzz: Any = importlib.import_module("rapidfuzz.fuzz")
    _HAS_RAPIDFUZZ = True
except (ImportError, ModuleNotFoundError):
    _rf_fuzz = None
    _HAS_RAPIDFUZZ = False


@dataclass(frozen=True)
class DedupConfig:
    """Centralized thresholds and parameters for deduplication."""

    # Near-duplicate title similarity threshold (0.0 to 1.0)
    title_similarity_threshold: float = 0.88
    # Lower threshold when both items originate from the same domain
    same_domain_title_threshold: float = 0.82
    # Minimum title character length to apply fuzzy matching (avoids false merges on "Home", "Docs")
    min_title_length_for_fuzzy: int = 12
    # Snippet/content near-duplicate similarity threshold
    snippet_similarity_threshold: float = 0.85
    # Minimum snippet character length to apply fuzzy matching
    min_snippet_length_for_fuzzy: int = 40
    # Enable canonical URL deduplication
    enable_canonical_dedup: bool = True


def normalize_title(title: str) -> str:
    """Normalize title for comparison: NFKC, lowercase, strip site suffixes like ' - Example'."""
    if not title:
        return ""
    norm = unicodedata.normalize("NFKC", title).strip().lower()
    # Remove bracketed editorial prefixes like 【最新】, [更新], etc.
    norm = re.sub(r"^[\[【][^\]】]+[\]】]\s*", "", norm)
    # Remove common site name suffixes often appended by CMS: "Title - SiteName", "Title | SiteName"
    norm = re.sub(r"\s+[-–—|:]\s+[^-–—|:]+$", "", norm)
    # Remove excessive whitespace and punctuation
    norm = re.sub(r"[\s_]+", " ", norm).strip()
    return norm


def levenshtein_ratio(s1: str, s2: str) -> float:
    """Calculate normalized Levenshtein similarity ratio between 0.0 and 1.0.

    Uses rapidfuzz if available; otherwise uses an optimized pure-Python dynamic programming approach.
    """
    if _HAS_RAPIDFUZZ and _rf_fuzz is not None:
        return float(_rf_fuzz.ratio(s1, s2) / 100.0)

    if s1 == s2:
        return 1.0
    len1, len2 = len(s1), len(s2)
    if len1 == 0 or len2 == 0:
        return 0.0

    # Ensure s1 is shorter to minimize space
    if len1 > len2:
        s1, s2 = s2, s1
        len1, len2 = len2, len1

    prev_row = list(range(len1 + 1))
    for i, c2 in enumerate(s2):
        curr_row = [i + 1] * (len1 + 1)
        for j, c1 in enumerate(s1):
            insertions = prev_row[j + 1] + 1
            deletions = curr_row[j] + 1
            substitutions = prev_row[j] + (c1 != c2)
            curr_row[j + 1] = min(insertions, deletions, substitutions)
        prev_row = curr_row

    dist = prev_row[len1]
    return 1.0 - (dist / max(len1, len2))


def ngram_jaccard_similarity(s1: str, s2: str, n: int = 2) -> float:
    """Compute character N-gram Jaccard similarity (well-suited for Japanese/CJK text)."""
    if s1 == s2:
        return 1.0
    if len(s1) < n or len(s2) < n:
        return levenshtein_ratio(s1, s2)

    set1 = {s1[i : i + n] for i in range(len(s1) - n + 1)}
    set2 = {s2[i : i + n] for i in range(len(s2) - n + 1)}

    intersection = len(set1 & set2)
    union = len(set1 | set2)
    if union == 0:
        return 0.0
    return intersection / union


def text_similarity(s1: str, s2: str) -> float:
    """Blended similarity metric combining Levenshtein ratio and character bi-gram Jaccard."""
    if not s1 or not s2:
        return 0.0
    lev = levenshtein_ratio(s1, s2)
    # If high Levenshtein, return immediately
    if lev >= 0.90:
        return lev
    jac = ngram_jaccard_similarity(s1, s2, n=2)
    return max(lev, jac)


def is_near_duplicate_title(t1: str, t2: str, threshold: float = 0.88) -> bool:
    """Check if two titles are near duplicates after normalization."""
    norm1 = normalize_title(t1)
    norm2 = normalize_title(t2)
    if not norm1 or not norm2:
        return False
    if norm1 == norm2:
        return True
    return text_similarity(norm1, norm2) >= threshold


@dataclass
class DeduplicatedCluster:
    """A primary document cluster containing the best representative item and its duplicates."""

    primary_item: dict[str, Any]
    duplicate_urls: list[str] = field(default_factory=list)
    engines: list[str] = field(default_factory=list)
    matched_queries: list[str] = field(default_factory=list)
    dedup_reason: str = ""


class ResultDeduplicator:
    """Phased deduplication engine for search results."""

    def __init__(self, config: DedupConfig | None = None) -> None:
        self.config = config or DedupConfig()

    def deduplicate(
        self,
        items: list[dict[str, Any]],
        query: str = "",
    ) -> list[dict[str, Any]]:
        """Deduplicate a list of raw search result dictionaries.

        Preserves primary item with all contributing engines and matched queries recorded.
        """
        if not items:
            return []

        clusters: list[DeduplicatedCluster] = []

        for item in items:
            url = str(item.get("url") or "").strip()
            if not url:
                continue

            norm_url = normalize_url(url)
            dedup_url_key = get_dedup_key(url)
            canonical_url = str(item.get("canonical_url") or "").strip()
            norm_canonical = normalize_url(canonical_url) if canonical_url else ""
            canonical_key = get_dedup_key(canonical_url) if canonical_url else ""

            raw_title = str(item.get("title") or "").strip()
            norm_tit = normalize_title(raw_title)

            raw_snippet = str(item.get("content") or item.get("snippet") or "").strip()
            norm_snip = unicodedata.normalize("NFKC", raw_snippet).strip().lower()

            item_engines: list[str] = []
            eng = item.get("engine") or item.get("source")
            if eng:
                item_engines.append(str(eng).strip())
            engs = item.get("engines")
            if isinstance(engs, (list, tuple)):
                for e in engs:
                    if e and str(e) not in item_engines:
                        item_engines.append(str(e))

            item_matched_q: list[str] = []
            if query:
                item_matched_q.append(query)
            extra_q = item.get("matched_queries")
            if isinstance(extra_q, list):
                for q in extra_q:
                    if q and str(q) not in item_matched_q:
                        item_matched_q.append(str(q))

            # Check matching against existing clusters
            matched_cluster: DeduplicatedCluster | None = None
            match_reason = ""

            for cluster in clusters:
                c_item = cluster.primary_item
                c_url = str(c_item.get("url") or "")
                c_dedup_url_key = get_dedup_key(c_url)
                c_canonical = str(c_item.get("canonical_url") or "")
                c_canonical_key = get_dedup_key(c_canonical) if c_canonical else ""

                # 1. Exact normalized URL match
                if dedup_url_key and dedup_url_key == c_dedup_url_key:
                    matched_cluster = cluster
                    match_reason = "exact_url"
                    break

                # 2. Canonical URL match
                if self.config.enable_canonical_dedup:
                    if canonical_key and (canonical_key == c_canonical_key or canonical_key == c_dedup_url_key):
                        matched_cluster = cluster
                        match_reason = "canonical_url"
                        break
                    if c_canonical_key and c_canonical_key == dedup_url_key:
                        matched_cluster = cluster
                        match_reason = "canonical_url"
                        break

                c_title = str(c_item.get("title") or "")
                c_norm_tit = normalize_title(c_title)

                # 3. Exact normalized title match
                if norm_tit and c_norm_tit and norm_tit == c_norm_tit:
                    dom1 = str(item.get("domain") or extract_domain(str(item.get("url") or "")))
                    dom2 = str(c_item.get("domain") or extract_domain(str(c_item.get("url") or "")))
                    if dom1 and dom2 and dom1 == dom2:
                        matched_cluster = cluster
                        match_reason = "exact_title_same_domain"
                        break
                    elif len(norm_tit) >= 28 and len(norm_tit.split()) >= 4:
                        matched_cluster = cluster
                        match_reason = "exact_title_cross_domain"
                        break

                # 4. Near-duplicate title match
                if (
                    len(norm_tit) >= self.config.min_title_length_for_fuzzy
                    and len(c_norm_tit) >= self.config.min_title_length_for_fuzzy
                ):
                    dom1 = str(item.get("domain") or extract_domain(str(item.get("url") or "")))
                    dom2 = str(c_item.get("domain") or extract_domain(str(c_item.get("url") or "")))
                    threshold = (
                        self.config.same_domain_title_threshold
                        if (dom1 and dom1 == dom2)
                        else self.config.title_similarity_threshold
                    )
                    sim = text_similarity(norm_tit, c_norm_tit)
                    if sim >= threshold:
                        # If domains differ, never merge short/generic titles across different sites
                        if dom1 != dom2 and (len(norm_tit) < 28 or len(norm_tit.split()) < 4):
                            continue

                        # Extra validation: check if snippets are also somewhat aligned
                        if norm_snip and len(norm_snip) >= 20:
                            c_snip = unicodedata.normalize("NFKC", str(c_item.get("content") or "")).strip().lower()
                            if c_snip:
                                snip_sim = text_similarity(norm_snip[:150], c_snip[:150])
                                # Require non-trivial snippet correlation or same domain
                                if snip_sim >= 0.40 or dom1 == dom2:
                                    matched_cluster = cluster
                                    match_reason = f"fuzzy_title(sim={sim:.2f})"
                                    break
                        else:
                            matched_cluster = cluster
                            match_reason = f"fuzzy_title(sim={sim:.2f})"
                            break

                # 5. Near-duplicate snippet / mirror match
                if (
                    len(norm_snip) >= self.config.min_snippet_length_for_fuzzy
                    and len(str(c_item.get("content") or "")) >= self.config.min_snippet_length_for_fuzzy
                ):
                    c_snip = unicodedata.normalize("NFKC", str(c_item.get("content") or "")).strip().lower()
                    snip_sim = text_similarity(norm_snip[:300], c_snip[:300])
                    if snip_sim >= self.config.snippet_similarity_threshold:
                        matched_cluster = cluster
                        match_reason = f"fuzzy_snippet(sim={snip_sim:.2f})"
                        break

            if matched_cluster:
                # Merge into existing cluster
                if url not in matched_cluster.duplicate_urls:
                    matched_cluster.duplicate_urls.append(url)
                for eng in item_engines:
                    if eng not in matched_cluster.engines:
                        matched_cluster.engines.append(eng)
                for q in item_matched_q:
                    if q not in matched_cluster.matched_queries:
                        matched_cluster.matched_queries.append(q)

                # Prefer canonical URL or longer content if the new item is better quality
                p_item = matched_cluster.primary_item
                if not p_item.get("canonical_url") and norm_canonical:
                    p_item["canonical_url"] = norm_canonical
                if len(norm_snip) > len(str(p_item.get("content") or "")):
                    p_item["content"] = raw_snippet
            else:
                # Create a new cluster
                new_cluster = DeduplicatedCluster(
                    primary_item=dict(item),
                    duplicate_urls=[],
                    engines=list(item_engines),
                    matched_queries=list(item_matched_q),
                    dedup_reason=match_reason,
                )
                # Store normalized URL
                new_cluster.primary_item["normalized_url"] = norm_url
                if norm_canonical:
                    new_cluster.primary_item["canonical_url"] = norm_canonical
                clusters.append(new_cluster)

        # Build output items with consolidated metadata
        deduped_results: list[dict[str, Any]] = []
        for cluster in clusters:
            out_item = cluster.primary_item
            out_item["duplicate_urls"] = cluster.duplicate_urls
            out_item["engines"] = sorted(cluster.engines) if cluster.engines else [str(out_item.get("source") or "")]
            out_item["matched_queries"] = sorted(cluster.matched_queries)
            deduped_results.append(out_item)

        return deduped_results


def deduplicate_results(
    items: list[dict[str, Any]],
    query: str = "",
    config: DedupConfig | None = None,
) -> list[dict[str, Any]]:
    """Convenience helper to deduplicate search results."""
    deduplicator = ResultDeduplicator(config=config)
    return deduplicator.deduplicate(items, query=query)
