"""PR2 webhook admission controls on the endpoint-registry native path
(``handle_verified_webhook``):

  * per-endpoint rate limiting is enforced BEFORE signature verification and
    surfaces as a retryable 429 (RateLimitedError), so the provider backs off;
  * denied webhooks (bad/stale signature, oversized body) are quarantined
    metadata-only — a sha256 + size + reason, never the raw body.

Rate-limit accounting happens before the signature check, so these tests do not
need valid signatures to exercise it (an unverifiable body still counts, then is
rejected 4xx and quarantined).
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import os

import pytest

os.environ.setdefault("AETHER_ENV", "local")

from config.settings import settings  # noqa: E402
from repositories.repos import reset_in_memory_stores  # noqa: E402
from shared.cache.cache import CacheClient  # noqa: E402
from shared.common.common import RateLimitedError  # noqa: E402
from services.integrations.providers.payment_rails.rate_limit import (  # noqa: E402
    PaymentWebhookRateLimiter,
)
from services.integrations.providers.payment_rails.service import (  # noqa: E402
    PaymentRailsService,
)
from services.integrations.providers.payment_rails.webhook_endpoints import (  # noqa: E402
    WebhookEndpointRegistry,
)
from services.integrations.webhook_quarantine import webhook_quarantine  # noqa: E402


def _patch_rails(monkeypatch, **overrides):
    fields = {
        "enabled": True, "coinbase_enabled": True, "stripe_enabled": True,
        "bridge_enabled": True, "webhook_rate_limit_enabled": True,
        "webhook_rate_limit_per_minute": 600, "webhook_quarantine_denied": True,
    }
    fields.update(overrides)
    monkeypatch.setattr(
        settings, "payment_rails", dataclasses.replace(settings.payment_rails, **fields)
    )


def _quarantined_for(tenant_id: str) -> list[dict]:
    return [r for r in webhook_quarantine._store.values() if r.get("tenant_id") == tenant_id]


# ── rate limiter unit ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_rate_limiter_allows_then_blocks():
    rl = PaymentWebhookRateLimiter(cache=CacheClient())
    ep = "whe_ratelimit_unit_a"
    seen = [await rl.allow(provider="stripe", limit=3, endpoint_id=ep) for _ in range(4)]
    assert seen == [True, True, True, False]


@pytest.mark.asyncio
async def test_rate_limiter_zero_limit_allows_all():
    rl = PaymentWebhookRateLimiter(cache=CacheClient())
    assert await rl.allow(provider="stripe", limit=0, endpoint_id="whe_zero") is True


@pytest.mark.asyncio
async def test_rate_limiter_fails_open_on_cache_error():
    class _Boom:
        async def incr_if_under(self, *a, **k):
            raise RuntimeError("cache unavailable")

    rl = PaymentWebhookRateLimiter(cache=_Boom())
    assert await rl.allow(provider="stripe", limit=1, endpoint_id="whe_boom") is True


@pytest.mark.asyncio
async def test_rate_limiter_scopes_by_endpoint():
    rl = PaymentWebhookRateLimiter(cache=CacheClient())
    assert await rl.allow(provider="stripe", limit=1, endpoint_id="whe_scope_1") is True
    # a different endpoint has its own independent budget
    assert await rl.allow(provider="stripe", limit=1, endpoint_id="whe_scope_2") is True
    # the first endpoint is now exhausted
    assert await rl.allow(provider="stripe", limit=1, endpoint_id="whe_scope_1") is False


# ── integration through handle_verified_webhook ──────────────────────────────

@pytest.mark.asyncio
async def test_webhook_rate_limited_returns_429_after_budget(monkeypatch):
    reset_in_memory_stores()
    _patch_rails(monkeypatch, webhook_rate_limit_per_minute=2)
    reg = WebhookEndpointRegistry()
    svc = PaymentRailsService()
    ep = await reg.create("tenantRL", "coinbase", "sandbox", created_by="admin")
    endpoint_id = ep["endpoint_id"]
    body = b'{"type":"noise"}'

    # First two are admitted by the limiter (then rejected 4xx for a bad sig).
    for _ in range(2):
        res = await svc.handle_verified_webhook(
            "tenantRL", "coinbase", "sandbox", body, "bad-sig", endpoint_id=endpoint_id,
        )
        assert res["handled"] is False

    # The third trips the per-endpoint budget → retryable 429 before any crypto.
    with pytest.raises(RateLimitedError):
        await svc.handle_verified_webhook(
            "tenantRL", "coinbase", "sandbox", body, "bad-sig", endpoint_id=endpoint_id,
        )


@pytest.mark.asyncio
async def test_disabled_rate_limit_does_not_block(monkeypatch):
    reset_in_memory_stores()
    _patch_rails(monkeypatch, webhook_rate_limit_enabled=False)
    svc = PaymentRailsService()
    # Many unverifiable posts never raise a 429 when the limiter is off.
    for _ in range(5):
        res = await svc.handle_verified_webhook(
            "tenantNoRL", "coinbase", "sandbox", b'{"x":1}', "bad-sig",
            endpoint_id="whe_norl",
        )
        assert res["handled"] is False


@pytest.mark.asyncio
async def test_denied_signature_is_quarantined_metadata_only(monkeypatch):
    reset_in_memory_stores()
    _patch_rails(monkeypatch)
    svc = PaymentRailsService()
    body = b'{"pan":"4111111111111111","note":"should never be stored raw"}'

    res = await svc.handle_verified_webhook(
        "tenantQ", "coinbase", "sandbox", body, "bad-sig", endpoint_id="whe_q",
    )
    assert res["handled"] is False

    records = _quarantined_for("tenantQ")
    assert len(records) == 1
    rec = records[0]
    assert rec["provider"] == "payment_rail:coinbase"
    assert rec["payload_sha256"] == hashlib.sha256(body).hexdigest()
    assert rec["payload_size_bytes"] == len(body)
    # metadata only — the raw body (and its sensitive content) is never stored
    assert "4111111111111111" not in json.dumps(rec)


@pytest.mark.asyncio
async def test_body_too_large_is_rejected_and_quarantined(monkeypatch):
    reset_in_memory_stores()
    _patch_rails(monkeypatch)
    svc = PaymentRailsService()
    oversized = b"x" * (svc.MAX_WEBHOOK_BODY_BYTES + 1)

    res = await svc.handle_verified_webhook(
        "tenantBig", "coinbase", "sandbox", oversized, "sig", endpoint_id="whe_big",
    )
    assert res == {"handled": False, "reason": "body_too_large"}
    records = _quarantined_for("tenantBig")
    assert len(records) == 1
    assert records[0]["reason_code"] == "body_too_large"
    assert records[0]["payload_size_bytes"] == len(oversized)


@pytest.mark.asyncio
async def test_quarantine_can_be_disabled(monkeypatch):
    reset_in_memory_stores()
    _patch_rails(monkeypatch, webhook_quarantine_denied=False)
    svc = PaymentRailsService()
    res = await svc.handle_verified_webhook(
        "tenantND", "coinbase", "sandbox", b'{"x":1}', "bad-sig", endpoint_id="whe_nd",
    )
    assert res["handled"] is False
    assert _quarantined_for("tenantND") == []
