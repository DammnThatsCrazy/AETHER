"""Relationship promotion -> graph gateway tests (M6 STEP 3).

Covers the promotion state machine: registry-floor evaluation (independence
floor, proof-level floor, temporal dispersion, supplied structural
requirements, contradiction), canonical edge shape, gateway projection
idempotency, revocation and rollout-flag gating (default OFF).
"""

from __future__ import annotations

import pytest
from shared.graph.edge_properties import REQUIRED_EDGE_PROPERTIES
from shared.graph.graph import GraphClient
from shared.graph.mutation_gateway import GraphMutationGateway
from shared.relationship_spine import flags
from shared.relationship_spine.evidence import Observation, candidate_groups_for_pair
from shared.relationship_spine.promotion import (
    PromotionReason,
    PromotionVerdict,
    edge_from_assertion,
    evaluate_promotion,
    project_assertion,
    revoke_assertion,
)


def _obs(oid, predicate, day="2026-01-01", src="s", proof="provider_observed"):
    return Observation(
        observation_id=oid,
        predicate=predicate,
        source_entity_id="a",
        target_entity_id="b",
        source_key=src,
        observed_at=f"{day}T00:00:00+00:00",
        supports_predicate=True,
        proof_level=proof,
    )


def _enable_promotion(monkeypatch):
    monkeypatch.setenv("AETHER_RELATIONSHIP_PROMOTION_ENABLED", "true")
    flags.invalidate_flag_cache()


def _disable_promotion(monkeypatch):
    monkeypatch.delenv("AETHER_RELATIONSHIP_PROMOTION_ENABLED", raising=False)
    monkeypatch.delenv("AETHER_SOCIAL360_ENABLED", raising=False)
    flags.invalidate_flag_cache()


def _edges_of_type(client, edge_type):
    return [e for e in client._backend._edges if e.edge_type == edge_type]


def test_follows_promotes_to_registered_social_edge():
    group = candidate_groups_for_pair(
        [
            _obs("e1", "FOLLOWS", src="A"),
            _obs("e2", "FOLLOWS", day="2026-01-02", src="B"),
        ],
        "FOLLOWS",
        "a",
        "b",
    )
    result = evaluate_promotion(group, tenant_id="t1")
    assert result.verdict == PromotionVerdict.PROMOTE
    assert result.promoted
    assert result.assertion is not None
    # FOLLOWS must promote as FOLLOWS_SOCIAL (M1 disambiguation, not a raw edge).
    assert result.assertion.edge_type == "FOLLOWS_SOCIAL"
    assert result.assertion.predicate == "FOLLOWS"
    assert result.assertion.source_entity_id == "a"
    assert result.assertion.target_entity_id == "b"


def test_interacts_with_requires_dispersion_and_three_sources():
    # Three independent sources on ONE day -> below floor (no dispersion).
    group = candidate_groups_for_pair(
        [
            _obs("i1", "INTERACTS_WITH", src="A"),
            _obs("i2", "INTERACTS_WITH", src="B"),
            _obs("i3", "INTERACTS_WITH", src="C"),
        ],
        "INTERACTS_WITH",
        "a",
        "b",
    )
    result = evaluate_promotion(group, tenant_id="t1")
    assert result.verdict == PromotionVerdict.BELOW_FLOOR
    assert result.reason == PromotionReason.INSUFFICIENT_TEMPORAL_DISPERSION.value

    # Three independent sources across two days -> promote.
    group2 = candidate_groups_for_pair(
        [
            _obs("i1", "INTERACTS_WITH", src="A", day="2026-01-01"),
            _obs("i2", "INTERACTS_WITH", src="B", day="2026-01-01"),
            _obs("i3", "INTERACTS_WITH", src="C", day="2026-01-02"),
        ],
        "INTERACTS_WITH",
        "a",
        "b",
    )
    result2 = evaluate_promotion(group2, tenant_id="t1")
    assert result2.verdict == PromotionVerdict.PROMOTE
    assert result2.assertion.edge_type == "SOCIAL_INTERACTS_WITH"


def test_proof_level_floor_enforced():
    # COLLABORATES_WITH floor is verified_authoritative; provider_observed obs
    # must NOT promote even with the corroboration supplied.
    group = candidate_groups_for_pair(
        [
            _obs("c1", "COLLABORATES_WITH", src="A", proof="provider_observed"),
            _obs("c2", "COLLABORATES_WITH", src="B", proof="provider_observed"),
        ],
        "COLLABORATES_WITH",
        "a",
        "b",
    )
    result = evaluate_promotion(
        group, tenant_id="t1", supplied_requirements={"corroborationRequired": True}
    )
    assert result.verdict == PromotionVerdict.BELOW_FLOOR
    assert result.reason == PromotionReason.BELOW_PROOF_FLOOR.value


def test_verified_authoritative_observation_meets_floor():
    group = candidate_groups_for_pair(
        [
            _obs("c1", "COLLABORATES_WITH", src="A", proof="verified_authoritative"),
            _obs("c2", "COLLABORATES_WITH", src="B", proof="verified_authoritative"),
        ],
        "COLLABORATES_WITH",
        "a",
        "b",
    )
    result = evaluate_promotion(
        group, tenant_id="t1", supplied_requirements={"corroborationRequired": True}
    )
    assert result.verdict == PromotionVerdict.PROMOTE


