#!/usr/bin/env python3
"""URL Normalizer for SearXNG Retrieval Pipeline.

Provides deterministic, security-aware URL normalization for search result deduplication,
canonicalization, and citation formatting.
"""

from __future__ import annotations

import functools
import ipaddress
import re
import socket
import urllib.parse
from typing import ClassVar

# Unicode full stops that UTS-46 maps to U+002E. A host registered under both
# spellings would otherwise defeat domain filters, source classification and
# same-domain deduplication.
_HOST_DOT_TRANSLATION: dict[int, str] = {0x3002: ".", 0xFF0E: ".", 0xFF61: "."}


def _normalize_host_spelling(host: str) -> str:
    """Fold Unicode full stops and strip the DNS root dot from a hostname."""
    return host.translate(_HOST_DOT_TRANSLATION).rstrip(".")


class URLNormalizer:
    """Normalizes web URLs for deduplication, clustering, and clean citations."""

    # Known analytics and advertising tracking query parameters
    TRACKING_PARAMS: ClassVar[set[str]] = {
        "utm_source",
        "utm_medium",
        "utm_campaign",
        "utm_term",
        "utm_content",
        "utm_id",
        "utm_reader",
        "utm_referrer",
        "utm_source_platform",
        "utm_creative_format",
        "utm_marketing_tactic",
        "fbclid",
        "gclid",
        "gclsrc",
        "dclid",
        "msclkid",
        "mc_eid",
        "yclid",
        "_ga",
        "_gl",
        "_hsenc",
        "_hsmi",
        "igshid",
        "srsltid",
        "zanpid",
        "ig_rid",
        "ref_src",
        "ref_url",
        "spm",
        "trk",
        "sc_cid",
    }

    # Query parameters that indicate a cryptographically signed or tokenized URL.
    # When present, query parameters must NEVER be stripped, or the URL will break.
    SIGNED_URL_INDICATORS: ClassVar[set[str]] = {
        "x-amz-signature",
        "x-amz-credential",
        "signature",
        "sig",
        "x-goog-signature",
        "x-goog-credential",
        "token",
        "authtoken",
    }

    # Default ports for standard schemes
    DEFAULT_PORTS: ClassVar[dict[str, int]] = {
        "http": 80,
        "https": 443,
        "ftp": 21,
    }

    UNRESERVED_PAT: ClassVar[re.Pattern[str]] = re.compile(r"%([0-9a-fA-F]{2})")

    @classmethod
    def is_signed_url(cls, query_params: dict[str, list[str]]) -> bool:
        """Check if any query parameter looks like a cryptographic signature or token."""
        lower_keys = {key.lower() for key in query_params}
        if lower_keys & cls.SIGNED_URL_INDICATORS:
            return True
        # Recognize Azure SAS multi-parameter signatures when paired with version `sv`
        return "sv" in lower_keys and bool(lower_keys & {"se", "sp", "sr", "st"})

    @classmethod
    def _unquote_unreserved(cls, match: re.Match) -> str:
        """Unquote percent-encoded bytes that represent RFC 3986 unreserved characters."""
        code = int(match.group(1), 16)
        # Unreserved characters: A-Z (65-90), a-z (97-122), 0-9 (48-57), -, ., _, ~
        if (
            (65 <= code <= 90)
            or (97 <= code <= 122)
            or (48 <= code <= 57)
            or code in (45, 46, 95, 126)  # '-', '.', '_', '~'
        ):
            return chr(code)
        # Otherwise normalize to uppercase percent encoding
        return f"%{code:02X}"

    @classmethod
    def normalize_percent_encoding(cls, path_or_query: str) -> str:
        """Normalize percent encodings: unescape unreserved characters and uppercase hex."""
        if "%" not in path_or_query:
            return path_or_query
        return cls.UNRESERVED_PAT.sub(cls._unquote_unreserved, path_or_query)

    @classmethod
    def normalize_host(cls, host: str | None, scheme: str) -> str:
        """Normalize host: lowercase, IDN punycode decode/encode safely, remove default port."""
        if not host:
            return ""

        raw = host.strip()
        if not raw:
            return ""

        userinfo, at_sep, hostport = raw.rpartition("@")
        h = hostport.strip()
        if not h:
            return raw

        # Handle bracketed IPv6 host like [::1]:8080
        port_suffix = ""
        if h.startswith("["):
            bracket_end = h.find("]")
            if bracket_end != -1:
                ip6_part = h[: bracket_end + 1]
                port_part = h[bracket_end + 1 :]
                if port_part.startswith(":"):
                    port_str = port_part[1:]
                    if port_str.isascii() and port_str.isdigit():
                        try:
                            p = int(port_str)
                            if p != cls.DEFAULT_PORTS.get(scheme.lower()):
                                port_suffix = f":{p}"
                        except ValueError:
                            port_suffix = port_part
                    else:
                        port_suffix = port_part
                norm_hostport = f"{ip6_part.lower()}{port_suffix}"
                return f"{userinfo}@{norm_hostport}" if at_sep else norm_hostport

        # Standard IPv4 or hostname with optional port
        if h.count(":") == 1:
            parts = h.split(":", 1)
            h_part = parts[0]
            if parts[1].isascii() and parts[1].isdigit():
                try:
                    p = int(parts[1])
                    if p != cls.DEFAULT_PORTS.get(scheme.lower()):
                        port_suffix = f":{p}"
                except ValueError:
                    port_suffix = f":{parts[1]}"
            else:
                port_suffix = f":{parts[1]}"
        else:
            h_part = h

        h_clean = h_part
        for dot in (chr(0x3002), chr(0xFF0E), chr(0xFF61)):
            h_clean = h_clean.replace(dot, ".")
        h_clean = h_clean.rstrip(".").lower()

        # Handle IDN (Internationalized Domain Names): encode to punycode (prefer UTS-46)
        try:
            import idna

            h_clean = idna.encode(h_clean, uts46=True).decode("ascii").lower()
        except Exception:  # noqa: BLE001
            try:
                h_clean = h_clean.encode("idna").decode("ascii").lower()
            except (UnicodeError, ValueError):
                pass

        norm_hostport = f"{h_clean}{port_suffix}"
        return f"{userinfo}@{norm_hostport}" if at_sep else norm_hostport

    @classmethod
    def normalize_url(
        cls,
        url: str,
        strip_tracking: bool = True,
        remove_fragment: bool = True,
        sort_params: bool = True,
    ) -> str:
        """Deterministically normalize URL string.

        Args:
            url: The input URL.
            strip_tracking: Whether to strip analytics/tracking query params (unless signed).
            remove_fragment: Whether to strip #fragment.
            sort_params: Whether to sort query parameters alphabetically.

        Returns:
            Normalized URL string. URLs carrying a recognised signature are
            returned verbatim (only control characters and, when requested,
            the fragment are removed) because re-encoding invalidates them.
        """
        raw = (url or "").strip()
        if not raw:
            return ""

        # Remove ASCII control characters
        raw = _CONTROL_CHARS_PATTERN.sub("", raw)
        if not raw:
            return ""

        try:
            parsed = urllib.parse.urlsplit(raw)
        except ValueError:
            return raw

        if not parsed.scheme and not parsed.netloc:
            return raw

        parsed_params = urllib.parse.parse_qs(parsed.query, keep_blank_values=True) if parsed.query else {}

        # Signed URLs (S3/GCS/Azure SAS, ...) are opaque: the signature covers the
        # exact path and query encoding, so any canonicalisation (trailing-slash
        # removal, percent-encoding changes, parameter sorting, scheme casing)
        # invalidates it. Preserve the original string and only honour the
        # fragment preference.
        if parsed_params and cls.is_signed_url(parsed_params):
            if remove_fragment:
                return raw.split("#", 1)[0]
            return raw

        scheme = (parsed.scheme or "http").lower()
        netloc = cls.normalize_host(parsed.netloc, scheme)

        # Normalize path
        raw_path = parsed.path or "/"
        # Remove duplicate slashes in path
        path = re.sub(r"/{2,}", "/", raw_path)
        path = cls.normalize_percent_encoding(path)

        # Remove trailing slash unless it is root '/' or indicates a directory
        if len(path) > 1 and path.endswith("/"):
            path = path.rstrip("/")

        cleaned_params: list[tuple[str, str]] = []
        for k, val_list in parsed_params.items():
            k_clean = k.strip()
            if strip_tracking and k_clean.lower() in cls.TRACKING_PARAMS:
                continue
            for v in val_list:
                cleaned_params.append((k_clean, v))

        if sort_params:
            cleaned_params.sort(key=lambda x: (x[0], x[1]))

        new_query = urllib.parse.urlencode(cleaned_params, doseq=True)
        new_query = cls.normalize_percent_encoding(new_query)

        fragment = "" if remove_fragment else (parsed.fragment or "")

        return urllib.parse.urlunsplit((scheme, netloc, path, new_query, fragment))

    @classmethod
    def get_dedup_key(cls, url: str) -> str:
        """Generate canonical key for deduplication comparison (ignores scheme and www prefix)."""
        norm = cls.normalize_url(url, strip_tracking=True, remove_fragment=True, sort_params=True)
        try:
            parsed = urllib.parse.urlsplit(norm)
            netloc = parsed.netloc.lower().removeprefix("www.")
            path = parsed.path.rstrip("/")
            query = f"?{parsed.query}" if parsed.query else ""
            return f"{netloc}{path}{query}"
        except ValueError:
            return norm.lower()

    @classmethod
    def extract_domain(cls, url: str) -> str:
        """Extract lowercase domain/netloc without www. prefix or root dot.

        Uses the same host spelling rules as :meth:`normalize_host` so that a
        ``site:`` filter, source classification and same-domain deduplication
        agree on FQDN-style (``example.com.``) and full-width hosts.
        """
        try:
            raw = (url or "").strip()
            if not raw:
                return ""
            raw = raw.translate(_HOST_DOT_TRANSLATION)
            if "://" not in raw and not raw.startswith("//"):
                first_part = raw.split("/", 1)[0]
                if "." in first_part and not any(c.isspace() for c in first_part):
                    raw = f"http://{raw}"
            parsed = urllib.parse.urlsplit(raw)
            netloc = _normalize_host_spelling((parsed.hostname or "").lower())
            return netloc.removeprefix("www.")
        except ValueError:
            return ""


