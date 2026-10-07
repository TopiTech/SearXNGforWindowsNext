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
import ipaddress
import json
import os
import re
import socket
import sys
import tempfile
import threading
import time
import urllib.parse
from html.parser import HTMLParser
from typing import Any

TOOLS_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.abspath(os.path.join(TOOLS_DIR, ".."))
if TOOLS_DIR not in sys.path:
    sys.path.insert(0, TOOLS_DIR)

import agentic_search
import retrieval_service
import searxng_client


class _HTMLTextExtractor(HTMLParser):
    """Linear-time HTML-to-text extractor used by the scrape fallback path.

    Replaces the former regex-based tag stripping (case-insensitive
    ``<script>``/``<style>``-style substitutions and a catch-all tag regex)
    with a ``html.parser.HTMLParser`` driven walker so that adversarial HTML
    cannot trigger catastrophic backtracking or super-linear regex work
    (ReDoS / CPU-exhaustion DoS) while holding the scraper thread lock.
    """

    _IGNORE_DEPTH_TAGS = frozenset({"script", "style", "noscript", "iframe", "template", "svg", "head"})

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._parts: list[str] = []
        self._ignore_depth = 0
        self._ignore_tag: str = ""

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag_l = tag.lower()
        if self._ignore_depth:
            if tag_l == self._ignore_tag and tag_l not in ("br", "img", "hr", "meta", "link", "input"):
                self._ignore_depth += 1
            return
        if tag_l in self._IGNORE_DEPTH_TAGS:
            self._ignore_depth = 1
            self._ignore_tag = tag_l
            return
        if tag_l in ("br", "p", "div", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6"):
            self._parts.append(" ")

    def handle_endtag(self, tag: str) -> None:
        tag_l = tag.lower()
        if self._ignore_depth:
            if tag_l == self._ignore_tag:
                self._ignore_depth -= 1
            return
        if tag_l in ("p", "div", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6"):
            self._parts.append(" ")

    def handle_data(self, data: str) -> None:
        if self._ignore_depth:
            return
        self._parts.append(data)

    def get_text(self) -> str:
        return "".join(self._parts)


def _strip_html_to_text(sample_html: str) -> str:
    """Linear-time tag stripping for the scrape fallback text extractor.

    Uses :class:`_HTMLTextExtractor` instead of chained regex substitutions so
    worst-case cost stays O(n) in the (already size-capped) input length. This
    prevents ReDoS/DoS via crafted HTML (unclosed ``<script>`` floods etc.).
    """
    if not sample_html:
        return ""
    extractor = _HTMLTextExtractor()
    try:
        extractor.feed(sample_html)
        extractor.close()
    except Exception:  # noqa: BLE001 - parser must never break scraping
        # Defensive fallback: collapse to plain whitespace-only text so the
        # caller treats it as "no extractable content" instead of crashing.
        return ""
    return re.sub(r"\s+", " ", extractor.get_text()).strip()


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


def _parse_float(val: Any, default: float, minimum: float, maximum: float) -> float:
    """Parse float parameter within [minimum, maximum] bounds."""
    if val is None or val == "":
        return default
    try:
        n = float(val)
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

    def _normalize_scrape_host(host_raw: str | None) -> str:
        """Normalize a host the same way httpx does before transport.

        Converts Unicode dots (U+3002, U+FF0E, U+FF61) to '.', strips
        trailing dots and applies IDNA/punycode encoding so the validator,
        the DNS pin and httpx's transport all agree on the host string
        that will be resolved (prevents pin bypass / DNS rebinding).
        """
        host_norm = (host_raw or "").strip().strip("[]").lower()
        for dot in (chr(0x3002), chr(0xFF0E), chr(0xFF61)):
            host_norm = host_norm.replace(dot, ".")
        host_norm = host_norm.rstrip(".")
        if "%" in host_norm:
            host_norm = host_norm.split("%", 1)[0]
        if host_norm and ":" not in host_norm and not host_norm.replace(".", "").isdigit():
            with contextlib.suppress(Exception):
                import idna  # local import: only needed for IDN hosts

                host_norm = idna.encode(host_norm, uts46=True).decode("ascii")
        return host_norm

    def _parse_url(value: str) -> urllib.parse.ParseResult:
        try:
            parsed_u = urllib.parse.urlparse(value)
            p = parsed_u.port
            if p is not None and (p == 0 or p > 65535):
                raise blocked_exc_cls("Invalid port: 0")
        except blocked_exc_cls:
            raise
        except ValueError as exc:
            raise blocked_exc_cls("Invalid URL") from exc
        if parsed_u.username or parsed_u.password or "@" in (parsed_u.netloc or ""):
            raise blocked_exc_cls("URLs with embedded credentials are not allowed")
        return parsed_u

    def _is_static_host_blocked(host: str | None) -> bool:
        host_clean = _normalize_scrape_host(host)
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
            if ":" in host_clean:
                return True
            if host_clean.replace(".", "").isdigit():
                with contextlib.suppress(OSError, ValueError):
                    packed = socket.inet_aton(host_clean)
                    return bool(webapp_mod._is_ip_blocked(ipaddress.IPv4Address(packed)))
                with contextlib.suppress(ValueError, TypeError, OverflowError):
                    ip_int = int(host_clean)
                    if 0 <= ip_int <= 0xFFFFFFFF:
                        return bool(webapp_mod._is_ip_blocked(ipaddress.IPv4Address(ip_int)))
                return True
            if host_clean.startswith(("0x", "0X", "0o", "0O", "0b", "0B")):
                with contextlib.suppress(ValueError, TypeError, OverflowError):
                    ip_int = int(host_clean, 0)
                    if 0 <= ip_int <= 0xFFFFFFFF:
                        return bool(webapp_mod._is_ip_blocked(ipaddress.IPv4Address(ip_int)))
                with contextlib.suppress(OSError, ValueError):
                    packed = socket.inet_aton(host_clean)
                    return bool(webapp_mod._is_ip_blocked(ipaddress.IPv4Address(packed)))
                return True
            if ":" not in host_clean and "." in host_clean:
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

    def _resolve_safe_ip(url_to_resolve: str) -> tuple[list[str], str, int, str]:
        p_url = _parse_url(url_to_resolve)
        if p_url.scheme not in ("http", "https"):
            raise blocked_exc_cls(f"Blocked invalid scheme: {p_url.scheme}")
        host = p_url.hostname
        if not host:
            raise blocked_exc_cls("Empty hostname")
        host_clean = _normalize_scrape_host(host)
        if not host_clean or _is_static_host_blocked(host_clean):
            raise blocked_exc_cls(f"Blocked: {host} is a private/reserved host or IP")
        port = p_url.port or (443 if p_url.scheme == "https" else 80)
        # Rebuild the URL with the normalized host so the transport (httpx)
        # resolves exactly the host we validated and pinned. Without this,
        # httpx's own host normalization (Unicode dots, trailing dot,
        # IDNA) can diverge from the pin host and silently disable the
        # pin, re-enabling DNS rebinding.
        if ":" in host_clean and not host_clean.startswith("["):
            host_out = f"[{host_clean}]"
        else:
            host_out = host_clean
        hostport = f"{host_out}:{port}" if p_url.port else host_out
        safe_url = p_url._replace(netloc=hostport).geturl()
        try:
            addr_info = socket.getaddrinfo(host_clean, port)
        except (socket.gaierror, OSError) as exc:
            raise blocked_exc_cls(f"DNS resolution failed for {host}: {exc}") from exc
        if not addr_info:
            raise blocked_exc_cls(f"Could not resolve host: {host}")
        valid_ips: list[str] = []
        for res in addr_info:
            ip_raw = res[4][0]
            if webapp_mod._is_ip_blocked(ip_raw):
                raise blocked_exc_cls(f"Blocked: {host} resolves to a private/reserved IP: {ip_raw}")
            ip_str = str(ip_raw)
            if ip_str not in valid_ips:
                valid_ips.append(ip_str)
        if not valid_ips:
            raise blocked_exc_cls(f"Could not find a global IP for {host}")
        v4_ips = [ip for ip in valid_ips if ":" not in ip]
        v6_ips = [ip for ip in valid_ips if ":" in ip]
        ordered_ips = v4_ips + v6_ips
        return ordered_ips, host_clean, port, safe_url

    try:
        httpx_mod = webapp_mod.httpx
        verify_ssl = os.environ.get("SEARXNG_SCRAPE_VERIFY_SSL", "true").lower() in ("true", "1", "yes")
        ua = (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36"
        )
        with webapp_mod._scrape_client_lock:
            if webapp_mod._scrape_client is None or webapp_mod._scrape_client_verify_ssl != verify_ssl:
                scrape_limits = httpx_mod.Limits(max_keepalive_connections=0, max_connections=50)
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
            safe_ips, original_host, port, safe_url = _resolve_safe_ip(current_url)
            headers = {"User-Agent": ua}
            with (
                webapp_mod.pinned_dns(original_host, safe_ips, port),
                webapp_mod._scrape_client.stream("GET", safe_url, headers=headers, timeout=req_timeout) as response,
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
                current_url = urllib.parse.urljoin(safe_url, location.strip())
        else:
            raise RuntimeError("Too many redirects")

        content_text = None
        if downloaded and hasattr(webapp_mod, "trafilatura"):
            try:
                content_text = webapp_mod.trafilatura.extract(downloaded, include_comments=False, include_tables=True)
            except (ValueError, RuntimeError, TypeError, AttributeError):
                content_text = None

        if not content_text and downloaded:
            # Fallback to linear-time HTML text extraction (ReDoS-safe; the
            # former chained case-insensitive tag-stripping regex calls had
            # super-linear worst-case cost on adversarial HTML).
            sample_html = downloaded[:1_000_000]
            raw_text = _strip_html_to_text(sample_html)
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
            "raw_html": downloaded,
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
        count_int = max(1, min(count, 50))
    except (ValueError, TypeError):
        count_int = 5

    try:
        page_int = max(1, min(pageno, 100))
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

                # If specialized engine routing returned 0 results, retry once with user's default enabled engines
                # (Only when engines were explicitly specified without categories, never override a specific user category)
                if not results and engines.strip() and not categories.strip():
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
        pageno=page_int,
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

    max_res = _parse_int(max_results, default=5, minimum=1, maximum=50)
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
    cookie_disabled = (cookies.get("disabled_engines") or "").strip()
    if cookie_disabled:
        disabled_set.update(c.strip() for c in cookie_disabled.split(",") if c.strip())
    cookie_enabled = (cookies.get("enabled_engines") or "").strip()
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
        if histogram_func is not None:
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
        "autocomplete": str(cookies.get("autocomplete") or "").strip() or "duckduckgo",
    }


def sync_engines_to_settings_file(
    enabled_engines: list[str],
    disabled_engines: list[str],
    settings_path: str | None = None,
) -> bool:
    """Safely update disabled: true/false for specified engines in config/settings.yml."""
    if not enabled_engines and not disabled_engines:
        return False

    if not settings_path:
        env_path = os.environ.get("SEARXNG_SETTINGS_PATH", "").strip().strip('"\'')
        if env_path and os.path.isfile(env_path):
            settings_path = env_path
        else:
            default_path = os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config", "settings.yml"
            )
            if os.path.isfile(default_path):
                settings_path = default_path

    if not settings_path or not os.path.isfile(settings_path):
        return False

    try:
        with open(settings_path, "r", encoding="utf-8") as f:
            content = f.read()

        engine_pat = re.compile(
            r"(?m)(^[ \t]*-[ \t]*name:[ \t]*['\"]?([^'\"\r\n]+)['\"]?[ \t]*\r?\n)([\s\S]*?)(?=(?:^[ \t]*-[ \t]*name:)|(?:^[a-zA-Z0-9_]+:)|\Z)"
        )

        found_engines: set[str] = set()

        def replace_engine_block(match: re.Match[str]) -> str:
            header = match.group(1)
            name = match.group(2).strip()
            body = match.group(3)
            found_engines.add(name)

            target_disabled = None
            if name in enabled_engines:
                target_disabled = False
            elif name in disabled_engines:
                target_disabled = True

            if target_disabled is None:
                return match.group(0)

            dis_pat = re.compile(r"(?m)^([ \t]*disabled[ \t]*:[ \t]*)(?:true|false|yes|no)(.*)$", re.IGNORECASE)
            if dis_pat.search(body):
                new_val = "true" if target_disabled else "false"
                new_body = dis_pat.sub(rf"\g<1>{new_val}\g<2>", body)
                return header + new_body
            else:
                indent = "    "
                line_ending = "\r\n" if "\r\n" in header else "\n"
                new_val = "true" if target_disabled else "false"
                return header + f"{indent}disabled: {new_val}{line_ending}" + body

        new_content = engine_pat.sub(replace_engine_block, content)

        # For any enabled engines not already in config/settings.yml, append to engines: section
        missing_to_add = [e for e in enabled_engines if e not in found_engines]
        if missing_to_add:
            top_level_pat = re.compile(r"(?m)(^engines:[ \t]*\r?\n[\s\S]*?)(?=^[a-zA-Z0-9_]+:|\Z)")
            m = top_level_pat.search(new_content)
            if m:
                sec_end = m.end(1)
                line_ending = "\r\n" if "\r\n" in new_content else "\n"
                to_insert = ""
                for e in missing_to_add:
                    to_insert += (
                        f"{line_ending}  - name: {e}{line_ending}    engine: {e}{line_ending}    disabled: false{line_ending}"
                    )
                new_content = new_content[:sec_end] + to_insert + new_content[sec_end:]

        if new_content != content:
            dir_name = os.path.dirname(settings_path)
            temp_path = None
            try:
                with tempfile.NamedTemporaryFile("w", dir=dir_name, delete=False, encoding="utf-8") as temp_file:
                    temp_path = temp_file.name
                    temp_file.write(new_content)
                    temp_file.flush()
                os.replace(temp_path, settings_path)
            except Exception:
                if temp_path:
                    with contextlib.suppress(Exception):
                        os.unlink(temp_path)
                raise
            return True
        return False
    except Exception:  # noqa: BLE001 - safely handle file I/O or parsing failures without crashing
        return False


def save_engines_settings_data(
    webapp_mod: Any,
    payload: dict[str, Any],
    response: Any = None,
) -> dict[str, Any]:
    """Persist user engine toggles and general preferences to settings.yml and session cookies."""
    disabled_engines = payload.get("disabled_engines")
    enabled_engines = payload.get("enabled_engines")
    cookie_max_age = 60 * 60 * 24 * 365 * 5  # 5 years

    dis_str = ""
    en_str = ""
    clean_dis: list[str] = []
    clean_en: list[str] = []

    if isinstance(disabled_engines, list):
        clean_dis = [str(x).strip() for x in disabled_engines if str(x).strip()]
        dis_str = ",".join(clean_dis)

    if isinstance(enabled_engines, list):
        clean_en = [str(x).strip() for x in enabled_engines if str(x).strip()]
        en_str = ",".join(clean_en)

    # 1. Persist engine enablement directly into config/settings.yml
    synced_yml = sync_engines_to_settings_file(clean_en, clean_dis)

    # 2. Live in-memory update for the running process
    se = None
    if webapp_mod is not None:
        searx_pkg = getattr(webapp_mod, "searx", None)
        if searx_pkg:
            se = getattr(searx_pkg, "engines", None)
    if se is None:
        se = sys.modules.get("searx.engines")
    if se and hasattr(se, "engines"):
        for name in clean_en:
            if name in se.engines:
                se.engines[name].disabled = False
        for name in clean_dis:
            if name in se.engines:
                se.engines[name].disabled = True

    # 3. Update active request preferences if available
    if webapp_mod is not None:
        with contextlib.suppress(Exception):
            sxng_req = getattr(webapp_mod, "sxng_request", None)
            prefs = getattr(sxng_req, "preferences", None) if sxng_req else None
            if prefs and hasattr(prefs, "engines") and hasattr(prefs.engines, "parse_cookie"):
                prefs.engines.parse_cookie(dis_str, en_str)

    # 4. Set persistent session cookies
    if response is not None and hasattr(response, "set_cookie"):
        if "disabled_engines" in payload:
            response.set_cookie("disabled_engines", dis_str, max_age=cookie_max_age, path="/")
        if "enabled_engines" in payload:
            response.set_cookie("enabled_engines", en_str, max_age=cookie_max_age, path="/")
        if "safesearch" in payload:
            response.set_cookie("safesearch", str(payload["safesearch"]), max_age=cookie_max_age, path="/")
        if "autocomplete" in payload:
            ac_val = str(payload["autocomplete"]).strip().lower()
            if ac_val in ("off", "none", "0", "false"):
                ac_val = "off"
            response.set_cookie("autocomplete", ac_val, max_age=cookie_max_age, path="/")

    return {
        "success": True,
        "disabled_engines_count": len(disabled_engines) if isinstance(disabled_engines, list) else 0,
        "enabled_engines_count": len(enabled_engines) if isinstance(enabled_engines, list) else 0,
        "synced_settings_yml": synced_yml,
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
    var cjk = (text.match(/[\\u3000-\\u303f\\u3040-\\u30ff\\u3400-\\u4dbf\\u4e00-\\u9fff\\uff00-\\uffef]/g) || []).length;
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


def _load_ai_workspace_html() -> str:
    """Load AI Workspace HTML from tools/webui component files, falling back to embedded string."""
    webui_dir = os.path.join(TOOLS_DIR, "webui")
    css_path = os.path.join(webui_dir, "styles.css")
    body_path = os.path.join(webui_dir, "body.html")
    js_path = os.path.join(webui_dir, "app.js")
    tmpl_path = os.path.join(webui_dir, "template.html")

    if os.path.isfile(css_path) and os.path.isfile(body_path) and os.path.isfile(js_path) and os.path.isfile(tmpl_path):
        with open(css_path, encoding="utf-8") as f:
            css_content = f.read()
        with open(body_path, encoding="utf-8") as f:
            body_content = f.read()
        with open(js_path, encoding="utf-8") as f:
            js_content = f.read()
        with open(tmpl_path, encoding="utf-8") as f:
            tmpl_content = f.read()
        return (
            tmpl_content.replace("{{ CSS }}", css_content)
            .replace("{{ BODY }}", body_content)
            .replace("{{ JS }}", js_content)
        )

    return _EMBEDDED_AI_WORKSPACE_HTML


_EMBEDDED_AI_WORKSPACE_HTML = r"""<!DOCTYPE html>
<html lang="ja" data-theme="dark">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <meta name="referrer" content="no-referrer">
  <title>SearXNG Next — AI Search &amp; Context Studio</title>
  <style>
/* ==========================================================================
   SearXNG Next AI-First Studio Stylesheet (Modern Minimal Design System)
   ========================================================================== */

:root, [data-theme="dark"] {
  --bg-base: #0b0f19;
  --bg-surface: #111827;
  --bg-elevated: #1e293b;
  --bg-input: #0f172a;
  --border-color: #26334d;
  --border-hover: #4f46e5;
  --text-main: #f1f5f9;
  --text-secondary: #94a3b8;
  --text-muted: #8494ac;
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
  --text-muted: #475569;
  --accent: #4f46e5;
  --accent-hover: #4338ca;
  --accent-soft: rgba(79, 70, 229, 0.09);
  --emerald: #059669;
  --emerald-soft: rgba(5, 150, 105, 0.10);
  --amber: #b45309;
  --amber-soft: rgba(180, 83, 9, 0.10);
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

/* Skip Link */
.skip-link {
  position: absolute;
  top: -999px;
  left: 1rem;
  z-index: 1000;
  padding: 0.5rem 1rem;
  background: var(--accent);
  color: #fff;
  border-radius: 0.4rem;
  font-weight: 700;
  text-decoration: none;
}
.skip-link:focus {
  top: 1rem;
  outline: 2px solid var(--accent);
  outline-offset: 2px;
}

/* Minimal Vector Icons (Zero-Dependency SVG) */
.ui-icon {
  width: 1rem;
  height: 1rem;
  display: inline-block;
  vertical-align: -0.15em;
  stroke-width: 2;
  stroke: currentColor;
  fill: none;
  flex-shrink: 0;
}
.ui-icon-sm { width: 0.82rem; height: 0.82rem; }
.ui-icon-lg { width: 1.25rem; height: 1.25rem; }
.btn .ui-icon { margin-right: 0.35rem; }
.icon-emerald { color: var(--emerald); }
.icon-amber { color: var(--amber); }
.icon-danger { color: var(--danger); }

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
.brand-logo .ui-icon {
  color: var(--accent);
  width: 1.15rem;
  height: 1.15rem;
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
  align-items: center;
  gap: 0.25rem;
  background: var(--bg-elevated);
  padding: 0.25rem;
  border-radius: 0.55rem;
  border: 1px solid var(--border-color);
}
.nav-tab {
  background: transparent;
  border: none;
  color: var(--text-secondary);
  padding: 0.38rem 0.85rem;
  border-radius: 0.4rem;
  font-size: 0.84rem;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.15s ease;
  display: inline-flex;
  align-items: center;
  gap: 0.4rem;
}
.nav-tab:hover {
  color: var(--text-main);
}
.nav-tab.active {
  background: var(--bg-surface);
  color: var(--text-main);
  box-shadow: 0 1px 3px rgba(0,0,0,0.18);
}
.nav-tab:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: 1px;
}
.header-actions {
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

/* Buttons */
.btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 0.35rem;
  padding: 0.45rem 0.9rem;
  border-radius: 0.45rem;
  font-size: 0.82rem;
  font-weight: 600;
  cursor: pointer;
  border: 1px solid var(--border-color);
  background: var(--bg-elevated);
  color: var(--text-main);
  transition: all 0.15s ease;
  text-decoration: none;
}
.btn:hover {
  background: var(--bg-surface);
  border-color: var(--border-hover);
}
.btn:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: 1px;
}
.btn-primary {
  background: var(--accent);
  border-color: var(--accent);
  color: #ffffff;
}
.btn-primary:hover {
  background: var(--accent-hover);
  border-color: var(--accent-hover);
  color: #ffffff;
}
.btn-sm {
  padding: 0.32rem 0.65rem;
  font-size: 0.76rem;
}

/* Main Container */
main.workspace {
  flex: 1;
  padding: 1.25rem 1.4rem 3rem;
  max-width: 1440px;
  width: 100%;
  margin: 0 auto;
  display: flex;
  flex-direction: column;
  gap: 1rem;
}

/* Search Panel */
.search-panel {
  background: var(--bg-surface);
  border: 1px solid var(--border-color);
  border-radius: 0.75rem;
  padding: 1rem 1.25rem;
  box-shadow: var(--shadow);
  position: relative;
}
.search-bar-row {
  display: flex;
  gap: 0.6rem;
  align-items: center;
}
.search-input-wrap {
  flex: 1;
  position: relative;
  display: flex;
  align-items: center;
}
.search-input-wrap .search-icon-left {
  position: absolute;
  left: 0.85rem;
  color: var(--text-secondary);
  pointer-events: none;
}
.search-input {
  width: 100%;
  padding: 0.72rem 4rem 0.72rem 2.45rem;
  background: var(--bg-input);
  border: 1px solid var(--border-color);
  border-radius: 0.5rem;
  color: var(--text-main);
  font-size: 0.94rem;
  transition: border-color 0.15s ease, box-shadow 0.15s ease;
}
.search-input:focus {
  outline: none;
  border-color: var(--accent);
  box-shadow: 0 0 0 3px var(--accent-soft);
}
.kbd-hint {
  position: absolute;
  right: 0.75rem;
  font-size: 0.72rem;
  color: var(--text-secondary);
  background: var(--bg-elevated);
  border: 1px solid var(--border-color);
  padding: 0.15rem 0.4rem;
  border-radius: 0.25rem;
  pointer-events: none;
}

/* Autocomplete Suggest Box */
.suggest-box {
  position: absolute;
  top: calc(100% + 4px);
  left: 0;
  right: 0;
  background: var(--bg-surface);
  border: 1px solid var(--border-color);
  border-radius: 0.5rem;
  box-shadow: 0 12px 28px rgba(0,0,0,0.36);
  z-index: 60;
  max-height: 280px;
  overflow-y: auto;
  display: none;
}
.suggest-box.show { display: block; }
.suggest-item {
  padding: 0.6rem 1rem;
  cursor: pointer;
  font-size: 0.86rem;
  color: var(--text-main);
  display: flex;
  align-items: center;
  gap: 0.6rem;
  border-bottom: 1px solid rgba(255,255,255,0.04);
  transition: background 0.12s ease, color 0.12s ease;
}
.suggest-item:last-child {
  border-bottom: none;
}
.suggest-item span {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.suggest-item .ui-icon {
  color: var(--text-secondary);
  flex-shrink: 0;
  transition: color 0.12s ease;
}
.suggest-item:hover, .suggest-item.active {
  background: var(--accent-soft);
  color: var(--accent-hover);
}
.suggest-item:hover .ui-icon, .suggest-item.active .ui-icon {
  color: var(--accent-hover);
}

/* Recent Searches */
.recent-searches-wrap {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 0.4rem;
  margin-top: 0.55rem;
  font-size: 0.76rem;
}
.recent-label {
  color: var(--text-secondary);
  font-weight: 600;
  margin-right: 0.2rem;
  display: inline-flex;
  align-items: center;
  gap: 0.25rem;
}
.recent-chip {
  background: var(--bg-elevated);
  border: 1px solid var(--border-color);
  color: var(--text-secondary);
  border-radius: 999px;
  padding: 0.16rem 0.6rem;
  font-size: 0.74rem;
  cursor: pointer;
  transition: all 0.12s ease;
  display: inline-flex;
  align-items: center;
  gap: 0.3rem;
}
.recent-chip:hover {
  border-color: var(--accent);
  color: var(--text-main);
  background: var(--accent-soft);
}
.recent-clear-btn {
  background: transparent;
  border: none;
  color: var(--text-secondary);
  cursor: pointer;
  font-size: 0.72rem;
  margin-left: 0.2rem;
  text-decoration: underline;
}
.recent-clear-btn:hover { color: var(--danger); }

/* Options Row */
.options-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.65rem;
  margin-top: 0.75rem;
  padding-top: 0.75rem;
  border-top: 1px solid var(--border-color);
}
.opt-group {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  font-size: 0.8rem;
  color: var(--text-secondary);
}
.opt-select, .opt-input {
  background: var(--bg-input);
  border: 1px solid var(--border-color);
  color: var(--text-main);
  border-radius: 0.4rem;
  padding: 0.32rem 0.6rem;
  font-size: 0.8rem;
}
.opt-select:focus, .opt-input:focus {
  outline: none;
  border-color: var(--accent);
}
.opt-input { min-width: 11rem; }

/* Preset Chips (Subtractive, Clean Style) */
.preset-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 0.35rem;
  margin-left: auto;
}
.chip {
  background: var(--bg-elevated);
  border: 1px solid var(--border-color);
  color: var(--text-secondary);
  font-size: 0.76rem;
  font-weight: 500;
  padding: 0.22rem 0.6rem;
  border-radius: 0.35rem;
  cursor: pointer;
  transition: all 0.12s ease;
}
.chip:hover {
  background: var(--bg-surface);
  color: var(--text-main);
  border-color: var(--accent);
}

/* Classic Category Pills */
.cat-btn {
  background: var(--bg-elevated);
  border: 1px solid var(--border-color);
  color: var(--text-secondary);
  font-size: 0.76rem;
  font-weight: 500;
  padding: 0.22rem 0.65rem;
  border-radius: 999px;
  cursor: pointer;
  transition: all 0.15s ease;
}
.cat-btn:hover {
  color: var(--text-main);
  border-color: var(--accent);
}
.cat-btn.active {
  background: var(--accent-soft);
  color: var(--accent-hover);
  border-color: var(--accent);
  font-weight: 700;
}
.cat-btn:focus-visible {
  outline: 2px solid var(--accent);
}

/* Pills & Badges */
.pill {
  display: inline-flex;
  align-items: center;
  gap: 0.25rem;
  font-size: 0.72rem;
  font-weight: 600;
  padding: 0.14rem 0.5rem;
  border-radius: 999px;
  background: var(--bg-elevated);
  color: var(--text-secondary);
  border: 1px solid var(--border-color);
}
.pill-accent {
  background: var(--accent-soft);
  color: var(--accent-hover);
  border-color: rgba(99, 102, 241, 0.3);
}
.pill-emerald {
  background: var(--emerald-soft);
  color: var(--emerald);
  border-color: rgba(16, 185, 129, 0.3);
}
.pill-amber {
  background: var(--amber-soft);
  color: var(--amber);
  border-color: rgba(245, 158, 11, 0.3);
}
.pill-danger {
  background: var(--danger-soft);
  color: var(--danger);
  border-color: rgba(239, 68, 68, 0.3);
}

/* Telemetry Ribbon */
.telemetry-bar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 0.6rem;
  padding: 0.55rem 0.85rem;
  background: var(--bg-surface);
  border: 1px solid var(--border-color);
  border-radius: 0.55rem;
  opacity: 0;
  transform: translateY(-4px);
  transition: all 0.2s ease;
  pointer-events: none;
}
.telemetry-bar.visible {
  opacity: 1;
  transform: translateY(0);
  pointer-events: auto;
}
.telemetry-left, .telemetry-right {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 0.45rem;
}

/* Split Grid Layout (AI Deep Search) */
.split-grid {
  display: grid;
  grid-template-columns: minmax(0, 1.45fr) minmax(360px, 1fr);
  gap: 1.25rem;
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
  header.topbar { padding: 0.65rem 0.9rem; }
  main.workspace { padding: 0.9rem 0.9rem 2rem; }
  .search-bar-row { flex-wrap: wrap; }
  .search-bar-row #run-btn { width: 100%; justify-content: center; }
  #classic-deep-btn { width: 100%; justify-content: center; }
  .options-row .opt-group { width: 100%; margin-left: 0 !important; }
  .options-row .opt-input { min-width: 0; width: 100%; }
  .kbd-hint { display: none; }
  .search-input { padding-right: 0.95rem; }
  .preset-chips { margin-left: 0; width: 100%; }
  .nav-tabs {
    width: 100%;
    overflow-x: auto;
    scrollbar-width: none;
    -webkit-overflow-scrolling: touch;
  }
  .nav-tab {
    white-space: nowrap;
    flex-shrink: 0;
  }
  .context-tabs {
    overflow-x: auto;
    scrollbar-width: none;
    -webkit-overflow-scrolling: touch;
  }
  .ctx-tab {
    white-space: nowrap;
    flex-shrink: 0;
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
  padding: 1.1rem 1.25rem;
  transition: border-color 0.15s ease, box-shadow 0.15s ease;
  display: flex;
  flex-direction: column;
  gap: 0.55rem;
}
.result-card:hover {
  border-color: var(--border-hover);
  box-shadow: var(--shadow);
}
.result-card.selected-card {
  border-color: var(--accent);
  box-shadow: 0 0 0 2px var(--accent-soft);
}
.card-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.5rem;
  font-size: 0.76rem;
}
.card-rank {
  font-weight: 700;
  color: var(--accent-hover);
}
.card-domain-wrap {
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
}
.card-favicon {
  width: 14px;
  height: 14px;
  border-radius: 2px;
  object-fit: contain;
}
.card-domain {
  color: var(--text-secondary);
  font-weight: 500;
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
}
.card-title a { color: var(--text-main); }
.card-title a:hover { color: var(--accent-hover); }

/* Highlights & Snippets */
.highlight-block {
  font-size: 0.84rem;
  color: var(--text-secondary);
  line-height: 1.55;
  background: var(--bg-elevated);
  border-left: 3px solid var(--accent);
  padding: 0.5rem 0.75rem;
  border-radius: 0 0.4rem 0.4rem 0;
  margin: 0.25rem 0;
}
.highlight-code {
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 0.78rem;
  background: var(--bg-input);
  border: 1px solid var(--border-color);
  padding: 0.6rem 0.75rem;
  border-radius: 0.4rem;
  overflow-x: auto;
  color: var(--emerald);
  margin: 0.25rem 0;
}
.card-actions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.45rem;
  margin-top: 0.25rem;
}
.inline-scrape-drawer {
  background: var(--bg-input);
  border: 1px solid var(--border-color);
  border-radius: 0.5rem;
  padding: 0.85rem;
  font-size: 0.82rem;
  line-height: 1.55;
  max-height: 24rem;
  overflow-y: auto;
  white-space: pre-wrap;
  margin-top: 0.4rem;
}

/* Skeleton Loading Cards */
@keyframes skeleton-pulse {
  0% { opacity: 0.4; }
  50% { opacity: 0.85; }
  100% { opacity: 0.4; }
}
.skeleton-card {
  background: var(--bg-surface);
  border: 1px solid var(--border-color);
  border-radius: 0.75rem;
  padding: 1.1rem 1.25rem;
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
  animation: skeleton-pulse 1.4s ease-in-out infinite;
}
.skeleton-line {
  background: var(--bg-elevated);
  border-radius: 4px;
  height: 0.85rem;
}
.skeleton-line.title { height: 1.25rem; width: 68%; }
.skeleton-line.meta { height: 0.75rem; width: 32%; }
.skeleton-line.body1 { width: 95%; }
.skeleton-line.body2 { width: 85%; }
.skeleton-line.body3 { width: 55%; }

/* Spinner */
@keyframes spin {
  to { transform: rotate(360deg); }
}
.ui-spinner {
  width: 1rem;
  height: 1rem;
  border: 2px solid var(--border-color);
  border-top-color: var(--accent);
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
  display: inline-block;
  vertical-align: -0.15em;
}

/* Context Panel (AI Studio Right) */
.context-panel {
  background: var(--bg-surface);
  border: 1px solid var(--border-color);
  border-radius: 0.75rem;
  padding: 1.1rem 1.25rem;
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
  position: sticky;
  top: 4.5rem;
  max-height: calc(100vh - 5.5rem);
}
.context-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.context-tabs {
  display: flex;
  gap: 0.25rem;
  background: var(--bg-elevated);
  padding: 0.2rem;
  border-radius: 0.45rem;
  border: 1px solid var(--border-color);
}
.ctx-tab {
  flex: 1;
  background: transparent;
  border: none;
  color: var(--text-secondary);
  padding: 0.3rem 0.5rem;
  border-radius: 0.35rem;
  font-size: 0.76rem;
  font-weight: 600;
  cursor: pointer;
  text-align: center;
  transition: all 0.15s ease;
}
.ctx-tab:hover { color: var(--text-main); }
.ctx-tab.active {
  background: var(--bg-surface);
  color: var(--text-main);
  box-shadow: 0 1px 2px rgba(0,0,0,0.15);
}
.ctx-tab:focus-visible { outline: 2px solid var(--accent); }
.context-textarea {
  width: 100%;
  height: 28rem;
  background: var(--bg-input);
  border: 1px solid var(--border-color);
  border-radius: 0.5rem;
  color: var(--text-main);
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 0.8rem;
  line-height: 1.5;
  padding: 0.75rem;
  resize: vertical;
}
.context-textarea:focus { outline: none; border-color: var(--accent); }

/* Context Markdown Preview Container */
.ctx-preview-container {
  width: 100%;
  height: 28rem;
  background: var(--bg-input);
  border: 1px solid var(--border-color);
  border-radius: 0.5rem;
  color: var(--text-main);
  font-size: 0.82rem;
  line-height: 1.6;
  padding: 0.85rem 1rem;
  overflow-y: auto;
  display: none;
}
.ctx-preview-container h1, .ctx-preview-container h2, .ctx-preview-container h3 {
  margin: 0.75rem 0 0.35rem;
  color: var(--accent-hover);
  font-weight: 700;
}
.ctx-preview-container h1 { font-size: 1.15rem; }
.ctx-preview-container h2 { font-size: 1.02rem; }
.ctx-preview-container h3 { font-size: 0.92rem; }
.ctx-preview-container p { margin: 0.4rem 0; }
.ctx-preview-container blockquote {
  border-left: 3px solid var(--accent);
  padding: 0.25rem 0.75rem;
  color: var(--text-secondary);
  margin: 0.5rem 0;
  background: var(--bg-elevated);
  border-radius: 0 0.3rem 0.3rem 0;
}
.ctx-preview-container pre {
  background: var(--bg-surface);
  border: 1px solid var(--border-color);
  padding: 0.6rem;
  border-radius: 0.4rem;
  overflow-x: auto;
  font-size: 0.78rem;
  margin: 0.5rem 0;
}
.ctx-preview-container table {
  width: 100%;
  border-collapse: collapse;
  margin: 0.6rem 0;
  font-size: 0.78rem;
}
.ctx-preview-container th, .ctx-preview-container td {
  border: 1px solid var(--border-color);
  padding: 0.35rem 0.55rem;
}
.ctx-preview-container th { background: var(--bg-elevated); font-weight: 700; }

.token-progress-wrap {
  display: flex;
  flex-direction: column;
  gap: 0.3rem;
  font-size: 0.74rem;
  color: var(--text-secondary);
}
.token-bar-bg {
  width: 100%;
  height: 6px;
  background: var(--bg-elevated);
  border-radius: 999px;
  overflow: hidden;
}
.token-bar-fill {
  height: 100%;
  width: 0%;
  background: var(--accent);
  transition: width 0.3s ease, background 0.3s ease;
}

/* Classic Search Mode View */
.classic-view-wrap {
  max-width: 860px;
  width: 100%;
  margin: 0 auto;
}
.classic-card {
  background: var(--bg-surface);
  border: 1px solid var(--border-color);
  border-radius: 0.75rem;
  padding: 1.1rem 1.3rem;
  display: flex;
  flex-direction: column;
  gap: 0.4rem;
  transition: border-color 0.15s ease;
}
.classic-card:hover { border-color: var(--border-hover); }
.classic-card.selected-card {
  border-color: var(--accent);
  box-shadow: 0 0 0 2px var(--accent-soft);
}
.classic-meta-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.5rem;
}
.classic-url-tag {
  font-size: 0.76rem;
  color: var(--text-secondary);
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
}
.classic-title-link {
  font-size: 1.08rem;
  font-weight: 700;
  color: var(--accent-hover);
  text-decoration: none;
}
.classic-title-link:hover { text-decoration: underline; }
.classic-snippet-text {
  font-size: 0.84rem;
  color: var(--text-secondary);
  line-height: 1.55;
}
.classic-actions-row {
  display: flex;
  align-items: center;
  gap: 0.45rem;
  margin-top: 0.35rem;
}
.classic-pagination-row {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 0.75rem;
  margin-top: 1.5rem;
}
.classic-answer-box {
  background: var(--accent-soft);
  border: 1px solid var(--accent);
  border-radius: 0.6rem;
  padding: 0.85rem 1.1rem;
  font-size: 0.86rem;
  line-height: 1.55;
  color: var(--text-main);
  margin-bottom: 0.85rem;
}

/* Image Grid Gallery */
.image-results-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(185px, 1fr));
  gap: 0.85rem;
  margin-top: 0.6rem;
}
.image-card {
  background: var(--bg-surface);
  border: 1px solid var(--border-color);
  border-radius: 0.6rem;
  overflow: hidden;
  display: flex;
  flex-direction: column;
  transition: transform 0.15s ease, border-color 0.15s ease;
}
.image-card:hover {
  transform: translateY(-2px);
  border-color: var(--border-hover);
}
.image-card.selected-card {
  border-color: var(--accent);
  box-shadow: 0 0 0 2px var(--accent-soft);
}
.image-card-thumb-wrap {
  width: 100%;
  height: 135px;
  background: var(--bg-elevated);
  position: relative;
  overflow: hidden;
  display: block;
  text-decoration: none;
}
.image-card-thumb {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
  transition: transform 0.2s ease;
}
.image-card:hover .image-card-thumb {
  transform: scale(1.03);
}
.image-res-badge {
  position: absolute;
  bottom: 6px;
  right: 6px;
  background: rgba(0, 0, 0, 0.72);
  color: #fff;
  font-size: 0.68rem;
  font-weight: 600;
  padding: 1px 5px;
  border-radius: 4px;
  backdrop-filter: blur(4px);
  pointer-events: none;
}
.image-card-placeholder {
  width: 100%;
  height: 100%;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 0.3rem;
  color: var(--text-muted);
  font-size: 0.72rem;
  background: var(--bg-elevated);
}
.image-card-placeholder svg {
  width: 1.5rem;
  height: 1.5rem;
  opacity: 0.6;
}
.image-card-body {
  padding: 0.55rem 0.7rem;
  display: flex;
  flex-direction: column;
  gap: 0.2rem;
}
.image-card-title {
  font-size: 0.76rem;
  font-weight: 600;
  line-height: 1.35;
  color: var(--text-main);
  overflow: hidden;
  text-overflow: ellipsis;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
}
.image-card-meta {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-top: 0.15rem;
}
.image-card-domain {
  font-size: 0.7rem;
  color: var(--text-secondary);
}
.image-full-link {
  color: var(--text-muted);
  display: inline-flex;
  align-items: center;
  transition: color 0.15s ease;
}
.image-full-link:hover {
  color: var(--accent);
}

/* Video Results List & Cards */
.video-results-list {
  display: flex;
  flex-direction: column;
  gap: 0.9rem;
  margin-top: 0.6rem;
}
.video-card {
  background: var(--bg-surface);
  border: 1px solid var(--border-color);
  border-radius: 0.75rem;
  padding: 0.85rem;
  display: flex;
  gap: 1.15rem;
  transition: border-color 0.15s ease, box-shadow 0.15s ease;
}
.video-card:hover {
  border-color: var(--border-hover);
  box-shadow: var(--shadow);
}
.video-card.selected-card {
  border-color: var(--accent);
  box-shadow: 0 0 0 2px var(--accent-soft);
}
.video-thumb-wrap {
  width: 220px;
  min-width: 220px;
  height: 124px;
  background: var(--bg-elevated);
  border-radius: 0.55rem;
  position: relative;
  overflow: hidden;
  display: block;
  flex-shrink: 0;
  text-decoration: none;
}
.video-thumb-img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
  transition: transform 0.2s ease;
}
.video-card:hover .video-thumb-img {
  transform: scale(1.03);
}
.video-thumb-placeholder {
  width: 100%;
  height: 100%;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 0.35rem;
  color: var(--text-muted);
  font-size: 0.75rem;
  background: var(--bg-elevated);
}
.video-play-overlay {
  position: absolute;
  top: 50%;
  left: 50%;
  transform: translate(-50%, -50%);
  width: 38px;
  height: 38px;
  background: rgba(0, 0, 0, 0.65);
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #fff;
  opacity: 0.85;
  transition: all 0.2s ease;
  pointer-events: none;
}
.video-card:hover .video-play-overlay {
  opacity: 1;
  transform: translate(-50%, -50%) scale(1.1);
  background: var(--accent);
}
.video-play-overlay svg {
  width: 16px;
  height: 16px;
  margin-left: 2px;
}
.video-duration-badge {
  position: absolute;
  bottom: 6px;
  right: 6px;
  background: rgba(0, 0, 0, 0.8);
  color: #fff;
  font-size: 0.72rem;
  font-weight: 600;
  padding: 1px 6px;
  border-radius: 4px;
  letter-spacing: 0.02em;
  pointer-events: none;
}
.video-card-content {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 0.35rem;
}
.video-title-link {
  font-size: 1.05rem;
  font-weight: 700;
  line-height: 1.35;
  color: var(--accent-hover);
  text-decoration: none;
  overflow: hidden;
  text-overflow: ellipsis;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
}
.video-title-link:hover {
  text-decoration: underline;
}
.video-snippet-text {
  font-size: 0.84rem;
  color: var(--text-secondary);
  line-height: 1.5;
  overflow: hidden;
  text-overflow: ellipsis;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
}
@media (max-width: 640px) {
  .video-card {
    flex-direction: column;
    gap: 0.75rem;
  }
  .video-thumb-wrap {
    width: 100%;
    min-width: 0;
    height: 190px;
  }
}
@media (max-width: 480px) {
  .image-results-grid {
    grid-template-columns: repeat(auto-fill, minmax(130px, 1fr));
    gap: 0.5rem;
  }
  .image-card-thumb-wrap {
    height: 105px;
  }
}

/* Settings Dashboard View */
.settings-view-wrap {
  max-width: 1100px;
  width: 100%;
  margin: 0 auto;
  display: flex;
  flex-direction: column;
  gap: 1.25rem;
}
.stats-overview-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
  gap: 0.85rem;
}
.stat-card {
  background: var(--bg-surface);
  border: 1px solid var(--border-color);
  border-radius: 0.65rem;
  padding: 0.85rem 1.1rem;
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
}
.stat-card-label {
  font-size: 0.74rem;
  font-weight: 600;
  color: var(--text-secondary);
  text-transform: uppercase;
  letter-spacing: 0.04em;
}
.stat-card-value {
  font-size: 1.35rem;
  font-weight: 800;
  color: var(--text-main);
}
.settings-subtabs {
  display: flex;
  gap: 0.5rem;
  border-bottom: 1px solid var(--border-color);
  padding-bottom: 0.5rem;
}
.settings-subtab {
  background: transparent;
  border: none;
  color: var(--text-secondary);
  font-size: 0.88rem;
  font-weight: 600;
  padding: 0.4rem 0.85rem;
  border-radius: 0.4rem;
  cursor: pointer;
  transition: all 0.15s ease;
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
}
.settings-subtab:hover { color: var(--text-main); }
.settings-subtab.active {
  background: var(--accent-soft);
  color: var(--accent-hover);
}
.settings-subtab:focus-visible { outline: 2px solid var(--accent); }
.engine-toolbar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 0.75rem;
  margin-bottom: 0.85rem;
}
.engine-search-wrap { flex: 1; max-width: 22rem; }
.engine-search-input {
  width: 100%;
  padding: 0.45rem 0.8rem;
  background: var(--bg-input);
  border: 1px solid var(--border-color);
  border-radius: 0.45rem;
  color: var(--text-main);
  font-size: 0.82rem;
}
.engine-bulk-actions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.45rem;
}
.engines-category-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 0.35rem;
  margin-bottom: 1rem;
}
.engines-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(min(100%, 280px), 1fr));
  gap: 0.75rem;
}
.engine-item-card {
  background: var(--bg-surface);
  border: 1px solid var(--border-color);
  border-radius: 0.6rem;
  padding: 0.75rem 0.95rem;
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
  transition: border-color 0.15s ease;
}
.engine-item-card:hover { border-color: var(--border-hover); }
.engine-item-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.engine-item-title {
  font-size: 0.88rem;
  font-weight: 700;
  display: flex;
  align-items: center;
  gap: 0.45rem;
}
.engine-item-meta {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.35rem;
  font-size: 0.72rem;
}

/* Toggle Switch */
.switch-label {
  position: relative;
  display: inline-block;
  width: 38px;
  height: 22px;
  cursor: pointer;
}
.switch-label input { opacity: 0; width: 0; height: 0; }
.switch-slider {
  position: absolute;
  top: 0; left: 0; right: 0; bottom: 0;
  background: var(--bg-elevated);
  border: 1px solid var(--border-color);
  border-radius: 999px;
  transition: all 0.2s ease;
}
.switch-slider:before {
  position: absolute;
  content: "";
  height: 16px;
  width: 16px;
  left: 2px;
  bottom: 2px;
  background: #ffffff;
  border-radius: 50%;
  transition: transform 0.2s ease;
}
.switch-label input:checked + .switch-slider {
  background: var(--accent);
  border-color: var(--accent);
}
.switch-label input:checked + .switch-slider:before {
  transform: translateX(16px);
}
.switch-label input:focus-visible + .switch-slider {
  outline: 2px solid var(--accent);
  outline-offset: 2px;
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

/* Unsaved Changes Banner */
.unsaved-bar {
  position: fixed;
  bottom: 1.5rem;
  left: 50%;
  transform: translateX(-50%) translateY(100px);
  background: var(--bg-surface);
  border: 1px solid var(--amber);
  box-shadow: 0 10px 30px rgba(0,0,0,0.45);
  padding: 0.75rem 1.4rem;
  border-radius: 0.6rem;
  display: flex;
  align-items: center;
  gap: 1rem;
  z-index: 100;
  transition: transform 0.25s ease, opacity 0.25s ease;
  opacity: 0;
  pointer-events: none;
}
.unsaved-bar.show {
  transform: translateX(-50%) translateY(0);
  opacity: 1;
  pointer-events: auto;
}
.unsaved-text {
  font-size: 0.84rem;
  font-weight: 600;
  color: var(--text-main);
  display: inline-flex;
  align-items: center;
  gap: 0.45rem;
}

/* Agent Hub Grid */
.hub-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(min(100%, 280px), 1fr));
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

/* Empty State */
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
  display: inline-flex;
  align-items: center;
  gap: 0.5rem;
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
  color: var(--text-secondary);
  border-top: 1px solid var(--border-color);
  background: var(--bg-surface);
}

  </style>
</head>
<body>
  <a href="#q" class="skip-link">検索入力へスキップ</a>
  <header class="topbar">
    <div class="brand-group">
      <a href="/" class="brand-logo" title="SearXNG Next Studio">
        <svg class="ui-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m12 3-1.9 5.8a2 2 0 0 1-1.3 1.3L3 12l5.8 1.9a2 2 0 0 1 1.3 1.3L12 21l1.9-5.8a2 2 0 0 1 1.3-1.3L21 12l-5.8-1.9a2 2 0 0 1-1.3-1.3Z"></path></svg>
        <span>SearXNG Next</span>
      </a>
      <span class="brand-badge">AI-First Edition</span>
      <span class="status-dot" id="health-dot" role="img" aria-label="Checking server status" title="Checking server status"></span>
    </div>

    <nav class="nav-tabs" role="tablist" aria-label="Workspace Modes">
      <button type="button" class="nav-tab active" role="tab" aria-selected="true" tabindex="0" aria-controls="main-split-view" data-mode="deep" id="tab-deep">Deep Search</button>
      <button type="button" class="nav-tab" role="tab" aria-selected="false" tabindex="-1" aria-controls="classic-search-view" data-mode="classic" id="tab-classic">Classic 検索</button>
      <button type="button" class="nav-tab" role="tab" aria-selected="false" tabindex="-1" aria-controls="agent-hub-view" data-mode="agent" id="tab-agent">Agent Hub</button>
      <button type="button" class="nav-tab" role="tab" aria-selected="false" tabindex="-1" aria-controls="settings-view" data-mode="settings" id="tab-settings">設定</button>
    </nav>

    <div class="header-actions">
      <button type="button" class="btn btn-sm" id="theme-toggle-btn" title="テーマ切替 (Dark / Light)" aria-label="テーマ切替">
        <svg class="ui-icon" id="theme-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 3a6 6 0 0 0 9 9 9 9 0 1 1-9-9Z"></path></svg>
        <span>テーマ</span>
      </button>
    </div>
  </header>

  <main class="workspace">
    <!-- Common Search & Scrape Input Panel -->
    <section class="search-panel" id="input-panel">
      <form id="ws-form" role="search" autocomplete="off">
        <div class="search-bar-row">
          <div class="search-input-wrap">
            <svg class="ui-icon search-icon-left" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="11" cy="11" r="8"></circle><line x1="21" y1="21" x2="16.65" y2="16.65"></line></svg>
            <input
              id="q"
              name="q"
              type="text"
              class="search-input"
              role="combobox"
              aria-label="Search query or target URL"
              aria-autocomplete="list"
              aria-controls="suggest-box"
              aria-expanded="false"
              placeholder="キーワード・質問 または URL (https://...) を入力 — URLは自動で本文抽出モードに切替..."
              autocomplete="off"
              autofocus
            >
            <span class="kbd-hint">/ or Ctrl+K</span>
            <div id="suggest-box" class="suggest-box" role="listbox" aria-label="検索候補"></div>
          </div>
          <button type="submit" class="btn btn-primary" id="run-btn" style="padding:0.72rem 1.25rem;font-size:0.9rem;">
            検索実行
          </button>
        </div>

        <!-- Recent Searches List -->
        <div id="recent-searches-wrap" class="recent-searches-wrap" style="display:none;"></div>

        <!-- AI Deep Search Options -->
        <div class="options-row" id="search-options-row">
          <div class="opt-group" id="opt-depth-group">
            <label for="opt-depth">Depth:</label>
            <select id="opt-depth" class="opt-select">
              <option value="advanced" selected>Deep: Advanced (並列本文抽出 + BM25)</option>
              <option value="code">Deep: Code &amp; Docs (技術・GitHub優先)</option>
              <option value="basic">Basic (スニペット + ドメイン評価)</option>
              <option value="fast">Fast: json_lite (最速スニペットのみ)</option>
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
            <button type="button" class="chip" data-preset="docs">公式Docs優先</button>
            <button type="button" class="chip" data-preset="github">GitHub &amp; SO</button>
            <button type="button" class="chip" data-preset="academic">Academic</button>
            <button type="button" class="chip" data-preset="clear">クリア</button>
          </div>
        </div>

        <!-- Classic Search Options (Category pills & Time range) -->
        <div class="options-row" id="classic-options-row" style="display:none;">
          <div class="opt-group" style="flex: 1; flex-wrap: wrap;">
            <span style="font-weight:600;font-size:0.78rem;color:var(--text-muted);margin-right:0.2rem;">カテゴリー:</span>
            <div class="preset-chips" id="classic-cat-chips" style="margin-left:0;">
              <button type="button" class="cat-btn active" data-cat="" aria-pressed="true">全般</button>
              <button type="button" class="cat-btn" data-cat="it" aria-pressed="false">IT・技術</button>
              <button type="button" class="cat-btn" data-cat="news" aria-pressed="false">ニュース</button>
              <button type="button" class="cat-btn" data-cat="science" aria-pressed="false">科学</button>
              <button type="button" class="cat-btn" data-cat="files" aria-pressed="false">ファイル</button>
              <button type="button" class="cat-btn" data-cat="social media" aria-pressed="false">ソーシャル</button>
              <button type="button" class="cat-btn" data-cat="images" aria-pressed="false">画像</button>
              <button type="button" class="cat-btn" data-cat="videos" aria-pressed="false">動画</button>
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

          <div class="opt-group" style="margin-left: auto;">
            <button type="button" class="btn btn-primary btn-sm" id="classic-deep-btn" title="Deep Searchモードに切り替えて、本文抽出とBM25スコアリングで深掘り検索を実行します">
              <svg class="ui-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="11" cy="11" r="8"></circle><line x1="21" y1="21" x2="16.65" y2="16.65"></line><line x1="11" y1="8" x2="11" y2="14"></line><line x1="8" y1="11" x2="14" y2="11"></line></svg>
              <span>Deep Searchで深掘り</span>
            </button>
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
          <span class="pill pill-emerald">URL自動検知 · DNS-Pinned &amp; SSRF Protected</span>
        </div>
      </form>
    </section>

    <!-- Telemetry & Quick Action Ribbon -->
    <section class="telemetry-bar" id="telemetry-bar" role="status" aria-live="polite">
      <div class="telemetry-left" id="telemetry-badges"></div>
      <div class="telemetry-right">
        <button type="button" class="btn btn-primary btn-sm" id="copy-md-main">
          <svg class="ui-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect width="14" height="14" x="8" y="8" rx="2" ry="2"></rect><path d="M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2"></path></svg>
          <span>Markdownをコピー</span>
        </button>
        <button type="button" class="btn btn-sm" id="copy-prompt-main">
          <span>RAGプロンプト形式</span>
        </button>
        <button type="button" class="btn btn-sm" id="copy-json-main">
          <span>JSON形式</span>
        </button>
        <button type="button" class="btn btn-sm" id="download-md-btn">
          <svg class="ui-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path><polyline points="7 10 12 15 17 10"></polyline><line x1="12" y1="15" x2="12" y2="3"></line></svg>
          <span>.md 保存</span>
        </button>
      </div>
    </section>

    <!-- View 1: AI Deep Search (Split Grid View) -->
    <section class="split-grid" id="main-split-view" role="tabpanel" aria-labelledby="tab-deep">
      <div class="results-list" id="results-container" aria-live="polite" aria-busy="false">
        <div class="empty-state" id="initial-empty-state">
          <h2>AI-First Unified Search &amp; Context Studio</h2>
          <p>検索キーワードを入力すると Deep Search (並列本文抽出 + BM25パッセージ抽出) を実行し、URL を貼り付けると自動で単一ページ本文抽出に切り替わります。</p>
          <div class="sample-queries">
            <button type="button" class="chip sample-q" data-q="FastAPI lifespan context manager syntax">FastAPI lifespan context manager</button>
            <button type="button" class="chip sample-q" data-q="Python asyncio TaskGroup exception handling">Python asyncio.TaskGroup</button>
            <button type="button" class="chip sample-q" data-q="https://docs.searxng.org">https://docs.searxng.org (URL抽出デモ)</button>
          </div>
        </div>
      </div>

      <!-- Sticky Right Panel: AI Context Inspector -->
      <aside class="context-panel" id="context-panel">
        <div class="context-header">
          <strong style="font-size:0.88rem;">LLM Context Inspector</strong>
          <div style="display:flex;gap:0.35rem;">
            <button type="button" class="btn btn-primary btn-sm" id="ctx-copy-btn">
              <svg class="ui-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect width="14" height="14" x="8" y="8" rx="2" ry="2"></rect><path d="M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2"></path></svg>
              <span>コピー</span>
            </button>
          </div>
        </div>
        <div class="context-tabs" role="tablist" aria-label="Context Output Format">
          <button type="button" class="ctx-tab active" role="tab" aria-selected="true" tabindex="0" aria-controls="ctx-output" data-ctx="markdown">Markdown</button>
          <button type="button" class="ctx-tab" role="tab" aria-selected="false" tabindex="-1" aria-controls="ctx-output" data-ctx="prompt">RAG Prompt</button>
          <button type="button" class="ctx-tab" role="tab" aria-selected="false" tabindex="-1" aria-controls="ctx-output" data-ctx="preview">Preview</button>
          <button type="button" class="ctx-tab" role="tab" aria-selected="false" tabindex="-1" aria-controls="ctx-output" data-ctx="json">JSON</button>
          <button type="button" class="ctx-tab" role="tab" aria-selected="false" tabindex="-1" aria-controls="ctx-output" data-ctx="curl">API / CLI</button>
        </div>
        <textarea id="ctx-output" class="context-textarea" readonly aria-label="Generated AI Context" placeholder="検索またはURL本文抽出を実行すると、ここにLLM貼り付け用の構造化Markdown・プロンプト・JSONが生成されます。"></textarea>
        <div id="ctx-preview" class="ctx-preview-container" aria-label="Markdown Preview"></div>
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
          <h2>Classic 軽量メタ検索モード</h2>
          <p>余分なAIパッキングを省き、複数の検索エンジンからスニペットを高速取得して一覧表示します。上部のカテゴリータブで絞り込みも可能です。</p>
          <div class="sample-queries">
            <button type="button" class="chip sample-classic-q" data-q="SearXNG Windows next release">SearXNG Windows next release</button>
            <button type="button" class="chip sample-classic-q" data-q="uv python package manager">uv python package manager</button>
          </div>
        </div>
      </div>
      <div id="classic-pagination-bar" class="classic-pagination-row" style="display:none;">
        <button type="button" class="btn btn-sm" id="classic-prev-btn">&larr; 前のページ</button>
        <span id="classic-page-indicator" class="pill">ページ 1 / 10</span>
        <button type="button" class="btn btn-sm" id="classic-next-btn">次のページ &rarr;</button>
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
      <div class="settings-subtabs" role="tablist" aria-label="設定カテゴリ">
        <button type="button" class="settings-subtab active" role="tab" aria-selected="true" tabindex="0" aria-controls="section-settings-engines" data-subtab="engines" id="subtab-engines-btn">検索エンジン管理</button>
        <button type="button" class="settings-subtab" role="tab" aria-selected="false" tabindex="-1" aria-controls="section-settings-general" data-subtab="general" id="subtab-general-btn">一般設定</button>
      </div>

      <!-- Section: Search Engines -->
      <div id="section-settings-engines" role="tabpanel" aria-labelledby="subtab-engines-btn">
        <div class="engine-toolbar">
          <div class="engine-search-wrap">
            <input type="text" id="engine-search-input" class="engine-search-input" placeholder="エンジン名やカテゴリーで絞り込み..." aria-label="検索エンジンの絞り込み">
          </div>
          <div class="engine-bulk-actions">
            <button type="button" class="btn btn-sm" id="btn-enable-all-cat">カテゴリー内を全有効化</button>
            <button type="button" class="btn btn-sm" id="btn-disable-all-cat">カテゴリー内を全無効化</button>
            <button type="button" class="btn btn-sm" id="btn-reset-engines-def">デフォルトに戻す</button>
            <button type="button" class="btn btn-primary btn-sm" id="btn-save-settings-engines">変更を保存</button>
          </div>
        </div>

        <div class="engines-category-chips" id="settings-engine-cat-chips"></div>
        <div class="engines-grid" id="settings-engines-grid"></div>
      </div>

      <!-- Section: General Preferences -->
      <div id="section-settings-general" role="tabpanel" aria-labelledby="subtab-general-btn" style="display:none;">
        <div class="general-settings-card">
          <div class="settings-row">
            <div class="settings-label-wrap">
              <h4><label for="pref-default-mode">デフォルト検索モード</label></h4>
              <p>検索トップ画面にアクセスした際、または外部から検索時の初期モード</p>
            </div>
            <div>
              <select id="pref-default-mode" class="opt-select" style="min-width:14rem;" aria-label="デフォルト検索モード">
                <option value="deep" selected>AI Deep Search (並列抽出 + BM25)</option>
                <option value="classic">Classic 検索 (軽量メタ検索)</option>
                <option value="balanced">Retrieval (Balanced グラウンディング)</option>
              </select>
            </div>
          </div>

          <div class="settings-row">
            <div class="settings-label-wrap">
              <h4><label for="pref-safesearch">セーフサーチ (SafeSearch)</label></h4>
              <p>成人向けコンテンツのフィルタリング設定</p>
            </div>
            <div>
              <select id="pref-safesearch" class="opt-select" style="min-width:14rem;" aria-label="セーフサーチ (SafeSearch)">
                <option value="0">無効 (Off)</option>
                <option value="1" selected>標準 (Moderate)</option>
                <option value="2">厳格 (Strict)</option>
              </select>
            </div>
          </div>

          <div class="settings-row">
            <div class="settings-label-wrap">
              <h4><label for="pref-autocomplete">サジェスト候補検索 (Autocomplete)</label></h4>
              <p>検索窓入力時にリアルタイムで検索キーワード候補を取得するエンジン</p>
            </div>
            <div>
              <select id="pref-autocomplete" class="opt-select" style="min-width:14rem;" aria-label="サジェスト候補検索 (Autocomplete)">
                <option value="duckduckgo" selected>DuckDuckGo (推奨・プライバシー保護)</option>
                <option value="google">Google (高精度・多言語)</option>
                <option value="brave">Brave Search</option>
                <option value="wikipedia">Wikipedia</option>
                <option value="off">無効 (オフ)</option>
              </select>
            </div>
          </div>

          <div class="settings-row">
            <div class="settings-label-wrap">
              <h4><label for="pref-default-count">デフォルト取得件数</label></h4>
              <p>検索時に各エンジンから集約・選抜する結果件数の標準値</p>
            </div>
            <div>
              <select id="pref-default-count" class="opt-select" style="min-width:14rem;" aria-label="デフォルト取得件数">
                <option value="5">5件</option>
                <option value="10" selected>10件</option>
                <option value="15">15件</option>
                <option value="20">20件</option>
              </select>
            </div>
          </div>

          <div class="settings-row">
            <div class="settings-label-wrap">
              <h4><label for="pref-default-tokens">トークン予算上限</label></h4>
              <p>AI Deep Search時にLLMへ渡すMarkdownコンテキストの上限</p>
            </div>
            <div>
              <select id="pref-default-tokens" class="opt-select" style="min-width:14rem;" aria-label="トークン予算上限">
                <option value="1500">1,500 tok</option>
                <option value="3000" selected>3,000 tok</option>
                <option value="6000">6,000 tok</option>
                <option value="10000">10,000 tok</option>
              </select>
            </div>
          </div>

          <div style="display:flex;justify-content:flex-end;gap:0.6rem;margin-top:0.5rem;">
            <button type="button" class="btn" id="btn-reset-general-prefs">初期値に戻す</button>
            <button type="button" class="btn btn-primary" id="btn-save-general-prefs">一般設定を保存</button>
          </div>
        </div>
      </div>
    </section>
  </main>

  <!-- Unsaved Changes Floating Bar -->
  <div id="unsaved-bar" class="unsaved-bar" role="status" aria-live="polite">
    <span class="unsaved-text">
      <svg class="ui-icon icon-amber" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z"></path><line x1="12" y1="9" x2="12" y2="13"></line><line x1="12" y1="17" x2="12.01" y2="17"></line></svg>
      未保存の設定変更があります
    </span>
    <button type="button" class="btn btn-sm" id="btn-discard-unsaved">変更を破棄</button>
    <button type="button" class="btn btn-primary btn-sm" id="btn-save-unsaved">変更を保存</button>
  </div>

  <div id="toast-notice" class="toast-notice" role="status" aria-live="polite"></div>

  <footer class="ws-footer">
    SearXNG for Windows Next — AI-First Dedicated Studio &middot;
    <a href="/healthz">Health (/healthz)</a> &middot;
    <a href="/api/ai_info">AI Info (/api/ai_info)</a> &middot;
    <a href="/api/settings/engines">Engines API</a>
  </footer>

  <script>
    (function () {
      'use strict';

      // Minimal SVG Icons (Zero-Dependency)
      var ICONS = {
        search: '<svg class="ui-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="11" cy="11" r="8"></circle><line x1="21" y1="21" x2="16.65" y2="16.65"></line></svg>',
        sparkles: '<svg class="ui-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m12 3-1.9 5.8a2 2 0 0 1-1.3 1.3L3 12l5.8 1.9a2 2 0 0 1 1.3 1.3L12 21l1.9-5.8a2 2 0 0 1 1.3-1.3L21 12l-5.8-1.9a2 2 0 0 1-1.3-1.3Z"></path></svg>',
        copy: '<svg class="ui-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect width="14" height="14" x="8" y="8" rx="2" ry="2"></rect><path d="M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2"></path></svg>',
        check: '<svg class="ui-icon icon-emerald" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><polyline points="20 6 9 17 4 12"></polyline></svg>',
        download: '<svg class="ui-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path><polyline points="7 10 12 15 17 10"></polyline><line x1="12" y1="15" x2="12" y2="3"></line></svg>',
        fileText: '<svg class="ui-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M14.5 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7.5L14.5 2z"></path><polyline points="14 2 14 8 20 8"></polyline><line x1="16" y1="13" x2="8" y2="13"></line><line x1="16" y1="17" x2="8" y2="17"></line></svg>',
        externalLink: '<svg class="ui-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"></path><polyline points="15 3 21 3 21 9"></polyline><line x1="10" y1="14" x2="21" y2="3"></line></svg>',
        alert: '<svg class="ui-icon icon-danger" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="10"></circle><line x1="12" y1="8" x2="12" y2="12"></line><line x1="12" y1="16" x2="12.01" y2="16"></line></svg>',
        warning: '<svg class="ui-icon icon-amber" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z"></path><line x1="12" y1="9" x2="12" y2="13"></line><line x1="12" y1="17" x2="12.01" y2="17"></line></svg>',
        clock: '<svg class="ui-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="10"></circle><polyline points="12 6 12 12 16 14"></polyline></svg>',
        sun: '<svg class="ui-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="4"></circle><path d="M12 2v2"></path><path d="M12 20v2"></path><path d="m4.93 4.93 1.41 1.41"></path><path d="m17.66 17.66 1.41 1.41"></path><path d="M2 12h2"></path><path d="M20 12h2"></path><path d="m6.34 17.66-1.41 1.41"></path><path d="m19.07 4.93-1.41 1.41"></path></svg>',
        moon: '<svg class="ui-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 3a6 6 0 0 0 9 9 9 9 0 1 1-9-9Z"></path></svg>',
        zap: '<svg class="ui-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"></polygon></svg>',
        play: '<svg class="ui-icon" viewBox="0 0 24 24" fill="currentColor" stroke="none" aria-hidden="true"><polygon points="6 3 20 12 6 21 6 3"></polygon></svg>',
        image: '<svg class="ui-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect width="18" height="18" x="3" y="3" rx="2" ry="2"></rect><circle cx="9" cy="9" r="2"></circle><path d="m21 15-3.086-3.086a2 2 0 0 0-2.828 0L6 21"></path></svg>'
      };

      function icon(name, extraClass) {
        var svg = ICONS[name] || '';
        if (extraClass && svg) {
          return svg.replace('class="ui-icon"', 'class="ui-icon ' + extraClass + '"');
        }
        return svg;
      }

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
        togglesModified: false,
        selectedCardIndex: -1
      };

      // AbortController for cancelable requests
      var currentAbortController = null;
      function cancelPendingRequest() {
        if (currentAbortController) {
          try { currentAbortController.abort(); } catch (e) {}
          currentAbortController = null;
        }
      }

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
        if (!/^https?:\/\//i.test(s)) return '#';
        try {
          var parsed = new URL(s);
          if (parsed.protocol === 'http:' || parsed.protocol === 'https:') {
            return parsed.href;
          }
        } catch (e) {}
        return '#';
      }

      function safeImageUrl(url) {
        var s = String(url == null ? '' : url).trim();
        if (!s) return '';
        if (/^data:image\/(?:png|jpeg|jpg|webp|gif);base64,[a-z0-9+/=]+$/i.test(s)) {
          return s;
        }
        var http = safeHttpUrl(s);
        return (http === '#') ? '' : http;
      }

      function escapeShellDoubleQuoted(str) {
        return String(str == null ? '' : str)
          .replace(/[\\$"\\`!]/g, function (ch) { return String.fromCharCode(92) + ch; });
      }

      function showToast(msg, isError) {
        var toast = document.getElementById('toast-notice');
        if (!toast) return;
        toast.innerHTML = (isError ? icon('alert') : icon('check')) + '<span>' + escapeHtml(msg) + '</span>';
        toast.style.background = isError ? 'var(--danger)' : 'var(--accent)';
        toast.classList.add('show');
        setTimeout(function () {
          toast.classList.remove('show');
        }, 2400);
      }

      function addListener(id, event, fn) {
        var el = document.getElementById(id);
        if (el) el.addEventListener(event, fn);
      }

      // Theme initialization
      var savedTheme = localStorage.getItem('sxng_ai_theme') || 'dark';
      document.documentElement.setAttribute('data-theme', savedTheme);
      function updateThemeIcon(t) {
        var btn = document.getElementById('theme-toggle-btn');
        if (!btn) return;
        var isDark = (t === 'dark');
        btn.innerHTML = (isDark ? icon('sun') : icon('moon')) + '<span>' + (isDark ? 'ライト' : 'ダーク') + '</span>';
      }
      updateThemeIcon(savedTheme);

      addListener('theme-toggle-btn', 'click', function () {
        var cur = document.documentElement.getAttribute('data-theme') === 'light' ? 'dark' : 'light';
        document.documentElement.setAttribute('data-theme', cur);
        localStorage.setItem('sxng_ai_theme', cur);
        updateThemeIcon(cur);
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
        return /^https?:\/\/\S+$/i.test(s);
      }

      function estimateTokens(text) {
        if (!text) return 0;
        var cjk = (text.match(/[\u3000-\u303f\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uff00-\uffef]/g) || []).length;
        var other = text.length - cjk;
        return Math.round(cjk / 1.5 + other / 4.0);
      }

      function copyWithFeedback(text, btn, label) {
        if (!text) return;
        var orig = btn.innerHTML;
        var done = function () {
          btn.innerHTML = icon('check') + '<span>' + (label || 'コピー完了') + '</span>';
          setTimeout(function () { btn.innerHTML = orig; }, 1600);
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

      /* -------------------------------------------------------------
       * URL & Browser History Synchronization (pushState / popstate)
       * ------------------------------------------------------------- */
      function updateUrlState(replace) {
        var params = new URLSearchParams();
        var qVal = document.getElementById('q').value.trim();
        if (qVal) params.set('q', qVal);
        if (state.mode && state.mode !== 'deep') params.set('mode', state.mode);
        if (state.mode === 'deep') {
          var depth = document.getElementById('opt-depth').value;
          if (depth && depth !== 'advanced') params.set('depth', depth);
        } else if (state.mode === 'classic') {
          if (state.classicCategory) params.set('category', state.classicCategory);
          if (state.classicPage > 1) params.set('page', String(state.classicPage));
        }

        var qs = params.toString();
        var targetUrl = qs ? '/?' + qs : '/';
        var currentSearch = window.location.search || '';
        var targetSearch = qs ? '?' + qs : '';

        if (currentSearch !== targetSearch) {
          if (replace) {
            history.replaceState({ q: qVal, mode: state.mode, cat: state.classicCategory, page: state.classicPage }, '', targetUrl);
          } else {
            history.pushState({ q: qVal, mode: state.mode, cat: state.classicCategory, page: state.classicPage }, '', targetUrl);
          }
        }
      }

      window.addEventListener('popstate', function () {
        var p = new URLSearchParams(window.location.search);
        var q = p.get('q') || '';
        var m = p.get('mode') || 'deep';
        var cat = p.get('category') || p.get('categories') || '';
        var pg = parseInt(p.get('page') || '1', 10) || 1;
        var depth = p.get('depth') || 'advanced';

        document.getElementById('q').value = q;
        document.getElementById('opt-depth').value = depth;
        state.classicCategory = cat;
        state.classicPage = pg;

        document.querySelectorAll('#classic-cat-chips .cat-btn').forEach(function (b) {
          var active = (b.dataset.cat === cat);
          b.classList.toggle('active', active);
          b.setAttribute('aria-pressed', active ? 'true' : 'false');
        });

        setMode(m, true);
        if (q) {
          if (isUrlText(q)) runScrapeMode(q);
          else if (m === 'classic') runClassicSearch(q, pg);
          else runUnifiedSearch(q);
        }
      });

      /* -------------------------------------------------------------
       * Search History Management (localStorage)
       * ------------------------------------------------------------- */
      var HISTORY_STORAGE_KEY = 'sxng_query_history';
      function getQueryHistory() {
        try {
          return JSON.parse(localStorage.getItem(HISTORY_STORAGE_KEY) || '[]');
        } catch (e) {
          return [];
        }
      }
      function saveQueryHistory(query) {
        var q = (query || '').trim();
        if (!q || isUrlText(q)) return;
        var hist = getQueryHistory().filter(function (item) { return item !== q; });
        hist.unshift(q);
        if (hist.length > 8) hist = hist.slice(0, 8);
        try { localStorage.setItem(HISTORY_STORAGE_KEY, JSON.stringify(hist)); } catch (e) {}
        renderQueryHistory();
      }
      function renderQueryHistory() {
        var wrap = document.getElementById('recent-searches-wrap');
        if (!wrap) return;
        var hist = getQueryHistory();
        if (!hist.length) {
          wrap.style.display = 'none';
          wrap.innerHTML = '';
          return;
        }
        wrap.style.display = 'flex';
        wrap.innerHTML = '<span class="recent-label">' + icon('clock') + ' 最近の検索:</span>';
        hist.forEach(function (term) {
          var chip = document.createElement('button');
          chip.type = 'button';
          chip.className = 'recent-chip';
          chip.textContent = term;
          chip.addEventListener('click', function () {
            document.getElementById('q').value = term;
            executeCurrentAction();
          });
          wrap.appendChild(chip);
        });
        var clearBtn = document.createElement('button');
        clearBtn.type = 'button';
        clearBtn.className = 'recent-clear-btn';
        clearBtn.textContent = '履歴クリア';
        clearBtn.addEventListener('click', function () {
          localStorage.removeItem(HISTORY_STORAGE_KEY);
          renderQueryHistory();
        });
        wrap.appendChild(clearBtn);
      }
      renderQueryHistory();

      /* -------------------------------------------------------------
       * Autocompleter Suggest Dropdown (/autocompleter)
       * ------------------------------------------------------------- */
      var suggestBox = document.getElementById('suggest-box');
      var suggestDebounceTimer = null;
      var activeSuggestIndex = -1;

      function closeSuggest() {
        suggestBox.classList.remove('show');
        suggestBox.innerHTML = '';
        activeSuggestIndex = -1;
        var qEl = document.getElementById('q');
        if (qEl) {
          qEl.setAttribute('aria-expanded', 'false');
          qEl.removeAttribute('aria-activedescendant');
        }
      }

      function setActiveSuggestAria() {
        var qEl = document.getElementById('q');
        if (!qEl) return;
        qEl.setAttribute('aria-expanded', 'true');
        if (activeSuggestIndex >= 0) {
          var items = suggestBox.querySelectorAll('.suggest-item');
          if (items[activeSuggestIndex]) {
            qEl.setAttribute('aria-activedescendant', items[activeSuggestIndex].id);
          }
        } else {
          qEl.removeAttribute('aria-activedescendant');
        }
      }

      function extractSuggestions(data) {
        if (!data) return [];
        var raw = [];
        if (Array.isArray(data)) {
          // OpenSearch 5-tuple format: [query, [sug1, sug2, ...], ...]
          if (data.length >= 2 && Array.isArray(data[1])) {
            raw = data[1];
          } else {
            // Flat list format: [sug1, sug2, ...]
            raw = data;
          }
        } else if (typeof data === 'object' && Array.isArray(data.suggestions)) {
          raw = data.suggestions;
        }

        var results = [];
        var seen = Object.create(null);
        for (var i = 0; i < raw.length; i++) {
          var item = raw[i];
          if (typeof item === 'string') {
            var trimmed = item.trim();
            if (trimmed && trimmed !== '[object Object]' && !seen[trimmed]) {
              seen[trimmed] = true;
              results.push(trimmed);
            }
          }
        }
        return results;
      }

      function getActiveAutocompleteBackend() {
        var ac = localStorage.getItem('sxng_pref_autocomplete');
        if (ac) return ac;
        var sel = document.getElementById('pref-autocomplete');
        return sel ? sel.value : 'duckduckgo';
      }

      function fetchSuggestions(query) {
        if (!query || query.length < 2 || isUrlText(query) || getActiveAutocompleteBackend() === 'off') {
          closeSuggest();
          return;
        }
        fetch('/autocompleter?q=' + encodeURIComponent(query), {
          headers: {
            'X-Requested-With': 'XMLHttpRequest',
            'Accept': 'application/json'
          }
        })
          .then(function (r) { return r.json(); })
          .then(function (data) {
            var curQ = document.getElementById('q').value.trim();
            if (!curQ || isUrlText(curQ)) {
              closeSuggest();
              return;
            }
            var list = extractSuggestions(data);
            if (!list.length) {
              closeSuggest();
              return;
            }
            suggestBox.innerHTML = '';
            activeSuggestIndex = -1;
            list.slice(0, 8).forEach(function (item, idx) {
              var div = document.createElement('div');
              div.className = 'suggest-item';
              div.setAttribute('role', 'option');
              div.id = 'suggest-opt-' + idx;
              div.setAttribute('aria-selected', 'false');
              div.innerHTML = icon('search') + '<span>' + escapeHtml(item) + '</span>';
              div.addEventListener('mousedown', function (e) {
                e.preventDefault();
                document.getElementById('q').value = item;
                closeSuggest();
                executeCurrentAction();
              });
              suggestBox.appendChild(div);
            });
            suggestBox.classList.add('show');
            setActiveSuggestAria();
          })
          .catch(function () { closeSuggest(); });
      }

      document.getElementById('q').addEventListener('input', function () {
        var val = this.value.trim();
        syncInputOptionsVisibility();
        clearTimeout(suggestDebounceTimer);
        suggestDebounceTimer = setTimeout(function () {
          fetchSuggestions(val);
        }, 180);
      });

      document.getElementById('q').addEventListener('keydown', function (e) {
        if (e.isComposing || e.keyCode === 229) return;
        var items = suggestBox.querySelectorAll('.suggest-item');
        if (!items.length || !suggestBox.classList.contains('show')) return;

        if (e.key === 'ArrowDown') {
          e.preventDefault();
          activeSuggestIndex = (activeSuggestIndex + 1) % items.length;
          items.forEach(function (el, i) {
            el.classList.toggle('active', i === activeSuggestIndex);
            el.setAttribute('aria-selected', i === activeSuggestIndex ? 'true' : 'false');
          });
          var selText = items[activeSuggestIndex].querySelector('span').textContent;
          document.getElementById('q').value = selText;
          setActiveSuggestAria();
        } else if (e.key === 'ArrowUp') {
          e.preventDefault();
          activeSuggestIndex = (activeSuggestIndex - 1 + items.length) % items.length;
          items.forEach(function (el, i) {
            el.classList.toggle('active', i === activeSuggestIndex);
            el.setAttribute('aria-selected', i === activeSuggestIndex ? 'true' : 'false');
          });
          var selText2 = items[activeSuggestIndex].querySelector('span').textContent;
          document.getElementById('q').value = selText2;
          setActiveSuggestAria();
        } else if (e.key === 'Enter') {
          if (activeSuggestIndex >= 0 && items[activeSuggestIndex]) {
            e.preventDefault();
            var chosen = items[activeSuggestIndex].querySelector('span').textContent;
            document.getElementById('q').value = chosen;
            closeSuggest();
            executeCurrentAction();
          }
        } else if (e.key === 'Escape') {
          closeSuggest();
        }
      });

      document.addEventListener('click', function (e) {
        if (!document.getElementById('ws-form').contains(e.target)) {
          closeSuggest();
        }
      });

      /* -------------------------------------------------------------
       * UI Mode & Visibility Sync
       * ------------------------------------------------------------- */
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
          runBtn.innerHTML = icon('fileText') + '<span>URL 本文抽出</span>';
        } else if (state.mode === 'classic') {
          searchOpts.style.display = 'none';
          classicOpts.style.display = 'flex';
          scrapeOpts.style.display = 'none';
          runBtn.innerHTML = icon('search') + '<span>検索</span>';
        } else {
          searchOpts.style.display = 'flex';
          classicOpts.style.display = 'none';
          scrapeOpts.style.display = 'none';
          var depthVal = document.getElementById('opt-depth').value;
          runBtn.innerHTML = (depthVal === 'fast')
            ? (icon('zap') + '<span>Fast Search</span>')
            : (icon('sparkles') + '<span>Deep Search</span>');
        }
      }

      function setMode(mode) {
        var skipHistory = arguments[1];
        state.mode = mode;
        state.selectedCardIndex = -1;
        document.querySelectorAll('.nav-tab').forEach(function (t) {
          var isSelected = (t.dataset.mode === mode);
          t.classList.toggle('active', isSelected);
          t.setAttribute('aria-selected', isSelected ? 'true' : 'false');
          t.setAttribute('tabindex', isSelected ? '0' : '-1');
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

        if (!skipHistory) {
          updateUrlState(false);
        }
      }

      document.getElementById('opt-depth').addEventListener('change', function () {
        syncInputOptionsVisibility();
        updateUrlState(true);
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
          document.querySelectorAll('#classic-cat-chips .cat-btn').forEach(function (b) {
            b.classList.remove('active');
            b.setAttribute('aria-pressed', 'false');
          });
          btn.classList.add('active');
          btn.setAttribute('aria-pressed', 'true');
          state.classicCategory = btn.dataset.cat || '';
          state.classicPage = 1;
          var qVal = document.getElementById('q').value.trim();
          if (qVal) {
            runClassicSearch(qVal, 1);
            updateUrlState(false);
          }
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

      /* -------------------------------------------------------------
       * Lightweight Vanilla Markdown Preview Renderer
       * ------------------------------------------------------------- */
      function renderSimpleMarkdown(md) {
        if (!md) return '<p style="color:var(--text-muted);">(コンテキストが空です)</p>';
        var text = escapeHtml(md).replace(/\r\n/g, '\n');

        // 1. Extract fenced code blocks with unique tokens
        var codeBlocks = [];
        text = text.replace(/```([a-zA-Z0-9_-]*)\n([\s\S]*?)```/g, function (_, lang, code) {
          var token = '@@CODE_BLOCK_' + codeBlocks.length + '@@';
          codeBlocks.push('<pre><code class="lang-' + lang + '">' + code + '</code></pre>');
          return '\n\n' + token + '\n\n';
        });

        // 2. Extract inline code with tokens
        var inlineCodes = [];
        text = text.replace(/`([^`]+)`/g, function (_, code) {
          var token = '@@INLINE_CODE_' + inlineCodes.length + '@@';
          inlineCodes.push('<code>' + code + '</code>');
          return token;
        });

        // 3. Process blocks (split by double newlines)
        var rawBlocks = text.split(/\n{2,}/);
        var htmlBlocks = [];

        for (var i = 0; i < rawBlocks.length; i++) {
          var block = rawBlocks[i].trim();
          if (!block) continue;

          // Check if block is a preserved code block token
          if (/^@@CODE_BLOCK_\d+@@$/.test(block)) {
            htmlBlocks.push(block);
            continue;
          }

          // Check if block is heading
          if (/^### (.*$)/.test(block)) {
            htmlBlocks.push(block.replace(/^### (.*$)/, '<h3>$1</h3>'));
            continue;
          }
          if (/^## (.*$)/.test(block)) {
            htmlBlocks.push(block.replace(/^## (.*$)/, '<h2>$1</h2>'));
            continue;
          }
          if (/^# (.*$)/.test(block)) {
            htmlBlocks.push(block.replace(/^# (.*$)/, '<h1>$1</h1>'));
            continue;
          }

          // Check if block is blockquote
          if (/^&gt; (.*$)/m.test(block)) {
            var bqLines = block.split(/\n/).map(function (line) {
              return line.replace(/^&gt;\s?/, '');
            });
            htmlBlocks.push('<blockquote>' + bqLines.join('<br>') + '</blockquote>');
            continue;
          }

          // Check if block is an unordered list (lines starting with - or *)
          var lines = block.split(/\n/);
          var isList = lines.length > 0 && lines.every(function (l) { return /^[\-\*]\s+/.test(l.trim()); });
          if (isList) {
            var listItems = lines.map(function (l) {
              return '<li>' + l.trim().replace(/^[\-\*]\s+/, '') + '</li>';
            });
            htmlBlocks.push('<ul>' + listItems.join('') + '</ul>');
            continue;
          }

          // Regular paragraph: replace single newlines with <br>
          htmlBlocks.push('<p>' + block.replace(/\n/g, '<br>') + '</p>');
        }

        var fullHtml = htmlBlocks.join('\n');

        // 4. Bold & Italic (applied outside code blocks)
        fullHtml = fullHtml.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
        fullHtml = fullHtml.replace(/\*([^*]+)\*/g, '<em>$1</em>');

        // 5. Links (handles escaped brackets in titles from escape_markdown_link)
        fullHtml = fullHtml.replace(/\[((?:\\\]|[^\]])+)\]\((https?:\/\/[^\s\)\"\']+)\)/g, function (_, label, rawUrl) {
          var cleanUrl = safeHttpUrl(rawUrl.replace(/&amp;/g, '&'));
          var displayLabel = label.replace(/\\([\[\]])/g, '$1');
          if (cleanUrl === '#') {
            return displayLabel;
          }
          return '<a href="' + escapeHtml(cleanUrl) + '" target="_blank" rel="noopener noreferrer">' + displayLabel + '</a>';
        });

        // 6. Restore code blocks and inline code (using function return to prevent $ pattern interpretation)
        for (var k = 0; k < codeBlocks.length; k++) {
          fullHtml = fullHtml.replace('@@CODE_BLOCK_' + k + '@@', function () { return codeBlocks[k]; });
        }
        for (var j = 0; j < inlineCodes.length; j++) {
          fullHtml = fullHtml.replace('@@INLINE_CODE_' + j + '@@', function () { return inlineCodes[j]; });
        }

        return fullHtml;
      }

      function updateContextView() {
        var ta = document.getElementById('ctx-output');
        var prev = document.getElementById('ctx-preview');

        if (state.ctxTab === 'preview') {
          ta.style.display = 'none';
          prev.style.display = 'block';
          prev.innerHTML = renderSimpleMarkdown(state.markdown || state.prompt || '');
        } else {
          prev.style.display = 'none';
          ta.style.display = 'block';
          if (state.ctxTab === 'markdown') ta.value = state.markdown || '';
          else if (state.ctxTab === 'prompt') ta.value = state.prompt || '';
          else if (state.ctxTab === 'json') ta.value = state.jsonStr || '';
          else if (state.ctxTab === 'curl') ta.value = state.curlStr || '';
        }

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
          t.setAttribute('tabindex', isSelected ? '0' : '-1');
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
        var val = (state.ctxTab === 'preview' || state.ctxTab === 'markdown') ? state.markdown : document.getElementById('ctx-output').value;
        copyWithFeedback(val, this, 'コピー完了');
      });
      document.getElementById('copy-md-main').addEventListener('click', function () {
        copyWithFeedback(state.markdown, this, 'Markdownコピー済');
      });
      document.getElementById('copy-prompt-main').addEventListener('click', function () {
        copyWithFeedback(state.prompt, this, 'プロンプトコピー済');
      });
      document.getElementById('copy-json-main').addEventListener('click', function () {
        copyWithFeedback(state.jsonStr, this, 'JSONコピー済');
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

      /* -------------------------------------------------------------
       * Skeleton Loader Renderer
       * ------------------------------------------------------------- */
      function renderSkeletonCards(container, count) {
        container.innerHTML = '';
        container.setAttribute('aria-busy', 'true');
        for (var i = 0; i < (count || 4); i++) {
          var card = document.createElement('div');
          card.className = 'skeleton-card';
          card.innerHTML =
            '<div class="skeleton-line meta"></div>' +
            '<div class="skeleton-line title"></div>' +
            '<div class="skeleton-line body1"></div>' +
            '<div class="skeleton-line body2"></div>';
          container.appendChild(card);
        }
      }

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

      /* -------------------------------------------------------------
       * Deep Search Mode Result Cards
       * ------------------------------------------------------------- */
      function renderSearchResults(items, query) {
        var container = document.getElementById('results-container');
        container.innerHTML = '';
        state.selectedCardIndex = -1;

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
          card.dataset.index = String(idx);

          var top = document.createElement('div');
          top.className = 'card-top';

          var leftMeta = document.createElement('div');
          leftMeta.style.display = 'flex';
          leftMeta.style.alignItems = 'center';
          leftMeta.style.gap = '0.5rem';

          var rankSpan = document.createElement('span');
          rankSpan.className = 'card-rank';
          rankSpan.textContent = '[' + (idx + 1) + ']';

          var domainWrap = document.createElement('span');
          domainWrap.className = 'card-domain-wrap';

          var domain = item.domain || (function () {
            try { return new URL(item.url).hostname.replace(/^www\./, ''); } catch (e) { return ''; }
          })();

          if (domain) {
            var fav = document.createElement('img');
            fav.className = 'card-favicon';
            fav.src = 'https://www.google.com/s2/favicons?domain=' + encodeURIComponent(domain) + '&sz=32';
            fav.alt = '';
            fav.loading = 'lazy';
            fav.onerror = function () { this.style.display = 'none'; };
            domainWrap.appendChild(fav);
          }

          var domSpan = document.createElement('span');
          domSpan.className = 'card-domain';
          domSpan.textContent = domain;
          domainWrap.appendChild(domSpan);

          leftMeta.appendChild(rankSpan);
          leftMeta.appendChild(domainWrap);

          var badges = document.createElement('div');
          badges.className = 'card-badges';

          if (typeof item.score === 'number' && item.score > 0) {
            var scorePill = document.createElement('span');
            scorePill.className = 'pill ' + (item.score >= 1.5 ? 'pill-emerald' : 'pill-accent');
            scorePill.textContent = 'Score ' + item.score.toFixed(2);
            badges.appendChild(scorePill);
          }
          if (item.is_scraped) {
            var scPill = document.createElement('span');
            scPill.className = 'pill pill-emerald';
            scPill.innerHTML = icon('check', 'ui-icon-sm') + '<span>本文抽出済</span>';
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

          var drawerId = 'deep-scrape-drawer-' + idx;
          var scrapeBtn = document.createElement('button');
          scrapeBtn.type = 'button';
          scrapeBtn.className = 'btn btn-sm';
          scrapeBtn.innerHTML = icon('fileText') + '<span>本文抽出</span>';
          scrapeBtn.setAttribute('aria-expanded', 'false');
          scrapeBtn.setAttribute('aria-controls', drawerId);
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
            drawer.id = drawerId;
            drawer.innerHTML = '<span class="ui-spinner"></span> URLから本文を抽出中...';
            card.appendChild(drawer);
            scrapeBtn.setAttribute('aria-expanded', 'true');
            fetch('/api/scrape_analyze?url=' + encodeURIComponent(item.url) + '&q=' + encodeURIComponent(query || ''))
              .then(function (r) { return r.json(); })
              .then(function (res) {
                if (res.error) {
                  drawer.innerHTML = icon('alert') + ' 抽出失敗: ' + escapeHtml(res.error);
                  return;
                }
                drawer.textContent = res.content || '(本文なし)';
              })
              .catch(function (e) {
                drawer.innerHTML = icon('alert') + ' 通信エラー: ' + escapeHtml(e);
              });
          });

          var copyItemBtn = document.createElement('button');
          copyItemBtn.type = 'button';
          copyItemBtn.className = 'btn btn-sm';
          copyItemBtn.setAttribute('aria-label', '引用をコピー');
          copyItemBtn.setAttribute('data-action', 'copy-citation');
          copyItemBtn.innerHTML = icon('copy') + '<span>引用コピー</span>';
          copyItemBtn.addEventListener('click', function () {
            var safeTitle = (item.title || item.url || '').split('[').join('\\[').split(']').join('\\]');
            var safeUrl = (item.url || '').split('(').join('%28').split(')').join('%29');
            var hText = (item.highlights && item.highlights.length) ? item.highlights.join('\n\n') : (item.content || '');
            var citeMd = '### [' + (idx + 1) + '] [' + safeTitle + '](' + safeUrl + ')\n> ' + hText.replace(/\n/g, '\n> ');
            copyWithFeedback(citeMd, copyItemBtn, 'コピー完了');
          });

          actions.appendChild(scrapeBtn);
          actions.appendChild(copyItemBtn);

          if (domain) {
            var filterDomBtn = document.createElement('button');
            filterDomBtn.type = 'button';
            filterDomBtn.className = 'btn btn-sm';
            filterDomBtn.textContent = 'site:' + domain;
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
        cancelPendingRequest();
        currentAbortController = new AbortController();
        var signal = currentAbortController.signal;

        var depth = document.getElementById('opt-depth').value;
        var count = document.getElementById('opt-count').value;
        var maxTok = parseInt(document.getElementById('opt-tokens').value, 10) || 3000;
        var siteVal = document.getElementById('opt-site').value.trim();
        state.maxTokens = maxTok;

        var container = document.getElementById('results-container');
        renderSkeletonCards(container, parseInt(count, 10) || 4);

        saveQueryHistory(query);
        closeSuggest();

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

        fetch(url, { signal: signal })
          .then(function (r) { return r.json(); })
          .then(function (res) {
            container.setAttribute('aria-busy', 'false');
            var telBar = document.getElementById('telemetry-bar');
            if (res.error && (!res.results || !res.results.length)) {
              if (telBar) telBar.classList.remove('visible');
              container.innerHTML = '<div class="empty-state"><h2 style="color:var(--danger);">' + icon('alert') + ' エラー</h2><p>' + escapeHtml(res.error) + '</p></div>';
              return;
            }
            state.markdown = res.markdown || '';
            state.prompt = res.rag_prompt || '';
            state.jsonStr = JSON.stringify(res, null, 2);

            var badges = document.getElementById('telemetry-badges');
            if (telBar) telBar.classList.add('visible');
            if (badges) {
              badges.innerHTML =
                '<span class="pill pill-accent">' + escapeHtml(res.search_depth || depth) + ' (' + escapeHtml(res.intent || 'general') + ')</span>' +
                '<span class="pill pill-emerald">' + escapeHtml(res.results_count || 0) + '件 (本文抽出: ' + escapeHtml(res.scraped_count || 0) + '件)</span>' +
                '<span class="pill">~' + escapeHtml(res.estimated_tokens || 0) + ' tokens</span>' +
                '<span class="pill">' + escapeHtml(res.elapsed_ms || 0) + ' ms</span>';
            }

            renderSearchResults(res.results || [], query);
            updateContextView();
            updateUrlState(false);
          })
          .catch(function (err) {
            if (err.name === 'AbortError') return;
            container.setAttribute('aria-busy', 'false');
            var telBar = document.getElementById('telemetry-bar');
            if (telBar) telBar.classList.remove('visible');
            container.innerHTML = '<div class="empty-state"><h2 style="color:var(--danger);">' + icon('alert') + ' 通信エラー</h2><p>' + escapeHtml(err) + '</p></div>';
          });
      }

      /* -------------------------------------------------------------
       * Classic Search Mode Implementation (Text & Image Gallery)
       * ------------------------------------------------------------- */
      function updateClassicPagination(page, items) {
        var pagBar = document.getElementById('classic-pagination-bar');
        if (!pagBar) return;
        pagBar.style.display = 'flex';
        var countVal = parseInt((document.getElementById('classic-count') || {}).value || '10', 10);
        if (isNaN(countVal) || countVal < 1) countVal = 10;
        var maxPages = 10;
        var isLastPage = (items.length < countVal);
        var totalPages = isLastPage ? Math.max(page, 1) : Math.max(page, maxPages);

        var indicator = document.getElementById('classic-page-indicator');
        if (indicator) {
          indicator.textContent = 'ページ ' + page + ' / ' + totalPages;
        }

        var prevBtn = document.getElementById('classic-prev-btn');
        if (prevBtn) prevBtn.disabled = (page <= 1);
        var nextBtn = document.getElementById('classic-next-btn');
        if (nextBtn) document.getElementById('classic-next-btn').disabled = (items.length < countVal) || (page >= totalPages);
      }

      function renderClassicSearchResults(items, query, page) {
        var container = document.getElementById('classic-results-container');
        container.innerHTML = '';
        state.selectedCardIndex = -1;

        if (!items || !items.length) {
          container.innerHTML = '<div class="empty-state"><h2>検索結果が見つかりませんでした</h2><p>キーワードを変更するか、カテゴリーフィルターを切り替えてみてください。</p></div>';
          document.getElementById('classic-pagination-bar').style.display = 'none';
          return;
        }

        // Image grid mode
        if (state.classicCategory === 'images') {
          var grid = document.createElement('div');
          grid.className = 'image-results-grid';
          items.forEach(function (item) {
            var card = document.createElement('article');
            card.className = 'image-card';

            var thumbWrap = document.createElement('a');
            thumbWrap.className = 'image-card-thumb-wrap';
            thumbWrap.href = safeHttpUrl(item.url);
            thumbWrap.target = '_blank';
            thumbWrap.rel = 'noopener noreferrer';
            thumbWrap.title = item.title || '';

            var thumbSrc = item.thumbnail_src || item.thumbnail;
            var fullSrc = item.img_src || thumbSrc;
            var displaySrc = thumbSrc || fullSrc;

            if (displaySrc) {
              var safeSrc = safeImageUrl(displaySrc);
              if (safeSrc) {
                var img = document.createElement('img');
                img.className = 'image-card-thumb';
                img.src = safeSrc;
                img.alt = item.title || '';
                img.loading = 'lazy';
                img.referrerPolicy = 'no-referrer';
                img.onerror = function () {
                  if (fullSrc && safeSrc !== safeImageUrl(fullSrc)) {
                    this.src = safeImageUrl(fullSrc);
                  } else {
                    this.style.display = 'none';
                    if (!thumbWrap.querySelector('.image-card-placeholder')) {
                      var ph = document.createElement('div');
                      ph.className = 'image-card-placeholder';
                      ph.innerHTML = icon('image') + '<span>画像を表示できません</span>';
                      thumbWrap.appendChild(ph);
                    }
                  }
                };
                thumbWrap.appendChild(img);
              }
            } else {
              var ph = document.createElement('div');
              ph.className = 'image-card-placeholder';
              ph.innerHTML = icon('image') + '<span>画像プレビューなし</span>';
              thumbWrap.appendChild(ph);
            }

            if (item.resolution) {
              var resBadge = document.createElement('span');
              resBadge.className = 'image-res-badge';
              resBadge.textContent = item.resolution;
              thumbWrap.appendChild(resBadge);
            }

            var body = document.createElement('div');
            body.className = 'image-card-body';

            var a = document.createElement('a');
            a.className = 'image-card-title';
            a.href = safeHttpUrl(item.url);
            a.target = '_blank';
            a.rel = 'noopener noreferrer';
            a.textContent = item.title || item.url;

            var domRow = document.createElement('div');
            domRow.className = 'image-card-meta';

            var dom = document.createElement('span');
            dom.className = 'image-card-domain';
            dom.textContent = item.domain || (function () {
              try { return new URL(item.url).hostname.replace(/^www\./, ''); } catch (e) { return ''; }
            })();

            domRow.appendChild(dom);

            if (item.img_src) {
              var fullLink = document.createElement('a');
              fullLink.className = 'image-full-link';
              fullLink.href = safeHttpUrl(item.img_src);
              fullLink.target = '_blank';
              fullLink.rel = 'noopener noreferrer';
              fullLink.title = '元画像を別タブで開く';
              fullLink.setAttribute('aria-label', '元画像を別タブで開く');
              fullLink.innerHTML = icon('externalLink');
              domRow.appendChild(fullLink);
            }

            body.appendChild(a);
            body.appendChild(domRow);

            card.appendChild(thumbWrap);
            card.appendChild(body);
            grid.appendChild(card);
          });
          container.appendChild(grid);

          updateClassicPagination(page, items);
          return;
        }

        // Dedicated Video list mode
        if (state.classicCategory === 'videos') {
          var vList = document.createElement('div');
          vList.className = 'video-results-list';
          items.forEach(function (item, idx) {
            var card = document.createElement('article');
            card.className = 'video-card';
            card.dataset.index = String(idx);

            var thumbWrap = document.createElement('a');
            thumbWrap.className = 'video-thumb-wrap';
            thumbWrap.href = safeHttpUrl(item.url);
            thumbWrap.target = '_blank';
            thumbWrap.rel = 'noopener noreferrer';
            thumbWrap.title = item.title || '';

            var videoThumb = item.thumbnail || item.thumbnail_src || item.img_src;
            if (!videoThumb) {
              var yt = (item.url || '').match(/(?:youtube\.com\/(?:watch\?v=|shorts\/)|youtu\.be\/)([a-zA-Z0-9_-]{11})/);
              if (yt) videoThumb = 'https://i.ytimg.com/vi/' + yt[1] + '/hqdefault.jpg';
            }

            if (videoThumb) {
              var safeSrc = safeImageUrl(videoThumb);
              if (safeSrc) {
                var img = document.createElement('img');
                img.className = 'video-thumb-img';
                img.src = safeSrc;
                img.alt = item.title || '';
                img.loading = 'lazy';
                img.referrerPolicy = 'no-referrer';
                img.onerror = function () {
                  this.style.display = 'none';
                  if (!thumbWrap.querySelector('.video-thumb-placeholder')) {
                    var ph = document.createElement('div');
                    ph.className = 'video-thumb-placeholder';
                    ph.innerHTML = icon('play') + '<span>動画プレビュー</span>';
                    thumbWrap.appendChild(ph);
                  }
                };
                thumbWrap.appendChild(img);
              }
            } else {
              var ph = document.createElement('div');
              ph.className = 'video-thumb-placeholder';
              ph.innerHTML = icon('play') + '<span>動画</span>';
              thumbWrap.appendChild(ph);
            }

            var playOverlay = document.createElement('div');
            playOverlay.className = 'video-play-overlay';
            playOverlay.innerHTML = icon('play');
            thumbWrap.appendChild(playOverlay);

            if (item.length) {
              var durBadge = document.createElement('span');
              durBadge.className = 'video-duration-badge';
              durBadge.textContent = item.length;
              thumbWrap.appendChild(durBadge);
            }

            var contentDiv = document.createElement('div');
            contentDiv.className = 'video-card-content';

            var metaRow = document.createElement('div');
            metaRow.className = 'classic-meta-row';

            var urlSpan = document.createElement('span');
            urlSpan.className = 'classic-url-tag';
            var domain = item.domain || (function () {
              try { return new URL(item.url).hostname.replace(/^www\./, ''); } catch (e) { return ''; }
            })();
            if (domain) {
              var fav = document.createElement('img');
              fav.className = 'card-favicon';
              fav.src = 'https://www.google.com/s2/favicons?domain=' + encodeURIComponent(domain) + '&sz=32';
              fav.alt = '';
              fav.loading = 'lazy';
              fav.onerror = function () { this.style.display = 'none'; };
              urlSpan.appendChild(fav);
            }
            var dName = document.createElement('span');
            dName.textContent = domain || item.url;
            urlSpan.appendChild(dName);

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
            contentDiv.appendChild(metaRow);

            var titleLink = document.createElement('a');
            titleLink.className = 'video-title-link';
            titleLink.href = safeHttpUrl(item.url);
            titleLink.target = '_blank';
            titleLink.rel = 'noopener noreferrer';
            titleLink.textContent = item.title || item.url;
            contentDiv.appendChild(titleLink);

            if (item.content) {
              var descDiv = document.createElement('div');
              descDiv.className = 'video-snippet-text';
              descDiv.textContent = item.content;
              contentDiv.appendChild(descDiv);
            }

            var actRow = document.createElement('div');
            actRow.className = 'classic-actions-row';

            var watchBtn = document.createElement('a');
            watchBtn.className = 'btn btn-sm btn-primary';
            watchBtn.href = safeHttpUrl(item.url);
            watchBtn.target = '_blank';
            watchBtn.rel = 'noopener noreferrer';
            watchBtn.setAttribute('aria-label', '動画を新しいタブで再生');
            watchBtn.innerHTML = icon('play') + '<span>動画を再生</span>';
            actRow.appendChild(watchBtn);

            var copyBtn = document.createElement('button');
            copyBtn.type = 'button';
            copyBtn.className = 'btn btn-sm';
            copyBtn.setAttribute('aria-label', '動画URLをコピー');
            copyBtn.setAttribute('data-action', 'copy-citation');
            copyBtn.innerHTML = icon('copy') + '<span>URLコピー</span>';
            copyBtn.addEventListener('click', function () {
              var safeTitle = (item.title || item.url || '').split('[').join('\\[').split(']').join('\\]');
              var safeUrl = (item.url || '').split('(').join('%28').split(')').join('%29');
              var citeText = '[' + safeTitle + '](' + safeUrl + ')';
              copyWithFeedback(citeText, copyBtn, 'コピー済');
            });
            actRow.appendChild(copyBtn);

            contentDiv.appendChild(actRow);

            card.appendChild(thumbWrap);
            card.appendChild(contentDiv);
            vList.appendChild(card);
          });
          container.appendChild(vList);

          updateClassicPagination(page, items);
          return;
        }

        // Standard 1-column list
        items.forEach(function (item, idx) {
          var card = document.createElement('article');
          card.className = 'classic-card';
          card.dataset.index = String(idx);

          var metaRow = document.createElement('div');
          metaRow.className = 'classic-meta-row';

          var urlSpan = document.createElement('span');
          urlSpan.className = 'classic-url-tag';
          var domain = item.domain || (function () {
            try { return new URL(item.url).hostname.replace(/^www\./, ''); } catch (e) { return ''; }
          })();

          if (domain) {
            var fav = document.createElement('img');
            fav.className = 'card-favicon';
            fav.src = 'https://www.google.com/s2/favicons?domain=' + encodeURIComponent(domain) + '&sz=32';
            fav.alt = '';
            fav.loading = 'lazy';
            fav.onerror = function () { this.style.display = 'none'; };
            urlSpan.appendChild(fav);
          }
          var dName = document.createElement('span');
          dName.textContent = domain || item.url;
          urlSpan.appendChild(dName);

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

          var scrapeBtn = document.createElement('button');
          scrapeBtn.type = 'button';
          scrapeBtn.className = 'btn btn-sm';
          scrapeBtn.innerHTML = icon('fileText') + '<span>本文抽出</span>';
          var drawerId = 'classic-scrape-drawer-' + idx;
          scrapeBtn.setAttribute('aria-expanded', 'false');
          scrapeBtn.setAttribute('aria-controls', drawerId);
          scrapeBtn.addEventListener('click', function () {
            var ex = card.querySelector('.inline-scrape-drawer');
            if (ex) {
              var isHidden = ex.style.display === 'none';
              ex.style.display = isHidden ? 'block' : 'none';
              scrapeBtn.setAttribute('aria-expanded', isHidden ? 'true' : 'false');
              return;
            }
            var d = document.createElement('div');
            d.className = 'inline-scrape-drawer';
            d.id = drawerId;
            d.innerHTML = '<span class="ui-spinner"></span> URL本文を抽出中...';
            card.appendChild(d);
            scrapeBtn.setAttribute('aria-expanded', 'true');
            fetch('/api/scrape_analyze?url=' + encodeURIComponent(item.url) + '&q=' + encodeURIComponent(query || ''))
              .then(function (r) { return r.json(); })
              .then(function (res) { d.textContent = res.content || res.error || '(本文なし)'; })
              .catch(function (e) { d.innerHTML = icon('alert') + ' 抽出エラー: ' + escapeHtml(e); });
          });

          var copyBtn = document.createElement('button');
          copyBtn.type = 'button';
          copyBtn.className = 'btn btn-sm';
          copyBtn.setAttribute('aria-label', '引用をコピー');
          copyBtn.setAttribute('data-action', 'copy-citation');
          copyBtn.innerHTML = icon('copy') + '<span>引用コピー</span>';
          copyBtn.addEventListener('click', function () {
            var safeTitle = (item.title || item.url || '').split('[').join('\\[').split(']').join('\\]');
            var safeUrl = (item.url || '').split('(').join('%28').split(')').join('%29');
            var citeText = '### [' + safeTitle + '](' + safeUrl + ')\n> ' + (item.content || '').replace(/\n/g, '\n> ');
            copyWithFeedback(citeText, copyBtn, 'コピー済');
          });

          actRow.appendChild(scrapeBtn);
          actRow.appendChild(copyBtn);
          card.appendChild(actRow);

          container.appendChild(card);
        });

        // Pagination
        updateClassicPagination(page, items);
      }

      function runClassicSearch(query, page) {
        cancelPendingRequest();
        currentAbortController = new AbortController();
        var signal = currentAbortController.signal;

        page = page || 1;
        state.classicPage = page;
        var cat = state.classicCategory || '';
        var tr = document.getElementById('classic-time-range').value || '';
        var count = document.getElementById('classic-count').value || '10';

        var container = document.getElementById('classic-results-container');
        var telPill = document.getElementById('classic-telemetry-pill');
        renderSkeletonCards(container, parseInt(count, 10) || 5);

        saveQueryHistory(query);
        closeSuggest();

        var params = new URLSearchParams({
          q: query,
          mode: 'classic',
          categories: cat,
          category: cat,
          time_range: tr,
          count: count,
          page: String(page)
        });

        fetch('/deep_search?' + params.toString(), { signal: signal })
          .then(function (r) { return r.json(); })
          .then(function (res) {
            container.setAttribute('aria-busy', 'false');
            var ansContainer = document.getElementById('classic-answers-container');
            var pagBar = document.getElementById('classic-pagination-bar');
            if (res.error && (!res.results || !res.results.length)) {
              if (telPill) telPill.style.display = 'none';
              if (ansContainer) ansContainer.innerHTML = '';
              if (pagBar) pagBar.style.display = 'none';
              container.innerHTML = '<div class="empty-state"><h2 style="color:var(--danger);">' + icon('alert') + ' エラー</h2><p>' + escapeHtml(res.error) + '</p></div>';
              return;
            }
            if (telPill) {
              telPill.style.display = 'block';
              telPill.innerHTML = '取得: ' + escapeHtml(res.results_count || 0) + '件 (' + escapeHtml(res.elapsed_ms || 0) + ' ms)' +
                (cat ? ' &middot; カテゴリー: ' + escapeHtml(cat) : '') +
                (tr ? ' &middot; 期間: ' + escapeHtml(tr) : '');
            }

            // Direct answers box
            if (ansContainer) {
              ansContainer.innerHTML = '';
              if (res.answers && res.answers.length) {
                res.answers.forEach(function (a) {
                  var abox = document.createElement('div');
                  abox.className = 'classic-answer-box';
                  abox.innerHTML = '<strong>ダイレクトアンサー:</strong><br>' + escapeHtml(a);
                  ansContainer.appendChild(abox);
                });
              }
            }

            renderClassicSearchResults(res.results || [], query, page);
            updateUrlState(false);
          })
          .catch(function (err) {
            if (err.name === 'AbortError') return;
            container.setAttribute('aria-busy', 'false');
            if (telPill) telPill.style.display = 'none';
            var ansContainer = document.getElementById('classic-answers-container');
            if (ansContainer) ansContainer.innerHTML = '';
            var pagBar = document.getElementById('classic-pagination-bar');
            if (pagBar) pagBar.style.display = 'none';
            container.innerHTML = '<div class="empty-state"><h2 style="color:var(--danger);">' + icon('alert') + ' 通信エラー</h2><p>' + escapeHtml(err) + '</p></div>';
          });
      }

      addListener('classic-prev-btn', 'click', function () {
        if (state.classicPage > 1) {
          var qVal = document.getElementById('q').value.trim();
          if (qVal) runClassicSearch(qVal, state.classicPage - 1);
        }
      });
      addListener('classic-next-btn', 'click', function () {
        var qVal = document.getElementById('q').value.trim();
        if (qVal) runClassicSearch(qVal, state.classicPage + 1);
      });
      var classicDeepBtn = document.getElementById('classic-deep-btn');
      if (classicDeepBtn) {
        classicDeepBtn.addEventListener('click', function () {
          var qVal = document.getElementById('q').value.trim();
          if (!qVal) {
            showToast('検索キーワードを入力してください');
            document.getElementById('q').focus();
            return;
          }
          setMode('deep');
          runUnifiedSearch(qVal);
        });
      }
      addListener('classic-time-range', 'change', function () {
        var qVal = document.getElementById('q').value.trim();
        if (qVal && state.mode === 'classic') runClassicSearch(qVal, 1);
      });
      addListener('classic-count', 'change', function () {
        var qVal = document.getElementById('q').value.trim();
        if (qVal && state.mode === 'classic') runClassicSearch(qVal, 1);
      });

      /* -------------------------------------------------------------
       * Scrape Mode Implementation
       * ------------------------------------------------------------- */
      function runScrapeMode(targetUrl) {
        cancelPendingRequest();
        currentAbortController = new AbortController();
        var signal = currentAbortController.signal;

        var maxLen = document.getElementById('opt-scrape-len').value || '8000';
        var focusQ = document.getElementById('opt-scrape-query').value.trim();
        var container = document.getElementById('results-container');
        container.innerHTML = '<div class="empty-state"><h2><span class="ui-spinner"></span> URL 本文抽出中...</h2><p>' + escapeHtml(targetUrl) + '</p></div>';

        closeSuggest();

        var api = '/api/scrape_analyze?url=' + encodeURIComponent(targetUrl) + '&max_length=' + encodeURIComponent(maxLen);
        if (focusQ) api += '&q=' + encodeURIComponent(focusQ);
        state.curlStr = 'curl -sG "' + window.location.origin + '/scrape" --data-urlencode "url=' + escapeShellDoubleQuoted(targetUrl) + '"';

        fetch(api, { signal: signal })
          .then(function (r) { return r.json(); })
          .then(function (res) {
            container.setAttribute('aria-busy', 'false');
            var telBar = document.getElementById('telemetry-bar');
            if (res.error) {
              if (telBar) telBar.classList.remove('visible');
              container.innerHTML = '<div class="empty-state"><h2 style="color:var(--danger);">' + icon('alert') + ' 抽出エラー</h2><p>' + escapeHtml(res.error) + '</p></div>';
              return;
            }
            state.markdown = res.markdown || res.content || '';
            state.prompt = res.rag_prompt || ('以下のWebページ抽出本文を根拠として要点を解説してください。\n\nURL: ' + targetUrl + '\n\n' + state.markdown);
            state.jsonStr = JSON.stringify(res, null, 2);

            var badges = document.getElementById('telemetry-badges');
            if (telBar) telBar.classList.add('visible');
            badges.innerHTML =
              '<span class="pill pill-emerald">' + icon('check', 'ui-icon-sm') + ' 本文抽出完了 (' + escapeHtml(res.char_count || 0) + ' 文字)</span>' +
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
              hlHeader.textContent = 'BM25 関連ハイライト (' + (res.query || '') + ')';
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
            updateUrlState(false);
          })
          .catch(function (err) {
            if (err.name === 'AbortError') return;
            var telBar = document.getElementById('telemetry-bar');
            if (telBar) telBar.classList.remove('visible');
            var oldBar = document.querySelector('.telemetry-bar:not(#telemetry-bar)');
            if (oldBar) oldBar.remove();
            container.setAttribute('aria-busy', 'false');
            container.innerHTML = '<div class="empty-state"><h2 style="color:var(--danger);">' + icon('alert') + ' 通信エラー</h2><p>' + escapeHtml(err) + '</p></div>';
          });
      }

      /* -------------------------------------------------------------
       * Settings Dashboard Implementation
       * ------------------------------------------------------------- */
      function setUnsavedChanges(modified) {
        state.togglesModified = modified;
        var bar = document.getElementById('unsaved-bar');
        if (bar) {
          bar.classList.toggle('show', modified);
        }
      }

      window.addEventListener('beforeunload', function (e) {
        if (state.togglesModified) {
          e.preventDefault();
          e.returnValue = '未保存の設定変更があります。ページを離れますか？';
          return e.returnValue;
        }
      });

      addListener('btn-discard-unsaved', 'click', function () {
        loadSettingsDashboard(true);
        setUnsavedChanges(false);
        showToast('変更を破棄しました');
      });

      addListener('btn-save-unsaved', 'click', function () {
        var saveEngBtn = document.getElementById('btn-save-settings-engines');
        if (saveEngBtn) saveEngBtn.click();
        setUnsavedChanges(false);
      });

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
          chk.setAttribute('aria-label', (e.name || '検索エンジン') + ' の有効化/無効化');
          chk.addEventListener('change', function () {
            e.enabled = chk.checked;
            e.status = e.enabled ? 'online' : 'disabled';
            dot.style.background = e.enabled ? 'var(--emerald)' : 'var(--text-muted)';
            setUnsavedChanges(true);
            updateOverviewStats();
          });
          var sld = document.createElement('span');
          sld.className = 'switch-slider';
          swLabel.appendChild(chk);
          swLabel.appendChild(sld);

          top.appendChild(title);
          top.appendChild(swLabel);
          c.appendChild(top);

          // Meta info row with Ping test
          var meta = document.createElement('div');
          meta.className = 'engine-item-meta';

          (e.categories || []).forEach(function (catName) {
            var cp = document.createElement('span');
            cp.className = 'pill';
            cp.textContent = catName;
            meta.appendChild(cp);
          });

          var latPill = document.createElement('span');
          latPill.className = 'pill';
          latPill.textContent = (typeof e.latency_ms === 'number' && e.latency_ms > 0) ? (e.latency_ms + ' ms') : '-- ms';
          meta.appendChild(latPill);

          if (typeof e.reliability === 'number') {
            var relPill = document.createElement('span');
            relPill.className = 'pill ' + (e.reliability >= 90 ? 'pill-emerald' : 'pill-amber');
            relPill.textContent = '信頼性 ' + e.reliability + '%';
            meta.appendChild(relPill);
          }

          // Individual Engine Test (Ping) button
          var testBtn = document.createElement('button');
          testBtn.type = 'button';
          testBtn.className = 'btn btn-sm';
          testBtn.style.marginLeft = 'auto';
          testBtn.textContent = 'テスト';
          testBtn.addEventListener('click', function () {
            testBtn.disabled = true;
            testBtn.innerHTML = '<span class="ui-spinner"></span>';
            var t0 = performance.now();
            fetch('/deep_search?q=test&count=1&engines=' + encodeURIComponent(e.name) + '&mode=classic')
              .then(function (r) { return r.json(); })
              .then(function (res) {
                var elapsed = Math.round(performance.now() - t0);
                testBtn.disabled = false;
                testBtn.textContent = 'テスト';
                if (res.results && res.results.length) {
                  latPill.textContent = elapsed + ' ms';
                  latPill.className = 'pill pill-emerald';
                  showToast(e.name + ': 疎通成功 (' + elapsed + 'ms)');
                } else {
                  showToast(e.name + ': 応答なし / 0件', true);
                }
              })
              .catch(function () {
                testBtn.disabled = false;
                testBtn.textContent = 'テスト';
                showToast(e.name + ': 通信エラー', true);
              });
          });
          meta.appendChild(testBtn);

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

      function loadSettingsDashboard(forceReload) {
        var grid = document.getElementById('settings-engines-grid');
        if (state.settingsEngines.length && !forceReload) {
          renderSettingsEngineCards();
          return;
        }

        grid.innerHTML = '<div style="grid-column:1/-1;text-align:center;padding:2rem;"><span class="ui-spinner"></span> エンジン稼働状況を取得中...</div>';

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
            allBtn.setAttribute('aria-pressed', 'true');
            allBtn.textContent = 'すべて (' + res.total_engines + ')';
            allBtn.addEventListener('click', function () {
              chipsContainer.querySelectorAll('.cat-btn').forEach(function (b) {
                b.classList.remove('active');
                b.setAttribute('aria-pressed', 'false');
              });
              allBtn.classList.add('active');
              allBtn.setAttribute('aria-pressed', 'true');
              state.settingsCurrentCat = '';
              renderSettingsEngineCards();
            });
            chipsContainer.appendChild(allBtn);

            (res.categories || []).forEach(function (cat) {
              var count = state.settingsEngines.filter(function (e) { return (e.categories || []).indexOf(cat) !== -1; }).length;
              var b = document.createElement('button');
              b.type = 'button';
              b.className = 'cat-btn';
              b.setAttribute('aria-pressed', 'false');
              b.textContent = cat + ' (' + count + ')';
              b.addEventListener('click', function () {
                chipsContainer.querySelectorAll('.cat-btn').forEach(function (btn) {
                  btn.classList.remove('active');
                  btn.setAttribute('aria-pressed', 'false');
                });
                b.classList.add('active');
                b.setAttribute('aria-pressed', 'true');
                state.settingsCurrentCat = cat;
                renderSettingsEngineCards();
              });
              chipsContainer.appendChild(b);
            });

            renderSettingsEngineCards();
          })
          .catch(function (err) {
            grid.innerHTML = '<div style="grid-column:1/-1;text-align:center;padding:2rem;color:var(--danger);">' + icon('alert') + ' エンジン設定の取得に失敗しました: ' + escapeHtml(err) + '</div>';
          });
      }

      function selectSettingsSubtab(name) {
        var engBtn = document.getElementById('subtab-engines-btn');
        var genBtn = document.getElementById('subtab-general-btn');
        var engSec = document.getElementById('section-settings-engines');
        var genSec = document.getElementById('section-settings-general');
        if (name === 'engines') {
          engBtn.classList.add('active');
          engBtn.setAttribute('aria-selected', 'true');
          engBtn.setAttribute('tabindex', '0');
          genBtn.classList.remove('active');
          genBtn.setAttribute('aria-selected', 'false');
          genBtn.setAttribute('tabindex', '-1');
          engSec.style.display = 'block';
          genSec.style.display = 'none';
        } else if (name === 'general') {
          genBtn.classList.add('active');
          genBtn.setAttribute('aria-selected', 'true');
          genBtn.setAttribute('tabindex', '0');
          engBtn.classList.remove('active');
          engBtn.setAttribute('aria-selected', 'false');
          engBtn.setAttribute('tabindex', '-1');
          engSec.style.display = 'none';
          genSec.style.display = 'block';
        }
      }

      addListener('subtab-engines-btn', 'click', function () {
        selectSettingsSubtab('engines');
      });
      addListener('subtab-general-btn', 'click', function () {
        selectSettingsSubtab('general');
      });

      var subtabBtns = [document.getElementById('subtab-engines-btn'), document.getElementById('subtab-general-btn')].filter(Boolean);
      subtabBtns.forEach(function (btn, idx) {
        btn.addEventListener('keydown', function (e) {
          if (e.key === 'ArrowRight' || e.key === 'ArrowDown') {
            e.preventDefault();
            var next = subtabBtns[(idx + 1) % subtabBtns.length];
            next.focus();
            selectSettingsSubtab(next.getAttribute('data-subtab'));
          } else if (e.key === 'ArrowLeft' || e.key === 'ArrowUp') {
            e.preventDefault();
            var prev = subtabBtns[(idx - 1 + subtabBtns.length) % subtabBtns.length];
            prev.focus();
            selectSettingsSubtab(prev.getAttribute('data-subtab'));
          }
        });
      });

      addListener('engine-search-input', 'input', function () {
        state.settingsSearch = this.value;
        renderSettingsEngineCards();
      });

      addListener('btn-enable-all-cat', 'click', function () {
        var cat = state.settingsCurrentCat;
        state.settingsEngines.forEach(function (e) {
          if (!cat || (e.categories && e.categories.indexOf(cat) !== -1)) {
            e.enabled = true;
            e.status = 'online';
          }
        });
        updateOverviewStats();
        renderSettingsEngineCards();
        setUnsavedChanges(true);
        showToast('カテゴリー内をすべて有効化しました');
      });

      addListener('btn-disable-all-cat', 'click', function () {
        var cat = state.settingsCurrentCat;
        state.settingsEngines.forEach(function (e) {
          if (!cat || (e.categories && e.categories.indexOf(cat) !== -1)) {
            e.enabled = false;
            e.status = 'disabled';
          }
        });
        updateOverviewStats();
        renderSettingsEngineCards();
        setUnsavedChanges(true);
        showToast('カテゴリー内をすべて無効化しました');
      });

      addListener('btn-reset-engines-def', 'click', function () {
        state.settingsEngines.forEach(function (e) {
          e.enabled = !!e.default_enabled;
          e.status = e.enabled ? 'online' : 'disabled';
        });
        updateOverviewStats();
        renderSettingsEngineCards();
        setUnsavedChanges(true);
        showToast('デフォルト構成を復元しました');
      });

      addListener('btn-save-settings-engines', 'click', function () {
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
            showToast('検索エンジン構成を保存しました');
            setUnsavedChanges(false);
          })
          .catch(function () {
            showToast('保存に失敗しました', true);
          });
      });

      function loadGeneralPreferences() {
        var mode = localStorage.getItem('sxng_pref_mode');
        var ss = localStorage.getItem('sxng_pref_safesearch');
        var count = localStorage.getItem('sxng_pref_count');
        var tok = localStorage.getItem('sxng_pref_tokens');
        var ac = localStorage.getItem('sxng_pref_autocomplete');

        if (mode && document.getElementById('pref-default-mode')) document.getElementById('pref-default-mode').value = mode;
        if (ss && document.getElementById('pref-safesearch')) document.getElementById('pref-safesearch').value = ss;
        if (count && document.getElementById('pref-default-count')) document.getElementById('pref-default-count').value = count;
        if (tok && document.getElementById('pref-default-tokens')) document.getElementById('pref-default-tokens').value = tok;
        if (ac && document.getElementById('pref-autocomplete')) document.getElementById('pref-autocomplete').value = ac;
      }
      loadGeneralPreferences();

      addListener('btn-save-general-prefs', 'click', function () {
        var mode = document.getElementById('pref-default-mode') ? document.getElementById('pref-default-mode').value : 'deep';
        var ss = document.getElementById('pref-safesearch') ? document.getElementById('pref-safesearch').value : '1';
        var count = document.getElementById('pref-default-count') ? document.getElementById('pref-default-count').value : '10';
        var tok = document.getElementById('pref-default-tokens') ? document.getElementById('pref-default-tokens').value : '3000';
        var ac = document.getElementById('pref-autocomplete') ? document.getElementById('pref-autocomplete').value : 'duckduckgo';

        localStorage.setItem('sxng_pref_mode', mode);
        localStorage.setItem('sxng_pref_safesearch', ss);
        localStorage.setItem('sxng_pref_count', count);
        localStorage.setItem('sxng_pref_tokens', tok);
        localStorage.setItem('sxng_pref_autocomplete', ac);

        fetch('/api/settings/engines', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ safesearch: ss, default_mode: mode, autocomplete: ac })
        }).finally(function () {
          showToast('一般設定を保存しました');
        });
      });

      addListener('btn-reset-general-prefs', 'click', function () {
        if (document.getElementById('pref-default-mode')) document.getElementById('pref-default-mode').value = 'deep';
        if (document.getElementById('pref-safesearch')) document.getElementById('pref-safesearch').value = '1';
        if (document.getElementById('pref-default-count')) document.getElementById('pref-default-count').value = '10';
        document.getElementById('pref-default-tokens').value = '3000';
        if (document.getElementById('pref-autocomplete')) {
          document.getElementById('pref-autocomplete').value = 'duckduckgo';
        }
        localStorage.removeItem('sxng_pref_mode');
        localStorage.removeItem('sxng_pref_safesearch');
        localStorage.removeItem('sxng_pref_count');
        localStorage.removeItem('sxng_pref_tokens');
        localStorage.removeItem('sxng_pref_autocomplete');
        showToast('初期設定を復元しました');
      });

      /* -------------------------------------------------------------
       * Agent & MCP Hub Implementation
       * ------------------------------------------------------------- */
      function loadAgentHub() {
        var container = document.getElementById('hub-cards-container');
        if (container.dataset.loaded === '1') return;
        container.innerHTML = '<div class="empty-state"><h2><span class="ui-spinner"></span> 連携情報を取得中...</h2></div>';

        fetch('/api/ai_info')
          .then(function (r) { return r.json(); })
          .then(function (info) {
            container.dataset.loaded = '1';
            container.innerHTML = '';
            var items = [
              {
                title: 'GenAI Retrieval API (/api/retrieval)',
                desc: 'GenAIモデル・自律エージェント向けの構造化グラウンディングAPI (schema_version: 1.0)。根拠パッセージ・検証メタデータ・BM25スコアを返します。',
                code: info.snippets.curl_retrieval + '\n\n# PowerShell:\n' + info.snippets.pwsh_retrieval
              },
              {
                title: 'HTTP Deep Search API (/deep_search)',
                desc: '1回のHTTPリクエストで検索・並列スクレイピング・BM25ハイライト抽出を実行し、MarkdownまたはJSONを返します。',
                code: info.snippets.curl_deep_md + '\n\n# PowerShell:\n' + info.snippets.pwsh_deep
              },
              {
                title: 'Claude Code (MCP 登録コマンド)',
                desc: 'ターミナルで1行実行するだけで、Claude Code に searxng_deep_search / searxng_search / searxng_scrape を追加します。',
                code: info.snippets.claude_code
              },
              {
                title: 'Cursor / Windsurf / Claude Desktop (mcp.json)',
                desc: '.cursor/mcp.json 等に貼り付けるだけでローカルMCPサーバーとして連携できます。',
                code: info.snippets.cursor_mcp
              },
              {
                title: 'OpenCode (opencode.json)',
                desc: 'プロジェクトルートの opencode.json に設定してネイティブ検索ツールとして利用できます。',
                code: info.snippets.opencode_json
              },
              {
                title: 'ターミナル CLI (searxng_cli.py)',
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
              copyBtn.setAttribute('aria-label', it.title + ' の設定コードをコピー');
              copyBtn.innerHTML = icon('copy') + '<span>コピー</span>';
              copyBtn.addEventListener('click', function () {
                copyWithFeedback(it.code, copyBtn, 'コピー済');
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
            container.innerHTML = '<div class="empty-state"><p style="color:var(--danger);">' + icon('alert') + ' エラー: ' + escapeHtml(err) + '</p></div>';
          });
      }

      function executeCurrentAction() {
        var qVal = document.getElementById('q').value.trim();
        if (!qVal) {
          showToast('検索キーワードまたはURLを入力してください');
          document.getElementById('q').focus();
          return;
        }

        closeSuggest();

        if (isUrlText(qVal)) {
          if (state.mode !== 'deep') {
            setMode('deep', true);
          }
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

      addListener('ws-form', 'submit', function (e) {
        e.preventDefault();
        executeCurrentAction();
      });

      /* -------------------------------------------------------------
       * Keyboard Navigation & Global Shortcuts (j/k, c, s, Alt+1..4)
       * ------------------------------------------------------------- */
      document.addEventListener('keydown', function (e) {
        if (e.key === 'Escape') {
          closeSuggest();
          var toast = document.getElementById('toast-notice');
          if (toast && toast.classList.contains('show')) {
            toast.classList.remove('show');
          }
          document.querySelectorAll('.inline-scrape-drawer').forEach(function (d) {
            d.style.display = 'none';
          });
          document.querySelectorAll('button[aria-expanded="true"]').forEach(function (b) {
            b.setAttribute('aria-expanded', 'false');
          });
          return;
        }

        var active = document.activeElement;
        var qInput = document.getElementById('q');
        var isEditing = active && (['INPUT', 'TEXTAREA', 'SELECT'].indexOf(active.tagName) !== -1 || active.isContentEditable);

        // Alt + 1..4 Mode Switching
        if (e.altKey && !e.ctrlKey && !e.metaKey) {
          if (e.key === '1') { e.preventDefault(); setMode('deep'); return; }
          if (e.key === '2') { e.preventDefault(); setMode('classic'); return; }
          if (e.key === '3') { e.preventDefault(); setMode('agent'); return; }
          if (e.key === '4') { e.preventDefault(); setMode('settings'); return; }
        }

        if ((e.key === '/' && active !== qInput && !isEditing) ||
            ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k')) {
          e.preventDefault();
          if (state.mode === 'agent' || state.mode === 'settings') {
            setMode('deep');
          }
          qInput.focus();
          qInput.select();
          return;
        }

        // Power user j/k card navigation when not editing
        if (!isEditing && (state.mode === 'deep' || state.mode === 'classic')) {
          var containerId = (state.mode === 'deep') ? 'results-container' : 'classic-results-container';
          var cards = Array.prototype.slice.call(document.querySelectorAll('#' + containerId + ' article'));
          if (!cards.length) return;

          function activateCard(targetIdx) {
            state.selectedCardIndex = targetIdx;
            cards.forEach(function (c, idx) {
              var isSel = (idx === state.selectedCardIndex);
              c.classList.toggle('selected-card', isSel);
              c.setAttribute('aria-selected', isSel ? 'true' : 'false');
            });
            var targetCard = cards[state.selectedCardIndex];
            if (targetCard) {
              targetCard.setAttribute('tabindex', '-1');
              targetCard.focus({ preventScroll: true });
              targetCard.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
            }
          }

          if (e.key === 'j') {
            e.preventDefault();
            activateCard(Math.min(cards.length - 1, state.selectedCardIndex + 1));
          } else if (e.key === 'k') {
            e.preventDefault();
            activateCard(Math.max(0, state.selectedCardIndex - 1));
          } else if (e.key === 'c' && state.selectedCardIndex >= 0 && state.selectedCardIndex < cards.length) {
            e.preventDefault();
            var copyBtn = cards[state.selectedCardIndex].querySelector('button[data-action="copy-citation"], button[aria-label*="コピー"]');
            if (copyBtn) copyBtn.click();
          } else if (e.key === 'Enter' && state.selectedCardIndex >= 0 && state.selectedCardIndex < cards.length && active === cards[state.selectedCardIndex]) {
            var link = cards[state.selectedCardIndex].querySelector('a');
            if (link) window.open(link.href, '_blank', 'noopener,noreferrer');
          }
        }
      });

      // Restore user preferences from localStorage
      var savedMode = localStorage.getItem('sxng_pref_mode');
      if (savedMode && ['deep', 'classic', 'balanced'].indexOf(savedMode) !== -1) {
        document.getElementById('pref-default-mode').value = savedMode;
        if (!window.location.search) {
          setMode(savedMode === 'balanced' ? 'deep' : savedMode, true);
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

      // Parse initial URL parameters
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
          var isCurrent = (b.dataset.cat === initCat);
          b.classList.toggle('active', isCurrent);
          b.setAttribute('aria-pressed', isCurrent ? 'true' : 'false');
        });
      }
      if (initPage > 1) {
        state.classicPage = initPage;
      }
      if (initMode && ['deep', 'classic', 'agent', 'settings'].indexOf(initMode) !== -1) {
        setMode(initMode, true);
      }
      if (initQ) {
        document.getElementById('q').value = initQ;
        syncInputOptionsVisibility();
        if (state.mode === 'classic' && initPage > 1) {
          runClassicSearch(initQ, initPage);
        } else {
          executeCurrentAction();
        }
      }
    })();

  </script>
</body>
</html>
"""

AI_WORKSPACE_HTML = _load_ai_workspace_html()

# --- Tier 0: Per-client rate limiting state (module level for testability) ---
_RATE_CAPACITY = 15.0  # burst size
_RATE_REFILL_PER_SEC = 0.5  # sustained: 30 requests / minute
_RATE_MAX_BUCKETS = 1024  # bound memory against IP spoof floods
_RATELOCK = threading.Lock()
_RATE_BUCKETS: dict[str, _TokenBucket] = {}
_RATE_LIMITED_PATHS = frozenset(
    {
        "/deep_search",
        "/api/search",
        "/api/retrieval",
        "/api/scrape_analyze",
    }
)


class _TokenBucket:
    """Thread-safe token-bucket rate limiter state keyed by client IP.

    Refills continuously at ``_RATE_REFILL_PER_SEC`` tokens per second up to
    ``_RATE_CAPACITY``; each request consumes one token. Prevents
    resource-exhaustion DoS via the expensive search/scrape endpoints
    (network fan-out, HTML scraping).
    """

    __slots__ = ("tokens", "updated")

    def __init__(self, tokens: float, updated: float) -> None:
        self.tokens = tokens
        self.updated = updated


def _rate_limit_check(client_id: str) -> bool:
    """Take one token for ``client_id``; return True when allowed."""
    now = time.monotonic()
    with _RATELOCK:
        bucket = _RATE_BUCKETS.get(client_id)
        if bucket is None:
            if len(_RATE_BUCKETS) >= _RATE_MAX_BUCKETS:
                # Evict stalest entries (oldest refill timestamps first)
                # to keep the table bounded under address churn.
                stale_cutoff = now - (_RATE_CAPACITY / _RATE_REFILL_PER_SEC)
                for stale_key in [k for k, v in _RATE_BUCKETS.items() if v.updated < stale_cutoff]:
                    del _RATE_BUCKETS[stale_key]
                if len(_RATE_BUCKETS) >= _RATE_MAX_BUCKETS and client_id not in _RATE_BUCKETS:
                    return False  # under flood: reject unknown clients
            bucket = _TokenBucket(_RATE_CAPACITY, now)
            _RATE_BUCKETS[client_id] = bucket
        elapsed = now - bucket.updated
        bucket.tokens = min(_RATE_CAPACITY, bucket.tokens + elapsed * _RATE_REFILL_PER_SEC)
        bucket.updated = now
        if bucket.tokens >= 1.0:
            bucket.tokens -= 1.0
            return True
        return False


def register_next_webui(app: Any, webapp_mod: Any = None) -> None:
    """Register SearXNG Next AI-First WebUI and API routes onto the Flask app idempotently."""
    # Guard against duplicate registration
    if getattr(app, "_sxng_next_registered", False):
        return
    app._sxng_next_registered = True

    from flask import Response, jsonify, redirect, request

    orig_search = app.view_functions.get("search")
    orig_preferences = app.view_functions.get("preferences")
    orig_about = app.view_functions.get("about")
    orig_autocompleter = app.view_functions.get("autocompleter")

    def unified_autocompleter_view() -> Any:
        q = (request.args.get("q") or request.form.get("q") or "").strip()
        if not q or len(q) < 1:
            return Response("[]", mimetype="application/json")

        req_backend = (request.args.get("backend") or request.args.get("autocomplete") or "").strip().lower()
        if req_backend in ("off", "none", "0", "false"):
            return Response("[]", mimetype="application/json")

        if "autocomplete" in request.cookies:
            cookie_ac = request.cookies.get("autocomplete", "").strip().lower()
            if not req_backend and (not cookie_ac or cookie_ac in ("off", "none", "0", "false")):
                return Response("[]", mimetype="application/json")
        else:
            cookie_ac = ""

        effective_backend = req_backend or cookie_ac
        results: list[str] = []
        if orig_autocompleter is not None:
            with contextlib.suppress(Exception):
                upstream_resp = orig_autocompleter()
                if hasattr(upstream_resp, "get_data"):
                    raw_data = upstream_resp.get_data(as_text=True)
                    parsed = json.loads(raw_data)
                    if isinstance(parsed, list):
                        if len(parsed) >= 2 and isinstance(parsed[1], list):
                            results = [str(x) for x in parsed[1] if isinstance(x, str) and x.strip()]
                        else:
                            results = [
                                str(x) for x in parsed if isinstance(x, str) and x.strip() and x != "[object Object]"
                            ]

        if not results:
            with contextlib.suppress(Exception):
                import searx.autocomplete as sxng_ac

                backends_dict = getattr(sxng_ac, "backends", {})
                preferred = (
                    effective_backend if effective_backend and effective_backend in backends_dict else "duckduckgo"
                )
                fallback_backends = [preferred]
                if "duckduckgo" not in fallback_backends:
                    fallback_backends.append("duckduckgo")
                if "google" not in fallback_backends:
                    fallback_backends.append("google")

                for backend in fallback_backends:
                    with contextlib.suppress(Exception):
                        cand = sxng_ac.search_autocomplete(backend, q, "auto")
                        if cand and isinstance(cand, list):
                            clean_cand = [
                                str(x).strip() for x in cand if isinstance(x, str) and x.strip() and str(x).strip() != q
                            ]
                            if clean_cand:
                                results = clean_cand
                                break

        is_ajax = (
            request.headers.get("X-Requested-With") == "XMLHttpRequest"
            or "application/json" in (request.headers.get("Accept") or "")
            or request.args.get("format") == "json"
        )
        if is_ajax:
            return Response(json.dumps(results), mimetype="application/json")

        relevances = {"google:suggestrelevance": [600 - i for i in range(len(results))]}
        return Response(
            json.dumps([q, results, [], [], relevances]),
            mimetype="application/x-suggestions+json",
        )

    # --- Tier 0: Per-client rate limiting for expensive API routes ---
    def _rate_limit_client_id() -> str:
        """Best-effort client identity: REMOTE_ADDR only.

        ``X-Forwarded-For`` is intentionally NOT trusted: this app binds to
        localhost (per DEVELOPMENT.md) and any header can be forged by a
        direct client to exhaust distinct bucket keys (memory DoS). Behind a
        trusted reverse proxy, the proxy address is the stable identity and
        the proxy itself should enforce per-client limits (see DEVELOPMENT.md
        nginx ``limit_req_zone`` guidance).
        """
        addr = request.remote_addr or "unknown"
        return ipaddress.ip_address(addr).compressed if _is_valid_ip(addr) else addr

    def _is_valid_ip(addr: str) -> bool:
        with contextlib.suppress(ValueError):
            ipaddress.ip_address(addr)
            return True
        return False

    @app.before_request
    def sxng_rate_limit_guard() -> Any:
        if request.path in _RATE_LIMITED_PATHS:
            client_id = _rate_limit_client_id()
            if not _rate_limit_check(client_id):
                retry_after = max(1, round(1.0 / _RATE_REFILL_PER_SEC))
                resp = jsonify({"error": "Rate limit exceeded", "retry_after": retry_after})
                resp.status_code = 429
                resp.headers["Retry-After"] = str(retry_after)
                return resp
        return None

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
            # 5. /autocompleter -> unified autocompleter handler with resilient fallback
            if path == "/autocompleter":
                return unified_autocompleter_view()
        return None

    # --- Tier B: app.view_functions replacement ---
    orig_search = app.view_functions.get("search")
    orig_preferences = app.view_functions.get("preferences")
    orig_about = app.view_functions.get("about")
    orig_autocompleter = app.view_functions.get("autocompleter")

    def unified_index_view() -> Any:
        return Response(AI_WORKSPACE_HTML, mimetype="text/html")

    def unified_search_view() -> Any:
        out_fmt = (request.values.get("format") or "").strip().lower()
        accept = request.headers.get("Accept") or ""
        if (
            out_fmt in ("json", "json_lite", "csv", "rss") or "application/json" in accept or "text/json" in accept
        ) and orig_search:
            return orig_search()
        params = dict(request.values)
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
    if orig_autocompleter is not None:
        app.view_functions["autocompleter"] = unified_autocompleter_view

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
        timeout = _parse_float(request.values.get("timeout") or payload.get("timeout"), 10.0, 1.0, 60.0)

        if not isinstance(url, str) or not url.strip():
            return jsonify({"error": "No URL provided", "url": "", "content": ""}), 400

        res = execute_scrape_analyze(
            url=url,
            query=str(query) if query else "",
            max_length=max_len,
            webapp_mod=webapp_mod,
            timeout=timeout,
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
        categories = (
            request.values.get("categories")
            or request.values.get("category")
            or payload.get("categories")
            or payload.get("category")
            or ""
        )
        engines = request.values.get("engines") or payload.get("engines") or ""
        time_range = request.values.get("time_range") or payload.get("time_range") or ""
        raw_timeout = request.values.get("timeout") or payload.get("timeout")
        timeout = _parse_float(raw_timeout, 15.0, 1.0, 60.0) if raw_timeout is not None else None
        raw_base_url = request.values.get("base_url") or payload.get("base_url")
        base_url = str(raw_base_url).strip() if raw_base_url else None
        inc_hl = _parse_bool(
            request.values.get("include_highlights", payload.get("include_highlights")),
            default=True,
        )

        inc_domains = _parse_domain_list(
            request.values.getlist("site")
            or request.values.get("include_domains")
            or payload.get("include_domains")
            or payload.get("site")
        )
        exc_domains = _parse_domain_list(
            request.values.getlist("exclude_site")
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
                base_url=base_url,
                timeout=timeout,
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
            base_url=base_url,
            timeout=timeout,
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
        raw_timeout = request.values.get("timeout") or payload.get("timeout")
        timeout = _parse_float(raw_timeout, 15.0, 1.0, 60.0) if raw_timeout is not None else None
        raw_base_url = request.values.get("base_url") or payload.get("base_url")
        base_url = str(raw_base_url).strip() if raw_base_url else None
        inc_domains = _parse_domain_list(
            request.values.getlist("site")
            or request.values.get("include_domains")
            or payload.get("include_domains")
            or payload.get("site")
        )
        exc_domains = _parse_domain_list(
            request.values.getlist("exclude_site")
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
            base_url=base_url,
            timeout=timeout,
        )

        if out_fmt in ("markdown", "md"):
            return Response(res.get("markdown", ""), status=200, mimetype="text/markdown")

        return jsonify(res), 200
