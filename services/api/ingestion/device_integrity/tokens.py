"""Single-use attestation challenges and signed device-integrity tokens.

After a successful attestation the server issues a short-lived token bound to
the tenant, the install's anonymous id and the platform. The mobile SDK sends it
as ``context.device.integrity.token`` and ingestion verifies it on every event.

Limit (documented): the token is a bearer credential for its lifetime; a client
that attested once can replay it from elsewhere with the same anonymous id until
it expires. Per-event App Attest assertions would close that gap.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from typing import Any, Optional

VERDICTS = ("verified", "basic", "virtual", "failed")
PLATFORMS = ("ios", "android")
_LOCAL_SECRET = secrets.token_bytes(32)  # local/dev only, when no secret is configured


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64url(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def token_key(configured: str, *, allow_ephemeral: bool) -> Optional[bytes]:
    if configured:
        return hashlib.sha256(configured.encode("utf-8")).digest()
    return _LOCAL_SECRET if allow_ephemeral else None


def new_challenge() -> str:
    return _b64url(secrets.token_bytes(32))


def issue_token(
    key: bytes, *, tenant_id: str, anonymous_id: str, platform: str, verdict: str,
    ttl_seconds: int, now: Optional[float] = None,
) -> tuple[str, int]:
    if verdict not in VERDICTS or platform not in PLATFORMS:
        raise ValueError("bad verdict or platform")
    issued = int(now if now is not None else time.time())
    payload = {"v": 1, "t": tenant_id, "a": anonymous_id, "p": platform, "d": verdict,
               "iat": issued, "exp": issued + ttl_seconds}
    body = _b64url(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode())
    sig = _b64url(hmac.new(key, body.encode(), hashlib.sha256).digest())
    return f"{body}.{sig}", payload["exp"]


def verify_token(
    key: bytes, token: Any, *, tenant_id: str, anonymous_id: Optional[str], now: Optional[float] = None,
) -> Optional[dict[str, Any]]:
    """Return ``{"verdict", "platform"}`` for a valid token, else ``None``."""
    if not isinstance(token, str) or token.count(".") != 1 or len(token) > 2048:
        return None
    body, sig = token.split(".")
    expected = _b64url(hmac.new(key, body.encode(), hashlib.sha256).digest())
    if not hmac.compare_digest(expected, sig):
        return None
    try:
        payload = json.loads(_unb64url(body))
    except (ValueError, TypeError):
        return None
    current = int(now if now is not None else time.time())
    if payload.get("v") != 1 or payload.get("t") != tenant_id or payload.get("exp", 0) < current:
        return None
    if not anonymous_id or payload.get("a") != anonymous_id:
        return None
    if payload.get("d") not in VERDICTS or payload.get("p") not in PLATFORMS:
        return None
    return {"verdict": payload["d"], "platform": payload["p"]}


__all__ = ["PLATFORMS", "VERDICTS", "issue_token", "new_challenge", "token_key", "verify_token"]
