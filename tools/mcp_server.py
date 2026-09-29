#!/usr/bin/env python3
"""SearXNG MCP (Model Context Protocol) stdio Server.

Provides a fast, zero-dependency MCP server conforming to the MCP 2024-11-05
specification. Enables AI coding agents (OpenCode, Claude Code, Cursor, Windsurf,
Cline, Roo Code, etc.) to query SearXNG for web search and content scraping.

Usage:
    python tools/mcp_server.py
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any

# Ensure the tools directory is in sys.path so searxng_client can be imported
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

import searxng_client  # noqa: E402

PROTOCOL_VERSION = "2024-11-05"
SERVER_NAME = "searxng-for-windows"
SERVER_VERSION = "1.0.0"

# Tool schemas exposed via MCP tools/list
TOOLS_DEFINITIONS: list[dict[str, Any]] = [
    {
        "name": "searxng_search",
        "description": (
            "Web search using SearXNG with token-optimized json_lite output. "
            "Returns search result titles, URLs, snippets, and engine attribution. "
            "Use this when you need up-to-date web documentation, API references, "
            "libraries, or solutions to coding errors."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The search keywords or query string.",
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
            },
            "required": ["query"],
        },
    },
    {
        "name": "searxng_scrape",
        "description": (
            "Extract readable text and article content from a web page URL. "
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
            },
            "required": ["url"],
        },
    },
    {
        "name": "searxng_health",
        "description": (
            "Check the health and reachability of the local SearXNG server instance."
        ),
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


def handle_tools_call(msg_id: Any, params: dict[str, Any]) -> dict[str, Any]:
    """Handle tools/call request by executing the specified SearXNG tool."""
    tool_name = params.get("name")
    arguments = params.get("arguments") or {}

    log_debug(f"Calling tool '{tool_name}' with arguments: {arguments}")

    if tool_name == "searxng_search":
        query = str(arguments.get("query", ""))
        count = int(arguments.get("count", 5))
        categories = str(arguments.get("categories", ""))
        engines = str(arguments.get("engines", ""))
        time_range = str(arguments.get("time_range", ""))

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

    elif tool_name == "searxng_scrape":
        url = str(arguments.get("url", ""))
        max_length = int(arguments.get("max_length", 4000))

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

    # Notifications (messages without id) require no response
    if msg_id is None and method:
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
        return handle_tools_call(msg_id, params)
    elif method == "resources/list":
        return {"jsonrpc": "2.0", "id": msg_id, "result": {"resources": []}}
    elif method == "prompts/list":
        return {"jsonrpc": "2.0", "id": msg_id, "result": {"prompts": []}}
    else:
        return make_jsonrpc_error(msg_id, -32601, f"Method not found: '{method}'")


def main() -> None:
    """Main stdio loop for the MCP server."""
    # Ensure Windows stdio uses UTF-8
    if hasattr(sys.stdin, "reconfigure"):
        sys.stdin.reconfigure(encoding="utf-8")
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
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
    except Exception as e:
        log_debug(f"Fatal error in stdio loop: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
