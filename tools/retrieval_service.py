#!/usr/bin/env python3
"""Unified Retrieval Service for SearXNG for Windows Next.

Implements the end-to-end logical pipeline:
Query Normalization -> Intent Classification -> Deterministic Expansion ->
Multi-Query Search -> URL Normalization -> Deduplication -> RRF ->
Lexical BM25 Reranking -> Top Page Scraping -> Heading Passage Chunking ->
Passage BM25 Reranking -> GenAI Structured Response (json_ai / evidence_json).
"""

from __future__ import annotations

import concurrent.futures
import logging
import threading
import time
from collections.abc import Callable
from concurrent.futures import Future
from typing import Any

from cross_encoder_rerank import CrossEncoderReranker
from deduplication import ResultDeduplicator
from lexical_rerank import LexicalReranker
from passage_chunker import HeadingPassageChunker, HTMLMetadataExtractor, SecurityScanner
from query_pipeline import QueryProcessor
from rank_fusion import ReciprocalRankFusion, ScoreComponents
from retrieval_models import (
    BUDGETS,
    RetrievalResponse,
    RetrievalResultItem,
    classify_source_type,
    compute_source_quality,
)
from url_normalizer import extract_domain, is_safe_retrieval_url, normalize_url

logger = logging.getLogger(__name__)


