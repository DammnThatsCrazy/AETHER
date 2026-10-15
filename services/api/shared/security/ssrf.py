"""Server-side request forgery (SSRF) validation for outbound requests.

:func:`validated_https_host` is the shared, fail-closed gate the runtime uses
before it issues an outbound HTTPS request to a tenant-supplied host. It is a
generalization of the Shopify ``_validated_shop_domain`` gate in
:mod:`connectors.providers.shopify.auth` — the hardcoded
``{shop}.myshopify.com`` regex becomes an explicit, caller-supplied suffix
allowlist, and the accept/reject policy is:

* a bare hostname (``example.com``) or a full ``https://`` URL
  (``https://example.com/path``) is accepted; any other scheme, userinfo,
  explicit port, or (for a bare host) path/query/fragment/trailing-dot is
  rejected;
* anything that parses as an IP literal (IPv4 + IPv6, including bracketed and
  bare forms) is rejected — the runtime must never issue an outbound request
  to a raw IP, which covers loopback, link-local, and private ranges;
* with a non-empty ``allow_suffixes`` allowlist, only hosts that equal an entry
  or are a label-boundary subdomain of an entry are accepted (so
  ``myshopify.com`` and ``evil.myshopify.com`` match ``("myshopify.com",)`` but
  ``evilmyshopify.com`` does not); with an empty allowlist, any public host
  that survives the structural, well-formedness, and IP gates is accepted.

The function returns the normalized lowercase host, or ``None`` on any
rejection. Every rejection path is fail-closed: it never raises and never
returns a raw or unvalidated value.

.. warning::

   ``require_public`` and the structural gates are inert against resolver-IP
   spellings and DNS-rebinding names (``127.0.0.1.nip.io``,
   ``169.254.169.254.nip.io``, ``metadata.google.internal``). The
   well-formedness and resolver-IP gates below close the deterministic subset
   (integer/hex/octal/compact IPv4 spellings and single-label names), but the
   DNS-rebinding class is inherent to "any public host" mode. Empty-allowlist
   mode is only safe for untrusted input when paired with a resolver-level
   check (resolve → validate address → no-rebinding).

The resolver-level check lives here too. :func:`resolve_public_addresses`
resolves a URL's host and requires every resolved address to be globally
routable (``ipaddress`` ``is_global``, not multicast), after unwrapping
IPv4-mapped IPv6 (``::ffff:a.b.c.d``), the NAT64 well-known prefix
(``64:ff9b::/96``), 6to4 (``2002::/16``) and Teredo (``2001::/32``) to their
embedded IPv4. That excludes loopback, link-local
and cloud metadata, RFC 1918, ULA, carrier-grade NAT (``100.64.0.0/10``),
documentation and reserved ranges. :func:`send_public_request` issues the
request against the validated address (original ``Host`` header, TLS SNI and
certificate check against the original hostname), so a second DNS answer can
never redirect the connection, and follows at most three redirects by hand,
re-validating every hop and dropping credentials when the host changes.
"""

from __future__ import annotations

import ipaddress
import re
import socket
import unicodedata
import urllib.parse
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import httpx

# Well-formed hostname: two or more ASCII labels, [a-z0-9]+hyphen, no leading/
# trailing hyphen, no empty label. ASCII-only — closes Unicode homographs
# (mуshopify.com) and every punctuation/control trick in the host string.
_HOST_RE = re.compile(r"[a-z0-9](?:[a-z0-9-]*[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]*[a-z0-9])?)+")
_DECIMAL_RE = re.compile(r"[0-9]+")
_HEX_RE = re.compile(r"0x[0-9a-fA-F]+")


def _looks_numeric(host: str) -> bool:
    """True when a resolver could interpret *host* as an IPv4 address.

    ``ipaddress`` only parses dotted-decimal literals, but resolvers also treat
    integer (``2130706433``), hex (``0x7f000001``), hex-dotted
    (``0x7f.0x0.0x0.0x1``), leading-zero octal (``0177.0.0.1``), and compact
    (``127.1``, ``1.2.3``) spellings as IPv4. The runtime must never reach a
    numeric address server-side.
    """
    if not host:
        return False
    if _DECIMAL_RE.fullmatch(host) or _HEX_RE.fullmatch(host):
        return True
    labels = host.split(".")
    if len(labels) > 4:
        return False
    return all(
        label and (_DECIMAL_RE.fullmatch(label) or _HEX_RE.fullmatch(label)) for label in labels
    )


