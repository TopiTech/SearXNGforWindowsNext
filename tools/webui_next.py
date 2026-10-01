#!/usr/bin/env python3
"""SearXNG Next — Lightweight AI-First WebUI & Server Endpoint Integration.

Provides:
1. `/ai` (and `/next`): Ultra-lightweight, zero-dependency AI Search & Context Studio
   unifying Agentic Deep Search (BM25 + parallel scraping + domain scoring),
   Fast Meta Search (`json_lite`), URL Content Extraction (`/scrape` + BM25 focus),
   and an interactive MCP / Coding Agent Configuration Hub.
2. `/deep_search`: HTTP API endpoint (GET/POST) exposing one-pass Exa/Tavily-style
   deep search in both JSON and raw Markdown (`format=markdown`) formats.
3. `/api/scrape_analyze`: Enhanced URL extraction endpoint with token estimation
   and optional BM25 passage highlight extraction for a single URL.
4. `/api/ai_info`: Instance capability and MCP/CLI configuration introspection API.
5. `/ai/embed.css` & `/ai/embed.js`: Progressive enhancement assets integrated
   directly into SearXNG's default `simple` theme (`/` and `/search`), adding
   one-click AI Markdown copy, token estimation, inline Deep Search, and
   per-result inline `/scrape` article extraction.
"""

from __future__ import annotations

import contextlib
import html
import ipaddress
import json
import os
import re
import socket
import sys
import urllib.parse
from typing import Any

TOOLS_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.abspath(os.path.join(TOOLS_DIR, ".."))
if TOOLS_DIR not in sys.path:
    sys.path.insert(0, TOOLS_DIR)

import agentic_search
import retrieval_service
import searxng_client


def _parse_bool(val: Any, default: bool = True) -> bool:
    """Parse boolean query/body parameter safely."""
    if val is None:
        return default
    if isinstance(val, bool):
        return val
    s = str(val).strip().lower()
    if s in ("1", "true", "yes", "on"):
        return True
    if s in ("0", "false", "no", "off"):
        return False
    return default


def _parse_int(val: Any, default: int, minimum: int, maximum: int) -> int:
    """Parse integer parameter within [minimum, maximum] bounds."""
    if val is None or val == "":
        return default
    try:
        n = int(val)
    except (ValueError, TypeError):
        return default
    return max(minimum, min(n, maximum))


def _parse_domain_list(val: Any) -> list[str]:
    """Normalize comma-separated string or list of domains."""
    return agentic_search.parse_domain_list(val)


def build_rag_prompt(query: str, markdown_context: str) -> str:
    """Wrap packed search markdown into a ready-to-paste LLM RAG prompt."""
    return agentic_search.build_rag_prompt(query, markdown_context)


def _scrape_url_direct(
    webapp_mod: Any,
    url: str,
    max_length: int = 12000,
    timeout: float = 6.0,
) -> dict[str, Any]:
    """Thread-safe in-process URL scraper reusing webapp.py's SSRF-hardened DNS pinning.

    Falls back to searxng_client.scrape when webapp_mod is unavailable.
    """
    clean_url = (url or "").strip()
    if not clean_url:
        return {"url": "", "content": "", "error": "URL が指定されていません。"}

    if (
        webapp_mod is None
        or not hasattr(webapp_mod, "_is_blocked_scrape_host")
        or not hasattr(webapp_mod, "pinned_dns")
    ):
        return searxng_client.scrape(clean_url, max_length=max_length, timeout=timeout)

    blocked_exc_cls = getattr(webapp_mod, "_ScrapeBlockedError", ValueError)
    too_large_exc_cls = getattr(webapp_mod, "_ScrapeResponseTooLargeError", RuntimeError)

    def _parse_url(value: str) -> urllib.parse.ParseResult:
        try:
            parsed_u = urllib.parse.urlparse(value)
            p = parsed_u.port
            if p is not None and (p == 0 or p > 65535):
                raise blocked_exc_cls("Invalid port: 0")
            return parsed_u
        except ValueError as exc:
            raise blocked_exc_cls("Invalid URL") from exc

    def _is_static_host_blocked(host: str | None) -> bool:
        host_clean = (host or "").strip().rstrip(".").lower()
        if not host_clean:
            return True
        is_reserved_fn = getattr(webapp_mod, "_is_reserved_scrape_host", None)
        if callable(is_reserved_fn):
            if is_reserved_fn(host_clean):
                return True
        elif webapp_mod._is_blocked_scrape_host(host_clean):
            return True
        if "%" in host_clean:
            host_clean = host_clean.split("%", 1)[0]
        try:
            ip_direct = ipaddress.ip_address(host_clean)
            return bool(webapp_mod._is_ip_blocked(ip_direct))
        except ValueError:
            if host_clean.isdigit():
                with contextlib.suppress(ValueError, TypeError, OverflowError):
                    ip_int = int(host_clean)
                    if 0 <= ip_int <= 0xFFFFFFFF:
                        return bool(webapp_mod._is_ip_blocked(ipaddress.IPv4Address(ip_int)))
            if host_clean.startswith(("0x", "0X", "0o", "0O", "0b", "0B")):
                with contextlib.suppress(ValueError, TypeError, OverflowError):
                    ip_int = int(host_clean, 0)
                    if 0 <= ip_int <= 0xFFFFFFFF:
                        return bool(webapp_mod._is_ip_blocked(ipaddress.IPv4Address(ip_int)))
            if ":" not in host_clean:
                with contextlib.suppress(OSError, ValueError):
                    packed = socket.inet_aton(host_clean)
                    return bool(webapp_mod._is_ip_blocked(ipaddress.IPv4Address(packed)))
        return False

    try:
        parsed = _parse_url(clean_url)
    except (ValueError, RuntimeError, blocked_exc_cls) as exc:
        return {"url": clean_url, "content": "", "error": f"スクレイピング拒否 (400): {exc}"}

    if parsed.scheme not in ("http", "https") or _is_static_host_blocked(parsed.hostname):
        return {
            "url": clean_url,
            "content": "",
            "error": "スクレイピング拒否 (400): プライベートIP、ループバック、または許可されていないスキームです。",
        }

    def _resolve_safe_ip(url_to_resolve: str) -> tuple[list[str], str, int]:
        p_url = _parse_url(url_to_resolve)
        if p_url.scheme not in ("http", "https"):
            raise blocked_exc_cls(f"Blocked invalid scheme: {p_url.scheme}")
        host = p_url.hostname
        if not host or _is_static_host_blocked(host):
            raise blocked_exc_cls(f"Blocked: {host} is a private/reserved host or IP")
        port = p_url.port or (443 if p_url.scheme == "https" else 80)
        try:
            addr_info = socket.getaddrinfo(host, port)
        except (socket.gaierror, OSError) as exc:
            raise blocked_exc_cls(f"DNS resolution failed for {host}: {exc}") from exc
        if not addr_info:
            raise blocked_exc_cls(f"Could not resolve host: {host}")
        valid_ips: list[str] = []
        for res in addr_info:
            ip_raw = res[4][0]
            if webapp_mod._is_ip_blocked(ip_raw):
                raise blocked_exc_cls(f"Blocked: {host} resolves to a private/reserved IP: {ip_raw}")
            valid_ips.append(str(ip_raw))
        if not valid_ips:
            raise blocked_exc_cls(f"Could not find a global IP for {host}")
        v4_ips = [ip for ip in valid_ips if ":" not in ip]
        v6_ips = [ip for ip in valid_ips if ":" in ip]
        ordered_ips = v4_ips + v6_ips
        return ordered_ips, host, port

    try:
        httpx_mod = webapp_mod.httpx
        verify_ssl = os.environ.get("SEARXNG_SCRAPE_VERIFY_SSL", "true").lower() in ("true", "1", "yes")
        ua = (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36"
        )
        with webapp_mod._scrape_client_lock:
            if webapp_mod._scrape_client is None or webapp_mod._scrape_client_verify_ssl != verify_ssl:
                scrape_limits = httpx_mod.Limits(max_keepalive_connections=20, max_connections=50)
                if webapp_mod._scrape_client is not None:
                    with contextlib.suppress(Exception):
                        webapp_mod._scrape_client.close()
                webapp_mod._scrape_client = httpx_mod.Client(
                    timeout=httpx_mod.Timeout(10.0, connect=5.0, read=10.0, write=5.0),
                    follow_redirects=False,
                    verify=verify_ssl,
                    limits=scrape_limits,
                    trust_env=False,
                )
                webapp_mod._scrape_client_verify_ssl = verify_ssl

        eff_stream_timeout = float(timeout or 10.0)
        req_timeout = httpx_mod.Timeout(
            eff_stream_timeout,
            connect=min(eff_stream_timeout, 5.0),
            read=eff_stream_timeout,
            write=min(eff_stream_timeout, 5.0),
        )
        current_url = clean_url
        downloaded = ""
        for _ in range(5):
            cur_parsed = _parse_url(current_url)
            if (cur_parsed.scheme or "").lower() not in ("http", "https"):
                raise blocked_exc_cls(f"Blocked invalid scheme during redirect: {cur_parsed.scheme}")
            safe_ips, original_host, port = _resolve_safe_ip(current_url)
            headers = {"User-Agent": ua}
            with (
                webapp_mod.pinned_dns(original_host, safe_ips, port),
                webapp_mod._scrape_client.stream("GET", current_url, headers=headers, timeout=req_timeout) as response,
            ):
                if response.status_code not in (301, 302, 303, 307, 308):
                    response.raise_for_status()
                    downloaded = webapp_mod._read_scrape_response(
                        response, max_duration=min(max(float(timeout or 10.0), 2.0), 15.0)
                    )
                    break
                location = response.headers.get("location")
                if not location or not location.strip():
                    raise RuntimeError(f"Redirect without Location header (status {response.status_code})")
                current_url = urllib.parse.urljoin(current_url, location.strip())
        else:
            raise RuntimeError("Too many redirects")

        content_text = None
        if downloaded and hasattr(webapp_mod, "trafilatura"):
            try:
                content_text = webapp_mod.trafilatura.extract(downloaded, include_comments=False, include_tables=True)
            except (ValueError, RuntimeError, TypeError, AttributeError):
                content_text = None

        if not content_text and downloaded:
            sample_html = downloaded[:1_000_000]
            raw_text = re.sub(r"(?si)<!--.*?-->", " ", sample_html)
            raw_text = re.sub(r"(?si)<script.*?>.*?</script>", " ", raw_text)
            raw_text = re.sub(r"(?si)<style.*?>.*?</style>", " ", raw_text)
            raw_text = re.sub(r"(?si)<noscript.*?>.*?</noscript>", " ", raw_text)
            raw_text = re.sub(r"(?si)<iframe.*?>.*?</iframe>", " ", raw_text)
            raw_text = re.sub(r"(?si)<template.*?>.*?</template>", " ", raw_text)
            raw_text = re.sub(r"<[^>]+>", " ", raw_text)
            raw_text = html.unescape(raw_text)
            raw_text = re.sub(r"\s+", " ", raw_text).strip()
            if raw_text:
                content_text = raw_text[:5000]

        if not content_text:
            return {"url": clean_url, "content": "", "error": "本文テキストを抽出できませんでした。"}

        orig_len = len(content_text)
        is_truncated = False
        if max_length and max_length > 0 and orig_len > max_length:
            content_text = content_text[:max_length]
            is_truncated = True

        return {
            "url": clean_url,
            "content": content_text,
            "is_truncated": is_truncated,
            "original_length": orig_len,
        }
    except too_large_exc_cls:
        return {"url": clean_url, "content": "", "error": "レスポンスサイズが上限を超えています。"}
    except blocked_exc_cls as exc:
        return {"url": clean_url, "content": "", "error": f"スクレイピング拒否: {str(exc)[:120]}"}
    except Exception as exc:  # noqa: BLE001
        return {"url": clean_url, "content": "", "error": f"取得失敗: {str(exc)[:120]}"}


def _search_in_process(
    webapp_mod: Any,
    query: str,
    count: int = 5,
    categories: str = "",
    engines: str = "",
    time_range: str = "",
    pageno: int = 1,
    base_url: str | None = None,
    timeout: float | None = None,
) -> dict[str, Any]:
    """Execute SearXNG meta-search in-process when running inside webapp.py, or fallback to HTTP client."""
    clean_query = (query or "").strip()
    if not clean_query:
        return {
            "query": "",
            "results": [],
            "error": "検索クエリが空です。検索したいキーワードを指定してください。",
        }

    try:
        count_int = max(1, min(int(count), 50))
    except (ValueError, TypeError):
        count_int = 5

    try:
        page_int = max(1, min(int(pageno), 100))
    except (ValueError, TypeError):
        page_int = 1

    if webapp_mod is not None:
        try:
            sxng_req = getattr(webapp_mod, "sxng_request", None)
            prefs = getattr(sxng_req, "preferences", None)
            if prefs is not None:

                def _run_form(form_dict: dict[str, str]) -> dict[str, Any]:
                    sq, _, _, _, _ = webapp_mod.get_search_query_from_webapp(prefs, form_dict)
                    if not getattr(sq, "engineref_list", None) and (
                        "categories" in form_dict or "engines" in form_dict
                    ):
                        fallback_form = {"q": clean_query}
                        if time_range.strip():
                            fallback_form["time_range"] = time_range.strip()
                        if page_int > 1:
                            fallback_form["pageno"] = str(page_int)
                        sq, _, _, _, _ = webapp_mod.get_search_query_from_webapp(prefs, fallback_form)
                    user_plugins = getattr(sxng_req, "user_plugins", [])
                    search_obj = webapp_mod.searx.search.SearchWithPlugins(sq, sxng_req, user_plugins)
                    rc = search_obj.search()
                    lite_raw = webapp_mod.webutils.get_json_lite_response(sq, rc)
                    return json.loads(lite_raw)

                form: dict[str, str] = {"q": clean_query}
                if categories.strip():
                    form["categories"] = categories.strip()
                if engines.strip():
                    form["engines"] = engines.strip()
                if time_range.strip():
                    form["time_range"] = time_range.strip()
                if page_int > 1:
                    form["pageno"] = str(page_int)

                data = _run_form(form)
                results = data.get("results", [])

                # If specialized routing returned 0 results, retry once with user's default enabled engines
                if not results and (categories.strip() or engines.strip()):
                    fallback_form = {"q": clean_query}
                    if time_range.strip():
                        fallback_form["time_range"] = time_range.strip()
                    if page_int > 1:
                        fallback_form["pageno"] = str(page_int)
                    data = _run_form(fallback_form)
                    results = data.get("results", [])

                if count_int and len(results) > count_int:
                    results = results[:count_int]

                return {
                    "query": clean_query,
                    "results": results,
                    "page": page_int,
                    "answers": data.get("answers", []),
                    "infoboxes": data.get("infoboxes", []),
                    "suggestions": data.get("suggestions", []),
                }
        except Exception:  # noqa: BLE001, S110
            # Fall back to HTTP client if outside request context or any internal mismatch
            pass

    return searxng_client.search(
        query=clean_query,
        count=count_int,
        categories=categories,
        engines=engines,
        time_range=time_range,
        base_url=base_url,
        timeout=timeout,
    )


