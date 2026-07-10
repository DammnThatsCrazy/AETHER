"""Gold rollup correctness and silver projection for card-linked facts."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio


async def _seed(tenant, ingestion):
    await ingestion.ingest_onchain_observation(tenant, {
        "id": "oc_g1", "chain": "base", "tx_hash": "0xg1", "asset": "USDC",
        "wallet_address_hash": "wh_g", "card_program_id": "redotpay",
        "amount_usd": "100.00", "campaign_id": "camp_base_usdc",
    })
    for i in range(2):
        await ingestion.ingest_provider_webhook(tenant, {
            "id": f"pw_g{i}", "provider": "rain", "provider_event_id": f"evt_g{i}",
            "basis": "spend", "card_program_id": "redotpay", "issuer_id": "rain",
            "payment_network": "visa", "amount_usd": "25.00",
            "wallet_address_hash": "wh_g", "campaign_id": "camp_base_usdc",
        })
    from services.card_linked_payments.paymentscan import ingest_benchmark
    await ingest_benchmark(tenant, entity_type="card_program", entity_ref="RedotPay",
                           metric_name="monthly_volume", metric_window="2026-06",
                           value="9999999")


async def test_entity_rollup_separates_topup_from_spend(tenant, ingestion):
    from services.card_linked_payments.gold import entity_economic_activity

    await _seed(tenant, ingestion)
    rollup = await entity_economic_activity(tenant, "wh_g")
    assert rollup["topup_count"] == 1
    assert rollup["topup_volume_usd"] == "100.00"
    assert rollup["spend_count"] == 2
    assert rollup["spend_volume_usd"] == "50.00"
    assert rollup["basis"] == "mixed"
    assert set(rollup["basis_breakdown"]) == {"topup", "spend"}
    assert rollup["programs_observed"] == ["redotpay"]


async def test_campaign_outcomes_never_conflate_and_label_attribution(tenant, ingestion):
    from services.card_linked_payments.gold import campaign_card_linked_outcomes

    await _seed(tenant, ingestion)
    outcomes = await campaign_card_linked_outcomes(tenant, "camp_base_usdc")
    assert outcomes["card_topup_volume_usd"] == "100.00"
    assert outcomes["card_spend_volume_usd"] == "50.00"
    assert outcomes["card_topup_users"] == 1
    assert outcomes["card_spend_users"] == 1
    assert outcomes["attribution_basis"] == "direct"
    assert outcomes["programs_observed"] == ["redotpay"]
    assert "visa" in outcomes["payment_networks_observed"]


async def test_benchmark_only_rows_excluded_from_user_level_rollups(tenant, ingestion):
    from services.card_linked_payments.gold import entity_economic_activity, program_issuer_benchmarks

    await _seed(tenant, ingestion)
    rollup = await entity_economic_activity(tenant, "wh_g")
    assert rollup["flow_count"] == 3  # benchmark row not counted
    benchmarks = await program_issuer_benchmarks(tenant)
    assert benchmarks["benchmark_count"] == 1


async def test_cluster_features_and_gold_materialization(tenant, ingestion):
    from services.card_linked_payments.gold import cluster_features, materialize_gold

    await _seed(tenant, ingestion)
    features = await cluster_features(tenant)
    assert len(features) == 1
    feature = features[0]
    assert feature["programs"] == ["redotpay"]
    assert feature["spend_count"] == 2 and feature["topup_count"] == 1
    assert feature["campaign_converted"] is True
    assert feature["refund_loop_suspect"] is False
    written = await materialize_gold(tenant)
    assert written["cluster_feature_rows"] == 1


def test_projector_projects_only_card_linked_events():
    from services.silver.projectors.card_linked_projector import CardLinkedProjector

    projector = CardLinkedProjector()
    plain = projector.project({
        "type": "payment_completed", "id": "e1",
        "context": {"tenantId": "t1"}, "properties": {},
    })
    assert plain is not None and plain.skipped

    carded = projector.project({
        "type": "payment_completed", "id": "e2",
        "context": {"tenantId": "t1"},
        "properties": {"card_program": "redotpay", "basis": "topup", "amount_usd": "5"},
    })
    assert carded is not None and not carded.skipped
    (row,) = carded.rows
    assert row["card_program_id"] == "redotpay"
    assert row["basis"] == "topup"
    assert carded.table == "card_linked_flow_facts"


def test_projector_downgrades_sdk_spend_claims():
    from services.silver.projectors.card_linked_projector import CardLinkedProjector

    result = CardLinkedProjector().project({
        "type": "transaction", "id": "e3",
        "context": {"tenantId": "t1"},
        "properties": {"card_program": "kast", "basis": "spend"},
    })
    assert result is not None
    assert result.rows[0]["basis"] == "unknown"


def test_projector_idempotency_key_stable():
    from services.silver.projectors.card_linked_projector import CardLinkedProjector

    event = {
        "type": "conversion", "id": "e4", "context": {"tenantId": "t1"},
        "properties": {"card_program": "gnosis"},
    }
    p = CardLinkedProjector()
    assert p.project(event).rows[0]["idempotency_key"] == p.project(event).rows[0]["idempotency_key"]
