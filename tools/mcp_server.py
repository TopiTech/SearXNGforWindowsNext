#!/usr/bin/env python3
"""SearXNG MCP (Model Context Protocol) stdio Server.

Provides a fast, zero-dependency MCP server conforming to the MCP 2024-11-05
specification. Enables AI coding agents (OpenCode, Claude Code, Cursor, Windsurf,
Cline, Roo Code, etc.) to query SearXNG for web search and content scraping.

Usage:
    python tools/mcp_server.py
"""

from __future__ import annotations

import contextlib
import json
import os
import sys
from typing import Any

# Ensure the tools directory is in sys.path so searxng_client can be imported
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

import searxng_client

PROTOCOL_VERSION = "2024-11-05"
SERVER_NAME = "searxng-for-windows"
SERVER_VERSION = "1.0.0"

# Tool schemas exposed via MCP tools/list
TOOLS_DEFINITIONS: list[dict[str, Any]] = [
    {
        "name": "searxng_search",
        "description": (
            "Unified web search & URL content extraction using SearXNG. "
            "Supports fast token-optimized json_lite snippets (default), one-pass deep search "
            "(parallel scraping + BM25 highlights via mode='deep' or search_depth), and automatic "
            "URL scraping when a URL (https://...) is passed as query."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The search keywords, research question, or target URL (https://...).",
                },
                "count": {
                    "type": "integer",
                    "description": "Number of top results to return (default 5, min 1, max 20).",
                    "default": 5,
                    "minimum": 1,
                    "maximum": 20,
                },
                "mode": {
                    "type": "string",
                    "description": "Optional execution mode: 'auto' (default), 'fast' (json_lite), 'balanced' (top passages), 'deep' (BM25 + scrape), or 'scrape'.",
                    "enum": ["auto", "fast", "balanced", "deep", "scrape"],
                    "default": "auto",
                },
                "search_depth": {
                    "type": "string",
                    "description": "Optional search depth ('basic', 'advanced', 'code', 'fast'). Setting this activates the unified pipeline.",
                    "enum": ["basic", "advanced", "code", "fast"],
                },
                "categories": {
                    "type": "string",
                    "description": "Optional search category filter (e.g., 'it', 'general', 'science').",
                },
                "engines": {
                    "type": "string",
                    "description": "Optional comma-separated search engine names (e.g., 'duckduckgo', 'bing').",
                },
                "time_range": {
                    "type": "string",
                    "description": "Optional time filter.",
                    "enum": ["day", "week", "month", "year"],
                },
                "include_highlights": {
                    "type": "boolean",
                    "description": "Whether to extract relevant passage highlights (default true).",
                    "default": True,
                },
                "include_domains": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional list of domains to restrict search to (e.g. ['docs.python.org', 'github.com']).",
                },
                "exclude_domains": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional list of domains to exclude.",
                },
                "max_tokens": {
                    "type": "integer",
                    "description": "Maximum token budget when using deep/unified mode (default 3000).",
                    "default": 3000,
                    "minimum": 500,
                    "maximum": 16000,
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "searxng_scrape",
        "description": (
            "Extract readable text, optional BM25 passage highlights, and article content from a web page URL. "
            "Use this when search snippets are insufficient and you need the full "
            "body text or documentation from a specific webpage."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "The URL of the webpage to scrape and extract text from.",
                },
                "max_length": {
                    "type": "integer",
                    "description": "Maximum characters to return to conserve LLM context (default 4000).",
                    "default": 4000,
                    "minimum": 500,
                    "maximum": 20000,
                },
                "query": {
                    "type": "string",
                    "description": "Optional focus keywords for BM25 highlight extraction from the scraped page.",
                },
            },
            "required": ["url"],
        },
    },
    {
        "name": "searxng_deep_search",
        "description": (
            "Exa/Tavily-like one-pass deep web search. Performs meta-search, automatically "
            "fetches top web pages in parallel, extracts clean relevant highlights via BM25, "
            "and reranks results using domain authority and intent routing. Returns rich "
            "context with minimal token usage in a single turn."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The search keywords, research question, or URL.",
                },
                "search_depth": {
                    "type": "string",
                    "description": (
                        "Search depth: 'basic' (snippets only), 'advanced' (speculative scrape + highlights), "
                        "'code' (prioritize code/docs), or 'fast' (json_lite)."
                    ),
                    "enum": ["basic", "advanced", "code", "fast"],
                    "default": "advanced",
                },
                "max_results": {
                    "type": "integer",
                    "description": "Number of top results to return (default 5, min 1, max 20).",
                    "default": 5,
                    "minimum": 1,
                    "maximum": 20,
                },
                "include_highlights": {
                    "type": "boolean",
                    "description": "Whether to extract relevant passage highlights (default true).",
                    "default": True,
                },
                "include_domains": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Optional list of domains to restrict search to (e.g. ['docs.python.org', 'github.com'])."
                    ),
                },
                "exclude_domains": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional list of domains to exclude.",
                },
                "max_tokens": {
                    "type": "integer",
                    "description": "Maximum token budget for returned markdown context (default 3000).",
                    "default": 3000,
                    "minimum": 500,
                    "maximum": 16000,
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "searxng_retrieval",
        "description": (
            "High-quality retrieval API for AI agents and LLMs. Returns structured evidence "
            "passages with stable source IDs, heading context, relevance scores, and prompt injection defense."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The search query or research question.",
                },
                "mode": {
                    "type": "string",
                    "description": "Retrieval mode: 'fast' (no scrape), 'balanced' (top pages scraped + passages), 'deep' (full multi-query deep search).",
                    "enum": ["fast", "balanced", "deep"],
                    "default": "balanced",
                },
                "count": {
                    "type": "integer",
                    "description": "Number of top results to return (default 5, min 1, max 20).",
                    "default": 5,
                    "minimum": 1,
                    "maximum": 20,
                },
                "categories": {
                    "type": "string",
                    "description": "Optional search category filter (e.g. 'it', 'general').",
                },
                "engines": {
                    "type": "string",
                    "description": "Optional comma-separated engine list (e.g. 'bing,duckduckgo').",
                },
                "time_range": {
                    "type": "string",
                    "description": "Optional time filter.",
                    "enum": ["day", "week", "month", "year"],
                },
                "include_domains": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional list of domains to restrict to.",
                },
                "exclude_domains": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional list of domains to exclude.",
                },
                "format": {
                    "type": "string",
                    "description": "Output format: 'markdown' (default) or 'json_ai' (structured schema).",
                    "enum": ["markdown", "json_ai"],
                    "default": "markdown",
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "searxng_health",
        "description": ("Check the health and reachability of the local SearXNG server instance."),
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
    },
]


