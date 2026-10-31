"""Journeys, tools, information, memory, features and the behavior model (WO-060–WO-083)."""
from __future__ import annotations

from ingestion.silver.projectors.agent_execution_projector import AgentExecutionProjector
from intelligence.agent_behavior.activity import (
    agent_journey, failure_resolution, information_inputs, memory_lifecycle, tool_entities,
)
from intelligence.agent_behavior.facts import normalize_rows
from intelligence.agent_behavior.model import (
    MIN_SAMPLE, build_behavior_model, confidence_envelope, observability_envelope, wilson,
)

T = "tenant-model"


def facts(*events):
    rows = []
    for i, (etype, agent, props) in enumerate(events):
        rows.extend(AgentExecutionProjector().project({
            "messageId": f"m-{i:03d}", "type": etype, "tenantId": T,
            "timestamp": f"2026-10-22T{10 + i // 3600:02d}:{(i // 60) % 60:02d}:{i % 60:02d}Z",
            "properties": {"agentId": agent, **props},
        }).rows)
    return normalize_rows(rows, T)


def test_agent_journey_joins_human_journey_only_explicitly():
    fs = facts(
        ("agent_task_started", "orch", {"taskId": "t", "journeyId": "jrn-1"}),
        ("agent_subagent_spawned", "orch", {"parentAgentId": "orch", "childAgentId": "w"}),
        ("agent_tool_invocation_observed", "w", {"toolName": "search", "status": "succeeded"}),
        ("agent_task_completed", "orch", {"taskId": "t", "outcome": "completed"}),
    )
    j = agent_journey(fs, "orch", handoffs=[{"journey_id": "jrn-1", "link_basis": "explicit_handoff"}])
    assert [a["agent"] for a in j["agents"]] == ["orch", "w"]
    assert [s["kind"] for s in j["steps"]] == ["task", "delegation", "tool", "task"]
    assert j["human_journey"]["basis"] == "observed" and j["outcome"]["value"] == "completed"
    assert agent_journey(fs, "orch")["human_journey"]["basis"] == "declared"
    assert agent_journey(fs[1:], "orch")["human_journey"]["basis"] == "unknown"


def test_failure_resolution_derived_and_explicit():
    fs = facts(
        ("agent_tool_invocation_observed", "a", {"taskId": "t", "toolName": "A", "status": "failed", "latencyMs": 900}),
        ("agent_tool_invocation_observed", "a", {"taskId": "t", "toolName": "A", "status": "failed", "latencyMs": 800}),
        ("agent_tool_invocation_observed", "a", {"taskId": "t", "toolName": "B", "status": "succeeded", "latencyMs": 100}),
        ("agent_tool_invocation_observed", "a", {"taskId": "u", "toolName": "C", "status": "failed"}),
        ("agent_tool_switched", "a", {"taskId": "u", "toolName": "D", "fromToolName": "C"}),
    )
    eps = {e["task"]: e for e in failure_resolution(fs)}
    t = eps["t"]
    assert t["resolved"] and t["resolution"] == {"tool": "B", "event_id": fs[2].event_id, "strategy": "switch"}
    assert [r["basis"] for r in t["retries"]] == ["derived"]
    assert t["switches"][0]["from_tool"] == "A" and t["switches"][0]["to_tool"] == "B"
    assert eps["u"]["switches"][0]["basis"] == "observed" and not eps["u"]["resolved"]
    tools = {x["tool"]: x for x in tool_entities(fs)}
    assert tools["A"]["success_rate"] == 0.0 and tools["B"]["success_rate"] == 1.0
    assert tools["A"]["latency_p50_ms"] == 850


