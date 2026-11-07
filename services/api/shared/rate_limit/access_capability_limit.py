"""Per-credential, per-capability request cap for Access Kit reads.

The tenant burst limiter (``limiter.py``) shares one pool across every key in a
tenant. This cap sits under it so a single API key or delegated token cannot use
the whole tenant allowance on one capability. It applies only to requests that
hit a named Access Kit route (whatever surface label the client sends), and never to platform operators. The caller keys it on the credential the authenticator validated, not on request headers.

The limit is requests per minute per (credential, capability). It defaults to
``DEFAULT_LIMIT_RPM`` and is set with ``AETHER_ACCESS_KIT_CREDENTIAL_RPM``;
``0`` disables it. The default is a proposal pending billing-owner approval; see
docs/architecture/target/access-kit-w4-limits-contract.md.
"""

from __future__ import annotations

import hashlib
import os
import time
from typing import Any, Optional

from shared.rate_limit.limiter import RateLimitResult

DEFAULT_LIMIT_RPM = 120
_WINDOW_SECONDS = 60
_MAX_MEMORY_BUCKETS = 10_000


def configured_limit() -> int:
    raw = os.getenv("AETHER_ACCESS_KIT_CREDENTIAL_RPM", "")
    if not raw.strip():
        return DEFAULT_LIMIT_RPM
    try:
        return max(0, int(raw))
    except ValueError:
        return DEFAULT_LIMIT_RPM


def credential_fingerprint(secret: str, fallback: str = "") -> str:
    """Stable, non-reversible identifier for the presented credential."""
    material = secret or fallback
    return hashlib.sha256(material.encode()).hexdigest()[:16] if material else ""


class AccessCredentialLimiter:
    """Fixed-window counter; Redis when provided, otherwise per-process memory."""

    def __init__(self) -> None:
        self._buckets: dict[str, tuple[float, int]] = {}

    async def check(
        self,
        tenant_id: str,
        credential_id: str,
        capability_id: str,
        *,
        limit: Optional[int] = None,
        redis: Any = None,
    ) -> RateLimitResult:
        limit = configured_limit() if limit is None else limit
        now = time.time()
        if limit <= 0 or not credential_id:
            return RateLimitResult(True, limit, limit, now + _WINDOW_SECONDS)
        window = int(now // _WINDOW_SECONDS)
        key = f"ak:cred:{tenant_id}:{credential_id}:{capability_id}:{window}"
        reset_at = (window + 1) * _WINDOW_SECONDS
        count = await self._increment(key, now, redis)
        if count > limit:
            return RateLimitResult(False, limit, 0, reset_at, max(1, int(reset_at - now)))
        return RateLimitResult(True, limit, limit - count, reset_at)

    async def _increment(self, key: str, now: float, redis: Any) -> int:
        if redis is not None:
            try:
                count = int(await redis.incr(key))
                if count == 1:
                    await redis.expire(key, _WINDOW_SECONDS * 2)
                return count
            except Exception:  # noqa: BLE001 - fall back to this process's counter
                pass
        if len(self._buckets) >= _MAX_MEMORY_BUCKETS:
            self._buckets = {k: v for k, v in self._buckets.items() if v[0] > now}
        expires, count = self._buckets.get(key, (now + _WINDOW_SECONDS * 2, 0))
        self._buckets[key] = (expires, count + 1)
        return count + 1
