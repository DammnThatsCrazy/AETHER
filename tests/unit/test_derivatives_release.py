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
    build_pr5_adapters,
    cross_venue_parity_report,
    normalize_all_fixture_fills,
)


def test_structurally_distinct_venues_normalize_to_canonical_fill_facts():
    facts = normalize_all_fixture_fills("tenant-release")
    assert {fact.provider for fact in facts} == {"dydx", "gmx", "drift", "centralized_futures"}
    assert all(fact.tenant_id == "tenant-release" for fact in facts)
    assert all(fact.execution_by_aether is False for fact in facts)
    assert all(isinstance(fact.price, Decimal) and isinstance(fact.quantity, Decimal) for fact in facts)
    assert all(fact.canonical_market_id.startswith(f"{fact.provider}:") for fact in facts)
    assert len({fact.idempotency_key for fact in facts}) == len(facts)


def test_cross_venue_parity_uses_capabilities_instead_of_fake_values():
    report = cross_venue_parity_report(build_pr5_adapters())
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


def test_load_recovery_licensing_deployment_and_strict_release_gate_are_complete():
    load = load_resilience_matrix()
    assert load["load_scenarios"]["liquidation_spike"]["covered"] is True
    assert load["recovery_scenarios"]["graph_rebuild"]["rebuild_source"] == "bronze_plus_canonical_state"
    licensing = provider_licensing_controls()
    assert all(provider["ml_training_restrictions_enforced"] for provider in licensing.values())
    profiles = deployment_profile_matrix()
    assert profiles["production"]["fail_closed"] is True
    strict = strict_release_gate_report()
    assert strict["passed"] is True
    assert all(strict["gates"].values())
    failed = strict_release_gate_report({"staging_ingestion_succeeded": False})
    assert failed["passed"] is False
