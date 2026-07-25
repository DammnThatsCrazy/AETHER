"""Cookie transport for Kyber workforce sessions.

Kyber never puts authority in a token the browser can read. The session cookie
carries an opaque handle to a server-side row; every attribute on it exists to
remove a specific attack:

``__Host-`` prefix
    A browser only accepts a ``__Host-`` cookie when it is ``Secure``, has
    ``Path=/`` and carries **no** ``Domain`` attribute. That last part is the
    point: a compromised sibling subdomain cannot set a cookie that the Kyber
    origin will later read back, so cookie-fixation across subdomains is
    impossible rather than merely unlikely.
``HttpOnly``
    Script on the page never reads the session handle, so an XSS foothold
    cannot exfiltrate a usable credential.
``SameSite=Strict``
    The cookie is not attached to cross-site navigations at all, which removes
    the whole class of cross-site request forgery before CSRF tokens are even
    considered. The CSRF token is defence in depth on top of it.

The CSRF cookie is *also* ``HttpOnly``. That rules out the classic
"double-submit read by JavaScript" pattern, deliberately: the raw CSRF token is
handed to the application once in a response body (``GET /v1/kyber/auth/session``)
and echoed back in the ``X-Kyber-CSRF`` header, while the cookie copy stays
unreadable to script. Verification then compares header against cookie in
constant time, so a forged cross-site request cannot supply a matching header
even if it can cause the cookie to ride along.

``Secure`` may be relaxed **only** when ``AETHER_ENV`` names a local, dev or
test environment, so a plain-http developer loop works. Every other value —
including an unset or unrecognised one — keeps ``Secure`` on.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import secrets
from typing import Any, Optional

#: Session handle. The ``__Host-`` prefix is load-bearing, not decoration.
SESSION_COOKIE_NAME = "__Host-kyber_session"

#: Server-side copy of the CSRF token for mutating requests.
CSRF_COOKIE_NAME = "__Host-kyber_csrf"

#: Header the client must echo the CSRF token in.
CSRF_HEADER_NAME = "X-Kyber-CSRF"

#: Optional header transport for the session handle. Used by non-browser
#: operator tooling that cannot hold cookies; it never bypasses any check.
SESSION_HEADER_NAME = "X-Kyber-Session"

#: Prefix every raw Kyber session token carries. Lets us reject obviously
#: malformed values before touching the database.
SESSION_TOKEN_PREFIX = "kses_"

_COOKIE_PATH = "/"
_SAME_SITE = "strict"

#: Environments where a plain-http developer loop is expected. Anything not in
#: this set — including an unset or misspelled value — keeps ``Secure`` on.
_INSECURE_OK_ENVIRONMENTS = frozenset({"local", "dev", "development", "test", "testing"})


def current_environment() -> str:
    """The configured environment name, lowercased. Defaults to ``local``."""
    return os.getenv("AETHER_ENV", "local").strip().lower()


def cookie_secure() -> bool:
    """Whether cookies must carry ``Secure``.

    Read at call time rather than import time so a process that changes
    ``AETHER_ENV`` (or a test that does) is not stuck with a stale answer.
    """
    return current_environment() not in _INSECURE_OK_ENVIRONMENTS


def cookie_attributes(*, max_age: Optional[int] = None) -> dict[str, Any]:
    """The attribute set shared by every Kyber cookie.

    ``domain`` is deliberately absent rather than ``None``-valued: the
    ``__Host-`` prefix requires the attribute to be omitted entirely.
    """
    attrs: dict[str, Any] = {
        "path": _COOKIE_PATH,
        "secure": cookie_secure(),
        "httponly": True,
        "samesite": _SAME_SITE,
    }
    if max_age is not None:
        attrs["max_age"] = max_age
    return attrs


def _set(response: Any, name: str, value: str, max_age: Optional[int]) -> None:
    response.set_cookie(name, value, **cookie_attributes(max_age=max_age))


def _clear(response: Any, name: str) -> None:
    response.delete_cookie(name, path=_COOKIE_PATH)


def set_session_cookie(response: Any, token: str, *, max_age: Optional[int] = None) -> None:
    """Attach the opaque session handle to ``response``.

    ``max_age`` should be the session's remaining authority (or presence)
    lifetime in seconds so the browser drops the cookie at roughly the same
    moment the server stops honouring it.
    """
    _set(response, SESSION_COOKIE_NAME, token, max_age)


def clear_session_cookie(response: Any) -> None:
    """Remove the session cookie. Always paired with a server-side revoke."""
    _clear(response, SESSION_COOKIE_NAME)


def set_csrf_cookie(response: Any, token: str, *, max_age: Optional[int] = None) -> None:
    """Attach the CSRF cookie copy. HttpOnly — see the module docstring."""
    _set(response, CSRF_COOKIE_NAME, token, max_age)


def clear_csrf_cookie(response: Any) -> None:
    """Remove the CSRF cookie."""
    _clear(response, CSRF_COOKIE_NAME)


def clear_kyber_cookies(response: Any) -> None:
    """Remove every Kyber cookie. Used on logout and on forced revocation."""
    clear_session_cookie(response)
    clear_csrf_cookie(response)


def _cookie(request: Any, name: str) -> Optional[str]:
    cookies = getattr(request, "cookies", None) or {}
    value = cookies.get(name)
    return value or None


def _header(request: Any, name: str) -> Optional[str]:
    headers = getattr(request, "headers", None) or {}
    try:
        value = headers.get(name)
    except AttributeError:  # pragma: no cover - defensive for exotic mappings
        return None
    return value or None


def read_session_token(request: Any) -> Optional[str]:
    """Extract the raw session handle from a request, or ``None``.

    Cookie first, then the explicit operator-tooling header, then an
    ``Authorization: Bearer`` value — and only when the value carries the Kyber
    token prefix, so a tenant API key can never be mistaken for a Kyber
    session.
    """
    token = _cookie(request, SESSION_COOKIE_NAME)
    if token:
        return token

    token = _header(request, SESSION_HEADER_NAME)
    if token and token.startswith(SESSION_TOKEN_PREFIX):
        return token

    authorization = _header(request, "Authorization") or _header(request, "authorization")
    if authorization:
        parts = authorization.split(None, 1)
        if len(parts) == 2 and parts[0].lower() == "bearer":
            candidate = parts[1].strip()
            if candidate.startswith(SESSION_TOKEN_PREFIX):
                return candidate
    return None


def read_csrf_cookie(request: Any) -> Optional[str]:
    """The CSRF token as stored in the cookie."""
    return _cookie(request, CSRF_COOKIE_NAME)


def read_csrf_header(request: Any) -> Optional[str]:
    """The CSRF token as echoed by the client."""
    return _header(request, CSRF_HEADER_NAME) or _header(request, CSRF_HEADER_NAME.lower())


def issue_csrf_token() -> tuple[str, str]:
    """Mint a CSRF token. Returns ``(raw, sha256_hex)``.

    Only the digest is ever persisted, exactly as for the session handle.
    """
    raw = secrets.token_urlsafe(32)
    return raw, hash_csrf_token(raw)


def hash_csrf_token(raw: str) -> str:
    """sha256 of a raw CSRF token, hex encoded."""
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def csrf_matches(header_token: Optional[str], cookie_token: Optional[str]) -> bool:
    """Constant-time comparison of the echoed header against the cookie copy."""
    if not header_token or not cookie_token:
        return False
    return hmac.compare_digest(header_token, cookie_token)


def csrf_matches_hash(header_token: Optional[str], stored_hash: Optional[str]) -> bool:
    """Constant-time comparison of an echoed token against a stored digest."""
    if not header_token or not stored_hash:
        return False
    return hmac.compare_digest(hash_csrf_token(header_token), stored_hash)


__all__ = [
    "CSRF_COOKIE_NAME",
    "CSRF_HEADER_NAME",
    "SESSION_COOKIE_NAME",
    "SESSION_HEADER_NAME",
    "SESSION_TOKEN_PREFIX",
    "clear_csrf_cookie",
    "clear_kyber_cookies",
    "clear_session_cookie",
    "cookie_attributes",
    "cookie_secure",
    "csrf_matches",
    "csrf_matches_hash",
    "current_environment",
    "hash_csrf_token",
    "issue_csrf_token",
    "read_csrf_cookie",
    "read_csrf_header",
    "read_session_token",
    "set_csrf_cookie",
    "set_session_cookie",
]