def log_debug(msg: str) -> None:
    """Log debug information to stderr so stdout is strictly preserved for JSON-RPC."""
    sys.stderr.write(f"[SearXNG MCP] {msg}\n")
    sys.stderr.flush()


def send_response(response: dict[str, Any]) -> None:
    """Serialize and write a JSON-RPC response to stdout followed by a newline."""
    body = json.dumps(response, ensure_ascii=False)
    sys.stdout.write(body + "\n")
    sys.stdout.flush()


def make_jsonrpc_error(msg_id: Any, code: int, message: str, data: Any = None) -> dict[str, Any]:
    """Construct a standard JSON-RPC 2.0 error object."""
    err: dict[str, Any] = {"code": code, "message": message}
    if data is not None:
        err["data"] = data
    return {"jsonrpc": "2.0", "id": msg_id, "error": err}


def handle_initialize(msg_id: Any, params: dict[str, Any]) -> dict[str, Any]:
    """Handle MCP initialize handshake."""
    log_debug("Client initialized connection")
    return {
        "jsonrpc": "2.0",
        "id": msg_id,
        "result": {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {
                "tools": {
                    "listChanged": False,
                },
            },
            "serverInfo": {
                "name": SERVER_NAME,
                "version": SERVER_VERSION,
            },
        },
    }


