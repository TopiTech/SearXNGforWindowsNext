import os
import re
import sys
import logging

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger("apply-patches")

# Determine repository root
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SITE_PACKAGES = os.path.join(REPO_ROOT, "python", "Lib", "site-packages")

def update_file(file_path, description, patch_func, *, required=True):
    if not os.path.exists(file_path):
        if required:
            raise RuntimeError(f"Required patch target not found for {description}: {file_path}")
        logger.warning(f"Optional file not found, skipping {description}: {file_path}")
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
    if "def get_json_lite_response" in content and "'score': d.get('score', 0)" in content and "_get_box" in content and "d.get('engines')" in content:
        return "ALREADY_APPLIED"

    lite_func = '''


def get_json_lite_response(sq: "SearchQuery", rc: "ResultContainer") -> str:
    """Returns a simplified JSON string (GenAI friendly)."""
    def _r(res):
        d = res.as_dict() if hasattr(res, 'as_dict') else (res if isinstance(res, dict) else {})
        return {
            'title': d.get('title', ''),
            'url': d.get('url', ''),
            'content': d.get('content', ''),
            'source': d.get('engine', '') or (', '.join(sorted(d.get('engines', []))) if d.get('engines') else ''),
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
        def _get_ans(a):
            if hasattr(a, 'as_dict'):
                return a.as_dict().get('answer', '')
            if isinstance(a, dict):
                return a.get('answer', '')
            return str(a)
        data['answers'] = [_get_ans(a) for a in rc.answers]
    if rc.infoboxes:
        def _get_box(i):
            d = i.as_dict() if hasattr(i, 'as_dict') else (i if isinstance(i, dict) else {})
            urls_raw = d.get('urls', []) if isinstance(d, dict) else getattr(i, 'urls', [])
            urls = []
            for u in urls_raw:
                if isinstance(u, dict):
                    urls.append({'title': u.get('title', ''), 'url': u.get('url', '')})
                else:
                    urls.append({'title': getattr(u, 'title', ''), 'url': getattr(u, 'url', '')})
            return {
                'infobox': d.get('infobox', '') if isinstance(d, dict) else getattr(i, 'infobox', ''),
                'content': d.get('content', '') if isinstance(d, dict) else getattr(i, 'content', ''),
                'urls': urls,
            }
        data['infoboxes'] = [_get_box(i) for i in rc.infoboxes]
    return json.dumps(data, cls=JSONEncoder)


'''
    # If old version exists, remove it first
    if "def get_json_lite_response" in content:
        content = re.sub(r'(?s)\n+def get_json_lite_response.*?return json\.dumps\(data, cls=JSONEncoder\)\n+', "\n", content)

    # Insert before get_themes while preserving a single blank-line boundary.
    # Match the line start optionally so the patch works whether get_themes is
    # the first definition in the module or follows other top-level code.
    content, count = re.subn(
        r'(^|\n)(def get_themes\b)',
        lite_func + r'\1\2',
        content,
    )
    return content

# --- Patch 3b: webutils.py (normalize Windows paths used in URL lookups) ---
def patch_webutils_windows_paths(content, path):
    required = (
        "file_list.append(str(f.relative_to(static_path)).replace(os.sep, '/'))",
        "result_templates.add(f.replace(os.sep, '/'))",
    )
    if all(anchor in content for anchor in required):
        return "ALREADY_APPLIED"

    replacements = {
        "file_list.append(str(f.relative_to(static_path)))":
            "file_list.append(str(f.relative_to(static_path)).replace(os.sep, '/'))",
        "result_templates.add(f)":
            "result_templates.add(f.replace(os.sep, '/'))",
    }
    patched = content
    for old, new in replacements.items():
        if old in patched:
            patched = patched.replace(old, new, 1)
    return patched


