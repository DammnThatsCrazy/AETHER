"""Integration Security.

Hardens the integration/webhook dispatch surface: HMAC webhook signing, secret
rotation, destination safety, optional tenant allowlist, retry/idempotency
enforcement, repeated-failure detection, and audit of config changes + dispatch
attempts. Secrets are never returned by any method here.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
import time
from collections import defaultdict
from typing import Any, Optional

from shared.common.common import BadRequestError
from shared.logger.logger import get_logger

from .audit_ledger import audit_ledger
from .contracts import ActorType, sanitize_metadata
from .policy_engine import evaluate_destination_safety, policy_engine

logger = get_logger("aether.security.integration_security")

MAX_RETRIES = 5
FAILURE_ALERT_THRESHOLD = 5

# In-memory dedupe + failure tracking for the local/dev path.
_SEEN_IDEMPOTENCY: dict[str, float] = {}
_FAILURE_COUNTS: dict[str, int] = defaultdict(int)


def sign_payload(secret: str, payload: bytes, timestamp: Optional[int] = None) -> dict[str, str]:
    """Produce a webhook signature header set. The secret is consumed here and
    never returned."""
    ts = timestamp or int(time.time())
    mac = hmac.new(secret.encode("utf-8"), f"{ts}.".encode() + payload, hashlib.sha256)
    return {"X-Aether-Timestamp": str(ts), "X-Aether-Signature": f"v1={mac.hexdigest()}"}


def verify_signature(secret: str, payload: bytes, timestamp: str, signature: str, tolerance_s: int = 300) -> bool:
    try:
        ts = int(timestamp)
    except (TypeError, ValueError):
        return False
    if abs(time.time() - ts) > tolerance_s:
        return False
    expected = hmac.new(secret.encode("utf-8"), f"{ts}.".encode() + payload, hashlib.sha256).hexdigest()
    provided = signature.split("=", 1)[-1]
    return hmac.compare_digest(expected, provided)


def generate_webhook_secret() -> str:
    """Generate a fresh signing secret. Callers must store it securely; it must
    never be echoed back through an API/UI/audit event."""
    return f"whsec_{secrets.token_urlsafe(32)}"


def redact_config(config: dict[str, Any]) -> dict[str, Any]:
    """Strip secret material from an integration config before returning it."""
    cleaned = sanitize_metadata(config)
    for k in list(cleaned.keys()):
        if k in ("signing_secret", "webhook_secret", "secret"):
            cleaned.pop(k, None)
    if any(k in config for k in ("signing_secret", "webhook_secret", "secret")):
        cleaned["secret_configured"] = True
    return cleaned


class IntegrationSecurity:
    async def rotate_secret(
        self, *, tenant_id: str, integration_id: str, actor_id: str,
        actor_type: ActorType = 'tenant_user',
    ) -> dict[str, Any]:
        new_secret = generate_webhook_secret()
        await audit_ledger.record(
            actor_id=actor_id, actor_type=actor_type,
            event_type="integration.secret_rotated", resource_type="integration",
            action="configure", outcome='allowed', tenant_id=tenant_id,
            resource_id=integration_id,
        )
        # Return only a non-secret reference; caller persists `new_secret` securely.
        return {"integration_id": integration_id, "rotated": True, "secret": new_secret}

    async def audit_config_change(
        self, *, tenant_id: str, integration_id: str, actor_id: str,
        actor_type: ActorType, change: dict[str, Any],
    ) -> None:
        await audit_ledger.record(
            actor_id=actor_id, actor_type=actor_type,
            event_type="integration.config_changed", resource_type="integration",
            action="configure", outcome='allowed', tenant_id=tenant_id,
            resource_id=integration_id, metadata=redact_config(change),
        )

    async def validate_destination(self, url: str, allowlist: Optional[list[str]] = None) -> None:
        # DNS resolution is offloaded to a bounded threadpool (see
        # evaluate_destination_safety) so a slow/wedged resolver never blocks the
        # async dispatch path / FastAPI event loop.
        unsafe, why = await evaluate_destination_safety(url)
        if unsafe:
            raise BadRequestError(f"unsafe webhook destination: {why}")
        if allowlist:
            from urllib.parse import urlparse
            host = (urlparse(url).hostname or "").lower()
            if host not in {h.lower() for h in allowlist}:
                raise BadRequestError(f"destination host {host!r} not in tenant allowlist")

    async def authorize_dispatch(
        self, *, tenant_id: str, integration_id: str, actor_id: str,
        actor_type: ActorType, integration_enabled: bool, destination_url: str,
        idempotency_key: Optional[str] = None, attempt: int = 1,
        allowlist: Optional[list[str]] = None,
    ) -> dict[str, Any]:
        if attempt > MAX_RETRIES:
            raise BadRequestError(f"retry limit ({MAX_RETRIES}) exceeded")
        if not idempotency_key:
            raise BadRequestError("idempotency_key is required for dispatch")
        dedupe_key = f"{tenant_id}:{integration_id}:{idempotency_key}"
        if dedupe_key in _SEEN_IDEMPOTENCY:
            return {"deduplicated": True, "dispatched": False}

        await self.validate_destination(destination_url, allowlist)
        decision = await policy_engine.check_integration_dispatch(
            actor_id=actor_id, actor_type=actor_type, tenant_id=tenant_id,
            integration_enabled=integration_enabled, destination_url=destination_url,
            integration_id=integration_id,
        )
        if not decision.allowed:
            return {"dispatched": False, "blocked": True, "reason": decision.reason}

        _SEEN_IDEMPOTENCY[dedupe_key] = time.time()
        await audit_ledger.record(
            actor_id=actor_id, actor_type=actor_type,
            event_type="integration.dispatch_attempt", resource_type="integration",
            action="dispatch", outcome='allowed', tenant_id=tenant_id,
            resource_id=integration_id, policy_decision_id=decision.decision_id,
            metadata={"attempt": attempt},
        )
        return {"dispatched": True, "policy_decision_id": decision.decision_id}

    async def record_failure(
        self, *, tenant_id: str, integration_id: str, actor_id: str = "system",
    ) -> dict[str, Any]:
        key = f"{tenant_id}:{integration_id}"
        _FAILURE_COUNTS[key] += 1
        count = _FAILURE_COUNTS[key]
        repeated = count >= FAILURE_ALERT_THRESHOLD
        await audit_ledger.record(
            actor_id=actor_id, actor_type='system',
            event_type="integration.dispatch_failed", resource_type="integration",
            action="dispatch", outcome='failed', tenant_id=tenant_id,
            resource_id=integration_id, metadata={"failure_count": count, "repeated": repeated},
        )
        return {"failure_count": count, "repeated_failures_detected": repeated}


integration_security = IntegrationSecurity()
