#!/usr/bin/env python3
"""Reciprocal Rank Fusion (RRF) and Multi-Signal Scoring Module for SearXNG.

Implements:
- Standard RRF: sum(1 / (k + rank)) across multiple queries and engines
- Multi-engine consensus bonus
- Detailed score breakdown tracking (score_components)
- Partial results and engine failure resilience
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from deduplication import deduplicate_results
from url_normalizer import extract_domain, get_dedup_key


@dataclass
class ScoreComponents:
    """Individual explainable score factors contributing to final retrieval rank."""

    fusion: float = 0.0
    lexical_relevance: float = 0.0
    freshness: float = 0.0
    source_quality: float = 0.0
    engine_consensus: float = 0.0

    def to_dict(self) -> dict[str, float]:
        """Convert score components to rounded float dictionary."""
        return {
            "fusion": round(self.fusion, 4),
            "lexical_relevance": round(self.lexical_relevance, 4),
            "freshness": round(self.freshness, 4),
            "source_quality": round(self.source_quality, 4),
            "engine_consensus": round(self.engine_consensus, 4),
        }


@dataclass(frozen=True)
class FusionConfig:
    """Configuration for Reciprocal Rank Fusion and consensus weighting."""

    # Standard RRF smoothing constant (default: 60)
    rrf_k: int = 60
    # Bonus multiplier per additional agreeing search engine
    consensus_bonus_per_engine: float = 0.15
    # Maximum consensus bonus cap
    max_consensus_bonus: float = 0.45
    # Bonus multiplier when an item matches multiple expanded queries
    multi_query_bonus: float = 0.20
    # Maximum multi-query bonus cap
    max_multi_query_bonus: float = 0.40

    def __init__(
        self,
        rrf_k: int = 60,
        consensus_bonus_per_engine: float = 0.15,
        max_consensus_bonus: float = 0.45,
        multi_query_bonus: float = 0.20,
        max_multi_query_bonus: float = 0.40,
        k: float | None = None,
        consensus_weight: float | None = None,
    ) -> None:
        object.__setattr__(self, "rrf_k", int(k) if k is not None else int(rrf_k))
        object.__setattr__(
            self,
            "consensus_bonus_per_engine",
            float(consensus_weight) if consensus_weight is not None else float(consensus_bonus_per_engine),
        )
        object.__setattr__(self, "max_consensus_bonus", float(max_consensus_bonus))
        object.__setattr__(self, "multi_query_bonus", float(multi_query_bonus))
        object.__setattr__(self, "max_multi_query_bonus", float(max_multi_query_bonus))


@dataclass
class EngineRankItem:
    """Input rank record from an engine or query."""

    url: str
    title: str = ""
    snippet: str = ""
    engine: str = "unknown"
    rank: int = 1
    query: str = ""
    canonical_url: str = ""


@dataclass
class FusedItem:
    """Output fused document with consensus scores."""

    url: str
    title: str
    snippet: str
    score: float
    engines: list[str]
    matched_queries: list[str]
    score_components: ScoreComponents
    raw_item: dict[str, Any] = field(default_factory=dict)


RRFConfig = FusionConfig


class ReciprocalRankFusion:
    """Aggregates and ranks search results across multiple queries and search engines."""

    def __init__(self, config: FusionConfig | None = None) -> None:
        self.config = config or FusionConfig()

    def fuse_query_runs(
        self,
        query_runs: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Fuse search results across multiple query executions and engines.

        Args:
            query_runs: List of query results, each formatted as:
                {
                    "query": str,
                    "results": list[dict[str, Any]],
                    "failed_engines": list[str] (optional),
                }

        Returns:
            Deduplicated, RRF-scored list of document dictionaries.
        """
        if not query_runs:
            return []

        # Map dedup_key -> aggregated item state
        # State: {
        #   "item": dict,
        #   "rrf_score": float,
        #   "engine_ranks": dict[str, int],  # engine -> best rank
        #   "query_ranks": dict[str, int],   # query -> best rank
        #   "matched_queries": set[str],
        #   "engines": set[str],
        # }
        doc_states: dict[str, dict[str, Any]] = {}

        for run in query_runs:
            q_text = str(run.get("query") or "").strip()
            raw_results = run.get("results") or []
            if not isinstance(raw_results, list):
                continue

            # First deduplicate within the query run to avoid duplicate spam from same engine
            deduped_run_results = deduplicate_results(raw_results, query=q_text)

            for rank_idx, item in enumerate(deduped_run_results, start=1):
                url = str(item.get("url") or "").strip()
                if not url:
                    continue

                d_key = get_dedup_key(url)
                eng = str(item.get("engine") or item.get("source") or "unknown").strip()
                item_engines: list[str] = item.get("engines") or ([eng] if eng else [])

                rrf_term = 1.0 / (self.config.rrf_k + rank_idx)

                if d_key not in doc_states:
                    doc_states[d_key] = {
                        "item": dict(item),
                        "rrf_score": rrf_term,
                        "engine_ranks": {e: rank_idx for e in item_engines},
                        "query_ranks": {q_text: rank_idx} if q_text else {},
                        "matched_queries": {q_text} if q_text else set(),
                        "engines": set(item_engines),
                    }
                else:
                    state = doc_states[d_key]
                    state["rrf_score"] += rrf_term
                    if q_text:
                        state["matched_queries"].add(q_text)
                        if q_text not in state["query_ranks"] or rank_idx < state["query_ranks"][q_text]:
                            state["query_ranks"][q_text] = rank_idx

                    for e in item_engines:
                        state["engines"].add(e)
                        if e not in state["engine_ranks"] or rank_idx < state["engine_ranks"][e]:
                            state["engine_ranks"][e] = rank_idx

                    # Merge duplicate URLs and content
                    curr_item = state["item"]
                    existing_dups = curr_item.setdefault("duplicate_urls", [])
                    if url not in existing_dups and url != curr_item.get("url"):
                        existing_dups.append(url)
                    for dup in item.get("duplicate_urls", []):
                        if dup not in existing_dups and dup != curr_item.get("url"):
                            existing_dups.append(dup)

                    # Update content if new item has longer snippet
                    if len(str(item.get("content") or "")) > len(str(curr_item.get("content") or "")):
                        curr_item["content"] = item.get("content")

        if not doc_states:
            return []

        # Find max raw RRF score to normalize between 0.0 and 1.0
        max_raw_rrf = max(s["rrf_score"] for s in doc_states.values()) or 1.0

        fused_items: list[dict[str, Any]] = []
        for d_key, state in doc_states.items():
            base_item = state["item"]
            normalized_rrf = state["rrf_score"] / max_raw_rrf

            # Calculate multi-engine consensus bonus
            engine_count = len(state["engines"])
            if engine_count > 1:
                consensus_bonus = min(
                    (engine_count - 1) * self.config.consensus_bonus_per_engine,
                    self.config.max_consensus_bonus,
                )
            else:
                consensus_bonus = 0.0

            # Calculate multi-query match bonus
            query_count = len(state["matched_queries"])
            if query_count > 1:
                query_bonus = min(
                    (query_count - 1) * self.config.multi_query_bonus,
                    self.config.max_multi_query_bonus,
                )
            else:
                query_bonus = 0.0

            total_fusion_score = normalized_rrf + consensus_bonus + query_bonus

            base_item["engines"] = sorted(state["engines"])
            base_item["engine_ranks"] = state["engine_ranks"]
            base_item["matched_queries"] = sorted(state["matched_queries"])
            base_item["domain"] = base_item.get("domain") or extract_domain(str(base_item.get("url") or ""))

            # Attach initial score components
            comps = ScoreComponents(
                fusion=total_fusion_score,
                lexical_relevance=0.0,
                freshness=0.0,
                source_quality=0.0,
                engine_consensus=consensus_bonus,
            )
            base_item["score"] = total_fusion_score
            base_item["score_components"] = comps

            fused_items.append(base_item)

        # Sort by total fusion score descending
        fused_items.sort(key=lambda x: float(x.get("score") or 0.0), reverse=True)
        return fused_items


