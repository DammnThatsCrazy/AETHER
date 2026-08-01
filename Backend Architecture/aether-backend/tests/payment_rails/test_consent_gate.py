"""Consent gate on the payment-rails observation path (default OFF).

When ``payment_rails.webhook_consent_gate_enabled`` is set, a normalized funding
session is persisted/emitted only if its subject (``user_id``) has granted the
``commerce`` consent purpose. These tests drive the gate through the shared
``_process_event`` seam (exercised by both the legacy and the endpoint-registry
webhook paths) and assert on the real observable effect — whether the funding
session was persisted — plus the metadata-only audit trail.

Proven here:
  * default OFF is non-breaking — an observation with no consent on file is still
    persisted when the gate is disabled;
  * enabled + subject granted ``commerce`` → persisted;
  * enabled + subject missing ``commerce`` (or no record at all) → dropped
    (never persisted), disposition ``consent_denied``, audited metadata-only;
  * enabled + no resolvable subject → allowed (nothing to gate), audited;
  * enabled + consent store error → fails closed (dropped).
"""

from __future__ import annotations

import dataclasses
import os

import pytest

os.environ.setdefault("AETHER_ENV", "local")

from config.settings import settings  # noqa: E402
from repositories.repos import ConsentRepository, reset_in_memory_stores  # noqa: E402
from services.integrations.providers.payment_rails import ADAPTERS  # noqa: E402
from services.integrations.providers.payment_rails.base import payload_hash  # noqa: E402
from services.integrations.providers.payment_rails.service import (  # noqa: E402
    PaymentRailsService,
)

pytestmark = pytest.mark.asyncio


def _patch_gate(monkeypatch, enabled: bool) -> None:
    monkeypatch.setattr(
        settings,
        "payment_rails",
        dataclasses.replace(settings.payment_rails, webhook_consent_gate_enabled=enabled),
    )


def _coinbase_event(adapter, tenant, *, user_ref, tx_id="cb-tx-1",
                    status="ONRAMP_TRANSACTION_STATUS_SUCCESS"):
    """A parsed Coinbase onramp event that normalizes to a funding session.

    ``user_ref`` becomes the session ``user_id`` (the consent subject); pass None
    to model an observation with no resolvable subject.
    """
    tx = {"transaction_id": tx_id, "status": status,
          "purchase_amount": "100", "payment_total": "101",
          "purchase_currency": "USDC", "purchase_network": "base"}
    if user_ref is not None:
        tx["partner_user_ref"] = user_ref
    payload = {"event_type": "onramp.transaction.updated",
               "event_id": f"{tx_id}:{status}", "transaction": tx}
    events = adapter.parse_webhook(tenant, payload, payload_hash(payload))
    assert events, "expected the coinbase payload to parse to one event"
    return events[0]


async def _grant(tenant: str, user_id: str, purposes) -> None:
    await ConsentRepository().insert(
        f"consent-{tenant}-{user_id}",
        {"tenant_id": tenant, "user_id": user_id, "granted_purposes": list(purposes)},
    )


async def _sessions(svc, tenant):
    return await svc.repos.sessions.list_for_tenant(tenant)


async def _audit_actions(svc, tenant):
    audits = await svc.repos.audit.list_for_tenant(tenant, limit=1000)
    return [a.get("action") for a in audits]


# ── default OFF is non-breaking ───────────────────────────────────────────────

async def test_gate_off_persists_even_without_consent(monkeypatch):
    reset_in_memory_stores()
    _patch_gate(monkeypatch, False)  # default
    svc = PaymentRailsService()
    adapter = ADAPTERS["coinbase"]
    event = _coinbase_event(adapter, "tenantOff", user_ref="user-nogrant")

    result = await svc._process_event("tenantOff", adapter, event)

    assert result["disposition"] != "consent_denied"
    assert len(await _sessions(svc, "tenantOff")) == 1  # observed despite no consent


# ── enabled: allow / deny by grant ────────────────────────────────────────────

async def test_gate_on_allows_with_commerce_consent(monkeypatch):
    reset_in_memory_stores()
    _patch_gate(monkeypatch, True)
    svc = PaymentRailsService()
    adapter = ADAPTERS["coinbase"]
    await _grant("tenantA", "user-alice", ["analytics", "commerce"])
    event = _coinbase_event(adapter, "tenantA", user_ref="user-alice")

    result = await svc._process_event("tenantA", adapter, event)

    assert result["disposition"] != "consent_denied"
    assert result.get("funding_session_id")
    assert len(await _sessions(svc, "tenantA")) == 1


async def test_gate_on_denies_when_no_consent_record(monkeypatch):
    reset_in_memory_stores()
    _patch_gate(monkeypatch, True)
    svc = PaymentRailsService()
    adapter = ADAPTERS["coinbase"]
    event = _coinbase_event(adapter, "tenantB", user_ref="user-bob")  # no grant seeded

    result = await svc._process_event("tenantB", adapter, event)

    assert result["disposition"] == "consent_denied"
    assert await _sessions(svc, "tenantB") == []  # observation dropped, never persisted
    assert "consent_denied" in await _audit_actions(svc, "tenantB")


async def test_gate_on_denies_when_commerce_purpose_missing(monkeypatch):
    reset_in_memory_stores()
    _patch_gate(monkeypatch, True)
    svc = PaymentRailsService()
    adapter = ADAPTERS["coinbase"]
    await _grant("tenantC", "user-carol", ["analytics", "marketing"])  # commerce absent
    event = _coinbase_event(adapter, "tenantC", user_ref="user-carol")

    result = await svc._process_event("tenantC", adapter, event)

    assert result["disposition"] == "consent_denied"
    assert await _sessions(svc, "tenantC") == []


# ── enabled: no resolvable subject is allowed (nothing to gate) ────────────────

async def test_gate_on_allows_when_no_subject(monkeypatch):
    reset_in_memory_stores()
    _patch_gate(monkeypatch, True)
    svc = PaymentRailsService()
    adapter = ADAPTERS["coinbase"]
    event = _coinbase_event(adapter, "tenantD", user_ref=None)  # no partner_user_ref

    result = await svc._process_event("tenantD", adapter, event)

    assert result["disposition"] != "consent_denied"
    assert len(await _sessions(svc, "tenantD")) == 1
    assert "consent_gate_no_subject" in await _audit_actions(svc, "tenantD")


# ── enabled: consent store error fails closed ─────────────────────────────────

async def test_gate_on_fails_closed_on_store_error(monkeypatch):
    reset_in_memory_stores()
    _patch_gate(monkeypatch, True)
    svc = PaymentRailsService()
    adapter = ADAPTERS["coinbase"]

    async def _boom(self, tenant_id, user_id):
        raise RuntimeError("consent store unavailable")

    monkeypatch.setattr(ConsentRepository, "get_consent", _boom)
    event = _coinbase_event(adapter, "tenantE", user_ref="user-eve")

    result = await svc._process_event("tenantE", adapter, event)

    assert result["disposition"] == "consent_denied"  # undeterminable grant → deny
    assert await _sessions(svc, "tenantE") == []
