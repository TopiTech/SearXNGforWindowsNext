import os
import re
import sys
import logging

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger("apply-patches")

# Determine repository root
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SITE_PACKAGES = os.path.join(REPO_ROOT, "python", "Lib", "site-packages")

def update_file(file_path, description, patch_func):
    if not os.path.exists(file_path):
        logger.warning(f"File not found, skipping {description}: {file_path}")
        return "SKIPPED"

    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()

    result = patch_func(content, file_path)

    if result == "ALREADY_APPLIED":
        logger.info(f"Already applied: {description}")
        return "ALREADY_APPLIED"
    elif result == content:
        raise RuntimeError(f"Patch failed for {description}: Upstream code may have changed, could not find injection point in {file_path}.")
    else:
        with open(file_path, 'w', encoding='utf-8', newline='\n') as f:
            f.write(result)
        logger.info(f"Patched: {description}")
        return "PATCHED"

# --- Patch 1: valkeydb.py (Windows compatibility: pwd → os.environ fallback) ---
def patch_valkeydb(content, path):
    if ('def _windows_safe_current_user():' in content
            and '_user_name, _user_uid = _windows_safe_current_user()' in content):
        return "ALREADY_APPLIED"

    # 1. Wrap Unix-only `import pwd` in try/except
    content = re.sub(
        r'^import pwd$',
        "try:\n    import pwd  # Unix only\nexcept ImportError:\n    pwd = None",
        content, flags=re.M
    )

    # 2. Inject Windows fallback function after logger (PEP 8: 2 blank lines)
    helper = '''


def _windows_safe_current_user():
    """Get current user safely on Windows (where pwd module is unavailable)."""
    if pwd is not None and hasattr(os, "getuid"):
        try:
            _pw = pwd.getpwuid(os.getuid())
            return _pw.pw_name, _pw.pw_uid
        except Exception:
            pass
    # Windows fallback
    username = (
        os.environ.get("USERNAME")
        or os.environ.get("USER")
        or os.environ.get("LOGNAME")
        or "windows"
    )
    return username, -1
'''
    if 'def _windows_safe_current_user():' in content:
        content = re.sub(
            r'\n{1,3}def _windows_safe_current_user\(\):.*?return username, -1',
            helper.rstrip(), content, flags=re.S
        )
    else:
        content = re.sub(
            r'(logger = logging\.getLogger\(__name__\))',
            r'\1' + helper, content
        )

    # 3. Replace call-site (indent-aware, exclude nested blocks)
    content = re.sub(
        r'^(\s{1,8})_pw = pwd\.getpwuid\(os\.getuid\(\)\)',
        r'\1_user_name, _user_uid = _windows_safe_current_user()',
        content, flags=re.M
    )

    # 4. Update logger.exception call with new variables
    content = re.sub(
        r'^(\s{1,8})logger\.exception\(".*?can\'t connect valkey DB \.\.\..*?\)',
        r'\1logger.exception("[%s (%s)] can\'t connect valkey DB ...", _user_name, _user_uid)',
        content, flags=re.M
    )
    return content

# --- Patch 2: settings_defaults.py (register json_lite output format) ---
def patch_settings_defaults(content, path):
    if "'json_lite'" in content:
        return "ALREADY_APPLIED"

    match = re.search(r"(?ms)(OUTPUT_FORMATS\s*=\s*\[)(.*?)(\])", content)
    if not match:
        return content

    body = match.group(2)
    if re.search(r"(?m)^\s*['\"]json_lite['\"]\s*,?\s*$", body):
        return "ALREADY_APPLIED"

    if re.search(r"(?m)^\s*['\"]json['\"]\s*,?\s*$", body):
        body = body.rstrip()
        if not body.endswith(","):
            body += ","
        body += "\n    'json_lite'"
    else:
        body = body.rstrip() + ", 'json_lite'"

    return content[:match.start()] + match.group(1) + body + match.group(3) + content[match.end():]