class RetrievalService:
    """Unified service orchestrating high-quality retrieval for AI agents and LLMs."""

    # Class-level shared stateless components to prevent GC pressure and re-allocation
    _shared_query_processor: QueryProcessor | None = None
    _shared_deduplicator: ResultDeduplicator | None = None
    _shared_rank_fusion: ReciprocalRankFusion | None = None
    _shared_lexical_reranker: LexicalReranker | None = None
    _shared_passage_chunker: HeadingPassageChunker | None = None
    _shared_cross_encoder: CrossEncoderReranker | None = None

    query_processor: QueryProcessor
    deduplicator: ResultDeduplicator
    rank_fusion: ReciprocalRankFusion
    lexical_reranker: LexicalReranker
    passage_chunker: HeadingPassageChunker
    cross_encoder: CrossEncoderReranker

    def __init__(
        self,
        search_func: Callable[..., dict[str, Any]] | None = None,
        scrape_func: Callable[..., dict[str, Any]] | None = None,
        cross_encoder: CrossEncoderReranker | None = None,
    ) -> None:
        self.search_func = search_func or (lambda **kwargs: {"results": []})
        self.scrape_func = scrape_func

        if RetrievalService._shared_query_processor is None:
            RetrievalService._shared_query_processor = QueryProcessor()
            RetrievalService._shared_deduplicator = ResultDeduplicator()
            RetrievalService._shared_rank_fusion = ReciprocalRankFusion()
            RetrievalService._shared_lexical_reranker = LexicalReranker()
            RetrievalService._shared_passage_chunker = HeadingPassageChunker()
            RetrievalService._shared_cross_encoder = CrossEncoderReranker()

        assert RetrievalService._shared_query_processor is not None
        assert RetrievalService._shared_deduplicator is not None
        assert RetrievalService._shared_rank_fusion is not None
        assert RetrievalService._shared_lexical_reranker is not None
        assert RetrievalService._shared_passage_chunker is not None
        assert RetrievalService._shared_cross_encoder is not None

        self.query_processor = RetrievalService._shared_query_processor
        self.deduplicator = RetrievalService._shared_deduplicator
        self.rank_fusion = RetrievalService._shared_rank_fusion
        self.lexical_reranker = RetrievalService._shared_lexical_reranker
        self.passage_chunker = RetrievalService._shared_passage_chunker
        self.cross_encoder = cross_encoder or RetrievalService._shared_cross_encoder

    def _fetch_query_results(self, **kwargs: Any) -> list[dict[str, Any]]:
        """Fetch raw results using self.search_func."""
        try:
            res = self.search_func(**kwargs)
            if isinstance(res, list):
                return res
            if isinstance(res, dict):
                return res.get("results") or []
            return []
        except Exception as exc:  # noqa: BLE001
            logger.warning("Search query failed: %s", exc)
            return []

    def _scrape_page(self, url: str, **kwargs: Any) -> dict[str, Any]:
        """Scrape page content using self.scrape_func."""
        if not self.scrape_func:
            return {"error": "no scraper configured"}
        try:
            return self.scrape_func(url, **kwargs)
        except Exception as exc:  # noqa: BLE001
            return {"error": str(exc)}

    def execute_retrieval(
        self,
        query: str,
        mode: str = "balanced",
        **kwargs: Any,
    ) -> RetrievalResponse:
        """Alias for search()."""
        return self.search(query=query, mode=mode, **kwargs)

    def _fetch_pages_concurrent(
        self,
        items: list[dict[str, Any]],
        max_pages: int,
        scrape_length: int,
        timeout: float,
        base_url: str | None = None,
    ) -> None:
        """Concurrently scrape top URLs with daemon threads and timeout protection."""
        if max_pages <= 0:
            return

        to_scrape = items[:max_pages]
        if not to_scrape:
            return

        sem = threading.Semaphore(min(len(to_scrape), 5))

        def _worker(fut: Future, url: str) -> None:
            with sem:
                if fut.cancelled():
                    return
                try:
                    kwargs: dict[str, Any] = {"max_length": scrape_length, "timeout": timeout}
                    if base_url is not None:
                        try:
                            res = self._scrape_page(url, base_url=base_url, **kwargs)
                        except TypeError:
                            res = self._scrape_page(url, **kwargs)
                    else:
                        res = self._scrape_page(url, **kwargs)
                    if not fut.cancelled():
                        try:
                            fut.set_result(res)
                        except (concurrent.futures.InvalidStateError, RuntimeError):
                            pass
                except BaseException as exc:  # noqa: BLE001
                    if not fut.cancelled():
                        try:
                            fut.set_exception(exc)
                        except (concurrent.futures.InvalidStateError, RuntimeError):
                            pass

        fut_map: dict[Future, dict[str, Any]] = {}
        for it in to_scrape:
            target_url = str(it.get("url") or "")
            if not target_url:
                continue
            if not is_safe_retrieval_url(target_url):
                it["raw_content"] = ""
                it["is_scraped"] = False
                it["scrape_error"] = "Blocked unsafe or non-HTTP retrieval URL"
                continue
            fut: Future = Future()
            t = threading.Thread(
                target=_worker,
                args=(fut, target_url),
                name=f"retrieval-scrape-{target_url[:30]}",
                daemon=True,
            )
            t.start()
            fut_map[fut] = it

        done, not_done = concurrent.futures.wait(fut_map.keys(), timeout=timeout)

        for fut in done:
            it = fut_map[fut]
            try:
                res = fut.result()
                err = res.get("error") if isinstance(res, dict) else "scrape error"
                content = (res.get("content") or "").strip() if isinstance(res, dict) else ""
                raw_html = res.get("raw_html") or "" if isinstance(res, dict) else ""
                if not err and content:
                    it["raw_content"] = content
                    it["raw_html"] = raw_html
                    it["is_scraped"] = True
                else:
                    it["raw_content"] = ""
                    it["is_scraped"] = False
                    it["scrape_error"] = str(err)
            except Exception as exc:  # noqa: BLE001
                it["raw_content"] = ""
                it["is_scraped"] = False
                it["scrape_error"] = str(exc)

        for fut in not_done:
            fut.cancel()
            it = fut_map[fut]
            it["raw_content"] = ""
            it["is_scraped"] = False
            it["scrape_error"] = "Scrape timed out"

    def search(
        self,
        query: str,
        mode: str = "balanced",
        count: int | None = None,
        categories: str = "",
        engines: str = "",
        time_range: str = "",
        include_domains: list[str] | None = None,
        exclude_domains: list[str] | None = None,
        base_url: str | None = None,
        timeout: float | None = None,
    ) -> RetrievalResponse:
        """Execute the end-to-end structured retrieval pipeline."""
        t0 = time.perf_counter()

        norm_mode = (mode or "balanced").strip().lower()
        if norm_mode not in BUDGETS:
            norm_mode = "balanced"
        budget = BUDGETS[norm_mode]

        # 1. Query Normalization & Intent Classification
        processed_q = self.query_processor.parse_and_normalize(query)
        if not processed_q.clean_text:
            return RetrievalResponse(
                query=processed_q,
                mode=norm_mode,
                warnings=["検索クエリが空です。"],
            )

        # Merge domain filters
        all_inc_domains = sorted(set(processed_q.include_domains + [d.lower() for d in (include_domains or []) if d]))
        all_exc_domains = sorted(set(processed_q.exclude_domains + [d.lower() for d in (exclude_domains or []) if d]))

        # 2. Deterministic Query Expansion
        expanded_q_list = self.query_processor.expand_query(processed_q, mode=norm_mode)
        all_search_queries = [processed_q.clean_text] + expanded_q_list

        # 3. Multi-Query Search Execution
        query_runs: list[dict[str, Any]] = []
        engines_used_set: set[str] = set()
        warnings_list: list[str] = []
        is_partial = False
        direct_answers: list[str] = []
        infoboxes: list[Any] = []

        eff_timeout = float(timeout) if timeout is not None and timeout > 0 else (budget.per_engine_timeout_ms / 1000.0)

        for q_exec in all_search_queries:
            search_args: dict[str, Any] = {
                "query": q_exec,
                "count": budget.max_results_per_query,
                "categories": categories,
                "engines": engines,
                "base_url": base_url,
                "timeout": eff_timeout,
            }
            if time_range:
                search_args["time_range"] = time_range

            try:
                fetched = self._fetch_query_results(**search_args)
            except Exception as exc:  # noqa: BLE001
                fetched = {"error": str(exc), "results": []}

            if isinstance(fetched, list):
                raw_results = fetched
                raw_run_res = {"results": fetched}
            elif isinstance(fetched, dict):
                raw_run_res = fetched
                if raw_run_res.get("error"):
                    warnings_list.append(f"Query '{q_exec}' error: {raw_run_res['error']}")
                    is_partial = True
                raw_results = raw_run_res.get("results") or []
            else:
                raw_results = []
                raw_run_res = {}

            # Collect direct answers and infoboxes
            for ans in raw_run_res.get("answers", []):
                ans_str = str(ans).strip()
                if ans_str and ans_str not in direct_answers:
                    direct_answers.append(ans_str)
            for ib in raw_run_res.get("infoboxes", []):
                if ib not in infoboxes:
                    infoboxes.append(ib)

            for r in raw_results:
                if isinstance(r, dict):
                    e = r.get("engine") or r.get("source")
                    if e:
                        engines_used_set.add(str(e))
                    if isinstance(r.get("engines"), (list, tuple)):
                        for eng_item in r["engines"]:
                            if eng_item:
                                engines_used_set.add(str(eng_item))

            query_runs.append({"query": q_exec, "results": raw_results})

        # 4. Filter Domain Constraints
        filtered_runs: list[dict[str, Any]] = []
        for run in query_runs:
            f_results: list[dict[str, Any]] = []
            for r in run["results"]:
                if not isinstance(r, dict):
                    continue
                u = str(r.get("url") or "")
                d = extract_domain(u)
                if all_inc_domains and not any(d == inc or d.endswith("." + inc) for inc in all_inc_domains):
                    continue
                if all_exc_domains and any(d == exc or d.endswith("." + exc) for exc in all_exc_domains):
                    continue
                f_results.append(r)
            filtered_runs.append({"query": run["query"], "results": f_results})

        # 5. Reciprocal Rank Fusion & Deduplication
        fused_items = self.rank_fusion.fuse_query_runs(filtered_runs)
        if not fused_items:
            elapsed_ms = (time.perf_counter() - t0) * 1000.0
            return RetrievalResponse(
                query=processed_q,
                mode=norm_mode,
                expanded_queries=expanded_q_list,
                engines_used=sorted(engines_used_set),
                partial=is_partial,
                elapsed_ms=elapsed_ms,
                results=[],
                warnings=warnings_list,
                answers=direct_answers,
                infoboxes=infoboxes,
            )

        candidate_items = fused_items[: budget.max_candidate_results]

        # 6. Lexical BM25 Reranking
        ranking_query = processed_q.clean_no_quotes or processed_q.clean_text
        self.lexical_reranker.rerank(ranking_query, candidate_items)

        # 7. Compute Blended Composite Score
        for item in candidate_items:
            comps: ScoreComponents = item["score_components"]
            dom = item.get("domain") or extract_domain(str(item.get("url") or ""))
            sq = compute_source_quality(dom)
            comps.source_quality = sq

            # Freshness score if query indicates freshness or published date is recent.
            # The date string must actually contain the requested year; a
            # non-matching or unparseable date previously still earned 0.8,
            # ranking stale 2015 pages above undated fresh results.
            fresh_score = 0.0
            pub_date = item.get("published_date") or item.get("published_at")
            if processed_q.freshness and pub_date:
                pub_date_str = str(pub_date)
                if processed_q.freshness.isdigit() and processed_q.freshness in pub_date_str:
                    fresh_score = 1.0
                else:
                    fresh_score = 0.3
            comps.freshness = fresh_score

            # Composite weighted score:
            # 40% fusion + 35% lexical + 15% source quality + 10% freshness
            composite_score = (
                0.40 * min(comps.fusion, 2.0)
                + 0.35 * comps.lexical_relevance
                + 0.15 * comps.source_quality
                + 0.10 * comps.freshness
            )
            item["score"] = composite_score

        # Sort by composite score
        candidate_items.sort(key=lambda x: float(x.get("score") or 0.0), reverse=True)

        # Optional Cross-Encoder reranking for top candidates
        if self.cross_encoder.is_available():
            candidate_items = self.cross_encoder.rerank(
                ranking_query,
                candidate_items,
                top_k=min(5, len(candidate_items)),
            )

        # Cap results to requested count or budget limit.
        # count=None -> budget default; count<=0 -> no results requested.
        # Never slice with a negative: candidate_items[:-3] would silently
        # drop items and count=0 previously fell through "0 or X" to the
        # budget default, returning 1 result instead of 0.
        if count is None:
            final_count = budget.max_candidate_results
        else:
            try:
                req_count = int(count)
            except (ValueError, TypeError):
                req_count = budget.max_candidate_results
            final_count = max(0, min(req_count, len(candidate_items)))
        selected_candidates = candidate_items[:final_count]

        # 8. Speculative Scraping & Heading-Aware Passage Extraction
        if budget.max_pages > 0:
            self._fetch_pages_concurrent(
                selected_candidates,
                max_pages=budget.max_pages,
                scrape_length=budget.max_total_chars,
                timeout=float(budget.scrape_timeout_ms / 1000.0),
                base_url=base_url,
            )

        # Build RetrievalResultItems
        final_result_items: list[RetrievalResultItem] = []
        total_passages_budget = budget.max_total_passages

        for idx, item in enumerate(selected_candidates, start=1):
            source_id = f"src_{idx:02d}"
            url = str(item.get("url") or "")
            norm_url = normalize_url(url)
            dom = item.get("domain") or extract_domain(url)
            src_type = classify_source_type(dom)

            raw_body = item.get("raw_content") or ""
            raw_html = item.get("raw_html") or ""
            snippet = str(item.get("content") or item.get("snippet") or "").strip()

            # Metadata extraction from HTML if present
            meta = HTMLMetadataExtractor.extract_metadata(raw_html, fallback_url=norm_url)
            canonical = meta.get("canonical_url") or item.get("canonical_url") or norm_url
            pub_at = meta.get("published_at") or item.get("published_date") or None
            upd_at = meta.get("updated_at") or None
            date_src = meta.get("date_source")
            date_conf = meta.get("date_confidence")

            # Extract evidence passages if scraped body is available
            evidence_list = []
            security_flags: list[str] = []

            if raw_body and total_passages_budget > 0:
                passages = self.passage_chunker.extract_evidence(
                    content=raw_body,
                    query=ranking_query,
                    source_id=source_id,
                    max_passages=min(budget.max_passages_per_page, total_passages_budget),
                )
                evidence_list.extend(passages)
                total_passages_budget -= len(passages)

                for p in passages:
                    for f in p.security_flags:
                        if f not in security_flags:
                            security_flags.append(f)
            elif snippet:
                # Fallback to snippet if not scraped
                flags = SecurityScanner.scan_for_injection(snippet)
                security_flags.extend(flags)

            res_item = RetrievalResultItem(
                id=source_id,
                title=str(item.get("title") or "Untitled").strip(),
                url=norm_url,
                canonical_url=canonical,
                domain=dom,
                published_at=pub_at,
                updated_at=upd_at,
                date_source=date_src,
                date_confidence=date_conf,
                source_type=src_type,
                score=float(item.get("score") or 0.0),
                score_components=item["score_components"],
                matched_queries=item.get("matched_queries") or [processed_q.clean_text],
                engines=item.get("engines") or [],
                snippet=snippet,
                evidence=evidence_list,
                security_flags=security_flags,
                duplicate_urls=item.get("duplicate_urls") or [],
                raw_content=raw_body,
                is_scraped=bool(item.get("is_scraped", False)),
            )
            final_result_items.append(res_item)

        elapsed_ms = (time.perf_counter() - t0) * 1000.0

        return RetrievalResponse(
            schema_version="1.0",
            query=processed_q,
            mode=norm_mode,
            expanded_queries=expanded_q_list,
            engines_used=sorted(engines_used_set),
            partial=is_partial,
            elapsed_ms=elapsed_ms,
            results=final_result_items,
            warnings=warnings_list,
            answers=direct_answers,
            infoboxes=infoboxes,
        )


_RETRIEVAL_SERVICE_SINGLETON: RetrievalService | None = None


def get_retrieval_service(
    search_func: Callable[..., dict[str, Any]] | None = None,
    scrape_func: Callable[..., dict[str, Any]] | None = None,
) -> RetrievalService:
    """Get or create RetrievalService instance.

    If custom callables (search_func or scrape_func) are provided, a fresh
    thread-safe RetrievalService instance is returned to avoid cross-thread
    state mutation in multithreaded web environments. Otherwise, a shared
    singleton instance is returned.
    """
    global _RETRIEVAL_SERVICE_SINGLETON
    if search_func is not None or scrape_func is not None:
        return RetrievalService(search_func=search_func, scrape_func=scrape_func)
    if _RETRIEVAL_SERVICE_SINGLETON is None:
        _RETRIEVAL_SERVICE_SINGLETON = RetrievalService()
    return _RETRIEVAL_SERVICE_SINGLETON
