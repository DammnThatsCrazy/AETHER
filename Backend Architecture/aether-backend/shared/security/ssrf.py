"""Server-side request forgery (SSRF) validation for outbound requests.

:func:`validated_https_host` is the shared, fail-closed gate the runtime uses
before it issues an outbound HTTPS request to a tenant-supplied host. It is a
generalization of the Shopify ``_validated_shop_domain`` gate in
:mod:`services.providers.shopify.auth` — the hardcoded
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
"""

from __future__ import annotations

import ipaddress
import re
import unicodedata
import urllib.parse

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


__all__ = [
    "validated_https_host",
]
