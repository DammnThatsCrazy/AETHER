"""B4 / B5 — additional webhook admission + verification edge cases.

WHAT THIS COVERS / WHY IT WAS NEEDED
------------------------------------
``test_webhook_admission.py`` already covers per-endpoint rate limiting,
oversized-body quarantine, and denied-signature quarantine. This module adds the
edge cases that were still MISSING on the endpoint-registry native path
(``handle_verified_webhook``), all of which protect delivery integrity once a
body has been admitted:

  B4 replay integrity
    * A verbatim provider redelivery of a validly-signed webhook maps to the
      ONE deterministic receipt, persists ONE FundingSession, emits its canonical
      events exactly once, and — critically — does NOT double-meter usage
      (billing safety). The second delivery is reported ``ignored_duplicate``.

  B5 malformed / hostile body handling (post-signature)
    * A body that passes signature verification but is not valid JSON is rejected
      safely (a uniform ``BadRequestError``) and leaves NO partial state — no
      session, no provider event, no receipt fabricated from an unparseable body.
    * A validly-signed body that is valid JSON but not a JSON object is rejected
      the same uniform way.
    * A malformed / unsupported signature format for a COMPOUND-header provider
      (Stripe) is rejected with a uniform, secret-free reason and a server-side
      audit entry — the verifier never leaks whether the id/secret existed.

DELIVERY-INTEGRITY GUARANTEE PROTECTED
--------------------------------------
One receipt / one session / one canonical event per observation / no duplicate
usage on replay; and no partially-persisted state from a body that never became
a real observation. Rejections are uniform and audited (no oracle for attackers).
"""

from __future__ import annotations

import dataclasses
import hashlib
import hmac
import json
import os
import uuid

import pytest

os.environ.setdefault("AETHER_ENV", "local")

from config.settings import settings  # noqa: E402
from repositories.repos import reset_in_memory_stores  # noqa: E402
from shared.common.common import BadRequestError  # noqa: E402
from services.billing.revops import UsageMeteringEventRepository  # noqa: E402
from services.integrations.providers.payment_rails.repository import (  # noqa: E402
    PaymentRailsRepositories,
)
from services.integrations.providers.payment_rails.service import (  # noqa: E402
    PaymentRailsService,
)
from services.providers.credentials.authority import credential_authority  # noqa: E402

pytestmark = pytest.mark.asyncio


class _RecordingProducer:
    def __init__(self) -> None:
        self.events = []

    async def publish(self, event) -> None:
        self.events.append(event)

    async def publish_batch(self, events) -> None:
        self.events.extend(events)


def _svc():
    return PaymentRailsService(
        repositories=PaymentRailsRepositories(), producer=_RecordingProducer()
    )


def _tenant() -> str:
    return f"t-{uuid.uuid4().hex[:8]}"


def _patch(monkeypatch, **overrides):
    fields = {
        "enabled": True, "coinbase_enabled": True, "stripe_enabled": True,
        "webhook_rate_limit_enabled": False, "webhook_quarantine_denied": False,
    }
    fields.update(overrides)
    monkeypatch.setattr(
        settings, "payment_rails", dataclasses.replace(settings.payment_rails, **fields)
    )


async def _configure_webhook_secret(tenant: str, provider: str, env: str, secret: str) -> None:
    await credential_authority.create_pending(
        tenant, provider, env, "webhook_signing_secret", secret, created_by="admin"
    )
    await credential_authority.activate(
        tenant, provider, env, "webhook_signing_secret", credential_version=1, actor="admin"
    )


def _coinbase_body(tx_id: str = "cb1", status: str = "ONRAMP_TRANSACTION_STATUS_SUCCESS") -> bytes:
    return json.dumps({
        "event_type": "onramp.transaction.updated",
        "transaction": {
            "transaction_id": tx_id, "partner_user_ref": "user-1", "status": status,
            "purchase_amount": {"value": "50", "currency": "USDC"},
            "payment_total": {"value": "51", "currency": "USD"},
            "purchase_currency": "USDC", "purchase_network": "base",
            "wallet_address": "0xabc",
        },
    }).encode()


def _body_hex_sig(secret: str, body: bytes) -> str:
    # Coinbase native scheme signs the raw body (no timestamp).
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


async def _meters(tenant: str):
    return await UsageMeteringEventRepository().find_many(filters={"tenant_id": tenant})


# ── B4: replay maps to one receipt / one session / no double usage ────────────


