#!/usr/bin/env python3
"""URL Normalizer for SearXNG Retrieval Pipeline.

Provides deterministic, security-aware URL normalization for search result deduplication,
canonicalization, and citation formatting.
"""

from __future__ import annotations

import ipaddress
import re
import socket
import urllib.parse
from typing import ClassVar


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
        "se",  # Azure SAS token expiry
        "sp",  # Azure SAS token permissions
        "sv",  # Azure SAS token version
        "st",  # Azure SAS token start
        "token",
        "authtoken",
    }

    # Default ports for standard schemes
    DEFAULT_PORTS: ClassVar[dict[str, int]] = {
        "http": 80,
        "https": 443,
        "ftp": 21,
    }

    UNRESERVED_PAT: ClassVar[re.Pattern] = re.compile(r"%([0-9a-fA-F]{2})")

    @classmethod
    def is_signed_url(cls, query_params: dict[str, list[str]]) -> bool:
        """Check if any query parameter looks like a cryptographic signature or token."""
        for key in query_params:
            if key.lower() in cls.SIGNED_URL_INDICATORS:
                return True
        return False

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

        h = host.strip()
        # Handle bracketed IPv6 host like [::1]:8080
        port_suffix = ""
        if h.startswith("["):
            bracket_end = h.find("]")
            if bracket_end != -1:
                ip6_part = h[: bracket_end + 1]
                port_part = h[bracket_end + 1 :]
                if port_part.startswith(":"):
                    port_str = port_part[1:]
                    if port_str.isdigit():
                        p = int(port_str)
                        if p != cls.DEFAULT_PORTS.get(scheme.lower()):
                            port_suffix = f":{p}"
                return f"{ip6_part.lower()}{port_suffix}"

        # Standard IPv4 or hostname with optional port
        if ":" in h:
            parts = h.split(":", 1)
            h_part = parts[0]
            if parts[1].isdigit():
                p = int(parts[1])
                if p != cls.DEFAULT_PORTS.get(scheme.lower()):
                    port_suffix = f":{p}"
            else:
                port_suffix = f":{parts[1]}"
        else:
            h_part = h

        h_clean = h_part.rstrip(".").lower()

        # Handle IDN (Internationalized Domain Names): encode to punycode
        try:
            h_clean = h_clean.encode("idna").decode("ascii").lower()
        except (UnicodeError, ValueError):
            pass

        return f"{h_clean}{port_suffix}"

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
            Normalized URL string.
        """
        raw = (url or "").strip()
        if not raw:
            return ""

        try:
            parsed = urllib.parse.urlsplit(raw)
        except ValueError:
            return raw

        if not parsed.scheme and not parsed.netloc:
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

        # Parse query params
        query_str = parsed.query or ""
        if query_str:
            parsed_params = urllib.parse.parse_qs(query_str, keep_blank_values=True)
            is_signed = cls.is_signed_url(parsed_params)

            cleaned_params: list[tuple[str, str]] = []
            for k, val_list in parsed_params.items():
                k_clean = k.strip()
                k_lower = k_clean.lower()
                if strip_tracking and not is_signed and k_lower in cls.TRACKING_PARAMS:
                    continue
                for v in val_list:
                    cleaned_params.append((k_clean, v))

            if sort_params and not is_signed:
                cleaned_params.sort(key=lambda x: (x[0], x[1]))

            new_query = urllib.parse.urlencode(cleaned_params, doseq=True)
            new_query = cls.normalize_percent_encoding(new_query)
        else:
            new_query = ""

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
        """Extract lowercase domain/netloc without www. prefix."""
        try:
            parsed = urllib.parse.urlsplit(url.strip())
            netloc = (parsed.hostname or "").lower()
            return netloc.removeprefix("www.")
        except ValueError:
            return ""


def normalize_url(url: str, strip_tracking: bool = True) -> str:
    """Convenience wrapper for URL normalizer."""
    return URLNormalizer.normalize_url(url, strip_tracking=strip_tracking)


def get_dedup_key(url: str) -> str:
    """Convenience wrapper for dedup key extraction."""
    return URLNormalizer.get_dedup_key(url)


def extract_domain(url: str) -> str:
    """Convenience wrapper for domain extraction."""
    return URLNormalizer.extract_domain(url)


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


def _is_reserved_scrape_host(host: str) -> bool:
    """Check if host is a local or reserved domain name."""
    h = (host or "").strip().rstrip(".").lower()
    if not h or h in ("localhost", "ip6-localhost", "ip6-loopback"):
        return True
    for tld in RESERVED_TLDS:
        bare = tld.lstrip(".")
        if h == bare or h.endswith(tld):
            return True
    return False


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


def is_safe_retrieval_url(url: str) -> bool:
    """Validate that a URL is safe for external retrieval and scraping (SSRF protection).

    Enforces:
    - Only 'http' and 'https' schemes
    - Valid port (1-65535, rejects port 0)
    - No credentials (user:pass@host)
    - Rejects localhost, loopback, private, link-local, multicast, transition IPv4 and IPv6
    - Rejects hex/octal/decimal obfuscated IP formats
    - Rejects reserved TLDs and bare intranet hostnames
    """
    if not url or not isinstance(url, str):
        return False

    clean_url = url.strip()
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

    # Block credentials in URL
    if parsed.username or parsed.password:
        return False

    host = (parsed.hostname or "").strip().rstrip(".").lower()
    if not host or _is_reserved_scrape_host(host):
        return False

    # Remove IPv6 zone index if present
    if "%" in host:
        host = host.split("%", 1)[0]

    # Check direct IP addresses
    try:
        ip = ipaddress.ip_address(host)
        return not _is_ip_blocked(ip)
    except ValueError:
        pass

    # Check numeric or obfuscated IP representations (e.g. 2130706433 or 0x7f000001)
    if host.isdigit():
        try:
            ip_int = int(host)
            if 0 <= ip_int <= 0xFFFFFFFF:
                ip_v4 = ipaddress.IPv4Address(ip_int)
                return not _is_ip_blocked(ip_v4)
        except (ValueError, ipaddress.AddressValueError):
            return False

    if host.startswith(("0x", "0X", "0o", "0O")):
        try:
            ip_int = int(host, 0)
            if 0 <= ip_int <= 0xFFFFFFFF:
                ip_v4 = ipaddress.IPv4Address(ip_int)
                return not _is_ip_blocked(ip_v4)
        except (ValueError, ipaddress.AddressValueError):
            return False

    if ":" not in host and "." in host and any(part.isdigit() for part in host.split(".")):
        try:
            packed = socket.inet_aton(host)
            ip_v4 = ipaddress.IPv4Address(packed)
            return not _is_ip_blocked(ip_v4)
        except (OSError, ValueError, ipaddress.AddressValueError):
            pass

    return True
