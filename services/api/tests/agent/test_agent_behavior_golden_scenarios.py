"""Golden scenarios for Agent Behavioral Intelligence (WO-002).

``tests/fixtures/agent_behavior/golden_scenarios.json`` defines what "working"
means for GS-A (cross-device human -> agent), GS-B (risk fleet), GS-C
(constrained non-action) and GS-D (failure adaptation). Each expectation is
either ``current`` -- asserted here against today's code -- or ``pending`` with
the work order that must make it current. When a work order lands, it flips its
expectations to current and extends this test; it does not write a new fixture.

Events go through the real Silver projector, the pure lineage and
fleet-hypothesis builders, the Silver graph projector (with the gateway call
captured) and the journey handoff service. Nothing that computes a result is
stubbed.
"""
from __future__ import annotations

import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

import pytest

from actions.agent.lineage import build_lineage_tree
from ingestion.silver.projectors import silver_graph_projector as sgp
from ingestion.silver.projectors.agent_execution_projector import AgentExecutionProjector
from intelligence.fraud_networks.fleet_hypothesis import (
    build_fleet_hypothesis,
    observations_from_rows,
)
from shared.graph.graph import EdgeType

REPO_ROOT = Path(__file__).resolve().parents[4]
FIXTURE = REPO_ROOT / "tests/fixtures/agent_behavior/golden_scenarios.json"
EVENT_REGISTRY = REPO_ROOT / "packages/shared/contracts/event-registry.json"
WORK_ORDER = re.compile(r"^WO-\d{3}$")
REQUIRED_KEYS = {
    "id", "title", "narrative", "handoff", "principals", "delegations",
    "risk_flagged_agents", "events", "expected", "known_gaps",
}
# Every scenario must say where its decision, journey and read model stand.
REQUIRED_EXPECTATIONS = {"lineage", "graph_edges", "decision_envelope", "agent_journey", "read_model"}

DOC = json.loads(FIXTURE.read_text())
TENANT = DOC["tenant_id"]
SCENARIOS = {s["id"]: s for s in DOC["scenarios"]}


