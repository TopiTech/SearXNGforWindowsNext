#!/usr/bin/env python3
"""Unit tests for AI Coding Agent integration tools (Client, MCP Server, CLI)."""

from __future__ import annotations

import email.message
import io
import json
import os
import sys
import time
import unittest
from typing import Any
from unittest.mock import MagicMock, patch

# Ensure tools directory is in sys.path
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

import mcp_server
import searxng_cli
import searxng_client
from query_pipeline import QueryProcessor
from retrieval_service import RetrievalService


class TestSearXNGClient(unittest.TestCase):
    """Test the shared SearXNG client functions."""

    def test_get_base_url_default(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            url = searxng_client.get_base_url()
            self.assertEqual(url, "http://127.0.0.1:8888")

    def test_get_base_url_env_override(self) -> None:
        with patch.dict(os.environ, {"SEARXNG_BASE_URL": "http://localhost:9000/"}):
            url = searxng_client.get_base_url()
            self.assertEqual(url, "http://localhost:9000")

    def test_get_timeout_env_override(self) -> None:
        with patch.dict(os.environ, {"SEARXNG_TIMEOUT": "25.5"}):
            self.assertEqual(searxng_client.get_timeout(), 25.5)

    def test_search_empty_query(self) -> None:
        res = searxng_client.search("")
        self.assertIn("error", res)
        self.assertEqual(res["results"], [])

    @patch("urllib.request.urlopen")
    def test_search_mocked_success(self, mock_urlopen: MagicMock) -> None:
        mock_resp = MagicMock()
        mock_payload = {
            "query": "python async",
            "results": [
                {
                    "title": "Python Asyncio Docs",
                    "url": "https://docs.python.org/3/library/asyncio.html",
                    "content": "Asynchronous I/O support...",
                    "source": "duckduckgo",
                },
                {
                    "title": "Asyncio Tutorial",
                    "url": "https://example.com/async",
                    "content": "Step by step tutorial...",
                    "source": "bing",
                },
            ],
            "answers": ["async/await was added in Python 3.5"],
            "infoboxes": [],
        }
        mock_resp.read.return_value = json.dumps(mock_payload).encode("utf-8")
        mock_urlopen.return_value.__enter__.return_value = mock_resp

        res = searxng_client.search("python async", count=1)
        self.assertNotIn("error", res)
        self.assertEqual(len(res["results"]), 1)
        self.assertEqual(res["results"][0]["title"], "Python Asyncio Docs")
        self.assertEqual(res["answers"], ["async/await was added in Python 3.5"])

    @patch("urllib.request.urlopen")
    def test_search_mocked_offline(self, mock_urlopen: MagicMock) -> None:
        import urllib.error

        mock_urlopen.side_effect = urllib.error.URLError("Connection refused")
        res = searxng_client.search("test")
        self.assertIn("error", res)
        self.assertIn("SearXNG for Windows.bat", res["error"])

    @patch("urllib.request.urlopen")
    def test_scrape_mocked_success_with_truncation(self, mock_urlopen: MagicMock) -> None:
        mock_resp = MagicMock()
        mock_payload = {
            "url": "https://example.com/article",
            "content": "A" * 5000,
        }
        mock_resp.read.return_value = json.dumps(mock_payload).encode("utf-8")
        mock_urlopen.return_value.__enter__.return_value = mock_resp

        res = searxng_client.scrape("https://example.com/article", max_length=1000)
        self.assertNotIn("error", res)
        self.assertEqual(len(res["content"]), 1000)
        self.assertTrue(res["is_truncated"])
        self.assertEqual(res["original_length"], 5000)

    @patch("urllib.request.urlopen")
    def test_scrape_mocked_ssrf_block(self, mock_urlopen: MagicMock) -> None:
        import urllib.error

        err = urllib.error.HTTPError(
            "http://127.0.0.1:8888/scrape?url=http://127.0.0.1",
            400,
            "Bad Request",
            hdrs=email.message.Message(),
            fp=io.BytesIO(b"Blocked"),
        )
        mock_urlopen.side_effect = err

        res = searxng_client.scrape("http://127.0.0.1")
        self.assertIn("error", res)
        self.assertIn("SSRF対策", res["error"])

    @patch("urllib.request.urlopen")
    def test_health_mocked_ok(self, mock_urlopen: MagicMock) -> None:
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.read.return_value = b"OK"
        mock_urlopen.return_value.__enter__.return_value = mock_resp

        healthy, msg = searxng_client.check_health()
        self.assertTrue(healthy)
        self.assertIn("稼働中", msg)

    @patch("urllib.request.urlopen")
    def test_health_mocked_offline(self, mock_urlopen: MagicMock) -> None:
        import urllib.error

        mock_urlopen.side_effect = urllib.error.URLError("Target machine refused")
        healthy, msg = searxng_client.check_health()
        self.assertFalse(healthy)
        self.assertIn("接続できませんでした", msg)

    @patch("urllib.request.urlopen")
    def test_search_count_sanitization(self, mock_urlopen: MagicMock) -> None:
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({"query": "test", "results": []}).encode("utf-8")
        mock_urlopen.return_value.__enter__.return_value = mock_resp

        res_str = searxng_client.search("test", count="3")
        self.assertNotIn("error", res_str)
        res_invalid = searxng_client.search("test", count="invalid")
        self.assertNotIn("error", res_invalid)

    @patch("urllib.request.urlopen")
    def test_search_pageno_forwarding(self, mock_urlopen: MagicMock) -> None:
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({"query": "test", "results": []}).encode("utf-8")
        mock_urlopen.return_value.__enter__.return_value = mock_resp

        searxng_client.search("test", pageno=1)
        req1 = mock_urlopen.call_args[0][0]
        self.assertNotIn("pageno", req1.full_url)

        searxng_client.search("test", pageno=3)
        req2 = mock_urlopen.call_args[0][0]
        self.assertIn("pageno=3", req2.full_url)

    @patch("urllib.request.urlopen")
    def test_scrape_max_length_sanitization(self, mock_urlopen: MagicMock) -> None:
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({"url": "https://example.com", "content": "A" * 100}).encode("utf-8")
        mock_urlopen.return_value.__enter__.return_value = mock_resp

        res_str = searxng_client.scrape("https://example.com", max_length="50")
        self.assertNotIn("error", res_str)
        self.assertEqual(len(res_str["content"]), 50)
        self.assertTrue(res_str["is_truncated"])

    @patch("urllib.request.urlopen")
    def test_health_404_fallback_to_root(self, mock_urlopen: MagicMock) -> None:
        import urllib.error
        from email.message import Message

        err_404 = urllib.error.HTTPError("http://127.0.0.1:8888/healthz", 404, "Not Found", Message(), None)
        root_resp = MagicMock()
        root_resp.status = 200
        root_resp.read.return_value = b"<html>SearXNG</html>"

        mock_urlopen.side_effect = [err_404, root_resp]
        healthy, msg = searxng_client.check_health()
        self.assertTrue(healthy)
        self.assertIn("サーバー応答あり", msg)

    def test_format_search_markdown(self) -> None:
        data = {
            "query": "SearXNG",
            "results": [
                {
                    "title": "SearXNG Docs",
                    "url": "https://docs.searxng.org",
                    "content": "Free metasearch engine",
                    "source": "duckduckgo",
                }
            ],
            "answers": ["SearXNG is open source"],
        }
        md = searxng_client.format_search_markdown(data)
        self.assertIn("## Web 検索結果: `SearXNG`", md)
        self.assertIn("[SearXNG Docs](https://docs.searxng.org)", md)
        self.assertIn("`[duckduckgo]`", md)
        self.assertIn("Free metasearch engine", md)
        self.assertIn("SearXNG is open source", md)

    def test_format_search_markdown_escapes_brackets_and_parens(self) -> None:
        data = {
            "query": "C (programming language)",
            "results": [
                {
                    "title": "[Solved] C (programming language) [Standard]",
                    "url": "https://en.wikipedia.org/wiki/C_(programming_language)",
                    "content": "C language overview",
                    "source": "wikipedia",
                }
            ],
        }
        md = searxng_client.format_search_markdown(data)
        self.assertIn("[\\[Solved\\] C (programming language) \\[Standard\\]]", md)
        self.assertIn("(https://en.wikipedia.org/wiki/C_%28programming_language%29)", md)

    def test_format_scrape_markdown(self) -> None:
        data = {
            "url": "https://example.com",
            "content": "Hello World Article",
            "is_truncated": True,
            "original_length": 50,
        }
        md = searxng_client.format_scrape_markdown(data)
        self.assertIn("## 抽出本文: https://example.com", md)
        self.assertIn("Hello World Article", md)
        self.assertIn("コンテキスト長制限のため", md)

    @patch("agentic_search.execute_deep_search")
    def test_search_deep_invokes_agentic_search(self, mock_deep: MagicMock) -> None:
        mock_deep.return_value = {
            "query": "fastapi",
            "results": [],
            "markdown": "## Deep Search Results: `fastapi`",
        }
        res = searxng_client.search_deep("fastapi", search_depth="advanced", max_results=3)
        self.assertEqual(res["query"], "fastapi")
        mock_deep.assert_called_once()

    def test_format_deep_search_markdown(self) -> None:
        data = {
            "query": "fastapi",
            "markdown": "## Deep Search Results: `fastapi`\n\n### [1] [Docs](https://fastapi.tiangolo.com)",
        }
        md = searxng_client.format_deep_search_markdown(data)
        self.assertIn("Deep Search Results", md)


class TestMCPServer(unittest.TestCase):
    """Test the MCP stdio server protocol handling."""

    def test_initialize_handshake(self) -> None:
        raw_msg = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
        resp = mcp_server.process_message(raw_msg)
        self.assertIsNotNone(resp)
        self.assertEqual(resp["id"], 1)
        self.assertEqual(resp["result"]["protocolVersion"], "2024-11-05")
        self.assertEqual(resp["result"]["serverInfo"]["name"], "searxng-for-windows")
        self.assertIn("tools", resp["result"]["capabilities"])

    def test_notification_initialized(self) -> None:
        raw_msg = json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"})
        resp = mcp_server.process_message(raw_msg)
        self.assertIsNone(resp)

    def test_ping(self) -> None:
        raw_msg = json.dumps({"jsonrpc": "2.0", "id": "p1", "method": "ping"})
        resp = mcp_server.process_message(raw_msg)
        self.assertIsNotNone(resp)
        self.assertEqual(resp["id"], "p1")
        self.assertEqual(resp["result"], {})

    def test_tools_list(self) -> None:
        raw_msg = json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
        resp = mcp_server.process_message(raw_msg)
        self.assertIsNotNone(resp)
        tools = resp["result"]["tools"]
        tool_names = [t["name"] for t in tools]
        self.assertIn("searxng_search", tool_names)
        self.assertIn("searxng_scrape", tool_names)
        self.assertIn("searxng_health", tool_names)

        # Check search tool schema
        search_tool = next(t for t in tools if t["name"] == "searxng_search")
        self.assertIn("query", search_tool["inputSchema"]["required"])
        self.assertIn("include_highlights", search_tool["inputSchema"]["properties"])
        self.assertEqual(search_tool["inputSchema"]["properties"]["include_highlights"]["type"], "boolean")

        # Check deep search tool schema
        self.assertIn("searxng_deep_search", tool_names)
        deep_tool = next(t for t in tools if t["name"] == "searxng_deep_search")
        self.assertIn("query", deep_tool["inputSchema"]["required"])
        self.assertIn("search_depth", deep_tool["inputSchema"]["properties"])

    @patch("searxng_client.search_deep")
    def test_tools_call_deep_search(self, mock_deep: MagicMock) -> None:
        mock_deep.return_value = {
            "query": "fastapi lifespan",
            "results": [],
            "markdown": "## Deep Search Results: `fastapi lifespan`\n\n### [1] [FastAPI](https://fastapi.tiangolo.com)",
        }
        raw_msg = json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 15,
                "method": "tools/call",
                "params": {"name": "searxng_deep_search", "arguments": {"query": "fastapi lifespan"}},
            }
        )
        resp = mcp_server.process_message(raw_msg)
        self.assertIsNotNone(resp)
        self.assertEqual(resp["id"], 15)
        self.assertFalse(resp["result"]["isError"])
        text = resp["result"]["content"][0]["text"]
        self.assertIn("Deep Search Results", text)

    @patch("searxng_client.search")
    def test_tools_call_search(self, mock_search: MagicMock) -> None:
        mock_search.return_value = {
            "query": "fastapi",
            "results": [
                {
                    "title": "FastAPI",
                    "url": "https://fastapi.tiangolo.com",
                    "content": "Modern Python web framework",
                    "source": "bing",
                }
            ],
        }
        raw_msg = json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 10,
                "method": "tools/call",
                "params": {"name": "searxng_search", "arguments": {"query": "fastapi"}},
            }
        )
        resp = mcp_server.process_message(raw_msg)
        self.assertIsNotNone(resp)
        self.assertEqual(resp["id"], 10)
        self.assertFalse(resp["result"]["isError"])
        text = resp["result"]["content"][0]["text"]
        self.assertIn("FastAPI", text)
        self.assertIn("Modern Python web framework", text)

    @patch("searxng_client.scrape")
    def test_tools_call_scrape(self, mock_scrape: MagicMock) -> None:
        mock_scrape.return_value = {
            "url": "https://docs.searxng.org",
            "content": "SearXNG is a privacy metasearch...",
            "is_truncated": False,
        }
        raw_msg = json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 11,
                "method": "tools/call",
                "params": {"name": "searxng_scrape", "arguments": {"url": "https://docs.searxng.org"}},
            }
        )
        resp = mcp_server.process_message(raw_msg)
        self.assertIsNotNone(resp)
        self.assertFalse(resp["result"]["isError"])
        self.assertIn("SearXNG is a privacy", resp["result"]["content"][0]["text"])

    @patch("searxng_client.check_health")
    def test_tools_call_health(self, mock_health: MagicMock) -> None:
        mock_health.return_value = (True, "SearXNG 稼働中")
        raw_msg = json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 12,
                "method": "tools/call",
                "params": {"name": "searxng_health", "arguments": {}},
            }
        )
        resp = mcp_server.process_message(raw_msg)
        self.assertIsNotNone(resp)
        self.assertFalse(resp["result"]["isError"])
        self.assertIn("SearXNG 稼働中", resp["result"]["content"][0]["text"])

    @patch("searxng_client.search")
    def test_tools_call_search_with_string_arguments(self, mock_search: MagicMock) -> None:
        mock_search.return_value = {"query": "fastapi", "results": []}
        raw_msg = json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 15,
                "method": "tools/call",
                "params": {"name": "searxng_search", "arguments": {"query": "fastapi", "count": "10"}},
            }
        )
        resp = mcp_server.process_message(raw_msg)
        self.assertIsNotNone(resp)
        self.assertFalse(resp["result"]["isError"])
        mock_search.assert_called_once_with(query="fastapi", count=10, categories="", engines="", time_range="")

    def test_tools_call_unknown_tool(self) -> None:
        raw_msg = json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 13,
                "method": "tools/call",
                "params": {"name": "unknown_tool", "arguments": {}},
            }
        )
        resp = mcp_server.process_message(raw_msg)
        self.assertIsNotNone(resp)
        self.assertTrue(resp["result"]["isError"])
        self.assertIn("不明なツール名", resp["result"]["content"][0]["text"])

    def test_unknown_method(self) -> None:
        raw_msg = json.dumps({"jsonrpc": "2.0", "id": 99, "method": "invalid/method"})
        resp = mcp_server.process_message(raw_msg)
        self.assertIsNotNone(resp)
        self.assertEqual(resp["error"]["code"], -32601)

    def test_parse_error(self) -> None:
        resp = mcp_server.process_message("{invalid json")
        self.assertIsNotNone(resp)
        self.assertEqual(resp["error"]["code"], -32700)

    def test_invalid_request(self) -> None:
        resp = mcp_server.process_message(json.dumps([1, 2, 3]))
        self.assertIsNotNone(resp)
        self.assertEqual(resp["error"]["code"], -32600)


