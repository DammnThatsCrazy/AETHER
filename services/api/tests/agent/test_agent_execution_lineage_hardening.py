"""AO-3: execution lineage hardening on silver_agent_execution_facts.

Source vs canonical ids, run vs trace, reported vs resolved principal, agent
definition vs instance, parent vs root. Resolution columns stay NULL at
projection time and projection is deterministic / replay safe.
"""

from __future__ import annotations

import ast
import copy
import re
from pathlib import Path

import pytest

from ingestion.silver.projectors.agent_execution_projector import AgentExecutionProjector
from shared.agent_lineage import vocabulary as lineage_vocab

# Exact column names consumed by the lineage resolution engine.
LINEAGE_COLUMNS = (
    "canonical_run_id", "source_run_id", "root_run_id", "parent_run_id",
    "agent_definition_id", "agent_instance_id",
    "parent_agent_entity_id", "root_agent_entity_id",
    "reported_principal_ref", "reported_principal_namespace",
    "canonical_principal_entity_id", "principal_resolution_status",
    "initiator_entity_id", "executor_entity_id", "operator_entity_id",
    "beneficiary_entity_id", "control_mode", "authority_type", "authority_ref",
    "delegation_depth", "protocol", "protocol_version", "external_effect_ref",
    "execution_verification_state", "parent_span_id",
)

_MIGRATION = (
    Path(__file__).resolve().parents[2]
    / "alembic" / "versions" / "20261030_agent_execution_lineage_hardening.py"
)


def _project(event: dict) -> dict:
    result = AgentExecutionProjector().project(event)
    assert result is not None
    assert result.table == "silver_agent_execution_facts"
    return result.rows[0]


def _event(**overrides) -> dict:
    event = {
        "messageId": "evt-1",
        "type": "agent_task_started",
        "tenantId": "tenant-a",
        "timestamp": "2026-10-30T10:00:00Z",
        "properties": {"agentId": "agent-1", "taskId": "task-1"},
        "context": {"tenantId": "tenant-a"},
    }
    event.update(overrides)
    return event


def test_every_lineage_column_is_emitted_and_migrated():
    row = _project(_event())
    assert set(LINEAGE_COLUMNS) <= set(row), set(LINEAGE_COLUMNS) - set(row)

    tree = ast.parse(_MIGRATION.read_text())
    declared = next(
        ast.literal_eval(node.value)
        for node in tree.body
        if isinstance(node, ast.Assign)
        and isinstance(node.targets[0], ast.Name)
        and node.targets[0].id == "_COLUMNS"
    )
    migrated = set(declared) | {"delegation_depth"}
    # parent_run_id predates this revision (20261022_agent_spawn_lineage).
    assert migrated == set(LINEAGE_COLUMNS) - {"parent_run_id"}
    assert re.search(r'down_revision = "20261027_attribution_model_validation_decisions"', _MIGRATION.read_text())


def test_legacy_producer_without_lineage_context_still_projects():
    row = _project(_event())
    assert row["agent_id"] == "agent-1"
    assert row["task_id"] == "task-1"
    assert row["source_run_id"] is None
    assert row["canonical_run_id"] is None
    assert row["reported_principal_ref"] is None
    assert row["canonical_principal_entity_id"] is None
    assert row["principal_resolution_status"] is None
    assert row["authority_type"] is None and row["authority_ref"] is None
    assert row["control_mode"] == "UNKNOWN"
    assert row["delegation_depth"] is None
    assert row["execution_verification_state"] == "source_reported"


def test_trace_id_is_never_promoted_to_source_or_canonical_run():
    row = _project(_event(context={"correlation": {"traceId": "trace-only", "spanId": "s1", "parentSpanId": "s0"}}))
    # Legacy columns keep their documented trace fallback for existing readers.
    assert row["run_id"] == "trace-only"
    assert row["run_correlation_source"] == "trace_id"
    # Canonical lineage columns do not.
    assert row["trace_id"] == "trace-only"
    assert row["source_run_id"] is None
    assert row["canonical_run_id"] is None
    assert row["span_id"] == "s1"
    assert row["parent_span_id"] == "s0"


def test_source_run_id_comes_only_from_a_real_run_reference_and_canonical_stays_null():
    row = _project(_event(
        properties={"runId": "run-9", "rootRunId": "run-1", "parentRunId": "run-5"},
        context={"correlation": {"traceId": "trace-9"}},
    ))
    assert row["source_run_id"] == "run-9"
    assert row["run_id"] == "run-9"
    assert row["run_correlation_source"] == "run_id"
    assert row["root_run_id"] == "run-1"
    assert row["parent_run_id"] == "run-5"
    assert row["canonical_run_id"] is None

    # A canonical id asserted by the producer is not trusted at projection.
    claimed = _project(_event(execution_context={"canonical_run_id": "forged-canonical"}))
    assert claimed["canonical_run_id"] is None


def test_reported_principal_is_a_claim_and_never_canonical():
    row = _project(_event(context={"beneficiaryActorId": "human-claimed"}))
    assert row["principal_id"] == "human-claimed"  # legacy column, unchanged
    assert row["reported_principal_ref"] == "human-claimed"
    assert row["canonical_principal_entity_id"] is None
    assert row["principal_resolution_status"] == "unresolved"

    forged = _project(_event(actor_context={
        "reported_principal_ref": "p-ref",
        "reported_principal_namespace": "vendor.runtime",
        "canonical_principal_entity_id": "entity-forged",
        "principal_resolution_status": "resolved",
        "principal": "ignored-because-reported-ref-wins",
    }))
    assert forged["reported_principal_ref"] == "p-ref"
    assert forged["reported_principal_namespace"] == "vendor.runtime"
    assert forged["canonical_principal_entity_id"] is None
    assert forged["principal_resolution_status"] == "unresolved"