# --- Patch 3c: simple search templates (accessible search-field name) ---
def patch_simple_search_accessibility(content, path):
    """Give the primary search field an accessible, localized name.

    A placeholder is not a label and disappears once a query is entered.  The
    simple theme has icon-only controls already labelled with ``aria-label``;
    use the same localized text for its primary text input.
    """
    search_input = 'id="q" name="q" type="text"'
    accessible_search_input = 'id="q" name="q" type="text" aria-label="{{ _(\'Search for...\') }}"'
    if accessible_search_input in content:
        return "ALREADY_APPLIED"
    if search_input not in content:
        return content
    return content.replace(search_input, accessible_search_input, 1)


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
            r"(def index_error\b.*?\n\s*)if\s+output_format\s*==\s*['\"]json['\"]:",
            r"\1if output_format in ('json', 'json_lite'):",
            content, flags=re.S
        )
        if n == 0 and "output_format in ('json', 'json_lite')" not in content:
            logger.warning("Could not patch index_error for json_lite, anchor not found.")

    # 2. Add top-level `import ipaddress` (remove any indented duplicates first)
    if not re.search(r'^import ipaddress', content, re.M):
        content = re.sub(r'^\s+import ipaddress\n', '', content, flags=re.M)
        content, count = re.subn(r'(import warnings\n)', r'\1import ipaddress\n', content)
        if count == 0:
            content, count = re.subn(r'(from flask import\b|import flask\b)', r'import ipaddress\n\1', content)
        if count == 0:
            raise RuntimeError(f"Patch failed for {path}: Could not find insertion point for 'import ipaddress'.")

    # 3. Inject json_lite handler before json handler (stable anchor point)
    if "output_format == 'json_lite'" not in content:
        handler = (
            "\n    if output_format == 'json_lite':\n"
            "        response = webutils.get_json_lite_response(search_query, result_container)\n"
            "        return Response(response, mimetype='application/json')\n\n"
        )
        content, count = re.subn(
            r"(?m)^(\s*if\s+output_format\s*==\s*['\"]json['\"]:\s*\n\s*response\s*=\s*webutils\.get_json_response)",
            handler + r"\1",
            content
        )
        if count == 0:
            content, count = re.subn(r"(# 3\. formats without a template\r?\n)", r"\1" + handler, content)
        if count == 0:
            raise RuntimeError(f"Patch failed for {path}: Could not find json format handler anchor to inject json_lite handler.")

    return content