def handle_tools_list(msg_id: Any, params: dict[str, Any]) -> dict[str, Any]:
    """Handle tools/list request."""
    return {
        "jsonrpc": "2.0",
        "id": msg_id,
        "result": {
            "tools": TOOLS_DEFINITIONS,
        },
    }


def _parse_bool(val: Any, default: bool = True) -> bool:
    """Parse a boolean value supporting booleans, integers, and common string values."""
    if val is None:
        return default
    if isinstance(val, bool):
        return val
    if isinstance(val, (int, float)):
        return bool(val)
    if isinstance(val, str):
        s = val.strip().lower()
        if s in ("true", "1", "yes", "on"):
            return True
        if s in ("false", "0", "no", "off"):
            return False
    return bool(val)


def _is_url_query(text: str) -> bool:
    try:
        from agentic_search import is_url_input

        return is_url_input(text)
    except ImportError:
        s = (text or "").strip()
        return (" " not in s) and s.lower().startswith(("http://", "https://"))


def _resolve_effective_mode(mode: str, search_depth: Any, query: str) -> str:
    """Resolve the effective unified-search mode honoring an explicit ``mode``.

    An explicit ``mode`` wins over ``search_depth``: ``mode="fast"`` stays
    fast even if a depth like ``"advanced"`` is also present, and
    ``mode="deep"`` stays deep even if ``search_depth="fast"`` is passed.
    URL inputs still resolve to ``"scrape"``. ``"auto"`` falls back to depth
    (``"fast"`` depth implies fast, otherwise deep).
    """
    norm = (mode or "auto").strip().lower()
    if norm == "scrape" or _is_url_query(query):
        return "scrape"
    if norm in ("fast", "deep"):
        return norm
    return "fast" if search_depth == "fast" else "deep"


