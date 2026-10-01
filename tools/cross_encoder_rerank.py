#!/usr/bin/env python3
"""Optional Cross-Encoder Reranker for SearXNG Retrieval Pipeline.

Provides optional semantic reranking using Cross-Encoder models (sentence-transformers / ONNX)
with graceful fallback when dependencies or models are not installed.
"""

from __future__ import annotations

import importlib
import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CrossEncoderConfig:
    """Configuration for optional neural Cross-Encoder reranking."""

    enabled: bool = False
    model_name: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"
    top_candidates: int = 5
    max_length: int = 512


class CrossEncoderReranker:
    """Optional Cross-Encoder reranker.

    Fails gracefully to a no-op if sentence-transformers is not installed,
    ensuring zero crashes or mandatory heavy PyTorch dependencies.
    """

    def __init__(self, config: CrossEncoderConfig | None = None) -> None:
        self.config = config or CrossEncoderConfig()
        self._model: Any = None
        self._load_attempted: bool = False

    def is_available(self) -> bool:
        """Check if sentence-transformers is available in the current Python environment."""
        if not self.config.enabled:
            return False
        try:
            importlib.import_module("sentence_transformers")
            return True
        except ImportError:
            return False

    def _ensure_model(self) -> Any:
        """Lazily load the cross-encoder model without failing if unavailable or offline."""
        if not self.config.enabled:
            return None
        if self._load_attempted:
            return self._model

        self._load_attempted = True
        try:
            mod = importlib.import_module("sentence_transformers")
            cross_encoder_cls = mod.CrossEncoder
            self._model = cross_encoder_cls(
                self.config.model_name,
                max_length=self.config.max_length,
            )
            return self._model
        except Exception as exc:  # noqa: BLE001 - graceful fallback if PyTorch or weights fail to load
            logger.debug("CrossEncoder could not be initialized (%s); using lexical ranking only.", exc)
            self._model = None
            return None

    def rerank(
        self,
        query: str,
        items: list[dict[str, Any]],
        top_k: int | None = None,
    ) -> list[dict[str, Any]]:
        """Optionally rerank top candidate items with Cross-Encoder.

        If Cross-Encoder is disabled or unavailable, returns items unmodified.
        """
        if not self.config.enabled or not items or not query.strip():
            return items

        model = self._ensure_model()
        if model is None:
            return items

        k = top_k or self.config.top_candidates
        candidates = items[:k]
        pairs = []
        for it in candidates:
            title = str(it.get("title") or "")
            body = str(it.get("content") or it.get("snippet") or "")
            pairs.append([query, f"{title}. {body}"])

        try:
            scores = model.predict(pairs)
            for idx, sc in enumerate(scores):
                candidates[idx]["cross_encoder_score"] = float(sc)
            candidates.sort(key=lambda x: float(x.get("cross_encoder_score") or 0.0), reverse=True)
            return candidates + items[k:]
        except Exception as exc:  # noqa: BLE001 - graceful fallback to standard scores on model inference errors
            logger.debug("CrossEncoder prediction failed: %s; falling back to standard scores.", exc)
            return items