# --- Patch 5: webapp.py (/scrape route + trafilatura & socket & contextlib & threading imports + thread-safe pinned_dns + reusable httpx client) ---
def patch_webapp_scrape_route(content, path):
    required_anchors = [
        "def scrape()",
        "_is_blocked_scrape_host",
        "_RESERVED_TLDS",
        "pinned_dns",
        "_scrape_client",
        "_scrape_client_lock",
        "_scrape_client_verify_ssl",
        "_thread_local_dns",
        "def _parse_scrape_url",
        "def _read_scrape_response",
        "_SCRAPE_MAX_RESPONSE_BYTES",
        "Fetched response exceeds size limit",
        "Blocked invalid scheme",
        "Redirect without Location header",
        "verify_ssl = os.environ.get('SEARXNG_SCRAPE_VERIFY_SSL', 'true').lower() in ('true', '1', 'yes')", # default should be true
        "max_keepalive_connections=20",
        "_searxng_original_getaddrinfo",
        "v15-bulletproof-scrape-fix",
        "import re",
        "import html",
        "import httpx",
        "import idna",
        "trust_env=False",
        "class _ScrapeBlockedError",
    ]
    if all(anchor in content for anchor in required_anchors):
        return "ALREADY_APPLIED"

    # 1. Add imports at module level (ensure re, html, httpx, and idna are present)
    for mod in ('re', 'html', 'httpx', 'idna'):
        if f'import {mod}' not in content:
            content, count = re.subn(r'(import warnings\n)', f'import {mod}\n' + r'\1', content, count=1)
            if count == 0:
                content, count = re.subn(r'(from flask import\b|import flask\b)', f'import {mod}\n' + r'\1', content, count=1)
            if count == 0:
                raise RuntimeError(f"Patch failed for {path}: Could not find import anchor for {mod}.")
    if 'import trafilatura' not in content:
        content, count = re.subn(r'(import flask\b|from flask import\b)', r'import trafilatura\nimport socket\nimport contextlib\nimport threading\n\1', content, count=1)
        if count == 0:
            content, count = re.subn(r'(import warnings\n)', r'import trafilatura\nimport socket\nimport contextlib\nimport threading\n\1', content, count=1)
        if count == 0:
            raise RuntimeError(f"Patch failed for {path}: Could not find import anchor for trafilatura.")
    else:
        # ensure socket, contextlib, and threading exist
        for mod in ('socket', 'contextlib', 'threading'):
            if f'import {mod}' not in content:
                content, count = re.subn(r'(import trafilatura\n)', r'\1' + f'import {mod}\n', content)
                if count == 0:
                    content, count = re.subn(r'(from flask import\b|import flask\b)', f'import {mod}\n' + r'\1', content, count=1)
                if count == 0:
                    raise RuntimeError(f"Patch failed for {path}: Could not find import anchor for {mod}.")

    # 2. Clean ALL previous helper blocks and scrape routes completely (idempotency & duplicate removal)
    while '# --- GenAI Scrape Helpers ---' in content:
        content = re.sub(r'(?s)\n# --- GenAI Scrape Helpers ---.*?(?=\n@app\.route|\n# --- GenAI Scrape Helpers ---|\Z)', '', content, count=1)
    
    while "@app.route('/scrape'" in content or '@app.route("/scrape"' in content:
        content = re.sub(r'(?s)\n@app\.route\(\s*[\'"]/scrape[\'"].*?(?=\n@app\.route|\Z)', '', content, count=1)

    # 3. Inject global client holder and pinned_dns context manager before scrape route
    # Also define the new route
    scrape_route_code = '''

# --- GenAI Scrape Helpers ---
class _ScrapeBlockedError(Exception):
    """Raised by /scrape when a request is denied for security reasons."""


class _ScrapeResponseTooLargeError(Exception):
    """Raised when an upstream /scrape response exceeds the memory budget."""


_SCRAPE_MAX_RESPONSE_BYTES = 5 * 1024 * 1024


def _read_scrape_response(response):
    content_length = response.headers.get('content-length')
    if content_length and content_length.isdigit() and int(content_length) > _SCRAPE_MAX_RESPONSE_BYTES:
        raise _ScrapeResponseTooLargeError()

    chunks = []
    total = 0
    for chunk in response.iter_bytes():
        total += len(chunk)
        if total > _SCRAPE_MAX_RESPONSE_BYTES:
            raise _ScrapeResponseTooLargeError()
        chunks.append(chunk)

    body = b''.join(chunks)
    encoding = response.encoding or 'utf-8'
    try:
        return body.decode(encoding, errors='replace')
    except (LookupError, ValueError):
        return body.decode('utf-8', errors='replace')


_scrape_client = None
_scrape_client_lock = threading.Lock()
_scrape_client_verify_ssl = None
_thread_local_dns = threading.local()
if not hasattr(socket, '_searxng_original_getaddrinfo'):
    socket._searxng_original_getaddrinfo = socket.getaddrinfo
_original_getaddrinfo = socket._searxng_original_getaddrinfo

def _safe_getaddrinfo(h, p, *args, **kwargs):
    pin = getattr(_thread_local_dns, 'pin', None)
    if pin:
        pin_host = pin.get('host')
        host_matches = False
        if pin_host:
            h_clean = (h or '').rstrip('.').lower()
            pin_clean = pin_host.rstrip('.').lower()
            if h_clean == pin_clean:
                host_matches = True
            else:
                try:
                    enc_h = idna.encode(h_clean).decode('ascii')
                    enc_pin = idna.encode(pin_clean).decode('ascii')
                    host_matches = (enc_h == enc_pin)
                except Exception:
                    pass

        if host_matches:
            pin_port = pin.get('port')
            port_matches = (
                p is None
                or p == pin_port
                or str(p) == str(pin_port)
                or (pin_port == 443 and p == 'https')
                or (pin_port == 80 and p == 'http')
            )
            if port_matches:
                try:
                    ip_obj = ipaddress.ip_address(pin['ip'])
                    port_num = int(pin_port or (443 if p in (443, 'https') else 80))
                    req_family = args[0] if len(args) > 0 else kwargs.get('family', 0)
                    ip_family = socket.AF_INET6 if ip_obj.version == 6 else socket.AF_INET
                    if req_family in (0, ip_family):
                        sockaddr = (pin['ip'], port_num, 0, 0) if ip_obj.version == 6 else (pin['ip'], port_num)
                        return [(ip_family, socket.SOCK_STREAM, socket.IPPROTO_TCP, '', sockaddr)]
                    else:
                        raise socket.gaierror(socket.EAI_NONAME, f'Address family not supported for pinned host {pin_host}')
                except socket.gaierror:
                    raise
                except Exception:
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


_RESERVED_TLDS = (
    '.localhost', '.local', '.internal', '.lan', '.home.arpa',
    '.invalid', '.test', '.example', '.onion', '.corp', '.home',
)


def _is_blocked_scrape_host(host):
    host = (host or '').strip().rstrip('.').lower()
    if not host or host == 'localhost' or any(host.endswith(tld) for tld in _RESERVED_TLDS):
        return True
    if '%' in host:
        host = host.split('%', 1)[0]
    try:
        ip = ipaddress.ip_address(host)
        return not ip.is_global
    except ValueError:
        pass

    try:
        for res in socket.getaddrinfo(host, None):
            if not ipaddress.ip_address(res[4][0]).is_global:
                return True
    except (socket.gaierror, ValueError):
        pass
    return False


@app.route('/scrape', methods=['GET', 'POST'])
def scrape():
    """Extract main text content from URL (GenAI friendly, SSRF-protected).
    # v15-bulletproof-scrape-fix

    SECURITY: Blocks loopback, private/reserved IP ranges, link-local, and
    file:// scheme to prevent SSRF attacks and internal resource exposure.
    DNS Rebinding is mitigated via thread-safe DNS pinning, allowing SSL verification to remain enabled.

    NOTE: SSL verification is enabled by default.
    Set SEARXNG_SCRAPE_VERIFY_SSL=false to disable validation if needed.
    """
    url = sxng_request.values.get('url')
    if not url:
        json_data = sxng_request.get_json(silent=True)
        if json_data and isinstance(json_data, dict):
            url = json_data.get('url')
    if not url or not isinstance(url, str) or not url.strip():
        return jsonify({'error': 'No URL provided'}), 400
    url = url.strip()

    def _parse_scrape_url(value):
        try:
            parsed_url = urllib.parse.urlparse(value)
            # Accessing .port validates malformed or out-of-range ports.
            parsed_url.port
            return parsed_url
        except ValueError as exc:
            raise _ScrapeBlockedError('Invalid URL') from exc

    def _fetch_scrape_url(request_url):
        global _scrape_client, _scrape_client_verify_ssl
        verify_ssl = os.environ.get('SEARXNG_SCRAPE_VERIFY_SSL', 'true').lower() in ('true', '1', 'yes')
        ua = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
              'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36')

        with _scrape_client_lock:
            if _scrape_client is None or _scrape_client_verify_ssl != verify_ssl:
                # Reusable HTTP client with connection pooling and explicit limits
                scrape_limits = httpx.Limits(max_keepalive_connections=20, max_connections=50)
                if _scrape_client is not None:
                    try:
                        _scrape_client.close()
                    except Exception:
                        pass
                # Do not inherit proxy or CA settings from the process environment.
                # In particular, routing through HTTP(S)_PROXY would make the
                # proxy resolve the user-controlled hostname and bypass the DNS
                # validation and pinning performed below.
                _scrape_client = httpx.Client(
                    timeout=10.0,
                    follow_redirects=False,
                    verify=verify_ssl,
                    limits=scrape_limits,
                    trust_env=False,
                )
                _scrape_client_verify_ssl = verify_ssl

        def _get_safe_ip_url(url_to_resolve):
            parsed = urllib.parse.urlparse(url_to_resolve)
            if parsed.scheme not in ('http', 'https'):
                raise _ScrapeBlockedError(f'Blocked invalid scheme: {parsed.scheme}')

            host = parsed.hostname
            if not host:
                raise _ScrapeBlockedError('Empty hostname')

            host_clean = host.strip().rstrip('.').lower()
            if host_clean == 'localhost' or any(host_clean.endswith(tld) for tld in _RESERVED_TLDS):
                raise _ScrapeBlockedError(f'Blocked: {host} is a private/reserved host')

            if '%' in host_clean:
                host_clean = host_clean.split('%', 1)[0]

            try:
                ip_direct = ipaddress.ip_address(host_clean)
                if not ip_direct.is_global:
                    raise _ScrapeBlockedError(f'Blocked: {host} is a private/reserved IP')
            except ValueError:
                pass

            try:
                port = parsed.port or (443 if parsed.scheme == 'https' else 80)
                addr_info = socket.getaddrinfo(host, port)
                if not addr_info:
                    raise _ScrapeBlockedError(f'Could not resolve host: {host}')
                valid_ips = []
                for res in addr_info:
                    ip_raw = res[4][0]
                    ip_obj = ipaddress.ip_address(ip_raw)
                    if not ip_obj.is_global:
                        raise _ScrapeBlockedError(f'Blocked: {host} resolves to a private/reserved IP: {ip_raw}')
                    valid_ips.append(ip_raw)
                if not valid_ips:
                    raise _ScrapeBlockedError(f'Could not find a global IP for {host}')
                return valid_ips[0], host, port
            except _ScrapeBlockedError:
                raise
            except socket.gaierror as e:
                raise _ScrapeBlockedError(f'DNS resolution failed for {host}: {e}')
            except Exception as e:
                raise RuntimeError(f'DNS resolution failed for {host}: {e}')

        current_url = request_url
        for _ in range(5):
            cur_parsed = _parse_scrape_url(current_url)
            if cur_parsed.scheme not in ('http', 'https'):
                raise _ScrapeBlockedError(f'Blocked invalid scheme during redirect: {cur_parsed.scheme}')

            safe_ip, original_host, port = _get_safe_ip_url(current_url)
            headers = {'User-Agent': ua}

            # Use thread-safe DNS Pinning context manager
            with pinned_dns(original_host, safe_ip, port):
                # The host in current_url remains example.com, so TLS verify works,
                # but the socket connects directly to safe_ip.
                with _scrape_client.stream('GET', current_url, headers=headers) as response:
                    if response.status_code not in (301, 302, 303, 307, 308):
                        response.raise_for_status()
                        return _read_scrape_response(response)

                    location = response.headers.get('location')
                    if not location:
                        raise RuntimeError(f'Redirect without Location header (status {response.status_code})')
                    current_url = urllib.parse.urljoin(current_url, location)
        else:
            raise RuntimeError('Too many redirects')

    try:
        parsed = _parse_scrape_url(url)
    except _ScrapeBlockedError as e:
        return jsonify({'error': str(e)}), 400
    if parsed.scheme not in ('http', 'https') or _is_blocked_scrape_host(parsed.hostname):
        return jsonify({'error': 'Invalid or blocked URL'}), 400

    try:
        downloaded = _fetch_scrape_url(url) or ''
        content_text = trafilatura.extract(
            downloaded, include_comments=False, include_tables=True
        )
        if not content_text and downloaded:
            # Fallback to basic HTML text extraction if trafilatura returns None/empty
            raw_text = re.sub(r'(?s)<script.*?>.*?</script>', ' ', downloaded)
            raw_text = re.sub(r'(?s)<style.*?>.*?</style>', ' ', raw_text)
            raw_text = re.sub(r'<[^>]+>', ' ', raw_text)
            raw_text = html.unescape(raw_text)
            raw_text = re.sub(r'\s+', ' ', raw_text).strip()
            if raw_text:
                content_text = raw_text[:5000]

        if not content_text:
            return jsonify({'error': 'Could not extract content'}), 422

        return jsonify({'url': url, 'content': content_text})
    except _ScrapeResponseTooLargeError:
        return jsonify({'error': 'Fetched response exceeds size limit'}), 502
    except httpx.TimeoutException as e:
        return jsonify({'error': f'Fetch timeout: {str(e)[:100]}'}), 504
    except httpx.HTTPError as e:
        return jsonify({'error': f'Fetch failed: {str(e)[:100]}'}), 502
    except _ScrapeBlockedError as e:
        return jsonify({'error': str(e)[:100]}), 400
    except RuntimeError as e:
        return jsonify({'error': str(e)[:100]}), 502
    except Exception as e:
        return jsonify({'error': f'Fetch failed: {str(e)[:100]}'}), 500

'''

    content, count = re.subn(r"(?m)^(\s*@app\.route\(\s*['\"]/search['\"])", lambda m: scrape_route_code + m.group(1), content)
    if count == 0:
        raise RuntimeError(f"Patch failed for {path}: Could not find @app.route('/search') anchor to inject /scrape route.")

    return content