@functools.lru_cache(maxsize=2048)
def normalize_url(url: str, strip_tracking: bool = True) -> str:
    """Convenience wrapper for URL normalizer."""
    return URLNormalizer.normalize_url(url, strip_tracking=strip_tracking)


@functools.lru_cache(maxsize=2048)
def get_dedup_key(url: str) -> str:
    """Convenience wrapper for dedup key extraction."""
    return URLNormalizer.get_dedup_key(url)


@functools.lru_cache(maxsize=2048)
def extract_domain(url: str) -> str:
    """Convenience wrapper for domain extraction."""
    return URLNormalizer.extract_domain(url)


def normalize_domain_list(
    value: str | list[str] | tuple[str, ...] | set[str] | None,
) -> list[str]:
    """Normalize a domain filter from a single string or an iterable.

    Accepts a comma-separated string, a list/tuple/set of strings, or ``None``.
    Entries may be full URLs; scheme, path, port, ``www.`` and surrounding
    dots/quotes are removed. Order is preserved and duplicates are dropped.
    """
    if not value:
        return []
    if isinstance(value, str):
        raw_items: list[str] = value.split(",")
    elif isinstance(value, (list, tuple, set)):
        raw_items = []
        for item in value:
            if item:
                raw_items.extend(str(item).split(","))
    else:
        return []

    cleaned: list[str] = []
    for item in raw_items:
        dom = (
            str(item)
            .strip()
            .strip("\"'")
            .lower()
            .removeprefix("https://")
            .removeprefix("http://")
            .split("/")[0]
            .split(":")[0]
            .removeprefix("www.")
            .translate(_HOST_DOT_TRANSLATION)
            .strip(".")
        )
        if dom and dom not in cleaned:
            cleaned.append(dom)
    return cleaned


