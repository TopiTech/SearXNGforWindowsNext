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

import html
import ipaddress
import json
import os
import re
import socket
import sys
import time
import urllib.parse
from typing import Any

TOOLS_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.abspath(os.path.join(TOOLS_DIR, ".."))
if TOOLS_DIR not in sys.path:
    sys.path.insert(0, TOOLS_DIR)

import agentic_search
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
    if not val:
        return []
    raw_items: list[str] = []
    if isinstance(val, (list, tuple, set)):
        for item in val:
            if item:
                raw_items.extend(str(item).split(","))
    elif isinstance(val, str):
        raw_items.extend(val.split(","))
    cleaned: list[str] = []
    for d in raw_items:
        dom = d.strip().lower().removeprefix("https://").removeprefix("http://").split("/")[0].removeprefix("www.")
        if dom and dom not in cleaned:
            cleaned.append(dom)
    return cleaned


def build_rag_prompt(query: str, markdown_context: str) -> str:
    """Wrap packed search markdown into a ready-to-paste LLM RAG prompt."""
    q = (query or "").strip()
    md = (markdown_context or "").strip()
    return (
        "以下のWeb検索結果および抽出された本文ハイライト（引用番号 [1]〜）を根拠として、"
        "質問に対して正確・体系的に回答してください。\n"
        "回答内で事実やコード・数値を参照する際は、対応する引用元 `[1]` などを明記してください。\n\n"
        f"## 質問・調査テーマ\n{q}\n\n"
        f"## 検索コンテキスト\n{md}\n"
    )


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

    try:
        parsed = _parse_url(clean_url)
    except Exception as exc:
        return {"url": clean_url, "content": "", "error": str(exc)}

    if parsed.scheme not in ("http", "https") or webapp_mod._is_blocked_scrape_host(parsed.hostname):
        return {
            "url": clean_url,
            "content": "",
            "error": "スクレイピング拒否 (400): プライベートIP、ループバック、または許可されていないスキームです。",
        }

    def _resolve_safe_ip(url_to_resolve: str) -> tuple[str, str, int]:
        p_url = _parse_url(url_to_resolve)
        if p_url.scheme not in ("http", "https"):
            raise blocked_exc_cls(f"Blocked invalid scheme: {p_url.scheme}")
        host = p_url.hostname
        if not host:
            raise blocked_exc_cls("Empty hostname")
        host_clean = host.strip().rstrip(".").lower()
        if webapp_mod._is_reserved_scrape_host(host_clean):
            raise blocked_exc_cls(f"Blocked: {host} is a private/reserved host")
        if "%" in host_clean:
            host_clean = host_clean.split("%", 1)[0]
        try:
            ip_direct = ipaddress.ip_address(host_clean)
            if webapp_mod._is_ip_blocked(ip_direct):
                raise blocked_exc_cls(f"Blocked: {host} is a private/reserved IP")
        except ValueError:
            if host_clean.isdigit():
                try:
                    ip_int = int(host_clean)
                    if 0 <= ip_int <= 0xFFFFFFFF:
                        v4 = ipaddress.IPv4Address(ip_int)
                        if webapp_mod._is_ip_blocked(v4):
                            raise blocked_exc_cls(f"Blocked: {host} is a private/reserved IP")
                except blocked_exc_cls:
                    raise
                except Exception:
                    pass

        port = p_url.port or (443 if p_url.scheme == "https" else 80)
        try:
            addr_info = socket.getaddrinfo(host, port)
        except socket.gaierror as exc:
            raise blocked_exc_cls(f"DNS resolution failed for {host}: {exc}") from exc
        if not addr_info:
            raise blocked_exc_cls(f"Could not resolve host: {host}")
        valid_ips: list[str] = []
        for res in addr_info:
            ip_raw = res[4][0]
            if webapp_mod._is_ip_blocked(ip_raw):
                raise blocked_exc_cls(f"Blocked: {host} resolves to a private/reserved IP: {ip_raw}")
            valid_ips.append(ip_raw)
        if not valid_ips:
            raise blocked_exc_cls(f"Could not find a global IP for {host}")
        return valid_ips[0], host, port

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
                    try:
                        webapp_mod._scrape_client.close()
                    except Exception:
                        pass
                webapp_mod._scrape_client = httpx_mod.Client(
                    timeout=httpx_mod.Timeout(10.0, connect=5.0, read=10.0, write=5.0),
                    follow_redirects=False,
                    verify=verify_ssl,
                    limits=scrape_limits,
                    trust_env=False,
                )
                webapp_mod._scrape_client_verify_ssl = verify_ssl

        current_url = clean_url
        downloaded = ""
        for _ in range(5):
            cur_parsed = _parse_url(current_url)
            if (cur_parsed.scheme or "").lower() not in ("http", "https"):
                raise blocked_exc_cls(f"Blocked invalid scheme during redirect: {cur_parsed.scheme}")
            safe_ip, original_host, port = _resolve_safe_ip(current_url)
            headers = {"User-Agent": ua}
            with webapp_mod.pinned_dns(original_host, safe_ip, port):
                with webapp_mod._scrape_client.stream("GET", current_url, headers=headers) as response:
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
                content_text = webapp_mod.trafilatura.extract(
                    downloaded, include_comments=False, include_tables=True
                )
            except Exception:
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
    except Exception as exc:
        return {"url": clean_url, "content": "", "error": f"取得失敗: {str(exc)[:120]}"}