async def test_replayed_signed_webhook_dedupes_to_one_receipt_no_double_usage(monkeypatch):
    reset_in_memory_stores()
    _patch(monkeypatch, usage_metering_enabled=True)
    svc = _svc()
    tenant, env, provider = _tenant(), "sandbox", "coinbase"
    secret = "whsec_replay"
    await _configure_webhook_secret(tenant, provider, env, secret)

    body = _coinbase_body()
    sig = _body_hex_sig(secret, body)

    first = await svc.handle_verified_webhook(
        tenant, provider, env, body, sig, endpoint_id="whe_replay",
    )
    assert first["handled"] is True
    first_receipt = first["events"][0]["receipt_id"]
    # a completed onramp implies payment_initiated + payment_completed → 2 meters
    assert len(await _meters(tenant)) == 2
    canonical_after_first = len(svc.producer.events)

    # Verbatim provider redelivery of the exact same signed body.
    second = await svc.handle_verified_webhook(
        tenant, provider, env, body, sig, endpoint_id="whe_replay",
    )
    assert second["handled"] is True
    assert second["events"][0]["disposition"] == "ignored_duplicate"
    # SAME deterministic receipt — one delivery ledger row, not two.
    assert second["events"][0]["receipt_id"] == first_receipt

    # No double-emit, no double-bill, still exactly one funding session.
    assert len(svc.producer.events) == canonical_after_first
    assert len(await _meters(tenant)) == 2  # usage metered once per canonical event
    assert len(await svc.repos.sessions.list_for_tenant(tenant)) == 1

    # The replay is recorded as a completed delivery on the one receipt.
    receipt = await svc.repos.receipts.get(tenant, first_receipt)
    assert receipt["processing_attempts"] == 2  # both deliveries hit one ledger row


# ── B5: malformed / non-object body rejected safely after signature passes ────


async def test_valid_signature_but_malformed_json_rejected_without_partial_state(monkeypatch):
    reset_in_memory_stores()
    _patch(monkeypatch)
    svc = _svc()
    tenant, env, provider = _tenant(), "sandbox", "coinbase"
    secret = "whsec_malformed"
    await _configure_webhook_secret(tenant, provider, env, secret)

    body = b"this is not json at all"
    sig = _body_hex_sig(secret, body)  # a VALID signature over the malformed body

    with pytest.raises(BadRequestError):
        await svc.handle_verified_webhook(
            tenant, provider, env, body, sig, endpoint_id="whe_malformed",
        )

    # Rejected safely: nothing was persisted from a body that never parsed into
    # an observation (no session, no provider event, no receipt fabricated).
    assert await svc.repos.sessions.list_for_tenant(tenant) == []
    assert await svc.repos.events.list_for_tenant(tenant) == []
    assert await svc.repos.receipts.list_for_tenant(tenant) == []


async def test_valid_signature_but_non_object_json_rejected(monkeypatch):
    reset_in_memory_stores()
    _patch(monkeypatch)
    svc = _svc()
    tenant, env, provider = _tenant(), "sandbox", "coinbase"
    secret = "whsec_nonobj"
    await _configure_webhook_secret(tenant, provider, env, secret)

    body = b"[1, 2, 3]"  # valid JSON, but a list — not a webhook object
    sig = _body_hex_sig(secret, body)

    with pytest.raises(BadRequestError):
        await svc.handle_verified_webhook(
            tenant, provider, env, body, sig, endpoint_id="whe_nonobj",
        )
    assert await svc.repos.sessions.list_for_tenant(tenant) == []
    assert await svc.repos.receipts.list_for_tenant(tenant) == []


async def test_malformed_compound_signature_uniform_reject_and_audit(monkeypatch):
    """A COMPOUND-header provider (Stripe) receiving a signature that is not a
    parseable ``t=..,v1=..`` value is rejected with a uniform, secret-free reason
    and a server-side audit — never a crash, never a leak of whether the secret
    or endpoint existed."""
    reset_in_memory_stores()
    _patch(monkeypatch)
    svc = _svc()
    tenant, env, provider = _tenant(), "sandbox", "stripe"
    await _configure_webhook_secret(tenant, provider, env, "whsec_stripe")

    body = json.dumps({"id": "evt_1", "type": "crypto.onramp_session_updated",
                       "data": {"object": {"id": "cos_1", "status": "fulfillment_complete"}}}).encode()

    result = await svc.handle_verified_webhook(
        tenant, provider, env, body, "garbage-not-a-compound-header",
        endpoint_id="whe_badfmt",
    )
    assert result["handled"] is False
    # A parseable-but-empty compound header classifies as ``bad_format``.
    assert result["reason"] == "bad_format"

    # Nothing persisted, and the rejection is audited server-side (metadata only).
    assert await svc.repos.sessions.list_for_tenant(tenant) == []
    audits = await svc.repos.audit.list_for_tenant(tenant, action="webhook_rejected")
    assert len(audits) == 1
    assert audits[0]["detail"]["reason"] == "bad_format"
    # the audit carries no secret / raw body
    assert "whsec_stripe" not in json.dumps(audits[0])
