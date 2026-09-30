#!/usr/bin/env python3
"""SearXNG Client Module for AI Coding Agents and CLI tools.

This module handles communication with a local or remote SearXNG instance,
specifically leveraging the lightweight `json_lite` format and `/scrape` endpoint.
It requires only the Python standard library so it runs without additional dependencies.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

DEFAULT_BASE_URL = "http://127.0.0.1:8888"
DEFAULT_TIMEOUT = 15.0
DEFAULT_HEADERS = {
    "User-Agent": "SearXNG-Agent-Client/1.0",
    "Accept": "application/json",
    "Connection": "keep-alive",
}


def get_base_url() -> str:
    """Return the configured SearXNG base URL, stripped of trailing slashes."""
    url = os.environ.get("SEARXNG_BASE_URL", DEFAULT_BASE_URL).strip()
    return url.rstrip("/")


def get_timeout() -> float:
    """Return the configured request timeout in seconds."""
    raw = os.environ.get("SEARXNG_TIMEOUT", "").strip()
    if raw:
        try:
            return float(raw)
        except ValueError:
            pass
    return DEFAULT_TIMEOUT


def _make_offline_error_message(base_url: str, error_detail: str = "") -> str:
    """Format an actionable error message when SearXNG is unreachable."""
    msg = (
        f"SearXNG サーバー ({base_url}) に接続できませんでした。\n"
        "SearXNG が起動しているか確認してください。\n"
        "Windows の場合: プロジェクトディレクトリの 'SearXNG for Windows.bat' を実行してサーバーを起動してください。\n"
        f"(詳細: {error_detail})"
        if error_detail
        else f"SearXNG サーバー ({base_url}) に接続できませんでした。"
    )
    return msg


def check_health(base_url: str | None = None, timeout: float | None = None) -> tuple[bool, str]:
    """Check if the SearXNG server is responsive.

    Returns:
        tuple[bool, str]: (is_healthy, status_message)
    """
    target_base = (base_url or get_base_url()).rstrip("/")
    t = timeout or get_timeout()
    health_url = f"{target_base}/healthz"

    try:
        req = urllib.request.Request(
            health_url,
            headers={"User-Agent": "SearXNG-Client/1.0"},
        )
        with urllib.request.urlopen(req, timeout=t) as resp:
            status = resp.status
            body = resp.read().decode("utf-8", errors="replace").strip()
            if status == 200 and body == "OK":
                return True, f"SearXNG サーバー稼働中 ({target_base}): OK"
            return True, f"SearXNG サーバー応答あり ({target_base}, status: {status})"
    except urllib.error.HTTPError as e:
        # If /healthz returns 404 on some older SearXNG setups, try root URL
        try:
            root_req = urllib.request.Request(
                target_base,
                headers={"User-Agent": "SearXNG-Client/1.0"},
            )
            with urllib.request.urlopen(root_req, timeout=t) as resp:
                return True, f"SearXNG サーバー応答あり ({target_base}, status: {resp.status})"
        except (urllib.error.URLError, TimeoutError, OSError):
            return False, f"SearXNG HTTP エラー: {e.code} ({e.reason})"
    except urllib.error.URLError as e:
        return False, _make_offline_error_message(target_base, str(e.reason))
    except TimeoutError:
        return False, f"SearXNG サーバー ({target_base}) への接続がタイムアウトしました ({t}秒)"
    except (OSError, ValueError) as e:
        return False, f"SearXNG 接続エラー: {e}"


def search(
    query: str,
    count: int = 5,
    categories: str = "",
    engines: str = "",
    time_range: str = "",
    base_url: str | None = None,
    timeout: float | None = None,
) -> dict[str, Any]:
    """Execute a web search using SearXNG's `json_lite` format.

    Args:
        query: The search query string.
        count: Maximum number of results to return (1-20, default 5).
        categories: Optional comma-separated SearXNG categories (e.g. 'it,general').
        engines: Optional comma-separated search engine names (e.g. 'duckduckgo,bing').
        time_range: Optional time range filter ('day', 'week', 'month', 'year').
        base_url: Optional SearXNG base URL override.
        timeout: Optional request timeout in seconds.

    Returns:
        dict: Standardized dictionary containing 'query', 'results', and optional 'error'.
    """
    clean_query = query.strip()
    if not clean_query:
        return {
            "query": "",
            "results": [],
            "error": "検索クエリが空です。検索したいキーワードを指定してください。",
        }

    target_base = (base_url or get_base_url()).rstrip("/")
    t = timeout or get_timeout()

    # Cap count within safe boundaries (1 to 50)
    try:
        count = int(count)
    except (ValueError, TypeError):
        count = 5
    count = max(1, min(count, 50))

    params: dict[str, str] = {
        "q": clean_query,
        "format": "json_lite",
    }
    if categories.strip():
        params["categories"] = categories.strip()
    if engines.strip():
        params["engines"] = engines.strip()
    if time_range.strip():
        params["time_range"] = time_range.strip()

    search_url = f"{target_base}/search?{urllib.parse.urlencode(params)}"

    try:
        req = urllib.request.Request(
            search_url,
            headers=DEFAULT_HEADERS,
        )
        with urllib.request.urlopen(req, timeout=t) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="replace"))

        results = data.get("results", [])
        if count and len(results) > count:
            results = results[:count]

        return {
            "query": clean_query,
            "results": results,
            "answers": data.get("answers", []),
            "infoboxes": data.get("infoboxes", []),
        }

    except urllib.error.HTTPError as e:
        err_msg = f"SearXNG HTTP エラー: {e.code} ({e.reason})"
        try:
            err_body = e.read().decode("utf-8", errors="replace")
            if "No query" in err_body:
                err_msg = "検索クエリが認識されませんでした。"
        except (OSError, UnicodeDecodeError):
            pass
        return {"query": clean_query, "results": [], "error": err_msg}

    except urllib.error.URLError as e:
        return {
            "query": clean_query,
            "results": [],
            "error": _make_offline_error_message(target_base, str(e.reason)),
        }

    except TimeoutError:
        return {
            "query": clean_query,
            "results": [],
            "error": f"SearXNG への検索リクエストがタイムアウトしました ({t}秒)",
        }

    except json.JSONDecodeError:
        return {
            "query": clean_query,
            "results": [],
            "error": "SearXNG からの応答を JSON として解析できませんでした。",
        }

    except (OSError, ValueError, KeyError) as e:
        return {"query": clean_query, "results": [], "error": f"検索処理中にエラーが発生しました: {e}"}


def scrape(
    url: str,
    max_length: int = 4000,
    base_url: str | None = None,
    timeout: float | None = None,
) -> dict[str, Any]:
    """Extract readable page text from a URL using SearXNG's `/scrape` endpoint.

    Args:
        url: The web page URL to scrape.
        max_length: Maximum length of extracted text before truncating (default 4000).
        base_url: Optional SearXNG base URL override.
        timeout: Optional request timeout in seconds.

    Returns:
        dict: Standardized dictionary containing 'url', 'content', and optional 'error'.
    """
    clean_url = url.strip()
    if not clean_url:
        return {"url": "", "content": "", "error": "URL が指定されていません。"}

    target_base = (base_url or get_base_url()).rstrip("/")
    t = timeout or get_timeout()
    try:
        max_length = int(max_length)
    except (ValueError, TypeError):
        max_length = 4000
    if max_length < 0:
        max_length = 4000

    params = {"url": clean_url}
    scrape_url = f"{target_base}/scrape?{urllib.parse.urlencode(params)}"

    try:
        req = urllib.request.Request(
            scrape_url,
            headers=DEFAULT_HEADERS,
        )
        with urllib.request.urlopen(req, timeout=t) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="replace"))

        content = data.get("content", "")
        is_truncated = False
        if max_length and len(content) > max_length:
            content = content[:max_length]
            is_truncated = True

        return {
            "url": clean_url,
            "content": content,
            "is_truncated": is_truncated,
            "original_length": len(data.get("content", "")),
        }

    except urllib.error.HTTPError as e:
        if e.code == 400:
            err_msg = (
                f"スクレイピング拒否 (400): 対象 URL ({clean_url}) はプライベートネットワーク、"
                "ループバック、または許可されていないスキームのため安全機構 (SSRF対策) によりブロックされました。"
            )
        elif e.code == 422:
            err_msg = f"本文抽出失敗 (422): {clean_url} から本文テキストを抽出できませんでした。"
        elif e.code == 504:
            err_msg = "スクレイピングタイムアウト (504): 対象サイトからの応答が得られませんでした。"
        else:
            err_msg = f"SearXNG スクレイピング HTTP エラー: {e.code} ({e.reason})"
        return {"url": clean_url, "content": "", "error": err_msg}

    except urllib.error.URLError as e:
        return {
            "url": clean_url,
            "content": "",
            "error": _make_offline_error_message(target_base, str(e.reason)),
        }

    except TimeoutError:
        return {
            "url": clean_url,
            "content": "",
            "error": f"スクレイピングリクエストがタイムアウトしました ({t}秒)",
        }

    except json.JSONDecodeError:
        return {
            "url": clean_url,
            "content": "",
            "error": "SearXNG スクレイピング応答を JSON として解析できませんでした。",
        }

    except (OSError, ValueError, KeyError) as e:
        return {
            "url": clean_url,
            "content": "",
            "error": f"スクレイピング処理中にエラーが発生しました: {e}",
        }


def format_search_markdown(search_data: dict[str, Any]) -> str:
    """Format search results into clean, AI-friendly Markdown."""
    error = search_data.get("error")
    if error:
        return f"### 検索エラー\n\n{error}"

    query = search_data.get("query", "")
    results = search_data.get("results", [])
    answers = search_data.get("answers", [])

    lines: list[str] = [f"## Web 検索結果: `{query}`\n"]

    if answers:
        for ans in answers:
            lines.append(f"> 💡 **直接回答**: {ans}\n")

    if not results:
        lines.append("該当する検索結果が見つかりませんでした。別のキーワードをお試しください。")
        return "\n".join(lines)

    lines.append(f"**取得件数:** {len(results)} 件\n")

    for i, item in enumerate(results, 1):
        title = item.get("title", "無題").strip()
        url = item.get("url", "").strip()
        content = item.get("content", "").strip()
        source = item.get("source", "").strip()

        source_tag = f" `[{source}]`" if source else ""
        lines.append(f"### {i}. [{title}]({url}){source_tag}")
        if content:
            lines.append(f"{content}\n")
        else:
            lines.append("*(スニペットなし)*\n")

    return "\n".join(lines).strip()


def format_scrape_markdown(scrape_data: dict[str, Any]) -> str:
    """Format scraped content into clean, AI-friendly Markdown."""
    error = scrape_data.get("error")
    if error:
        return f"### 本文抽出エラー\n\n{error}"

    url = scrape_data.get("url", "")
    content = scrape_data.get("content", "").strip()
    is_truncated = scrape_data.get("is_truncated", False)
    orig_len = scrape_data.get("original_length", len(content))

    lines: list[str] = [f"## 抽出本文: {url}\n"]

    if not content:
        lines.append("抽出可能な本文が見つかりませんでした。")
        return "\n".join(lines)

    if is_truncated:
        lines.append(f"> ⚠️ *コンテキスト長制限のため、先頭 {len(content)} 文字を表示しています (全 {orig_len} 文字)。*\n")

    lines.append(content)
    return "\n".join(lines).strip()


def _load_agentic_search() -> Any:
    """Import and return the agentic_search module safely regardless of working directory."""
    try:
        import agentic_search
    except ImportError:
        import sys

        sys_path = os.path.dirname(os.path.abspath(__file__))
        if sys_path not in sys.path:
            sys.path.insert(0, sys_path)
        import agentic_search
    return agentic_search


def unified_search(
    query: str,
    mode: str = "auto",
    search_depth: str = "advanced",
    max_results: int = 5,
    include_highlights: bool = True,
    include_domains: list[str] | None = None,
    exclude_domains: list[str] | None = None,
    categories: str = "",
    engines: str = "",
    time_range: str = "",
    focus_query: str = "",
    max_tokens: int = 3000,
    max_scrape_length: int = 8000,
    base_url: str | None = None,
    timeout: float | None = None,
) -> dict[str, Any]:
    """Execute unified search or URL scraping (`auto`, `deep`, `fast`, or `scrape`).

    Automatically detects if `query` is a URL and extracts its content + BM25 highlights,
    or runs either fast (`json_lite`) or deep (parallel scrape + BM25) meta-search.
    """
    agentic_mod = _load_agentic_search()
    return agentic_mod.execute_unified_search(
        query=query,
        search_func=search,
        scrape_func=scrape,
        mode=mode,
        search_depth=search_depth,
        max_results=max_results,
        include_highlights=include_highlights,
        include_domains=include_domains,
        exclude_domains=exclude_domains,
        categories=categories,
        engines=engines,
        time_range=time_range,
        focus_query=focus_query,
        max_tokens=max_tokens,
        max_scrape_length=max_scrape_length,
        base_url=base_url,
        timeout=timeout,
    )


def search_deep(
    query: str,
    search_depth: str = "advanced",
    max_results: int = 5,
    include_highlights: bool = True,
    include_domains: list[str] | None = None,
    exclude_domains: list[str] | None = None,
    max_tokens: int = 3000,
    base_url: str | None = None,
    timeout: float | None = None,
) -> dict[str, Any]:
    """Execute deep, agentic search with speculative page fetching and BM25 highlights.

    Args:
        query: Search query or research topic.
        search_depth: 'basic'/'fast' (snippets only), 'advanced' (speculative scrape + highlights),
                      or 'code' (prioritize technical docs and code repositories).
        max_results: Number of top results to return (default 5, min 1, max 20).
        include_highlights: Whether to extract relevant passage highlights (default True).
        include_domains: Optional list of domains to restrict search to.
        exclude_domains: Optional list of domains to exclude.
        max_tokens: Maximum tokens for packed context (default 3000).
        base_url: Optional SearXNG base URL override.
        timeout: Optional request timeout in seconds.

    Returns:
        dict: Standardized deep search result dictionary with markdown representation.
    """
    agentic_mod = _load_agentic_search()
    return agentic_mod.execute_deep_search(
        query=query,
        search_func=search,
        scrape_func=scrape,
        search_depth=search_depth,
        max_results=max_results,
        include_highlights=include_highlights,
        include_domains=include_domains,
        exclude_domains=exclude_domains,
        max_tokens=max_tokens,
        base_url=base_url,
        timeout=timeout,
    )


def format_deep_search_markdown(deep_data: dict[str, Any]) -> str:
    """Format deep search results into high-density Markdown for AI agents."""
    error = deep_data.get("error")
    if error:
        return f"### ディープ検索エラー\n\n{error}"

    # Return packed markdown if already computed by agentic_search
    md = deep_data.get("markdown")
    if md:
        return md

    # Fallback to standard search markdown
    return format_search_markdown(deep_data)


def format_markdown(data: dict[str, Any]) -> str:
    """Unified Markdown formatter handling `deep`, `fast` (`json_lite`), and `scrape` results."""
    mode = str(data.get("mode", "")).lower()
    if mode == "scrape" or ("url" in data and "results" not in data):
        md = data.get("markdown")
        if md and not data.get("error"):
            return str(md)
        return format_scrape_markdown(data)

    md = data.get("markdown")
    if md and not data.get("error"):
        return str(md)

    if mode == "deep":
        return format_deep_search_markdown(data)

    return format_search_markdown(data)


