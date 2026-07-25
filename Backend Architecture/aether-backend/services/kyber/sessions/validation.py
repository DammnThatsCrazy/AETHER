"""Request-shape checks for Kyber: origin, fetch metadata, CSRF, fixation.

Everything here is a pure function over already-extracted values. Nothing
touches the database, the clock or the network, so the rules are testable
without a request object and cannot drift between the dependency that enforces
them and the tests that assert them.

Three independent controls guard a mutating Kyber request, and all three must
pass:

1. **Origin / Referer** — the declared initiator must be an allow-listed Kyber
   origin. A request with no ``Origin`` *and* no ``Referer`` is rejected on a
   mutating method rather than waved through, because "absent" is exactly what
   a stripped-header forgery looks like.
2. **Fetch metadata** — ``Sec-Fetch-Site: same-origin`` (browsers set this and
   script cannot forge it). ``cross-site`` and ``same-site`` are both refused:
   a sibling subdomain is not the Kyber origin.
3. **CSRF token** — the ``X-Kyber-CSRF`` header must equal the HttpOnly cookie
   copy. A cross-site attacker can cause the cookie to ride along but cannot
   read it back to populate the header.

Session-fixation protection is the fourth control and is not about the request
shape: whenever the authority behind a session changes — new authentication
strength, new role templates, a fresh step-up — the handle is rotated, so a
token an attacker planted before the privilege change is worthless after it.
"""
from __future__ import annotations

import os
from typing import Any, Iterable, Optional
from urllib.parse import urlsplit

from .cookies import csrf_matches, read_csrf_cookie, read_csrf_header

#: Methods that cannot change state and therefore skip origin/CSRF checks.
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})

#: The only acceptable ``Sec-Fetch-Site`` value for a mutating Kyber request.
REQUIRED_SEC_FETCH_SITE = "same-origin"

#: Environment variable holding the comma-separated Kyber origin allow-list.
ALLOWED_ORIGINS_ENV = "KYBER_ALLOWED_ORIGINS"

#: Fallback allow-list, used only in local/dev where no explicit list is set.
_LOCAL_DEFAULT_ORIGINS = (
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://localhost:5173",
)

_LOCAL_ENVIRONMENTS = frozenset({"local", "dev", "development", "test", "testing"})

# Failure reasons. These are *not* ``DenialReason`` values: a forged origin is
# a malformed request, not an authorization outcome, and it must not be
# reported to the caller as though their session or role were at fault.
CSRF_FAILURE = "csrf_invalid"
ORIGIN_FAILURE = "origin_not_allowed"
ORIGIN_MISSING_FAILURE = "origin_missing"
FETCH_SITE_FAILURE = "fetch_site_not_same_origin"


def is_safe_method(method: Optional[str]) -> bool:
    """True when the method cannot mutate state."""
    return (method or "GET").upper() in SAFE_METHODS


def normalize_origin(value: Optional[str]) -> Optional[str]:
    """Reduce a URL to ``scheme://host[:port]``, or ``None`` if unusable.

    Comparing full URLs is a known source of bypasses (``https://evil/?x=good``
    prefix-matching a good origin); reducing both sides to a scheme/authority
    pair makes the comparison exact.
    """
    if not value:
        return None
    candidate = value.strip()
    if not candidate or candidate.lower() == "null":
        return None
    parts = urlsplit(candidate)
    if not parts.scheme or not parts.netloc:
        return None
    return f"{parts.scheme.lower()}://{parts.netloc.lower()}"


def configured_origins(environment: Optional[str] = None) -> tuple[str, ...]:
    """The Kyber origin allow-list for this deployment.

    Reads ``KYBER_ALLOWED_ORIGINS`` at call time. Outside local/dev an unset
    variable yields an **empty** allow-list, so every mutating request fails
    closed until an operator configures the console origin — a misconfigured
    deployment is unusable rather than open.
    """
    raw = os.getenv(ALLOWED_ORIGINS_ENV, "")
    origins = tuple(
        origin for origin in (normalize_origin(part) for part in raw.split(",")) if origin
    )
    if origins:
        return origins
    env = (environment or os.getenv("AETHER_ENV", "local")).strip().lower()
    if env in _LOCAL_ENVIRONMENTS:
        return _LOCAL_DEFAULT_ORIGINS
    return ()


