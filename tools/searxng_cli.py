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

import searxng_client


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

    # Subcommand: search (Unified Search & Scrape entrypoint)
    search_parser = subparsers.add_parser(
        "search",
        help="Unified Web Search & URL Scrape (supports json_lite fast mode, deep BM25 mode, and URL auto-detection)",
    )
    search_parser.add_argument("query", help="Search keyword(s) or target URL (https://...)")
    search_parser.add_argument(
        "-n",
        "--count",
        type=int,
        default=5,
        help="Number of results to return (default: 5)",
    )
    search_parser.add_argument(
        "--mode",
        dest="mode",
        choices=["auto", "fast", "deep", "scrape"],
        default="auto",
        help="Execution mode: 'auto' (URL->scrape, keyword->fast/deep), 'fast' (json_lite), 'deep' (BM25+scrape), 'scrape'",
    )
    search_parser.add_argument(
        "-d",
        "--depth",
        dest="depth",
        choices=["basic", "advanced", "code", "fast"],
        default=None,
        help="Search depth when running unified/deep search ('advanced', 'code', 'basic', 'fast')",
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
        "--site",
        dest="include_domains",
        action="append",
        default=[],
        help="Restrict search to specific domain(s) (activates unified deep pipeline)",
    )
    search_parser.add_argument(
        "--exclude-site",
        dest="exclude_domains",
        action="append",
        default=[],
        help="Exclude specific domain(s) (activates unified deep pipeline)",
    )
    search_parser.add_argument(
        "--max-tokens",
        dest="max_tokens",
        type=int,
        default=3000,
        help="Maximum token budget for Markdown context (default: 3000)",
    )
    search_parser.add_argument(
        "--max-chars",
        dest="max_chars",
        type=int,
        default=8000,
        help="Maximum characters when scraping a URL (default: 8000)",
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
        help="Extract readable main text (and optional BM25 highlights) from a target web page URL",
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
        "-q",
        "--query",
        dest="focus_query",
        default="",
        help="Optional focus keywords for BM25 passage highlight extraction",
    )
    scrape_parser.add_argument(
        "--json",
        dest="as_json",
        action="store_true",
        help="Output raw JSON instead of Markdown",
    )

    # Subcommand: deep (Exa/Tavily-like one-pass deep search)
    deep_parser = subparsers.add_parser(
        "deep",
        help="Exa/Tavily-like deep search with parallel scraping and BM25 highlights",
    )
    deep_parser.add_argument("query", help="Search query or research topic")
    deep_parser.add_argument(
        "-n",
        "--max-results",
        type=int,
        default=5,
        help="Number of results to return (default: 5)",
    )
    deep_parser.add_argument(
        "-d",
        "--depth",
        choices=["basic", "advanced", "code", "fast"],
        default="advanced",
        help="Search depth: 'basic' (snippets), 'advanced' (highlights), 'code' (tech/code priority), or 'fast' (json_lite)",
    )
    deep_parser.add_argument(
        "--no-highlights",
        dest="include_highlights",
        action="store_false",
        default=True,
        help="Disable passage highlight extraction",
    )
    deep_parser.add_argument(
        "--site",
        dest="include_domains",
        action="append",
        default=[],
        help="Restrict search to specific domain(s) (can be specified multiple times)",
    )
    deep_parser.add_argument(
        "--exclude-site",
        dest="exclude_domains",
        action="append",
        default=[],
        help="Exclude specific domain(s) (can be specified multiple times)",
    )
    deep_parser.add_argument(
        "--max-tokens",
        dest="max_tokens",
        type=int,
        default=3000,
        help="Maximum token budget for Markdown context (default: 3000)",
    )
    deep_parser.add_argument(
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


def _is_url_arg(text: str) -> bool:
    s = (text or "").strip()
    return (" " not in s) and s.lower().startswith(("http://", "https://"))


def cmd_search(args: argparse.Namespace) -> int:
    """Handle 'search' subcommand (routes to unified_search when URL/deep/filter options are used)."""
    mode = getattr(args, "mode", "auto") or "auto"
    depth = getattr(args, "depth", None)
    inc_domains = getattr(args, "include_domains", None) or []
    exc_domains = getattr(args, "exclude_domains", None) or []
    use_unified = (
        mode in ("deep", "scrape")
        or depth is not None
        or bool(inc_domains)
        or bool(exc_domains)
        or (mode == "auto" and _is_url_arg(args.query))
    )

    if use_unified:
        effective_mode = (
            "scrape" if (mode == "scrape" or _is_url_arg(args.query)) else ("fast" if depth == "fast" else "deep")
        )
        res = searxng_client.unified_search(
            query=args.query,
            mode=effective_mode,
            search_depth=depth or "advanced",
            max_results=args.count,
            categories=args.category,
            engines=args.engines,
            time_range=args.time_range,
            include_domains=inc_domains or None,
            exclude_domains=exc_domains or None,
            max_tokens=getattr(args, "max_tokens", 3000),
            max_scrape_length=getattr(args, "max_chars", 8000),
            base_url=args.base_url,
            timeout=args.timeout,
        )
        if args.as_json:
            print(json.dumps(res, ensure_ascii=False, indent=2))
        else:
            print(searxng_client.format_markdown(res))
        return 1 if res.get("error") else 0

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
    focus_query = getattr(args, "focus_query", "") or ""
    if focus_query.strip():
        res = searxng_client.unified_search(
            query=args.url,
            mode="scrape",
            focus_query=focus_query.strip(),
            max_scrape_length=args.max_chars,
            base_url=args.base_url,
            timeout=args.timeout,
        )
        if args.as_json:
            print(json.dumps(res, ensure_ascii=False, indent=2))
        else:
            print(searxng_client.format_markdown(res))
        return 1 if res.get("error") else 0

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


def cmd_deep(args: argparse.Namespace) -> int:
    """Handle 'deep' subcommand."""
    res = searxng_client.search_deep(
        query=args.query,
        search_depth=args.depth,
        max_results=args.max_results,
        include_highlights=args.include_highlights,
        include_domains=args.include_domains if args.include_domains else None,
        exclude_domains=args.exclude_domains if args.exclude_domains else None,
        max_tokens=args.max_tokens,
        base_url=args.base_url,
        timeout=args.timeout,
    )
    if args.as_json:
        print(json.dumps(res, ensure_ascii=False, indent=2))
    else:
        print(searxng_client.format_deep_search_markdown(res))

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
    elif args.command == "deep":
        exit_code = cmd_deep(args)
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