class TestSearXNGCLI(unittest.TestCase):
    """Test the SearXNG CLI commands and options."""

    @patch("searxng_client.check_health")
    def test_cmd_health_success(self, mock_health: MagicMock) -> None:
        mock_health.return_value = (True, "SearXNG Server OK")
        parser = searxng_cli.build_parser()
        args = parser.parse_args(["health"])

        with patch("sys.stdout", new_callable=io.StringIO) as mock_out:
            code = searxng_cli.cmd_health(args)
            self.assertEqual(code, 0)
            self.assertIn("✅ SearXNG Server OK", mock_out.getvalue())

    @patch("searxng_client.check_health")
    def test_cmd_health_json(self, mock_health: MagicMock) -> None:
        mock_health.return_value = (True, "SearXNG Server OK")
        parser = searxng_cli.build_parser()
        args = parser.parse_args(["health", "--json"])

        with patch("sys.stdout", new_callable=io.StringIO) as mock_out:
            code = searxng_cli.cmd_health(args)
            self.assertEqual(code, 0)
            data = json.loads(mock_out.getvalue())
            self.assertTrue(data["healthy"])
            self.assertEqual(data["status"], "SearXNG Server OK")

    @patch("searxng_client.search")
    def test_cmd_search_markdown(self, mock_search: MagicMock) -> None:
        mock_search.return_value = {
            "query": "python",
            "results": [
                {
                    "title": "Python Language",
                    "url": "https://python.org",
                    "content": "Python is a programming language",
                    "source": "duckduckgo",
                }
            ],
        }
        parser = searxng_cli.build_parser()
        args = parser.parse_args(["search", "python", "-n", "3"])

        with patch("sys.stdout", new_callable=io.StringIO) as mock_out:
            code = searxng_cli.cmd_search(args)
            self.assertEqual(code, 0)
            self.assertIn("Python Language", mock_out.getvalue())

    @patch("searxng_client.search")
    def test_cmd_search_page_arg(self, mock_search: MagicMock) -> None:
        mock_search.return_value = {"query": "python", "results": []}
        parser = searxng_cli.build_parser()
        args = parser.parse_args(["search", "python", "-p", "3"])
        with patch("sys.stdout", new_callable=io.StringIO):
            code = searxng_cli.cmd_search(args)
        self.assertEqual(code, 0)
        mock_search.assert_called_once()
        self.assertEqual(mock_search.call_args[1].get("pageno"), 3)

    @patch("searxng_client.search")
    def test_cmd_search_cp1252_stdout_resilience(self, mock_search: MagicMock) -> None:
        """Verify cmd_search does not crash when stdout cannot encode Japanese characters."""
        mock_search.return_value = {"query": "python", "results": []}
        parser = searxng_cli.build_parser()
        args = parser.parse_args(["search", "python"])

        class MockCP1252Stream(io.StringIO):
            encoding = "cp1252"

            def write(self, s: str) -> int:
                s.encode("cp1252")
                return super().write(s)

        with patch("sys.stdout", new_callable=MockCP1252Stream):
            code = searxng_cli.cmd_search(args)
            self.assertEqual(code, 0)

    @patch("searxng_client.scrape")
    def test_cmd_scrape_markdown(self, mock_scrape: MagicMock) -> None:
        mock_scrape.return_value = {
            "url": "https://example.com",
            "content": "Scraped article text",
            "is_truncated": False,
        }
        parser = searxng_cli.build_parser()
        args = parser.parse_args(["scrape", "https://example.com", "-m", "2000"])

        with patch("sys.stdout", new_callable=io.StringIO) as mock_out:
            code = searxng_cli.cmd_scrape(args)
            self.assertEqual(code, 0)
            self.assertIn("Scraped article text", mock_out.getvalue())

    @patch("searxng_client.search_deep")
    def test_cmd_deep_markdown(self, mock_deep: MagicMock) -> None:
        mock_deep.return_value = {
            "query": "fastapi",
            "results": [],
            "markdown": "## Deep Search Results: `fastapi`",
        }
        parser = searxng_cli.build_parser()
        args = parser.parse_args(["deep", "fastapi", "-n", "3", "-d", "advanced"])

        with patch("sys.stdout", new_callable=io.StringIO) as mock_out:
            code = searxng_cli.cmd_search(args) if args.command == "search" else searxng_cli.cmd_deep(args)
            self.assertEqual(code, 0)
            self.assertIn("Deep Search Results", mock_out.getvalue())

    @patch("searxng_client.unified_search")
    def test_cmd_search_url_auto_detect_and_deep_mode(self, mock_unified: MagicMock) -> None:
        mock_unified.return_value = {
            "mode": "scrape",
            "url": "https://docs.searxng.org",
            "markdown": "## Extracted Content: https://docs.searxng.org\n\nSearXNG documentation body.",
        }
        parser = searxng_cli.build_parser()
        args = parser.parse_args(["search", "https://docs.searxng.org"])

        with patch("sys.stdout", new_callable=io.StringIO) as mock_out:
            code = searxng_cli.cmd_search(args)
            self.assertEqual(code, 0)
            self.assertIn("Extracted Content", mock_out.getvalue())
            mock_unified.assert_called_once()

    @patch("searxng_client.unified_search")
    def test_mcp_search_with_deep_mode_or_url(self, mock_unified: MagicMock) -> None:
        mock_unified.return_value = {
            "mode": "deep",
            "query": "fastapi",
            "markdown": "## Deep Search Results: `fastapi`",
        }
        raw_msg = json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 42,
                "method": "tools/call",
                "params": {
                    "name": "searxng_search",
                    "arguments": {"query": "fastapi", "mode": "deep", "search_depth": "code"},
                },
            }
        )
        resp = mcp_server.process_message(raw_msg)
        self.assertIsNotNone(resp)
        self.assertFalse(resp["result"]["isError"])
        self.assertIn("Deep Search Results", resp["result"]["content"][0]["text"])
        mock_unified.assert_called_once()

    def test_resolve_effective_mode_prefers_explicit_mode(self) -> None:
        # Explicit mode wins over a conflicting search_depth.
        self.assertEqual(mcp_server._resolve_effective_mode("fast", "advanced", "fastapi"), "fast")
        self.assertEqual(mcp_server._resolve_effective_mode("deep", "fast", "fastapi"), "deep")
        # Auto falls back to depth; URL inputs always scrape.
        self.assertEqual(mcp_server._resolve_effective_mode("auto", "fast", "fastapi"), "fast")
        self.assertEqual(mcp_server._resolve_effective_mode("auto", "advanced", "fastapi"), "deep")
        self.assertEqual(mcp_server._resolve_effective_mode("fast", "advanced", "https://example.com"), "scrape")
        # CLI helper shares the same semantics.
        self.assertEqual(searxng_cli._resolve_effective_mode("fast", "advanced", "fastapi"), "fast")
        self.assertEqual(searxng_cli._resolve_effective_mode("deep", "fast", "fastapi"), "deep")
        self.assertEqual(searxng_cli._resolve_effective_mode("fast", "advanced", "https://example.com"), "scrape")

    @patch("searxng_client.search")
    def test_mcp_search_fast_mode_routes_unified(self, mock_search: MagicMock) -> None:
        # mode="fast" is a unified mode: it must not fall through to the raw
        # json_lite search path.
        with patch("searxng_client.unified_search") as mock_unified:
            mock_unified.return_value = {"mode": "fast", "query": "q", "markdown": "## Fast Search Results"}
            raw_msg = json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": 43,
                    "method": "tools/call",
                    "params": {"name": "searxng_search", "arguments": {"query": "q", "mode": "fast"}},
                },
            )
            resp = mcp_server.process_message(raw_msg)
            self.assertIsNotNone(resp)
            self.assertFalse(resp["result"]["isError"])
            mock_unified.assert_called_once()
            mock_search.assert_not_called()

    def test_tools_call_handler_exception_returns_internal_error(self) -> None:
        # A crashing tool handler must produce a JSON-RPC error, not kill stdio.
        with patch.object(mcp_server, "handle_tools_call", side_effect=RuntimeError("boom")):
            resp = mcp_server.process_message(
                json.dumps({"jsonrpc": "2.0", "id": 44, "method": "tools/call", "params": {}})
            )
        self.assertIsNotNone(resp)
        self.assertEqual(resp["id"], 44)
        self.assertEqual(resp["error"]["code"], -32603)

    @patch("searxng_client.unified_search")
    def test_cli_search_fast_mode_uses_unified(self, mock_unified: MagicMock) -> None:
        mock_unified.return_value = {"mode": "fast", "query": "q", "markdown": "## Fast Search Results"}
        parser = searxng_cli.build_parser()
        args = parser.parse_args(["search", "q", "--mode", "fast"])
        with patch("sys.stdout", new_callable=io.StringIO):
            code = searxng_cli.cmd_search(args)
        self.assertEqual(code, 0)
        mock_unified.assert_called_once()
        self.assertEqual(mock_unified.call_args[1]["mode"], "fast")

    @patch("searxng_client.unified_search")
    def test_cli_search_fast_mode_not_overridden_by_depth(self, mock_unified: MagicMock) -> None:
        mock_unified.return_value = {"mode": "fast", "query": "q", "markdown": "## Fast Search Results"}
        parser = searxng_cli.build_parser()
        args = parser.parse_args(["search", "q", "--mode", "fast", "-d", "advanced"])
        with patch("sys.stdout", new_callable=io.StringIO):
            searxng_cli.cmd_search(args)
        self.assertEqual(mock_unified.call_args[1]["mode"], "fast")
        self.assertEqual(mock_unified.call_args[1]["search_depth"], "advanced")

    @patch("urllib.request.urlopen")
    def test_client_search_handles_none_parameters(self, mock_urlopen: MagicMock) -> None:
        """Verify searxng_client.search gracefully handles None for categories, engines, and time_range."""
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({"query": "test", "results": []}).encode("utf-8")
        mock_urlopen.return_value.__enter__.return_value = mock_resp

        res = searxng_client.search(
            "test",
            categories=None,
            engines=None,
            time_range=None,
        )
        self.assertNotIn("error", res)
        self.assertEqual(res["query"], "test")

    @patch("searxng_client.unified_search")
    def test_mcp_handles_null_optional_arguments(self, mock_unified: MagicMock) -> None:
        """Verify MCP server handles null JSON parameters without turning them into 'None' strings."""
        mock_unified.return_value = {
            "mode": "deep",
            "query": "python",
            "markdown": "## Results",
        }
        raw_msg = json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 99,
                "method": "tools/call",
                "params": {
                    "name": "searxng_search",
                    "arguments": {
                        "query": "python",
                        "mode": "deep",
                        "categories": None,
                        "engines": None,
                        "time_range": None,
                        "include_highlights": None,
                    },
                },
            }
        )
        resp = mcp_server.process_message(raw_msg)
        self.assertIsNotNone(resp)
        self.assertFalse(resp["result"]["isError"])
        mock_unified.assert_called_once()
        call_kwargs = mock_unified.call_args[1]
        self.assertEqual(call_kwargs["categories"], "")
        self.assertEqual(call_kwargs["engines"], "")
        self.assertEqual(call_kwargs["time_range"], "")
        self.assertTrue(call_kwargs["include_highlights"])

    @patch("searxng_client.search")
    def test_mcp_basic_search_handles_null_arguments(self, mock_search: MagicMock) -> None:
        """Verify standard MCP searxng_search handles null parameters safely."""
        mock_search.return_value = {
            "query": "python",
            "results": [],
        }
        raw_msg = json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 101,
                "method": "tools/call",
                "params": {
                    "name": "searxng_search",
                    "arguments": {
                        "query": "python",
                        "categories": None,
                        "engines": None,
                        "time_range": None,
                    },
                },
            }
        )
        resp = mcp_server.process_message(raw_msg)
        self.assertIsNotNone(resp)
        self.assertFalse(resp["result"]["isError"])
        mock_search.assert_called_once_with(query="python", count=5, categories="", engines="", time_range="")

    @patch("searxng_client.search_deep")
    def test_mcp_deep_search_null_highlights_defaults_to_true(self, mock_deep: MagicMock) -> None:
        """Verify searxng_deep_search with include_highlights=null preserves default True."""
        mock_deep.return_value = {
            "query": "python",
            "markdown": "## Deep Results",
        }
        raw_msg = json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 100,
                "method": "tools/call",
                "params": {
                    "name": "searxng_deep_search",
                    "arguments": {
                        "query": "python",
                        "include_highlights": None,
                    },
                },
            }
        )
        resp = mcp_server.process_message(raw_msg)
        self.assertIsNotNone(resp)
        self.assertFalse(resp["result"]["isError"])
        mock_deep.assert_called_once()
        self.assertTrue(mock_deep.call_args[1]["include_highlights"])

    def test_webui_next_ai_info_opencode_snippet_has_environment(self) -> None:
        """Verify get_ai_info provides complete opencode config with environment."""
        import webui_next

        info = webui_next.get_ai_info(host_url="http://127.0.0.1:8888")
        opencode_raw = info["snippets"]["opencode_json"]
        opencode_cfg = json.loads(opencode_raw)
        self.assertIn("mcp", opencode_cfg)
        self.assertIn("environment", opencode_cfg["mcp"]["searxng"])
        self.assertEqual(opencode_cfg["mcp"]["searxng"]["environment"]["SEARXNG_BASE_URL"], "http://127.0.0.1:8888")

    @patch("urllib.request.urlopen")
    def test_search_malformed_payload_resilience(self, mock_urlopen: MagicMock) -> None:
        """Verify searxng_client.search gracefully filters non-dict items and handles None fields."""
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(
            {
                "results": [{"title": "Valid", "url": "https://example.com"}, None, "string-result", 42],
                "answers": None,
                "infoboxes": None,
            }
        ).encode("utf-8")
        mock_urlopen.return_value.__enter__.return_value = mock_resp

        res = searxng_client.search("python")
        self.assertNotIn("error", res)
        self.assertEqual(len(res["results"]), 1)
        self.assertEqual(res["results"][0]["title"], "Valid")
        self.assertEqual(res["answers"], [])
        self.assertEqual(res["infoboxes"], [])

    @patch("urllib.request.urlopen")
    def test_scrape_null_content_resilience(self, mock_urlopen: MagicMock) -> None:
        """Verify searxng_client.scrape handles null content field without crashing."""
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({"content": None}).encode("utf-8")
        mock_urlopen.return_value.__enter__.return_value = mock_resp

        res = searxng_client.scrape("https://example.com")
        self.assertNotIn("error", res)
        self.assertEqual(res["content"], "")
        self.assertFalse(res["is_truncated"])
        self.assertEqual(res["original_length"], 0)

    def test_mcp_parse_bool_and_is_url_query(self) -> None:
        """Verify MCP boolean parser and URL query detection."""
        self.assertTrue(mcp_server._parse_bool("true"))
        self.assertTrue(mcp_server._parse_bool("1"))
        self.assertTrue(mcp_server._parse_bool(True))
        self.assertFalse(mcp_server._parse_bool("false"))
        self.assertFalse(mcp_server._parse_bool("0"))
        self.assertFalse(mcp_server._parse_bool("no"))
        self.assertFalse(mcp_server._parse_bool(False))
        self.assertTrue(mcp_server._parse_bool(None, default=True))

        self.assertTrue(mcp_server._is_url_query("https://example.com/page"))
        self.assertFalse(mcp_server._is_url_query("https://example.com keyword"))
        self.assertFalse(mcp_server._is_url_query("plain query"))

    @patch("searxng_client.search_deep")
    def test_mcp_deep_search_string_false_highlights(self, mock_deep: MagicMock) -> None:
        """Verify searxng_deep_search with include_highlights='false' parses as False."""
        mock_deep.return_value = {"query": "python", "markdown": "## Deep Results"}
        raw_msg = json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 101,
                "method": "tools/call",
                "params": {
                    "name": "searxng_deep_search",
                    "arguments": {
                        "query": "python",
                        "include_highlights": "false",
                    },
                },
            }
        )
        resp = mcp_server.process_message(raw_msg)
        self.assertIsNotNone(resp)
        self.assertFalse(resp["result"]["isError"])
        mock_deep.assert_called_once()
        self.assertFalse(mock_deep.call_args[1]["include_highlights"])

    def test_cli_search_no_highlights_flag(self) -> None:
        """Verify CLI search subcommand supports --no-highlights flag."""
        parser = searxng_cli.build_parser()
        args = parser.parse_args(["search", "python", "--depth", "advanced", "--no-highlights"])
        self.assertFalse(args.include_highlights)

        with patch("searxng_client.unified_search") as mock_unified:
            mock_unified.return_value = {"markdown": "results"}
            with patch("sys.stdout", new_callable=io.StringIO):
                ret = searxng_cli.cmd_search(args)
            self.assertEqual(ret, 0)
            mock_unified.assert_called_once()
            self.assertFalse(mock_unified.call_args[1]["include_highlights"])

    def test_cli_is_url_arg_delegation(self) -> None:
        """Verify CLI _is_url_arg properly detects single URLs vs query text."""
        self.assertTrue(searxng_cli._is_url_arg("https://example.com/test"))
        self.assertFalse(searxng_cli._is_url_arg("https://example.com test query"))
        self.assertFalse(searxng_cli._is_url_arg("normal text"))


