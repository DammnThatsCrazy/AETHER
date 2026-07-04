from decimal import Decimal
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "Backend Architecture" / "aether-backend"
sys.path.insert(0, str(BACKEND_ROOT))

from services.derivatives.intelligence import (
    ACTOR_EDGE_LAYER_MAP,
    DOMAIN_EDGE_LAYER_MAP,
    AuthorityGrant,
    EvidenceClass,
    EvidenceEnvelope,
    GraphLayer,
    answer_noesis_derivatives_question,
    build_campaign_outcome_claim,
    build_profile360_derivatives_summary,
    compute_behavior_features,
    project_position_edges,
)
from services.derivatives.models import PositionEpochState, PositionSide, PositionStatus, SourceRef


def _position(tenant_id="tenant-a", pnl="12.50", fees="1.25"):
    return PositionEpochState(
        tenant_id=tenant_id,
        trading_account_id="acct-1",
        canonical_market_id="mkt-btc-usd-perp",
        epoch_id="epoch-1",
        side=PositionSide.LONG,
        status=PositionStatus.CLOSED,
        size=Decimal("0"),
        entry_notional=Decimal("0"),
        realized_pnl=Decimal(pnl),
        fees=Decimal(fees),
        opened_at="2026-07-01T00:00:00Z",
        closed_at="2026-07-02T00:00:00Z",
        source_fill_ids=["fill-1", "fill-2"],
    )


def test_edge_inventory_separates_actor_layers_from_domain_edges():
    assert ACTOR_EDGE_LAYER_MAP["DELEGATES_TRADING_TO"] is GraphLayer.H2A
    assert ACTOR_EDGE_LAYER_MAP["REPORTS_PNL_TO"] is GraphLayer.A2H
    assert all(layer is GraphLayer.DOMAIN_EXCLUDED for layer in DOMAIN_EDGE_LAYER_MAP.values())
    assert DOMAIN_EDGE_LAYER_MAP["HOLDS_POSITION"] is GraphLayer.DOMAIN_EXCLUDED


def test_position_projection_is_idempotent_tenant_scoped_and_evidence_backed():
    first = project_position_edges(_position(), "2026-07-03T00:00:00Z")
    second = project_position_edges(_position(), "2026-07-03T00:00:00Z")

    assert [edge.idempotency_key for edge in first] == [edge.idempotency_key for edge in second]
    assert {edge.tenant_id for edge in first} == {"tenant-a"}
    assert {edge.layer for edge in first} == {GraphLayer.DOMAIN_EXCLUDED}
    assert first[0].evidence.evidence_class is EvidenceClass.COMPUTATION
    assert first[0].evidence.source_refs
    assert first[-1].properties["net_realized_pnl"] == "11.25"


def test_unknown_or_misclassified_graph_edges_fail_closed():
    evidence = EvidenceEnvelope(
        evidence_class=EvidenceClass.FACT,
        source_refs=("provider:event-1",),
        source_event_ids=("event-1",),
        confidence=Decimal("1"),
        valid_time="2026-07-01T00:00:00Z",
        recorded_time="2026-07-01T00:00:00Z",
        explanation="test",
    )
    with pytest.raises(ValueError, match="unclassified"):
        from services.derivatives.intelligence import DerivativesGraphEdgeIntent

        DerivativesGraphEdgeIntent("tenant-a", "UNMAPPED", "a", "b", GraphLayer.H2H, evidence, "2026-07-01T00:00:00Z", "2026-07-01T00:00:00Z")
    with pytest.raises(ValueError, match="must be classified"):
        from services.derivatives.intelligence import DerivativesGraphEdgeIntent

        DerivativesGraphEdgeIntent("tenant-a", "HOLDS_POSITION", "a", "b", GraphLayer.H2H, evidence, "2026-07-01T00:00:00Z", "2026-07-01T00:00:00Z")


def test_authority_grant_emits_actor_and_policy_domain_edges():
    grant = AuthorityGrant(
        tenant_id="tenant-a",
        human_ref="human:h1",
        agent_ref="agent:a1",
        risk_policy_ref="risk_policy:rp1",
        markets=("mkt-btc-usd-perp",),
        max_leverage=Decimal("3"),
        max_notional=Decimal("10000"),
        approval_required=True,
        valid_from="2026-07-01T00:00:00Z",
        recorded_at="2026-07-01T00:00:01Z",
        source_ref=SourceRef("tenant_policy", "policy-1", "2026-07-01T00:00:00Z"),
    )

    edges = grant.to_graph_edges()
    assert [edge.edge_type for edge in edges] == ["DELEGATES_TRADING_TO", "GOVERNED_BY_POLICY"]
    assert edges[0].layer is GraphLayer.H2A
    assert edges[1].layer is GraphLayer.DOMAIN_EXCLUDED
    assert edges[0].properties["withdrawal_prohibited"] == "true"


def test_behavior_profile_and_campaign_features_are_decimal_and_tenant_isolated():
    features = compute_behavior_features("tenant-a", [_position(), _position("tenant-b", "99", "0")], "30d")

    assert features["position_count"] == 1
    assert features["long_bias"] == Decimal("1")
    assert features["net_realized_pnl"] == Decimal("11.25")
    assert features["markets"] == ["mkt-btc-usd-perp"]

    profile = build_profile360_derivatives_summary("tenant-a", [_position()])
    assert profile["dimension"] == "derivatives"
    assert profile["state"] == "complete"
    assert profile["evidence_class"] == "computation"

    empty_profile = build_profile360_derivatives_summary("tenant-a", [])
    assert empty_profile["state"] == "empty"
    assert empty_profile["evidence_class"] == "insufficient_evidence"

    campaign = build_campaign_outcome_claim("tenant-a", "campaign-1", [_position()])
    assert campaign["claim_class"] == "inference"
    assert campaign["causal_status"] == "not_proven"
    assert campaign["net_realized_pnl"] == Decimal("11.25")


def test_noesis_answers_classify_claims_and_return_insufficient_evidence():
    answer = answer_noesis_derivatives_question("tenant-a", "Which agents had the best net PnL?", [_position()])
    assert {claim["class"] for claim in answer["claims"]} == {"fact", "computation", "inference"}
    assert "net realized PnL 11.25" in answer["answer"]

    insufficient = answer_noesis_derivatives_question("tenant-a", "Show liquidations", [_position("tenant-b")])
    assert insufficient["claims"] == [{"class": "insufficient_evidence", "text": "No tenant-scoped derivative positions were provided."}]
