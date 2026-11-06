"""Lineage engine: ground truth, replay, order independence, restatement, invariants."""
from __future__ import annotations

import random

import pytest

from actions.agent_lineage import synthetic as S
from actions.agent_lineage._common import UNATTRIBUTED, attribution_for
from actions.agent_lineage.config import LineageConfig
from actions.agent_lineage.engine import LineageEngine, compare_rows
from actions.agent_lineage.evidence import AuthorityRecord, PrincipalBinding
from shared.agent_lineage import vocabulary as V
from shared.agent_lineage.models import LineageCluster, LineageRow, LineageSummary

T = "tenant-a"


def _fact(agent, event="agent_task_started", at="2026-10-01T10:00:00Z", **extra):
    return {
        "tenant_id": T, "source_event_id": f"{agent}-{event}-{at}-{sorted(extra.items())}",
        "source_event_type": event, "agent_id": agent, "occurred_at": at, **extra,
    }


def _spawn(parent, child, at="2026-10-01T10:00:00Z", state="attested"):
    return _fact(parent, "agent_subagent_spawned", at, parent_agent_ref=parent, child_agent_ref=child,
                 execution_verification_state=state)


def _grant(agent, principal="human:h", ref=None, **extra):
    return AuthorityRecord(
        tenant_id=T, authority_ref=ref or f"grant-{principal}-{agent}", grantor_entity_id=principal,
        grantee_entity_id=agent, grantor_kind="principal", **extra,
    )


def _resolved(rows, *grants, config=None):
    engine = LineageEngine(T, config) if config else LineageEngine(T)
    for grant in grants:
        engine.upsert_authority(grant)
    engine.ingest(rows)
    return engine, engine.resolve()


def _row(engine, agent, principal="human:h"):
    return engine.rows()[(principal, agent)]


@pytest.mark.parametrize("tier", [100, 1000])
def test_fixture_resolves_to_ground_truth(tier):
    fixture = S.build_fixture(tier)
    engine = LineageEngine(S.TENANT)
    S.load(engine, fixture)
    engine.resolve()
    score = S.score(engine, fixture)
    for metric, value in score.items():
        if metric not in ("agents_in_truth", "agents_resolved"):
            assert value == 0, f"{metric}={value}"
    assert score["agents_resolved"] == score["agents_in_truth"]


def test_rows_clusters_and_summaries_satisfy_the_wire_models():
    fixture = S.build_fixture(1000)
    engine = LineageEngine(S.TENANT)
    S.load(engine, fixture)
    result = engine.resolve()
    for row in result.rows_upserted:
        assert LineageRow(**row).relationship_type in V.LINEAGE_RELATIONSHIP_TYPES
    for summary in result.summaries:
        LineageSummary(**summary)
    for clusters in result.clusters.values():
        for cluster in clusters:
            payload = {k: v for k, v in cluster.items() if k not in ("tenant_id", "principal_entity_id")}
            assert LineageCluster(**payload).bases


def test_arrival_order_does_not_change_the_projection():
    fixture = S.build_fixture(1000)
    first = LineageEngine(S.TENANT)
    S.load(first, fixture)
    first.resolve()
    random.Random(99).shuffle(fixture.facts)
    random.Random(99).shuffle(fixture.authorities)
    second = LineageEngine(S.TENANT)
    S.load(second, fixture)
    second.resolve()
    assert first.rows() == second.rows()


def test_replay_changes_nothing_and_counts_duplicates():
    fixture = S.build_fixture(100)
    engine = LineageEngine(S.TENANT)
    S.load(engine, fixture)
    engine.resolve()
    before = {key: dict(row) for key, row in engine.rows().items()}
    duplicates = engine.duplicates_ignored
    engine.ingest(fixture.facts)
    again = engine.resolve()
    assert engine.rows() == before
    assert again.rows_upserted == [] and again.restatements == []
    assert engine.duplicates_ignored == duplicates + len(fixture.facts)