def fuse_results(
    query_runs: list[dict[str, Any]],
    config: FusionConfig | None = None,
) -> list[dict[str, Any]]:
    """Convenience helper for Reciprocal Rank Fusion."""
    fusion = ReciprocalRankFusion(config=config)
    return fusion.fuse_query_runs(query_runs)


def reciprocal_rank_fusion(
    candidates: list[EngineRankItem],
    config: FusionConfig | None = None,
) -> list[FusedItem]:
    """Apply Reciprocal Rank Fusion on candidates from multiple queries and engines."""
    cfg = config or FusionConfig()
    query_runs_map: dict[str, list[dict[str, Any]]] = {}
    for c in candidates:
        q = c.query or "default"
        item_dict = {
            "url": c.url,
            "title": c.title,
            "content": c.snippet,
            "snippet": c.snippet,
            "engine": c.engine,
            "source": c.engine,
            "canonical_url": c.canonical_url,
        }
        query_runs_map.setdefault(q, []).append(item_dict)

    query_runs = [{"query": q, "results": res} for q, res in query_runs_map.items()]
    fused_dicts = ReciprocalRankFusion(config=cfg).fuse_query_runs(query_runs)

    out: list[FusedItem] = []
    for d in fused_dicts:
        comps = d.get("score_components")
        if not isinstance(comps, ScoreComponents):
            comps = ScoreComponents()
        out.append(
            FusedItem(
                url=str(d.get("url") or ""),
                title=str(d.get("title") or ""),
                snippet=str(d.get("content") or d.get("snippet") or ""),
                score=float(d.get("score") or 0.0),
                engines=list(d.get("engines") or []),
                matched_queries=list(d.get("matched_queries") or []),
                score_components=comps,
                raw_item=d,
            )
        )
    return out