# --- Patch 3: webutils.py (add get_json_lite_response, optimised) ---
def patch_webutils(content, path):
    if "def get_json_lite_response" in content and "'score': d.get('score', 0)" in content:
        return "ALREADY_APPLIED"

    lite_func = '''


def get_json_lite_response(sq: "SearchQuery", rc: "ResultContainer") -> str:
    """Returns a simplified JSON string (GenAI friendly)."""
    def _r(res):
        d = res.as_dict()
        return {
            'title': d.get('title', ''),
            'url': d.get('url', ''),
            'content': d.get('content', ''),
            'source': d.get('engine', ''),
            'score': d.get('score', 0),
            'published_date': d.get('pubdate') or d.get('publishedDate'),
            'author': d.get('author', ''),
            'category': d.get('category', ''),
        }
    data = {
        'query': sq.query,
        'results': [_r(r) for r in rc.get_ordered_results()[:20]],
        'suggestions': list(rc.suggestions),
        'corrections': list(rc.corrections),
    }
    if rc.answers:
        data['answers'] = [a.as_dict().get('answer') for a in rc.answers]
    if rc.infoboxes:
        data['infoboxes'] = [
            {
                'infobox': getattr(i, 'infobox', ''),
                'content': getattr(i, 'content', ''),
                'urls': [{'title': u.get('title'), 'url': u.get('url')}
                         for u in getattr(i, 'urls', [])],
            }
            for i in rc.infoboxes
        ]
    return json.dumps(data, cls=JSONEncoder)


'''
    # If old version exists, remove it first
    if "def get_json_lite_response" in content:
        content = re.sub(r'(?s)\n+def get_json_lite_response.*?return json\.dumps\(data, cls=JSONEncoder\)\n+', "\n", content)

    # Insert before get_themes while preserving a single blank-line boundary.
    content, count = re.subn(r'(\n)(def get_themes\b)', lite_func + r'\1\2', content)
    return content

# --- Patch 4: webapp.py (json_lite handler + ipaddress import) ---
def patch_webapp_json_handler(content, path):
    checks = [
        "output_format in ('json', 'json_lite')" in content,
        "output_format == 'json_lite'" in content,
        bool(re.search(r'^import ipaddress', content, re.M))
    ]
    if all(checks):
        return "ALREADY_APPLIED"

    # 1. Widen index_error() to handle json_lite (include in json error path)
    if "output_format in ('json', 'json_lite')" not in content:
        content, n = re.subn(
            r"(def index_error\b.*?\n\s+)if output_format == 'json':",
            r"\1if output_format in ('json', 'json_lite'):",
            content, flags=re.S
        )
        if n == 0:
            return content

    # 2. Add top-level `import ipaddress` (remove any indented duplicates first)
    if not re.search(r'^import ipaddress', content, re.M):
        content = re.sub(r'^\s+import ipaddress\n', '', content, flags=re.M)
        # Try to anchor after warnings
        content, count = re.subn(r'(import warnings\n)', r'\1import ipaddress\n', content)
        if count == 0:
            content, count = re.subn(r'(import httpx\n)', r'import ipaddress\n\1', content)
        if count == 0:
            return content

    # 3. Inject json_lite handler before json handler (stable anchor point)
    if "output_format == 'json_lite'" not in content:
        handler = (
            "\n    if output_format == 'json_lite':\n"
            "        response = webutils.get_json_lite_response(search_query, result_container)\n"
            "        return Response(response, mimetype='application/json')\n\n"
        )
        content, count = re.subn(
            r"(?m)^(    if output_format == 'json':\n\n        response = webutils\.get_json_response)",
            handler + r"    if output_format == 'json':\n\n        response = webutils.get_json_response",
            content
        )
        if count == 0:
            content, count = re.subn(r"(# 3\. formats without a template\r?\n)", r"\1" + handler, content)
        if count == 0:
            return content

    return content

