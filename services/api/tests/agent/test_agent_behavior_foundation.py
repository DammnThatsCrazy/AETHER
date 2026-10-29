"""Agent behavior foundation: actors, agent identity, taxonomy, facts (WO-010–WO-033)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from identity.identity.actor_ref import (
    ACTOR_TYPES, actor_ref, actor_ref_from_identifier, resolved_actor_ref,
)
from identity.identity.agent_identity import (
    KNOWN_AGENT, PROBABLE_AGENT, UNKNOWN_AUTOMATED_ACTOR, UNKNOWN_ACTOR,
    agent_continuity, agent_identity, agent_identity_claims, classify_relationship,
    continuity_hypotheses,
)
from ingestion.ingestion.validation import scrub_sensitive_fields
from ingestion.silver.projectors.agent_execution_projector import AgentExecutionProjector
from intelligence.agent_behavior import contracts as c
from intelligence.agent_behavior.facts import fact_from_row, normalize_rows, watermark
from intelligence.agent_behavior.taxonomy import (
    ADAPTER_CLASSES, ADAPTERS, DOTTED_TO_CANONICAL, AdapterError, map_runtime_record,
)

REPO = Path(__file__).resolve().parents[4]
REGISTRY = {e["type"]: e for e in json.loads(
    (REPO / "packages/shared/contracts/event-registry.json").read_text())["events"]}
T = "tenant-f"


def row(event_type, agent="a1", at="2026-10-22T10:00:00Z", eid=None, **props):
    eid = eid or f"e-{event_type}-{at}"
    result = AgentExecutionProjector().project({
        "messageId": eid, "type": event_type, "tenantId": T, "timestamp": at,
        "properties": {"agentId": agent, **props},
    })
    assert result is not None, event_type
    return result.rows[0]


# --- claims (INV-002, INV-010) ------------------------------------------------

def test_claim_rules():
    assert c.observed("x", ["e1"]).epistemic_status == "observed"
    assert c.not_observed("outside telemetry").epistemic_status == "unavailable"
    assert c.declared("y", ["e2"]).to_dict()["basis"] == "declared"
    with pytest.raises(ValueError):
        c.Claim("x", c.OBSERVED)  # observed without evidence
    with pytest.raises(ValueError):
        c.Claim(None, c.UNKNOWN)  # absent without a reason
    with pytest.raises(ValueError):
        c.Claim("x", c.UNKNOWN, reason="r")  # absent with a value
    assert c.weakest(c.OBSERVED, c.INFERRED) == c.INFERRED
    assert c.weakest(c.UNKNOWN) == c.UNKNOWN


# --- ActorRef (WO-010) --------------------------------------------------------

def test_actor_ref_is_deterministic_tenant_and_namespace_scoped():
    a = actor_ref(T, "agent", "orch", namespace="deployment:d1")
    assert a.actor_id == actor_ref(T, "agent", "orch", namespace="deployment:d1").actor_id
    assert a.actor_id != actor_ref(T, "agent", "orch", namespace="deployment:d2").actor_id
    assert a.actor_id != actor_ref("other", "agent", "orch", namespace="deployment:d1").actor_id
    assert actor_ref_from_identifier(T, "wallet_address", "0xabc", namespace="sdk").actor_type == "unknown"
    assert actor_ref_from_identifier(T, "agent_id", "x", namespace="sdk").actor_type == "agent"
    assert resolved_actor_ref(T, "ent-1", "human").basis == "resolved"
    with pytest.raises(ValueError):
        actor_ref(T, "robot", "x", namespace="n")
    assert set(ACTOR_TYPES) == {"human", "agent", "organization", "service", "protocol", "device", "unknown"}


# --- agent identity (WO-011–WO-013) ---------------------------------------------

def _facts(*rows):
    return normalize_rows(list(rows), T)


def test_recognition_states_do_not_overclaim():
    spawn = row("agent_subagent_spawned", "orch", parentAgentId="orch", childAgentId="w1", runId="r")
    tool = row("agent_tool_invocation_observed", "w1", at="2026-10-22T10:00:01Z", toolName="t", runId="r1",
               modelId="vendor-model-x")
    facts = _facts(spawn, tool)
    worker = agent_identity(tenant_id=T, agent_ref="w1", facts=facts)
    assert worker.recognition == PROBABLE_AGENT
    assert worker.parent_agent_id == "orch" and worker.agent_class == "worker"
    assert worker.model_family == "vendor-model-x"
    assert worker.provenance["model_basis"] == "source_reported"
    orch = agent_identity(tenant_id=T, agent_ref="orch", facts=facts)
    assert orch.agent_class == "orchestrator"
    known = agent_identity(tenant_id=T, agent_ref="w1", facts=facts, canonical_agent_entity_id="ag-1")
    assert known.recognition == KNOWN_AGENT and known.actor.basis == "resolved"
    anon = agent_identity(tenant_id=T, agent_ref=None, facts=_facts(
        row("agent_tool_invocation_observed", agent=None, toolName="t")))
    assert anon.recognition == UNKNOWN_AUTOMATED_ACTOR
    assert agent_identity(tenant_id=T, agent_ref=None, facts=[]).recognition == UNKNOWN_ACTOR


def test_continuity_separates_model_runtime_and_declared_relations():
    facts = _facts(
        row("agent_task_started", "a1", at="2026-10-22T10:00:00Z", runId="r1", modelId="m1"),
        row("agent_task_started", "a1", at="2026-10-22T11:00:00Z", runId="r2", modelId="m2"),
        row("agent_registered", "a2", at="2026-10-22T12:00:00Z", continuityRelation="clone", fromAgentId="a1"),
        row("agent_terminated", "a1", at="2026-10-22T13:00:00Z"),
    )
    a1 = agent_continuity(tenant_id=T, agent_ref="a1", facts=facts)
    assert [v["model_id"] for v in a1["configuration_versions"]] == ["m1", "m2"]
    assert a1["model_changed"] is True
    assert {i["run_id"] for i in a1["runtime_instances"]} == {"r1", "r2"}
    assert a1["relations"][-1]["relation"] == "terminated"
    a2 = agent_continuity(tenant_id=T, agent_ref="a2", facts=facts)
    assert a2["relations"][0]["basis"] == "declared"
    assert classify_relationship(a1, a2) == "cloned"
    assert classify_relationship(a1, a1) == "same_agent_new_model"
    assert classify_relationship(a1, agent_continuity(tenant_id=T, agent_ref="zz", facts=facts)) == "unrelated"


def test_identity_claims_are_never_merge_eligible_and_ambiguity_goes_to_review():
    r1 = row("agent_task_started", "shared", eid="x1")
    r1["deployment_id"] = "dep-a"
    r2 = row("agent_task_started", "shared", eid="x2", at="2026-10-22T10:00:05Z")
    facts = _facts(r1, r2)
    claims = agent_identity_claims(T, facts)
    assert {cl["source_namespace"] for cl in claims} == {"deployment:dep-a", "source_reported"}
    assert all(cl["merge_eligible"] is False for cl in claims)
    review = continuity_hypotheses(T, facts)
    assert review and review[0]["review_state"] == "needs_review"
    assert review[0]["fact_status"] == "not_a_fact_until_reviewed"


# --- taxonomy and adapters (WO-030, WO-031) ------------------------------------

def test_every_design_event_maps_to_an_active_registered_and_projected_type():
    handled = AgentExecutionProjector.handles
    for dotted, (event_type, _) in DOTTED_TO_CANONICAL.items():
        assert REGISTRY[event_type]["status"] == "active", dotted
        assert REGISTRY[event_type]["silverProjection"] == "agent_execution_facts", dotted
        assert event_type in handled, dotted
    families = {d.split(".")[1] for d in DOTTED_TO_CANONICAL}
    assert {"objective", "information", "decision", "authorization", "tool", "task",
            "execution", "transaction", "message", "memory"} <= families
    assert set(ADAPTERS) == set(ADAPTER_CLASSES)


def test_mcp_adapter_maps_without_inference_and_drops_content():
    base = {"id": "c1", "timestamp": "2026-10-22T10:00:00Z", "agentId": "a1",
            "method": "tools/call", "params": {"name": "search"}, "prompt": "secret plan"}
    [invoked] = map_runtime_record("mcp", base)
    assert invoked["type"] == "agent_tool_invocation_observed"
    assert invoked["properties"]["status"] == "invoked" and "prompt" not in invoked["properties"]
    [failed] = map_runtime_record("mcp", {**base, "error": {"code": -32000}})
    assert failed["properties"]["status"] == "failed"
    [ok] = map_runtime_record("mcp", {**base, "result": {"isError": False}})
    assert ok["properties"]["status"] == "succeeded"
    assert map_runtime_record("mcp", base)[0]["messageId"] == invoked["messageId"]
    with pytest.raises(AdapterError):
        map_runtime_record("mcp", {**base, "method": "resources/list"})


def test_wallet_and_generic_adapters():
    [quote] = map_runtime_record("wallet_payment", {"id": "w1", "timestamp": "t", "agentId": "a",
                                                     "state": "quoted", "amount": "10.5", "currency": "USDC"})
    assert quote["type"] == "agent_quote_received" and quote["properties"]["amount"] == "10.5"
    [gen] = map_runtime_record("generic_runtime", {"id": "g1", "timestamp": "t", "agentId": "a",
                                                   "event": "agent.objective.created",
                                                   "properties": {"objectiveId": "o1", "reasoning": "x"}})
    assert gen["type"] == "agent_objective_created" and "reasoning" not in gen["properties"]
    with pytest.raises(AdapterError):
        map_runtime_record("generic_runtime", {"id": "g1", "timestamp": "t", "event": "agent.x"})
    with pytest.raises(AdapterError):
        map_runtime_record("teleporter", {})


# --- Bronze secrets and Silver facts (WO-032, WO-033) --------------------------

def test_agent_payload_secrets_are_scrubbed_at_ingestion():
    props = {"toolName": "pay", "privateKey": "k", "apiKey": "x", "accessToken": "t",
             "nested": {"password": "p", "seedPhrase": "s"}, "authorizationId": "auth-1"}
    scrubbed, found = scrub_sensitive_fields(props)
    assert found
    for key in ("privateKey", "apiKey", "accessToken"):
        assert scrubbed[key] == "[REDACTED]"
    assert scrubbed["nested"] == {"password": "[REDACTED]", "seedPhrase": "[REDACTED]"}
    assert scrubbed["authorizationId"] == "auth-1"  # a reference, not a secret


def test_silver_projection_carries_behavior_references():
    r = row("agent_candidate_considered", objectiveId="o1", decisionId="d1", candidateId="sku-1",
            latencyMs=40, attempt="2", amount="12.50", currency="USD")
    assert (r["objective_ref"], r["decision_ref"], r["candidate_ref"]) == ("o1", "d1", "sku-1")
    assert (r["latency_ms"], r["attempt"], r["amount"], r["currency"]) == (40, 2, "12.50", "USD")
    bad = row("agent_quote_received", amount="1e999999999999", attempt=-1)
    assert bad["attempt"] is None
    assert row("agent_quote_received", amount="ten")["amount"] is None


def test_facts_fall_back_to_payload_and_are_tenant_ordered():
    legacy = {"source_event_id": "old", "source_event_type": "agent_memory_created", "tenant_id": T,
              "agent_id": "a", "occurred_at": "2026-10-22T09:00:00Z", "payload": {"memoryId": "m1"}}
    other = {**legacy, "source_event_id": "x", "tenant_id": "other"}
    newer = row("agent_memory_retrieved", memoryId="m1", at="2026-10-22T10:00:00Z")
    facts = normalize_rows([newer, other, legacy, legacy], T)
    assert [f.event_id for f in facts] == ["old", newer["source_event_id"]]
    assert facts[0].memory_ref == "m1"
    assert watermark(facts).endswith(newer["source_event_id"])
    assert fact_from_row({**legacy, "payload": None}).memory_ref is None