_CONTROL_CHARS_PATTERN: re.Pattern[str] = re.compile(r"[\x00-\x1f\x7f]")

# URLs must percent-encode whitespace. Both the SSRF validator and the scraping
# transport use this single rule so a URL cannot be "safe" for one and invalid
# for the other.
FORBIDDEN_URL_CHARS_PATTERN: re.Pattern[str] = re.compile(r"[\x00-\x20\x7f]")


def contains_forbidden_url_chars(value: str) -> bool:
    """Return True when a URL contains raw whitespace or ASCII control characters."""
    return bool(FORBIDDEN_URL_CHARS_PATTERN.search(value or ""))


RESERVED_TLDS: tuple[str, ...] = (
    ".localhost",
    ".local",
    ".internal",
    ".lan",
    ".home.arpa",
    ".invalid",
    ".test",
    ".example",
    ".onion",
    ".corp",
    ".home",
    ".localdomain",
    ".intranet",
    ".private",
    ".arpa",
)

KNOWN_LOOPBACK_DOMAINS: tuple[str, ...] = (
    "localtest.me",
    "lvh.me",
    "vcap.me",
    "lacolhost.com",
    "localh4.st",
    "traefik.me",
)

WILDCARD_DNS_DOMAINS: tuple[str, ...] = (
    ".nip.io",
    ".sslip.io",
)

