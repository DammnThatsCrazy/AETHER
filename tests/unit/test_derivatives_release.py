from decimal import Decimal
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "Backend Architecture" / "aether-backend"
sys.path.insert(0, str(BACKEND_ROOT))

from services.derivatives.ml_release import (  # noqa: E402
    coordinated_behavior_safeguard,
    deployment_profile_matrix,
    deterministic_validation_report,
    load_resilience_matrix,
    model_governance_registry,
    provider_licensing_controls,
    strict_release_gate_report,
)
from services.derivatives.models import PositionEpochState, PositionSide, PositionStatus  # noqa: E402
from services.derivatives.multi_venue import (  # noqa: E402
    CANONICAL_CONCEPTS,
    build_scaffolded_adapters,
    cross_venue_parity_report,
)


def test_structurally_distinct_venues_normalize_to_canonical_fill_facts():
    payloads = {
        "dydx": {"id": "dy-fill-1", "subaccount": "sub-7", "ticker": "BTC-USD", "side": "BUY", "price": "61000.12", "size": "0.10", "fee": "1.20", "feeAsset": "USDC", "createdAt": "2026-07-05T00:00:00Z", "liquidity": "maker"},
        "gmx": {"eventId": "gmx-fill-1", "account": "0xabc", "market": "ETH-USD", "direction": "short", "executionPrice": "3400.01", "sizeUsd": "100.00", "feeUsd": "0.40", "feeAsset": "USDC", "blockTime": "2026-07-05T00:01:00Z"},
        "drift": {"fillId": "drift-fill-1", "authority": "sol-auth", "marketName": "SOL-PERP", "direction": "long", "oraclePrice": "150.00", "baseAssetAmount": "2.5", "fee": "0.05", "feeAsset": "USDC", "slotTime": "2026-07-05T00:02:00Z", "liquidity": "taker"},
        "centralized_futures": {"tradeId": "cex-fill-1", "accountId": "acct-cex", "symbol": "BTCUSDT-PERP", "side": "SELL", "avgPrice": "60990.00", "contracts": "0.20", "commission": "1.00", "commissionAsset": "USDT", "time": "2026-07-05T00:03:00Z", "makerTaker": "taker"},
    }
    facts = []
    for venue_id, adapter in build_scaffolded_adapters().items():
        observation = adapter.bronze(
            "tenant-release",
            "unit-test",
            f"{venue_id}:fill:1",
            payloads[venue_id],
        )
        facts.append(adapter.normalize_fill(observation))
    assert {fact.provider for fact in facts} == {"dydx", "gmx", "drift", "centralized_futures"}
    assert all(fact.tenant_id == "tenant-release" for fact in facts)
    assert all(fact.execution_by_aether is False for fact in facts)
    assert all(isinstance(fact.price, Decimal) and isinstance(fact.quantity, Decimal) for fact in facts)
    assert all(fact.canonical_market_id.startswith(f"{fact.provider}:") for fact in facts)
    assert len({fact.idempotency_key for fact in facts}) == len(facts)


def test_cross_venue_parity_uses_capabilities_instead_of_fake_values():
    report = cross_venue_parity_report(build_scaffolded_adapters())
    assert report["provider_specific_api_leakage"] is False
    assert report["canonical_concepts"] == list(CANONICAL_CONCEPTS)
    assert report["venues"]["gmx"]["missing_concepts"] == ["orders"]
    assert "gmx" in report["missing_by_concept"]["orders"]


def test_deterministic_intelligence_validation_and_model_governance_fail_closed_without_consent():
    position = PositionEpochState(
        tenant_id="tenant-release",
        trading_account_id="acct-1",
        canonical_market_id="dydx:fixture:BTC-USD",
        epoch_id="epoch-1",
        side=PositionSide.LONG,
        status=PositionStatus.CLOSED,
        size=Decimal("0"),
        realized_pnl=Decimal("10"),
        fees=Decimal("1"),
        source_fill_ids=["fill-1"],
    )
    report = deterministic_validation_report("tenant-release", [position])
    assert report["metrics"]["effective_leverage"] == "validated"
    assert report["feature_summary"]["net_realized_pnl"] == "9"
    registry = model_governance_registry(consent_allows_training=False, reliable_labels_available=True)
    assert all(card["status"] == "deterministic_fallback_only" for card in registry.values())
    assert all(card["kill_switch"] is True and card["fallback"] == "deterministic_rules" for card in registry.values())


def test_coordinated_behavior_safeguard_never_labels_misconduct_from_timing_alone():
    weak = coordinated_behavior_safeguard({"timing": True})
    assert weak["label"] == "insufficient_evidence"
    assert weak["non_accusatory"] is True
    strong = coordinated_behavior_safeguard({"timing": True, "sizing": True, "venue_overlap": True, "market_overlap": True})
    assert strong["label"] == "possible_coordination_hypothesis"
    assert strong["review_state"] == "requires_human_review"


def test_load_recovery_licensing_deployment_and_strict_release_gate_require_evidence():
    load = load_resilience_matrix()
    assert load["load_scenarios"]["liquidation_spike"]["covered"] is True
    assert load["recovery_scenarios"]["graph_rebuild"]["rebuild_source"] == "bronze_plus_canonical_state"
    licensing = provider_licensing_controls()
    assert all(provider["ml_training_restrictions_enforced"] for provider in licensing.values())
    profiles = deployment_profile_matrix()
    assert profiles["production"]["fail_closed"] is True
    unevaluated = strict_release_gate_report()
    assert unevaluated["passed"] is False
    assert unevaluated["availability"] == "insufficient_evidence"
    assert all(value is None for value in unevaluated["gates"].values())
    strict = strict_release_gate_report(
        {gate: True for gate in unevaluated["gates"]}
    )
    assert strict["passed"] is True
    assert strict["availability"] == "evaluated"
    assert all(strict["gates"].values())
    failed = strict_release_gate_report({"staging_ingestion_succeeded": False})
    assert failed["passed"] is False