# --- Patch 5: webapp.py (/scrape route + trafilatura & socket & contextlib & threading imports + thread-safe pinned_dns + reusable httpx client) ---
def patch_webapp_scrape_route(content, path):
    required_anchors = [
        "def scrape()",
        "_is_blocked_scrape_host",
        "pinned_dns",
        "_scrape_client",
        "_thread_local_dns",
        "Blocked invalid scheme",
        "Redirect without Location header",
        "verify_ssl = os.environ.get('SEARXNG_SCRAPE_VERIFY_SSL', 'true').lower() in ('true', '1', 'yes')" # default should be true
    ]
    if all(anchor in content for anchor in required_anchors):
        return "ALREADY_APPLIED"

    # 1. Add `import trafilatura`, `import socket`, `import contextlib`, `import threading` at module level
    if 'import trafilatura' not in content:
        content, count = re.subn(r'(import flask\b)', r'import trafilatura\nimport socket\nimport contextlib\nimport threading\n\1', content)
        if count == 0:
            return content
    else:
        # ensure socket, contextlib, and threading exist
        for mod in ('socket', 'contextlib', 'threading'):
            if f'import {mod}' not in content:
                content, count = re.subn(r'(import trafilatura\n)', f'\\1import {mod}\n', content)
                if count == 0:
                    content, count = re.subn(r'(import flask\b)', f'import {mod}\n\\1', content)
                if count == 0:
                    return content

    # 2. Clean stale /scrape route (idempotency)
    content = re.sub(
        r'\n@app\.route\(\'/scrape\'[^\n]*\)\ndef scrape\(\):.*?(?=\n\n@app\.route|\n@app\.route|\Z)',
        '\n', content, flags=re.S
    )

    # 3. Inject global client holder and pinned_dns context manager before scrape route
    # Also define the new route
    scrape_route_code = '''

# --- GenAI Scrape Helpers ---
_scrape_client = None
_thread_local_dns = threading.local()
_original_getaddrinfo = socket.getaddrinfo

def _safe_getaddrinfo(h, p, *args, **kwargs):
    pin = getattr(_thread_local_dns, 'pin', None)
    if pin and h == pin.get('host') and (p == pin.get('port') or p is None):
        try:
            ip_obj = ipaddress.ip_address(pin['ip'])
            family = socket.AF_INET6 if ip_obj.version == 6 else socket.AF_INET
            sockaddr = (pin['ip'], pin['port'], 0, 0) if ip_obj.version == 6 else (pin['ip'], pin['port'])
            return [(family, socket.SOCK_STREAM, socket.IPPROTO_TCP, '', sockaddr)]
        except ValueError:
            pass
    return _original_getaddrinfo(h, p, *args, **kwargs)

socket.getaddrinfo = _safe_getaddrinfo


@contextlib.contextmanager
def pinned_dns(host, ip, port):
    """Thread-safe DNS pinning using threading.local().
    Bypasses standard DNS resolution for a specific host/port to a target IP
    within the current thread execution context.
    """
    _thread_local_dns.pin = {'host': host, 'ip': ip, 'port': port}
    try:
        yield
    finally:
        _thread_local_dns.pin = None


@app.route('/scrape', methods=['GET', 'POST'])
def scrape():
    """Extract main text content from URL (GenAI friendly, SSRF-protected).
    # v4-sni-fix

    SECURITY: Blocks loopback, private/reserved IP ranges, link-local, and
    file:// scheme to prevent SSRF attacks and internal resource exposure.
    DNS Rebinding is mitigated via thread-safe DNS pinning, allowing SSL verification to remain enabled.

    NOTE: SSL verification is enabled by default.
    Set SEARXNG_SCRAPE_VERIFY_SSL=false to disable validation if needed.
    """
    url = sxng_request.values.get('url')
    if not url and sxng_request.is_json and sxng_request.json:
        url = sxng_request.json.get('url')
    if not url:
        return jsonify({'error': 'No URL provided'}), 400

    def _is_blocked_scrape_host(host):
        host = (host or '').strip().rstrip('.').lower()
        if not host or host == 'localhost' or host.endswith('.localhost'):
            return True
        if '%' in host:
            host = host.split('%', 1)[0]
        try:
            ip = ipaddress.ip_address(host)
            if not ip.is_global:
                return True
        except ValueError:
            pass

        try:
            for res in socket.getaddrinfo(host, None):
                if not ipaddress.ip_address(res[4][0]).is_global:
                    return True
        except (socket.gaierror, ValueError):
            pass
        return False

    def _fetch_scrape_url(request_url):
        global _scrape_client
        verify_ssl = os.environ.get('SEARXNG_SCRAPE_VERIFY_SSL', 'true').lower() in ('true', '1', 'yes')
        ua = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
              'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36')

        if _scrape_client is None:
            # Reusable HTTP client with connection pooling
            _scrape_client = httpx.Client(timeout=10.0, follow_redirects=False, verify=verify_ssl)

        def _get_safe_ip_url(url_to_resolve):
            parsed = urllib.parse.urlparse(url_to_resolve)
            if parsed.scheme not in ('http', 'https'):
                raise RuntimeError(f'Blocked invalid scheme: {parsed.scheme}')

            host = parsed.hostname
            if _is_blocked_scrape_host(host):
                raise RuntimeError(f'Blocked: {host} is a private/reserved host')

            try:
                port = parsed.port or (443 if parsed.scheme == 'https' else 80)
                addr_info = socket.getaddrinfo(host, port)
                for res in addr_info:
                    ip_raw = res[4][0]
                    ip_obj = ipaddress.ip_address(ip_raw)
                    if ip_obj.is_global:
                        return ip_raw, host, port
                raise RuntimeError(f'Could not find a global IP for {host}')
            except Exception as e:
                raise RuntimeError(f'DNS resolution failed for {host}: {e}')

        current_url = request_url
        for _ in range(5):
            cur_parsed = urllib.parse.urlparse(current_url)
            if cur_parsed.scheme not in ('http', 'https'):
                raise RuntimeError(f'Blocked invalid scheme during redirect: {cur_parsed.scheme}')

            safe_ip, original_host, port = _get_safe_ip_url(current_url)
            headers = {'User-Agent': ua}

            # Use thread-safe DNS Pinning context manager
            with pinned_dns(original_host, safe_ip, port):
                # The host in current_url remains example.com, so TLS verify works,
                # but the socket connects directly to safe_ip.
                response = _scrape_client.get(current_url, headers=headers)

            if response.status_code not in (301, 302, 303, 307, 308):
                response.raise_for_status()
                return response.text

            location = response.headers.get('location')
            if not location:
                raise RuntimeError(f'Redirect without Location header (status {response.status_code})')
            current_url = urllib.parse.urljoin(current_url, location)
        else:
            raise RuntimeError('Too many redirects')

    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ('http', 'https') or _is_blocked_scrape_host(parsed.hostname):
        return jsonify({'error': 'Invalid or blocked URL'}), 400

    try:
        downloaded = _fetch_scrape_url(url)
        content_text = trafilatura.extract(
            downloaded, include_comments=False, include_tables=True
        )
        if not content_text:
            return jsonify({'error': 'Could not extract content'}), 422

        return jsonify({'url': url, 'content': content_text})
    except httpx.HTTPError as e:
        return jsonify({'error': f'Fetch failed: {str(e)[:100]}'}), 502
    except Exception as e:
        return jsonify({'error': f'Fetch failed: {str(e)[:100]}'}), 500

'''

    content, count = re.subn(r"(@app\.route\('/search')", scrape_route_code + r'\1', content)
    if count == 0:
        return content

    return content