def handle_tools_call(msg_id: Any, params: dict[str, Any]) -> dict[str, Any]:
    """Handle tools/call request by executing the specified SearXNG tool."""
    tool_name = params.get("name")
    raw_args = params.get("arguments")
    arguments = raw_args if isinstance(raw_args, dict) else {}

    # Log only the tool name: full arguments can contain sensitive user
    # queries/URLs and stderr is often captured by clients.
    log_debug(f"Calling tool '{tool_name}'")

    if tool_name == "searxng_search":
        query = str(arguments.get("query") or "")
        try:
            count = int(arguments.get("count", 5))
        except (ValueError, TypeError):
            count = 5
        categories = str(arguments.get("categories") or "")
        engines = str(arguments.get("engines") or "")
        time_range = str(arguments.get("time_range") or "")
        mode = str(arguments.get("mode") or "auto").strip().lower()
        search_depth = arguments.get("search_depth")
        raw_hl = arguments.get("include_highlights")
        include_highlights = _parse_bool(raw_hl, default=True)
        raw_inc = arguments.get("include_domains")
        include_domains = [str(d) for d in raw_inc] if isinstance(raw_inc, list) else None
        raw_exc = arguments.get("exclude_domains")
        exclude_domains = [str(d) for d in raw_exc] if isinstance(raw_exc, list) else None

        use_unified = (
            mode in ("fast", "balanced", "deep", "scrape")
            or search_depth is not None
            or bool(include_domains)
            or bool(exclude_domains)
            or (mode == "auto" and _is_url_query(query))
        )

        if mode == "balanced":
            data = searxng_client.retrieval_search(
                query=query,
                mode="balanced",
                count=count,
                categories=categories,
                engines=engines,
                time_range=time_range,
                include_domains=include_domains,
                exclude_domains=exclude_domains,
            )
            is_error = bool(data.get("error"))
            formatted_text = searxng_client.format_markdown(data)
        elif use_unified:
            try:
                max_tokens = int(arguments.get("max_tokens", 3000))
            except (ValueError, TypeError):
                max_tokens = 3000
            effective_mode = _resolve_effective_mode(mode, search_depth, query)
            data = searxng_client.unified_search(
                query=query,
                mode=effective_mode,
                search_depth=str(search_depth or "advanced"),
                max_results=count,
                include_highlights=include_highlights,
                categories=categories,
                engines=engines,
                time_range=time_range,
                include_domains=include_domains,
                exclude_domains=exclude_domains,
                max_tokens=max_tokens,
            )
            is_error = bool(data.get("error"))
            formatted_text = searxng_client.format_markdown(data)
        else:
            data = searxng_client.search(
                query=query,
                count=count,
                categories=categories,
                engines=engines,
                time_range=time_range,
            )
            is_error = bool(data.get("error"))
            formatted_text = searxng_client.format_search_markdown(data)

        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "result": {
                "content": [{"type": "text", "text": formatted_text}],
                "isError": is_error,
            },
        }

    elif tool_name == "searxng_retrieval":
        query = str(arguments.get("query") or "")
        ret_mode = str(arguments.get("mode") or "balanced").strip().lower()
        if ret_mode not in ("fast", "balanced", "deep"):
            ret_mode = "balanced"
        try:
            count = int(arguments.get("count", 5))
        except (ValueError, TypeError):
            count = 5
        categories = str(arguments.get("categories") or "")
        engines = str(arguments.get("engines") or "")
        time_range = str(arguments.get("time_range") or "")
        raw_inc = arguments.get("include_domains")
        include_domains = [str(d) for d in raw_inc] if isinstance(raw_inc, list) else None
        raw_exc = arguments.get("exclude_domains")
        exclude_domains = [str(d) for d in raw_exc] if isinstance(raw_exc, list) else None
        out_format = str(arguments.get("format") or "markdown").strip().lower()

        data = searxng_client.retrieval_search(
            query=query,
            mode=ret_mode,
            count=count,
            categories=categories,
            engines=engines,
            time_range=time_range,
            include_domains=include_domains,
            exclude_domains=exclude_domains,
        )
        is_error = bool(data.get("error"))
        if out_format == "json_ai":
            formatted_text = json.dumps(data, ensure_ascii=False, indent=2)
        else:
            formatted_text = searxng_client.format_markdown(data)

        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "result": {
                "content": [{"type": "text", "text": formatted_text}],
                "isError": is_error,
            },
        }

    elif tool_name == "searxng_scrape":
        url = str(arguments.get("url") or "")
        try:
            max_length = int(arguments.get("max_length", 4000))
        except (ValueError, TypeError):
            max_length = 4000
        focus_query = str(arguments.get("query") or "").strip()

        if focus_query:
            data = searxng_client.unified_search(
                query=url,
                mode="scrape",
                focus_query=focus_query,
                max_scrape_length=max_length,
            )
            is_error = bool(data.get("error"))
            formatted_text = searxng_client.format_markdown(data)
        else:
            data = searxng_client.scrape(url=url, max_length=max_length)
            is_error = bool(data.get("error"))
            formatted_text = searxng_client.format_scrape_markdown(data)

        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "result": {
                "content": [{"type": "text", "text": formatted_text}],
                "isError": is_error,
            },
        }

    elif tool_name == "searxng_deep_search":
        query = str(arguments.get("query") or "")
        search_depth = str(arguments.get("search_depth") or "advanced")
        try:
            max_results = int(arguments.get("max_results", 5))
        except (ValueError, TypeError):
            max_results = 5
        raw_hl = arguments.get("include_highlights")
        include_highlights = _parse_bool(raw_hl, default=True)
        raw_inc = arguments.get("include_domains")
        include_domains = [str(d) for d in raw_inc] if isinstance(raw_inc, list) else None
        raw_exc = arguments.get("exclude_domains")
        exclude_domains = [str(d) for d in raw_exc] if isinstance(raw_exc, list) else None
        try:
            max_tokens = int(arguments.get("max_tokens", 3000))
        except (ValueError, TypeError):
            max_tokens = 3000

        data = searxng_client.search_deep(
            query=query,
            search_depth=search_depth,
            max_results=max_results,
            include_highlights=include_highlights,
            include_domains=include_domains,
            exclude_domains=exclude_domains,
            max_tokens=max_tokens,
        )
        is_error = bool(data.get("error"))
        formatted_text = searxng_client.format_deep_search_markdown(data)

        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "result": {
                "content": [{"type": "text", "text": formatted_text}],
                "isError": is_error,
            },
        }

    elif tool_name == "searxng_health":
        is_healthy, status_msg = searxng_client.check_health()
        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "result": {
                "content": [{"type": "text", "text": status_msg}],
                "isError": not is_healthy,
            },
        }

    else:
        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "result": {
                "content": [{"type": "text", "text": f"不明なツール名です: '{tool_name}'"}],
                "isError": True,
            },
        }


