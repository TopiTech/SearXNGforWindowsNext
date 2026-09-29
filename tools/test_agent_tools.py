#!/usr/bin/env python3
"""Unit tests for AI Coding Agent integration tools (Client, MCP Server, CLI)."""

from __future__ import annotations

import argparse
import io
import json
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

# Ensure tools directory is in sys.path
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

import mcp_server  # noqa: E402
import searxng_cli  # noqa: E402
import searxng_client  # noqa: E402


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
            hdrs=None,  # type: ignore[arg-type]
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


if __name__ == "__main__":
    unittest.main()