def test_actor_roles_stay_distinct_and_never_collapse_into_actor_id():
    row = _project(_event(
        context={"actorId": "actor-ctx"},
        actor_context={
            "initiator": "agent-a1", "executor": "agent-a97234",
            "operator": "org-o4", "beneficiary": "human-h1",
        },
    ))
    assert row["actor_id"] == "actor-ctx"
    assert row["initiator_entity_id"] == "agent-a1"
    assert row["executor_entity_id"] == "agent-a97234"
    assert row["operator_entity_id"] == "org-o4"
    assert row["beneficiary_entity_id"] == "human-h1"
    # Roles are not principal attribution.
    assert row["reported_principal_ref"] is None
    assert row["canonical_principal_entity_id"] is None


@pytest.mark.parametrize("mode", lineage_vocab.CONTROL_MODES)
def test_control_mode_accepts_every_vocabulary_value(mode):
    assert _project(_event(execution_context={"control_mode": mode}))["control_mode"] == mode


@pytest.mark.parametrize("bad", ["human_direct", "AUTONOMOUS", "", None, 7, ["HUMAN_DIRECT"]])
def test_control_mode_outside_vocabulary_becomes_unknown(bad):
    assert _project(_event(execution_context={"control_mode": bad}))["control_mode"] == "UNKNOWN"


def test_authority_context_is_read_with_unknown_type_normalised():
    row = _project(_event(authority_context={"authority_type": "mandate", "mandate_ref": "mandate-1"}))
    assert (row["authority_type"], row["authority_ref"]) == ("mandate", "mandate-1")

    row = _project(_event(authority_context={"authority_type": "delegation", "authority_ref": "deleg-1"}))
    assert (row["authority_type"], row["authority_ref"]) == ("delegation", "deleg-1")

    row = _project(_event(authority_context={"authority_type": "made-up", "authority_ref": "x"}))
    assert row["authority_type"] == "unknown"


def test_lineage_blocks_are_read_from_context_and_camel_case():
    row = _project(_event(
        context={
            "tenantId": "tenant-a",
            "executionContext": {
                "agentDefinitionId": "def-1",
                "agentInstanceId": "inst-1",
                "sourceRunId": "run-camel",
                "delegationDepth": 3,
                "externalEffectRef": "effect-1",
                "controlMode": "AGENT_DELEGATED_TO_AGENT",
            },
            "protocol_context": {"protocol": "mcp", "protocol_version": "2025-06-18"},
        },
    ))
    assert row["agent_definition_id"] == "def-1"
    assert row["agent_instance_id"] == "inst-1"
    assert row["source_run_id"] == "run-camel"
    assert row["delegation_depth"] == 3
    assert row["external_effect_ref"] == "effect-1"
    assert row["control_mode"] == "AGENT_DELEGATED_TO_AGENT"
    assert row["protocol"] == "mcp"
    assert row["protocol_version"] == "2025-06-18"


def test_legacy_protocol_version_property_still_projects():
    row = _project(_event(properties={"protocolVersion": "2024-11-05", "protocol": "mcp"}))
    assert row["protocol_version"] == "2024-11-05"
    assert row["protocol"] == "mcp"


@pytest.mark.parametrize("bad", [-1, True, "3", 1.5, 10_001])
def test_delegation_depth_rejects_non_integer_or_unbounded_values(bad):
    assert _project(_event(execution_context={"delegation_depth": bad}))["delegation_depth"] is None


def test_verification_state_is_derived_not_producer_asserted():
    claimed = _project(_event(execution_context={"execution_verification_state": "attested"}))
    assert claimed["execution_verification_state"] == "source_reported"
    verified = _project(_event(validated_agent_deployment={"deploymentId": "d-1", "agentId": "registry-agent"}))
    assert verified["execution_verification_state"] == "deployment_verified"
    assert verified["agent_definition_id"] == "registry-agent"
    assert verified["deployment_id"] == "d-1"


def test_resolution_outputs_are_null_at_projection_time():
    row = _project(_event(
        actor_context={"canonical_principal_entity_id": "e-1"},
        execution_context={"canonical_run_id": "c-1"},
        properties={"parentAgentId": "p", "rootAgentId": "r", "childAgentId": "c"},
        type="agent_subagent_spawned",
    ))
    assert row["parent_agent_ref"] == "p" and row["root_agent_ref"] == "r"  # source claims kept
    for resolved in (
        "canonical_run_id", "canonical_principal_entity_id",
        "parent_agent_entity_id", "root_agent_entity_id",
    ):
        assert row[resolved] is None, resolved


def test_projection_is_deterministic_and_replay_safe():
    event = _event(
        properties={"runId": "run-1", "agentInstanceId": "inst-1", "parentRunId": "run-0"},
        context={
            "beneficiaryActorId": "human-1",
            "correlation": {"traceId": "t-1", "spanId": "s-1", "parentSpanId": "s-0"},
        },
        actor_context={"initiator": "a-1", "executor": "a-2"},
        authority_context={"authority_type": "delegation", "authority_ref": "deleg-1"},
        execution_context={"control_mode": "HUMAN_APPROVED_AGENT_EXECUTED", "delegation_depth": 2},
        protocol_context={"protocol": "a2a"},
    )
    before = copy.deepcopy(event)
    first = _project(event)
    second = _project(event)
    replay = _project(copy.deepcopy(event))
    assert first == second == replay
    assert event == before  # projection never mutates its input
    assert first["idempotency_key"] == "evt-1"
