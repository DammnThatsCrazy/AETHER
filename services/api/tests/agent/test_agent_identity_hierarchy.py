"""AO-2: agent identity hierarchy semantics + human/agent separation guard."""

from __future__ import annotations

import pytest

from actions.agent.identity_hierarchy import (
    AGENT_ENTITY_KINDS,
    HIERARCHY_EDGES,
    HIERARCHY_ID_COLUMNS,
    HIERARCHY_LEVELS,
    HUMAN_ENTITY_KINDS,
    NON_IDENTITY_EVIDENCE_FIELDS,
    HumanAgentIdentityError,
    ensure_distinct_human_agent,
    hierarchy_refs_from_deployment,
    is_logical_identity,
)
from identity.identity.merge_policy import NON_MERGE_ELIGIBLE_SIGNAL_NAMES
from identity.identity.models import IdentitySignalType
from identity.identity.veto_engine import evaluate_vetoes
from shared.agent_lineage import vocabulary as V
from shared.graph.graph import EdgeType
from shared.graph.relationship_layers import _EDGE_LAYER_MAP


def test_hierarchy_levels_are_a_subset_of_the_seam_vocabulary_in_order():
    seam = [lvl for lvl in V.AGENT_HIERARCHY_LEVELS if lvl in HIERARCHY_LEVELS]
    assert seam == [lvl for lvl in HIERARCHY_LEVELS if lvl in V.AGENT_HIERARCHY_LEVELS]
    assert set(HIERARCHY_LEVELS) - set(V.AGENT_HIERARCHY_LEVELS) == set()


def test_only_the_definition_is_a_logical_identity():
    assert [lvl for lvl in HIERARCHY_LEVELS if is_logical_identity(lvl)] == ["agent_definition"]


def test_deployed_as_and_instantiated_as_are_registered_lineage_edges():
    for _, edge, _ in HIERARCHY_EDGES:
        assert edge in V.LINEAGE_RELATIONSHIP_TYPES
        assert getattr(EdgeType, edge) in _EDGE_LAYER_MAP


def test_every_level_has_an_identifier_column():
    assert set(HIERARCHY_ID_COLUMNS) == set(HIERARCHY_LEVELS)


def test_ten_thousand_instances_stay_one_logical_identity():
    definitions = {"agent-1"}
    deployments = {f"dep-{i}" for i in range(10)}
    instances = {f"inst-{i}" for i in range(10_000)}
    logical = {lvl: n for lvl, n in (
        ("agent_definition", len(definitions)),
        ("agent_deployment", len(deployments)),
        ("agent_instance", len(instances)),
    ) if is_logical_identity(lvl)}
    assert logical == {"agent_definition": 1}


def test_deployment_refs_are_source_references_not_canonical_entities():
    refs = hierarchy_refs_from_deployment({
        "id": "dep-1", "tenant_id": "t", "agent_id": "registry-agent",
        "agent_source_namespace": "vendor.runtime",
    })
    assert refs == {
        "tenant_id": "t", "agent_definition_ref": "registry-agent",
        "agent_source_namespace": "vendor.runtime", "deployment_id": "dep-1",
    }
    assert not any("entity" in key for key in refs)


def test_guard_rejects_same_id_and_wrong_kinds():
    with pytest.raises(HumanAgentIdentityError):
        ensure_distinct_human_agent(human_entity_id="e-1", agent_entity_id="e-1")
    with pytest.raises(HumanAgentIdentityError):
        ensure_distinct_human_agent(human_entity_id="h", agent_entity_id="a", human_kind="agent")
    with pytest.raises(HumanAgentIdentityError):
        ensure_distinct_human_agent(human_entity_id="h", agent_entity_id="a", agent_kind="person")
    with pytest.raises(HumanAgentIdentityError):
        ensure_distinct_human_agent(human_entity_id="", agent_entity_id="a")
    ensure_distinct_human_agent(human_entity_id="h-1", agent_entity_id="a-1")
    assert not HUMAN_ENTITY_KINDS & AGENT_ENTITY_KINDS


def test_hierarchy_identifiers_are_never_identity_signal_types():
    signal_values = {s.value for s in IdentitySignalType}
    # agent_id / deployment_id are on the resolver denylist; everything else is
    # not an identity signal at all, so it cannot contribute to a merge.
    leaking = (NON_IDENTITY_EVIDENCE_FIELDS & signal_values) - NON_MERGE_ELIGIBLE_SIGNAL_NAMES
    assert leaking == set()
    assert set(HIERARCHY_ID_COLUMNS.values()) - {"source_event_id"} <= NON_IDENTITY_EVIDENCE_FIELDS


@pytest.mark.asyncio
@pytest.mark.parametrize("current,candidate", [("person", "agent"), ("agent", "person")])
async def test_resolver_vetoes_human_agent_merge(current, candidate):
    vetoes = await evaluate_vetoes(
        tenant_id="t", candidate_tenant_id="t",
        candidate_entity_types=[candidate], current_entity_type=current,
        candidate_statuses=["active"], candidate_verified_emails=[],
        candidate_authenticated_user_ids=[], candidate_device_ids=[],
        candidate_has_revoked_consent=False, candidate_is_deleted=False,
        candidate_is_suppressed=False, candidate_source_namespaces=[],
    )
    assert any(v.veto_type.value == "agent_person_merge_attempt" for v in vetoes)
