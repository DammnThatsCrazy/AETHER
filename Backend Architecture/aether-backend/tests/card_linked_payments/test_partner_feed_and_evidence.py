"""Signed partner-feed contract, evidence-strength labeling, summing guard,
and import-engine integration — backend suite.

Complements ``test_card_linked_correctness.py`` with the turnkey deliverables:
  1. versioned SIGNED partner-feed contract (HMAC via BYOK, strict allowlist,
     blocked-field rejection, spend-side basis, atomic-string money);
  2. evidence-strength labeling + never-provider-confirmed guard, and the hard
     top-up/spend never-summed guard;
  3. card-linked import routed through the canonical import engine.
"""

from __future__ import annotations

import json
import os
import uuid

import pytest

os.environ.setdefault("AETHER_ENV", "local")

from config.settings import settings  # noqa: E402
from services.card_linked_payments.ingestion import CardLinkedIngestionService  # noqa: E402
from services.card_linked_payments.repositories import (  # noqa: E402
    get_card_linked_repositories,
    reset_card_linked_repositories,
)

pytestmark = pytest.mark.asyncio


def _svc() -> CardLinkedIngestionService:
    reset_card_linked_repositories()
    return CardLinkedIngestionService(settings)


def _tenant() -> str:
    return "t_" + uuid.uuid4().hex[:12]


def _event(**overrides) -> dict:
    base = {
        "provider": "acme", "provider_event_id": "pe-1", "basis": "spend",
        "card_program_id": "redotpay", "amount_usd": "42.50",
        "wallet_address_hash": "0xwallet", "event_time": "2026-07-10T10:00:00Z",
    }
    base.update(overrides)
    return base


# ── deliverable 1: signed, versioned contract ─────────────────────────────────

def test_partner_feed_contract_allowlist_and_blocked_and_basis_and_money():
    from services.card_linked_payments.partner_feed import (
        PartnerFeedSchemaError,
        validate_partner_feed_event,
    )

    clean = validate_partner_feed_event(_event(), tenant_id="t1", partner="acme")
    assert clean["schema_version"] == "card_linked.partner_feed.v1"
    assert clean["amount_usd"] == "42.50" and isinstance(clean["amount_usd"], str)
    assert clean["id"] and clean["idempotency_key"]

    # blocked instrument field
    with pytest.raises(ValueError, match="Blocked"):
        validate_partner_feed_event(_event(pan="4111111111111111"), tenant_id="t1")
    # unexpected field (strict allowlist)
    with pytest.raises(PartnerFeedSchemaError, match="allowlist"):
        validate_partner_feed_event(_event(mystery="x"), tenant_id="t1")
    # top-up/funding never accepted on the partner feed
    with pytest.raises(PartnerFeedSchemaError, match="spend-side"):
        validate_partner_feed_event(_event(basis="topup"), tenant_id="t1")
    # float money rejected
    with pytest.raises(PartnerFeedSchemaError, match="float"):
        validate_partner_feed_event(_event(amount_usd=42.5), tenant_id="t1")


async def test_partner_feed_hmac_and_fail_closed_gate(monkeypatch):
    from shared.providers.key_vault import BYOKKeyVault
    from services.card_linked_payments import partner_feed as pf

    tenant, secret, partner = _tenant(), "sh_secret", "acme"
    vault = BYOKKeyVault()
    await vault.store_key(tenant, f"{pf.PARTNER_FEED_VAULT_PROVIDER}:{partner}",
                          "webhook_secret", secret)
    verifier = pf.CardLinkedPartnerFeedVerifier(vault=vault)
    raw = json.dumps(_event()).encode("utf-8")
    good = verifier.sign(secret, raw)

    assert await verifier.verify(tenant, raw, good, partner=partner) is True
    assert await verifier.verify(tenant, raw, "bad", partner=partner) is False
    assert await verifier.verify(tenant, raw + b"x", good, partner=partner) is False

    # Fail closed outside local; tolerate absent signature in local.
    monkeypatch.setattr(pf, "_is_local_env", lambda: False)
    with pytest.raises(pf.PartnerFeedSignatureError):
        await pf.verify_partner_feed_signature(tenant, raw, None, partner=partner, verifier=verifier)
    await pf.verify_partner_feed_signature(tenant, raw, good, partner=partner, verifier=verifier)
    monkeypatch.setattr(pf, "_is_local_env", lambda: True)
    await pf.verify_partner_feed_signature(tenant, raw, None, partner=partner, verifier=verifier)


