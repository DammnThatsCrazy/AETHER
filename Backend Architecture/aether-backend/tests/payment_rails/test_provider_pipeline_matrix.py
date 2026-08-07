"""B2 — per-provider end-to-end pipeline breadth (all FIVE providers).

WHAT THIS COVERS / WHY IT WAS NEEDED
------------------------------------
The existing suite proves the full webhook pipeline end to end for exactly one
provider (MoonPay, in ``test_service_and_routes.py``). The other four providers
are only covered *piecewise*: ``test_native_webhook_flow.py`` proves signature
verification through the endpoint seam, and ``test_adapters.py`` proves
parse/normalize/canonical in isolation — but no test drives Privy, Stripe,
Coinbase or Bridge through the WHOLE service pipeline
(webhook → native signature verify → parse → normalize → persist FundingSession
→ canonical ``payment_*`` emission → durable receipt) with a real signed body.

This module is that parametrized matrix. For every one of the five named
providers it signs a provider-shaped ``completed`` webhook with the provider's
NATIVE signature scheme, feeds it through ``PaymentRailsService.handle_webhook``,
and asserts the delivery-integrity invariants:

  * the webhook is admitted (``handled``) and creates exactly ONE FundingSession
    attributed to the right provider;
  * the session implies exactly ``payment_initiated`` + ``payment_completed``,
    each carrying the DETERMINISTIC canonical id
    ``canonical_event_id(tenant, session_id, event_type)`` — i.e. exactly one
    canonical id per (observation, event_type), never a random duplicate;
  * canonical payloads are correctly attributed to the provider and tenant; and
  * the durable receipt for the delivery reaches ``COMPLETED``, linked to the
    funding session and to both canonical event ids.

DELIVERY-INTEGRITY GUARANTEE PROTECTED
--------------------------------------
One receipt / one session / one canonical event per observation, with correct
provider attribution — proven uniformly across all five adapters, not just the
one that happened to have an end-to-end test.
"""

from __future__ import annotations

import dataclasses
import hashlib
import hmac
import json
import os
import time
import uuid

import pytest

os.environ.setdefault("AETHER_ENV", "local")

from config.settings import settings  # noqa: E402
from repositories.repos import reset_in_memory_stores  # noqa: E402
from services.integrations.providers.payment_rails import get_adapter  # noqa: E402
from services.integrations.providers.payment_rails.base import (  # noqa: E402
    get_payment_rails_vault,
)
from services.integrations.providers.payment_rails.receipts import ReceiptStage  # noqa: E402
from services.integrations.providers.payment_rails.repository import (  # noqa: E402
    PaymentRailsRepositories,
)
from services.integrations.providers.payment_rails.service import (  # noqa: E402
    PaymentRailsService,
    canonical_event_id,
)

pytestmark = pytest.mark.asyncio(loop_scope="function")

ALL_PROVIDERS = ["privy", "stripe", "coinbase", "moonpay", "bridge"]


class _RecordingProducer:
    def __init__(self) -> None:
        self.events = []

    async def publish(self, event) -> None:
        self.events.append(event)

    async def publish_batch(self, events) -> None:
        self.events.extend(events)


def _tenant() -> str:
    return f"t-{uuid.uuid4().hex[:8]}"


@pytest.fixture(autouse=True)
def _enable_rails(monkeypatch):
    monkeypatch.setattr(
        settings, "payment_rails",
        dataclasses.replace(
            settings.payment_rails,
            enabled=True, privy_enabled=True, stripe_enabled=True,
            coinbase_enabled=True, moonpay_enabled=True, bridge_enabled=True,
        ),
    )


@pytest.fixture()
def service():
    return PaymentRailsService(
        repositories=PaymentRailsRepositories(), producer=_RecordingProducer()
    )


# ── provider-shaped ``completed`` webhook bodies ──────────────────────────────
# Each normalizes to a FundingSession with canonical status ``completed`` so the
# implied canonical set is exactly [payment_initiated, payment_completed].

def _body(provider: str) -> bytes:
    if provider == "privy":
        payload = {
            "type": "funding.completed",
            "data": {
                "funding_id": "f1", "status": "completed", "amount": "100",
                "source_currency": "usd", "asset": "usdc", "chain": "base",
                "wallet_address": "0xabc", "user_id": "u1",
            },
        }
    elif provider == "stripe":
        payload = {
            "id": "evt_1",
            "type": "crypto.onramp_session_updated",
            "data": {"object": {
                "id": "cos_1", "status": "fulfillment_complete",
                "transaction_details": {
                    "source_currency": "usd", "source_amount": "51",
                    "destination_currency": "usdc", "destination_amount": "50",
                    "destination_network": "ethereum", "wallet_address": "0xabc",
                },
                "metadata": {"user_id": "u1", "session_id": "sess_1"},
            }},
        }
    elif provider == "coinbase":
        payload = {
            "event_type": "onramp.transaction.updated",
            "transaction": {
                "transaction_id": "cb1", "partner_user_ref": "user-1",
                "status": "ONRAMP_TRANSACTION_STATUS_SUCCESS",
                "purchase_amount": {"value": "50", "currency": "USDC"},
                "payment_total": {"value": "51", "currency": "USD"},
                "purchase_currency": "USDC", "purchase_network": "base",
                "wallet_address": "0xabc", "tx_hash": "0xdead",
            },
        }
    elif provider == "moonpay":
        payload = {
            "type": "transaction_updated",
            "data": {
                "id": "mp1", "status": "completed", "externalCustomerId": "u1",
                "baseCurrencyAmount": 100, "quoteCurrencyAmount": 95,
                "baseCurrency": {"code": "usd"}, "currency": {"code": "usdc"},
                "walletAddress": "0xabc", "cryptoTransactionId": "0xhash",
            },
        }
    elif provider == "bridge":
        payload = {
            "event_type": "virtual_account.activity",
            "event_object": {
                "id": "act1", "type": "payment_processed", "status": "payment_processed",
                "amount": "250.00", "currency": "usd", "customer_id": "cust1",
                "virtual_account_id": "va1", "deposit_id": "dep1",
                "source": {"payment_rail": "ach", "currency": "usd"},
                "destination": {"currency": "usdc", "payment_rail": "base",
                                "address": "0xdest", "transaction_hash": "0xtx"},
            },
        }
    else:  # pragma: no cover - guard
        raise AssertionError(f"unknown provider {provider}")
    return json.dumps(payload).encode()


