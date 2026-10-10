"""RFC 7636 PKCE (Proof Key for Code Exchange) — S256 only.

PKCE binds an authorization request to the client that started it: the client
sends ``code_challenge = base64url(sha256(verifier))`` on the authorize call and
proves possession by sending the raw ``verifier`` on the token call. Only the
S256 method is supported here — ``plain`` offers no protection and is refused by
omission.

The verifier is a high-entropy secret; it must be persisted server-side bound to
the flow and never exposed to the browser. This module only computes and
compares — storage/binding is the broker's responsibility.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import re
import secrets
from dataclasses import dataclass

#: RFC 7636 §4.1 — verifier length bounds (unreserved characters only).
MIN_VERIFIER_LENGTH = 43
MAX_VERIFIER_LENGTH = 128

CHALLENGE_METHOD = "S256"

# Unreserved set per RFC 7636 §4.1: ALPHA / DIGIT / "-" / "." / "_" / "~".
_VERIFIER_RE = re.compile(r"^[A-Za-z0-9\-._~]{43,128}$")


@dataclass(frozen=True)
class PkcePair:
    """A verifier/challenge pair. ``method`` is always :data:`CHALLENGE_METHOD`."""

    verifier: str
    challenge: str
    method: str = CHALLENGE_METHOD


def _b64url_no_pad(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _validate_verifier(verifier: str) -> None:
    if not isinstance(verifier, str) or not _VERIFIER_RE.match(verifier):
        raise ValueError(
            "PKCE verifier must be 43-128 unreserved characters (RFC 7636 §4.1)"
        )


def compute_challenge(verifier: str) -> str:
    """Return ``base64url(sha256(verifier))`` with padding stripped (S256)."""
    _validate_verifier(verifier)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return _b64url_no_pad(digest)


def generate_pkce() -> PkcePair:
    """Generate a fresh, RFC-compliant S256 verifier/challenge pair.

    ``token_urlsafe(96)`` yields 128 unreserved characters, the RFC maximum; the
    slice is defensive against future changes to the token width.
    """
    verifier = secrets.token_urlsafe(96)[:MAX_VERIFIER_LENGTH]
    return PkcePair(verifier=verifier, challenge=compute_challenge(verifier))


def verify_pkce(verifier: str, challenge: str) -> bool:
    """Constant-time check that ``verifier`` produces ``challenge`` under S256.

    Returns ``False`` (never raises) for a malformed verifier or a mismatch, so
    the token-exchange path can treat every failure identically.
    """
    if not isinstance(challenge, str):
        return False
    try:
        expected = compute_challenge(verifier)
    except ValueError:
        return False
    return hmac.compare_digest(expected, challenge)


__all__ = [
    "CHALLENGE_METHOD",
    "MAX_VERIFIER_LENGTH",
    "MIN_VERIFIER_LENGTH",
    "PkcePair",
    "compute_challenge",
    "generate_pkce",
    "verify_pkce",
]
