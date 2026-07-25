"""Baseline security response headers (middleware/middleware.py).

The helper is tested directly against a minimal fake response so these
assertions do not need the FastAPI app, a live route table, or auth.

Two regressions are specifically guarded:
  * HSTS must never be emitted outside production (it would pin a developer's
    browser to HTTPS on localhost for a year).
  * ``Permissions-Policy`` must NOT deny ``publickey-credentials-get`` — Kyber
    WebAuthn enrollment and step-up would silently break.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2] / "Backend Architecture" / "aether-backend"
sys.path.insert(0, str(BACKEND))
os.environ.setdefault("AETHER_ENV", "local")

from middleware.middleware import _apply_security_headers  # noqa: E402


class FakeResponse:
    """Minimal stand-in exposing the only surface the helper touches."""

    def __init__(self, headers: dict[str, str] | None = None) -> None:
        self.headers: dict[str, str] = dict(headers or {})


def _headers(*, is_production: bool = False, initial: dict[str, str] | None = None):
    response = FakeResponse(initial)
    returned = _apply_security_headers(response, is_production=is_production)
    assert returned is response, "helper must return the same response object"
    return response.headers


def test_baseline_headers_have_exact_expected_values() -> None:
    headers = _headers()
    assert headers["Content-Security-Policy"] == "frame-ancestors 'none'"
    assert headers["X-Content-Type-Options"] == "nosniff"
    assert headers["Referrer-Policy"] == "strict-origin-when-cross-origin"
    assert headers["Permissions-Policy"] == (
        "camera=(), microphone=(), geolocation=(), payment=(), usb=()"
    )


def test_hsts_present_in_production() -> None:
    headers = _headers(is_production=True)
    assert headers["Strict-Transport-Security"] == "max-age=31536000; includeSubDomains"


def test_hsts_absent_outside_production() -> None:
    headers = _headers(is_production=False)
    assert "Strict-Transport-Security" not in headers


def test_permissions_policy_does_not_disable_webauthn() -> None:
    """Kyber device trust calls navigator.credentials.get() — never deny it."""
    for is_production in (False, True):
        policy = _headers(is_production=is_production)["Permissions-Policy"]
        assert "publickey-credentials-get" not in policy
        assert "publickey-credentials-create" not in policy


def test_existing_csp_is_not_overwritten() -> None:
    existing = "default-src 'self'; frame-ancestors 'self'"
    headers = _headers(initial={"Content-Security-Policy": existing})
    assert headers["Content-Security-Policy"] == existing
    # The rest of the baseline still applies.
    assert headers["X-Content-Type-Options"] == "nosniff"


def test_no_conflicting_or_isolation_headers_are_set() -> None:
    """X-Frame-Options conflicts with frame-ancestors; COOP/COEP break embeds."""
    headers = _headers(is_production=True)
    for banned in (
        "X-Frame-Options",
        "Cross-Origin-Opener-Policy",
        "Cross-Origin-Embedder-Policy",
        "Cross-Origin-Resource-Policy",
    ):
        assert banned not in headers


async def test_helper_is_usable_from_async_middleware() -> None:
    """The lifecycle middleware is async; the helper stays a plain call."""
    headers = _headers()
    assert headers["Content-Security-Policy"] == "frame-ancestors 'none'"