def _search_in_process(
    webapp_mod: Any,
    query: str,
    count: int = 5,
    categories: str = "",
    engines: str = "",
    time_range: str = "",
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

    if webapp_mod is not None:
        try:
            sxng_req = getattr(webapp_mod, "sxng_request", None)
            prefs = getattr(sxng_req, "preferences", None)
            if prefs is not None:
                def _run_form(form_dict: dict[str, str]) -> dict[str, Any]:
                    sq, _, _, _, _ = webapp_mod.get_search_query_from_webapp(prefs, form_dict)
                    if not getattr(sq, "engineref_list", None) and ("categories" in form_dict or "engines" in form_dict):
                        fallback_form = {"q": clean_query}
                        if time_range.strip():
                            fallback_form["time_range"] = time_range.strip()
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

                data = _run_form(form)
                results = data.get("results", [])

                # If specialized routing returned 0 results, retry once with user's default enabled engines
                if not results and (categories.strip() or engines.strip()):
                    fallback_form = {"q": clean_query}
                    if time_range.strip():
                        fallback_form["time_range"] = time_range.strip()
                    data = _run_form(fallback_form)
                    results = data.get("results", [])

                if count_int and len(results) > count_int:
                    results = results[:count_int]

                return {
                    "query": clean_query,
                    "results": results,
                    "answers": data.get("answers", []),
                    "infoboxes": data.get("infoboxes", []),
                    "suggestions": data.get("suggestions", []),
                }
        except Exception:
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
    max_tokens: int = 3000,
    base_url: str | None = None,
    timeout: float | None = None,
) -> dict[str, Any]:
    """Run the full Agentic Deep Search pipeline and enrich with token & timing telemetry."""
    t0 = time.perf_counter()
    depth = (search_depth or "advanced").strip().lower()
    if depth not in ("basic", "advanced", "code"):
        depth = "advanced"

    max_res = _parse_int(max_results, default=5, minimum=1, maximum=20)
    max_tok = _parse_int(max_tokens, default=3000, minimum=500, maximum=16000)

    def _s_func(
        query: str,
        count: int = 15,
        categories: str = "",
        engines: str = "",
        base_url: str | None = None,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        return _search_in_process(
            webapp_mod=webapp_mod,
            query=query,
            count=count,
            categories=categories,
            engines=engines,
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

    res = agentic_search.execute_deep_search(
        query=query,
        search_func=_s_func,
        scrape_func=_sc_func,
        search_depth=depth,
        max_results=max_res,
        include_highlights=include_highlights,
        include_domains=include_domains,
        exclude_domains=exclude_domains,
        max_tokens=max_tok,
        base_url=base_url,
        timeout=timeout,
    )

    elapsed_ms = round((time.perf_counter() - t0) * 1000.0, 1)
    md = res.get("markdown", "")
    est_tokens = agentic_search.TokenBudgeter.estimate_tokens(md)
    results_list = res.get("results", [])
    scraped_count = sum(1 for item in results_list if isinstance(item, dict) and item.get("is_scraped"))

    res["search_depth"] = depth
    res["max_tokens"] = max_tok
    res["estimated_tokens"] = est_tokens
    res["scraped_count"] = scraped_count
    res["elapsed_ms"] = elapsed_ms
    res["rag_prompt"] = build_rag_prompt(res.get("query") or query, md)
    return res


def execute_scrape_analyze(
    url: str,
    query: str = "",
    max_length: int = 8000,
    webapp_mod: Any = None,
    timeout: float = 10.0,
) -> dict[str, Any]:
    """Scrape a URL, estimate tokens, and optionally extract BM25 highlights matching a focus query."""
    t0 = time.perf_counter()
    clean_url = (url or "").strip()
    clean_q = (query or "").strip()
    max_len = _parse_int(max_length, default=8000, minimum=500, maximum=50000)

    scrape_res = _scrape_url_direct(webapp_mod, clean_url, max_length=max_len, timeout=timeout)
    elapsed_ms = round((time.perf_counter() - t0) * 1000.0, 1)

    if scrape_res.get("error"):
        return {
            "url": clean_url,
            "query": clean_q,
            "content": "",
            "highlights": [],
            "char_count": 0,
            "estimated_tokens": 0,
            "elapsed_ms": elapsed_ms,
            "error": scrape_res["error"],
            "markdown": f"### 本文抽出エラー\n\n{scrape_res['error']}",
        }

    content = scrape_res.get("content", "")
    highlights: list[str] = []
    if clean_q and content:
        extractor = agentic_search.BM25PassageExtractor()
        highlights = extractor.extract_highlights(content, clean_q, top_k=3)

    dom = agentic_search.extract_domain(clean_url)
    est_tokens = agentic_search.TokenBudgeter.estimate_tokens(content)

    md_lines = [f"## 抽出本文: [{dom or clean_url}]({clean_url})\n"]
    if scrape_res.get("is_truncated"):
        md_lines.append(
            f"> ⚠️ *先頭 {len(content)} 文字を表示中 (全 {scrape_res.get('original_length', len(content))} 文字)*\n"
        )
    if highlights:
        md_lines.append(f"### 🎯 BM25 ハイライト (`{clean_q}`)\n")
        for idx, h in enumerate(highlights, 1):
            if h.startswith("```"):
                md_lines.append(f"**[{idx}]**\n{h}\n")
            else:
                quoted = "\n".join(f"> {line}" for line in h.split("\n"))
                md_lines.append(f"**[{idx}]**\n{quoted}\n")
        md_lines.append("---\n### 📄 抽出本文\n")

    md_lines.append(content)
    markdown_out = "\n".join(md_lines).strip()

    return {
        "url": clean_url,
        "domain": dom,
        "query": clean_q,
        "content": content,
        "highlights": highlights,
        "is_truncated": bool(scrape_res.get("is_truncated", False)),
        "original_length": int(scrape_res.get("original_length", len(content))),
        "char_count": len(content),
        "estimated_tokens": est_tokens,
        "elapsed_ms": elapsed_ms,
        "markdown": markdown_out,
    }


def get_ai_info(webapp_mod: Any = None, host_url: str = "http://127.0.0.1:8888") -> dict[str, Any]:
    """Return instance AI capabilities, engine statistics, and MCP/CLI configuration snippets."""
    base = (host_url or "http://127.0.0.1:8888").rstrip("/")
    instance_name = "SearXNG for Windows Next"
    version_str = "Next"
    enabled_engines_count = 0

    if webapp_mod is not None:
        try:
            instance_name = webapp_mod.get_setting("general.instance_name") or instance_name
            version_str = getattr(webapp_mod, "VERSION_STRING", version_str)
            eng_dict = getattr(webapp_mod, "engines", {}) or {}
            enabled_engines_count = sum(
                1 for e in eng_dict.values() if not getattr(e, "disabled", False)
            )
        except Exception:
            pass

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
            "mcp": {
                "searxng": {
                    "type": "local",
                    "command": [python_exe, mcp_py],
                    "enabled": True,
                }
            }
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
            "pwsh_deep": f'Invoke-RestMethod "{base}/deep_search?q=FastAPI+lifespan&depth=advanced&max_results=5"',
        },
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
.sxng-next-badge {
  display: inline-block;
  margin-top: 0.25rem;
  padding: 0.18rem 0.65rem;
  font-size: 0.75rem;
  font-weight: 600;
  letter-spacing: 0.03em;
  border-radius: 999px;
  background: var(--sxng-ai-accent-soft);
  color: var(--sxng-ai-accent);
  border: 1px solid var(--sxng-ai-border);
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
          existingBox.style.display = existingBox.style.display === 'none' ? 'block' : 'none';
          return;
        }
        var box = document.createElement('div');
        box.className = 'sxng-ai-scrape-box';
        box.innerHTML = '<span>⏳ 本文を抽出中 (trafilatura)...</span>';
        art.appendChild(box);
        scrapeBtn.disabled = true;

        var qInput = document.getElementById('q');
        var qVal = qInput ? qInput.value.trim() : '';
        var apiUrl = '/api/scrape_analyze?url=' + encodeURIComponent(targetUrl) + '&q=' + encodeURIComponent(qVal) + '&max_length=6000';
        fetch(apiUrl)
          .then(function (r) { return r.json(); })
          .then(function (res) {
            scrapeBtn.disabled = false;
            if (res.error) {
              box.innerHTML = '<div style="color:#ef4444;">⚠️ ' + res.error + '</div>';
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
              (res.char_count || 0) + ' chars / ~' + tok + ' tokens</span>';

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
            box.innerHTML = '<div style="color:#ef4444;">⚠️ 通信エラー: ' + err + '</div>';
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
      inlineDeepBtn.addEventListener('click', function () {
        if (deepDrawer.classList.contains('open') && deepDrawer.dataset.loaded === '1') {
          deepDrawer.classList.remove('open');
          return;
        }
        deepDrawer.classList.add('open');
        if (deepDrawer.dataset.loaded === '1') return;

        var bar = document.getElementById('sxng-ai-results-bar');
        var q = (bar && bar.dataset.query) || (document.getElementById('q') ? document.getElementById('q').value : '');
        if (!q) return;

        deepDrawer.innerHTML = '<div>⚡ <strong>Agentic Deep Search 実行中...</strong> (並列本文抽出 + BM25 ハイライト + ドメイン評価)</div>';
        fetch('/deep_search?q=' + encodeURIComponent(q) + '&depth=advanced&max_results=5&max_tokens=3000')
          .then(function (r) { return r.json(); })
          .then(function (res) {
            if (res.error) {
              deepDrawer.innerHTML = '<div style="color:#ef4444;">⚠️ ' + res.error + '</div>';
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
              '<span class="sxng-ai-token-pill">Intent: ' + (res.intent || 'general') + '</span> ' +
              '<span class="sxng-ai-token-pill">~' + (res.estimated_tokens || 0) + ' tokens</span> ' +
              '<span class="sxng-ai-token-pill">' + (res.elapsed_ms || 0) + ' ms</span>';

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
            deepDrawer.innerHTML = '<div style="color:#ef4444;">⚠️ Deep Search 通信エラー: ' + err + '</div>';
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
    .search-input:focus {
      border-color: var(--accent);
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
    .chip {
      padding: 0.18rem 0.55rem;
      border-radius: 999px;
      font-size: 0.73rem;
      border: 1px solid var(--border-color);
      background: var(--bg-elevated);
      color: var(--text-secondary);
      cursor: pointer;
    }
    .chip:hover {
      border-color: var(--accent);
      color: var(--text-main);
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
    /* Split Grid Layout */
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
      border-color: var(--accent);
    }
    .card-top {
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      justify-content: space-between;
      gap: 0.4rem;
      margin-bottom: 0.35rem;
    }
    .card-rank {
      font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      font-size: 0.75rem;
      font-weight: 700;
      padding: 0.12rem 0.45rem;
      border-radius: 0.35rem;
      background: var(--accent-soft);
      color: var(--accent-hover);
    }
    .card-domain {
      font-size: 0.76rem;
      color: var(--text-secondary);
      font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
    }
    .card-badges {
      display: flex;
      flex-wrap: wrap;
      gap: 0.35rem;
    }
    .card-title {
      font-size: 1.02rem;
      font-weight: 700;
      margin-bottom: 0.45rem;
      line-height: 1.35;
    }
    .highlight-block {
      margin: 0.45rem 0;
      padding: 0.55rem 0.75rem;
      border-left: 3px solid var(--accent);
      background: var(--bg-elevated);
      border-radius: 0 0.45rem 0.45rem 0;
      font-size: 0.85rem;
      color: var(--text-main);
      white-space: pre-wrap;
      word-break: break-word;
    }
    .highlight-code {
      margin: 0.45rem 0;
      padding: 0.65rem 0.8rem;
      background: #090d16;
      color: #e2e8f0;
      border: 1px solid var(--border-color);
      border-radius: 0.45rem;
      font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      font-size: 0.79rem;
      overflow-x: auto;
      white-space: pre;
    }
    .card-actions {
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      gap: 0.45rem;
      margin-top: 0.65rem;
      padding-top: 0.55rem;
      border-top: 1px solid var(--border-color);
    }
    .inline-scrape-drawer {
      margin-top: 0.65rem;
      padding: 0.7rem;
      border-radius: 0.5rem;
      background: var(--bg-input);
      border: 1px solid var(--border-color);
      font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      font-size: 0.78rem;
      max-height: 18rem;
      overflow: auto;
      white-space: pre-wrap;
      word-break: break-word;
    }
    /* Right Column: AI Context Studio */
    .context-panel {
      background: var(--bg-surface);
      border: 1px solid var(--border-color);
      border-radius: 0.75rem;
      padding: 0.95rem 1.05rem;
      position: sticky;
      top: 4.5rem;
    }
    .context-header {
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      justify-content: space-between;
      gap: 0.5rem;
      margin-bottom: 0.65rem;
    }
    .context-tabs {
      display: flex;
      flex-wrap: wrap;
      gap: 0.3rem;
      margin-bottom: 0.65rem;
    }
    .ctx-tab {
      padding: 0.28rem 0.65rem;
      font-size: 0.76rem;
      font-weight: 600;
      border-radius: 0.4rem;
      border: 1px solid var(--border-color);
      background: var(--bg-elevated);
      color: var(--text-secondary);
      cursor: pointer;
    }
    .ctx-tab.active {
      background: var(--accent-soft);
      color: var(--accent-hover);
      border-color: var(--accent);
    }
    .context-textarea {
      width: 100%;
      height: 28rem;
      padding: 0.75rem;
      border-radius: 0.5rem;
      border: 1px solid var(--border-color);
      background: var(--bg-input);
      color: var(--text-main);
      font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      font-size: 0.79rem;
      line-height: 1.5;
      resize: vertical;
      outline: none;
    }
    .token-progress-wrap {
      margin-top: 0.55rem;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 0.6rem;
      font-size: 0.75rem;
      color: var(--text-secondary);
    }
    .token-bar-bg {
      flex: 1;
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
    /* Agent Hub Grid */
    .hub-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(340px, 1fr));
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
      <a href="/ai" class="brand-logo" style="text-decoration:none;">
        <span>⚡ SearXNG Next</span>
      </a>
      <span class="brand-badge">AI-First Studio</span>
      <span class="status-dot" id="health-dot" title="Server Online"></span>
    </div>

    <nav class="nav-tabs" role="tablist" aria-label="Workspace Modes">
      <button type="button" class="nav-tab active" data-mode="deep" id="tab-deep">⚡ Deep Search (BM25 + Scrape)</button>
      <button type="button" class="nav-tab" data-mode="fast" id="tab-fast">🚀 Fast Search (json_lite)</button>
      <button type="button" class="nav-tab" data-mode="scrape" id="tab-scrape">📄 URL Scrape (本文抽出)</button>
      <button type="button" class="nav-tab" data-mode="agent" id="tab-agent">🤖 Agent &amp; MCP Hub</button>
    </nav>

    <div class="header-actions">
      <button type="button" class="btn btn-sm" id="theme-toggle-btn" title="テーマ切替 (Dark / Light)">🌗 テーマ</button>
      <a href="/" class="btn btn-sm" id="classic-ui-link" title="標準のSearXNG検索画面へ">🔍 Classic UI</a>
      <a href="/preferences" class="btn btn-sm" title="エンジン・表示設定">⚙️ 設定</a>
    </div>
  </header>

  <main class="workspace">
    <!-- Search & Scrape Input Panel -->
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
              placeholder="調査したい技術トピック・エラー・質問を入力 (例: FastAPI lifespan context manager)..."
              autocomplete="off"
              autofocus
            >
            <span class="kbd-hint">/ or Ctrl+K</span>
          </div>
          <button type="submit" class="btn btn-primary" id="run-btn" style="padding:0.72rem 1.25rem;font-size:0.9rem;">
            ⚡ 実行
          </button>
        </div>

        <!-- Deep & Fast Search Options -->
        <div class="options-row" id="search-options-row">
          <div class="opt-group" id="opt-depth-group">
            <label for="opt-depth">Depth:</label>
            <select id="opt-depth" class="opt-select">
              <option value="advanced" selected>Advanced (並列本文抽出 + BM25)</option>
              <option value="code">Code &amp; Docs (技術・GitHub優先)</option>
              <option value="basic">Basic (高速スニペット + ドメイン評価)</option>
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

        <!-- Scrape Mode Options -->
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
          <span class="pill pill-emerald">🛡️ DNS-Pinned &amp; SSRF Protected</span>
        </div>
      </form>
    </section>

    <!-- Telemetry & Quick Action Ribbon -->
    <section class="telemetry-bar" id="telemetry-bar">
      <div class="telemetry-left" id="telemetry-badges"></div>
      <div class="telemetry-right">
        <button type="button" class="btn btn-primary btn-sm" id="copy-md-main">📋 AI用Markdownをコピー</button>
        <button type="button" class="btn btn-sm" id="copy-prompt-main">💬 RAGプロンプト形式でコピー</button>
        <button type="button" class="btn btn-sm" id="copy-json-main">{ } JSONをコピー</button>
        <button type="button" class="btn btn-sm" id="download-md-btn">💾 .md 保存</button>
      </div>
    </section>

    <!-- Main Search / Scrape Split View -->
    <section class="split-grid" id="main-split-view">
      <div class="results-list" id="results-container">
        <div class="empty-state" id="initial-empty-state">
          <h2>⚡ AI-First Web Search &amp; Context Extraction</h2>
          <p>並列スクレイピング・BM25ハイライト抽出・ドメイン権威スコアリングを1パスで実行し、LLMに最適なコンテキストを生成します。</p>
          <div class="sample-queries">
            <button type="button" class="chip sample-q" data-q="FastAPI lifespan context manager syntax">🔎 FastAPI lifespan context manager</button>
            <button type="button" class="chip sample-q" data-q="Python asyncio TaskGroup exception handling">🔎 Python asyncio.TaskGroup</button>
            <button type="button" class="chip sample-q" data-q="SearXNG json_lite agentic search">🔎 SearXNG json_lite</button>
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
        <div class="context-tabs">
          <button type="button" class="ctx-tab active" data-ctx="markdown">Markdown</button>
          <button type="button" class="ctx-tab" data-ctx="prompt">RAG Prompt</button>
          <button type="button" class="ctx-tab" data-ctx="json">JSON</button>
          <button type="button" class="ctx-tab" data-ctx="curl">API / CLI</button>
        </div>
        <textarea id="ctx-output" class="context-textarea" readonly aria-label="Generated AI Context" placeholder="検索またはURL本文抽出を実行すると、ここにLLM貼り付け用の構造化Markdown・プロンプト・JSONが生成されます。"></textarea>
        <div class="token-progress-wrap">
          <span id="token-usage-label">0 / 3,000 tokens</span>
          <div class="token-bar-bg"><div class="token-bar-fill" id="token-bar-fill"></div></div>
        </div>
      </aside>
    </section>

    <!-- Agent & MCP Hub View -->
    <section id="agent-hub-view" style="display:none;">
      <div class="hub-grid" id="hub-cards-container"></div>
    </section>
  </main>

  <footer class="ws-footer">
    SearXNG for Windows Next — AI-First Lightweight WebUI ·
    <a href="/">Classic Search</a> ·
    <a href="/healthz">Health (/healthz)</a> ·
    <a href="/api/ai_info">AI Info (/api/ai_info)</a>
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
        maxTokens: 3000
      };

      // Theme initialization
      var savedTheme = localStorage.getItem('sxng_ai_theme') || 'dark';
      document.documentElement.setAttribute('data-theme', savedTheme);
      document.getElementById('theme-toggle-btn').addEventListener('click', function () {
        var cur = document.documentElement.getAttribute('data-theme') === 'light' ? 'dark' : 'light';
        document.documentElement.setAttribute('data-theme', cur);
        localStorage.setItem('sxng_ai_theme', cur);
      });

      function estimateTokens(text) {
        if (!text) return 0;
        var cjk = (text.match(/[\\u3040-\\u30ff\\u3400-\\u4dbf\\u4e00-\\u9fff]/g) || []).length;
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

      function setMode(mode) {
        state.mode = mode;
        document.querySelectorAll('.nav-tab').forEach(function (t) {
          t.classList.toggle('active', t.dataset.mode === mode);
        });

        var inputPanel = document.getElementById('input-panel');
        var searchOpts = document.getElementById('search-options-row');
        var scrapeOpts = document.getElementById('scrape-options-row');
        var depthGroup = document.getElementById('opt-depth-group');
        var tokensGroup = document.getElementById('opt-tokens-group');
        var siteGroup = document.getElementById('opt-site-group');
        var presetChips = document.getElementById('preset-chips');
        var mainSplit = document.getElementById('main-split-view');
        var agentHub = document.getElementById('agent-hub-view');
        var qInput = document.getElementById('q');
        var runBtn = document.getElementById('run-btn');

        if (mode === 'agent') {
          inputPanel.style.display = 'none';
          mainSplit.style.display = 'none';
          agentHub.style.display = 'block';
          loadAgentHub();
          return;
        }

        inputPanel.style.display = 'block';
        mainSplit.style.display = 'grid';
        agentHub.style.display = 'none';

        if (mode === 'scrape') {
          searchOpts.style.display = 'none';
          scrapeOpts.style.display = 'flex';
          qInput.placeholder = '本文を抽出したいWebページのURLを入力 (例: https://docs.searxng.org)...';
          runBtn.innerHTML = '📄 本文抽出';
        } else {
          searchOpts.style.display = 'flex';
          scrapeOpts.style.display = 'none';
          if (mode === 'deep') {
            depthGroup.style.display = 'inline-flex';
            tokensGroup.style.display = 'inline-flex';
            siteGroup.style.display = 'inline-flex';
            presetChips.style.display = 'inline-flex';
            qInput.placeholder = 'Deep Search: 質問・エラー・技術キーワードを入力 (並列本文抽出 + BM25)...';
            runBtn.innerHTML = '⚡ Deep Search';
          } else {
            depthGroup.style.display = 'none';
            tokensGroup.style.display = 'none';
            siteGroup.style.display = 'none';
            presetChips.style.display = 'none';
            qInput.placeholder = 'Fast Search (json_lite): 検索キーワードを入力...';
            runBtn.innerHTML = '🚀 Fast Search';
          }
        }
      }

      document.querySelectorAll('.nav-tab').forEach(function (btn) {
        btn.addEventListener('click', function () {
          setMode(btn.dataset.mode);
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

      document.querySelectorAll('.ctx-tab').forEach(function (tab) {
        tab.addEventListener('click', function () {
          state.ctxTab = tab.dataset.ctx;
          document.querySelectorAll('.ctx-tab').forEach(function (t) {
            t.classList.toggle('active', t.dataset.ctx === state.ctxTab);
          });
          updateContextView();
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
        var a = document.createElement('a');
        a.href = URL.createObjectURL(blob);
        a.download = 'searxng-context.md';
        a.click();
      });

      function renderHighlights(container, highlights, fallbackContent) {
        var list = (highlights && highlights.length) ? highlights : (fallbackContent ? [fallbackContent] : []);
        list.forEach(function (h) {
          if (!h) return;
          if (h.indexOf('```') === 0) {
            var pre = document.createElement('pre');
            pre.className = 'highlight-code';
            pre.textContent = h.replace(/^```[a-zA-Z0-9_-]*\\n?/, '').replace(/```$/, '');
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
          } else if (item.source) {
            var srcPill = document.createElement('span');
            srcPill.className = 'pill';
            srcPill.textContent = item.source;
            badges.appendChild(srcPill);
          }

          top.appendChild(leftMeta);
          top.appendChild(badges);
          card.appendChild(top);

          var titleEl = document.createElement('div');
          titleEl.className = 'card-title';
          var link = document.createElement('a');
          link.href = item.url;
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
          scrapeBtn.addEventListener('click', function () {
            var existing = card.querySelector('.inline-scrape-drawer');
            if (existing) {
              existing.style.display = existing.style.display === 'none' ? 'block' : 'none';
              return;
            }
            var drawer = document.createElement('div');
            drawer.className = 'inline-scrape-drawer';
            drawer.textContent = '⏳ URLから本文を抽出中...';
            card.appendChild(drawer);
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
            var hText = (item.highlights && item.highlights.length) ? item.highlights.join('\\n\\n') : (item.content || '');
            var citeMd = '### [' + (idx + 1) + '] [' + (item.title || item.url) + '](' + item.url + ')\\n> ' + hText.replace(/\\n/g, '\\n> ');
            copyWithFeedback(citeMd, copyItemBtn, '✅ コピー完了');
          });

          if (domain) {
            var filterDomBtn = document.createElement('button');
            filterDomBtn.type = 'button';
            filterDomBtn.className = 'btn btn-sm';
            filterDomBtn.innerHTML = '🎯 site:' + domain;
            filterDomBtn.addEventListener('click', function () {
              document.getElementById('opt-site').value = domain;
              if (state.mode !== 'deep') setMode('deep');
              executeCurrentAction();
            });
            actions.appendChild(filterDomBtn);
          }

          actions.insertBefore(copyItemBtn, actions.firstChild);
          actions.insertBefore(scrapeBtn, actions.firstChild);
          card.appendChild(actions);
          container.appendChild(card);
        });
      }

      function runDeepSearch(query) {
        var depth = document.getElementById('opt-depth').value;
        var count = document.getElementById('opt-count').value;
        var maxTok = parseInt(document.getElementById('opt-tokens').value, 10) || 3000;
        var siteVal = document.getElementById('opt-site').value.trim();
        state.maxTokens = maxTok;

        var container = document.getElementById('results-container');
        container.innerHTML = '<div class="empty-state"><h2>⚡ Deep Search 実行中...</h2><p>メタ検索 → ドメイン権威スコアリング → 並列本文抽出 (trafilatura) → BM25 パッセージ抽出を実行しています。</p></div>';

        var params = new URLSearchParams({
          q: query,
          depth: depth,
          max_results: count,
          max_tokens: String(maxTok)
        });
        if (siteVal) params.set('site', siteVal);

        var url = '/deep_search?' + params.toString();
        var origin = window.location.origin;
        state.curlStr = 'curl -sG "' + origin + '/deep_search" --data-urlencode "q=' + query + '" --data-urlencode "depth=' + depth + '" --data-urlencode "format=markdown"';

        fetch(url)
          .then(function (r) { return r.json(); })
          .then(function (res) {
            if (res.error && (!res.results || !res.results.length)) {
              container.innerHTML = '<div class="empty-state"><h2 style="color:var(--danger);">⚠️ エラー</h2><p>' + res.error + '</p></div>';
              return;
            }
            state.markdown = res.markdown || '';
            state.prompt = res.rag_prompt || '';
            state.jsonStr = JSON.stringify(res, null, 2);

            var telBar = document.getElementById('telemetry-bar');
            var badges = document.getElementById('telemetry-badges');
            telBar.classList.add('visible');
            badges.innerHTML =
              '<span class="pill pill-accent">Intent: ' + (res.intent || 'general') + '</span>' +
              '<span class="pill pill-emerald">取得: ' + (res.results_count || 0) + '件 (本文抽出: ' + (res.scraped_count || 0) + '件)</span>' +
              '<span class="pill">~' + (res.estimated_tokens || 0) + ' tokens</span>' +
              '<span class="pill">' + (res.elapsed_ms || 0) + ' ms</span>';

            renderSearchResults(res.results || [], query);
            updateContextView();
          })
          .catch(function (err) {
            container.innerHTML = '<div class="empty-state"><h2 style="color:var(--danger);">⚠️ 通信エラー</h2><p>' + err + '</p></div>';
          });
      }

      function runFastSearch(query) {
        var count = parseInt(document.getElementById('opt-count').value, 10) || 5;
        var container = document.getElementById('results-container');
        container.innerHTML = '<div class="empty-state"><h2>🚀 Fast Search (json_lite) 実行中...</h2></div>';

        var t0 = performance.now();
        var url = '/search?q=' + encodeURIComponent(query) + '&format=json_lite';
        state.curlStr = 'curl -sG "' + window.location.origin + '/search" --data-urlencode "q=' + query + '" --data-urlencode "format=json_lite"';

        fetch(url)
          .then(function (r) { return r.json(); })
          .then(function (res) {
            var elapsed = Math.round(performance.now() - t0);
            var results = (res.results || []).slice(0, count);
            var mdLines = ['## Fast Search Results: `' + query + '`\\n'];
            if (res.answers && res.answers.length) {
              res.answers.forEach(function (a) { mdLines.push('> 💡 **Direct Answer**: ' + a + '\\n'); });
            }
            results.forEach(function (r, i) {
              var src = r.source ? ' `[' + r.source + ']`' : '';
              mdLines.push('### [' + (i + 1) + '] [' + (r.title || r.url) + '](' + r.url + ')' + src);
              if (r.content) mdLines.push('> ' + r.content + '\\n');
            });
            var md = mdLines.join('\\n').trim();
            var tok = estimateTokens(md);
            state.markdown = md;
            state.prompt = '以下のWeb検索結果を参考に質問に回答してください。\\n\\n## 質問\\n' + query + '\\n\\n## 検索結果\\n' + md;
            state.jsonStr = JSON.stringify(res, null, 2);

            var telBar = document.getElementById('telemetry-bar');
            var badges = document.getElementById('telemetry-badges');
            telBar.classList.add('visible');
            badges.innerHTML =
              '<span class="pill pill-accent">Format: json_lite</span>' +
              '<span class="pill pill-emerald">取得: ' + results.length + '件</span>' +
              '<span class="pill">~' + tok + ' tokens</span>' +
              '<span class="pill">' + elapsed + ' ms</span>';

            renderSearchResults(results, query);
            updateContextView();
          })
          .catch(function (err) {
            container.innerHTML = '<div class="empty-state"><h2 style="color:var(--danger);">⚠️ 通信エラー</h2><p>' + err + '</p></div>';
          });
      }

      function runScrapeMode(targetUrl) {
        var maxLen = document.getElementById('opt-scrape-len').value || '8000';
        var focusQ = document.getElementById('opt-scrape-query').value.trim();
        var container = document.getElementById('results-container');
        container.innerHTML = '<div class="empty-state"><h2>📄 URL 本文抽出中 (trafilatura)...</h2><p>' + targetUrl + '</p></div>';

        var api = '/api/scrape_analyze?url=' + encodeURIComponent(targetUrl) + '&max_length=' + encodeURIComponent(maxLen);
        if (focusQ) api += '&q=' + encodeURIComponent(focusQ);
        state.curlStr = 'curl -sG "' + window.location.origin + '/scrape" --data-urlencode "url=' + targetUrl + '"';

        fetch(api)
          .then(function (r) { return r.json(); })
          .then(function (res) {
            if (res.error) {
              container.innerHTML = '<div class="empty-state"><h2 style="color:var(--danger);">⚠️ 抽出エラー</h2><p>' + res.error + '</p></div>';
              return;
            }
            state.markdown = res.markdown || res.content || '';
            state.prompt = '以下のWebページ抽出本文を根拠として要点を解説してください。\\n\\nURL: ' + targetUrl + '\\n\\n' + state.markdown;
            state.jsonStr = JSON.stringify(res, null, 2);

            var telBar = document.getElementById('telemetry-bar');
            var badges = document.getElementById('telemetry-badges');
            telBar.classList.add('visible');
            badges.innerHTML =
              '<span class="pill pill-emerald">✅ 本文抽出完了 (' + (res.char_count || 0) + ' 文字)</span>' +
              '<span class="pill pill-accent">~' + (res.estimated_tokens || 0) + ' tokens</span>' +
              '<span class="pill">' + (res.elapsed_ms || 0) + ' ms</span>';

            container.innerHTML = '';
            var card = document.createElement('article');
            card.className = 'result-card';
            var title = document.createElement('div');
            title.className = 'card-title';
            var a = document.createElement('a');
            a.href = res.url;
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
              hlHeader.textContent = '🎯 BM25 関連ハイライト (' + res.query + ')';
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
            container.innerHTML = '<div class="empty-state"><h2 style="color:var(--danger);">⚠️ 通信エラー</h2><p>' + err + '</p></div>';
          });
      }

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
                title: '⚡ HTTP Deep Search API (/deep_search)',
                desc: '1回のHTTPリクエストで検索・並列スクレイピング・BM25ハイライト抽出を実行し、MarkdownまたはJSONを返します。',
                code: info.snippets.curl_deep_md + '\\n\\n# PowerShell:\\n' + info.snippets.pwsh_deep
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
            container.innerHTML = '<div class="empty-state"><p>エラー: ' + err + '</p></div>';
          });
      }

      function executeCurrentAction() {
        var qVal = document.getElementById('q').value.trim();
        if (!qVal) return;

        // Auto-detect URL in search bar if user pastes http(s)://...
        if (state.mode === 'scrape' || (/^https?:\\/\\//i.test(qVal) && qVal.indexOf(' ') === -1)) {
          if (state.mode !== 'scrape') setMode('scrape');
          runScrapeMode(qVal);
        } else if (state.mode === 'fast') {
          runFastSearch(qVal);
        } else {
          runDeepSearch(qVal);
        }
      }

      document.getElementById('ws-form').addEventListener('submit', function (e) {
        e.preventDefault();
        executeCurrentAction();
      });

      // Global keyboard shortcuts
      document.addEventListener('keydown', function (e) {
        var qInput = document.getElementById('q');
        if ((e.key === '/' && document.activeElement !== qInput && !['INPUT', 'TEXTAREA', 'SELECT'].includes(document.activeElement.tagName)) ||
            ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k')) {
          e.preventDefault();
          qInput.focus();
          qInput.select();
        }
      });

      // Parse initial URL parameters (?q=...&mode=...&depth=...)
      var urlParams = new URLSearchParams(window.location.search);
      var initMode = urlParams.get('mode');
      var initDepth = urlParams.get('depth');
      var initQ = urlParams.get('q') || urlParams.get('url');
      if (initDepth && ['advanced', 'code', 'basic'].indexOf(initDepth) !== -1) {
        document.getElementById('opt-depth').value = initDepth;
      }
      if (initMode && ['deep', 'fast', 'scrape', 'agent'].indexOf(initMode) !== -1) {
        setMode(initMode);
      }
      if (initQ) {
        document.getElementById('q').value = initQ;
        var classicLink = document.getElementById('classic-ui-link');
        if (classicLink && state.mode !== 'scrape') {
          classicLink.href = '/search?q=' + encodeURIComponent(initQ);
        }
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
    if "ai_workspace" in getattr(app, "view_functions", {}):
        return

    from flask import Response, jsonify, request

    @app.route("/ai", methods=["GET"])
    @app.route("/next", methods=["GET"])
    def ai_workspace() -> Any:
        """Render the lightweight AI Search & Context Studio."""
        return Response(AI_WORKSPACE_HTML, mimetype="text/html; charset=utf-8")

    @app.route("/ai/embed.css", methods=["GET"])
    def ai_embed_css() -> Any:
        """Serve lightweight CSS for SearXNG's native simple theme."""
        return Response(
            SIMPLE_EMBED_CSS,
            mimetype="text/css; charset=utf-8",
            headers={"Cache-Control": "public, max-age=300"},
        )

    @app.route("/ai/embed.js", methods=["GET"])
    def ai_embed_js() -> Any:
        """Serve progressive AI enhancement JS for SearXNG's native simple theme."""
        return Response(
            SIMPLE_EMBED_JS,
            mimetype="application/javascript; charset=utf-8",
            headers={"Cache-Control": "public, max-age=300"},
        )

    @app.route("/api/ai_info", methods=["GET"])
    def ai_info_route() -> Any:
        """Return instance AI capabilities and ready-to-copy MCP/CLI configs."""
        host_url = request.host_url.rstrip("/") if getattr(request, "host_url", None) else "http://127.0.0.1:8888"
        return jsonify(get_ai_info(webapp_mod=webapp_mod, host_url=host_url))

    @app.route("/api/scrape_analyze", methods=["GET", "POST"])
    def scrape_analyze_route() -> Any:
        """Extract clean article text, token estimate, and optional BM25 highlights from a URL."""
        payload = request.get_json(silent=True) if request.is_json else None
        payload = payload if isinstance(payload, dict) else {}

        url = request.values.get("url") or payload.get("url") or ""
        query = request.values.get("q") or request.values.get("query") or payload.get("q") or payload.get("query") or ""
        max_len = request.values.get("max_length") or payload.get("max_length") or 8000

        if not isinstance(url, str) or not url.strip():
            return jsonify({"error": "No URL provided", "url": "", "content": ""}), 400

        res = execute_scrape_analyze(
            url=url,
            query=str(query) if query else "",
            max_length=max_len,
            webapp_mod=webapp_mod,
        )
        status_code = 400 if res.get("error") and "拒否" in str(res.get("error")) else (422 if res.get("error") else 200)
        return jsonify(res), status_code

    @app.route("/deep_search", methods=["GET", "POST"])
    def deep_search_route() -> Any:
        """Exa/Tavily-style one-pass Deep Search HTTP endpoint."""
        payload = request.get_json(silent=True) if request.is_json else None
        payload = payload if isinstance(payload, dict) else {}

        query = (
            request.values.get("q")
            or request.values.get("query")
            or payload.get("q")
            or payload.get("query")
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
                return Response("### Error\n\nNo query provided.", status=400, mimetype="text/markdown; charset=utf-8")
            return jsonify({"error": "No query", "query": "", "results": []}), 400

        depth = (
            request.values.get("depth")
            or request.values.get("search_depth")
            or payload.get("search_depth")
            or payload.get("depth")
            or "advanced"
        )
        max_results = (
            request.values.get("max_results")
            or request.values.get("count")
            or request.values.get("n")
            or payload.get("max_results")
            or payload.get("count")
            or 5
        )
        max_tokens = (
            request.values.get("max_tokens")
            or payload.get("max_tokens")
            or 3000
        )
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

        res = execute_server_deep_search(
            query=query.strip(),
            webapp_mod=webapp_mod,
            search_depth=str(depth),
            max_results=max_results,
            include_highlights=inc_hl,
            include_domains=inc_domains or None,
            exclude_domains=exc_domains or None,
            max_tokens=max_tokens,
        )

        if out_fmt in ("markdown", "md"):
            return Response(res.get("markdown", ""), status=200, mimetype="text/markdown; charset=utf-8")

        return jsonify(res), 200