def execute_server_deep_search(
    query: str,
    webapp_mod: Any = None,
    search_depth: str = "advanced",
    max_results: int = 5,
    include_highlights: bool = True,
    include_domains: list[str] | None = None,
    exclude_domains: list[str] | None = None,
    categories: str = "",
    engines: str = "",
    time_range: str = "",
    max_tokens: int = 3000,
    mode: str = "auto",
    focus_query: str = "",
    max_scrape_length: int = 8000,
    pageno: int = 1,
    base_url: str | None = None,
    timeout: float | None = None,
) -> dict[str, Any]:
    """Run the unified Search & Scrape pipeline in-process with token & timing telemetry."""
    depth = (search_depth or "advanced").strip().lower()
    if depth not in ("basic", "advanced", "code", "fast"):
        depth = "advanced"

    max_res = _parse_int(max_results, default=5, minimum=1, maximum=20)
    max_tok = _parse_int(max_tokens, default=3000, minimum=500, maximum=16000)
    page_num = _parse_int(pageno, default=1, minimum=1, maximum=100)

    def _s_func(
        query: str,
        count: int = 15,
        categories: str = "",
        engines: str = "",
        time_range: str = "",
        base_url: str | None = None,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        return _search_in_process(
            webapp_mod=webapp_mod,
            query=query,
            count=count,
            categories=categories,
            engines=engines,
            time_range=time_range,
            pageno=page_num,
            base_url=base_url,
            timeout=timeout,
        )

    def _sc_func(
        url: str,
        max_length: int = 12000,
        timeout: float = 6.0,
    ) -> dict[str, Any]:
        return _scrape_url_direct(
            webapp_mod=webapp_mod,
            url=url,
            max_length=max_length,
            timeout=timeout,
        )

    res = agentic_search.execute_unified_search(
        query=query,
        search_func=_s_func,
        scrape_func=_sc_func,
        mode=mode,
        search_depth=depth,
        max_results=max_res,
        include_highlights=include_highlights,
        include_domains=include_domains,
        exclude_domains=exclude_domains,
        categories=categories,
        engines=engines,
        time_range=time_range,
        focus_query=focus_query,
        max_tokens=max_tok,
        max_scrape_length=max_scrape_length,
        base_url=base_url,
        timeout=timeout,
    )
    res["page"] = page_num
    return res


def execute_server_retrieval_search(
    query: str,
    webapp_mod: Any = None,
    mode: str = "balanced",
    count: int = 5,
    categories: str = "",
    engines: str = "",
    time_range: str = "",
    include_domains: list[str] | None = None,
    exclude_domains: list[str] | None = None,
    base_url: str | None = None,
    timeout: float | None = None,
) -> dict[str, Any]:
    """Execute high-quality retrieval pipeline in-process, returning GenAI Structured Schema dict."""
    count_int = _parse_int(count, default=5, minimum=1, maximum=50)

    def _s_func(
        query: str,
        count: int = 15,
        categories: str = "",
        engines: str = "",
        time_range: str = "",
        base_url: str | None = None,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        return _search_in_process(
            webapp_mod=webapp_mod,
            query=query,
            count=count,
            categories=categories,
            engines=engines,
            time_range=time_range,
            base_url=base_url,
            timeout=timeout,
        )

    def _sc_func(
        url: str,
        max_length: int = 12000,
        timeout: float = 6.0,
    ) -> dict[str, Any]:
        return _scrape_url_direct(
            webapp_mod=webapp_mod,
            url=url,
            max_length=max_length,
            timeout=timeout,
        )

    svc = retrieval_service.get_retrieval_service(search_func=_s_func, scrape_func=_sc_func)
    resp = svc.search(
        query=query,
        mode=mode,
        count=count_int,
        categories=categories,
        engines=engines,
        time_range=time_range,
        include_domains=include_domains,
        exclude_domains=exclude_domains,
        base_url=base_url,
        timeout=timeout,
    )
    data = resp.to_dict()
    data["markdown"] = resp.to_markdown()
    return data


def execute_scrape_analyze(
    url: str,
    query: str = "",
    max_length: int = 8000,
    webapp_mod: Any = None,
    timeout: float = 10.0,
) -> dict[str, Any]:
    """Scrape a URL, estimate tokens, and optionally extract BM25 highlights matching a focus query."""
    max_len = _parse_int(max_length, default=8000, minimum=500, maximum=50000)

    def _sc_func(
        target_url: str,
        max_length: int = 8000,
        timeout: float = 10.0,
    ) -> dict[str, Any]:
        return _scrape_url_direct(webapp_mod, target_url, max_length=max_length, timeout=timeout)

    return agentic_search.execute_scrape_pipeline(
        url=url,
        scrape_func=_sc_func,
        focus_query=query,
        max_length=max_len,
        timeout=timeout,
    )


def get_ai_info(webapp_mod: Any = None, host_url: str = "http://127.0.0.1:8888") -> dict[str, Any]:
    """Return instance AI capabilities, engine statistics, and MCP/CLI configuration snippets."""
    base = (host_url or "http://127.0.0.1:8888").rstrip("/")
    instance_name = "SearXNG for Windows Next"
    version_str = "Next"
    enabled_engines_count = 0

    if webapp_mod is not None:
        with contextlib.suppress(Exception):
            instance_name = webapp_mod.get_setting("general.instance_name") or instance_name
            version_str = getattr(webapp_mod, "VERSION_STRING", version_str)
            eng_dict = getattr(webapp_mod, "engines", {}) or {}
            enabled_engines_count = sum(1 for e in eng_dict.values() if not getattr(e, "disabled", False))

    mcp_py = os.path.join(REPO_ROOT, "tools", "mcp_server.py").replace("\\", "/")
    cli_py = os.path.join(REPO_ROOT, "tools", "searxng_cli.py").replace("\\", "/")
    python_exe = os.path.join(REPO_ROOT, "python", "python.exe").replace("\\", "/")
    if not os.path.exists(python_exe):
        python_exe = "python"

    cursor_mcp = json.dumps(
        {
            "mcpServers": {
                "searxng": {
                    "command": python_exe,
                    "args": [mcp_py],
                    "env": {"SEARXNG_BASE_URL": base},
                }
            }
        },
        indent=2,
        ensure_ascii=False,
    )

    opencode_mcp = json.dumps(
        {
            "$schema": "https://opencode.ai/config.json",
            "mcp": {
                "searxng": {
                    "type": "local",
                    "command": [python_exe, mcp_py],
                    "environment": {"SEARXNG_BASE_URL": base},
                    "enabled": True,
                }
            },
        },
        indent=2,
        ensure_ascii=False,
    )

    return {
        "healthy": True,
        "instance_name": instance_name,
        "version": version_str,
        "base_url": base,
        "enabled_engines_count": enabled_engines_count,
        "boost_domains_count": len(agentic_search.DEFAULT_BOOST_DOMAINS),
        "endpoints": {
            "ai_workspace": "/ai",
            "deep_search": "/deep_search",
            "retrieval": "/api/retrieval",
            "json_lite": "/search?format=json_lite",
            "scrape": "/scrape",
            "scrape_analyze": "/api/scrape_analyze",
            "health": "/healthz",
        },
        "snippets": {
            "claude_code": f'claude mcp add searxng -- "{python_exe}" "{mcp_py}"',
            "cursor_mcp": cursor_mcp,
            "opencode_json": opencode_mcp,
            "cli_deep": f'"{python_exe}" "{cli_py}" deep "FastAPI lifespan context manager" -n 5',
            "curl_deep_md": f'curl -sG "{base}/deep_search" --data-urlencode "q=FastAPI lifespan" --data-urlencode "format=markdown"',
            "curl_retrieval": f'curl -sG "{base}/api/retrieval" --data-urlencode "q=FastAPI lifespan" --data-urlencode "mode=balanced"',
            "pwsh_deep": f'Invoke-RestMethod "{base}/deep_search?q=FastAPI+lifespan&depth=advanced&max_results=5"',
            "pwsh_retrieval": f'Invoke-RestMethod "{base}/api/retrieval?q=FastAPI+lifespan&mode=balanced&count=5"',
        },
    }


def get_engines_settings_data(
    webapp_mod: Any = None,
    request_cookies: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Extract full engines health, latency, reliability, and enablement settings."""
    import time

    disabled_set: set[str] = set()
    enabled_set: set[str] = set()

    # Read cookies if available
    cookies = request_cookies or {}
    cookie_disabled = str(cookies.get("disabled_engines", "")).strip()
    if cookie_disabled:
        disabled_set.update(c.strip() for c in cookie_disabled.split(",") if c.strip())
    cookie_enabled = str(cookies.get("enabled_engines", "")).strip()
    if cookie_enabled:
        enabled_set.update(c.strip() for c in cookie_enabled.split(",") if c.strip())

    if webapp_mod is not None:
        with contextlib.suppress(Exception):
            sxng_req = getattr(webapp_mod, "sxng_request", None)
            prefs = getattr(sxng_req, "preferences", None) if sxng_req else None
            if prefs and hasattr(prefs, "engines"):
                with contextlib.suppress(Exception):
                    disabled_set.update(prefs.engines.get_disabled())

    now = time.time()
    se = None
    sp = None
    reliabilities: dict[str, Any] = {}
    histogram_func = None

    if webapp_mod is not None:
        searx_pkg = getattr(webapp_mod, "searx", None)
        if searx_pkg:
            se = getattr(searx_pkg, "engines", None)
            search_mod = getattr(searx_pkg, "search", None)
            sp = getattr(search_mod, "processors", None) if search_mod else None

    if se is None:
        with contextlib.suppress(Exception):
            import searx.engines as se_mod

            se = se_mod
    if sp is None:
        with contextlib.suppress(Exception):
            import searx.search.processors as sp_mod

            sp = sp_mod

    with contextlib.suppress(Exception):
        from searx.metrics import get_reliabilities, histogram

        histogram_func = histogram
        if se and hasattr(se, "engines"):
            reliabilities = get_reliabilities(se.engines)

    all_engines = getattr(se, "engines", {}) if se else {}
    all_categories = getattr(se, "categories", {}) if se else {}
    processors = getattr(sp, "PROCESSORS", {}) if sp else {}

    engine_items: list[dict[str, Any]] = []
    category_names = sorted(all_categories.keys()) if all_categories else []

    total_latency = 0.0
    latency_count = 0
    total_reliability = 0.0
    rel_count = 0
    suspended_count = 0

    for name, e in sorted(all_engines.items(), key=lambda kv: kv[0]):
        cats = list(getattr(e, "categories", []))
        def_disabled = bool(getattr(e, "disabled", False))

        # Determine enabled state
        if name in disabled_set:
            is_enabled = False
        elif name in enabled_set:
            is_enabled = True
        else:
            is_enabled = not def_disabled

        p = processors.get(name) if processors else None
        suspend_sec = 0
        if p and getattr(p, "suspend_end_time", None) and p.suspend_end_time > now:
            suspend_sec = int(p.suspend_end_time - now)
            suspended_count += 1

        status = "suspended" if suspend_sec > 0 else ("online" if is_enabled else "disabled")

        med_ms = None
        if histogram_func:
            with contextlib.suppress(Exception):
                h = histogram_func("engine", name, "time", "total")
                if h is not None and getattr(h, "count", 0) > 0 and hasattr(h, "percentage"):
                    med_ms = round(h.percentage(50), 1)
                    total_latency += med_ms
                    latency_count += 1

        rel_data = reliabilities.get(name, {}) if reliabilities else {}
        rel_pct = rel_data.get("reliability")
        if rel_pct is not None:
            with contextlib.suppress(Exception):
                rel_val = float(str(rel_pct))
                total_reliability += rel_val
                rel_count += 1

        errors = rel_data.get("errors", [])

        about_val = getattr(e, "about", "")
        about_url = ""
        if isinstance(about_val, dict):
            about_url = str(about_val.get("website", ""))
        elif isinstance(about_val, str):
            about_url = about_val

        engine_items.append(
            {
                "name": name,
                "categories": cats,
                "enabled": is_enabled,
                "default_enabled": not def_disabled,
                "status": status,
                "suspend_remaining_sec": suspend_sec,
                "reliability": rel_pct,
                "latency_ms": med_ms,
                "shortcut": getattr(e, "shortcut", "") or "",
                "about": about_url,
                "supports": {
                    "safesearch": bool(getattr(e, "safesearch", False)),
                    "time_range": bool(getattr(e, "time_range_support", False)),
                },
                "errors": errors if isinstance(errors, list) else [],
            }
        )

    active_count = sum(1 for item in engine_items if item["enabled"])
    avg_latency = round(total_latency / latency_count, 1) if latency_count > 0 else 0
    avg_rel = round(total_reliability / rel_count, 1) if rel_count > 0 else 100.0

    return {
        "success": True,
        "total_engines": len(engine_items),
        "active_engines": active_count,
        "suspended_engines": suspended_count,
        "avg_latency_ms": avg_latency,
        "avg_reliability": avg_rel,
        "categories": category_names,
        "engines": engine_items,
    }


def save_engines_settings_data(
    webapp_mod: Any,
    payload: dict[str, Any],
    response: Any = None,
) -> dict[str, Any]:
    """Persist user engine toggles and general preferences to session cookies."""
    disabled_engines = payload.get("disabled_engines")
    enabled_engines = payload.get("enabled_engines")
    cookie_max_age = 60 * 60 * 24 * 365 * 5  # 5 years

    dis_str = ""
    en_str = ""

    if isinstance(disabled_engines, list):
        clean_dis = [str(x).strip() for x in disabled_engines if str(x).strip()]
        dis_str = ",".join(clean_dis)

    if isinstance(enabled_engines, list):
        clean_en = [str(x).strip() for x in enabled_engines if str(x).strip()]
        en_str = ",".join(clean_en)

    if response is not None and hasattr(response, "set_cookie"):
        response.set_cookie("disabled_engines", dis_str, max_age=cookie_max_age, path="/")
        response.set_cookie("enabled_engines", en_str, max_age=cookie_max_age, path="/")
        if "safesearch" in payload:
            response.set_cookie("safesearch", str(payload["safesearch"]), max_age=cookie_max_age, path="/")

    return {
        "success": True,
        "disabled_engines_count": len(disabled_engines) if isinstance(disabled_engines, list) else 0,
        "enabled_engines_count": len(enabled_engines) if isinstance(enabled_engines, list) else 0,
    }


# ---------------------------------------------------------------------------
# Lightweight CSS & JS for SearXNG `simple` theme (`/` and `/search`)
# ---------------------------------------------------------------------------

SIMPLE_EMBED_CSS = """/* SearXNG Next — Lightweight AI-First Integration Styles */
:root {
  --sxng-ai-accent: #4f46e5;
  --sxng-ai-accent-hover: #4338ca;
  --sxng-ai-accent-soft: rgba(79, 70, 229, 0.10);
  --sxng-ai-border: rgba(128, 128, 128, 0.24);
  --sxng-ai-bg-card: rgba(128, 128, 128, 0.06);
  --sxng-ai-text-muted: #6b7280;
  --sxng-ai-emerald: #10b981;
}
@media (prefers-color-scheme: dark) {
  :root {
    --sxng-ai-accent: #818cf8;
    --sxng-ai-accent-hover: #a5b4fc;
    --sxng-ai-accent-soft: rgba(129, 140, 248, 0.14);
    --sxng-ai-border: rgba(255, 255, 255, 0.14);
    --sxng-ai-bg-card: rgba(255, 255, 255, 0.05);
    --sxng-ai-text-muted: #9ca3af;
  }
}
html.theme-dark {
  --sxng-ai-accent: #818cf8;
  --sxng-ai-accent-hover: #a5b4fc;
  --sxng-ai-accent-soft: rgba(129, 140, 248, 0.14);
  --sxng-ai-border: rgba(255, 255, 255, 0.14);
  --sxng-ai-bg-card: rgba(255, 255, 255, 0.05);
  --sxng-ai-text-muted: #9ca3af;
}
#links_on_top a.link_on_top_ai {
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
  padding: 0.25rem 0.65rem;
  border-radius: 999px;
  background: var(--sxng-ai-accent-soft);
  color: var(--sxng-ai-accent) !important;
  font-weight: 600;
  font-size: 0.85rem;
  text-decoration: none;
  border: 1px solid var(--sxng-ai-border);
  transition: transform 0.12s ease, background 0.15s ease;
}
#links_on_top a.link_on_top_ai:hover {
  transform: translateY(-1px);
  background: rgba(79, 70, 229, 0.2);
}
.index .title {
  margin: 3.5rem auto 0.6rem !important;
}
.sxng-next-badge-wrap {
  display: flex;
  justify-content: center;
  align-items: center;
  margin: 0 auto 1.6rem;
}
.sxng-next-badge {
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
  padding: 0.2rem 0.75rem;
  font-size: 0.75rem;
  font-weight: 600;
  letter-spacing: 0.03em;
  border-radius: 999px;
  background: var(--sxng-ai-accent-soft);
  color: var(--sxng-ai-accent);
  border: 1px solid var(--sxng-ai-border);
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.05);
  backdrop-filter: blur(8px);
  -webkit-backdrop-filter: blur(8px);
}
/* Fallback: If badge happens to be directly inside .title (legacy markup), prevent overlap */
.index .title > .sxng-next-badge {
  display: inline-block;
  margin-top: 2.2rem;
  position: relative;
  z-index: 10;
}
.sxng-ai-home-bar {
  display: flex;
  flex-wrap: wrap;
  justify-content: center;
  gap: 0.5rem;
  margin: 0.9rem auto 0;
  max-width: 38rem;
  padding: 0 0.75rem;
}
.sxng-ai-btn {
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
  padding: 0.42rem 0.85rem;
  border-radius: 0.5rem;
  font-size: 0.82rem;
  font-weight: 500;
  line-height: 1.2;
  cursor: pointer;
  text-decoration: none !important;
  border: 1px solid var(--sxng-ai-border);
  background: var(--sxng-ai-bg-card);
  color: inherit !important;
  transition: background 0.15s ease, border-color 0.15s ease, transform 0.1s ease;
}
.sxng-ai-btn:hover {
  border-color: var(--sxng-ai-accent);
  background: var(--sxng-ai-accent-soft);
}
.sxng-ai-btn-primary {
  background: var(--sxng-ai-accent) !important;
  color: #ffffff !important;
  border-color: transparent !important;
  font-weight: 600;
}
html.theme-dark .sxng-ai-btn-primary {
  color: #0f172a !important;
}
.sxng-ai-btn-primary:hover {
  opacity: 0.92;
}
.sxng-ai-results-bar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 0.5rem;
  margin: 0.5rem 0 1rem 0;
  padding: 0.55rem 0.85rem;
  border-radius: 0.6rem;
  border: 1px solid var(--sxng-ai-border);
  background: var(--sxng-ai-bg-card);
  font-size: 0.82rem;
  grid-column: 1 / -1;
}
.sxng-ai-results-bar-left,
.sxng-ai-results-bar-right {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.45rem;
}
.sxng-ai-token-pill {
  display: inline-flex;
  align-items: center;
  padding: 0.18rem 0.55rem;
  border-radius: 999px;
  font-size: 0.75rem;
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  background: var(--sxng-ai-accent-soft);
  color: var(--sxng-ai-accent);
  font-weight: 600;
}
.sxng-ai-deep-drawer {
  display: none;
  margin: 0 0 1.2rem 0;
  padding: 0.9rem 1rem;
  border-radius: 0.65rem;
  border: 1px solid var(--sxng-ai-accent);
  background: var(--sxng-ai-bg-card);
  grid-column: 1 / -1;
}
.sxng-ai-deep-drawer.open {
  display: block;
}
.sxng-ai-deep-pre {
  max-height: 22rem;
  overflow: auto;
  padding: 0.75rem;
  margin-top: 0.55rem;
  border-radius: 0.45rem;
  border: 1px solid var(--sxng-ai-border);
  background: rgba(0, 0, 0, 0.04);
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 0.79rem;
  white-space: pre-wrap;
  word-break: break-word;
}
.sxng-ai-inline-action {
  display: inline-flex;
  align-items: center;
  gap: 0.2rem;
  margin-left: 0.45rem;
  padding: 0.1rem 0.45rem;
  border-radius: 0.35rem;
  border: 1px solid var(--sxng-ai-border);
  background: transparent;
  color: inherit;
  font-size: 0.74rem;
  cursor: pointer;
}
.sxng-ai-inline-action:hover {
  border-color: var(--sxng-ai-accent);
  color: var(--sxng-ai-accent);
}
.sxng-ai-btn:focus-visible,
.sxng-ai-inline-action:focus-visible,
.link_on_top_ai:focus-visible {
  outline: 2px solid var(--sxng-ai-accent);
  outline-offset: 2px;
}
.sxng-ai-scrape-box {
  margin-top: 0.55rem;
  padding: 0.65rem 0.8rem;
  border-radius: 0.45rem;
  border: 1px solid var(--sxng-ai-border);
  background: var(--sxng-ai-bg-card);
  font-size: 0.82rem;
}
.sxng-ai-scrape-box pre {
  max-height: 15rem;
  overflow: auto;
  margin: 0.45rem 0 0;
  white-space: pre-wrap;
  word-break: break-word;
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 0.78rem;
}
"""

SIMPLE_EMBED_JS = """/* SearXNG Next — Progressive AI Enhancement for Simple Theme */
(function () {
  'use strict';

  function escapeHtml(str) {
    return String(str == null ? '' : str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  function estimateTokens(text) {
    if (!text) return 0;
    var cjk = (text.match(/[\\u3040-\\u30ff\\u3400-\\u4dbf\\u4e00-\\u9fff]/g) || []).length;
    var other = text.length - cjk;
    return Math.round(cjk / 1.5 + other / 4.0);
  }

  function copyText(text, btn, doneLabel) {
    var orig = btn ? btn.innerHTML : '';
    var finish = function () {
      if (!btn) return;
      btn.innerHTML = doneLabel || '✅ コピー完了';
      setTimeout(function () { btn.innerHTML = orig; }, 1600);
    };
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(finish).catch(function () {
        fallbackCopy(text);
        finish();
      });
    } else {
      fallbackCopy(text);
      finish();
    }
  }

  function fallbackCopy(text) {
    var ta = document.createElement('textarea');
    ta.value = text;
    ta.style.position = 'fixed';
    ta.style.opacity = '0';
    document.body.appendChild(ta);
    ta.select();
    try { document.execCommand('copy'); } catch (e) {}
    document.body.removeChild(ta);
  }

  function collectPageResults() {
    var qInput = document.getElementById('q');
    var query = qInput ? qInput.value.trim() : '';
    var articles = document.querySelectorAll('#urls article.result');
    var items = [];
    articles.forEach(function (art, idx) {
      var h3a = art.querySelector('h3 a');
      var urlLink = art.querySelector('a.url_header') || h3a;
      var contentEl = art.querySelector('p.content');
      var scrapedEl = art.querySelector('.sxng-ai-scrape-content');
      var enginesEls = art.querySelectorAll('.engines span');
      var engines = [];
      enginesEls.forEach(function (s) {
        if (!s.classList.contains('sxng-ai-inline-action')) {
          engines.push(s.textContent.trim());
        }
      });
      if (h3a && urlLink) {
        items.push({
          rank: idx + 1,
          title: h3a.textContent.trim(),
          url: urlLink.href,
          content: contentEl ? contentEl.textContent.trim() : '',
          scraped: scrapedEl ? scrapedEl.textContent.trim() : '',
          source: engines.join(', ')
        });
      }
    });
    return { query: query, items: items };
  }

  function buildPageMarkdown(asPrompt) {
    var data = collectPageResults();
    var lines = ['## Web Search Results: `' + data.query + '`\\n'];
    var ansEls = document.querySelectorAll('#answers .answer');
    ansEls.forEach(function (a) {
      lines.push('> 💡 **Direct Answer**: ' + a.textContent.trim() + '\\n');
    });
    data.items.forEach(function (it) {
      var src = it.source ? ' `[' + it.source + ']`' : '';
      lines.push('### [' + it.rank + '] [' + it.title + '](' + it.url + ')' + src);
      if (it.scraped) {
        lines.push('> **抽出本文**:\\n> ' + it.scraped.replace(/\\n/g, '\\n> ') + '\\n');
      } else if (it.content) {
        lines.push('> ' + it.content + '\\n');
      }
    });
    var md = lines.join('\\n').trim();
    if (asPrompt) {
      return (
        '以下のWeb検索結果（引用番号 [1]〜）を根拠として、質問に正確かつ詳細に回答してください。\\n\\n' +
        '## 質問\\n' + data.query + '\\n\\n## 検索コンテキスト\\n' + md
      );
    }
    return md;
  }

  function enhanceSearchResultsPage() {
    var resultsDiv = document.getElementById('results');
    if (!resultsDiv) return;

    var articles = document.querySelectorAll('#urls article.result');
    articles.forEach(function (art) {
      if (art.dataset.sxngAiEnhanced === '1') return;
      art.dataset.sxngAiEnhanced = '1';

      var h3a = art.querySelector('h3 a');
      var urlLink = art.querySelector('a.url_header') || h3a;
      if (!urlLink || !urlLink.href) return;
      var targetUrl = urlLink.href;
      var titleText = h3a ? h3a.textContent.trim() : targetUrl;
      var contentEl = art.querySelector('p.content');
      var snippetText = contentEl ? contentEl.textContent.trim() : '';

      var enginesBar = art.querySelector('.engines');
      if (!enginesBar) return;

      var scrapeBtn = document.createElement('button');
      scrapeBtn.type = 'button';
      scrapeBtn.className = 'sxng-ai-inline-action';
      scrapeBtn.innerHTML = '📄 本文抽出';
      scrapeBtn.title = 'このURLの本文を抽出してプレビュー (/scrape)';
      scrapeBtn.setAttribute('aria-expanded', 'false');

      var citeBtn = document.createElement('button');
      citeBtn.type = 'button';
      citeBtn.className = 'sxng-ai-inline-action';
      citeBtn.innerHTML = '📋 引用コピー';
      citeBtn.title = 'AIプロンプト用にMarkdown引用形式でコピー';

      citeBtn.addEventListener('click', function () {
        var md = '### [' + titleText + '](' + targetUrl + ')\\n' + (snippetText ? '> ' + snippetText : '');
        copyText(md, citeBtn, '✅ 引用コピー済');
      });

      scrapeBtn.addEventListener('click', function () {
        var existingBox = art.querySelector('.sxng-ai-scrape-box');
        if (existingBox) {
          var isHidden = existingBox.style.display === 'none';
          existingBox.style.display = isHidden ? 'block' : 'none';
          scrapeBtn.setAttribute('aria-expanded', isHidden ? 'true' : 'false');
          return;
        }
        var box = document.createElement('div');
        box.className = 'sxng-ai-scrape-box';
        box.innerHTML = '<span>⏳ 本文を抽出中 (trafilatura)...</span>';
        art.appendChild(box);
        scrapeBtn.disabled = true;
        scrapeBtn.setAttribute('aria-expanded', 'true');

        var qInput = document.getElementById('q');
        var qVal = qInput ? qInput.value.trim() : '';
        var apiUrl = '/api/scrape_analyze?url=' + encodeURIComponent(targetUrl) + '&q=' + encodeURIComponent(qVal) + '&max_length=6000';
        fetch(apiUrl)
          .then(function (r) { return r.json(); })
          .then(function (res) {
            scrapeBtn.disabled = false;
            if (res.error) {
              box.innerHTML = '<div style="color:#ef4444;">⚠️ ' + escapeHtml(res.error) + '</div>';
              return;
            }
            var tok = res.estimated_tokens || estimateTokens(res.content || '');
            box.innerHTML = '';
            var header = document.createElement('div');
            header.style.display = 'flex';
            header.style.justifyContent = 'space-between';
            header.style.alignItems = 'center';
            header.style.gap = '0.5rem';

            var meta = document.createElement('span');
            meta.innerHTML = '<strong>📄 抽出本文</strong> <span class="sxng-ai-token-pill">' +
              escapeHtml(res.char_count || 0) + ' chars / ~' + escapeHtml(tok) + ' tokens</span>';

            var copyExtractedBtn = document.createElement('button');
            copyExtractedBtn.type = 'button';
            copyExtractedBtn.className = 'sxng-ai-inline-action';
            copyExtractedBtn.innerHTML = '📋 本文Markdownをコピー';
            copyExtractedBtn.addEventListener('click', function () {
              copyText(res.markdown || res.content || '', copyExtractedBtn, '✅ コピー完了');
            });

            header.appendChild(meta);
            header.appendChild(copyExtractedBtn);
            box.appendChild(header);

            var pre = document.createElement('pre');
            pre.className = 'sxng-ai-scrape-content';
            pre.textContent = res.content || '';
            box.appendChild(pre);
            updateTokenCounter();
          })
          .catch(function (err) {
            scrapeBtn.disabled = false;
            box.innerHTML = '<div style="color:#ef4444;">⚠️ 通信エラー: ' + escapeHtml(err) + '</div>';
          });
      });

      enginesBar.appendChild(scrapeBtn);
      enginesBar.appendChild(citeBtn);
    });

    function updateTokenCounter() {
      var pill = document.getElementById('sxng-ai-page-tokens');
      if (!pill) return;
      var md = buildPageMarkdown(false);
      var tok = estimateTokens(md);
      pill.textContent = '~' + tok + ' tokens';
    }

    var copyMdBtn = document.getElementById('sxng-ai-copy-md-btn');
    if (copyMdBtn) {
      copyMdBtn.addEventListener('click', function () {
        copyText(buildPageMarkdown(false), copyMdBtn, '✅ Markdownコピー済');
      });
    }

    var copyPromptBtn = document.getElementById('sxng-ai-copy-prompt-btn');
    if (copyPromptBtn) {
      copyPromptBtn.addEventListener('click', function () {
        copyText(buildPageMarkdown(true), copyPromptBtn, '✅ プロンプトコピー済');
      });
    }

    var inlineDeepBtn = document.getElementById('sxng-ai-inline-deep-btn');
    var deepDrawer = document.getElementById('sxng-ai-deep-drawer');
    if (inlineDeepBtn && deepDrawer) {
      inlineDeepBtn.setAttribute('aria-expanded', 'false');
      inlineDeepBtn.setAttribute('aria-controls', 'sxng-ai-deep-drawer');
      inlineDeepBtn.addEventListener('click', function () {
        if (deepDrawer.classList.contains('open') && deepDrawer.dataset.loaded === '1') {
          deepDrawer.classList.remove('open');
          inlineDeepBtn.setAttribute('aria-expanded', 'false');
          return;
        }
        deepDrawer.classList.add('open');
        inlineDeepBtn.setAttribute('aria-expanded', 'true');
        if (deepDrawer.dataset.loaded === '1') return;

        var bar = document.getElementById('sxng-ai-results-bar');
        var q = (bar && bar.dataset.query) || (document.getElementById('q') ? document.getElementById('q').value : '');
        if (!q) return;

        deepDrawer.innerHTML = '<div>⚡ <strong>Agentic Deep Search 実行中...</strong> (並列本文抽出 + BM25 ハイライト + ドメイン評価)</div>';
        fetch('/deep_search?q=' + encodeURIComponent(q) + '&depth=advanced&max_results=5&max_tokens=3000')
          .then(function (r) { return r.json(); })
          .then(function (res) {
            if (res.error) {
              deepDrawer.innerHTML = '<div style="color:#ef4444;">⚠️ ' + escapeHtml(res.error) + '</div>';
              return;
            }
            deepDrawer.dataset.loaded = '1';
            deepDrawer.innerHTML = '';

            var topRow = document.createElement('div');
            topRow.style.display = 'flex';
            topRow.style.flexWrap = 'wrap';
            topRow.style.justifyContent = 'space-between';
            topRow.style.alignItems = 'center';
            topRow.style.gap = '0.5rem';

            var titleSpan = document.createElement('div');
            titleSpan.innerHTML = '<strong>⚡ Deep Search 完了</strong> ' +
              '<span class="sxng-ai-token-pill">Intent: ' + escapeHtml(res.intent || 'general') + '</span> ' +
              '<span class="sxng-ai-token-pill">~' + escapeHtml(res.estimated_tokens || 0) + ' tokens</span> ' +
              '<span class="sxng-ai-token-pill">' + escapeHtml(res.elapsed_ms || 0) + ' ms</span>';

            var btnGroup = document.createElement('div');
            btnGroup.style.display = 'flex';
            btnGroup.style.gap = '0.4rem';

            var copyDeepBtn = document.createElement('button');
            copyDeepBtn.type = 'button';
            copyDeepBtn.className = 'sxng-ai-btn sxng-ai-btn-primary';
            copyDeepBtn.innerHTML = '📋 Deep Search Markdownをコピー';
            copyDeepBtn.addEventListener('click', function () {
              copyText(res.markdown || '', copyDeepBtn, '✅ コピー完了');
            });

            var openWsLink = document.createElement('a');
            openWsLink.className = 'sxng-ai-btn';
            openWsLink.href = '/ai?q=' + encodeURIComponent(q) + '&mode=deep';
            openWsLink.innerHTML = '🚀 AI Workspace で詳細表示';

            btnGroup.appendChild(copyDeepBtn);
            btnGroup.appendChild(openWsLink);
            topRow.appendChild(titleSpan);
            topRow.appendChild(btnGroup);
            deepDrawer.appendChild(topRow);

            var pre = document.createElement('pre');
            pre.className = 'sxng-ai-deep-pre';
            pre.textContent = res.markdown || '';
            deepDrawer.appendChild(pre);
          })
          .catch(function (err) {
            deepDrawer.innerHTML = '<div style="color:#ef4444;">⚠️ Deep Search 通信エラー: ' + escapeHtml(err) + '</div>';
          });
      });
    }

    updateTokenCounter();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', enhanceSearchResultsPage);
  } else {
    enhanceSearchResultsPage();
  }
})();
"""


# ---------------------------------------------------------------------------
# Dedicated SearXNG Next AI Workspace HTML (`/ai`)
# ---------------------------------------------------------------------------

AI_WORKSPACE_HTML = """<!DOCTYPE html>
<html lang="ja" data-theme="dark">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <meta name="referrer" content="no-referrer">
  <title>SearXNG Next — AI Search &amp; Context Studio</title>
  <style>
    :root, [data-theme="dark"] {
      --bg-base: #0b0f19;
      --bg-surface: #111827;
      --bg-elevated: #1e293b;
      --bg-input: #0f172a;
      --border-color: #26334d;
      --border-hover: #4f46e5;
      --text-main: #f1f5f9;
      --text-secondary: #94a3b8;
      --text-muted: #64748b;
      --accent: #6366f1;
      --accent-hover: #818cf8;
      --accent-soft: rgba(99, 102, 241, 0.14);
      --emerald: #10b981;
      --emerald-soft: rgba(16, 185, 129, 0.14);
      --amber: #f59e0b;
      --amber-soft: rgba(245, 158, 11, 0.14);
      --danger: #ef4444;
      --danger-soft: rgba(239, 68, 68, 0.14);
      --shadow: 0 8px 24px rgba(0, 0, 0, 0.32);
    }
    [data-theme="light"] {
      --bg-base: #f8fafc;
      --bg-surface: #ffffff;
      --bg-elevated: #f1f5f9;
      --bg-input: #ffffff;
      --border-color: #e2e8f0;
      --border-hover: #4f46e5;
      --text-main: #0f172a;
      --text-secondary: #475569;
      --text-muted: #64748b;
      --accent: #4f46e5;
      --accent-hover: #4338ca;
      --accent-soft: rgba(79, 70, 229, 0.09);
      --emerald: #059669;
      --emerald-soft: rgba(5, 150, 105, 0.10);
      --amber: #d97706;
      --amber-soft: rgba(217, 119, 6, 0.10);
      --danger: #dc2626;
      --danger-soft: rgba(220, 38, 38, 0.10);
      --shadow: 0 6px 20px rgba(15, 23, 42, 0.06);
    }
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Hiragino Sans", "Noto Sans JP", sans-serif;
      background: var(--bg-base);
      color: var(--text-main);
      line-height: 1.55;
      min-height: 100vh;
      display: flex;
      flex-direction: column;
    }
    a { color: var(--accent-hover); text-decoration: none; }
    a:hover { text-decoration: underline; }
    /* Top Header */
    header.topbar {
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      justify-content: space-between;
      gap: 0.75rem;
      padding: 0.75rem 1.4rem;
      background: var(--bg-surface);
      border-bottom: 1px solid var(--border-color);
      position: sticky;
      top: 0;
      z-index: 50;
    }
    .brand-group {
      display: flex;
      align-items: center;
      gap: 0.65rem;
    }
    .brand-logo {
      font-weight: 800;
      font-size: 1.12rem;
      letter-spacing: -0.02em;
      color: var(--text-main);
      display: flex;
      align-items: center;
      gap: 0.45rem;
      text-decoration: none !important;
    }
    .brand-badge {
      font-size: 0.72rem;
      font-weight: 700;
      padding: 0.16rem 0.55rem;
      border-radius: 999px;
      background: var(--accent-soft);
      color: var(--accent-hover);
      border: 1px solid var(--border-color);
    }
    .status-dot {
      width: 8px;
      height: 8px;
      border-radius: 50%;
      background: var(--emerald);
      display: inline-block;
      box-shadow: 0 0 8px var(--emerald);
    }
    .nav-tabs {
      display: flex;
      flex-wrap: wrap;
      gap: 0.35rem;
    }
    .nav-tab {
      padding: 0.42rem 0.85rem;
      border-radius: 0.5rem;
      font-size: 0.83rem;
      font-weight: 600;
      background: transparent;
      color: var(--text-secondary);
      border: 1px solid transparent;
      cursor: pointer;
      transition: all 0.14s ease;
      display: inline-flex;
      align-items: center;
      gap: 0.35rem;
    }
    .nav-tab:hover {
      color: var(--text-main);
      background: var(--bg-elevated);
    }
    .nav-tab.active {
      color: var(--accent-hover);
      background: var(--accent-soft);
      border-color: var(--accent);
    }
    .header-actions {
      display: flex;
      align-items: center;
      gap: 0.5rem;
      font-size: 0.82rem;
    }
    .btn {
      display: inline-flex;
      align-items: center;
      gap: 0.35rem;
      padding: 0.42rem 0.8rem;
      border-radius: 0.5rem;
      font-size: 0.81rem;
      font-weight: 600;
      border: 1px solid var(--border-color);
      background: var(--bg-elevated);
      color: var(--text-main);
      cursor: pointer;
      transition: all 0.14s ease;
      text-decoration: none !important;
    }
    .btn:hover {
      border-color: var(--accent);
    }
    .btn-primary {
      background: var(--accent);
      color: #ffffff;
      border-color: transparent;
    }
    .btn-primary:hover {
      background: var(--accent-hover);
    }
    .btn-sm {
      padding: 0.25rem 0.58rem;
      font-size: 0.75rem;
      border-radius: 0.38rem;
    }
    /* Main Container */
    main.workspace {
      width: 100%;
      max-width: 1440px;
      margin: 0 auto;
      padding: 1.25rem 1.4rem 2.5rem;
      flex: 1;
    }
    /* Control Panel / Search Box */
    .search-panel {
      background: var(--bg-surface);
      border: 1px solid var(--border-color);
      border-radius: 0.85rem;
      padding: 1.1rem 1.2rem;
      box-shadow: var(--shadow);
      margin-bottom: 1.15rem;
    }
    .search-bar-row {
      display: flex;
      gap: 0.6rem;
      align-items: center;
    }
    .search-input-wrap {
      position: relative;
      flex: 1;
      display: flex;
      align-items: center;
    }
    .search-input {
      width: 100%;
      padding: 0.72rem 5.5rem 0.72rem 0.95rem;
      font-size: 0.98rem;
      border-radius: 0.6rem;
      border: 1px solid var(--border-color);
      background: var(--bg-input);
      color: var(--text-main);
      outline: none;
      transition: border-color 0.15s ease;
    }
    .search-input:focus,
    .search-input:focus-visible,
    .opt-select:focus,
    .opt-select:focus-visible,
    .opt-input:focus,
    .opt-input:focus-visible,
    .context-textarea:focus,
    .context-textarea:focus-visible {
      border-color: var(--accent);
      box-shadow: 0 0 0 2px var(--accent-soft);
    }
    .btn:focus-visible,
    .nav-tab:focus-visible,
    .chip:focus-visible,
    .cat-btn:focus-visible,
    .ctx-tab:focus-visible,
    .brand-logo:focus-visible {
      outline: 2px solid var(--accent);
      outline-offset: 2px;
    }
    .kbd-hint {
      position: absolute;
      right: 0.65rem;
      font-size: 0.72rem;
      font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      color: var(--text-muted);
      padding: 0.12rem 0.42rem;
      border-radius: 0.3rem;
      border: 1px solid var(--border-color);
      background: var(--bg-surface);
      pointer-events: none;
    }
    .options-row {
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      gap: 0.75rem;
      margin-top: 0.8rem;
      padding-top: 0.75rem;
      border-top: 1px solid var(--border-color);
      font-size: 0.8rem;
      color: var(--text-secondary);
    }
    .opt-group {
      display: inline-flex;
      align-items: center;
      gap: 0.38rem;
    }
    .opt-select, .opt-input {
      padding: 0.28rem 0.55rem;
      border-radius: 0.4rem;
      border: 1px solid var(--border-color);
      background: var(--bg-input);
      color: var(--text-main);
      font-size: 0.79rem;
      outline: none;
    }
    .opt-input {
      width: 11rem;
    }
    .preset-chips {
      display: inline-flex;
      flex-wrap: wrap;
      gap: 0.35rem;
      margin-left: auto;
    }
    .chip, .cat-btn {
      padding: 0.2rem 0.6rem;
      border-radius: 999px;
      font-size: 0.75rem;
      font-weight: 500;
      border: 1px solid var(--border-color);
      background: var(--bg-elevated);
      color: var(--text-secondary);
      cursor: pointer;
      transition: all 0.12s ease;
    }
    .chip:hover, .cat-btn:hover {
      border-color: var(--accent);
      color: var(--text-main);
    }
    .cat-btn.active {
      background: var(--accent-soft);
      border-color: var(--accent);
      color: var(--accent-hover);
      font-weight: 700;
    }
    /* Telemetry Ribbon */
    .telemetry-bar {
      display: none;
      flex-wrap: wrap;
      align-items: center;
      justify-content: space-between;
      gap: 0.65rem;
      padding: 0.65rem 1rem;
      margin-bottom: 1rem;
      border-radius: 0.65rem;
      background: var(--bg-surface);
      border: 1px solid var(--border-color);
      font-size: 0.81rem;
    }
    .telemetry-bar.visible {
      display: flex;
    }
    .telemetry-left, .telemetry-right {
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      gap: 0.5rem;
    }
    .pill {
      display: inline-flex;
      align-items: center;
      gap: 0.3rem;
      padding: 0.2rem 0.6rem;
      border-radius: 999px;
      font-size: 0.75rem;
      font-weight: 600;
      font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      background: var(--bg-elevated);
      color: var(--text-secondary);
      border: 1px solid var(--border-color);
    }
    .pill-accent {
      background: var(--accent-soft);
      color: var(--accent-hover);
      border-color: var(--accent);
    }
    .pill-emerald {
      background: var(--emerald-soft);
      color: var(--emerald);
      border-color: var(--emerald);
    }
    .pill-amber {
      background: var(--amber-soft);
      color: var(--amber);
      border-color: var(--amber);
    }
    .pill-danger {
      background: var(--danger-soft);
      color: var(--danger);
      border-color: var(--danger);
    }
    /* Split Grid Layout (AI Deep Search) */
    .split-grid {
      display: grid;
      grid-template-columns: 1.25fr 0.95fr;
      gap: 1.15rem;
      align-items: start;
    }
    @media (max-width: 1024px) {
      .split-grid {
        grid-template-columns: 1fr;
      }
      .context-panel {
        position: static;
      }
    }
    @media (max-width: 640px) {
      header.topbar {
        padding: 0.65rem 0.9rem;
      }
      main.workspace {
        padding: 0.9rem 0.9rem 2rem;
      }
      .search-bar-row {
        flex-wrap: wrap;
      }
      .search-bar-row #run-btn {
        width: 100%;
        justify-content: center;
      }
      .kbd-hint {
        display: none;
      }
      .search-input {
        padding-right: 0.95rem;
      }
      .preset-chips {
        margin-left: 0;
        width: 100%;
      }
    }
    /* Result Cards */
    .results-list {
      display: flex;
      flex-direction: column;
      gap: 0.85rem;
    }
    .result-card {
      background: var(--bg-surface);
      border: 1px solid var(--border-color);
      border-radius: 0.75rem;
      padding: 0.95rem 1.1rem;
      transition: border-color 0.15s ease;
    }
    .result-card:hover {
      border-color: var(--border-hover);
    }
    .card-top {
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 0.5rem;
      margin-bottom: 0.4rem;
      font-size: 0.76rem;
    }
    .card-domain {
      color: var(--text-muted);
      font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      display: flex;
      align-items: center;
      gap: 0.35rem;
    }
    .card-rank {
      color: var(--accent-hover);
      font-weight: 700;
    }
    .card-badges {
      display: flex;
      align-items: center;
      gap: 0.35rem;
    }
    .card-title {
      font-size: 1.05rem;
      font-weight: 700;
      line-height: 1.35;
      margin-bottom: 0.45rem;
    }
    .card-snippet {
      font-size: 0.85rem;
      color: var(--text-secondary);
      line-height: 1.5;
      margin-bottom: 0.6rem;
    }
    .card-actions {
      display: flex;
      flex-wrap: wrap;
      gap: 0.4rem;
      margin-top: 0.5rem;
      padding-top: 0.5rem;
      border-top: 1px dashed var(--border-color);
    }
    .highlight-block {
      background: var(--bg-elevated);
      border-left: 3px solid var(--accent);
      padding: 0.5rem 0.75rem;
      border-radius: 0.35rem;
      font-size: 0.82rem;
      color: var(--text-main);
      margin-bottom: 0.45rem;
      white-space: pre-wrap;
    }
    .highlight-code {
      background: var(--bg-input);
      border: 1px solid var(--border-color);
      padding: 0.6rem 0.75rem;
      border-radius: 0.45rem;
      font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      font-size: 0.78rem;
      overflow-x: auto;
      margin-bottom: 0.45rem;
    }
    .inline-scrape-drawer {
      margin-top: 0.65rem;
      padding: 0.8rem;
      border-radius: 0.5rem;
      background: var(--bg-input);
      border: 1px solid var(--border-color);
      font-size: 0.8rem;
      max-height: 22rem;
      overflow-y: auto;
      white-space: pre-wrap;
      word-break: break-word;
    }
    /* Context Panel (AI Studio Right) */
    .context-panel {
      background: var(--bg-surface);
      border: 1px solid var(--border-color);
      border-radius: 0.85rem;
      padding: 1rem 1.1rem;
      box-shadow: var(--shadow);
      position: sticky;
      top: 4.8rem;
      display: flex;
      flex-direction: column;
      gap: 0.75rem;
      max-height: calc(100vh - 6rem);
    }
    .context-header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 0.5rem;
    }
    .context-tabs {
      display: flex;
      gap: 0.3rem;
      border-bottom: 1px solid var(--border-color);
      padding-bottom: 0.4rem;
    }
    .ctx-tab {
      padding: 0.25rem 0.6rem;
      font-size: 0.76rem;
      font-weight: 600;
      background: transparent;
      color: var(--text-secondary);
      border: none;
      cursor: pointer;
      border-radius: 0.35rem;
    }
    .ctx-tab.active {
      color: var(--accent-hover);
      background: var(--accent-soft);
    }
    .context-textarea {
      width: 100%;
      height: 24rem;
      background: var(--bg-input);
      color: var(--text-main);
      border: 1px solid var(--border-color);
      border-radius: 0.5rem;
      padding: 0.75rem;
      font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      font-size: 0.78rem;
      line-height: 1.5;
      resize: vertical;
      outline: none;
    }
    .token-progress-wrap {
      display: flex;
      flex-direction: column;
      gap: 0.3rem;
      font-size: 0.75rem;
      color: var(--text-secondary);
    }
    .token-bar-bg {
      width: 100%;
      height: 6px;
      border-radius: 999px;
      background: var(--bg-elevated);
      overflow: hidden;
    }
    .token-bar-fill {
      height: 100%;
      background: var(--accent);
      width: 0%;
      transition: width 0.2s ease;
    }

    /* Classic Search Mode View (Centered Single Column) */
    .classic-view-wrap {
      max-width: 900px;
      margin: 0 auto;
      width: 100%;
    }
    .classic-card {
      background: var(--bg-surface);
      border: 1px solid var(--border-color);
      border-radius: 0.75rem;
      padding: 1.05rem 1.25rem;
      margin-bottom: 0.85rem;
      transition: border-color 0.15s ease, box-shadow 0.15s ease;
    }
    .classic-card:hover {
      border-color: var(--border-hover);
      box-shadow: 0 4px 16px rgba(0,0,0,0.18);
    }
    .classic-meta-row {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 0.6rem;
      margin-bottom: 0.35rem;
      font-size: 0.78rem;
    }
    .classic-url-tag {
      color: var(--text-muted);
      font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      display: flex;
      align-items: center;
      gap: 0.4rem;
      word-break: break-all;
    }
    .classic-title-link {
      font-size: 1.15rem;
      font-weight: 700;
      line-height: 1.35;
      margin-bottom: 0.45rem;
      display: inline-block;
    }
    .classic-snippet-text {
      font-size: 0.88rem;
      color: var(--text-secondary);
      line-height: 1.55;
      margin-bottom: 0.65rem;
    }
    .classic-actions-row {
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      gap: 0.45rem;
      padding-top: 0.5rem;
      border-top: 1px dashed var(--border-color);
    }
    .classic-pagination-row {
      display: flex;
      align-items: center;
      justify-content: center;
      gap: 0.75rem;
      margin-top: 1.5rem;
      padding: 1rem 0;
    }
    .classic-answer-box {
      background: var(--bg-elevated);
      border-left: 4px solid var(--accent);
      border-radius: 0.6rem;
      padding: 0.9rem 1.1rem;
      margin-bottom: 1rem;
      font-size: 0.92rem;
    }

    /* Settings Dashboard View */
    .settings-view-wrap {
      max-width: 1100px;
      margin: 0 auto;
      width: 100%;
    }
    .stats-overview-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
      gap: 0.85rem;
      margin-bottom: 1.25rem;
    }
    .stat-card {
      background: var(--bg-surface);
      border: 1px solid var(--border-color);
      border-radius: 0.75rem;
      padding: 0.9rem 1.1rem;
      display: flex;
      flex-direction: column;
      gap: 0.25rem;
    }
    .stat-card-label {
      font-size: 0.75rem;
      color: var(--text-muted);
      text-transform: uppercase;
      font-weight: 700;
      letter-spacing: 0.04em;
    }
    .stat-card-value {
      font-size: 1.45rem;
      font-weight: 800;
      color: var(--text-main);
    }
    .settings-subtabs {
      display: flex;
      gap: 0.5rem;
      margin-bottom: 1rem;
      border-bottom: 1px solid var(--border-color);
      padding-bottom: 0.5rem;
    }
    .settings-subtab {
      padding: 0.45rem 1rem;
      border-radius: 0.5rem;
      font-size: 0.84rem;
      font-weight: 600;
      background: transparent;
      color: var(--text-secondary);
      border: 1px solid transparent;
      cursor: pointer;
    }
    .settings-subtab.active {
      color: var(--accent-hover);
      background: var(--accent-soft);
      border-color: var(--accent);
    }
    .engine-toolbar {
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      justify-content: space-between;
      gap: 0.75rem;
      margin-bottom: 1rem;
      background: var(--bg-surface);
      border: 1px solid var(--border-color);
      border-radius: 0.75rem;
      padding: 0.75rem 1rem;
    }
    .engine-search-wrap {
      flex: 1;
      min-width: 14rem;
    }
    .engine-search-input {
      width: 100%;
      padding: 0.45rem 0.85rem;
      border-radius: 0.45rem;
      border: 1px solid var(--border-color);
      background: var(--bg-input);
      color: var(--text-main);
      font-size: 0.82rem;
      outline: none;
    }
    .engine-bulk-actions {
      display: flex;
      gap: 0.4rem;
    }
    .engines-category-chips {
      display: flex;
      flex-wrap: wrap;
      gap: 0.35rem;
      margin-bottom: 1rem;
    }
    .engines-grid {
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(310px, 1fr));
      gap: 0.85rem;
    }
    .engine-item-card {
      background: var(--bg-surface);
      border: 1px solid var(--border-color);
      border-radius: 0.65rem;
      padding: 0.85rem 1rem;
      display: flex;
      flex-direction: column;
      gap: 0.5rem;
      transition: border-color 0.15s ease;
    }
    .engine-item-card:hover {
      border-color: var(--border-hover);
    }
    .engine-item-header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 0.5rem;
    }
    .engine-item-title {
      font-weight: 700;
      font-size: 0.92rem;
      display: flex;
      align-items: center;
      gap: 0.4rem;
    }
    .engine-item-meta {
      display: flex;
      flex-wrap: wrap;
      gap: 0.35rem;
      font-size: 0.74rem;
    }
    /* Toggle Switch */
    .switch-label {
      position: relative;
      display: inline-block;
      width: 40px;
      height: 22px;
      flex-shrink: 0;
    }
    .switch-label input {
      opacity: 0;
      width: 0;
      height: 0;
    }
    .switch-slider {
      position: absolute;
      cursor: pointer;
      top: 0; left: 0; right: 0; bottom: 0;
      background-color: var(--bg-elevated);
      border: 1px solid var(--border-color);
      transition: .2s;
      border-radius: 22px;
    }
    .switch-slider:before {
      position: absolute;
      content: "";
      height: 16px;
      width: 16px;
      left: 2px;
      bottom: 2px;
      background-color: var(--text-muted);
      transition: .2s;
      border-radius: 50%;
    }
    input:checked + .switch-slider {
      background-color: var(--accent);
      border-color: var(--accent);
    }
    input:checked + .switch-slider:before {
      transform: translateX(18px);
      background-color: #ffffff;
    }
    /* General Settings Form */
    .general-settings-card {
      background: var(--bg-surface);
      border: 1px solid var(--border-color);
      border-radius: 0.75rem;
      padding: 1.25rem 1.4rem;
      display: flex;
      flex-direction: column;
      gap: 1.2rem;
    }
    .settings-row {
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      justify-content: space-between;
      gap: 1rem;
      padding-bottom: 1rem;
      border-bottom: 1px solid var(--border-color);
    }
    .settings-row:last-child {
      border-bottom: none;
      padding-bottom: 0;
    }
    .settings-label-wrap h4 {
      font-size: 0.92rem;
      margin-bottom: 0.2rem;
    }
    .settings-label-wrap p {
      font-size: 0.78rem;
      color: var(--text-secondary);
    }

    /* Agent Hub Grid */
    .hub-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(min(100%, 320px), 1fr));
      gap: 1rem;
    }
    .hub-card {
      background: var(--bg-surface);
      border: 1px solid var(--border-color);
      border-radius: 0.75rem;
      padding: 1rem 1.1rem;
    }
    .hub-card h3 {
      font-size: 0.95rem;
      margin-bottom: 0.4rem;
      display: flex;
      align-items: center;
      justify-content: space-between;
    }
    .hub-card p {
      font-size: 0.8rem;
      color: var(--text-secondary);
      margin-bottom: 0.6rem;
    }
    .hub-pre {
      padding: 0.65rem;
      border-radius: 0.45rem;
      background: var(--bg-input);
      border: 1px solid var(--border-color);
      font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      font-size: 0.76rem;
      overflow-x: auto;
      white-space: pre-wrap;
      word-break: break-all;
    }
    .empty-state {
      text-align: center;
      padding: 3rem 1rem;
      color: var(--text-secondary);
      background: var(--bg-surface);
      border: 1px dashed var(--border-color);
      border-radius: 0.75rem;
    }
    .empty-state h2 {
      font-size: 1.15rem;
      color: var(--text-main);
      margin-bottom: 0.4rem;
    }
    .sample-queries {
      display: flex;
      flex-wrap: wrap;
      justify-content: center;
      gap: 0.45rem;
      margin-top: 1rem;
    }
    /* Toast Notification */
    .toast-notice {
      position: fixed;
      bottom: 2rem;
      right: 2rem;
      padding: 0.75rem 1.25rem;
      border-radius: 0.5rem;
      background: var(--accent);
      color: #ffffff;
      font-size: 0.85rem;
      font-weight: 600;
      box-shadow: 0 8px 24px rgba(0,0,0,0.35);
      z-index: 1000;
      opacity: 0;
      pointer-events: none;
      transition: opacity 0.25s ease, transform 0.25s ease;
      transform: translateY(10px);
    }
    .toast-notice.show {
      opacity: 1;
      pointer-events: auto;
      transform: translateY(0);
    }
    footer.ws-footer {
      text-align: center;
      padding: 1rem;
      font-size: 0.76rem;
      color: var(--text-muted);
      border-top: 1px solid var(--border-color);
      background: var(--bg-surface);
    }
  </style>
