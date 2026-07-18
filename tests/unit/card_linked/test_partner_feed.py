"""Signed, versioned card-linked partner-feed contract + evidence/summing guards.

Covers deliverables 1 and 2:
  * HMAC-SHA256 verification (constant-time) via the per-tenant BYOK partner
    secret; unsigned/invalid rejected fail-closed outside local mode;
  * versioned schema + STRICT allowlist + blocked-field REJECTION;
  * spend-side-only basis (never top-up/funding), atomic-string money;
  * deterministic idempotency key;
  * evidence-strength labeling (SDK never provider-confirmed);
  * the hard top-up/spend non-conflation (never-summed) guard.
"""

from __future__ import annotations

import json

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

pytestmark = pytest.mark.asyncio


# ── contract validation (allowlist / blocked / schema / basis / money) ────────

def _event(**overrides) -> dict:
    base = {
        "provider": "acme",
        "provider_event_id": "evt-1",
        "basis": "spend",
        "card_program_id": "redotpay",
        "issuer_id": "rain",
        "payment_network": "visa",
        "amount_usd": "42.50",
        "wallet_address_hash": "0xwallet",
        "event_time": "2026-07-10T10:00:00Z",
    }
    base.update(overrides)
    return base


def test_contract_accepts_valid_event_and_is_deterministic():
    from services.card_linked_payments.partner_feed import (
        CARD_LINKED_PARTNER_FEED_SCHEMA_VERSION,
        validate_partner_feed_event,
    )

    clean = validate_partner_feed_event(_event(), tenant_id="t1", partner="acme")
    assert clean["schema_version"] == CARD_LINKED_PARTNER_FEED_SCHEMA_VERSION
    assert clean["occurred_at"].endswith("+00:00")  # normalized to UTC
    assert clean["amount_usd"] == "42.50"
    key1 = clean["idempotency_key"]
    key2 = validate_partner_feed_event(_event(), tenant_id="t1", partner="acme")["idempotency_key"]
    assert key1 == key2 and "partner_feed" in key1


def test_contract_rejects_blocked_instrument_fields():
    from services.card_linked_payments.partner_feed import (
        PartnerFeedSchemaError,
        validate_partner_feed_event,
    )

    for blocked in ("pan", "full_card_number", "cvv", "routing_number",
                    "full_bank_account", "raw_kyc_document"):
        with pytest.raises(ValueError, match="Blocked"):
            validate_partner_feed_event(_event(**{blocked: "x"}), tenant_id="t1")


def test_contract_strict_allowlist_rejects_unexpected_field():
    from services.card_linked_payments.partner_feed import validate_partner_feed_event

    with pytest.raises(ValueError, match="allowlist"):
        validate_partner_feed_event(_event(surprise_column="boom"), tenant_id="t1")


def test_contract_rejects_unsupported_schema_version():
    from services.card_linked_payments.partner_feed import validate_partner_feed_event

    with pytest.raises(ValueError, match="schema_version"):
        validate_partner_feed_event(_event(schema_version="card_linked.partner_feed.v999"),
                                    tenant_id="t1")


def test_contract_rejects_topup_basis_spend_side_only():
    from services.card_linked_payments.partner_feed import validate_partner_feed_event

    for topup_basis in ("topup", "funding"):
        with pytest.raises(ValueError, match="spend-side"):
            validate_partner_feed_event(_event(basis=topup_basis), tenant_id="t1")
    # authorization/settlement/refund/reversal are accepted spend-side bases
    for ok_basis in ("authorization", "settlement", "refund", "reversal"):
        validate_partner_feed_event(_event(basis=ok_basis), tenant_id="t1")


def test_contract_rejects_float_money_but_accepts_atomic_string():
    from services.card_linked_payments.partner_feed import (
        PartnerFeedSchemaError,
        validate_partner_feed_event,
    )

    with pytest.raises(PartnerFeedSchemaError, match="float"):
        validate_partner_feed_event(_event(amount_usd=42.50), tenant_id="t1")
    clean = validate_partner_feed_event(_event(amount_usd="100"), tenant_id="t1")
    assert clean["amount_usd"] == "100" and isinstance(clean["amount_usd"], str)


# ── HMAC verification (constant-time) via BYOK vault ──────────────────────────

async def _verifier_with_secret(tenant: str, secret: str, partner: str | None = "acme"):
    from shared.providers.key_vault import BYOKKeyVault
    from services.card_linked_payments.partner_feed import (
        CardLinkedPartnerFeedVerifier,
        PARTNER_FEED_VAULT_PROVIDER,
    )

    vault = BYOKKeyVault()
    provider_name = f"{PARTNER_FEED_VAULT_PROVIDER}:{partner}" if partner else PARTNER_FEED_VAULT_PROVIDER
    await vault.store_key(tenant, provider_name, "webhook_secret", secret)
    return CardLinkedPartnerFeedVerifier(vault=vault)


