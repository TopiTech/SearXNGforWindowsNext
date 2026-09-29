#!/usr/bin/env python3
"""SearXNG CLI Tool for Terminal Users and Coding Agents.

Allows command-line searching, web scraping, and health checks against
SearXNG for Windows without needing an MCP host.
Useful for Codex CLI, Aider, terminal subagents, and automated scripts.

Usage:
    python tools/searxng_cli.py search "FastAPI tutorial" -n 5
    python tools/searxng_cli.py search "SearXNG" --json
    python tools/searxng_cli.py scrape "https://docs.searxng.org" --max-chars 3000
    python tools/searxng_cli.py health
"""

from __future__ import annotations

import argparse
import json
import os
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

import searxng_client  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    """Build command line argument parser."""
    parser = argparse.ArgumentParser(
        prog="searxng",
        description="SearXNG for Windows - CLI Search & Scraping Tool for Agents and Humans",
    )
    parser.add_argument(
        "--base-url",
        dest="base_url",
        default=None,
        help="SearXNG base URL (default: http://127.0.0.1:8888 or SEARXNG_BASE_URL env var)",
    )
    parser.add_argument(
        "--timeout",
        dest="timeout",
        type=float,
        default=None,
        help="Request timeout in seconds (default: 15.0 or SEARXNG_TIMEOUT env var)",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    # Subcommand: search
    search_parser = subparsers.add_parser(
        "search",
        help="Search the web using SearXNG's lightweight json_lite format",
    )
    search_parser.add_argument("query", help="Search keyword(s)")
    search_parser.add_argument(
        "-n",
        "--count",
        type=int,
        default=5,
        help="Number of results to return (default: 5)",
    )
    search_parser.add_argument(
        "-c",
        "--category",
        dest="category",
        default="",
        help="Category filter (e.g. 'it', 'general', 'science')",
    )
    search_parser.add_argument(
        "-e",
        "--engines",
        dest="engines",
        default="",
        help="Comma-separated engine list (e.g. 'duckduckgo,bing')",
    )
    search_parser.add_argument(
        "-t",
        "--time-range",
        dest="time_range",
        choices=["day", "week", "month", "year"],
        default="",
        help="Time range filter",
    )
    search_parser.add_argument(
        "--json",
        dest="as_json",
        action="store_true",
        help="Output raw JSON instead of Markdown",
    )

    # Subcommand: scrape
    scrape_parser = subparsers.add_parser(
        "scrape",
        help="Extract readable main text from a target web page URL",
    )
    scrape_parser.add_argument("url", help="Target URL to extract content from")
    scrape_parser.add_argument(
        "-m",
        "--max-chars",
        dest="max_chars",
        type=int,
        default=4000,
        help="Maximum characters of extracted text to display (default: 4000)",
    )
    scrape_parser.add_argument(
        "--json",
        dest="as_json",
        action="store_true",
        help="Output raw JSON instead of Markdown",
    )

    # Subcommand: health
    health_parser = subparsers.add_parser(
        "health",
        help="Check health and connectivity of the SearXNG server",
    )
    health_parser.add_argument(
        "--json",
        dest="as_json",
        action="store_true",
        help="Output JSON status",
    )

    return parser


def cmd_search(args: argparse.Namespace) -> int:
    """Handle 'search' subcommand."""
    res = searxng_client.search(
        query=args.query,
        count=args.count,
        categories=args.category,
        engines=args.engines,
        time_range=args.time_range,
        base_url=args.base_url,
        timeout=args.timeout,
    )
    if args.as_json:
        print(json.dumps(res, ensure_ascii=False, indent=2))
    else:
        print(searxng_client.format_search_markdown(res))

    return 1 if res.get("error") else 0


def cmd_scrape(args: argparse.Namespace) -> int:
    """Handle 'scrape' subcommand."""
    res = searxng_client.scrape(
        url=args.url,
        max_length=args.max_chars,
        base_url=args.base_url,
        timeout=args.timeout,
    )
    if args.as_json:
        print(json.dumps(res, ensure_ascii=False, indent=2))
    else:
        print(searxng_client.format_scrape_markdown(res))

    return 1 if res.get("error") else 0


def cmd_health(args: argparse.Namespace) -> int:
    """Handle 'health' subcommand."""
    is_healthy, status_msg = searxng_client.check_health(
        base_url=args.base_url,
        timeout=args.timeout,
    )
    if args.as_json:
        out = {
            "healthy": is_healthy,
            "status": status_msg,
            "base_url": (args.base_url or searxng_client.get_base_url()),
        }
        print(json.dumps(out, ensure_ascii=False, indent=2))
    else:
        icon = "✅" if is_healthy else "❌"
        print(f"{icon} {status_msg}")

    return 0 if is_healthy else 1


def main() -> None:
    """CLI entrypoint."""
    # Ensure Windows stdout/stderr handles UTF-8 correctly
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")

    parser = build_parser()
    args = parser.parse_args()

    exit_code = 0
    if args.command == "search":
        exit_code = cmd_search(args)
    elif args.command == "scrape":
        exit_code = cmd_scrape(args)
    elif args.command == "health":
        exit_code = cmd_health(args)
    else:
        parser.print_help()
        exit_code = 1

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