async def _signed_handle(service, tenant_id: str, provider: str, body: bytes):
    """Store the tenant's signing secret and POST the webhook signed with the
    provider's NATIVE scheme (the legacy ``handle_webhook`` path resolves the
    secret from the vault and verifies with ``native_signature_scheme``)."""
    adapter = get_adapter(provider)
    secret = "whsec_" + tenant_id
    await get_payment_rails_vault().store_key(
        tenant_id, adapter.vault_provider_name, "payment", secret
    )
    scheme = adapter.native_signature_scheme()
    ts = str(int(time.time()))
    if scheme == "stripe_compound":
        mac = hmac.new(secret.encode(), f"{ts}.".encode() + body, hashlib.sha256).hexdigest()
        header, timestamp = f"t={ts},v1={mac}", ts
    elif scheme == "moonpay_compound":
        mac = hmac.new(secret.encode(), f"{ts}.".encode() + body, hashlib.sha256).hexdigest()
        header, timestamp = f"t={ts},s={mac}", ts
    elif scheme == "body_hex":
        mac = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        header, timestamp = mac, None
    else:  # timestamped_hex (Privy / Bridge)
        mac = hmac.new(secret.encode(), f"{ts}.".encode() + body, hashlib.sha256).hexdigest()
        header, timestamp = f"v1={mac}", ts
    return await service.handle_webhook(tenant_id, provider, body, header, timestamp)


@pytest.mark.parametrize("provider", ALL_PROVIDERS)
async def test_provider_webhook_pipeline_end_to_end(service, provider):
    reset_in_memory_stores()
    tenant_id = _tenant()

    result = await _signed_handle(service, tenant_id, provider, _body(provider))

    # 1. Admitted + created exactly one session, attributed to this provider.
    assert result["handled"] is True, f"{provider}: signature/verify failed"
    event_result = result["events"][0]
    assert event_result["disposition"] == "created"
    assert event_result["status"] == "completed"

    sessions = await service.repos.sessions.list_for_tenant(tenant_id)
    assert len(sessions) == 1
    session = sessions[0]
    assert session["provider"] == provider  # correct provider attribution

    # 2. Exactly the two implied canonical events, each with the DETERMINISTIC id
    #    (one canonical id per observation + event_type — no random duplicates).
    emitted = service.producer.events
    assert [e.payload["event_type"] for e in emitted] == [
        "payment_initiated", "payment_completed",
    ]
    for e in emitted:
        assert e.tenant_id == tenant_id
        assert e.payload["event_id"] == canonical_event_id(
            tenant_id, e.payload["session_id"], e.payload["event_type"]
        )
        # canonical payload attributes the observation to the right provider
        assert e.payload["properties"]["provider"] == provider
    # deterministic ids are distinct per event type (no collision, no dupe)
    assert len({e.payload["event_id"] for e in emitted}) == 2

    # 3. The durable receipt for the delivery reached COMPLETED, linked to the
    #    session and to both canonical ids (one receipt per observation).
    rid = event_result["receipt_id"]
    receipt = await service.repos.receipts.get(tenant_id, rid)
    assert receipt["current_stage"] == ReceiptStage.COMPLETED
    assert receipt["funding_session_id"] == session["id"]
    assert len(receipt["canonical_event_ids"]) == 2
    assert receipt["completed_at"] is not None


@pytest.mark.parametrize("provider", ALL_PROVIDERS)
async def test_provider_webhook_replay_is_idempotent(service, provider):
    """A verbatim provider redelivery of the same signed webhook must dedupe to
    the SAME receipt/session and emit no second canonical event — the exact-once
    guarantee, proven for every provider."""
    reset_in_memory_stores()
    tenant_id = _tenant()
    body = _body(provider)

    first = await _signed_handle(service, tenant_id, provider, body)
    first_receipt = first["events"][0]["receipt_id"]
    first_canonical_count = len(service.producer.events)

    second = await _signed_handle(service, tenant_id, provider, body)
    assert second["handled"] is True
    assert second["events"][0]["disposition"] == "ignored_duplicate"
    # same deterministic receipt, no re-emission, still exactly one session
    assert second["events"][0]["receipt_id"] == first_receipt
    assert len(service.producer.events) == first_canonical_count
    assert len(await service.repos.sessions.list_for_tenant(tenant_id)) == 1