async def test_hmac_verify_valid_and_invalid_and_tampered():
    tenant, secret, partner = "t-hmac", "sh_super_secret", "acme"
    verifier = await _verifier_with_secret(tenant, secret, partner)
    raw = json.dumps(_event()).encode("utf-8")
    good = verifier.sign(secret, raw)

    assert await verifier.verify(tenant, raw, good, partner=partner) is True
    # wrong signature
    assert await verifier.verify(tenant, raw, "deadbeef", partner=partner) is False
    # tampered body → signature no longer matches
    assert await verifier.verify(tenant, raw + b" ", good, partner=partner) is False
    # missing signature / missing secret both fail closed
    assert await verifier.verify(tenant, raw, None, partner=partner) is False
    assert await verifier.verify(tenant, raw, good, partner="other-partner") is False


async def test_fail_closed_gate_outside_local(monkeypatch):
    from services.card_linked_payments import partner_feed as pf

    tenant, secret, partner = "t-gate", "sh_secret", "acme"
    verifier = await _verifier_with_secret(tenant, secret, partner)
    raw = json.dumps(_event()).encode("utf-8")
    good = verifier.sign(secret, raw)

    # Force non-local: unsigned is rejected, valid signature passes.
    monkeypatch.setattr(pf, "_is_local_env", lambda: False)
    with pytest.raises(pf.PartnerFeedSignatureError):
        await pf.verify_partner_feed_signature(tenant, raw, None, partner=partner, verifier=verifier)
    await pf.verify_partner_feed_signature(tenant, raw, good, partner=partner, verifier=verifier)

    # Local mode: an absent signature is tolerated (fail-open locally).
    monkeypatch.setattr(pf, "_is_local_env", lambda: True)
    await pf.verify_partner_feed_signature(tenant, raw, None, partner=partner, verifier=verifier)


# ── evidence-strength labeling + overclaim guard ──────────────────────────────

def test_evidence_strength_classification_and_overclaim_guard():
    from services.card_linked_payments.models import (
        EvidenceOverclaimError,
        assert_evidence_not_overclaimed,
        classify_evidence_strength,
    )

    assert classify_evidence_strength("provider_webhook") == "provider_confirmed"
    assert classify_evidence_strength("onchain_observer") == "onchain_observed"
    assert classify_evidence_strength("sdk") == "sdk_reported"
    assert classify_evidence_strength("tenant_import") == "self_reported"
    assert classify_evidence_strength("paymentscan", basis="benchmark_only") == "benchmark"
    # A non-provider source may NEVER be labeled provider_confirmed.
    with pytest.raises(EvidenceOverclaimError):
        assert_evidence_not_overclaimed("sdk", "provider_confirmed")
    assert_evidence_not_overclaimed("provider_webhook", "provider_confirmed")  # ok


async def test_sdk_flow_labeled_sdk_reported_never_provider_confirmed(tenant, ingestion):
    result = await ingestion.ingest_sdk_event(tenant, {
        "type": "payment_completed", "event_id": "sdk_ev", "user_id": "u1",
        "properties": {"card_program": "RedotPay", "basis": "spend", "amount_usd": "10"},
    }, consent_snapshot={"commerce": True})
    record, _ = result
    assert record["evidence_strength"] == "sdk_reported"
    assert record["evidence_strength"] != "provider_confirmed"
    # SDK spend claims are still downgraded to unknown basis (no off-chain proof).
    assert record["basis"] == "unknown"


async def test_provider_flow_labeled_provider_confirmed(tenant, ingestion):
    record, _ = await ingestion.ingest_provider_webhook(tenant, {
        "id": "pw_ev", "provider": "rain", "provider_event_id": "evt_ev",
        "basis": "spend", "card_program_id": "redotpay", "amount_usd": "5.00",
    })
    assert record["evidence_strength"] == "provider_confirmed"


# ── top-up / spend non-conflation (never-summed) guard ────────────────────────

def test_summing_guard_rejects_combined_total():
    from services.card_linked_payments.models import (
        TopupSpendConflationError,
        assert_topup_spend_separated,
    )

    # A clean, separated rollup passes and is returned unchanged.
    clean = {"topup_volume_usd": "100.00", "spend_volume_usd": "50.00"}
    assert assert_topup_spend_separated(clean) is clean
    # Any single combined scalar is rejected.
    for forbidden in ("total_volume_usd", "combined_volume_usd", "net_volume_usd",
                      "gross_volume_usd", "volume_usd"):
        with pytest.raises(TopupSpendConflationError):
            assert_topup_spend_separated({forbidden: "150.00"})