# --- Patch 6: engines/__init__.py (restore upstream disabled-engine semantics) ---
def patch_engines_init(content, path):
    """Undo legacy patches that made ``disabled`` act like ``inactive``.

    SearXNG keeps disabled engines loaded so users can enable them in
    preferences or invoke them with a bang.  Only ``inactive`` means removed.
    This cleanup is retained so existing installations are repaired on the
    next patch run; pristine upstream files are left unchanged.
    """
    early_return_block = """
    # Early return for engines that are intentionally disabled or inactive in config.
    if engine_data.get('inactive') is True:
        logger.debug('Engine \"%s\" is inactive in config, skipping load', engine_name)
        return None
    if engine_data.get('disabled') is True:
        logger.debug('Engine \"%s\" is disabled in config, skipping load', engine_name)
        return None
"""
    combined_loop_block = """        if engine_data.get(\"inactive\") is True or engine_data.get(\"disabled\") is True:
            logger.debug(
                \"loading engine %s skipped: inactive or disabled in config!\",
                engine_data.get(\"name\", \"???\"),
            )
            continue
"""

    patched = content.replace(early_return_block, "")
    patched = patched.replace(
        combined_loop_block,
        '        if engine_data.get("inactive") is True:\n            continue\n',
    )
    return "ALREADY_APPLIED" if patched == content else patched


