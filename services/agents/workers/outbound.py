"""Outbound fetches for discovery workers — public internet addresses only.

Crawl and scan targets come from task payloads, so they are untrusted. A
fetch resolves the host, requires every resolved address to be globally
routable (``ipaddress`` ``is_global``, not multicast) after unwrapping
IPv4-mapped IPv6 and the NAT64 well-known prefix ``64:ff9b::/96``, connects to
the validated address with the original ``Host`` header and TLS SNI, and
follows at most three redirects by hand, re-validating every hop and dropping
credentials when the host changes.

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
    """True only for a globally routable unicast address (mapped/NAT64 unwrapped)."""
    try:
        addr = ipaddress.ip_address(value)
    except ValueError:
        return False
    if isinstance(addr, ipaddress.IPv6Address):
        if addr.ipv4_mapped is not None:
            addr = addr.ipv4_mapped
        elif addr in _NAT64_PREFIX:
            addr = ipaddress.IPv4Address(int(addr) & 0xFFFFFFFF)
    return addr.is_global and not addr.is_multicast


def resolve_public_addresses(url: str, *, allow_local: bool = False) -> list[str]:
    """Resolve *url*'s host; raise unless it is http(s) and every address is public."""
    try:
        parts = urllib.parse.urlsplit(url)
        port = parts.port
    except (TypeError, ValueError) as exc:
        raise UnsafeDestinationError(f"Cannot parse URL {url!r}: {exc}") from exc
    host = parts.hostname
    if not host or parts.scheme not in ("http", "https"):
        raise UnsafeDestinationError(f"Not an http(s) URL with a host: {url!r}")
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
                raise UnsafeDestinationError(f"{url!r} resolves to non-public address {address!r}")
    return addresses


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
        address = resolve_public_addresses(url, allow_local=allow_local)[0].split("%")[0]
        logical = httpx.URL(url)
        request = client.build_request(
            "GET",
            logical.copy_with(host=address),
            headers={**headers, "Host": logical.netloc.decode("ascii")},
            extensions={"sni_hostname": logical.host},
        )
        response = client.send(request, follow_redirects=False)
        location = response.headers.get("location")
        if response.status_code not in _REDIRECT_STATUSES or not location:
            return response, url
        next_url = urllib.parse.urljoin(url, location)
        if httpx.URL(next_url).netloc != logical.netloc:
            headers = {k: v for k, v in headers.items() if k.lower() not in _CREDENTIAL_HEADERS}
        url = next_url
    raise UnsafeDestinationError(f"Too many redirects (more than {max_redirects}) ending at {url!r}")