# --- Patch 6: engines/__init__.py (check disabled flag BEFORE loading module) ---
def patch_engines_init(content, path):
    if "skipping load" in content or "inactive or disabled in config!" in content:
        return "ALREADY_APPLIED"

    # 1. Patch load_engine (singular) - add early return for disabled/inactive
    inject_code = """
    # Early return for engines that are intentionally disabled or inactive in config.
    if engine_data.get('inactive') is True:
        logger.debug('Engine "%s" is inactive in config, skipping load', engine_name)
        return None
    if engine_data.get('disabled') is True:
        logger.debug('Engine "%s" is disabled in config, skipping load', engine_name)
        return None
"""
    pattern = r"(if engine_name\.lower\(\) != engine_name:.*?engine_data\['name'\] = engine_name\n)"
    content, count = re.subn(pattern, r"\1" + inject_code, content, flags=re.S)
    if count == 0:
        return content

    # 2. Patch load_engines (plural) - skip loading disabled engines to avoid noise
    inject_loop = """
        if engine_data.get("inactive") is True or engine_data.get("disabled") is True:
            logger.debug(
                "loading engine %s skipped: inactive or disabled in config!",
                engine_data.get("name", "???"),
            )
            continue"""

    pattern = r"(def load_engines\(engine_list:.*?for engine_data in engine_list:)"
    content, count = re.subn(pattern, r"\1" + inject_loop, content, flags=re.S)
    if count == 0:
        pattern = r"(for engine_data in engine_list:)"
        content, count = re.subn(pattern, r"\1" + inject_loop, content, count=1)

    if count == 0:
        return content

    return content

# --- Patch 7: search/processors/__init__.py (skip intentionally disabled engines) ---
def patch_processors_init(content, path):
    if "skipping processor init" in content:
        return "ALREADY_APPLIED"

    pattern = r"(if eng_settings\.get\(\"inactive\", False\) is True:\s+continue)"
    inject_code = """
            if eng_settings.get("disabled", False) is True:
                logger.debug("Engine '%s' is disabled in config, skipping processor init.", eng_name)
                continue"""

    content, count = re.subn(pattern, r"\1" + inject_code, content)
    return content

def main():
    logger.info("Applying Windows compatibility and feature patches...")
    
    # Run patches
    update_file(
        os.path.join(SITE_PACKAGES, "searx", "valkeydb.py"),
        "valkeydb.py (Windows pwd compatibility)",
        patch_valkeydb
    )
    update_file(
        os.path.join(SITE_PACKAGES, "searx", "settings_defaults.py"),
        "settings_defaults.py (json_lite format)",
        patch_settings_defaults
    )
    update_file(
        os.path.join(SITE_PACKAGES, "searx", "webutils.py"),
        "webutils.py (get_json_lite_response)",
        patch_webutils
    )
    update_file(
        os.path.join(SITE_PACKAGES, "searx", "webapp.py"),
        "webapp.py (json_lite handler)",
        patch_webapp_json_handler
    )
    update_file(
        os.path.join(SITE_PACKAGES, "searx", "webapp.py"),
        "webapp.py (/scrape endpoint)",
        patch_webapp_scrape_route
    )
    update_file(
        os.path.join(SITE_PACKAGES, "searx", "engines", "__init__.py"),
        "engines/__init__.py (check disabled before module load)",
        patch_engines_init
    )
    update_file(
        os.path.join(SITE_PACKAGES, "searx", "search", "processors", "__init__.py"),
        "search/processors/__init__.py (skip disabled engines)",
        patch_processors_init
    )

    logger.info("All patches processed.")

if __name__ == "__main__":
    main()