# --- Patch 7: search/processors/__init__.py (restore upstream disabled-engine semantics) ---
def patch_processors_init(content, path):
    injected_block = """            if eng_settings.get("disabled", False) is True:
                logger.debug("Engine '%s' is disabled in config, skipping processor init.", eng_name)
                continue
"""
    patched = content.replace(injected_block, "")
    return "ALREADY_APPLIED" if patched == content else patched

# --- Patch 8: engines/google.py (fix CAPTCHA false positives) ---
def patch_google_captcha(content, path):
    if 'loc = (resp.headers.get("Location")' in content:
        return "ALREADY_APPLIED"
    old = (
        "    if resp.status_code == 302:\n"
        "        raise SearxEngineCaptchaException()\n"
        "\n"
        "    if len(resp.text) < 2000 and \"/sorry/\" in resp.text:\n"
        "        raise SearxEngineCaptchaException()"
    )
    new = (
        "    if resp.status_code == 302:\n"
        "        loc = (resp.headers.get(\"Location\") or resp.headers.get(\"location\") or \"\")\n"
        "        if \"/sorry\" in loc or \"sorry.google.com\" in loc or not loc:\n"
        "            raise SearxEngineCaptchaException()\n"
        "\n"
        "    if len(resp.text) < 2000 and \"/sorry/\" in resp.text:\n"
        "        raise SearxEngineCaptchaException()"
    )
    if old in content:
        return content.replace(old, new)
    return content