def _project(scenario: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    projector = AgentExecutionProjector()
    for ev in scenario["events"]:
        result = projector.project({
            "messageId": ev["id"],
            "type": ev["type"],
            "tenantId": TENANT,
            "timestamp": ev["at"],
            "properties": {"agentId": ev["agent"], **ev["properties"]},
        })
        assert result is not None, f"{ev['type']} is not projected to Silver"
        assert result.table == "silver_agent_execution_facts"
        rows.extend(result.rows)
    return rows


def _lineage(scenario: dict[str, Any], rows: list[dict[str, Any]]) -> dict[str, Any]:
    activity: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        activity[row["agent_id"]].append(row)
    return build_lineage_tree(
        tenant_id=TENANT,
        root_agent_ref=scenario["expected"]["lineage"]["root"],
        spawn_rows=rows,
        activity_rows=dict(activity),
    )


def _pending_blocks(expected: dict[str, Any]):
    for key, value in expected.items():
        if isinstance(value, dict) and value.get("status") == "pending":
            yield key, value
    for edge in expected.get("graph_edges", []):
        if edge["status"] == "pending":
            yield f"graph_edge:{edge['type']}", edge


# --- fixture integrity -------------------------------------------------------

def test_fixture_covers_the_four_golden_scenarios():
    assert DOC["schema_version"] == "1.0.0"
    assert list(SCENARIOS) == ["GS-A", "GS-B", "GS-C", "GS-D"]


@pytest.mark.parametrize("sid", list(SCENARIOS))
def test_scenario_shape_and_deterministic_ids(sid):
    scenario = SCENARIOS[sid]
    assert REQUIRED_KEYS <= set(scenario)
    assert REQUIRED_EXPECTATIONS <= set(scenario["expected"])
    prefix = sid.lower().replace("-", "")
    ids = [ev["id"] for ev in scenario["events"]]
    assert ids == [f"{prefix}-evt-{i:04d}" for i in range(1, len(ids) + 1)]
    times = [ev["at"] for ev in scenario["events"]]
    assert times == sorted(times), "events must be listed in occurrence order"


def test_event_ids_are_unique_across_scenarios():
    ids = [ev["id"] for s in DOC["scenarios"] for ev in s["events"]]
    assert len(ids) == len(set(ids))


@pytest.mark.parametrize("sid", list(SCENARIOS))
def test_pending_expectations_name_their_work_order(sid):
    pending = list(_pending_blocks(SCENARIOS[sid]["expected"]))
    assert pending, "a scenario with nothing pending should drop its pending blocks"
    for name, block in pending:
        assert WORK_ORDER.match(block.get("owner_work_order", "")), name


@pytest.mark.parametrize("sid", list(SCENARIOS))
def test_evidence_references_resolve_to_scenario_events(sid):
    scenario = SCENARIOS[sid]
    ids = {ev["id"] for ev in scenario["events"]}
    refs: list[str] = []
    for edge in scenario["expected"]["graph_edges"]:
        refs.extend(edge["evidence_event_ids"])
    for child in scenario["expected"]["lineage"]["children"].values():
        refs.append(child["spawn_event_id"])
    for key in ("tool_results", "policy_decisions", "economic_attempts"):
        refs.extend(item["event_id"] for item in scenario["expected"].get(key, []))
    assert refs and set(refs) <= ids


def test_every_event_type_is_a_registered_agent_event():
    registry = {e["type"]: e for e in json.loads(EVENT_REGISTRY.read_text())["events"]}
    handled = AgentExecutionProjector.handles
    for scenario in DOC["scenarios"]:
        for ev in scenario["events"]:
            assert ev["type"] in registry, f"{ev['type']} missing from event-registry.json"
            assert registry[ev["type"]]["status"] == "active", ev["type"]
            assert ev["type"] in handled, f"{ev['type']} is not handled by the agent projector"
        for forbidden in scenario["expected"].get("forbidden_event_types", []):
            assert forbidden in registry, f"forbidden type {forbidden} is not a real event type"


def test_every_expected_graph_edge_type_exists():
    known = {v for k, v in vars(EdgeType).items() if k.isupper() and isinstance(v, str)}
    for scenario in DOC["scenarios"]:
        for edge in scenario["expected"]["graph_edges"]:
            assert edge["type"] in known, edge["type"]
            assert edge["epistemic_status"] in {"observed", "inferred", "derived"}


# --- current behavior --------------------------------------------------------

@pytest.mark.parametrize("sid", list(SCENARIOS))
def test_lineage_matches_expected(sid):
    scenario = SCENARIOS[sid]
    want = scenario["expected"]["lineage"]
    got = _lineage(scenario, _project(scenario))

    assert got["evidence_status"] == want["evidence_status"]
    assert got["attribution"] == want["attribution"]
    assert got["truncated"] == want["truncated"]
    for key in ("agent_count", "max_depth", "tool_call_count"):
        assert got["totals"][key] == want[key], key

    kids = {node["agent_ref"]: node for node in got["tree"]["children"]}
    assert set(kids) == set(want["children"])
    for ref, child in want["children"].items():
        node = kids[ref]
        assert node["spawned_by"]["source_event_id"] == child["spawn_event_id"]
        assert node["spawned_by"]["evidence_status"] == "source_reported"
        tools = {t["tool_name"]: t["calls"] for t in node["activity"]["tools"]}
        assert tools == child["tools"]
        if "outcomes" in child:
            assert node["activity"]["outcomes"] == child["outcomes"]

    root_activity = got["tree"]["activity"]
    if "root_outcomes" in want:
        assert root_activity["outcomes"] == want["root_outcomes"]
    if "root_tools" in want:
        assert {t["tool_name"]: t["calls"] for t in root_activity["tools"]} == want["root_tools"]


@pytest.mark.parametrize("sid", [s for s in SCENARIOS if "tool_results" in SCENARIOS[s]["expected"]])
def test_tool_results_are_captured_in_silver(sid):
    scenario = SCENARIOS[sid]
    rows = {r["source_event_id"]: r for r in _project(scenario)}
    for item in scenario["expected"]["tool_results"]:
        row = rows[item["event_id"]]
        assert (row["agent_id"], row["tool_name"], row["status"]) == (
            item["agent"], item["tool"], item["status"],
        )


def test_gs_c_policy_denial_is_recorded_and_nothing_executes():
    scenario = SCENARIOS["GS-C"]
    rows = {r["source_event_id"]: r for r in _project(scenario)}
    for item in scenario["expected"]["policy_decisions"]:
        row = rows[item["event_id"]]
        assert row["policy_id"] == item["policy_id"]
        assert row["policy_decision"] == item["policy_decision"]
        assert row["action_type"] == item["action_type"]
        assert row["policy_reason_codes"] == item["reason_codes"]
    emitted = {ev["type"] for ev in scenario["events"]}
    assert not emitted & set(scenario["expected"]["forbidden_event_types"])


def test_gs_b_economic_attempt_is_a_silver_fact():
    scenario = SCENARIOS["GS-B"]
    rows = {r["source_event_id"]: r for r in _project(scenario)}
    for item in scenario["expected"]["economic_attempts"]:
        row = rows[item["event_id"]]
        assert row["agent_id"] == item["agent"] and row["status"] == item["status"]


@pytest.mark.parametrize("sid", [s for s in SCENARIOS if "fleet_hypothesis" in SCENARIOS[s]["expected"]])
def test_fleet_hypothesis_stays_evidence_qualified(sid):
    scenario = SCENARIOS[sid]
    want = scenario["expected"]["fleet_hypothesis"]
    rows = _project(scenario)
    lineage = _lineage(scenario, rows)
    members = [lineage["root_agent_ref"]] + [n["agent_ref"] for n in lineage["tree"]["children"]]
    hyp = build_fleet_hypothesis(
        tenant_id=TENANT,
        root_agent_ref=lineage["root_agent_ref"],
        member_refs=members,
        observations=observations_from_rows(rows, TENANT, members),
        principal_entity_ids=[d["grantor"] for d in scenario["delegations"]],
        risk_flagged_refs=set(scenario["risk_flagged_agents"]),
    )
    assert hyp is not None
    assert hyp["member_count"] == want["member_count"]
    assert hyp["status"] == want["status"]
    assert hyp["priority"] == want["priority"]
    assert hyp["person_link"]["principal_entity_ids"] == want["principal_entity_ids"]
    assert hyp["person_link"]["claim"] == want["person_link_claim"]
    if "max_confidence" in want:
        assert hyp["confidence"] <= want["max_confidence"]
    if "flagged_agent_refs" in want:
        assert hyp["risk_context"]["flagged_agent_refs"] == want["flagged_agent_refs"]
    if "evidence_types_include" in want:
        assert set(want["evidence_types_include"]) <= {e["type"] for e in hyp["evidence"]}
    if "competing_explanations_include" in want:
        ids = {c["id"] for c in hyp["competing_explanations"]}
        assert set(want["competing_explanations_include"]) <= ids
    if "never_status" in want:
        assert hyp["status"] != want["never_status"]


@pytest.mark.asyncio
@pytest.mark.parametrize("sid", list(SCENARIOS))
async def test_current_graph_edges_match_emission(sid, monkeypatch):
    """Only edges marked ``current`` are emitted today; pending ones must not be."""
    scenario = SCENARIOS[sid]
    edges: dict[tuple[str, str, str], list[str]] = defaultdict(list)

    async def capture_edge(edge, *, subject_id=""):
        edges[(edge.edge_type, edge.from_vertex_id, edge.to_vertex_id)].append(
            edge.properties["source_event_id"]
        )

    async def ignore_vertex(vertex, *, tenant_id):
        return None

    async def no_run_projection(self, row, tenant_id, source_event_id):
        return None

    monkeypatch.setattr(sgp, "_emit", capture_edge)
    monkeypatch.setattr(sgp, "_emit_vertex", ignore_vertex)
    monkeypatch.setattr(sgp.SilverGraphProjector, "_emit_external_agent_run", no_run_projection)

    projector = AgentExecutionProjector()
    graph = sgp.SilverGraphProjector()
    for ev in scenario["events"]:
        event = {
            "messageId": ev["id"], "type": ev["type"], "tenantId": TENANT,
            "timestamp": ev["at"], "properties": {"agentId": ev["agent"], **ev["properties"]},
        }
        await graph._emit_agent_execution(projector.project(event), event)

    expected = {
        (e["type"], e["from"], e["to"]): e["evidence_event_ids"]
        for e in scenario["expected"]["graph_edges"] if e["status"] == "current"
    }
    assert dict(edges) == expected
    for edge in scenario["expected"]["graph_edges"]:
        if edge["status"] == "pending":
            assert (edge["type"], edge["from"], edge["to"]) not in edges, (
                f"{edge['type']} is emitted now; mark it current and drop {edge['owner_work_order']}"
            )


@pytest.mark.asyncio
async def test_gs_a_mobile_to_web_handoff_is_explicit_and_does_not_merge():
    from journeys.handoff.service import issue_handoff, redeem_handoff
    from repositories import journey_handoff_repo

    journey_handoff_repo.reset_journey_handoff_memory()
    try:
        handoff = SCENARIOS["GS-A"]["handoff"]
        src, dst = handoff["source"], handoff["destination"]
        issued = await issue_handoff(
            tenant_id=TENANT, app_namespace="gs-app", journey_id=handoff["journey_id"],
            session_id=src["session_id"], anonymous_id=src["anonymous_id"], platform=src["platform"],
        )
        link, reason = await redeem_handoff(
            tenant_id=TENANT, app_namespace="gs-app", token=issued["token"],
            session_id=dst["session_id"], anonymous_id=dst["anonymous_id"], platform=dst["platform"],
        )
        assert reason == "" and link is not None
        assert link["journey_id"] == handoff["journey_id"]
        assert link["link_basis"] == handoff["expected"]["link_basis"]
        assert link["identity_merge"] == handoff["expected"]["identity_merge"]
        assert link["from"]["platform"] == src["platform"] and link["to"]["platform"] == dst["platform"]
    finally:
        journey_handoff_repo.reset_journey_handoff_memory()


@pytest.mark.asyncio
async def test_lineage_edge_cannot_be_planted_for_another_agent(monkeypatch):
    emitted = []

    async def capture_edge(edge, *, subject_id=""):
        emitted.append((edge.edge_type, edge.from_vertex_id, edge.to_vertex_id))

    async def noop(*a, **k):
        return None

    monkeypatch.setattr(sgp, "_emit", capture_edge)
    monkeypatch.setattr(sgp, "_emit_vertex", noop)
    monkeypatch.setattr(sgp.SilverGraphProjector, "_emit_external_agent_run", noop)
    event = {"messageId": "forge-1", "type": "agent_subagent_spawned", "tenantId": TENANT,
             "timestamp": "2026-10-22T10:00:00Z",
             "properties": {"agentId": "attacker", "parentAgentId": "victim-orch", "childAgentId": "x"}}
    await sgp.SilverGraphProjector()._emit_agent_execution(AgentExecutionProjector().project(event), event)
    assert emitted == []


@pytest.mark.parametrize("sid", [s for s in SCENARIOS
                                 if SCENARIOS[s]["expected"]["decision_envelope"]["status"] == "current"])
def test_current_decision_envelopes_match(sid):
    from intelligence.agent_behavior.decisions import build_envelope, group_decisions
    from intelligence.agent_behavior.facts import normalize_rows

    expected = SCENARIOS[sid]["expected"]
    design = expected["decision_envelope"]["design"]
    facts = normalize_rows(_project(SCENARIOS[sid]), TENANT)
    env = build_envelope(design["decision_id"], group_decisions(facts)[design["decision_id"]], facts).to_dict()
    assert env["decision_actor"]["value"] == design["decision_actor"]
    assert env["objective"]["value"] == design["objective_ref"]
    assert [c["candidate"] for c in env["candidates"]["candidates"]] == design["candidates"]
    assert [c["ref"] for c in env["constraints"]] == design["constraint_refs"]
    assert env["disposition"]["disposition"] == design["disposition"]
    assert design["authority_check_event_id"] in env["evidence"]
    assert env["outcome"]["evidence"] == [design["outcome_event_id"]]
    assert env["status"] == design["status"]
    for key in ("opportunity_envelope", "action_disposition"):
        if expected.get(key, {}).get("status") == "current":
            want = expected[key]["design"]
            got = env["opportunity"] if key == "opportunity_envelope" else env["disposition"]
            assert {k: got[k] for k in want} == want


def test_gs_d_failure_resolution_is_current():
    from intelligence.agent_behavior.activity import failure_resolution
    from intelligence.agent_behavior.facts import normalize_rows

    want = SCENARIOS["GS-D"]["expected"]["failure_resolution"]
    assert want["status"] == "current"
    [episode] = failure_resolution(normalize_rows(_project(SCENARIOS["GS-D"]), TENANT))
    design = want["design"]
    assert [{"tool": r["tool"], "event_id": r["event_id"]} for r in episode["retries"]] == design["retries"]
    assert [{k: s[k] for k in ("from_tool", "to_tool", "event_id")} for s in episode["switches"]] == design["switches"]
    assert episode["resolved"] is design["resolved"] and episode["basis"] == design["basis"]
