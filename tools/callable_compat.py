#!/usr/bin/env python3
"""Keyword-argument compatibility for pluggable search/scrape backends.

The retrieval pipeline accepts arbitrary callables (``search_func`` and
``scrape_func``). Some expose a narrower signature than the pipeline's full
option set. Retrying on ``TypeError`` cannot tell a signature mismatch apart
from a genuine ``TypeError`` raised inside the backend: it re-runs side-effecting
requests and hides real bugs. Inspecting the signature once lets the pipeline
pass exactly the keyword arguments the backend declares, exactly once.
"""

from __future__ import annotations

import inspect
from collections.abc import Callable
from typing import Any


def supported_kwargs(func: Callable[..., Any], kwargs: dict[str, Any]) -> dict[str, Any]:
    """Return the subset of ``kwargs`` that ``func`` accepts by keyword."""
    try:
        parameters = inspect.signature(func).parameters
    except (TypeError, ValueError):
        # Builtins and other callables without an introspectable signature:
        # forward everything and let Python report a genuine binding error.
        return dict(kwargs)

    if any(param.kind is inspect.Parameter.VAR_KEYWORD for param in parameters.values()):
        return dict(kwargs)

    accepted = {
        name
        for name, param in parameters.items()
        if param.kind is inspect.Parameter.POSITIONAL_OR_KEYWORD or param.kind is inspect.Parameter.KEYWORD_ONLY
    }
    return {key: value for key, value in kwargs.items() if key in accepted}


def call_with_supported_kwargs(func: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    """Call ``func`` once, passing only the keyword arguments it declares."""
    return func(*args, **supported_kwargs(func, kwargs))
