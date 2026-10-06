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
import contextlib
import io
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
        choices=["auto", "fast", "balanced", "deep", "scrape"],
        default="auto",
        help="Execution mode: 'auto' (URL->scrape, keyword->fast/deep), 'fast' (json_lite), 'balanced' (top passages), 'deep' (BM25+scrape), 'scrape'",
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
        "-p",
        "--page",
        "--pageno",
        dest="page",
        type=int,
        default=1,
        help="Search results page number (default: 1)",
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
        "--no-highlights",
        dest="include_highlights",
        action="store_false",
        default=True,
        help="Disable passage highlight extraction (activates unified deep pipeline if applicable)",
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
    search_parser.add_argument(
        "--ai",
        dest="as_ai",
        action="store_true",
        help="Output structured GenAI Retrieval API JSON",
    )

    # Subcommand: retrieval (GenAI Retrieval API)
    retrieval_parser = subparsers.add_parser(
        "retrieval",
        help="Execute high-quality AI retrieval returning cited evidence passages & GenAI schema",
    )
    retrieval_parser.add_argument("query", help="Search keyword(s) or question")
    retrieval_parser.add_argument(
        "-n",
        "--count",
        type=int,
        default=5,
        help="Number of results to return (default: 5)",
    )
    retrieval_parser.add_argument(
        "--mode",
        dest="mode",
        choices=["fast", "balanced", "deep"],
        default="balanced",
        help="Retrieval mode: 'fast' (no scrape), 'balanced' (top passages), 'deep' (full multi-query passages)",
    )
    retrieval_parser.add_argument("-c", "--category", dest="category", default="", help="Category filter")
    retrieval_parser.add_argument("-e", "--engines", dest="engines", default="", help="Comma-separated engine list")
    retrieval_parser.add_argument(
        "-t",
        "--time-range",
        dest="time_range",
        choices=["day", "week", "month", "year"],
        default="",
        help="Time range filter",
    )
    retrieval_parser.add_argument(
        "--site",
        dest="include_domains",
        action="append",
        default=[],
        help="Restrict search to specific domain(s)",
    )
    retrieval_parser.add_argument(
        "--exclude-site",
        dest="exclude_domains",
        action="append",
        default=[],
        help="Exclude specific domain(s)",
    )
    retrieval_parser.add_argument(
        "--json",
        dest="as_json",
        action="store_true",
        help="Output GenAI schema JSON (schema_version 1.0)",
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
    try:
        from agentic_search import is_url_input

        return is_url_input(text)
    except ImportError:
        s = (text or "").strip()
        return (" " not in s) and s.lower().startswith(("http://", "https://"))


def _resolve_effective_mode(mode: str, depth: str | None, query: str) -> str:
    """Resolve the effective unified-search mode honoring an explicit ``mode``.

    Shared semantics with ``mcp_server._resolve_effective_mode``: an explicit
    ``mode`` wins over ``depth``; URL inputs resolve to ``"scrape"``;
    ``"auto"`` falls back to depth (``"fast"`` depth implies fast).
    """
    norm = (mode or "auto").strip().lower()
    if norm == "scrape" or _is_url_arg(query):
        return "scrape"
    if norm in ("fast", "deep"):
        return norm
    return "fast" if depth == "fast" else "deep"


def _print_output(text: str) -> None:
    """Safely print text to stdout, falling back to character replacement if the encoding cannot represent it."""
    try:
        print(text)
    except UnicodeEncodeError:
        encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
        print(text.encode(encoding, errors="replace").decode(encoding))


def cmd_search(args: argparse.Namespace) -> int:
    """Handle 'search' subcommand (routes to unified_search when URL/deep/filter options are used)."""
    mode = getattr(args, "mode", "auto") or "auto"
    depth = getattr(args, "depth", None)
    inc_domains = getattr(args, "include_domains", None) or []
    exc_domains = getattr(args, "exclude_domains", None) or []
    use_unified = (
        mode in ("fast", "deep", "scrape")
        or depth is not None
        or bool(inc_domains)
        or bool(exc_domains)
        or (mode == "auto" and _is_url_arg(args.query))
    )

    if mode == "balanced" or getattr(args, "as_ai", False):
        ret_mode = mode if mode in ("fast", "balanced", "deep") else "balanced"
        res = searxng_client.retrieval_search(
            query=args.query,
            mode=ret_mode,
            count=args.count,
            categories=args.category,
            engines=args.engines,
            time_range=args.time_range,
            include_domains=inc_domains or None,
            exclude_domains=exc_domains or None,
            base_url=args.base_url,
            timeout=args.timeout,
        )
        if args.as_json or getattr(args, "as_ai", False):
            _print_output(json.dumps(res, ensure_ascii=False, indent=2))
        else:
            _print_output(searxng_client.format_markdown(res))
        return 1 if res.get("error") else 0

    if use_unified:
        effective_mode = _resolve_effective_mode(mode, depth, args.query)
        res = searxng_client.unified_search(
            query=args.query,
            mode=effective_mode,
            search_depth=depth or "advanced",
            max_results=args.count,
            include_highlights=getattr(args, "include_highlights", True),
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
            _print_output(json.dumps(res, ensure_ascii=False, indent=2))
        else:
            _print_output(searxng_client.format_markdown(res))
        return 1 if res.get("error") else 0

    res = searxng_client.search(
        query=args.query,
        count=args.count,
        categories=args.category,
        engines=args.engines,
        time_range=args.time_range,
        pageno=getattr(args, "page", 1),
        base_url=args.base_url,
        timeout=args.timeout,
    )
    if args.as_json:
        _print_output(json.dumps(res, ensure_ascii=False, indent=2))
    else:
        _print_output(searxng_client.format_search_markdown(res))

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
            _print_output(json.dumps(res, ensure_ascii=False, indent=2))
        else:
            _print_output(searxng_client.format_markdown(res))
        return 1 if res.get("error") else 0

    res = searxng_client.scrape(
        url=args.url,
        max_length=args.max_chars,
        base_url=args.base_url,
        timeout=args.timeout,
    )
    if args.as_json:
        _print_output(json.dumps(res, ensure_ascii=False, indent=2))
    else:
        _print_output(searxng_client.format_scrape_markdown(res))

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
        _print_output(json.dumps(res, ensure_ascii=False, indent=2))
    else:
        _print_output(searxng_client.format_deep_search_markdown(res))

    return 1 if res.get("error") else 0


def cmd_retrieval(args: argparse.Namespace) -> int:
    """Handle 'retrieval' subcommand."""
    res = searxng_client.retrieval_search(
        query=args.query,
        mode=args.mode,
        count=args.count,
        categories=args.category,
        engines=args.engines,
        time_range=args.time_range,
        include_domains=args.include_domains if args.include_domains else None,
        exclude_domains=args.exclude_domains if args.exclude_domains else None,
        base_url=args.base_url,
        timeout=args.timeout,
    )
    if args.as_json:
        _print_output(json.dumps(res, ensure_ascii=False, indent=2))
    else:
        _print_output(searxng_client.format_markdown(res))

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
        _print_output(json.dumps(out, ensure_ascii=False, indent=2))
    else:
        icon = "✅" if is_healthy else "❌"
        _print_output(f"{icon} {status_msg}")

    return 0 if is_healthy else 1


def main() -> None:
    """CLI entrypoint."""
    # Ensure Windows stdout/stderr handles UTF-8 correctly
    if hasattr(sys.stdout, "reconfigure"):
        with contextlib.suppress(AttributeError, ValueError, io.UnsupportedOperation):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        with contextlib.suppress(AttributeError, ValueError, io.UnsupportedOperation):
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    parser = build_parser()
    args = parser.parse_args()

    exit_code = 0
    if args.command == "search":
        exit_code = cmd_search(args)
    elif args.command == "retrieval":
        exit_code = cmd_retrieval(args)
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