</head>
<body>
  <header class="topbar">
    <div class="brand-group">
      <a href="/" class="brand-logo" title="SearXNG Next Studio">
        <span>⚡ SearXNG Next</span>
      </a>
      <span class="brand-badge">AI-First Edition</span>
      <span class="status-dot" id="health-dot" role="img" aria-label="Checking server status" title="Checking server status"></span>
    </div>

    <nav class="nav-tabs" role="tablist" aria-label="Workspace Modes">
      <button type="button" class="nav-tab active" role="tab" aria-selected="true" aria-controls="main-split-view" data-mode="deep" id="tab-deep">⚡ AI Deep Search</button>
      <button type="button" class="nav-tab" role="tab" aria-selected="false" aria-controls="classic-search-view" data-mode="classic" id="tab-classic">🔍 Classic 検索</button>
      <button type="button" class="nav-tab" role="tab" aria-selected="false" aria-controls="agent-hub-view" data-mode="agent" id="tab-agent">🤖 Agent &amp; MCP Hub</button>
      <button type="button" class="nav-tab" role="tab" aria-selected="false" aria-controls="settings-view" data-mode="settings" id="tab-settings">⚙️ 設定</button>
    </nav>

    <div class="header-actions">
      <button type="button" class="btn btn-sm" id="theme-toggle-btn" title="テーマ切替 (Dark / Light)">🌗 テーマ</button>
    </div>
  </header>

  <main class="workspace">
    <!-- Common Search & Scrape Input Panel -->
    <section class="search-panel" id="input-panel">
      <form id="ws-form" role="search">
        <div class="search-bar-row">
          <div class="search-input-wrap">
            <input
              id="q"
              name="q"
              type="text"
              class="search-input"
              aria-label="Search query or target URL"
              placeholder="キーワード・質問 または URL (https://...) を入力 — URLは自動で本文抽出モードに切替..."
              autocomplete="off"
              autofocus
            >
            <span class="kbd-hint">/ or Ctrl+K</span>
          </div>
          <button type="submit" class="btn btn-primary" id="run-btn" style="padding:0.72rem 1.25rem;font-size:0.9rem;">
            ⚡ 統合検索
          </button>
        </div>

        <!-- AI Deep Search Options -->
        <div class="options-row" id="search-options-row">
          <div class="opt-group" id="opt-depth-group">
            <label for="opt-depth">Depth:</label>
            <select id="opt-depth" class="opt-select">
              <option value="advanced" selected>⚡ Deep: Advanced (並列本文抽出 + BM25)</option>
              <option value="code">💻 Deep: Code &amp; Docs (技術・GitHub優先)</option>
              <option value="basic">📊 Basic (スニペット + ドメイン評価)</option>
              <option value="fast">🚀 Fast: json_lite (最速スニペットのみ)</option>
            </select>
          </div>

          <div class="opt-group">
            <label for="opt-count">件数:</label>
            <select id="opt-count" class="opt-select">
              <option value="3">3件</option>
              <option value="5" selected>5件</option>
              <option value="8">8件</option>
              <option value="10">10件</option>
              <option value="15">15件</option>
            </select>
          </div>

          <div class="opt-group" id="opt-tokens-group">
            <label for="opt-tokens">Token予算:</label>
            <select id="opt-tokens" class="opt-select">
              <option value="1500">1,500 tok</option>
              <option value="3000" selected>3,000 tok</option>
              <option value="6000">6,000 tok</option>
              <option value="10000">10,000 tok</option>
            </select>
          </div>

          <div class="opt-group" id="opt-site-group">
            <label for="opt-site">site:</label>
            <input id="opt-site" type="text" class="opt-input" placeholder="docs.python.org, github.com">
          </div>

          <div class="preset-chips" id="preset-chips">
            <button type="button" class="chip" data-preset="docs">📚 公式Docs優先</button>
            <button type="button" class="chip" data-preset="github">🐙 GitHub + SO</button>
            <button type="button" class="chip" data-preset="academic">🎓 Academic</button>
            <button type="button" class="chip" data-preset="clear">🧹 フィルタ解除</button>
          </div>
        </div>

        <!-- Classic Search Options (Category pills & Time range) -->
        <div class="options-row" id="classic-options-row" style="display:none;">
          <div class="opt-group" style="flex: 1; flex-wrap: wrap;">
            <span style="font-weight:600;font-size:0.78rem;color:var(--text-muted);margin-right:0.2rem;">カテゴリー:</span>
            <div class="preset-chips" id="classic-cat-chips" style="margin-left:0;">
              <button type="button" class="cat-btn active" data-cat="">🌐 全般</button>
              <button type="button" class="cat-btn" data-cat="it">💻 IT・技術</button>
              <button type="button" class="cat-btn" data-cat="news">📰 ニュース</button>
              <button type="button" class="cat-btn" data-cat="science">🔬 科学</button>
              <button type="button" class="cat-btn" data-cat="files">📁 ファイル</button>
              <button type="button" class="cat-btn" data-cat="social media">💬 ソーシャル</button>
              <button type="button" class="cat-btn" data-cat="images">🖼️ 画像</button>
              <button type="button" class="cat-btn" data-cat="videos">🎬 動画</button>
            </div>
          </div>

          <div class="opt-group">
            <label for="classic-time-range">期間:</label>
            <select id="classic-time-range" class="opt-select">
              <option value="" selected>指定なし</option>
              <option value="day">24時間以内</option>
              <option value="week">1週間以内</option>
              <option value="month">1ヶ月以内</option>
              <option value="year">1年以内</option>
            </select>
          </div>

          <div class="opt-group">
            <label for="classic-count">件数:</label>
            <select id="classic-count" class="opt-select">
              <option value="10" selected>10件</option>
              <option value="20">20件</option>
              <option value="30">30件</option>
            </select>
          </div>
        </div>

        <!-- Scrape Mode Options (Auto-shown when URL is entered) -->
        <div class="options-row" id="scrape-options-row" style="display:none;">
          <div class="opt-group">
            <label for="opt-scrape-len">最大文字数:</label>
            <select id="opt-scrape-len" class="opt-select">
              <option value="4000">4,000 文字</option>
              <option value="8000" selected>8,000 文字</option>
              <option value="15000">15,000 文字</option>
              <option value="30000">30,000 文字</option>
            </select>
          </div>
          <div class="opt-group" style="flex:1;">
            <label for="opt-scrape-query">BM25 抽出キーワード (任意):</label>
            <input id="opt-scrape-query" type="text" class="opt-input" style="width:100%;max-width:24rem;" placeholder="ページ内からピンポイント抽出したい語句 (空欄なら全文のみ)">
          </div>
          <span class="pill pill-emerald">🛡️ URL自動検知 · DNS-Pinned &amp; SSRF Protected</span>
        </div>
      </form>
    </section>

    <!-- Telemetry & Quick Action Ribbon -->
    <section class="telemetry-bar" id="telemetry-bar" role="status" aria-live="polite">
      <div class="telemetry-left" id="telemetry-badges"></div>
      <div class="telemetry-right">
        <button type="button" class="btn btn-primary btn-sm" id="copy-md-main">📋 AI用Markdownをコピー</button>
        <button type="button" class="btn btn-sm" id="copy-prompt-main">💬 RAGプロンプト形式でコピー</button>
        <button type="button" class="btn btn-sm" id="copy-json-main">{ } JSONをコピー</button>
        <button type="button" class="btn btn-sm" id="download-md-btn">💾 .md 保存</button>
      </div>
    </section>

    <!-- View 1: AI Deep Search (Split Grid View) -->
    <section class="split-grid" id="main-split-view" role="tabpanel" aria-labelledby="tab-deep">
      <div class="results-list" id="results-container" aria-live="polite" aria-busy="false">
        <div class="empty-state" id="initial-empty-state">
          <h2>⚡ AI-First Unified Search &amp; Context Studio</h2>
          <p>検索キーワードを入力すると Deep Search (並列本文抽出 + BM25パッセージ抽出) を実行し、URL を貼り付けると自動で単一ページ本文抽出に切り替わります。</p>
          <div class="sample-queries">
            <button type="button" class="chip sample-q" data-q="FastAPI lifespan context manager syntax">🔎 FastAPI lifespan context manager</button>
            <button type="button" class="chip sample-q" data-q="Python asyncio TaskGroup exception handling">🔎 Python asyncio.TaskGroup</button>
            <button type="button" class="chip sample-q" data-q="https://docs.searxng.org">📄 https://docs.searxng.org (URL抽出デモ)</button>
          </div>
        </div>
      </div>

      <!-- Sticky Right Panel: AI Context Inspector -->
      <aside class="context-panel" id="context-panel">
        <div class="context-header">
          <strong style="font-size:0.88rem;">🧠 LLM Context Inspector</strong>
          <div style="display:flex;gap:0.35rem;">
            <button type="button" class="btn btn-primary btn-sm" id="ctx-copy-btn">📋 コピー</button>
          </div>
        </div>
        <div class="context-tabs" role="tablist" aria-label="Context Output Format">
          <button type="button" class="ctx-tab active" role="tab" aria-selected="true" aria-controls="ctx-output" data-ctx="markdown">Markdown</button>
          <button type="button" class="ctx-tab" role="tab" aria-selected="false" aria-controls="ctx-output" data-ctx="prompt">RAG Prompt</button>
          <button type="button" class="ctx-tab" role="tab" aria-selected="false" aria-controls="ctx-output" data-ctx="json">JSON</button>
          <button type="button" class="ctx-tab" role="tab" aria-selected="false" aria-controls="ctx-output" data-ctx="curl">API / CLI</button>
        </div>
        <textarea id="ctx-output" class="context-textarea" readonly aria-label="Generated AI Context" placeholder="検索またはURL本文抽出を実行すると、ここにLLM貼り付け用の構造化Markdown・プロンプト・JSONが生成されます。"></textarea>
        <div class="token-progress-wrap">
          <span id="token-usage-label">0 / 3,000 tokens</span>
          <div class="token-bar-bg"><div class="token-bar-fill" id="token-bar-fill"></div></div>
        </div>
      </aside>
    </section>

    <!-- View 2: Classic Lightweight Search View (Single Column) -->
    <section id="classic-search-view" class="classic-view-wrap" role="tabpanel" aria-labelledby="tab-classic" style="display:none;">
      <div id="classic-telemetry-pill" style="margin-bottom:0.75rem;font-size:0.8rem;color:var(--text-muted);display:none;"></div>
      <div id="classic-answers-container"></div>
      <div id="classic-results-container" class="results-list" aria-live="polite" aria-busy="false">
        <div class="empty-state">
          <h2>🔍 Classic 軽量メタ検索モード</h2>
          <p>余分なAIパッキングを省き、複数の検索エンジンからスニペットを高速取得して一覧表示します。上部のカテゴリータブで絞り込みも可能です。</p>
          <div class="sample-queries">
            <button type="button" class="chip sample-classic-q" data-q="SearXNG Windows next release">🔎 SearXNG Windows next release</button>
            <button type="button" class="chip sample-classic-q" data-q="uv python package manager">🔎 uv python package manager</button>
          </div>
        </div>
      </div>
      <div id="classic-pagination-bar" class="classic-pagination-row" style="display:none;">
        <button type="button" class="btn btn-sm" id="classic-prev-btn">← 前のページ</button>
        <span id="classic-page-indicator" class="pill">ページ 1</span>
        <button type="button" class="btn btn-sm" id="classic-next-btn">次のページ →</button>
      </div>
    </section>

    <!-- View 3: Agent & MCP Hub View -->
    <section id="agent-hub-view" role="tabpanel" aria-labelledby="tab-agent" style="display:none;">
      <div class="hub-grid" id="hub-cards-container" aria-live="polite"></div>
    </section>

    <!-- View 4: Settings Dashboard View -->
    <section id="settings-view" class="settings-view-wrap" role="tabpanel" aria-labelledby="tab-settings" style="display:none;">
      <!-- Stats Overview Cards -->
      <div class="stats-overview-grid" id="settings-stats-grid">
        <div class="stat-card">
          <span class="stat-card-label">稼働中エンジン</span>
          <span class="stat-card-value" id="stat-active-engines">-- / --</span>
        </div>
        <div class="stat-card">
          <span class="stat-card-label">一時停止 / レート制限中</span>
          <span class="stat-card-value" id="stat-suspended-engines" style="color:var(--amber);">0</span>
        </div>
        <div class="stat-card">
          <span class="stat-card-label">平均応答時間</span>
          <span class="stat-card-value" id="stat-avg-latency">-- ms</span>
        </div>
        <div class="stat-card">
          <span class="stat-card-label">全体信頼性スコア</span>
          <span class="stat-card-value" id="stat-avg-reliability" style="color:var(--emerald);">--%</span>
        </div>
      </div>

      <!-- Settings Subtabs -->
      <div class="settings-subtabs" role="tablist">
        <button type="button" class="settings-subtab active" data-subtab="engines" id="subtab-engines-btn">🔌 検索エンジン管理</button>
        <button type="button" class="settings-subtab" data-subtab="general" id="subtab-general-btn">⚙️ 一般設定</button>
      </div>

      <!-- Section: Search Engines -->
      <div id="section-settings-engines">
        <div class="engine-toolbar">
          <div class="engine-search-wrap">
            <input type="text" id="engine-search-input" class="engine-search-input" placeholder="エンジン名やカテゴリーで絞り込み...">
          </div>
          <div class="engine-bulk-actions">
            <button type="button" class="btn btn-sm" id="btn-enable-all-cat">カテゴリー内を全有効化</button>
            <button type="button" class="btn btn-sm" id="btn-disable-all-cat">カテゴリー内を全無効化</button>
            <button type="button" class="btn btn-sm" id="btn-reset-engines-def">デフォルトに戻す</button>
            <button type="button" class="btn btn-primary btn-sm" id="btn-save-settings-engines">💾 変更を保存</button>
          </div>
        </div>

        <div class="engines-category-chips" id="settings-engine-cat-chips"></div>
        <div class="engines-grid" id="settings-engines-grid"></div>
      </div>

      <!-- Section: General Preferences -->
      <div id="section-settings-general" style="display:none;">
        <div class="general-settings-card">
          <div class="settings-row">
            <div class="settings-label-wrap">
              <h4>デフォルト検索モード</h4>
              <p>検索トップ画面にアクセスした際、または外部から検索時の初期モード</p>
            </div>
            <div>
              <select id="pref-default-mode" class="opt-select" style="min-width:14rem;">
                <option value="deep" selected>⚡ AI Deep Search (並列抽出 + BM25)</option>
                <option value="classic">🔍 Classic 検索 (軽量メタ検索)</option>
                <option value="balanced">🧠 Retrieval (Balanced グラウンディング)</option>
              </select>
            </div>
          </div>

          <div class="settings-row">
            <div class="settings-label-wrap">
              <h4>セーフサーチ (SafeSearch)</h4>
              <p>成人向けコンテンツのフィルタリング設定</p>
            </div>
            <div>
              <select id="pref-safesearch" class="opt-select" style="min-width:14rem;">
                <option value="0">無効 (Off)</option>
                <option value="1" selected>標準 (Moderate)</option>
                <option value="2">厳格 (Strict)</option>
              </select>
            </div>
          </div>

          <div class="settings-row">
            <div class="settings-label-wrap">
              <h4>デフォルト取得件数</h4>
              <p>検索時に各エンジンから集約・選抜する結果件数の標準値</p>
            </div>
            <div>
              <select id="pref-default-count" class="opt-select" style="min-width:14rem;">
                <option value="5">5件</option>
                <option value="10" selected>10件</option>
                <option value="15">15件</option>
                <option value="20">20件</option>
              </select>
            </div>
          </div>

          <div class="settings-row">
            <div class="settings-label-wrap">
              <h4>トークン予算上限</h4>
              <p>AI Deep Search時にLLMへ渡すMarkdownコンテキストの上限</p>
            </div>
            <div>
              <select id="pref-default-tokens" class="opt-select" style="min-width:14rem;">
                <option value="1500">1,500 tok</option>
                <option value="3000" selected>3,000 tok</option>
                <option value="6000">6,000 tok</option>
                <option value="10000">10,000 tok</option>
              </select>
            </div>
          </div>

          <div style="display:flex;justify-content:flex-end;gap:0.6rem;margin-top:0.5rem;">
            <button type="button" class="btn" id="btn-reset-general-prefs">初期値に戻す</button>
            <button type="button" class="btn btn-primary" id="btn-save-general-prefs">💾 一般設定を保存</button>
          </div>
        </div>
      </div>
    </section>
  </main>

  <div id="toast-notice" class="toast-notice" role="status" aria-live="polite"></div>

  <footer class="ws-footer">
    SearXNG for Windows Next — AI-First Dedicated Studio ·
    <a href="/healthz">Health (/healthz)</a> ·
    <a href="/api/ai_info">AI Info (/api/ai_info)</a> ·
    <a href="/api/settings/engines">Engines API</a>
  </footer>

  <script>
    (function () {
      'use strict';

      var state = {
        mode: 'deep',
        ctxTab: 'markdown',
        lastData: null,
        markdown: '',
        prompt: '',
        jsonStr: '',
        curlStr: '',
        maxTokens: 3000,
        classicCategory: '',
        classicTimeRange: '',
        classicPage: 1,
        classicCount: 10,
        settingsEngines: [],
        settingsCategories: [],
        settingsCurrentCat: '',
        settingsSearch: '',
        togglesModified: false
      };

      function escapeHtml(str) {
        return String(str == null ? '' : str)
          .replace(/&/g, '&amp;')
          .replace(/</g, '&lt;')
          .replace(/>/g, '&gt;')
          .replace(/"/g, '&quot;')
          .replace(/'/g, '&#39;');
      }

      function safeHttpUrl(url) {
        var s = String(url == null ? '' : url).trim();
        if (!s) return '#';
        try {
          var parsed = new URL(s, window.location.origin);
          if (parsed.protocol === 'http:' || parsed.protocol === 'https:') {
            return parsed.href;
          }
        } catch (e) {}
        return '#';
      }

      function escapeShellDoubleQuoted(str) {
        return String(str == null ? '' : str)
          .replace(/[\\$"\\`!]/g, function (ch) { return '\\' + ch; });
      }

      function showToast(msg) {
        var toast = document.getElementById('toast-notice');
        if (!toast) return;
        toast.textContent = msg;
        toast.classList.add('show');
        setTimeout(function () {
          toast.classList.remove('show');
        }, 2200);
      }

      // Theme initialization
      var savedTheme = localStorage.getItem('sxng_ai_theme') || 'dark';
      document.documentElement.setAttribute('data-theme', savedTheme);
      document.getElementById('theme-toggle-btn').addEventListener('click', function () {
        var cur = document.documentElement.getAttribute('data-theme') === 'light' ? 'dark' : 'light';
        document.documentElement.setAttribute('data-theme', cur);
        localStorage.setItem('sxng_ai_theme', cur);
      });

      // Server status indicator: verify /healthz
      (function checkServerHealth() {
        var dot = document.getElementById('health-dot');
        if (!dot) return;
        fetch('/healthz')
          .then(function (r) {
            var online = r.ok;
            dot.setAttribute('aria-label', online ? 'Server Online' : 'Server Error');
            dot.setAttribute('title', online ? 'Server Online' : 'Server Error');
            if (!online) dot.style.background = 'var(--danger)';
          })
          .catch(function () {
            dot.setAttribute('aria-label', 'Server Offline');
            dot.setAttribute('title', 'Server Offline');
            dot.style.background = 'var(--danger)';
          });
      })();

      function isUrlText(text) {
        var s = (text || '').trim();
        return /^https?:\\/\\/\\S+$/i.test(s);
      }

      function estimateTokens(text) {
        if (!text) return 0;
        var cjk = (text.match(/[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff]/g) || []).length;
        var other = text.length - cjk;
        return Math.round(cjk / 1.5 + other / 4.0);
      }

      function copyWithFeedback(text, btn, label) {
        if (!text) return;
        var orig = btn.innerHTML;
        var done = function () {
          btn.innerHTML = label || '✅ コピー完了';
          setTimeout(function () { btn.innerHTML = orig; }, 1500);
        };
        if (navigator.clipboard && navigator.clipboard.writeText) {
          navigator.clipboard.writeText(text).then(done).catch(done);
        } else {
          var ta = document.createElement('textarea');
          ta.value = text;
          document.body.appendChild(ta);
          ta.select();
          try { document.execCommand('copy'); } catch (e) {}
          document.body.removeChild(ta);
          done();
        }
      }

      function syncInputOptionsVisibility() {
        if (state.mode === 'agent' || state.mode === 'settings') return;
        var qVal = document.getElementById('q').value.trim();
        var searchOpts = document.getElementById('search-options-row');
        var classicOpts = document.getElementById('classic-options-row');
        var scrapeOpts = document.getElementById('scrape-options-row');
        var runBtn = document.getElementById('run-btn');
        var isUrl = isUrlText(qVal);

        if (isUrl) {
          searchOpts.style.display = 'none';
          classicOpts.style.display = 'none';
          scrapeOpts.style.display = 'flex';
          runBtn.innerHTML = '📄 URL 本文抽出';
        } else if (state.mode === 'classic') {
          searchOpts.style.display = 'none';
          classicOpts.style.display = 'flex';
          scrapeOpts.style.display = 'none';
          runBtn.innerHTML = '🔍 検索';
        } else {
          searchOpts.style.display = 'flex';
          classicOpts.style.display = 'none';
          scrapeOpts.style.display = 'none';
          var depthVal = document.getElementById('opt-depth').value;
          runBtn.innerHTML = depthVal === 'fast' ? '🚀 Fast Search' : '⚡ 統合検索';
        }
      }

      function setMode(mode) {
        state.mode = mode;
        document.querySelectorAll('.nav-tab').forEach(function (t) {
          var isSelected = (t.dataset.mode === mode);
          t.classList.toggle('active', isSelected);
          t.setAttribute('aria-selected', isSelected ? 'true' : 'false');
        });

        var inputPanel = document.getElementById('input-panel');
        var mainSplit = document.getElementById('main-split-view');
        var classicView = document.getElementById('classic-search-view');
        var agentHub = document.getElementById('agent-hub-view');
        var settingsView = document.getElementById('settings-view');

        inputPanel.style.display = (mode === 'agent' || mode === 'settings') ? 'none' : 'block';
        mainSplit.style.display = (mode === 'deep') ? 'grid' : 'none';
        classicView.style.display = (mode === 'classic') ? 'block' : 'none';
        agentHub.style.display = (mode === 'agent') ? 'block' : 'none';
        settingsView.style.display = (mode === 'settings') ? 'block' : 'none';

        if (mode === 'agent') {
          loadAgentHub();
        } else if (mode === 'settings') {
          loadSettingsDashboard();
        } else {
          syncInputOptionsVisibility();
        }
      }

      document.getElementById('q').addEventListener('input', function () {
        syncInputOptionsVisibility();
      });

      document.getElementById('opt-depth').addEventListener('change', function () {
        syncInputOptionsVisibility();
      });

      var navTabs = Array.prototype.slice.call(document.querySelectorAll('.nav-tab'));
      navTabs.forEach(function (btn, idx) {
        btn.addEventListener('click', function () {
          setMode(btn.dataset.mode);
        });
        btn.addEventListener('keydown', function (e) {
          if (e.key === 'ArrowRight' || e.key === 'ArrowLeft') {
            e.preventDefault();
            var nextIdx = (idx + (e.key === 'ArrowRight' ? 1 : navTabs.length - 1)) % navTabs.length;
            navTabs[nextIdx].focus();
            setMode(navTabs[nextIdx].dataset.mode);
          }
        });
      });

      // Classic Category buttons
      document.querySelectorAll('#classic-cat-chips .cat-btn').forEach(function (btn) {
        btn.addEventListener('click', function () {
          document.querySelectorAll('#classic-cat-chips .cat-btn').forEach(function (b) { b.classList.remove('active'); });
          btn.classList.add('active');
          state.classicCategory = btn.dataset.cat || '';
          state.classicPage = 1;
          var qVal = document.getElementById('q').value.trim();
          if (qVal) runClassicSearch(qVal, 1);
        });
      });

      document.querySelectorAll('.chip[data-preset]').forEach(function (chip) {
        chip.addEventListener('click', function () {
          var p = chip.dataset.preset;
          var siteInput = document.getElementById('opt-site');
          if (p === 'docs') siteInput.value = 'docs.python.org, developer.mozilla.org, react.dev, fastapi.tiangolo.com';
          else if (p === 'github') siteInput.value = 'github.com, stackoverflow.com';
          else if (p === 'academic') siteInput.value = 'arxiv.org, wikipedia.org';
          else if (p === 'clear') siteInput.value = '';
        });
      });

      document.querySelectorAll('.sample-q').forEach(function (chip) {
        chip.addEventListener('click', function () {
          document.getElementById('q').value = chip.dataset.q;
          setMode('deep');
          executeCurrentAction();
        });
      });

      document.querySelectorAll('.sample-classic-q').forEach(function (chip) {
        chip.addEventListener('click', function () {
          document.getElementById('q').value = chip.dataset.q;
          setMode('classic');
          executeCurrentAction();
        });
      });

      function updateContextView() {
        var ta = document.getElementById('ctx-output');
        if (state.ctxTab === 'markdown') ta.value = state.markdown || '';
        else if (state.ctxTab === 'prompt') ta.value = state.prompt || '';
        else if (state.ctxTab === 'json') ta.value = state.jsonStr || '';
        else if (state.ctxTab === 'curl') ta.value = state.curlStr || '';

        var tok = estimateTokens(state.markdown || '');
        var budget = state.maxTokens || 3000;
        var pct = Math.min(100, Math.round((tok / Math.max(budget, 1)) * 100));
        document.getElementById('token-usage-label').textContent = '~' + tok + ' / ' + budget + ' tokens (' + pct + '%)';
        document.getElementById('token-bar-fill').style.width = pct + '%';
      }

      var ctxTabs = Array.prototype.slice.call(document.querySelectorAll('.ctx-tab'));
      function selectCtxTab(ctxName) {
        state.ctxTab = ctxName;
        ctxTabs.forEach(function (t) {
          var isSelected = (t.dataset.ctx === state.ctxTab);
          t.classList.toggle('active', isSelected);
          t.setAttribute('aria-selected', isSelected ? 'true' : 'false');
        });
        updateContextView();
      }
      ctxTabs.forEach(function (tab, idx) {
        tab.addEventListener('click', function () {
          selectCtxTab(tab.dataset.ctx);
        });
        tab.addEventListener('keydown', function (e) {
          if (e.key === 'ArrowRight' || e.key === 'ArrowLeft') {
            e.preventDefault();
            var nextIdx = (idx + (e.key === 'ArrowRight' ? 1 : ctxTabs.length - 1)) % ctxTabs.length;
            ctxTabs[nextIdx].focus();
            selectCtxTab(ctxTabs[nextIdx].dataset.ctx);
          }
        });
      });

      document.getElementById('ctx-copy-btn').addEventListener('click', function () {
        var ta = document.getElementById('ctx-output');
        copyWithFeedback(ta.value, this, '✅ コピー完了');
      });
      document.getElementById('copy-md-main').addEventListener('click', function () {
        copyWithFeedback(state.markdown, this, '✅ Markdownコピー済');
      });
      document.getElementById('copy-prompt-main').addEventListener('click', function () {
        copyWithFeedback(state.prompt, this, '✅ プロンプトコピー済');
      });
      document.getElementById('copy-json-main').addEventListener('click', function () {
        copyWithFeedback(state.jsonStr, this, '✅ JSONコピー済');
      });
      document.getElementById('download-md-btn').addEventListener('click', function () {
        if (!state.markdown) return;
        var blob = new Blob([state.markdown], { type: 'text/markdown;charset=utf-8' });
        var objUrl = URL.createObjectURL(blob);
        var a = document.createElement('a');
        a.href = objUrl;
        a.download = 'searxng-context.md';
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        setTimeout(function () { URL.revokeObjectURL(objUrl); }, 1000);
      });

      function renderHighlights(container, highlights, fallbackContent) {
        var list = (highlights && highlights.length) ? highlights : (fallbackContent ? [fallbackContent] : []);
        list.forEach(function (h) {
          if (!h) return;
          if (h.indexOf('```') === 0) {
            var pre = document.createElement('pre');
            pre.className = 'highlight-code';
            pre.textContent = h.replace(/^```[a-zA-Z0-9_-]*\n?/, '').replace(/```$/, '');
            container.appendChild(pre);
          } else {
            var div = document.createElement('div');
            div.className = 'highlight-block';
            div.textContent = h;
            container.appendChild(div);
          }
        });
      }

      function renderSearchResults(items, query) {
        var container = document.getElementById('results-container');
        container.innerHTML = '';

        if (!items || !items.length) {
          var empty = document.createElement('div');
          empty.className = 'empty-state';
          empty.innerHTML = '<h2>検索結果が見つかりませんでした</h2><p>別のキーワードまたはフィルタ条件でお試しください。</p>';
          container.appendChild(empty);
          return;
        }

        items.forEach(function (item, idx) {
          var card = document.createElement('article');
          card.className = 'result-card';

          var top = document.createElement('div');
          top.className = 'card-top';

          var leftMeta = document.createElement('div');
          leftMeta.style.display = 'flex';
          leftMeta.style.alignItems = 'center';
          leftMeta.style.gap = '0.45rem';

          var rankSpan = document.createElement('span');
          rankSpan.className = 'card-rank';
          rankSpan.textContent = '[' + (idx + 1) + ']';

          var domSpan = document.createElement('span');
          domSpan.className = 'card-domain';
          var domain = item.domain || (function () {
            try { return new URL(item.url).hostname.replace(/^www\\./, ''); } catch (e) { return ''; }
          })();
          domSpan.textContent = domain;

          leftMeta.appendChild(rankSpan);
          leftMeta.appendChild(domSpan);

          var badges = document.createElement('div');
          badges.className = 'card-badges';

          if (typeof item.score === 'number' && item.score > 0) {
            var scorePill = document.createElement('span');
            scorePill.className = 'pill ' + (item.score >= 1.5 ? 'pill-emerald' : 'pill-accent');
            scorePill.textContent = 'Score: ' + item.score.toFixed(2);
            badges.appendChild(scorePill);
          }
          if (item.is_scraped) {
            var scPill = document.createElement('span');
            scPill.className = 'pill pill-emerald';
            scPill.textContent = '✅ 本文抽出・BM25済';
            badges.appendChild(scPill);
          } else if (item.source || item.engine) {
            var srcPill = document.createElement('span');
            srcPill.className = 'pill';
            srcPill.textContent = item.source || item.engine;
            badges.appendChild(srcPill);
          }

          top.appendChild(leftMeta);
          top.appendChild(badges);
          card.appendChild(top);

          var titleEl = document.createElement('div');
          titleEl.className = 'card-title';
          var link = document.createElement('a');
          link.href = safeHttpUrl(item.url);
          link.target = '_blank';
          link.rel = 'noopener noreferrer';
          link.textContent = item.title || item.url;
          titleEl.appendChild(link);
          card.appendChild(titleEl);

          var hlWrap = document.createElement('div');
          renderHighlights(hlWrap, item.highlights, item.content);
          card.appendChild(hlWrap);

          var actions = document.createElement('div');
          actions.className = 'card-actions';

          var scrapeBtn = document.createElement('button');
          scrapeBtn.type = 'button';
          scrapeBtn.className = 'btn btn-sm';
          scrapeBtn.innerHTML = '📄 全文を抽出 (/scrape)';
          scrapeBtn.setAttribute('aria-expanded', 'false');
          scrapeBtn.addEventListener('click', function () {
            var existing = card.querySelector('.inline-scrape-drawer');
            if (existing) {
              var isHidden = existing.style.display === 'none';
              existing.style.display = isHidden ? 'block' : 'none';
              scrapeBtn.setAttribute('aria-expanded', isHidden ? 'true' : 'false');
              return;
            }
            var drawer = document.createElement('div');
            drawer.className = 'inline-scrape-drawer';
            drawer.textContent = '⏳ URLから本文を抽出中...';
            card.appendChild(drawer);
            scrapeBtn.setAttribute('aria-expanded', 'true');
            fetch('/api/scrape_analyze?url=' + encodeURIComponent(item.url) + '&q=' + encodeURIComponent(query || ''))
              .then(function (r) { return r.json(); })
              .then(function (res) {
                if (res.error) {
                  drawer.textContent = '⚠️ ' + res.error;
                  return;
                }
                drawer.textContent = res.content || '(本文なし)';
              })
              .catch(function (e) {
                drawer.textContent = '⚠️ 通信エラー: ' + e;
              });
          });

          var copyItemBtn = document.createElement('button');
          copyItemBtn.type = 'button';
          copyItemBtn.className = 'btn btn-sm';
          copyItemBtn.innerHTML = '📋 この結果を引用コピー';
          copyItemBtn.addEventListener('click', function () {
            var hText = (item.highlights && item.highlights.length) ? item.highlights.join('\n\n') : (item.content || '');
            var citeMd = '### [' + (idx + 1) + '] [' + (item.title || item.url) + '](' + item.url + ')\n> ' + hText.replace(/\n/g, '\n> ');
            copyWithFeedback(citeMd, copyItemBtn, '✅ コピー完了');
          });

          actions.appendChild(scrapeBtn);
          actions.appendChild(copyItemBtn);

          if (domain) {
            var filterDomBtn = document.createElement('button');
            filterDomBtn.type = 'button';
            filterDomBtn.className = 'btn btn-sm';
            filterDomBtn.textContent = '🎯 site:' + domain;
            filterDomBtn.addEventListener('click', function () {
              document.getElementById('opt-site').value = domain;
              if (state.mode !== 'deep') setMode('deep');
              executeCurrentAction();
            });
            actions.appendChild(filterDomBtn);
          }

          card.appendChild(actions);
          container.appendChild(card);
        });
      }

      function runUnifiedSearch(query) {
        var depth = document.getElementById('opt-depth').value;
        var count = document.getElementById('opt-count').value;
        var maxTok = parseInt(document.getElementById('opt-tokens').value, 10) || 3000;
        var siteVal = document.getElementById('opt-site').value.trim();
        state.maxTokens = maxTok;

        var container = document.getElementById('results-container');
        container.setAttribute('aria-busy', 'true');
        var isFast = (depth === 'fast');
        container.innerHTML = isFast
          ? '<div class="empty-state"><h2>🚀 Fast Search (json_lite) 実行中...</h2><p>高速メタ検索とトークン予算パッキングを実行しています。</p></div>'
          : '<div class="empty-state"><h2>⚡ Unified Search 実行中...</h2><p>メタ検索 → ドメイン権威スコアリング → 並列本文抽出 (trafilatura) → BM25 パッセージ抽出を実行しています。</p></div>';

        var params = new URLSearchParams({
          q: query,
          depth: depth,
          max_results: count,
          max_tokens: String(maxTok)
        });
        if (siteVal) params.set('site', siteVal);

        var url = '/deep_search?' + params.toString();
        var origin = window.location.origin;
        state.curlStr = 'curl -sG "' + origin + '/deep_search" --data-urlencode "q=' + escapeShellDoubleQuoted(query) + '" --data-urlencode "depth=' + escapeShellDoubleQuoted(depth) + '" --data-urlencode "format=markdown"';

        fetch(url)
          .then(function (r) { return r.json(); })
          .then(function (res) {
            container.setAttribute('aria-busy', 'false');
            if (res.error && (!res.results || !res.results.length)) {
              container.innerHTML = '<div class="empty-state"><h2 style="color:var(--danger);">⚠️ エラー</h2><p>' + escapeHtml(res.error) + '</p></div>';
              return;
            }
            state.markdown = res.markdown || '';
            state.prompt = res.rag_prompt || '';
            state.jsonStr = JSON.stringify(res, null, 2);

            var telBar = document.getElementById('telemetry-bar');
            var badges = document.getElementById('telemetry-badges');
            telBar.classList.add('visible');
            badges.innerHTML =
              '<span class="pill pill-accent">Mode: ' + escapeHtml(res.search_depth || depth) + ' (' + escapeHtml(res.intent || 'general') + ')</span>' +
              '<span class="pill pill-emerald">取得: ' + escapeHtml(res.results_count || 0) + '件 (本文抽出: ' + escapeHtml(res.scraped_count || 0) + '件)</span>' +
              '<span class="pill">~' + escapeHtml(res.estimated_tokens || 0) + ' tokens</span>' +
              '<span class="pill">' + escapeHtml(res.elapsed_ms || 0) + ' ms</span>';

            renderSearchResults(res.results || [], query);
            updateContextView();
          })
          .catch(function (err) {
            container.setAttribute('aria-busy', 'false');
            container.innerHTML = '<div class="empty-state"><h2 style="color:var(--danger);">⚠️ 通信エラー</h2><p>' + escapeHtml(err) + '</p></div>';
          });
      }

      /* -------------------------------------------------------------
       * Classic Search Mode Implementation
       * ------------------------------------------------------------- */
      function renderClassicSearchResults(items, query, page) {
        var container = document.getElementById('classic-results-container');
        container.innerHTML = '';

        if (!items || !items.length) {
          container.innerHTML = '<div class="empty-state"><h2>検索結果が見つかりませんでした</h2><p>キーワードを変更するか、上部のカテゴリーフィルター（全般、IT、ニュース等）を切り替えてみてください。</p></div>';
          document.getElementById('classic-pagination-bar').style.display = 'none';
          return;
        }

        items.forEach(function (item, idx) {
          var card = document.createElement('article');
          card.className = 'classic-card';

          var metaRow = document.createElement('div');
          metaRow.className = 'classic-meta-row';

          var urlSpan = document.createElement('span');
          urlSpan.className = 'classic-url-tag';
          var domain = item.domain || (function () {
            try { return new URL(item.url).hostname.replace(/^www\\./, ''); } catch (e) { return ''; }
          })();
          urlSpan.innerHTML = '🌐 ' + escapeHtml(domain || item.url);

          var badgeGroup = document.createElement('div');
          badgeGroup.style.display = 'flex';
          badgeGroup.style.gap = '0.35rem';

          var engName = item.engine || item.source;
          if (engName) {
            var engPill = document.createElement('span');
            engPill.className = 'pill pill-accent';
            engPill.textContent = engName;
            badgeGroup.appendChild(engPill);
          }

          metaRow.appendChild(urlSpan);
          metaRow.appendChild(badgeGroup);
          card.appendChild(metaRow);

          var titleLink = document.createElement('a');
          titleLink.className = 'classic-title-link';
          titleLink.href = safeHttpUrl(item.url);
          titleLink.target = '_blank';
          titleLink.rel = 'noopener noreferrer';
          titleLink.textContent = item.title || item.url;
          card.appendChild(titleLink);

          var snippetDiv = document.createElement('div');
          snippetDiv.className = 'classic-snippet-text';
          snippetDiv.textContent = item.content || '(スニペットなし)';
          card.appendChild(snippetDiv);

          var actRow = document.createElement('div');
          actRow.className = 'classic-actions-row';

          // 1-Click transfer to AI Deep Search
          var deepBtn = document.createElement('button');
          deepBtn.type = 'button';
          deepBtn.className = 'btn btn-primary btn-sm';
          deepBtn.innerHTML = '⚡ AIで深掘り';
          deepBtn.addEventListener('click', function () {
            document.getElementById('q').value = query;
            setMode('deep');
            runUnifiedSearch(query);
          });

          var scrapeBtn = document.createElement('button');
          scrapeBtn.type = 'button';
          scrapeBtn.className = 'btn btn-sm';
          scrapeBtn.innerHTML = '📄 本文抽出';
          scrapeBtn.addEventListener('click', function () {
            var ex = card.querySelector('.inline-scrape-drawer');
            if (ex) {
              ex.style.display = ex.style.display === 'none' ? 'block' : 'none';
              return;
            }
            var d = document.createElement('div');
            d.className = 'inline-scrape-drawer';
            d.textContent = '⏳ URL本文を抽出中...';
            card.appendChild(d);
            fetch('/api/scrape_analyze?url=' + encodeURIComponent(item.url) + '&q=' + encodeURIComponent(query || ''))
              .then(function (r) { return r.json(); })
              .then(function (res) { d.textContent = res.content || res.error || '(本文なし)'; })
              .catch(function (e) { d.textContent = '⚠️ 抽出エラー: ' + e; });
          });

          var copyBtn = document.createElement('button');
          copyBtn.type = 'button';
          copyBtn.className = 'btn btn-sm';
          copyBtn.innerHTML = '📋 引用コピー';
          copyBtn.addEventListener('click', function () {
            var citeText = '### [' + (item.title || item.url) + '](' + item.url + ')\n> ' + (item.content || '').replace(/\n/g, '\n> ');
            copyWithFeedback(citeText, copyBtn, '✅ コピー済');
          });

          actRow.appendChild(deepBtn);
          actRow.appendChild(scrapeBtn);
          actRow.appendChild(copyBtn);
          card.appendChild(actRow);

          container.appendChild(card);
        });

        // Pagination
        var pagBar = document.getElementById('classic-pagination-bar');
        pagBar.style.display = 'flex';
        document.getElementById('classic-page-indicator').textContent = 'ページ ' + page;
        document.getElementById('classic-prev-btn').disabled = (page <= 1);
      }

      function runClassicSearch(query, page) {
        page = page || 1;
        state.classicPage = page;
        var cat = state.classicCategory || '';
        var tr = document.getElementById('classic-time-range').value || '';
        var count = document.getElementById('classic-count').value || '10';

        var container = document.getElementById('classic-results-container');
        var telPill = document.getElementById('classic-telemetry-pill');
        container.setAttribute('aria-busy', 'true');
        container.innerHTML = '<div class="empty-state"><h2>🔍 検索中 (ページ ' + page + ')...</h2><p>各検索エンジンへ並行リクエストを実行しています。</p></div>';

        var params = new URLSearchParams({
          q: query,
          mode: 'classic',
          categories: cat,
          time_range: tr,
          count: count,
          page: String(page)
        });

        fetch('/deep_search?' + params.toString())
          .then(function (r) { return r.json(); })
          .then(function (res) {
            container.setAttribute('aria-busy', 'false');
            if (res.error && (!res.results || !res.results.length)) {
              container.innerHTML = '<div class="empty-state"><h2 style="color:var(--danger);">⚠️ エラー</h2><p>' + escapeHtml(res.error) + '</p></div>';
              return;
            }
            telPill.style.display = 'block';
            telPill.innerHTML = '取得: ' + escapeHtml(res.results_count || 0) + '件 (' + escapeHtml(res.elapsed_ms || 0) + ' ms)' +
              (cat ? ' · カテゴリー: ' + escapeHtml(cat) : '') +
              (tr ? ' · 期間: ' + escapeHtml(tr) : '');

            // Direct answers box
            var ansContainer = document.getElementById('classic-answers-container');
            ansContainer.innerHTML = '';
            if (res.answers && res.answers.length) {
              res.answers.forEach(function (a) {
                var abox = document.createElement('div');
                abox.className = 'classic-answer-box';
                abox.innerHTML = '<strong>💡 ダイレクトアンサー:</strong><br>' + escapeHtml(a);
                ansContainer.appendChild(abox);
              });
            }

            renderClassicSearchResults(res.results || [], query, page);
          })
          .catch(function (err) {
            container.setAttribute('aria-busy', 'false');
            container.innerHTML = '<div class="empty-state"><h2 style="color:var(--danger);">⚠️ 通信エラー</h2><p>' + escapeHtml(err) + '</p></div>';
          });
      }

      document.getElementById('classic-prev-btn').addEventListener('click', function () {
        if (state.classicPage > 1) {
          var qVal = document.getElementById('q').value.trim();
          if (qVal) runClassicSearch(qVal, state.classicPage - 1);
        }
      });
      document.getElementById('classic-next-btn').addEventListener('click', function () {
        var qVal = document.getElementById('q').value.trim();
        if (qVal) runClassicSearch(qVal, state.classicPage + 1);
      });
      document.getElementById('classic-time-range').addEventListener('change', function () {
        var qVal = document.getElementById('q').value.trim();
        if (qVal && state.mode === 'classic') runClassicSearch(qVal, 1);
      });
      document.getElementById('classic-count').addEventListener('change', function () {
        var qVal = document.getElementById('q').value.trim();
        if (qVal && state.mode === 'classic') runClassicSearch(qVal, 1);
      });

      function runScrapeMode(targetUrl) {
        var maxLen = document.getElementById('opt-scrape-len').value || '8000';
        var focusQ = document.getElementById('opt-scrape-query').value.trim();
        var container = document.getElementById('results-container');
        container.setAttribute('aria-busy', 'true');
        container.innerHTML = '<div class="empty-state"><h2>📄 URL 本文抽出中 (trafilatura)...</h2><p>' + escapeHtml(targetUrl) + '</p></div>';

        var api = '/api/scrape_analyze?url=' + encodeURIComponent(targetUrl) + '&max_length=' + encodeURIComponent(maxLen);
        if (focusQ) api += '&q=' + encodeURIComponent(focusQ);
        state.curlStr = 'curl -sG "' + window.location.origin + '/scrape" --data-urlencode "url=' + escapeShellDoubleQuoted(targetUrl) + '"';

        fetch(api)
          .then(function (r) { return r.json(); })
          .then(function (res) {
            container.setAttribute('aria-busy', 'false');
            if (res.error) {
              container.innerHTML = '<div class="empty-state"><h2 style="color:var(--danger);">⚠️ 抽出エラー</h2><p>' + escapeHtml(res.error) + '</p></div>';
              return;
            }
            state.markdown = res.markdown || res.content || '';
            state.prompt = res.rag_prompt || ('以下のWebページ抽出本文を根拠として要点を解説してください。\n\nURL: ' + targetUrl + '\n\n' + state.markdown);
            state.jsonStr = JSON.stringify(res, null, 2);

            var telBar = document.getElementById('telemetry-bar');
            var badges = document.getElementById('telemetry-badges');
            telBar.classList.add('visible');
            badges.innerHTML =
              '<span class="pill pill-emerald">✅ 本文抽出完了 (' + escapeHtml(res.char_count || 0) + ' 文字)</span>' +
              '<span class="pill pill-accent">~' + escapeHtml(res.estimated_tokens || 0) + ' tokens</span>' +
              '<span class="pill">' + escapeHtml(res.elapsed_ms || 0) + ' ms</span>';

            container.innerHTML = '';
            var card = document.createElement('article');
            card.className = 'result-card';
            var title = document.createElement('div');
            title.className = 'card-title';
            var a = document.createElement('a');
            a.href = safeHttpUrl(res.url);
            a.target = '_blank';
            a.rel = 'noopener noreferrer';
            a.textContent = res.url;
            title.appendChild(a);
            card.appendChild(title);

            if (res.highlights && res.highlights.length) {
              var hlHeader = document.createElement('div');
              hlHeader.style.fontWeight = '700';
              hlHeader.style.fontSize = '0.84rem';
              hlHeader.style.margin = '0.5rem 0 0.3rem';
              hlHeader.textContent = '🎯 BM25 関連ハイライト (' + (res.query || '') + ')';
              card.appendChild(hlHeader);
              renderHighlights(card, res.highlights, '');
            }

            var pre = document.createElement('div');
            pre.className = 'inline-scrape-drawer';
            pre.style.maxHeight = '34rem';
            pre.textContent = res.content || '';
            card.appendChild(pre);
            container.appendChild(card);
            updateContextView();
          })
          .catch(function (err) {
            container.setAttribute('aria-busy', 'false');
            container.innerHTML = '<div class="empty-state"><h2 style="color:var(--danger);">⚠️ 通信エラー</h2><p>' + escapeHtml(err) + '</p></div>';
          });
      }

      /* -------------------------------------------------------------
       * Settings Dashboard Implementation
       * ------------------------------------------------------------- */
      function renderSettingsEngineCards() {
        var grid = document.getElementById('settings-engines-grid');
        grid.innerHTML = '';

        var filter = (state.settingsSearch || '').toLowerCase().trim();
        var cat = state.settingsCurrentCat || '';

        var list = state.settingsEngines.filter(function (e) {
          if (cat && (!e.categories || e.categories.indexOf(cat) === -1)) return false;
          if (filter) {
            var matchName = e.name.toLowerCase().indexOf(filter) !== -1;
            var matchCat = (e.categories || []).some(function (c) { return c.toLowerCase().indexOf(filter) !== -1; });
            var matchBang = (e.shortcut || '').toLowerCase().indexOf(filter) !== -1;
            if (!matchName && !matchCat && !matchBang) return false;
          }
          return true;
        });

        if (!list.length) {
          grid.innerHTML = '<div style="grid-column:1/-1;text-align:center;padding:2rem;color:var(--text-muted);">該当する検索エンジンがありません</div>';
          return;
        }

        list.forEach(function (e) {
          var c = document.createElement('div');
          c.className = 'engine-item-card';

          var top = document.createElement('div');
          top.className = 'engine-item-header';

          var title = document.createElement('div');
          title.className = 'engine-item-title';

          var dot = document.createElement('span');
          dot.style.width = '8px';
          dot.style.height = '8px';
          dot.style.borderRadius = '50%';
          dot.style.display = 'inline-block';
          if (e.status === 'suspended') {
            dot.style.background = 'var(--amber)';
            dot.title = '一時停止 / レート制限中 (' + (e.suspend_remaining_sec || 0) + 's 残り)';
          } else if (e.enabled) {
            dot.style.background = 'var(--emerald)';
            dot.title = '稼働中';
          } else {
            dot.style.background = 'var(--text-muted)';
            dot.title = '無効';
          }

          var nameSpan = document.createElement('span');
          nameSpan.textContent = e.name;

          title.appendChild(dot);
          title.appendChild(nameSpan);

          if (e.shortcut) {
            var bang = document.createElement('span');
            bang.className = 'pill';
            bang.style.fontSize = '0.7rem';
            bang.textContent = '!' + e.shortcut;
            title.appendChild(bang);
          }

          // Toggle switch
          var swLabel = document.createElement('label');
          swLabel.className = 'switch-label';
          var chk = document.createElement('input');
          chk.type = 'checkbox';
          chk.checked = !!e.enabled;
          chk.addEventListener('change', function () {
            e.enabled = chk.checked;
            e.status = e.enabled ? 'online' : 'disabled';
            dot.style.background = e.enabled ? 'var(--emerald)' : 'var(--text-muted)';
            state.togglesModified = true;
            updateOverviewStats();
          });
          var sld = document.createElement('span');
          sld.className = 'switch-slider';
          swLabel.appendChild(chk);
          swLabel.appendChild(sld);

          top.appendChild(title);
          top.appendChild(swLabel);
          c.appendChild(top);

          // Meta info row
          var meta = document.createElement('div');
          meta.className = 'engine-item-meta';

          (e.categories || []).forEach(function (catName) {
            var cp = document.createElement('span');
            cp.className = 'pill';
            cp.textContent = catName;
            meta.appendChild(cp);
          });

          if (typeof e.latency_ms === 'number' && e.latency_ms > 0) {
            var latPill = document.createElement('span');
            latPill.className = 'pill';
            latPill.textContent = e.latency_ms + ' ms';
            meta.appendChild(latPill);
          }
          if (typeof e.reliability === 'number') {
            var relPill = document.createElement('span');
            relPill.className = 'pill ' + (e.reliability >= 90 ? 'pill-emerald' : 'pill-amber');
            relPill.textContent = '信頼性 ' + e.reliability + '%';
            meta.appendChild(relPill);
          }

          c.appendChild(meta);
          grid.appendChild(c);
        });
      }

      function updateOverviewStats() {
        var active = state.settingsEngines.filter(function (e) { return e.enabled; }).length;
        var suspended = state.settingsEngines.filter(function (e) { return e.status === 'suspended'; }).length;
        document.getElementById('stat-active-engines').textContent = active + ' / ' + state.settingsEngines.length;
        document.getElementById('stat-suspended-engines').textContent = suspended;
      }

      function loadSettingsDashboard() {
        var grid = document.getElementById('settings-engines-grid');
        if (state.settingsEngines.length) {
          renderSettingsEngineCards();
          return;
        }

        grid.innerHTML = '<div style="grid-column:1/-1;text-align:center;padding:2rem;">⏳ エンジン稼働状況を取得中...</div>';

        fetch('/api/settings/engines')
          .then(function (r) { return r.json(); })
          .then(function (res) {
            if (!res.success) throw new Error('Failed to load engines');
            state.settingsEngines = res.engines || [];
            state.settingsCategories = res.categories || [];

            document.getElementById('stat-active-engines').textContent = res.active_engines + ' / ' + res.total_engines;
            document.getElementById('stat-suspended-engines').textContent = res.suspended_engines;
            document.getElementById('stat-avg-latency').textContent = res.avg_latency_ms + ' ms';
            document.getElementById('stat-avg-reliability').textContent = res.avg_reliability + '%';

            // Render category chips
            var chipsContainer = document.getElementById('settings-engine-cat-chips');
            chipsContainer.innerHTML = '';
            var allBtn = document.createElement('button');
            allBtn.type = 'button';
            allBtn.className = 'cat-btn active';
            allBtn.textContent = 'すべて (' + res.total_engines + ')';
            allBtn.addEventListener('click', function () {
              chipsContainer.querySelectorAll('.cat-btn').forEach(function (b) { b.classList.remove('active'); });
              allBtn.classList.add('active');
              state.settingsCurrentCat = '';
              renderSettingsEngineCards();
            });
            chipsContainer.appendChild(allBtn);

            (res.categories || []).forEach(function (cat) {
              var count = state.settingsEngines.filter(function (e) { return (e.categories || []).indexOf(cat) !== -1; }).length;
              var b = document.createElement('button');
              b.type = 'button';
              b.className = 'cat-btn';
              b.textContent = cat + ' (' + count + ')';
              b.addEventListener('click', function () {
                chipsContainer.querySelectorAll('.cat-btn').forEach(function (btn) { btn.classList.remove('active'); });
                b.classList.add('active');
                state.settingsCurrentCat = cat;
                renderSettingsEngineCards();
              });
              chipsContainer.appendChild(b);
            });

            renderSettingsEngineCards();
          })
          .catch(function (err) {
            grid.innerHTML = '<div style="grid-column:1/-1;text-align:center;padding:2rem;color:var(--danger);">⚠️ エンジン設定の取得に失敗しました: ' + escapeHtml(err) + '</div>';
          });
      }

      // Settings subtab switching
      document.getElementById('subtab-engines-btn').addEventListener('click', function () {
        this.classList.add('active');
        document.getElementById('subtab-general-btn').classList.remove('active');
        document.getElementById('section-settings-engines').style.display = 'block';
        document.getElementById('section-settings-general').style.display = 'none';
      });
      document.getElementById('subtab-general-btn').addEventListener('click', function () {
        this.classList.add('active');
        document.getElementById('subtab-engines-btn').classList.remove('active');
        document.getElementById('section-settings-engines').style.display = 'none';
        document.getElementById('section-settings-general').style.display = 'block';
      });

      // Filter input
      document.getElementById('engine-search-input').addEventListener('input', function () {
        state.settingsSearch = this.value;
        renderSettingsEngineCards();
      });

      // Bulk actions
      document.getElementById('btn-enable-all-cat').addEventListener('click', function () {
        var cat = state.settingsCurrentCat;
        state.settingsEngines.forEach(function (e) {
          if (!cat || (e.categories && e.categories.indexOf(cat) !== -1)) {
            e.enabled = true;
            e.status = 'online';
          }
        });
        updateOverviewStats();
        renderSettingsEngineCards();
        showToast('カテゴリー内をすべて有効化しました（保存を押して反映）');
      });

      document.getElementById('btn-disable-all-cat').addEventListener('click', function () {
        var cat = state.settingsCurrentCat;
        state.settingsEngines.forEach(function (e) {
          if (!cat || (e.categories && e.categories.indexOf(cat) !== -1)) {
            e.enabled = false;
            e.status = 'disabled';
          }
        });
        updateOverviewStats();
        renderSettingsEngineCards();
        showToast('カテゴリー内をすべて無効化しました（保存を押して反映）');
      });

      document.getElementById('btn-reset-engines-def').addEventListener('click', function () {
        state.settingsEngines.forEach(function (e) {
          e.enabled = !!e.default_enabled;
          e.status = e.enabled ? 'online' : 'disabled';
        });
        updateOverviewStats();
        renderSettingsEngineCards();
        showToast('デフォルトのエンジン構成に復元しました（保存を押して反映）');
      });

      // Save engines settings
      document.getElementById('btn-save-settings-engines').addEventListener('click', function () {
        var disabled = [];
        var enabled = [];
        state.settingsEngines.forEach(function (e) {
          if (e.enabled) enabled.push(e.name);
          else disabled.push(e.name);
        });

        fetch('/api/settings/engines', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ disabled_engines: disabled, enabled_engines: enabled })
        })
          .then(function (r) { return r.json(); })
          .then(function () {
            showToast('✅ 検索エンジンの構成を保存しました');
            state.togglesModified = false;
          })
          .catch(function () {
            showToast('⚠️ 保存に失敗しました');
          });
      });

      // Save general preferences
      document.getElementById('btn-save-general-prefs').addEventListener('click', function () {
        var mode = document.getElementById('pref-default-mode').value;
        var ss = document.getElementById('pref-safesearch').value;
        var count = document.getElementById('pref-default-count').value;
        var tok = document.getElementById('pref-default-tokens').value;

        localStorage.setItem('sxng_pref_mode', mode);
        localStorage.setItem('sxng_pref_safesearch', ss);
        localStorage.setItem('sxng_pref_count', count);
        localStorage.setItem('sxng_pref_tokens', tok);

        fetch('/api/settings/engines', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ safesearch: ss, default_mode: mode })
        }).finally(function () {
          showToast('✅ 一般設定を保存しました');
        });
      });

      document.getElementById('btn-reset-general-prefs').addEventListener('click', function () {
        document.getElementById('pref-default-mode').value = 'deep';
        document.getElementById('pref-safesearch').value = '1';
        document.getElementById('pref-default-count').value = '10';
        document.getElementById('pref-default-tokens').value = '3000';
        showToast('初期設定を復元しました');
      });

      function loadAgentHub() {
        var container = document.getElementById('hub-cards-container');
        if (container.dataset.loaded === '1') return;
        container.innerHTML = '<div class="empty-state"><h2>🤖 サーバー連携情報を取得中...</h2></div>';

        fetch('/api/ai_info')
          .then(function (r) { return r.json(); })
          .then(function (info) {
            container.dataset.loaded = '1';
            container.innerHTML = '';
            var items = [
              {
                title: '⚡ GenAI Retrieval API (/api/retrieval)',
                desc: 'GenAIモデル・自律エージェント向けの構造化グラウンディングAPI (schema_version: 1.0)。根拠パッセージ・検証メタデータ・BM25スコアを返します。',
                code: info.snippets.curl_retrieval + '\n\n# PowerShell:\n' + info.snippets.pwsh_retrieval
              },
              {
                title: '⚡ HTTP Deep Search API (/deep_search)',
                desc: '1回のHTTPリクエストで検索・並列スクレイピング・BM25ハイライト抽出を実行し、MarkdownまたはJSONを返します。',
                code: info.snippets.curl_deep_md + '\n\n# PowerShell:\n' + info.snippets.pwsh_deep
              },
              {
                title: '🤖 Claude Code (MCP 登録コマンド)',
                desc: 'ターミナルで1行実行するだけで、Claude Code に searxng_deep_search / searxng_search / searxng_scrape を追加します。',
                code: info.snippets.claude_code
              },
              {
                title: '💻 Cursor / Windsurf / Claude Desktop (mcp.json)',
                desc: '.cursor/mcp.json 等に貼り付けるだけでローカルMCPサーバーとして連携できます。',
                code: info.snippets.cursor_mcp
              },
              {
                title: '🚀 OpenCode (opencode.json)',
                desc: 'プロジェクトルートの opencode.json に設定してネイティブ検索ツールとして利用できます。',
                code: info.snippets.opencode_json
              },
              {
                title: '🖥️ ターミナル CLI (searxng_cli.py)',
                desc: 'MCP非対応のエージェント（Codex CLI, Aider等）やスクリプトから直接ワンパス深層検索を実行できます。',
                code: info.snippets.cli_deep
              }
            ];
            items.forEach(function (it) {
              var card = document.createElement('div');
              card.className = 'hub-card';
              var h3 = document.createElement('h3');
              var span = document.createElement('span');
              span.textContent = it.title;
              var copyBtn = document.createElement('button');
              copyBtn.type = 'button';
              copyBtn.className = 'btn btn-sm';
              copyBtn.innerHTML = '📋 コピー';
              copyBtn.addEventListener('click', function () {
                copyWithFeedback(it.code, copyBtn, '✅ コピー済');
              });
              h3.appendChild(span);
              h3.appendChild(copyBtn);

              var p = document.createElement('p');
              p.textContent = it.desc;

              var pre = document.createElement('pre');
              pre.className = 'hub-pre';
              pre.textContent = it.code;

              card.appendChild(h3);
              card.appendChild(p);
              card.appendChild(pre);
              container.appendChild(card);
            });
          })
          .catch(function (err) {
            container.innerHTML = '<div class="empty-state"><p>エラー: ' + escapeHtml(err) + '</p></div>';
          });
      }

      function executeCurrentAction() {
        var qVal = document.getElementById('q').value.trim();
        if (!qVal) return;

        // Auto-detect URL in search bar if user pastes http(s)://...
        if (isUrlText(qVal)) {
          syncInputOptionsVisibility();
          runScrapeMode(qVal);
        } else if (state.mode === 'classic') {
          syncInputOptionsVisibility();
          runClassicSearch(qVal, 1);
        } else {
          syncInputOptionsVisibility();
          runUnifiedSearch(qVal);
        }
      }

      document.getElementById('ws-form').addEventListener('submit', function (e) {
        e.preventDefault();
        executeCurrentAction();
      });

      // Global keyboard shortcuts
      document.addEventListener('keydown', function (e) {
        var active = document.activeElement;
        var qInput = document.getElementById('q');
        var isEditing = active && (['INPUT', 'TEXTAREA', 'SELECT'].includes(active.tagName) || active.isContentEditable);
        if ((e.key === '/' && active !== qInput && !isEditing) ||
            ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k')) {
          e.preventDefault();
          qInput.focus();
          qInput.select();
        }
      });

      // Restore user preferences from localStorage
      var savedMode = localStorage.getItem('sxng_pref_mode');
      if (savedMode && ['deep', 'classic', 'balanced'].indexOf(savedMode) !== -1) {
        document.getElementById('pref-default-mode').value = savedMode;
        if (!window.location.search) {
          setMode(savedMode === 'balanced' ? 'deep' : savedMode);
        }
      }
      var savedCount = localStorage.getItem('sxng_pref_count');
      if (savedCount) {
        document.getElementById('pref-default-count').value = savedCount;
        document.getElementById('classic-count').value = savedCount;
      }
      var savedTok = localStorage.getItem('sxng_pref_tokens');
      if (savedTok) {
        document.getElementById('pref-default-tokens').value = savedTok;
        document.getElementById('opt-tokens').value = savedTok;
      }

      // Parse initial URL parameters (?q=...&mode=...&depth=...&category=...&page=...)
      var urlParams = new URLSearchParams(window.location.search);
      var initMode = urlParams.get('mode');
      var initDepth = urlParams.get('depth');
      var initCat = urlParams.get('category') || urlParams.get('categories');
      var initPage = parseInt(urlParams.get('page') || urlParams.get('pageno'), 10) || 1;
      var initQ = urlParams.get('q') || urlParams.get('url');

      if (initDepth && ['advanced', 'code', 'basic', 'fast'].indexOf(initDepth) !== -1) {
        document.getElementById('opt-depth').value = initDepth;
      }
      if (initCat) {
        state.classicCategory = initCat;
        document.querySelectorAll('#classic-cat-chips .cat-btn').forEach(function (b) {
          b.classList.toggle('active', b.dataset.cat === initCat);
        });
      }
      if (initMode && ['deep', 'classic', 'agent', 'settings'].indexOf(initMode) !== -1) {
        setMode(initMode);
      }
      if (initQ) {
        document.getElementById('q').value = initQ;
        syncInputOptionsVisibility();
        executeCurrentAction();
      }
    })();
  </script>