# --- Patch 9: engines/sogou.py (robust CAPTCHA detection) ---
def patch_sogou_captcha(content, path):
    if "antispider" in content and "captcha" in content.lower() and "resp.headers.get" in content:
        return "ALREADY_APPLIED"
    old = (
        "def response(resp):\n"
        "    if (\n"
        "        resp.status_code == 302\n"
        "        and resp.next_request is not None\n"
        "        and str(resp.next_request.url).startswith(\"http://www.sogou.com/antispider\")\n"
        "    ):\n"
        "        raise SearxEngineCaptchaException()"
    )
    new = (
        "def response(resp):\n"
        "    if resp.status_code == 302:\n"
        "        loc = resp.headers.get(\"Location\") or resp.headers.get(\"location\") or \"\"\n"
        "        if \"antispider\" in loc or \"sogou.com/antispider\" in loc:\n"
        "            raise SearxEngineCaptchaException()\n"
        "        if resp.next_request is not None and str(resp.next_request.url).startswith(\"http://www.sogou.com/antispider\"):\n"
        "            raise SearxEngineCaptchaException()\n"
        "        text_preview = (resp.text or \"\")[:4096]\n"
        "        if \"antispider\" in text_preview or \"captcha\" in text_preview.lower():\n"
        "            raise SearxEngineCaptchaException()\n"
        "    if resp.status_code == 200:\n"
        "        text_preview = (resp.text or \"\")[:8192].lower()\n"
        "        if \"antispider\" in text_preview and (\"captcha\" in text_preview or \"verify\" in text_preview):\n"
        "            if \"class=\\\"result\\\"\" not in text_preview and \"class=\\\"rb\\\"\" not in text_preview:\n"
        "                raise SearxEngineCaptchaException()"
    )
    if old in content:
        return content.replace(old, new)
    return content

