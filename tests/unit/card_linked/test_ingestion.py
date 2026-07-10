"""Card-linked ingestion semantics: basis separation, idempotency, privacy."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio


async def test_paymentscan_benchmark_is_benchmark_only(tenant):
    from services.card_linked_payments.paymentscan import ingest_benchmark

    record = await ingest_benchmark(
        tenant, entity_type="card_program", entity_ref="Redot Pay",
        metric_name="monthly_volume", metric_window="2026-06", value="1000000",
    )
    assert record["catalog_entity_id"] == "card_program:redotpay"
    assert record["basis"] == "benchmark_only"
    assert record["reconciliation_state"] == "benchmark_only"
    assert record["source"] == "paymentscan"
    assert record["confidence"] in ("weak", "probable")


async def test_paymentscan_reported_basis_kept_but_never_user_truth(tenant):
    from services.card_linked_payments.paymentscan import ingest_benchmark

    record = await ingest_benchmark(
        tenant, entity_type="card_program", entity_ref="KAST",
        metric_name="topup_volume", metric_window="2026-06", basis="topup",
    )
    assert record["basis"] == "topup"                       # exact source basis kept
    assert record["reconciliation_state"] == "benchmark_only"  # never user-level truth


async def test_provider_webhook_is_spend_classified(tenant, ingestion):
    record, disposition = await ingestion.ingest_provider_webhook(tenant, {
        "id": "pw_1", "provider": "rain", "provider_event_id": "evt_1",
        "basis": "spend", "card_program_id": "redotpay", "issuer_id": "rain",
        "payment_network": "visa", "amount_usd": "42.50",
    })
    assert disposition == "created"
    assert record["basis"] == "spend"
    assert record["source"] == "provider_webhook"
    assert record["confidence"] == "strong"
    assert record["rail"] == "card"


async def test_provider_webhook_rejects_topup_basis(tenant, ingestion):
    with pytest.raises(ValueError, match="spend, settlement, refund, or reversal"):
        await ingestion.ingest_provider_webhook(tenant, {
            "id": "pw_2", "provider": "rain", "provider_event_id": "evt_2",
            "basis": "topup",
        })


async def test_onchain_is_topup_and_never_spend(tenant, ingestion):
    record, _ = await ingestion.ingest_onchain_observation(tenant, {
        "id": "oc_1", "chain": "base", "tx_hash": "0xabc", "asset": "USDC",
        "wallet_address_hash": "wh_1", "card_program_id": "redotpay",
        "amount_usd": "100.00",
    })
    assert record["basis"] == "topup"
    assert record["source"] == "onchain_observer"

    with pytest.raises(ValueError, match="topup, funding, or settlement"):
        await ingestion.ingest_onchain_observation(tenant, {
            "id": "oc_2", "chain": "base", "tx_hash": "0xdef", "basis": "spend",
        })


async def test_sdk_spend_claim_downgraded_to_unknown(tenant, ingestion):
    """SDK events alone can never prove off-chain card spend."""
    result = await ingestion.ingest_sdk_event(tenant, {
        "type": "payment_completed", "event_id": "sdk_1", "user_id": "u1",
        "properties": {"card_program": "RedotPay", "basis": "spend", "amount_usd": "10"},
    }, consent_snapshot={"commerce": True})
    assert result is not None
    record, _ = result
    assert record["basis"] == "unknown"
    from services.card_linked_payments.repositories import get_card_linked_repositories
    warnings = await get_card_linked_repositories().audit.list_for_tenant(tenant, kind="basis_warning")
    assert warnings, "spend-claim downgrade must be audited"


async def test_sdk_event_without_card_context_ignored(tenant, ingestion):
    assert await ingestion.ingest_sdk_event(tenant, {
        "type": "payment_completed", "event_id": "sdk_2", "properties": {},
    }) is None


async def test_idempotency_dedupes_replays(tenant, ingestion):
    payload = {
        "id": "pw_3", "provider": "rain", "provider_event_id": "evt_3",
        "basis": "spend", "card_program_id": "redotpay",
    }
    _, first = await ingestion.ingest_provider_webhook(tenant, payload)
    _, second = await ingestion.ingest_provider_webhook(tenant, payload)
    assert (first, second) == ("created", "duplicate")


async def test_blocked_pii_rejected_and_audited(tenant, ingestion):
    from services.card_linked_payments.repositories import get_card_linked_repositories

    with pytest.raises(ValueError, match="Blocked"):
        await ingestion.ingest_provider_webhook(tenant, {
            "id": "pw_4", "provider": "rain", "provider_event_id": "evt_4",
            "basis": "spend", "pan": "4111111111111111",
        })
    attempts = await get_card_linked_repositories().audit.list_for_tenant(tenant, kind="blocked_pii")
    assert len(attempts) == 1


async def test_region_policy_strips_user_level_fields(tenant, ingestion):
    from services.card_linked_payments.repositories import get_card_linked_repositories

    result = await ingestion.ingest_sdk_event(tenant, {
        "type": "payment_completed", "event_id": "sdk_eu_1", "user_id": "u-eu",
        "properties": {"card_program": "Gnosis Pay", "basis": "topup"},
    }, region_hint="eu", consent_snapshot={"commerce": True})
    assert result is not None
    record, _ = result
    assert record["region_policy"] == "EU_RESTRICTED"
    assert record["user_id"] is None
    suppressions = await get_card_linked_repositories().audit.list_for_tenant(tenant, kind="region_suppressed")
    assert suppressions


async def test_consent_refusal_suppresses_user_attribution(tenant, ingestion):
    from services.card_linked_payments.repositories import get_card_linked_repositories

    result = await ingestion.ingest_sdk_event(tenant, {
        "type": "payment_completed", "event_id": "sdk_nc_1", "user_id": "u-nc",
        "properties": {"card_program": "KAST", "basis": "topup"},
    }, consent_snapshot={"commerce": False})
    assert result is not None
    record, _ = result
    assert record["user_id"] is None
    assert await get_card_linked_repositories().audit.list_for_tenant(tenant, kind="consent_suppressed")


async def test_agent_influenced_requires_agent_and_commerce_consent(tenant, ingestion):
    result = await ingestion.ingest_sdk_event(tenant, {
        "type": "payment_completed", "event_id": "sdk_ag_1", "user_id": "u-ag",
        "agent_id": "agent-1",
        "properties": {"card_program": "MetaMask Card", "basis": "topup"},
    }, consent_snapshot={"commerce": True, "agent": False})
    record, _ = result
    assert record["user_id"] is None  # suppressed: agent consent missing


async def test_reconciliation_matches_onchain_with_provider(tenant, ingestion):
    from services.card_linked_payments.repositories import get_card_linked_repositories

    await ingestion.ingest_onchain_observation(tenant, {
        "id": "oc_m1", "chain": "base", "tx_hash": "0x111", "asset": "USDC",
        "wallet_address_hash": "wh_match", "card_program_id": "redotpay",
    })
    await ingestion.ingest_provider_webhook(tenant, {
        "id": "pw_m1", "provider": "rain", "provider_event_id": "evt_m1",
        "basis": "spend", "card_program_id": "redotpay",
        "wallet_address_hash": "wh_match",
    })
    repos = get_card_linked_repositories()
    matches = await repos.reconciliation.list_for_tenant(tenant)
    assert matches and matches[0]["state"] == "matched"
    flows = await repos.flows.list_for_tenant(tenant, wallet_address_hash="wh_match")
    assert {f["reconciliation_state"] for f in flows} == {"matched"}
    # matching links records — it never rewrites basis
    assert {f["basis"] for f in flows} == {"topup", "spend"}


async def test_tenant_isolation(tenant, ingestion):
    from services.card_linked_payments.repositories import get_card_linked_repositories

    await ingestion.ingest_provider_webhook(tenant, {
        "id": "pw_iso", "provider": "rain", "provider_event_id": "evt_iso",
        "basis": "spend", "card_program_id": "redotpay",
    })
    other = await get_card_linked_repositories().flows.list_for_tenant(f"{tenant}-other")
    assert other == []


async def test_unknown_issuer_and_network_allowed(tenant, ingestion):
    record, _ = await ingestion.ingest_provider_webhook(tenant, {
        "id": "pw_unk", "provider": "unknown", "provider_event_id": "evt_unk",
        "basis": "spend", "card_program_id": "tuyo",
    })
    assert record["payment_network"] == "unknown"
    assert record["issuer_id"] is None