async def test_rollups_keep_topup_and_spend_separate(tenant, ingestion):
    from services.card_linked_payments.gold import (
        campaign_card_linked_outcomes,
        entity_economic_activity,
    )
    from services.card_linked_payments.models import COMBINED_TOTAL_FORBIDDEN_KEYS

    await ingestion.ingest_onchain_observation(tenant, {
        "id": "oc_x", "chain": "base", "tx_hash": "0xx", "asset": "USDC",
        "wallet_address_hash": "wh_x", "card_program_id": "redotpay",
        "amount_usd": "100.00", "campaign_id": "camp_x",
    })
    await ingestion.ingest_provider_webhook(tenant, {
        "id": "pw_x", "provider": "rain", "provider_event_id": "evt_x",
        "basis": "spend", "card_program_id": "redotpay", "amount_usd": "25.00",
        "wallet_address_hash": "wh_x", "campaign_id": "camp_x",
    })
    rollup = await entity_economic_activity(tenant, "wh_x")
    outcomes = await campaign_card_linked_outcomes(tenant, "camp_x")
    for surface in (rollup, outcomes):
        assert not (set(surface) & COMBINED_TOTAL_FORBIDDEN_KEYS)
    # top-up and spend are distinct numbers, never one total
    assert rollup["topup_volume_usd"] == "100.00"
    assert rollup["spend_volume_usd"] == "25.00"
    assert "evidence_breakdown" in rollup and "evidence_breakdown" in outcomes


# ── route wiring: signed feed rejected fail-closed, accepted when valid ────────

class _FakeTenant:
    def __init__(self, tenant_id: str):
        self.tenant_id = tenant_id
        self.is_platform_admin = False

    def require_permission(self, perm: str) -> None:
        return None


def _client(tenant_id: str) -> TestClient:
    from services.card_linked_payments.routes import router

    app = FastAPI()
    app.include_router(router)

    @app.middleware("http")
    async def _inject(request: Request, call_next):
        request.state.tenant = _FakeTenant(tenant_id)
        return await call_next(request)

    return TestClient(app)


def _enable_flags(monkeypatch):
    from config.settings import CardLinkedPaymentRailsConfig, settings

    monkeypatch.setattr(settings, "card_linked_payment_rails",
                        CardLinkedPaymentRailsConfig(enabled=True))


async def _install_verifier(monkeypatch, tenant, secret, partner):
    from services.card_linked_payments import partner_feed as pf

    verifier = await _verifier_with_secret(tenant, secret, partner)
    monkeypatch.setattr(pf, "_default_verifier", verifier)
    return verifier


async def test_route_rejects_unsigned_outside_local(monkeypatch, tenant):
    from services.card_linked_payments import ingestion as ing_mod
    from services.card_linked_payments import partner_feed as pf

    _enable_flags(monkeypatch)
    monkeypatch.setattr(ing_mod, "_service", None, raising=False)
    await _install_verifier(monkeypatch, tenant, "sh_route_secret", "acme")
    monkeypatch.setattr(pf, "_is_local_env", lambda: False)

    client = _client(tenant)
    url = "/v1/integrations/providers/payment-rails/card-linked/ingest/provider-webhook"
    raw = json.dumps(_event()).encode("utf-8")
    resp = client.post(url, content=raw, headers={"X-Aether-Partner": "acme"})
    assert resp.status_code == 401


async def test_route_accepts_valid_signature(monkeypatch, tenant):
    from services.card_linked_payments import ingestion as ing_mod
    from services.card_linked_payments import partner_feed as pf

    _enable_flags(monkeypatch)
    monkeypatch.setattr(ing_mod, "_service", None, raising=False)
    verifier = await _install_verifier(monkeypatch, tenant, "sh_route_secret", "acme")
    monkeypatch.setattr(pf, "_is_local_env", lambda: False)

    client = _client(tenant)
    url = "/v1/integrations/providers/payment-rails/card-linked/ingest/provider-webhook"
    raw = json.dumps(_event()).encode("utf-8")
    sig = verifier.sign("sh_route_secret", raw)
    resp = client.post(url, content=raw,
                       headers={"X-Aether-Partner": "acme", "X-Aether-Partner-Signature": sig})
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["disposition"] == "created"
    assert data["schema_version"] == pf.CARD_LINKED_PARTNER_FEED_SCHEMA_VERSION

    # A bad signature is rejected fail-closed.
    bad = client.post(url, content=raw,
                      headers={"X-Aether-Partner": "acme", "X-Aether-Partner-Signature": "nope"})
    assert bad.status_code == 401


async def test_route_local_mode_allows_unsigned(monkeypatch, tenant):
    """Local mode preserves the prior behavior: unsigned partner events pass."""
    from services.card_linked_payments import ingestion as ing_mod
    from services.card_linked_payments import partner_feed as pf

    _enable_flags(monkeypatch)
    monkeypatch.setattr(ing_mod, "_service", None, raising=False)
    monkeypatch.setattr(pf, "_is_local_env", lambda: True)

    client = _client(tenant)
    url = "/v1/integrations/providers/payment-rails/card-linked/ingest/provider-webhook"
    raw = json.dumps(_event()).encode("utf-8")
    resp = client.post(url, content=raw, headers={"X-Aether-Partner": "acme"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["disposition"] == "created"