def verify_origin(
    *,
    origin: Optional[str],
    referer: Optional[str] = None,
    allowed_origins: Optional[Iterable[str]] = None,
) -> tuple[bool, Optional[str]]:
    """Check the request initiator against the allow-list.

    Returns ``(ok, failure_reason)``. ``Origin`` wins when present; ``Referer``
    is only consulted as a fallback, because it is the weaker signal.
    """
    allowed = tuple(allowed_origins) if allowed_origins is not None else configured_origins()
    normalized_allowed = {normalize_origin(a) for a in allowed}
    normalized_allowed.discard(None)

    declared = normalize_origin(origin) or normalize_origin(referer)
    if declared is None:
        return False, ORIGIN_MISSING_FAILURE
    if declared not in normalized_allowed:
        return False, ORIGIN_FAILURE
    return True, None


def verify_sec_fetch_site(value: Optional[str]) -> tuple[bool, Optional[str]]:
    """Check the ``Sec-Fetch-Site`` fetch-metadata header.

    A missing header is accepted here — non-browser operator tooling does not
    send it — because origin and CSRF still have to pass independently. A
    *present but wrong* value is always a rejection.
    """
    if value is None or not value.strip():
        return True, None
    if value.strip().lower() != REQUIRED_SEC_FETCH_SITE:
        return False, FETCH_SITE_FAILURE
    return True, None


def verify_csrf(header_token: Optional[str], cookie_token: Optional[str]) -> tuple[bool, Optional[str]]:
    """Compare the echoed CSRF header against the HttpOnly cookie copy."""
    if csrf_matches(header_token, cookie_token):
        return True, None
    return False, CSRF_FAILURE


def validate_mutating_request(
    request: Any,
    *,
    allowed_origins: Optional[Iterable[str]] = None,
) -> Optional[str]:
    """Run every request-shape control for a possibly-mutating request.

    Returns ``None`` when the request is acceptable, or the first failure
    reason. Safe methods short-circuit to ``None``.
    """
    method = getattr(request, "method", "GET")
    if is_safe_method(method):
        return None

    headers = getattr(request, "headers", None) or {}
    get = getattr(headers, "get", lambda _k, _d=None: None)

    ok, reason = verify_origin(
        origin=get("Origin") or get("origin"),
        referer=get("Referer") or get("referer"),
        allowed_origins=allowed_origins,
    )
    if not ok:
        return reason

    ok, reason = verify_sec_fetch_site(get("Sec-Fetch-Site") or get("sec-fetch-site"))
    if not ok:
        return reason

    ok, reason = verify_csrf(read_csrf_header(request), read_csrf_cookie(request))
    if not ok:
        return reason
    return None


# ── Session fixation ─────────────────────────────────────────────────────────


def requires_rotation(
    *,
    previous_strength: Optional[str],
    new_strength: Optional[str],
    previous_template_ids: Optional[Iterable[str]] = None,
    new_template_ids: Optional[Iterable[str]] = None,
) -> bool:
    """True when the session handle must be replaced before continuing.

    Any change to what the session can *do* invalidates the old handle. That
    covers the fixation case (an attacker plants a handle, the victim then
    authenticates or is granted a role) and the downgrade case alike — a
    session that loses authority is rotated too, so a captured pre-downgrade
    handle cannot be replayed.
    """
    if previous_strength != new_strength:
        return True
    before = frozenset(previous_template_ids or ())
    after = frozenset(new_template_ids or ())
    return before != after


def rotation_reason(
    *,
    previous_strength: Optional[str],
    new_strength: Optional[str],
    previous_template_ids: Optional[Iterable[str]] = None,
    new_template_ids: Optional[Iterable[str]] = None,
) -> Optional[str]:
    """A short, audit-safe explanation of why rotation is required."""
    if previous_strength != new_strength:
        return f"authentication_strength {previous_strength!r} -> {new_strength!r}"
    before = frozenset(previous_template_ids or ())
    after = frozenset(new_template_ids or ())
    if before != after:
        return "role_templates_changed"
    return None


__all__ = [
    "ALLOWED_ORIGINS_ENV",
    "CSRF_FAILURE",
    "FETCH_SITE_FAILURE",
    "ORIGIN_FAILURE",
    "ORIGIN_MISSING_FAILURE",
    "REQUIRED_SEC_FETCH_SITE",
    "SAFE_METHODS",
    "configured_origins",
    "is_safe_method",
    "normalize_origin",
    "requires_rotation",
    "rotation_reason",
    "validate_mutating_request",
    "verify_csrf",
    "verify_origin",
    "verify_sec_fetch_site",
]