@pytest.mark.parametrize("batches", [2, 7, 40])
def test_incremental_resolve_converges_on_a_full_rebuild(batches):
    fixture = S.build_fixture(1000)
    full = LineageEngine(S.TENANT)
    S.load(full, fixture)
    full.resolve()

    incremental = LineageEngine(S.TENANT)
    # Authority and bindings arrive mid-stream: late canonical evidence must
    # reach already-projected agents.
    size = max(1, len(fixture.facts) // batches)
    chunks = [fixture.facts[i:i + size] for i in range(0, len(fixture.facts), size)]
    for index, chunk in enumerate(chunks):
        incremental.ingest(chunk)
        if index == len(chunks) // 2:
            for record in fixture.authorities:
                incremental.upsert_authority(record)
            for binding in fixture.bindings:
                incremental.upsert_binding(binding)
        incremental.resolve()
    incremental.ingest(fixture.foreign_facts)
    incremental.resolve()
    assert incremental.rows() == full.rows()


def test_a_correction_restates_downstream_rows_and_reversing_it_returns_the_same_state():
    rows = [_fact("a"), _spawn("a", "b"), _fact("b"), _spawn("b", "c"), _fact("c")]
    engine, _ = _resolved(rows, _grant("a", ref="g1", delegation_allowed=True))
    original = {key: dict(row) for key, row in engine.rows().items()}
    assert _row(engine, "c")["attribution_class"] == "verified"

    revoked = engine.upsert_authority(_grant("a", ref="g1", delegation_allowed=True, revoked_at=1.0, version=2))
    assert revoked
    result = engine.resolve()
    assert {r["agent_entity_id"] for r in result.restatements} == {"a", "b", "c"}
    assert all(r["after"]["relationship_status"] == "revoked" for r in result.restatements)
    assert _row(engine, "c")["active_state"] == "revoked"
    # A stale lower-version record cannot undo the correction.
    assert not engine.upsert_authority(_grant("a", ref="g1", delegation_allowed=True))

    engine.upsert_authority(_grant("a", ref="g1", delegation_allowed=True, version=3))
    engine.resolve()
    assert engine.rows() == original


def test_a_rebuild_diff_reports_rows_that_vanished_or_changed():
    engine, _ = _resolved([_fact("a"), _spawn("a", "b")], _grant("a"))
    prior = {key: dict(row) for key, row in engine.rows().items()}
    rebuilt, _ = _resolved([_fact("a")], _grant("a"))
    removed, restatements, dropped = compare_rows(prior, rebuilt.rows())
    assert removed == [("human:h", "b")]
    assert [r["change_kind"] for r in restatements] == ["removed"]
    assert dropped == 0


# ── invariants ────────────────────────────────────────────────────────────


def test_a_reported_principal_is_a_claim_until_a_binding_resolves_it():
    claim = {"reported_principal_ref": "h@example.test", "reported_principal_namespace": "email"}
    engine, _ = _resolved([_fact("a", **claim)])
    row = _row(engine, "a", UNATTRIBUTED)
    assert row["attribution_class"] == "unresolved" and row["evidence_class"] == "UNKNOWN"
    assert ("h@example.test", "a") not in engine.rows()

    engine.upsert_binding(PrincipalBinding(
        tenant_id=T, kind="claim", principal_entity_id="human:h", namespace="email",
        claim_ref="h@example.test", evidence_class="PROVIDER_ASSERTED",
    ))
    engine.resolve()
    assert _row(engine, "a")["attribution_class"] == "inferred"
    assert (UNATTRIBUTED, "a") not in engine.rows()


@pytest.mark.parametrize("evidence_class", V.PRINCIPAL_EVIDENCE_CLASSES)
def test_only_proof_classes_can_reach_verified(evidence_class):
    engine = LineageEngine(T)
    engine.upsert_binding(PrincipalBinding(
        tenant_id=T, kind="agent", principal_entity_id="human:h", agent_entity_id="a",
        evidence_class=evidence_class,
    ))
    engine.ingest([_fact("a")])
    engine.resolve()
    verified = _row(engine, "a")["attribution_class"] == "verified"
    assert verified == (evidence_class in V.PRINCIPAL_PROOF_EVIDENCE_CLASSES)
    assert attribution_for(evidence_class) == _row(engine, "a")["attribution_class"]


def test_a_human_and_an_agent_never_become_the_same_identity():
    # Naming an observed agent as principal is not attribution.
    engine = LineageEngine(T)
    engine.upsert_binding(PrincipalBinding(
        tenant_id=T, kind="agent", principal_entity_id="b", agent_entity_id="a",
        evidence_class="VERIFIED_AUTHORITY",
    ))
    engine.upsert_binding(PrincipalBinding(
        tenant_id=T, kind="agent", principal_entity_id="a", agent_entity_id="a",
        evidence_class="VERIFIED_AUTHORITY",
    ))
    engine.ingest([_fact("a"), _fact("b")])
    engine.resolve()
    assert set(engine.rows()) == {(UNATTRIBUTED, "a"), (UNATTRIBUTED, "b")}


def test_an_agent_observed_after_being_named_principal_stops_being_one():
    engine = LineageEngine(T)
    engine.upsert_binding(PrincipalBinding(
        tenant_id=T, kind="agent", principal_entity_id="b", agent_entity_id="a",
        evidence_class="VERIFIED_AUTHORITY",
    ))
    engine.ingest([_fact("a")])
    engine.resolve()
    assert ("b", "a") in engine.rows()
    engine.ingest([_fact("b")])
    engine.resolve()
    assert ("b", "a") not in engine.rows()


def test_an_agent_naming_a_verified_parent_gains_no_attribution():
    engine, _ = _resolved(
        [_fact("orch"), _fact("impostor", parent_agent_ref="orch")], _grant("orch"),
    )
    row = _row(engine, "impostor")
    assert row["attribution_class"] == "unresolved"
    assert row["parent_agent_id"] == "orch"


def test_a_link_is_only_as_strong_as_its_weakest_hop():
    engine, _ = _resolved(
        [_fact("a"), _spawn("a", "b"), _spawn("b", "c", state=None), _spawn("c", "d")], _grant("a"),
    )
    assert _row(engine, "b")["attribution_class"] == "verified"
    assert _row(engine, "c")["evidence_class"] == "PROVIDER_ASSERTED"
    # A verified hop below an unverified one does not restore strength.
    assert _row(engine, "d")["attribution_class"] == "inferred"


def test_a_verified_link_demotes_a_contradicting_weak_claim_but_retains_it():
    engine = LineageEngine(T)
    engine.upsert_authority(_grant("a"))
    engine.upsert_binding(PrincipalBinding(
        tenant_id=T, kind="claim", principal_entity_id="human:other", namespace="crm",
        claim_ref="other", evidence_class="PROVIDER_ASSERTED",
    ))
    engine.ingest([_fact("a", reported_principal_ref="other", reported_principal_namespace="crm")])
    engine.resolve()
    assert _row(engine, "a")["attribution_class"] == "verified"
    weak = _row(engine, "a", "human:other")
    assert weak["attribution_class"] == "unresolved"
    assert weak["competing_principal_ids"] == ["human:h", "human:other"]


def test_competing_weak_claims_are_both_retained():
    engine = LineageEngine(T)
    for ref_, principal in (("x", "org:x"), ("y", "org:y")):
        engine.upsert_binding(PrincipalBinding(
            tenant_id=T, kind="claim", principal_entity_id=principal, namespace="crm", claim_ref=ref_,
            evidence_class="PROVIDER_ASSERTED",
        ))
    engine.ingest([
        _fact("a", reported_principal_ref="x", reported_principal_namespace="crm"),
        _fact("a", at="2026-10-01T10:00:01Z", reported_principal_ref="y", reported_principal_namespace="crm"),
    ])
    engine.resolve()
    for principal in ("org:x", "org:y"):
        assert _row(engine, "a", principal)["attribution_class"] == "inferred"
        assert _row(engine, "a", principal)["competing_principal_ids"] == ["org:x", "org:y"]


def test_a_cycle_is_marked_not_fatal_not_inflated_and_not_hidden():
    rows = [_spawn("a", "b"), _spawn("b", "c"), _spawn("c", "a"), _spawn("c", "d"), _spawn("d", "e")]
    engine, result = _resolved(rows)
    agents = {key[1] for key in engine.rows()}
    assert agents == {"a", "b", "c", "d", "e"}
    assert engine.agent_count() == 5
    for agent in "abc":
        assert _row(engine, agent, UNATTRIBUTED)["lineage_status"] == "cyclic"
    assert _row(engine, "d", UNATTRIBUTED)["lineage_status"] == "partial"
    summary = next(s for s in result.summaries if s["principal_entity_id"] == UNATTRIBUTED)
    assert summary["cyclic_agents"] == 3
    assert summary["disclosure"]["completeness"] == "partial"


def test_a_self_edge_and_a_cycle_anchor_with_authority_are_handled():
    rows = [_spawn("a", "a"), _spawn("b", "c"), _spawn("c", "b")]
    engine, _ = _resolved(rows, _grant("b"))
    assert _row(engine, "a", UNATTRIBUTED)["lineage_status"] == "cyclic"
    assert _row(engine, "b")["attribution_class"] == "verified"
    # Inheriting across a corrupt topology is at most inferred.
    assert _row(engine, "c")["attribution_class"] == "inferred"


def test_an_unobserved_parent_is_an_unresolved_state_and_late_arrival_resolves_it():
    engine, _ = _resolved([_fact("child", parent_agent_ref="ghost")])
    assert _row(engine, "child", UNATTRIBUTED)["lineage_status"] == "unresolved_parent"
    engine.upsert_authority(_grant("ghost"))
    engine.ingest([_spawn("ghost", "child")])
    engine.resolve()
    row = _row(engine, "child")
    assert row["parent_agent_id"] == "ghost" and row["lineage_status"] == "complete"
    assert (UNATTRIBUTED, "child") not in engine.rows()


def test_recursion_is_iterative_and_deep_chains_degrade_explicitly():
    depth = 3000
    rows = [_fact("n0")] + [_spawn(f"n{i}", f"n{i + 1}") for i in range(depth)]
    engine, result = _resolved(rows, _grant("n0"))
    assert _row(engine, "n31")["attribution_class"] == "verified"  # >= 32 durable levels
    assert _row(engine, "n63")["attribution_class"] == "verified"
    beyond = _row(engine, f"n{depth}")
    assert beyond["attribution_class"] == "unresolved" and beyond["lineage_status"] == "depth_limited"
    summary = next(s for s in result.summaries if s["principal_entity_id"] == "human:h")
    assert summary["disclosure"]["truncated"] is True
    assert summary["disclosure"]["completeness"] == "truncated"
    assert summary["max_delegation_depth"] == depth + 1


def test_processing_depth_can_never_drop_below_the_durable_minimum():
    with pytest.raises(ValueError):
        LineageConfig(max_depth=V.MIN_DURABLE_DELEGATION_DEPTH - 1)


def test_authority_scope_marks_out_of_scope_descendants_without_hiding_them():
    rows = [_fact("a"), _spawn("a", "b"), _spawn("b", "c"), _spawn("c", "d")]
    engine, result = _resolved(rows, _grant("a", delegation_allowed=True, maximum_delegation_depth=1))
    assert _row(engine, "b")["authority_resolution_status"] == "verified"
    assert _row(engine, "c")["authority_resolution_status"] == "out_of_scope"
    assert _row(engine, "d")["authority_resolution_status"] == "out_of_scope"
    summary = next(s for s in result.summaries if s["principal_entity_id"] == "human:h")
    assert summary["out_of_scope_agents"] == 2

    engine, _ = _resolved([_fact("a"), _spawn("a", "b")], _grant("a", delegation_allowed=False))
    assert _row(engine, "b")["authority_resolution_status"] == "out_of_scope"


def test_activity_after_expiry_is_marked_expired():
    rows = [_fact("a", at="2026-10-01T10:00:00Z")]
    engine, _ = _resolved(rows, _grant("a", valid_until=0.0))
    assert _row(engine, "a")["relationship_status"] == "expired"


def test_other_tenants_evidence_is_rejected():
    engine = LineageEngine(T)
    engine.ingest([{**_fact("a"), "tenant_id": "tenant-b"}])
    assert engine.upsert_authority(AuthorityRecord(
        tenant_id="tenant-b", authority_ref="g", grantor_entity_id="human:h", grantee_entity_id="a",
    )) is False
    engine.resolve()
    assert engine.rows() == {} and engine.cross_tenant_rejected == 2


def test_unknown_never_becomes_zero():
    engine, result = _resolved([_fact("a")], _grant("a"))
    summary = result.summaries[0]
    for field in ("agent_instances", "agent_runs", "tools_used", "services_used", "risk_flagged_agents"):
        assert summary[field] is None, field
    row = _row(engine, "a")
    assert row["risk_signal_count"] is None
    assert row["economic_activity_present"] is None
    assert row["communication_activity_present"] is None


def test_a_trace_is_not_a_run():
    engine, result = _resolved([_fact("a", run_id="trace-1", trace_id="trace-1", run_correlation_source="trace_id")])
    assert result.summaries[0]["agent_runs"] is None
    engine, result = _resolved([_fact("a", run_id="run-1", run_correlation_source="run_id")])
    assert result.summaries[0]["agent_runs"] == 1


def test_instances_do_not_become_logical_identities():
    rows = [_fact("a", agent_definition_id="def", agent_instance_id=f"i{n}", at=f"2026-10-01T10:00:{n:02d}Z") for n in range(50)]
    engine, result = _resolved(rows, _grant("a"))
    summary = result.summaries[0]
    assert engine.agent_count() == 1
    assert summary["unique_agent_definitions"] == 1 and summary["agent_instances"] == 50


def test_uncertain_population_is_a_suspected_cluster_never_common_control():
    rows = [_fact(f"u{i}", deployment_id="dep-shared", tool_name="http_get") for i in range(30)]
    _, result = _resolved(rows)
    clusters = result.clusters[UNATTRIBUTED]
    assert clusters
    for cluster in clusters:
        assert cluster["attribution_class"] == "suspected_cluster"
        assert cluster["implies_common_control"] is False
        assert cluster["bases"]
    summary = next(s for s in result.summaries if s["principal_entity_id"] == UNATTRIBUTED)
    assert summary["unresolved_agents"] == 30 and summary["verified_links"] == 0


def test_probabilistic_association_needs_a_gated_majority_and_stays_suspected():
    linked = [f"l{i}" for i in range(3)]
    engine = LineageEngine(T)
    for agent in linked:
        engine.upsert_authority(_grant(agent))
    engine.ingest([_fact(agent, deployment_id="dep") for agent in linked])
    engine.ingest([_fact("unlinked", deployment_id="dep")])
    engine.resolve()
    row = _row(engine, "unlinked")
    assert row["attribution_class"] == "suspected_cluster"
    assert row["evidence_class"] == "INFRASTRUCTURE_CORRELATED"

    # Below the linked-member gate there is no association at all.
    engine, _ = _resolved(
        [_fact("l0", deployment_id="dep"), _fact("unlinked", deployment_id="dep")], _grant("l0"),
    )
    assert (UNATTRIBUTED, "unlinked") in engine.rows()

    # A divided deployment does not reach the share gate.
    grants = [_grant(f"l{i}", principal=f"human:{i % 2}") for i in range(6)]
    rows = [_fact(f"l{i}", deployment_id="dep") for i in range(6)] + [_fact("unlinked", deployment_id="dep")]
    engine, _ = _resolved(rows, *grants)
    assert (UNATTRIBUTED, "unlinked") in engine.rows()


def test_a_verified_cluster_is_the_only_one_that_says_anything_about_control():
    rows = [_fact("a", deployment_id="dep", agent_definition_id="d")]
    for i in range(6):
        rows.append(_spawn("a", f"c{i}"))
        rows.append(_fact(f"c{i}", deployment_id="dep"))
    _, result = _resolved(rows, _grant("a"))
    by_basis = {c["bases"][0]["basis"]: c for c in result.clusters["human:h"]}
    assert by_basis["shared_delegation_root"]["implies_common_control"] is True
    assert by_basis["temporal_coordination"]["implies_common_control"] is False


def test_descendant_counts_roll_up_and_unknown_risk_stays_unknown():
    rows = [_fact("a"), _spawn("a", "b"), _spawn("b", "c"), _spawn("a", "d"), _fact("c", risk_level="high")]
    _, result = _resolved(rows, _grant("a"))
    nodes = {n["agent_entity_id"]: n for n in result.nodes_upserted}
    assert nodes["a"]["direct_child_count"] == 2
    assert nodes["a"]["recursive_descendant_count"] == 3
    assert nodes["a"]["max_descendant_depth"] == 2
    assert nodes["a"]["risk_descendant_count"] == 1
    assert nodes["d"]["risk_descendant_count"] is None
    assert nodes["c"]["path"].split("\x1f") == ["a", "b", "c"]


def test_as_of_comes_from_evidence_so_rebuilds_are_identical():
    rows = [_fact("a", at="2026-10-01T10:00:00Z")]
    first, _ = _resolved(rows, _grant("a"))
    second, _ = _resolved(rows, _grant("a"))
    assert first.rows() == second.rows()
    assert _row(first, "a")["last_reconciled_at"] == "2026-10-01T10:00:00.000Z"


def test_real_projector_output_flows_through_the_engine():
    """Field names must match what the Silver projector actually writes."""
    from ingestion.silver.projectors.agent_execution_projector import AgentExecutionProjector

    projector = AgentExecutionProjector()

    def project(event_type, agent, **properties):
        result = projector.project({
            "messageId": f"e-{agent}-{event_type}", "tenantId": T, "type": event_type,
            "timestamp": "2026-10-01T10:00:00Z",
            "validated_agent_deployment": {"agentId": agent, "deploymentId": "dep-1"},
            "properties": properties, "context": {},
        })
        assert result is not None
        return result.rows[0]

    rows = [
        project("agent_subagent_spawned", "orch", parentAgentId="orch", childAgentId="worker"),
        project("agent_tool_invocation_observed", "worker", toolName="read_file", runId="run-1"),
    ]
    engine = LineageEngine(T)
    engine.upsert_authority(_grant("orch"))
    assert engine.ingest(rows) == 2
    result = engine.resolve()
    row = _row(engine, "worker")
    assert row["parent_agent_id"] == "orch" and row["root_agent_id"] == "orch"
    assert row["depth"] == 2 and row["agent_run_count"] == 1
    assert row["evidence_count"] == 1
    # The projector leaves canonical columns NULL; the engine never reads a claim as truth.
    assert all(fact.get("canonical_principal_entity_id") is None for fact in rows)
    assert result.summaries[0]["tools_used"] == 1


def test_a_deployment_id_alone_does_not_prove_who_reported_a_spawn():
    engine, _ = _resolved(
        [_fact("a"), _spawn("a", "evil", state="deployment_verified")], _grant("a"),
    )
    assert _row(engine, "evil")["attribution_class"] == "inferred"


def test_a_self_claimed_child_cannot_raise_the_named_principals_risk_inputs():
    rows = [_fact("a")]
    for i in range(10):
        rows.append(_fact(f"evil{i}", "agent_policy_evaluated", parent_agent_ref="a", policy_decision="deny"))
    _, result = _resolved(rows, _grant("a", ref="g", maximum_delegation_depth=0, delegation_allowed=False))
    summary = next(s for s in result.summaries if s["principal_entity_id"] == "human:h")
    assert summary["unresolved_agents"] == 10
    assert summary["activity"]["denied_event_count"] == 0
    assert summary["activity"]["agent_count"] == 1
    assert summary["out_of_scope_agents"] == 0


def test_a_repeated_declaration_cannot_displace_a_registered_owner():
    engine = LineageEngine(T)
    engine.upsert_binding(PrincipalBinding(
        tenant_id=T, kind="agent", principal_entity_id="human:owner", agent_entity_id="a",
        evidence_class="DETERMINISTIC_BINDING", source="registry",
    ))
    for version in (1, 2, 3):
        engine.upsert_binding(PrincipalBinding(
            tenant_id=T, kind="agent", principal_entity_id="human:scapegoat", agent_entity_id="a",
            evidence_class="TENANT_DECLARED", version=version,
        ))
    engine.ingest([_fact("a")])
    engine.resolve()
    assert _row(engine, "a", "human:owner")["attribution_class"] == "verified"
    assert _row(engine, "a", "human:scapegoat")["attribution_class"] == "unresolved"


def test_a_ref_in_someone_elses_spawn_cannot_turn_a_principal_into_an_agent():
    rows = [_fact("a"), _spawn("a", "b"), _spawn("a", "human:h")]
    engine, _ = _resolved(rows, _grant("a"))
    assert _row(engine, "a")["attribution_class"] == "verified"
    assert _row(engine, "b")["attribution_class"] == "verified"
    # Declaring a known principal to be an agent does not redirect its fleet either.
    engine.upsert_binding(PrincipalBinding(
        tenant_id=T, kind="agent", principal_entity_id="human:q", agent_entity_id="human:h",
        evidence_class="TENANT_DECLARED",
    ))
    engine.resolve()
    assert _row(engine, "a")["attribution_class"] == "verified"
    assert ("human:q", "a") not in engine.rows()