class TestWebUINextRegression(unittest.TestCase):
    """Regression tests for SearXNG Next WebUI fixes."""

    def test_save_engines_settings_data_preserves_unspecified_cookies(self) -> None:
        """Saving general preferences must not overwrite/clear disabled_engines or enabled_engines."""
        import webui_next

        class MockResponse:
            def __init__(self) -> None:
                self.cookies: dict[str, str] = {}

            def set_cookie(self, key: str, value: str, **kwargs: Any) -> None:
                self.cookies[key] = value

        resp = MockResponse()
        payload = {"safesearch": 2}
        result = webui_next.save_engines_settings_data(None, payload, response=resp)

        self.assertTrue(result["success"])
        self.assertIn("safesearch", resp.cookies)
        self.assertEqual(resp.cookies["safesearch"], "2")
        self.assertNotIn("disabled_engines", resp.cookies)
        self.assertNotIn("enabled_engines", resp.cookies)

    def test_save_engines_settings_data_sets_specified_engine_cookies(self) -> None:
        """Explicitly passed engine settings must set the corresponding cookies."""
        import webui_next

        class MockResponse:
            def __init__(self) -> None:
                self.cookies: dict[str, str] = {}

            def set_cookie(self, key: str, value: str, **kwargs: Any) -> None:
                self.cookies[key] = value

        resp = MockResponse()
        payload = {"disabled_engines": ["duckduckgo", "brave"], "enabled_engines": ["google"]}
        result = webui_next.save_engines_settings_data(None, payload, response=resp)

        self.assertTrue(result["success"])
        self.assertEqual(resp.cookies.get("disabled_engines"), "duckduckgo,brave")
        self.assertEqual(resp.cookies.get("enabled_engines"), "google")

    def test_ui_toast_and_preferences_script_integrity(self) -> None:
        """Verify DOM IDs and JavaScript event bindings in WebUI Next HTML template."""
        import webui_next

        html = webui_next.AI_WORKSPACE_HTML
        # 1. Toast notice DOM element exists
        self.assertIn('id="toast-notice"', html)
        # 2. Escape shortcut operates on toast-notice
        self.assertIn("document.getElementById('toast-notice')", html)
        # 3. Preferences reset handler cleans localStorage
        self.assertIn("localStorage.removeItem('sxng_pref_mode')", html)
        self.assertIn("localStorage.removeItem('sxng_pref_safesearch')", html)

    def test_sync_engines_to_settings_file_updates_yaml(self) -> None:
        """Verify sync_engines_to_settings_file safely modifies YAML without destroying comments."""
        import tempfile

        import webui_next

        sample_yaml = (
            "# Top comment\n"
            "engines:\n"
            "  # Bing engine\n"
            "  - name: bing\n"
            "    engine: bing\n"
            "    disabled: false\n"
            "\n"
            "  # DuckDuckGo engine\n"
            "  - name: duckduckgo\n"
            "    engine: duckduckgo\n"
            "    shortcut: ddg\n"
            "    disabled: true\n"
            "\n"
            "doi_resolvers:\n"
            "  oadoi.org: 'https://oadoi.org/'\n"
        )
        with tempfile.NamedTemporaryFile("w+", delete=False, encoding="utf-8", suffix=".yml") as tmp:
            tmp.write(sample_yaml)
            tmp_path = tmp.name

        try:
            # Enable duckduckgo, disable bing, add new engine brave
            changed = webui_next.sync_engines_to_settings_file(
                enabled_engines=["duckduckgo", "brave"],
                disabled_engines=["bing"],
                settings_path=tmp_path,
            )
            self.assertTrue(changed)

            with open(tmp_path, "r", encoding="utf-8") as f:
                updated = f.read()

            self.assertIn(
                "# DuckDuckGo engine\n  - name: duckduckgo\n    engine: duckduckgo\n    shortcut: ddg\n    disabled: false",
                updated,
            )
            self.assertIn("# Bing engine\n  - name: bing\n    engine: bing\n    disabled: true", updated)
            self.assertIn("- name: brave\n    engine: brave\n    disabled: false", updated)
            self.assertIn("# Top comment", updated)
            self.assertIn("doi_resolvers:", updated)
        finally:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)

    def test_save_engines_settings_data_updates_in_memory_and_settings_file(self) -> None:
        """Verify save_engines_settings_data updates in-memory engine objects immediately."""
        import types

        import webui_next

        class MockEngine:
            def __init__(self, name: str, disabled: bool) -> None:
                self.name = name
                self.disabled = disabled

        ddg_engine = MockEngine("duckduckgo", disabled=True)
        bing_engine = MockEngine("bing", disabled=False)

        mock_webapp = types.SimpleNamespace(
            searx=types.SimpleNamespace(
                engines=types.SimpleNamespace(engines={"duckduckgo": ddg_engine, "bing": bing_engine})
            )
        )

        payload = {"enabled_engines": ["duckduckgo"], "disabled_engines": ["bing"]}
        res = webui_next.save_engines_settings_data(mock_webapp, payload)

        self.assertTrue(res["success"])
        self.assertFalse(ddg_engine.disabled, "duckduckgo should be live updated to disabled=False")
        self.assertTrue(bing_engine.disabled, "bing should be live updated to disabled=True")

    def test_preferences_parse_cookie_and_dict_handle_bare_engine_names(self) -> None:
        """Verify Preferences and BooleanChoices parse bare engine names to enable all categories."""
        import searx.plugins
        from searx.preferences import BooleanChoices, Preferences

        choices = {
            "duckduckgo__general": False,
            "duckduckgo__images": False,
            "bing__general": True,
        }
        bc = BooleanChoices("engines", dict(choices))

        # Bare engine name 'duckduckgo' should enable both duckduckgo__general and duckduckgo__images
        bc.parse_cookie(data_disabled="bing", data_enabled="duckduckgo")
        self.assertTrue(bc.choices["duckduckgo__general"])
        self.assertTrue(bc.choices["duckduckgo__images"])
        self.assertFalse(bc.choices["bing__general"])

        # Test Preferences.parse_dict with only enabled_engines
        import types

        import searx.favicons.proxy

        with patch.object(searx.favicons.proxy, "CFG", types.SimpleNamespace(resolver_map={})):
            prefs = Preferences(["simple"], ["general", "images"], {}, searx.plugins.STORAGE)
            prefs.engines.choices = dict(choices)
            prefs.parse_dict({"enabled_engines": "duckduckgo"})
            self.assertTrue(prefs.engines.choices["duckduckgo__general"])
            self.assertTrue(prefs.engines.choices["duckduckgo__images"])


