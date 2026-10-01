#!/usr/bin/env python3
"""Multilingual Lexical Reranking (BM25 with Word + CJK N-grams) for SearXNG.

Provides auditable, dependency-free lexical ranking supporting Japanese, English,
CJK, and mixed-language queries without external dictionaries or native binaries.
"""

from __future__ import annotations

import math
import re
import unicodedata
from dataclasses import dataclass
from typing import Any

from rank_fusion import ScoreComponents

# Standard stopwords for query and document distillation
STOP_WORDS: set[str] = {
    # English
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
    # Japanese particles and auxiliary verbs
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


@dataclass(frozen=True)
class LexicalConfig:
    """Parameters for BM25 lexical reranking."""

    k1: float = 1.5
    b: float = 0.75
    # Weight multipliers for different fields
    title_weight: float = 3.0
    heading_weight: float = 2.0
    content_weight: float = 1.0
    # Bonuses for exact contiguous phrase matches
    exact_title_bonus: float = 1.5
    exact_content_bonus: float = 0.8


class MultilingualTokenizer:
    """Extracts words for Latin/alphanumeric scripts and character 2-grams / 3-grams for CJK text."""

    CJK_RANGE_PAT = re.compile(r"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff]")
    LATIN_WORD_PAT = re.compile(r"[a-z0-9_+#.-]+")

    @classmethod
    def tokenize(cls, text: str) -> list[str]:
        """Convert text into tokens using words for English and N-grams for CJK."""
        if not text:
            return []

        norm = unicodedata.normalize("NFKC", text.lower())
        tokens: list[str] = []

        # 1. Extract Latin/alphanumeric words
        for w in cls.LATIN_WORD_PAT.findall(norm):
            if w not in STOP_WORDS and len(w) > 0:
                tokens.append(w)

        # 2. Extract CJK fragments and generate 2-grams & 3-grams
        # Group contiguous CJK characters
        cjk_blocks = re.findall(r"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff]+", norm)
        for block in cjk_blocks:
            b_len = len(block)
            if b_len == 1:
                if block not in STOP_WORDS:
                    tokens.append(block)
                continue

            # Bi-grams
            for i in range(b_len - 1):
                bg = block[i : i + 2]
                if bg not in STOP_WORDS:
                    tokens.append(bg)

            # Tri-grams for blocks of length >= 3
            if b_len >= 3:
                for i in range(b_len - 2):
                    tokens.append(block[i : i + 3])

        return tokens


class LexicalReranker:
    """Calculates field-weighted BM25 lexical relevance for search documents and passages."""

    def __init__(self, config: LexicalConfig | None = None) -> None:
        self.config = config or LexicalConfig()
        self.tokenizer = MultilingualTokenizer()

    def score_document(
        self,
        query: str,
        title: str,
        headings: list[str] | None,
        content: str,
        avgdl: float,
        df_map: dict[str, int],
        num_docs: int,
    ) -> float:
        """Calculate weighted BM25 score for a single document against a query."""
        q_tokens = self.tokenizer.tokenize(query)
        if not q_tokens:
            return 0.0

        title_tokens = self.tokenizer.tokenize(title)
        headings_tokens = self.tokenizer.tokenize(" ".join(headings or []))
        content_tokens = self.tokenizer.tokenize(content)

        doc_len = (
            len(title_tokens) * self.config.title_weight
            + len(headings_tokens) * self.config.heading_weight
            + len(content_tokens) * self.config.content_weight
        )
        if doc_len == 0:
            return 0.0

        # Term frequency per field
        tf_title: dict[str, int] = {}
        for t in title_tokens:
            tf_title[t] = tf_title.get(t, 0) + 1

        tf_headings: dict[str, int] = {}
        for t in headings_tokens:
            tf_headings[t] = tf_headings.get(t, 0) + 1

        tf_content: dict[str, int] = {}
        for t in content_tokens:
            tf_content[t] = tf_content.get(t, 0) + 1

        score = 0.0
        norm_avgdl = max(avgdl, 1.0)

        for qt in set(q_tokens):
            q_df = df_map.get(qt, 0)
            idf = math.log(1.0 + (num_docs - q_df + 0.5) / (q_df + 0.5))

            # Weighted term frequency across fields
            w_tf = (
                tf_title.get(qt, 0) * self.config.title_weight
                + tf_headings.get(qt, 0) * self.config.heading_weight
                + tf_content.get(qt, 0) * self.config.content_weight
            )
            if w_tf <= 0:
                continue

            numerator = w_tf * (self.config.k1 + 1.0)
            denominator = w_tf + self.config.k1 * (1.0 - self.config.b + self.config.b * (doc_len / norm_avgdl))
            score += idf * (numerator / max(denominator, 0.001))

        # Bonuses for exact continuous string match
        q_clean = query.strip().lower()
        if q_clean and len(q_clean) >= 3:
            if q_clean in title.lower():
                score += self.config.exact_title_bonus
            if q_clean in content.lower():
                score += self.config.exact_content_bonus

        return max(score, 0.0)

    def rerank(
        self,
        query: str,
        items: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Compute lexical scores for all items and update score_components."""
        if not items or not query.strip():
            return items

        q_tokens = set(self.tokenizer.tokenize(query))
        num_docs = len(items)

        # Pre-compute document tokens and lengths
        doc_data: list[tuple[list[str], list[str], list[str], float]] = []
        df_map: dict[str, int] = {qt: 0 for qt in q_tokens}

        total_doc_len = 0.0
        for item in items:
            t_toks = self.tokenizer.tokenize(str(item.get("title") or ""))
            h_toks = self.tokenizer.tokenize(" ".join(item.get("headings") or []))
            c_toks = self.tokenizer.tokenize(str(item.get("content") or item.get("snippet") or ""))

            w_len = (
                len(t_toks) * self.config.title_weight
                + len(h_toks) * self.config.heading_weight
                + len(c_toks) * self.config.content_weight
            )
            total_doc_len += w_len

            all_seen_terms = set(t_toks) | set(h_toks) | set(c_toks)
            for qt in q_tokens:
                if qt in all_seen_terms:
                    df_map[qt] += 1

            doc_data.append((t_toks, h_toks, c_toks, w_len))

        avgdl = total_doc_len / max(num_docs, 1)

        raw_scores: list[float] = []
        for idx, item in enumerate(items):
            title = str(item.get("title") or "")
            headings = item.get("headings")
            content = str(item.get("content") or item.get("snippet") or "")
            s = self.score_document(
                query=query,
                title=title,
                headings=headings,
                content=content,
                avgdl=avgdl,
                df_map=df_map,
                num_docs=num_docs,
            )
            raw_scores.append(s)

        max_score = max(raw_scores) if raw_scores else 1.0
        if max_score <= 0.0:
            max_score = 1.0

        for idx, item in enumerate(items):
            norm_lex = raw_scores[idx] / max_score
            item["lexical_score"] = norm_lex

            comps = item.get("score_components")
            if isinstance(comps, ScoreComponents):
                comps.lexical_relevance = norm_lex
            elif isinstance(comps, dict):
                comps["lexical_relevance"] = norm_lex

        return items


def rerank_lexical(
    query: str,
    items: list[dict[str, Any]],
    config: LexicalConfig | None = None,
) -> list[dict[str, Any]]:
    """Convenience helper to apply multilingual lexical BM25 reranking."""
    reranker = LexicalReranker(config=config)
    return reranker.rerank(query, items)


class BM25Reranker:
    """Standard BM25 corpus ranker for tokenized document lists."""

    def __init__(self, corpus: list[list[str]], k1: float = 1.5, b: float = 0.75) -> None:
        self.corpus = corpus
        self.k1 = k1
        self.b = b
        self.num_docs = len(corpus)
        self.avgdl = sum(len(doc) for doc in corpus) / max(self.num_docs, 1)
        self.df_map: dict[str, int] = {}
        for doc in corpus:
            for term in set(doc):
                self.df_map[term] = self.df_map.get(term, 0) + 1

    def score(self, query_tokens: list[str]) -> list[float]:
        """Compute BM25 score for all documents against query tokens."""
        scores: list[float] = []
        for doc in self.corpus:
            doc_len = len(doc)
            tf_map: dict[str, int] = {}
            for t in doc:
                tf_map[t] = tf_map.get(t, 0) + 1
            doc_score = 0.0
            for qt in set(query_tokens):
                tf = tf_map.get(qt, 0)
                if tf <= 0:
                    continue
                df = self.df_map.get(qt, 0)
                idf = math.log(1.0 + (self.num_docs - df + 0.5) / (df + 0.5))
                num = tf * (self.k1 + 1.0)
                den = tf + self.k1 * (1.0 - self.b + self.b * (doc_len / max(self.avgdl, 1.0)))
                doc_score += idf * (num / max(den, 0.001))
            scores.append(doc_score)
        return scores


def tokenize_for_bm25(text: str) -> list[str]:
    """Tokenize text into words and CJK character N-grams."""
    return MultilingualTokenizer.tokenize(text)


CJKTokenizer = MultilingualTokenizer


def compute_field_lexical_score(
    query: str,
    title: str,
    headings: list[str] | None = None,
    content: str = "",
) -> float:
    """Calculate field-weighted BM25 lexical score for a single document."""
    reranker = LexicalReranker()
    q_toks = MultilingualTokenizer.tokenize(query)
    df_map = {qt: 1 for qt in q_toks}
    return reranker.score_document(
        query=query,
        title=title,
        headings=headings,
        content=content,
        avgdl=100.0,
        df_map=df_map,
        num_docs=1,
    )
