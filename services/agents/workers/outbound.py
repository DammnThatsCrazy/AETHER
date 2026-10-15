"""Outbound fetches for discovery workers — public internet addresses only.

Crawl and scan targets come from task payloads, so they are untrusted. A
fetch resolves the host, requires every resolved address to be globally
routable (``ipaddress`` ``is_global``, not multicast) after unwrapping
IPv4-mapped IPv6, NAT64 (``64:ff9b::/96``), 6to4 and Teredo, connects to
a validated address with the original ``Host`` header and TLS SNI (moving on
to the next validated address only when a connection cannot be established),
and follows at most three redirects by hand, re-validating every hop and
dropping credentials when the host changes or ``https`` downgrades to ``http``.

This mirrors the backend's ``shared.security.ssrf`` check; the Agent Layer is
a separate deployable and cannot import backend modules.
"""

from __future__ import annotations

import ipaddress
import socket
import urllib.parse

import httpx

MAX_REDIRECTS = 3
_NAT64_PREFIX = ipaddress.ip_network("64:ff9b::/96")
_REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})
_CREDENTIAL_HEADERS = frozenset({"authorization", "proxy-authorization", "cookie"})


class UnsafeDestinationError(ValueError):
    """The fetch target is malformed or not a public internet address."""


def is_public_address(value: str) -> bool:
    """True only for a globally routable unicast address (mapped/NAT64/6to4/Teredo unwrapped)."""
    try:
        addr = ipaddress.ip_address(value)
    except ValueError:
        return False
    candidates = [addr]
    if isinstance(addr, ipaddress.IPv6Address):
        if addr.ipv4_mapped is not None:
            candidates = [addr.ipv4_mapped]
        elif addr in _NAT64_PREFIX:
            candidates = [ipaddress.IPv4Address(int(addr) & 0xFFFFFFFF)]
        elif addr.sixtofour is not None:
            candidates = [addr.sixtofour]
        elif addr.teredo is not None:
            candidates = list(addr.teredo)
    return all(c.is_global and not c.is_multicast for c in candidates)


def resolve_public_addresses(url: str, *, allow_local: bool = False) -> list[str]:
    """Resolve *url*'s host; raise unless it is http(s) and every address is public."""
    try:
        parts = urllib.parse.urlsplit(url)
        port = parts.port
    except (TypeError, ValueError) as exc:
        raise UnsafeDestinationError("Cannot parse fetch URL") from exc
    host = parts.hostname
    if not host or parts.scheme not in ("http", "https"):
        raise UnsafeDestinationError("Not an http(s) URL with a host")
    try:
        ipaddress.ip_address(host)
        addresses = [host]
    except ValueError:
        try:
            infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
        except (OSError, UnicodeError) as exc:
            raise UnsafeDestinationError(f"DNS resolution failed for {host!r}: {exc}") from exc
        addresses = list(dict.fromkeys(str(info[4][0]) for info in infos))
    if not addresses:
        raise UnsafeDestinationError(f"No addresses resolved for {host!r}")
    if not allow_local:
        for address in addresses:
            if not is_public_address(address):
                raise UnsafeDestinationError(f"Host {host!r} resolves to non-public address {address!r}")
    return addresses


def _send_pinned(client: httpx.Client, url: str, headers: dict[str, str], allow_local: bool) -> httpx.Response:
    """GET each validated address in turn; only a failed connection moves on to the next."""
    logical = httpx.URL(url)
    requests = [
        client.build_request(
            "GET",
            logical.copy_with(host=address.split("%")[0]),
            headers={**headers, "Host": logical.netloc.decode("ascii")},
            extensions={"sni_hostname": logical.host},
        )
        for address in resolve_public_addresses(url, allow_local=allow_local)
    ]
    for request in requests[:-1]:
        try:
            return client.send(request, follow_redirects=False)
        except (httpx.ConnectError, httpx.ConnectTimeout):
            continue
    return client.send(requests[-1], follow_redirects=False)


def fetch_public(
    client: httpx.Client,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    allow_local: bool = False,
    max_redirects: int = MAX_REDIRECTS,
) -> tuple[httpx.Response, str]:
    """GET *url* through *client*, reaching only public addresses.

    Returns the final response and the final logical URL (the redirect target
    by hostname, not the pinned address). Raises :class:`UnsafeDestinationError`
    before connecting to a non-public destination or after too many redirects.
    """
    headers = {k: v for k, v in (headers or {}).items() if k.lower() != "host"}
    for _ in range(max_redirects + 1):
        response = _send_pinned(client, url, headers, allow_local)
        location = response.headers.get("location")
        if response.status_code not in _REDIRECT_STATUSES or not location:
            return response, url
        next_url = urllib.parse.urljoin(url, location)
        here, there = httpx.URL(url), httpx.URL(next_url)
        if there.netloc != here.netloc or (here.scheme == "https" and there.scheme != "https"):
            headers = {k: v for k, v in headers.items() if k.lower() not in _CREDENTIAL_HEADERS}
        url = next_url
    raise UnsafeDestinationError(f"Too many redirects (more than {max_redirects}) ending at host {httpx.URL(url).host!r}")
