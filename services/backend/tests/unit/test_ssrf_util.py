"""Unit tests for the shared SSRF host-validation seam.

``validated_https_host`` is the fail-closed gate the runtime applies before any
outbound HTTPS request to a tenant-supplied host. These tests pin the public
contract: valid bare hosts and ``https://`` URLs return the normalized
lowercase host; every structural, IP, and allowlist rejection returns ``None``.
"""

from __future__ import annotations

import pytest

from shared.security.ssrf import validated_https_host


# Valid bare hosts — accepted and returned lowercased and structurally unchanged.
VALID_BARE_HOSTS = [
    "example.com",
    "EXAMPLE.com",  # normalized to lowercase
    "sub.example.com",
    "shopify.com",
    "a-b.example.com",
    "xn--nxasmq6b.example.com",
]

# Valid full https:// URLs — accepted and return just the normalized host.
VALID_HTTPS_URLS = [
    ("https://example.com", "example.com"),
    ("https://example.com/path", "example.com"),
    ("https://example.com/path?query=1#frag", "example.com"),
    ("HTTPS://EXAMPLE.com/path", "example.com"),
    ("https://shop.example.com/admin", "shop.example.com"),
]

# Every one of these must be rejected (return None).
INVALID_VALUES = [
    # empty / whitespace
    "",
    "   ",
    "example.com ",
    " example.com",
    "example.com\tfoo",
    "example.com\n",
    "exa mple.com",
    # non-https schemes
    "http://example.com",
    "ftp://example.com",
    "//example.com",
    # userinfo
    "user@example.com",
    "https://user@example.com",
    "https://user:pass@example.com",
    # explicit port
    "example.com:8443",
    "https://example.com:8443",
    # path / query / fragment in bare-host mode
    "example.com/path",
    "example.com?query=1",
    "example.com#fragment",
    "example.com//foo",
    # trailing dot
    "example.com.",
    "https://example.com.",
    # IPv4 literals
    "127.0.0.1",
    "127.0.0.0/8",
    "169.254.169.254",
    "10.0.0.1",
    "192.168.1.1",
    "172.16.0.1",
    "8.8.8.8",
    "https://127.0.0.1",
    # IPv6 literals
    "::1",
    "fc00::1",
    "https://[::1]",
]


@pytest.mark.parametrize("host", VALID_BARE_HOSTS)
def test_valid_bare_host_returns_normalized_host(host: str) -> None:
    assert validated_https_host(host) == host.lower()


@pytest.mark.parametrize(("url", "expected"), VALID_HTTPS_URLS)
def test_valid_https_url_returns_only_the_host(url: str, expected: str) -> None:
    assert validated_https_host(url) == expected


@pytest.mark.parametrize("value", INVALID_VALUES)
def test_rejects_structural_and_ip_values(value: str) -> None:
    assert validated_https_host(value) is None


def test_rejects_non_string_input() -> None:
    assert validated_https_host(None) is None
    assert validated_https_host(1234) is None  # type: ignore[arg-type]


# Resolver-IP spellings and single-label names — a resolver interprets these as
# loopback/private addresses even though ``ipaddress`` does not parse them as IP
# literals. Every one must be rejected (return None) in empty-allowlist mode.
RESOLVER_IP_VALUES = [
    "localhost",
    "LOCALHOST",
    "127.1",
    "127.0.0.01",
    "127.000.000.001",
    "2130706433",
    "0x7f000001",
    "0x7f.0x0.0x0.0x1",
    "0177.0.0.1",
    "0",
    "1.2.3",
]

# Control hosts that LOOK numeric but are legitimate multi-label DNS names and
# must stay accepted (no false positives from the resolver-IP gate).
STILL_ACCEPTED_HOSTS = [
    "1000.com",
    "101.com",
    "123.com",
    "512.100.com",
    "foo.123.456",
]


@pytest.mark.parametrize("value", RESOLVER_IP_VALUES)
def test_rejects_resolver_ip_spellings_and_single_labels(value: str) -> None:
    assert validated_https_host(value) is None


@pytest.mark.parametrize("host", STILL_ACCEPTED_HOSTS)
def test_resolver_ip_gate_has_no_false_positives(host: str) -> None:
    assert validated_https_host(host) == host


# Empty-label hosts — must be rejected even when the allowlist would otherwise
# match past the empty/leading label.
EMPTY_LABEL_VALUES = [".myshopify.com", "a..myshopify.com", "..myshopify.com"]


@pytest.mark.parametrize("value", EMPTY_LABEL_VALUES)
def test_rejects_empty_label_hosts_even_with_matching_allowlist(value: str) -> None:
    assert validated_https_host(value, allow_suffixes=("myshopify.com",)) is None