# ── deliverable 2: evidence strength + summing guard ──────────────────────────

async def test_evidence_strength_labels_per_source():
    svc = _svc()
    tenant = _tenant()
    prov, _ = await svc.ingest_provider_webhook(tenant, {
        "id": "pw-ev", "provider": "acme", "provider_event_id": "pe-ev",
        "basis": "spend", "card_program_id": "redotpay", "amount_usd": "5.00",
    })
    assert prov["evidence_strength"] == "provider_confirmed"

    oc, _ = await svc.ingest_onchain_observation(tenant, {
        "id": "oc-ev", "chain": "base", "tx_hash": "0xev", "asset": "USDC",
        "wallet_address_hash": "wh-ev", "card_program_id": "redotpay",
    })
    assert oc["evidence_strength"] == "onchain_observed"

    sdk = await svc.ingest_sdk_event(tenant, {
        "type": "payment_completed", "event_id": "sdk-ev", "user_id": "u1",
        "properties": {"card_program": "redotpay", "basis": "spend", "amount_usd": "3"},
    }, consent_snapshot={"commerce": True})
    sdk_record = sdk[0]
    assert sdk_record["evidence_strength"] == "sdk_reported"
    assert sdk_record["evidence_strength"] != "provider_confirmed"
    assert sdk_record["basis"] == "unknown"  # never promoted to provider spend


def test_summing_guard_hard_rejects_combined_total():
    from services.card_linked_payments.models import (
        TopupSpendConflationError,
        assert_topup_spend_separated,
    )

    assert assert_topup_spend_separated({"topup_volume_usd": "1", "spend_volume_usd": "2"})
    with pytest.raises(TopupSpendConflationError):
        assert_topup_spend_separated({"total_volume_usd": "3"})


async def test_rollups_never_sum_topup_and_spend():
    from services.card_linked_payments.gold import entity_economic_activity
    from services.card_linked_payments.models import COMBINED_TOTAL_FORBIDDEN_KEYS

    svc = _svc()
    tenant = _tenant()
    await svc.ingest_onchain_observation(tenant, {
        "id": "oc-r", "chain": "base", "tx_hash": "0xr", "asset": "USDC",
        "wallet_address_hash": "wh-r", "card_program_id": "redotpay", "amount_usd": "100.00",
    })
    await svc.ingest_provider_webhook(tenant, {
        "id": "pw-r", "provider": "acme", "provider_event_id": "pe-r",
        "basis": "spend", "card_program_id": "redotpay",
        "wallet_address_hash": "wh-r", "amount_usd": "25.00",
    })
    rollup = await entity_economic_activity(tenant, "wh-r")
    assert not (set(rollup) & COMBINED_TOTAL_FORBIDDEN_KEYS)
    assert rollup["topup_volume_usd"] == "100.00"
    assert rollup["spend_volume_usd"] == "25.00"
    assert rollup["evidence_breakdown"]


# ── deliverable 3: import engine integration ──────────────────────────────────

async def test_import_lineage_stamped_and_reconciles():
    svc = _svc()
    tenant = _tenant()
    results = await svc.ingest_tenant_import(tenant, [
        {"id": "imp-1", "basis": "topup", "card_program_id": "redotpay",
         "wallet_address_hash": "wh-imp", "amount_usd": "40.00",
         "occurred_at": "2026-07-10T00:00:00Z"},
    ])
    record = results[0][0]
    assert record["import_lineage"]["engine"] == "services.imports"
    assert record["evidence_strength"] == "self_reported"

    # Later provider evidence corroborates → reconciled (basis never rewritten).
    await svc.ingest_provider_webhook(tenant, {
        "id": "pw-imp", "provider": "acme", "provider_event_id": "pe-imp",
        "basis": "spend", "card_program_id": "redotpay",
        "wallet_address_hash": "wh-imp", "amount_usd": "9.00",
    })
    repos = get_card_linked_repositories()
    matches = await repos.reconciliation.list_for_tenant(tenant)
    assert matches and matches[0]["state"] == "matched"
    flows = await repos.flows.list_for_tenant(tenant, wallet_address_hash="wh-imp")
    assert {f["basis"] for f in flows} == {"topup", "spend"}