class TestAgentQueryPipelineIntegration(unittest.TestCase):
    """Regression tests for agent tool integration with QueryProcessor and RetrievalService."""

    def test_redos_catastrophic_backtracking_mitigated(self) -> None:
        """Verify 20,000 non-matching character payload finishes in < 50ms without ReDoS."""
        payload = "x" * 20000
        t0 = time.perf_counter()
        m = QueryProcessor.COMPARISON_PATTERNS[1].search(payload)
        elapsed_ms = (time.perf_counter() - t0) * 1000.0

        self.assertIsNone(m)
        self.assertLess(elapsed_ms, 50.0, f"ReDoS risk detected: regex took {elapsed_ms:.2f}ms")

    def test_query_length_boundary_protection(self) -> None:
        """Verify inputs exceeding 2,000 characters are bounded by QueryProcessor."""
        oversized_query = "searxng query " * 300  # 4200 chars
        proc = QueryProcessor.parse_and_normalize(oversized_query)

        self.assertLessEqual(len(proc.original), QueryProcessor.MAX_QUERY_LENGTH)
        self.assertLessEqual(len(proc.clean_text), QueryProcessor.MAX_QUERY_LENGTH)
        self.assertEqual(len(proc.original), 2000)

    def test_exact_phrase_quote_preservation_in_retrieval(self) -> None:
        """Verify exact phrase quotes are retained through query pipeline into search dispatch."""
        raw_query = '"Python 3.12" site:docs.python.org'
        proc = QueryProcessor.parse_and_normalize(raw_query)

        self.assertEqual(proc.clean_text, '"Python 3.12"')
        self.assertEqual(proc.clean_no_quotes, "Python 3.12")
        self.assertIn("Python 3.12", proc.exact_phrases)

        dispatched: list[str] = []

        def mock_search(**kwargs: Any) -> dict[str, Any]:
            if "query" in kwargs:
                dispatched.append(str(kwargs["query"]))
            return {"results": []}

        service = RetrievalService(search_func=mock_search)
        service.search(raw_query, mode="fast")

        self.assertGreater(len(dispatched), 0)
        self.assertEqual(dispatched[0], '"Python 3.12"')


if __name__ == "__main__":
    unittest.main()