def process_message(line: str) -> dict[str, Any] | None:
    """Process a single JSON-RPC request/notification line."""
    clean_line = line.strip()
    if not clean_line:
        return None

    try:
        req = json.loads(clean_line)
    except json.JSONDecodeError as e:
        return make_jsonrpc_error(None, -32700, f"Parse error: {e}")

    if not isinstance(req, dict):
        return make_jsonrpc_error(None, -32600, "Invalid Request: root must be an object")

    msg_id = req.get("id")
    method = req.get("method")
    params = req.get("params") or {}

    # Notifications (messages without id) require no response. A request with
    # an explicit JSON-RPC "id": null is still a request and MUST be answered,
    # so only a *missing* id key makes it a notification.
    if "id" not in req and method:
        if method == "notifications/initialized":
            log_debug("Notification received: initialized")
        return None

    if not method:
        return make_jsonrpc_error(msg_id, -32600, "Invalid Request: missing method")

    if method == "initialize":
        return handle_initialize(msg_id, params)
    elif method == "ping":
        return {"jsonrpc": "2.0", "id": msg_id, "result": {}}
    elif method == "tools/list":
        return handle_tools_list(msg_id, params)
    elif method == "tools/call":
        if not isinstance(params, dict):
            return make_jsonrpc_error(msg_id, -32602, "Invalid params: params must be an object")
        try:
            return handle_tools_call(msg_id, params)
        except Exception as exc:  # noqa: BLE001 - keep stdio loop alive
            log_debug(f"tools/call handler failed: {exc}")
            return make_jsonrpc_error(msg_id, -32603, "Internal error")
    elif method == "resources/list":
        return {"jsonrpc": "2.0", "id": msg_id, "result": {"resources": []}}
    elif method == "prompts/list":
        return {"jsonrpc": "2.0", "id": msg_id, "result": {"prompts": []}}
    else:
        return make_jsonrpc_error(msg_id, -32601, f"Method not found: '{method}'")


def main() -> None:
    """Main stdio loop for the MCP server."""
    # Ensure Windows stdio uses UTF-8
    with contextlib.suppress(Exception):
        if hasattr(sys.stdin, "reconfigure"):
            sys.stdin.reconfigure(encoding="utf-8")
    with contextlib.suppress(Exception):
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8")
    with contextlib.suppress(Exception):
        if hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(encoding="utf-8")

    log_debug(f"Starting {SERVER_NAME} v{SERVER_VERSION} (stdio mode)...")

    try:
        for line in sys.stdin:
            resp = process_message(line)
            if resp is not None:
                send_response(resp)
    except KeyboardInterrupt:
        log_debug("Server stopped by user interrupt.")
    except (OSError, UnicodeDecodeError, ValueError) as e:
        log_debug(f"Fatal error in stdio loop: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