def test_information_and_memory_are_references_with_anomalies():
    fs = facts(
        ("agent_source_consulted", "a", {"sourceRef": "web:reviews", "decisionId": "d1"}),
        ("agent_execution_failed", "a", {"decisionId": "d1"}),
        ("agent_information_retrieved", "a", {"sourceRef": "web:reviews"}),
        ("agent_memory_created", "a", {"memoryId": "m1"}),
        ("agent_memory_retrieved", "a", {"memoryId": "m1"}),
        ("agent_memory_invalidated", "a", {"memoryId": "m1"}),
        ("agent_memory_retrieved", "a", {"memoryId": "m1"}),
        ("agent_memory_updated", "a", {"memoryId": "m2"}),
    )
    info = information_inputs(fs)
    src = info["sources"][0]
    assert src["uses"] == 2 and src["decisions_with_failure"] == ["d1"]
    assert "not a causal claim" in src["failure_association"]["reason"]
    assert info["inputs_without_decision"] == 1
    mem = {m["memory_ref"]: m for m in memory_lifecycle(fs)}
    assert mem["m1"]["state"] == "invalidated" and mem["m1"]["retrievals"] == 2
    assert mem["m1"]["anomalies"][0]["reason"] == "retrieved_after_invalidated"
    assert mem["m2"]["anomalies"][0]["reason"] == "used_before_creation_observed"


def test_confidence_withholds_small_samples():
    assert confidence_envelope(2, 3)["value"] is None
    assert confidence_envelope(2, 3)["sufficiency"] == "insufficient_evidence"
    env = confidence_envelope(8, 10)
    assert env["value"] == 0.8 and env["interval"][0] < 0.8 < env["interval"][1]
    assert wilson(0, 0) == (None, None)


def test_behavior_model_answers_gate_c_questions_and_is_rebuildable():
    events = []
    for i in range(6):
        d = f"d{i}"
        events += [
            ("agent_decision_started", "buyer", {"decisionId": d}),
            ("agent_candidate_considered", "buyer", {"decisionId": d, "candidateId": f"cheap-{i}", "amount": "10", "vendor": "acme"}),
            ("agent_candidate_considered", "buyer", {"decisionId": d, "candidateId": f"dear-{i}", "amount": "30", "vendor": "zeta"}),
            ("agent_tool_invocation_observed", "buyer", {"decisionId": d, "toolName": "search", "status": "succeeded"}),
            ("agent_action_selected", "buyer", {"decisionId": d, "candidateId": f"cheap-{i}", "actionType": "purchase"}),
            ("agent_decision_completed", "buyer", {"decisionId": d, "outcome": "purchased", "candidateSetComplete": True}),
        ]
    fs = facts(*events)
    m = build_behavior_model(fs, "buyer")
    assert m["what_it_usually_does"]["usual_disposition"] == "selected_action"
    assert m["what_it_usually_does"]["top_tools"][0]["tool"] == "search"
    prefs = {p["preference"]: p for p in m["preferences"]}
    assert prefs["lowest_price"]["rate"]["value"] == 1.0 and prefs["lowest_price"]["basis"] == "inferred"
    assert prefs["vendor:acme"]["rate"]["n"] == 6
    assert "memory" in m["what_aether_cannot_see"] and "chain_of_thought" in m["what_aether_cannot_see"]
    assert m["features"]["tool_success_rate"]["value"] == 1.0
    assert m["capabilities"][0]["status"] == "demonstrated"
    assert build_behavior_model(list(reversed(fs)), "buyer") == m
    assert m["model"]["input_count"] == len(fs) and m["evidence"]["decisions"] == 6


def test_observability_and_sparse_agents():
    fs = facts(("agent_tool_invocation_observed", "x", {"toolName": "t", "status": "succeeded"}))
    obs = observability_envelope(fs)
    assert obs["observed_families"] == ["tool"] and "decision" in obs["not_observed_families"]
    m = build_behavior_model(fs, "x")
    assert m["features"]["tool_success_rate"]["n"] == 1 < MIN_SAMPLE
    assert m["features"]["tool_success_rate"]["value"] is None
    assert m["preferences"] == []
    assert build_behavior_model([], "ghost")["what_it_usually_does"]["basis"] == "unknown"