_WILDCARD_IPV4_PATTERN: re.Pattern[str] = re.compile(r"(?:^|[.-])(?P<ip>\d{1,4}(?:[.-]\d{1,4}){3})(?=[.-]|$)")
_WILDCARD_HEX_PATTERN: re.Pattern[str] = re.compile(r"(?:^|[.-])(?P<hex>[0-9a-fA-F]{8})(?=[.-]|$)")


def _is_ip_blocked(ip: ipaddress.IPv4Address | ipaddress.IPv6Address | str) -> bool:
    """Validate if an IP address is blocked (private, loopback, multicast, reserved, etc.)."""
    if not isinstance(ip, (ipaddress.IPv4Address, ipaddress.IPv6Address)):
        try:
            ip = ipaddress.ip_address(ip)
        except ValueError:
            return True

    if (
        ip.is_loopback
        or ip.is_private
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
        or not ip.is_global
    ):
        return True

    mapped = getattr(ip, "ipv4_mapped", None)
    if mapped is not None and _is_ip_blocked(mapped):
        return True
    s6to4 = getattr(ip, "sixtofour", None)
    if s6to4 is not None and _is_ip_blocked(s6to4):
        return True
    teredo = getattr(ip, "teredo", None)
    return bool(teredo is not None and (_is_ip_blocked(teredo[0]) or _is_ip_blocked(teredo[1])))


def _is_reserved_scrape_host(host: str) -> bool:
    """Check if host is a local, reserved, loopback, or private wildcard domain name."""
    h = (host or "").strip().rstrip(".").lower()
    if not h or h in ("localhost", "ip6-localhost", "ip6-loopback"):
        return True
    for tld in RESERVED_TLDS:
        bare = tld.lstrip(".")
        if h == bare or h.endswith(tld):
            return True
    for loopback_dom in KNOWN_LOOPBACK_DOMAINS:
        if h == loopback_dom or h.endswith("." + loopback_dom):
            return True
    for wc_dom in WILDCARD_DNS_DOMAINS:
        bare_wc = wc_dom.lstrip(".")
        if h == bare_wc or h.endswith(wc_dom):
            prefix = h[: -len(wc_dom)] if h.endswith(wc_dom) else ""
            if not prefix:
                return True
            for match_ip in _WILDCARD_IPV4_PATTERN.finditer(prefix):
                raw_ip = match_ip.group("ip").replace("-", ".")
                try:
                    ip_addr = ipaddress.IPv4Address(raw_ip)
                    if _is_ip_blocked(ip_addr):
                        return True
                except (ValueError, ipaddress.AddressValueError):
                    try:
                        packed = socket.inet_aton(raw_ip)
                        if _is_ip_blocked(ipaddress.IPv4Address(packed)):
                            return True
                    except (OSError, ValueError):
                        pass
            for match_hex in _WILDCARD_HEX_PATTERN.finditer(prefix):
                try:
                    ip_int = int(match_hex.group("hex"), 16)
                    if _is_ip_blocked(ipaddress.IPv4Address(ip_int)):
                        return True
                except (ValueError, ipaddress.AddressValueError):
                    pass
            for label in prefix.split("."):
                if "-" in label:
                    candidate_v6 = label.replace("-", ":")
                    try:
                        ip_v6 = ipaddress.IPv6Address(candidate_v6)
                        if _is_ip_blocked(ip_v6):
                            return True
                    except (ValueError, ipaddress.AddressValueError):
                        pass
    return False