def test_rejects_unicode_homograph() -> None:
    # Cyrillic 'у' (U+0443) is not an ASCII alphanumeric — the well-formedness
    # gate is ASCII-only, so the homograph never reaches the allowlist.
    homograph = "mуshopify.com"
    assert validated_https_host(homograph) is None


def test_malformed_allow_suffixes_fails_closed() -> None:
    # Non-str allowlist entries must return None, never raise.
    assert validated_https_host("example.com", allow_suffixes=(None,)) is None  # type: ignore[arg-type]
    assert validated_https_host("example.com", allow_suffixes=(("x", 42),)) is None  # type: ignore[arg-type]


def test_numeric_label_subdomain_still_matches_allowlist() -> None:
    # Numeric labels are fine inside a normal DNS label structure; only an
    # all-numeric, resolver-IP interpretation is blocked.
    assert (
        validated_https_host("127.myshopify.com", allow_suffixes=("myshopify.com",))
        == "127.myshopify.com"
    )
    assert (
        validated_https_host("0.myshopify.com", allow_suffixes=("myshopify.com",))
        == "0.myshopify.com"
    )


# NOTE: the DNS-rebinding class (``127.0.0.1.nip.io``, ``169.254.169.254.nip.io``,
# ``metadata.google.internal``) is inherent to empty-allowlist mode and is NOT
# closed by the structural gates — that requires a resolver-level check (see the
# module docstring warning). These are documented residual risk, not asserted
# here as either accepted or rejected.

# --- allow_suffixes semantics -------------------------------------------------


def test_empty_allowlist_accepts_any_public_host() -> None:
    # Empty allowlist rejects nothing public — the structural, well-formedness,
    # and IP gates alone decide acceptance.
    assert validated_https_host("example.com") == "example.com"
    assert validated_https_host("sub.example.com") == "sub.example.com"
    assert validated_https_host("https://example.com/path") == "example.com"


def test_allowlist_exact_match_and_subdomain() -> None:
    allowed = ("myshopify.com",)
    # Exact match.
    assert validated_https_host("myshopify.com", allow_suffixes=allowed) == ("myshopify.com")
    # Label-boundary subdomain.
    assert validated_https_host("evil.myshopify.com", allow_suffixes=allowed) == (
        "evil.myshopify.com"
    )
    assert (
        validated_https_host("sub.evil.myshopify.com", allow_suffixes=allowed)
        == "sub.evil.myshopify.com"
    )


def test_allowlist_rejects_non_matching_host() -> None:
    allowed = ("myshopify.com",)
    # No label boundary — "evilmyshopify.com" is not a subdomain.
    assert validated_https_host("evilmyshopify.com", allow_suffixes=allowed) is None
    # Unrelated host.
    assert validated_https_host("example.com", allow_suffixes=allowed) is None


def test_allowlist_is_case_insensitive() -> None:
    allowed = ("myshopify.com",)
    assert validated_https_host("EVIL.MYSHOPIFY.COM", allow_suffixes=allowed) == (
        "evil.myshopify.com"
    )
    assert validated_https_host("evil.myshopify.com", allow_suffixes=("MYSHOPIFY.COM",)) == (
        "evil.myshopify.com"
    )


def test_allowlist_multiple_entries_any_match() -> None:
    allowed = ("shopify.com", "myshopify.com")
    assert validated_https_host("admin.myshopify.com", allow_suffixes=allowed) == (
        "admin.myshopify.com"
    )
    assert validated_https_host("sub.shopify.com", allow_suffixes=allowed) == ("sub.shopify.com")
    assert validated_https_host("example.com", allow_suffixes=allowed) is None


def test_allowlist_applies_to_url_host() -> None:
    allowed = ("myshopify.com",)
    assert (
        validated_https_host("https://evil.myshopify.com/oauth", allow_suffixes=allowed)
        == "evil.myshopify.com"
    )


# --- require_public defense-in-depth -----------------------------------------


def test_ip_literals_are_rejected_even_with_require_public_false() -> None:
    # The IP-literal gate is unconditional; require_public is only
    # defense-in-depth on top of it.
    assert validated_https_host("10.0.0.1", require_public=False) is None
    assert validated_https_host("127.0.0.1", require_public=False) is None
    assert validated_https_host("169.254.169.254", require_public=False) is None
    assert validated_https_host("::1", require_public=False) is None


def test_require_public_does_not_reject_public_hosts() -> None:
    assert validated_https_host("example.com", require_public=True) == "example.com"
    assert validated_https_host("example.com", require_public=False) == "example.com"
