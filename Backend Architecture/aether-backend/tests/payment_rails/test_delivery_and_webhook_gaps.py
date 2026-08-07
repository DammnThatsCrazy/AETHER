"""Delivery + webhook gap-fill (C2, D2, B1, B3, F1).

- C2 cross-source dedupe: webhook then poll of the same tx → one session, no
  duplicate canonical/usage.
- D2 dead-letter: a receipt that can never reach a funding session is dead-lettered.
- B1 cross-environment isolation: a sandbox endpoint resolves the sandbox secret,
  so a live-signed webhook fails.
- B3 missing-signature for coinbase / bridge / privy.
- F1 negative fee amounts are exact decimals, not coerced/rejected.

All in-memory (AETHER_ENV=local).
"""

from __future__ import annotations

import dataclasses
import hashlib
import hmac
import os
import uuid
from datetime import datetime, timezone

import pytest

os.environ.setdefault("AETHER_ENV", "local")

from config.settings import settings  # noqa: E402
from repositories.repos import reset_in_memory_stores  # noqa: E402
from services.integrations.providers.payment_rails import ADAPTERS  # noqa: E402
from services.integrations.providers.payment_rails.base import payload_hash  # noqa: E402
from services.integrations.providers.payment_rails.moonpay import _sum_fee  # noqa: E402
from services.integrations.providers.payment_rails.receipts import ReceiptState, ReceiptStage  # noqa: E402
from services.integrations.providers.payment_rails.repository import PaymentRailsRepositories  # noqa: E402
from services.integrations.providers.payment_rails.service import PaymentRailsService  # noqa: E402
from services.integrations.providers.payment_rails.signature_verify import verify_signature  # noqa: E402
from services.providers.credentials.authority import credential_authority  # noqa: E402

pytestmark = pytest.mark.asyncio


class _Producer:
    def __init__(self):
        self.events = []

    async def publish(self, event):
        self.events.append(event)

    async def publish_batch(self, events):
        self.events.extend(events)


def _svc():
    return PaymentRailsService(PaymentRailsRepositories(), producer=_Producer())


def _tenant():
    return f"t-{uuid.uuid4().hex[:8]}"


# ── C2: webhook then poll of the same tx ──────────────────────────────────────

async def test_webhook_then_poll_same_tx_no_duplicate(monkeypatch):
    reset_in_memory_stores()
    svc, tenant = _svc(), _tenant()
    adapter = ADAPTERS["moonpay"]
    record = {"id": "tx-conv", "status": "completed", "externalCustomerId": "u1",
              "baseCurrencyAmount": 100, "quoteCurrencyAmount": 95,
              "baseCurrency": {"code": "usd"}, "currency": {"code": "usdc"}}
    wh = adapter.parse_webhook(tenant, {"type": "transaction_updated", "data": record},
                               payload_hash({"data": record}))[0]
    await svc._process_event(tenant, adapter, wh, environment="sandbox")
    canonical_after_webhook = len(svc.producer.events)

    # Same transaction observed again via polling.
    poll = adapter._parse_poll_records(tenant, [record])[0]
    await svc._process_event(tenant, adapter, poll, environment="sandbox")

    sessions = await svc.repos.sessions.list_for_tenant(tenant)
    same_tx = [s for s in sessions if s.get("idempotency_key") == "moonpay:tx-conv"]
    assert len(same_tx) == 1  # converged on one funding session
    assert len(svc.producer.events) == canonical_after_webhook  # no duplicate canonical/usage


# ── D2: dead-letter ───────────────────────────────────────────────────────────

async def test_receipt_without_session_is_dead_lettered(monkeypatch):
    reset_in_memory_stores()
    svc, tenant = _svc(), _tenant()
    r = await svc.repos.receipts.open(
        tenant, "moonpay", provider_event_id="stuck-1", body_hash="h",
        environment="sandbox", stage=ReceiptStage.RECEIVED,
    )
    rid = r["receipt_id"]
    # Simulate a delivery that exhausted its repair budget without a session.
    r["repair_attempts"] = svc.MAX_REPAIR_ATTEMPTS
    await svc.repos.receipts._store.set(f"{tenant}:{rid}", r)

    stats = await svc.run_canonical_repair(tenant)
    assert stats["receipts_dead_lettered"] >= 1
    healed = await svc.repos.receipts.get(tenant, rid)
    assert healed["current_stage"] == ReceiptState.DEAD_LETTERED


# ── B1: cross-environment isolation ───────────────────────────────────────────

async def test_sandbox_endpoint_rejects_live_signed_webhook(monkeypatch):
    reset_in_memory_stores()
    monkeypatch.setattr(settings, "payment_rails", dataclasses.replace(
        settings.payment_rails, enabled=True, coinbase_enabled=True,
    ))
    svc, tenant = _svc(), _tenant()
    for env, secret in (("sandbox", "sbx_secret"), ("live", "live_secret")):
        await credential_authority.create_pending(
            tenant, "coinbase", env, "webhook_signing_secret", secret, created_by="admin")
        await credential_authority.activate(
            tenant, "coinbase", env, "webhook_signing_secret", credential_version=1, actor="admin")

    body = b'{"event_type":"onramp.transaction.updated","transaction":{"transaction_id":"t","status":"success","partner_user_ref":"u"}}'
    ts = str(int(datetime.now(timezone.utc).timestamp()))
    live_sig = hmac.new(b"live_secret", body, hashlib.sha256).hexdigest()
    sbx_sig = hmac.new(b"sbx_secret", body, hashlib.sha256).hexdigest()

    # The endpoint is in the sandbox environment → sandbox secret is resolved.
    live_result = await svc.handle_verified_webhook(
        tenant, "coinbase", "sandbox", body, live_sig, ts, endpoint_id="whe_x")
    assert live_result["handled"] is False  # live-signed body fails against sandbox secret
    sbx_result = await svc.handle_verified_webhook(
        tenant, "coinbase", "sandbox", body, sbx_sig, ts, endpoint_id="whe_x")
    assert sbx_result["handled"] is True


# ── B3: missing signature per provider ────────────────────────────────────────

@pytest.mark.parametrize("provider", ["coinbase", "bridge", "privy"])
async def test_missing_signature_rejected(provider):
    adapter = ADAPTERS[provider]
    body = b'{"any":"body"}'
    # No signature supplied → verification fails (never accepted).
    result = verify_signature(
        adapter.native_signature_scheme(), ["some_secret"], body, None,
        timestamp="123", now_epoch=123,
    )
    assert result.ok is False


# ── F1: negative fee amounts ──────────────────────────────────────────────────

def test_sum_fee_negative_amounts_exact():
    # A negative component (e.g. a fee adjustment/refund) is summed exactly,
    # never coerced to zero or rejected.
    assert _sum_fee({"feeAmount": "-0.5", "extraFeeAmount": "1.5"}) == "1.0"
    assert _sum_fee({"feeAmount": "-2.5"}) == "-2.5"