def is_safe_retrieval_url(url: str, resolve_dns: bool = False) -> bool:
    """Validate that a URL is safe for external retrieval and scraping (SSRF protection).

    Enforces:
    - Only 'http' and 'https' schemes
    - Valid port (1-65535, rejects port 0)
    - No credentials (user:pass@host)
    - Rejects raw whitespace and ASCII control characters (0x00-0x20, 0x7F)
    - Rejects backslash characters anywhere in the URL (SSRF parser differential mitigation)
    - Rejects localhost, loopback, private, link-local, multicast, transition IPv4 and IPv6
    - Rejects hex/octal/decimal obfuscated IP formats
    - Rejects reserved TLDs and bare intranet hostnames
    - Optional active DNS resolution to detect private/loopback resolved IPs
    """
    if not url or not isinstance(url, str):
        return False

    if contains_forbidden_url_chars(url) or "\\" in url:
        return False

    clean_url = url.strip()
    if not clean_url:
        return False

    try:
        parsed = urllib.parse.urlsplit(clean_url)
    except ValueError:
        return False

    if parsed.scheme.lower() not in ("http", "https"):
        return False

    try:
        port = parsed.port
        if port is not None and (port <= 0 or port > 65535):
            return False
    except ValueError:
        return False

    # Block credentials or userinfo in URL (mitigates SSRF parser confusion)
    if parsed.username or parsed.password or "@" in (parsed.netloc or ""):
        return False

    # Backslashes were rejected for the whole URL above; keep this guard as a
    # second line of defence for callers that construct a ParseResult directly.
    if "\\" in (parsed.netloc or ""):
        return False

    raw_host = parsed.hostname or ""
    host = raw_host.strip().strip("[]").lower()
    for dot in (chr(0x3002), chr(0xFF0E), chr(0xFF61)):
        host = host.replace(dot, ".")
    host = host.rstrip(".")

    # Zone IDs (%) are only meaningful on IPv6 literals; reject % on all other hosts
    # so malformed hostnames like `8.8.8.8%25.internal` cannot be truncated.
    if "%" in host:
        if ":" not in host:
            return False
        host_base, zone_id = host.split("%", 1)
        if not zone_id:
            return False
        try:
            ip = ipaddress.IPv6Address(host_base)
        except ValueError:
            return False
        return not _is_ip_blocked(ip)

    if host and ":" not in host and not host.isascii():
        try:
            import idna

            host = idna.encode(host, uts46=True).decode("ascii").lower()
        except ImportError:
            try:
                host = host.encode("idna").decode("ascii").lower()
            except (UnicodeError, ValueError):
                return False
        except (UnicodeError, ValueError):
            return False

    if not host or _is_reserved_scrape_host(host):
        return False

    # Check direct IP addresses
    try:
        ip = ipaddress.ip_address(host)
        return not _is_ip_blocked(ip)
    except ValueError:
        if ":" in host:
            return False

    # Check numeric or obfuscated IP representations (e.g. 2130706433, 017700000001, or 0x7f000001)
    if host.replace(".", "").isdigit():
        if host.isdigit():
            try:
                ip_int = int(host)
                if not (0 <= ip_int <= 0xFFFFFFFF) or _is_ip_blocked(ipaddress.IPv4Address(ip_int)):
                    return False
            except (ValueError, ipaddress.AddressValueError):
                return False
            try:
                packed = socket.inet_aton(host)
                if _is_ip_blocked(ipaddress.IPv4Address(packed)):
                    return False
            except (OSError, ValueError, ipaddress.AddressValueError):
                pass
            return True

        try:
            packed = socket.inet_aton(host)
            ip_v4 = ipaddress.IPv4Address(packed)
            return not _is_ip_blocked(ip_v4)
        except (OSError, ValueError, ipaddress.AddressValueError):
            pass

        # An all-numeric host (with or without dots) that cannot be parsed as a valid IPv4 address
        # is invalid (RFC 3696 / ICANN forbids all-numeric TLDs) and must be rejected.
        return False

    if host.startswith(("0x", "0X", "0o", "0O", "0b", "0B")):
        try:
            ip_int = int(host, 0)
            if 0 <= ip_int <= 0xFFFFFFFF:
                ip_v4 = ipaddress.IPv4Address(ip_int)
                return not _is_ip_blocked(ip_v4)
        except (ValueError, ipaddress.AddressValueError):
            pass

        try:
            packed = socket.inet_aton(host)
            ip_v4 = ipaddress.IPv4Address(packed)
            return not _is_ip_blocked(ip_v4)
        except (OSError, ValueError, ipaddress.AddressValueError):
            pass

        return False

    if ":" not in host and "." not in host:
        # Bare single-label intranet hostname (e.g., 'payroll', 'nas', 'router')
        # All public web URLs require a dot-separated domain (RFC 3986 / ICANN prohibition of dotless domains).
        return False

    if ":" not in host and "." in host:
        try:
            packed = socket.inet_aton(host)
            ip_v4 = ipaddress.IPv4Address(packed)
            return not _is_ip_blocked(ip_v4)
        except (OSError, ValueError, ipaddress.AddressValueError):
            pass

    if resolve_dns:
        try:
            addr_info = socket.getaddrinfo(host, None)
            if not addr_info:
                return False
            for res in addr_info:
                ip_raw = str(res[4][0])
                if _is_ip_blocked(ip_raw):
                    return False
        except (socket.gaierror, ValueError, OSError):
            return False

    return True
