"""
Outbound HTTP for cover images.

Cover URLs reach the server through query parameters and form fields, so they
are not trusted: only http(s) to public addresses is allowed (no file://, no
localhost, no LAN hosts), redirects are checked the same way, and responses
are size-capped.
"""

import ipaddress
import socket
import urllib.request
from urllib.parse import urlsplit

# Generous for a cover or a variant page scan
MAX_IMAGE_BYTES = 25 * 1024 * 1024


class UnsafeURLError(ValueError):
    """Raised when a URL points somewhere a cover fetch must not go."""


def check_url(url: str) -> None:
    """Raise UnsafeURLError unless url is http(s) to a public address."""
    parts = urlsplit(url or "")
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise UnsafeURLError(f"Only http(s) URLs are allowed: {url!r}")
    try:
        infos = socket.getaddrinfo(parts.hostname, parts.port or 443, proto=socket.IPPROTO_TCP)
    except socket.gaierror as e:
        raise UnsafeURLError(f"Cannot resolve {parts.hostname}: {e}")
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if not ip.is_global:
            raise UnsafeURLError(f"Refusing non-public address {ip} for {parts.hostname}")


def host_matches(url: str, domain: str) -> bool:
    """True if url's host is domain or a subdomain of it."""
    host = (urlsplit(url or "").hostname or "").lower()
    return host == domain or host.endswith("." + domain)


class _CheckedRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        check_url(newurl)
        new = super().redirect_request(req, fp, code, msg, headers, newurl)
        # Never forward credentials to another host
        if new is not None and urlsplit(newurl).hostname != urlsplit(req.full_url).hostname:
            new.remove_header("Authorization")
        return new


_opener = urllib.request.build_opener(_CheckedRedirectHandler)


def safe_fetch(url: str, headers: dict = None, timeout: int = 15, max_bytes: int = MAX_IMAGE_BYTES) -> bytes:
    """
    GET url and return the body. Raises UnsafeURLError for disallowed URLs or
    oversized responses, and the usual URLError/OSError for network errors.
    """
    check_url(url)
    req = urllib.request.Request(url, headers=headers or {})
    with _opener.open(req, timeout=timeout) as resp:
        data = resp.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise UnsafeURLError(f"Response larger than {max_bytes} bytes: {url}")
    return data