def _has_disallowed_characters(value: str) -> bool:
    """True when *value* contains whitespace or control/format characters.

    ``str.isspace()`` covers ASCII and Unicode whitespace; every Unicode
    category starting with ``C`` (control, format, surrogate, private-use, and
    unassigned code points) is treated as disallowed so whitespace or control
    tricks can never hide inside a host string.
    """

    return any(ch.isspace() or unicodedata.category(ch)[0] == "C" for ch in value)


def validated_https_host(
    value: str,
    *,
    allow_suffixes: tuple[str, ...] = (),
    require_public: bool = True,
) -> str | None:
    """Validate a tenant-supplied host; return the normalized host or ``None``.

    *value* may be a bare host (``example.com``) or a full ``https://`` URL
    (``https://example.com/path``); a full URL is accepted only with the
    ``https`` scheme (case-insensitive). Returns the normalized lowercase host
    with no scheme, port, or path, or ``None`` when the value is rejected.

    *allow_suffixes* entries are full domains. A host is accepted when it
    equals an entry or ends with ``"." + entry`` (label boundary) —
    case-insensitive. When *allow_suffixes* is empty, any public host that
    passes the structural and IP gates is accepted.

    *require_public* is defense-in-depth: when true, any value that still
    parses as an IP must be globally routable. The unconditional IP-literal
    gate above it already rejects every IP literal; this flag documents the
    policy and protects any future relaxation.

    Fail-closed: every rejection path returns ``None``; this function never
    raises and never returns a raw or unvalidated value.
    """
    if not isinstance(value, str):
        return None
    if not value:
        return None
    # Reject any whitespace or control/format character anywhere in the value —
    # never silently strip, because leading/trailing or embedded whitespace is
    # itself a trick (fail-closed rather than tolerant).
    if _has_disallowed_characters(value):
        return None

    lowered = value.lower()

    try:
        parts = urllib.parse.urlsplit(lowered)
    except ValueError:
        return None

    if parts.scheme:
        # Full-URL mode: only the https scheme is accepted, and the netloc must
        # carry no userinfo and no explicit port.
        if parts.scheme != "https":
            return None
        try:
            port = parts.port
        except ValueError:
            return None
        if port is not None or parts.username is not None or parts.password is not None:
            return None
        host = parts.hostname
        if not host:
            return None
    else:
        # Bare-host mode: the entire value must be a bare hostname. Parsing
        # "//" + value makes scheme/userinfo/port/path/query/fragment tricks
        # visible so the round-trip equality check rejects them all.
        try:
            bare = urllib.parse.urlsplit("//" + lowered)
        except ValueError:
            return None
        if bare.hostname is None or bare.hostname != lowered:
            return None
        try:
            port = bare.port
        except ValueError:
            return None
        if (
            port is not None
            or bare.username is not None
            or bare.password is not None
            or bare.path
            or bare.query
            or bare.fragment
        ):
            return None
        host = bare.hostname

    host = host.lower()
    if host.endswith("."):
        return None

    # IP literal gate — never reach an IP server-side.
    try:
        ipaddress.ip_address(host)
        return None
    except ValueError:
        pass
    # Backstop for literals the first pass rejects on the first try (trailing
    # dot / brackets): any value that normalizes to an IP is still blocked.
    try:
        ipaddress.ip_address(host.rstrip(".").strip("[]"))
        return None
    except ValueError:
        pass

    # Well-formed FQDN gate: two or more ASCII labels, no empty/leading/trailing
    # label, no Unicode homograph, no punctuation. Closes the empty-label
    # allowlist edge and the IDN-homograph vector.
    if not _HOST_RE.fullmatch(host):
        return None
    # Resolver-IP gate: spellings a resolver treats as IPv4 even though
    # ``ipaddress`` does not (integer/hex/octal/compact forms).
    if _looks_numeric(host):
        return None

    # Defense-in-depth: with require_public, a value that still parses as an IP
    # must be globally routable. The literal gate above already rejects every
    # IP, so this is unreachable today; it is preserved as an explicit security
    # boundary for any future relaxation. Note this is ALSO inert against
    # resolver-IP spellings and DNS-rebinding names — those are only handled by
    # a resolver-level check; see the module docstring warning.
    if require_public:
        try:
            candidate = ipaddress.ip_address(host.rstrip(".").strip("[]"))
        except ValueError:
            pass
        else:
            if not candidate.is_global:
                return None

    # Suffix allowlist: exact match or label-boundary subdomain of an entry.
    # A malformed (non-str) entry fails closed — never raise.
    if allow_suffixes:
        for entry in allow_suffixes:
            if not isinstance(entry, str):
                return None
            suffix = entry.lower()
            if host == suffix or host.endswith("." + suffix):
                break
        else:
            return None

    return host