# --- Patch 10: search/processors/abstract.py (restore configured suspension times) ---
def patch_abstract_suspend(content, path):
    """Undo the legacy global cap that overrode ``suspended_times``.

    ``max_ban_time_on_fail`` applies to ordinary engine failures.  Explicit
    SearXNG access-denied and CAPTCHA exceptions carry their own values from
    ``search.suspended_times`` and must retain those configured values.
    """
    legacy = (
        "            suspended_time = min(suspended_time, get_setting(\"search.max_ban_time_on_fail\"))\n"
        "            if \"captcha\" in suspend_reason.lower() or \"SearxEngineCaptcha\" in suspend_reason:\n"
        "                suspended_time = min(suspended_time, 900)\n"
        "            if suspended_time > 120 and self.continuous_errors == 1:\n"
        "                suspended_time = min(suspended_time, 120)\n"
        "\n"
        "            self.suspend_end_time = default_timer() + suspended_time\n"
        "            self.suspend_reason = suspend_reason\n"
        "            logger.debug(\"Suspend for %i seconds\", suspended_time)"
    )
    upstream = (
        "            self.suspend_end_time = default_timer() + suspended_time\n"
        "            self.suspend_reason = suspend_reason\n"
        "            logger.debug(\"Suspend for %i seconds\", suspended_time)"
    )
    patched = content.replace(legacy, upstream)
    return "ALREADY_APPLIED" if patched == content else patched

# --- Patch 11: search/processors/online.py (Retry-After + CAPTCHA logging) ---
def patch_online_captcha(content, path):
    if "_parse_retry_after_header" in content:
        patched = content.replace("            e.suspended_time = min(e.suspended_time, 900)\n", "")
        return "ALREADY_APPLIED" if patched == content else patched
    old_import = "from searx.metrics.error_recorder import count_error\nfrom .abstract import EngineProcessor, RequestParams"
    new_import = (
        "from searx.metrics.error_recorder import count_error\n"
        "from .abstract import EngineProcessor, RequestParams\n"
        "\n"
        "\n"
        "def _parse_retry_after_header(resp) -> int | None:\n"
        "    if resp is None:\n"
        "        return None\n"
        "    try:\n"
        "        hdr = None\n"
        "        if hasattr(resp, 'headers'):\n"
        "            hdr = resp.headers.get('Retry-After') or resp.headers.get('retry-after')\n"
        "        if hdr is None:\n"
        "            return None\n"
        "        hdr = hdr.strip()\n"
        "        if hdr.isdigit():\n"
        "            v = int(hdr)\n"
        "            return max(5, min(v, 900))\n"
        "    except Exception:\n"
        "        pass\n"
        "    return None"
    )
    if old_import in content:
        content = content.replace(old_import, new_import)
    old_block = (
        "        except (\n"
        "            SearxEngineCaptchaException,\n"
        "            SearxEngineTooManyRequestsException,\n"
        "            SearxEngineAccessDeniedException,\n"
        "        ) as e:\n"
        "            self.handle_exception(result_container, e, suspend=True)\n"
        "            self.logger.debug(e.message)"
    )
    new_block = (
        "        except SearxEngineCaptchaException as e:\n"
        "            retry_after = _parse_retry_after_header(getattr(e, 'response', None))\n"
        "            if retry_after is not None:\n"
        "                e.suspended_time = min(e.suspended_time, retry_after)\n"
        "            self.handle_exception(result_container, e, suspend=True)\n"
        "            self.logger.warning(\"CAPTCHA %s suspended for %ss: %s\", self.engine.name, e.suspended_time, e.message)\n"
        "        except (\n"
        "            SearxEngineTooManyRequestsException,\n"
        "            SearxEngineAccessDeniedException,\n"
        "        ) as e:\n"
        "            self.handle_exception(result_container, e, suspend=True)\n"
        "            self.logger.debug(e.message)"
    )
    if old_block in content:
        content = content.replace(old_block, new_block)
    return content