</body>
</html>

"""


def register_next_webui(app: Any, webapp_mod: Any = None) -> None:
    """Register SearXNG Next AI-First WebUI and API routes onto the Flask app idempotently."""
    # Guard against duplicate registration
    if getattr(app, "_sxng_next_registered", False):
        return
    app._sxng_next_registered = True

    from flask import Response, jsonify, redirect, request

    # --- Tier A: app.before_request hook (Earliest Interception) ---
    @app.before_request
    def sxng_ui_unification_guard() -> Any:
        path = getattr(request, "path", "")
        if request.method == "GET":
            # 1. Root / -> immediately serve AI-First Studio
            if path == "/":
                return Response(AI_WORKSPACE_HTML, mimetype="text/html")
            # 2. Browser /search -> 302 redirect to /?q=... unless data format requested
            if path == "/search":
                out_fmt = (request.args.get("format") or "").strip().lower()
                accept = request.headers.get("Accept") or ""
                if not out_fmt and "application/json" not in accept and "text/json" not in accept:
                    params = dict(request.args)
                    qs = urllib.parse.urlencode(params)
                    return redirect(f"/?{qs}" if qs else "/", code=302)
            # 3. Browser /preferences -> redirect to Settings tab
            if path == "/preferences":
                out_fmt = (request.args.get("format") or "").strip().lower()
                accept = request.headers.get("Accept") or ""
                if not out_fmt and "application/json" not in accept:
                    return redirect("/?mode=settings", code=302)
            # 4. Browser /about -> redirect to Agent Hub
            if path == "/about":
                return redirect("/?mode=agent", code=302)
        return None

    # --- Tier B: app.view_functions replacement ---
    orig_search = app.view_functions.get("search")
    orig_preferences = app.view_functions.get("preferences")
    orig_about = app.view_functions.get("about")

    def unified_index_view() -> Any:
        return Response(AI_WORKSPACE_HTML, mimetype="text/html")

    def unified_search_view() -> Any:
        out_fmt = (request.values.get("format") or "").strip().lower()
        accept = request.headers.get("Accept") or ""
        if (
            out_fmt in ("json", "json_lite", "csv", "rss") or "application/json" in accept or "text/json" in accept
        ) and orig_search:
            return orig_search()
        params = dict(request.args)
        qs = urllib.parse.urlencode(params)
        return redirect(f"/?{qs}" if qs else "/", code=302)

    def unified_preferences_view() -> Any:
        if request.method == "POST" and orig_preferences:
            return orig_preferences()
        return redirect("/?mode=settings", code=302)

    app.view_functions["index"] = unified_index_view
    if orig_search is not None:
        app.view_functions["search"] = unified_search_view
    if orig_preferences is not None:
        app.view_functions["preferences"] = unified_preferences_view
    if orig_about is not None:
        app.view_functions["about"] = lambda: redirect("/?mode=agent", code=302)

    @app.route("/ai", methods=["GET"])
    @app.route("/next", methods=["GET"])
    def ai_workspace() -> Any:
        """Render the lightweight AI Search & Context Studio."""
        return Response(AI_WORKSPACE_HTML, mimetype="text/html")

    @app.route("/ai/embed.css", methods=["GET"])
    def ai_embed_css() -> Any:
        """Serve lightweight CSS for SearXNG's native simple theme."""
        return Response(
            SIMPLE_EMBED_CSS,
            mimetype="text/css",
            headers={"Cache-Control": "public, max-age=300"},
        )

    @app.route("/ai/embed.js", methods=["GET"])
    def ai_embed_js() -> Any:
        """Serve progressive AI enhancement JS for SearXNG's native simple theme."""
        return Response(
            SIMPLE_EMBED_JS,
            mimetype="application/javascript",
            headers={"Cache-Control": "public, max-age=300"},
        )

    @app.route("/api/ai_info", methods=["GET"])
    def ai_info_route() -> Any:
        """Return instance AI capabilities and ready-to-copy MCP/CLI configs."""
        host_url = request.host_url.rstrip("/") if getattr(request, "host_url", None) else "http://127.0.0.1:8888"
        return jsonify(get_ai_info(webapp_mod=webapp_mod, host_url=host_url))

    @app.route("/api/settings/engines", methods=["GET", "POST"])
    def settings_engines_route() -> Any:
        """Endpoint to query and persist engine health, latency, reliability, and enablement."""
        if request.method == "POST":
            payload = request.get_json(silent=True) if request.is_json else None
            payload = payload if isinstance(payload, dict) else {}
            data = save_engines_settings_data(webapp_mod, payload)
            resp = jsonify(data)
            save_engines_settings_data(webapp_mod, payload, response=resp)
            return resp

        cookies = dict(request.cookies) if getattr(request, "cookies", None) else {}
        data = get_engines_settings_data(webapp_mod=webapp_mod, request_cookies=cookies)
        return jsonify(data)

    @app.route("/api/scrape_analyze", methods=["GET", "POST"])
    def scrape_analyze_route() -> Any:
        """Extract clean article text, token estimate, and optional BM25 highlights from a URL."""
        payload = request.get_json(silent=True) if request.is_json else None
        payload = payload if isinstance(payload, dict) else {}

        url = request.values.get("url") or payload.get("url") or ""
        query = request.values.get("q") or request.values.get("query") or payload.get("q") or payload.get("query") or ""
        max_len = _parse_int(request.values.get("max_length") or payload.get("max_length"), 8000, 500, 50000)

        if not isinstance(url, str) or not url.strip():
            return jsonify({"error": "No URL provided", "url": "", "content": ""}), 400

        res = execute_scrape_analyze(
            url=url,
            query=str(query) if query else "",
            max_length=max_len,
            webapp_mod=webapp_mod,
        )
        err = str(res.get("error") or "")
        err_lower = err.lower()
        is_blocked = (
            "拒否" in err
            or "400" in err
            or "blocked" in err_lower
            or "private" in err_lower
            or "invalid port" in err_lower
            or "loopback" in err_lower
            or "ssrf" in err_lower
        )
        status_code = 400 if is_blocked else (422 if err else 200)
        return jsonify(res), status_code

    @app.route("/deep_search", methods=["GET", "POST"])
    @app.route("/api/search", methods=["GET", "POST"])
    def deep_search_route() -> Any:
        """Unified Search & Scrape HTTP endpoint (supports mode=auto|deep|fast|classic|scrape)."""
        payload = request.get_json(silent=True) if request.is_json else None
        payload = payload if isinstance(payload, dict) else {}

        query = (
            request.values.get("q")
            or request.values.get("query")
            or request.values.get("url")
            or payload.get("q")
            or payload.get("query")
            or payload.get("url")
            or ""
        )
        out_fmt = (
            request.values.get("format")
            or payload.get("format")
            or ("markdown" if "text/markdown" in (request.headers.get("Accept") or "") else "json")
        )
        out_fmt = str(out_fmt).strip().lower()

        if not isinstance(query, str) or not query.strip():
            if out_fmt in ("markdown", "md"):
                return Response("### Error\n\nNo query provided.", status=400, mimetype="text/markdown")
            return jsonify({"error": "No query", "query": "", "results": []}), 400

        mode = request.values.get("mode") or payload.get("mode") or "auto"
        depth = (
            request.values.get("depth")
            or request.values.get("search_depth")
            or payload.get("search_depth")
            or payload.get("depth")
            or "advanced"
        )
        raw_max_results = (
            request.values.get("max_results")
            or request.values.get("count")
            or request.values.get("n")
            or payload.get("max_results")
            or payload.get("count")
        )
        max_results = _parse_int(raw_max_results, 5, 1, 50)
        max_tokens = _parse_int(request.values.get("max_tokens") or payload.get("max_tokens"), 3000, 500, 20000)
        raw_page = (
            request.values.get("page") or request.values.get("pageno") or payload.get("page") or payload.get("pageno")
        )
        pageno = _parse_int(raw_page, 1, 1, 100)
        focus_query = (
            request.values.get("focus_query")
            or request.values.get("focus_q")
            or payload.get("focus_query")
            or payload.get("focus_q")
            or ""
        )
        raw_scrape_len = (
            request.values.get("max_scrape_length")
            or request.values.get("max_length")
            or payload.get("max_scrape_length")
            or payload.get("max_length")
        )
        max_scrape_length = _parse_int(raw_scrape_len, 8000, 500, 50000)
        categories = request.values.get("categories") or payload.get("categories") or ""
        engines = request.values.get("engines") or payload.get("engines") or ""
        time_range = request.values.get("time_range") or payload.get("time_range") or ""
        inc_hl = _parse_bool(
            request.values.get("include_highlights", payload.get("include_highlights")),
            default=True,
        )

        inc_domains = _parse_domain_list(
            request.args.getlist("site")
            or request.values.get("include_domains")
            or payload.get("include_domains")
            or payload.get("site")
        )
        exc_domains = _parse_domain_list(
            request.args.getlist("exclude_site")
            or request.values.get("exclude_domains")
            or payload.get("exclude_domains")
            or payload.get("exclude_site")
        )

        if out_fmt in ("json_ai", "evidence_json", "ai") or mode in ("balanced", "retrieval"):
            ret_mode = "balanced" if mode in ("balanced", "retrieval", "auto") else str(mode)
            res = execute_server_retrieval_search(
                query=query.strip(),
                webapp_mod=webapp_mod,
                mode=ret_mode,
                count=max_results,
                categories=str(categories),
                engines=str(engines),
                time_range=str(time_range),
                include_domains=inc_domains or None,
                exclude_domains=exc_domains or None,
            )
            if out_fmt in ("markdown", "md"):
                return Response(res.get("markdown", ""), status=200, mimetype="text/markdown")
            return jsonify(res), 200

        res = execute_server_deep_search(
            query=query.strip(),
            webapp_mod=webapp_mod,
            search_depth=str(depth),
            max_results=max_results,
            include_highlights=inc_hl,
            include_domains=inc_domains or None,
            exclude_domains=exc_domains or None,
            categories=str(categories),
            engines=str(engines),
            time_range=str(time_range),
            max_tokens=max_tokens,
            mode=str(mode),
            focus_query=str(focus_query),
            max_scrape_length=max_scrape_length,
            pageno=pageno,
        )

        if out_fmt in ("markdown", "md"):
            return Response(res.get("markdown", ""), status=200, mimetype="text/markdown")

        return jsonify(res), 200

    @app.route("/api/retrieval", methods=["GET", "POST"])
    def retrieval_api_route() -> Any:
        """Dedicated GenAI Retrieval API endpoint returning schema_version 1.0 JSON."""
        payload = request.get_json(silent=True) if request.is_json else None
        payload = payload if isinstance(payload, dict) else {}

        query = request.values.get("q") or request.values.get("query") or payload.get("q") or payload.get("query") or ""
        if not isinstance(query, str) or not query.strip():
            return jsonify({"error": "No query", "schema_version": "1.0", "results": []}), 400

        mode = request.values.get("mode") or payload.get("mode") or "balanced"
        raw_count = request.values.get("count") or request.values.get("n") or payload.get("count")
        count = _parse_int(raw_count, 5, 1, 50)
        categories = request.values.get("categories") or payload.get("categories") or ""
        engines = request.values.get("engines") or payload.get("engines") or ""
        time_range = request.values.get("time_range") or payload.get("time_range") or ""
        inc_domains = _parse_domain_list(
            request.args.getlist("site")
            or request.values.get("include_domains")
            or payload.get("include_domains")
            or payload.get("site")
        )
        exc_domains = _parse_domain_list(
            request.args.getlist("exclude_site")
            or request.values.get("exclude_domains")
            or payload.get("exclude_domains")
            or payload.get("exclude_site")
        )
        out_fmt = str(request.values.get("format") or payload.get("format") or "json").strip().lower()

        res = execute_server_retrieval_search(
            query=query.strip(),
            webapp_mod=webapp_mod,
            mode=str(mode),
            count=count,
            categories=str(categories),
            engines=str(engines),
            time_range=str(time_range),
            include_domains=inc_domains or None,
            exclude_domains=exc_domains or None,
        )

        if out_fmt in ("markdown", "md"):
            return Response(res.get("markdown", ""), status=200, mimetype="text/markdown")

        return jsonify(res), 200