class UnsafeDestinationError(ValueError):
    """The outbound destination is malformed or not a public internet address."""


_NAT64_PREFIX = ipaddress.ip_network("64:ff9b::/96")


def is_public_address(value: str) -> bool:
    """True only for a globally routable unicast address.

    IPv4-mapped, NAT64 (``64:ff9b::/96``) and 6to4 (``2002::/16``) IPv6
    addresses are judged by the IPv4 address they embed, Teredo
    (``2001::/32``) by both its server and client IPv4, independent of how the
    running Python version classifies the IPv6 prefix. Unparseable input is
    not public.
    """
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
    """Resolve *url*'s host and return its addresses; raise unless all are public.

    Only ``http``/``https`` URLs are accepted. An IP-literal host is checked
    without touching the resolver. With *allow_local* (local development only)
    the addresses are returned without the public-address check.
    """
    try:
        parts = urllib.parse.urlsplit(url)
        port = parts.port
    except (TypeError, ValueError) as exc:
        raise UnsafeDestinationError("Cannot parse outbound URL") from exc
    host = parts.hostname
    if not host:
        raise UnsafeDestinationError("Cannot parse hostname from outbound URL")
    if parts.scheme not in ("http", "https"):
        raise UnsafeDestinationError(f"Unsupported URL scheme {parts.scheme!r} for host {host!r}")

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
                raise UnsafeDestinationError(
                    f"Host {host!r} resolves to non-public address {address!r}. SSRF protection active."
                )
    return addresses


_REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})
_CREDENTIAL_HEADERS = frozenset({"authorization", "proxy-authorization", "cookie"})
MAX_REDIRECTS = 3


def _pinned_request(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    headers: dict[str, str],
    body: dict[str, Any],
    allow_local: bool,
) -> httpx.Request:
    import httpx

    address = resolve_public_addresses(url, allow_local=allow_local)[0].split("%")[0]
    logical = httpx.URL(url)
    headers = {k: v for k, v in headers.items() if k.lower() != "host"}
    return client.build_request(
        method,
        logical.copy_with(host=address),
        headers={**headers, "Host": logical.netloc.decode("ascii")},
        extensions={"sni_hostname": logical.host},
        **body,
    )


async def send_public_request(
    method: str,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    content: bytes | str | None = None,
    json: Any = None,
    timeout: float = 20.0,
    max_redirects: int = MAX_REDIRECTS,
    allow_local: bool = False,
    transport: httpx.AsyncBaseTransport | None = None,
) -> httpx.Response:
    """Send one request to a tenant-configured *url*, reaching only public addresses.

    The connection goes to the validated address. Redirects are followed by
    hand, at most *max_redirects* hops (``0`` returns the redirect response),
    each hop re-validated; ``Authorization``/``Proxy-Authorization``/``Cookie``
    are dropped when the host changes, and 301/302 on POST and every 303 turn
    into a body-less GET. Raises :class:`UnsafeDestinationError` before any
    connection to a non-public destination.
    """
    import httpx

    headers = dict(headers or {})
    body: dict[str, Any] = {"content": content, "json": json}
    async with httpx.AsyncClient(transport=transport, timeout=timeout, follow_redirects=False) as client:
        for _ in range(max_redirects + 1):
            response = await client.send(_pinned_request(client, method, url, headers, body, allow_local))
            location = response.headers.get("location")
            if response.status_code not in _REDIRECT_STATUSES or not location or max_redirects == 0:
                return response
            next_url = urllib.parse.urljoin(url, location)
            if httpx.URL(next_url).netloc != httpx.URL(url).netloc:
                headers = {k: v for k, v in headers.items() if k.lower() not in _CREDENTIAL_HEADERS}
            if response.status_code == 303 or (response.status_code in (301, 302) and method.upper() == "POST"):
                method, body = "GET", {}
            url = next_url
    raise UnsafeDestinationError(f"Too many redirects (more than {max_redirects}) ending at host {httpx.URL(url).host!r}")


__all__ = [
    "MAX_REDIRECTS",
    "UnsafeDestinationError",
    "is_public_address",
    "resolve_public_addresses",
    "send_public_request",
    "validated_https_host",
]