# --- Patch 12: settings.yml / settings_defaults.py (reduce suspended_times) ---
def patch_settings_yml(content, path):
    if "SearxEngineCaptcha: 900" in content:
        return "ALREADY_APPLIED"
    content = re.sub(r'SearxEngineCaptcha:\s*\d+', 'SearxEngineCaptcha: 900', content)
    content = re.sub(r'SearxEngineAccessDenied:\s*\d+', 'SearxEngineAccessDenied: 900', content)
    content = re.sub(r'SearxEngineTooManyRequests:\s*\d+', 'SearxEngineTooManyRequests: 600', content)
    content = re.sub(r'cf_SearxEngineCaptcha:\s*\d+', 'cf_SearxEngineCaptcha: 3600', content)
    content = re.sub(r'recaptcha_SearxEngineCaptcha:\s*\d+', 'recaptcha_SearxEngineCaptcha: 3600', content)
    return content

def patch_config_settings_yml(content, path):
    if "SearxEngineCaptcha: 900" in content:
        return "ALREADY_APPLIED"
    # If user has custom SearxEngineCaptcha (not legacy 86400/3600), or if absent, preserve user customization
    if re.search(r'SearxEngineCaptcha:\s*(?!86400|3600)\d+', content) or "SearxEngineCaptcha" not in content:
        return "ALREADY_APPLIED"
    patched = patch_settings_yml(content, path)
    if patched == content:
        # Preserve user customization without raising RuntimeError in update_file
        return "ALREADY_APPLIED"
    return patched

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
        os.path.join(SITE_PACKAGES, "searx", "webutils.py"),
        "webutils.py (normalize Windows paths)",
        patch_webutils_windows_paths
    )
    update_file(
        os.path.join(SITE_PACKAGES, "searx", "templates", "simple", "search.html"),
        "templates/simple/search.html (accessible search label)",
        patch_simple_search_accessibility
    )
    update_file(
        os.path.join(SITE_PACKAGES, "searx", "templates", "simple", "simple_search.html"),
        "templates/simple/simple_search.html (accessible search label)",
        patch_simple_search_accessibility
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
        "engines/__init__.py (restore disabled-engine behavior)",
        patch_engines_init
    )
    update_file(
        os.path.join(SITE_PACKAGES, "searx", "search", "processors", "__init__.py"),
        "search/processors/__init__.py (restore disabled-engine behavior)",
        patch_processors_init
    )
    update_file(
        os.path.join(SITE_PACKAGES, "searx", "engines", "google.py"),
        "engines/google.py (CAPTCHA false-positive fix)",
        patch_google_captcha
    )
    update_file(
        os.path.join(SITE_PACKAGES, "searx", "engines", "sogou.py"),
        "engines/sogou.py (robust CAPTCHA detection)",
        patch_sogou_captcha
    )
    update_file(
        os.path.join(SITE_PACKAGES, "searx", "search", "processors", "abstract.py"),
        "search/processors/abstract.py (restore configured suspension times)",
        patch_abstract_suspend
    )
    update_file(
        os.path.join(SITE_PACKAGES, "searx", "search", "processors", "online.py"),
        "search/processors/online.py (Retry-After + CAPTCHA logging)",
        patch_online_captcha
    )
    update_file(
        os.path.join(SITE_PACKAGES, "searx", "settings.yml"),
        "searx/settings.yml (reduce suspended_times defaults)",
        patch_settings_yml
    )
    update_file(
        os.path.join(REPO_ROOT, "config", "settings.yml"),
        "config/settings.yml (reduce suspended_times)",
        patch_config_settings_yml,
        required=False
    )

    logger.info("All patches processed.")

if __name__ == "__main__":
    main()