def test_unevaluable_requirement_is_not_silently_met():
    # CO_EXPOSED declares incentiveExposureRequired; a plain evidence group has
    # no incentive-exposure context -> unevaluable (not treated as absent).
    group = candidate_groups_for_pair(
        [_obs("x1", "CO_EXPOSED", src="A")], "CO_EXPOSED", "a", "b"
    )
    result = evaluate_promotion(group, tenant_id="t1")
    assert result.verdict == PromotionVerdict.BELOW_FLOOR
    assert "incentiveExposureRequired" in result.unmet_requirements
    assert result.reason == PromotionReason.REQ_UNEVALUABLE.value


def test_supplied_incentive_exposure_allows_promotion():
    group = candidate_groups_for_pair(
        [_obs("x1", "CO_EXPOSED", src="A")], "CO_EXPOSED", "a", "b"
    )
    result = evaluate_promotion(
        group, tenant_id="t1", supplied_requirements={"incentiveExposureRequired": True}
    )
    assert result.verdict == PromotionVerdict.PROMOTE


def test_contradiction_blocks_promotion():
    obs = [
        _obs("e1", "FOLLOWS", src="A"),
        _obs("e2", "FOLLOWS", src="B"),
        Observation(
            observation_id="e3",
            predicate="FOLLOWS",
            source_entity_id="a",
            target_entity_id="b",
            source_key="C",
            observed_at="2026-01-03T00:00:00+00:00",
            supports_predicate=False,
        ),
    ]
    group = candidate_groups_for_pair(obs, "FOLLOWS", "a", "b")
    result = evaluate_promotion(group, tenant_id="t1")
    assert result.verdict == PromotionVerdict.CONTRADICTED
    assert result.assertion is None


def test_unknown_predicate_is_honest():
    group = candidate_groups_for_pair(
        [_obs("e1", "NOT_A_REAL_PREDICATE", src="A")],
        "NOT_A_REAL_PREDICATE",
        "a",
        "b",
    )
    result = evaluate_promotion(group, tenant_id="t1")
    assert result.verdict == PromotionVerdict.UNKNOWN_PREDICATE


def test_edge_has_canonical_properties():
    group = candidate_groups_for_pair(
        [
            _obs("e1", "FOLLOWS", src="A"),
            _obs("e2", "FOLLOWS", day="2026-01-02", src="B"),
        ],
        "FOLLOWS",
        "a",
        "b",
    )
    assertion = evaluate_promotion(group, tenant_id="t1").assertion
    edge = edge_from_assertion(assertion)
    assert edge.from_vertex_id == "a"
    assert edge.to_vertex_id == "b"
    props = edge.properties
    assert REQUIRED_EDGE_PROPERTIES <= set(props), props
    assert props["tenant_id"] == "t1"
    assert props["idempotency_key"]
    assert props["actor_kind"] == "system"
    assert props["relationship_predicate"] == "FOLLOWS"
    assert props["claim_ceiling"] == "observed"
    assert "e1" in props["evidence_refs"]
    assert "e2" in props["evidence_refs"]


@pytest.mark.asyncio
async def test_project_assertion_is_idempotent(monkeypatch):
    _enable_promotion(monkeypatch)
    client = GraphClient()
    await client.connect()
    gateway = GraphMutationGateway(graph_client=client)
    group = candidate_groups_for_pair(
        [
            _obs("e1", "FOLLOWS", src="A"),
            _obs("e2", "FOLLOWS", day="2026-01-02", src="B"),
        ],
        "FOLLOWS",
        "a",
        "b",
    )
    assertion = evaluate_promotion(group, tenant_id="t1").assertion
    assert await project_assertion(assertion, gateway=gateway, graph_client=client) == "projected"
    # A second projection of the same assertion converges (no duplicate edge).
    assert await project_assertion(assertion, gateway=gateway, graph_client=client) == "skipped_existing"
    assert len(_edges_of_type(client, "FOLLOWS_SOCIAL")) == 1


@pytest.mark.asyncio
async def test_project_assertion_flag_off_is_disabled(monkeypatch):
    _disable_promotion(monkeypatch)
    client = GraphClient()
    await client.connect()
    gateway = GraphMutationGateway(graph_client=client)
    group = candidate_groups_for_pair(
        [_obs("e1", "FOLLOWS", src="A")], "FOLLOWS", "a", "b"
    )
    assertion = evaluate_promotion(group, tenant_id="t1").assertion
    assert await project_assertion(assertion, gateway=gateway, graph_client=client) == "disabled"
    assert _edges_of_type(client, "FOLLOWS_SOCIAL") == []


@pytest.mark.asyncio
async def test_revoke_assertion_through_gateway(monkeypatch):
    _enable_promotion(monkeypatch)
    client = GraphClient()
    await client.connect()
    gateway = GraphMutationGateway(graph_client=client)
    group = candidate_groups_for_pair(
        [
            _obs("e1", "FOLLOWS", src="A"),
            _obs("e2", "FOLLOWS", day="2026-01-02", src="B"),
        ],
        "FOLLOWS",
        "a",
        "b",
    )
    assertion = evaluate_promotion(group, tenant_id="t1").assertion
    await project_assertion(assertion, gateway=gateway, graph_client=client)
    assert len(_edges_of_type(client, "FOLLOWS_SOCIAL")) == 1
    assert await revoke_assertion(assertion, gateway=gateway, graph_client=client) == "revoked"
    revoked = [e for e in _edges_of_type(client, "FOLLOWS_SOCIAL") if (e.properties or {}).get("revoked")]
    assert revoked, "revocation should soft-revoke (mark revoked), never hard-delete"
