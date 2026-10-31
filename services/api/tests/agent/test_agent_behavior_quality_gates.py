"""Quality gates for agent behavioral intelligence (WO-170–WO-175)."""
from __future__ import annotations

import json
import random
import time
from pathlib import Path

import pytest

from ingestion.silver.projectors.agent_execution_projector import AgentExecutionProjector
from intelligence.agent_behavior.activity import agent_journey
from intelligence.agent_behavior.decisions import project_decisions
from intelligence.agent_behavior.facts import normalize_rows
from intelligence.agent_behavior.model import build_behavior_model
from intelligence.agent_behavior.read_models import agent360_behavior
from shared.contracts_models.epistemic import EpistemicStatus

FIXTURE = json.loads((Path(__file__).resolve().parents[4] / "tests/fixtures/agent_behavior/golden_scenarios.json").read_text())
VALID_STATUS = EpistemicStatus.valid_values()


def project(events, tenant):
    rows = []
    for e in events:
        rows.extend(AgentExecutionProjector().project({**e, "tenantId": tenant}).rows)
    return rows


def scenario_rows(sid):
    s = next(x for x in FIXTURE["scenarios"] if x["id"] == sid)
    return project([{"messageId": ev["id"], "type": ev["type"], "timestamp": ev["at"],
                     "properties": {"agentId": ev["agent"], **ev["properties"]}} for ev in s["events"]],
                   FIXTURE["tenant_id"])


def walk(obj):
    if isinstance(obj, dict):
        yield obj
        for v in obj.values():
            yield from walk(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from walk(v)


# --- WO-170 contract: every emitted status is canonical ------------------------------

@pytest.mark.parametrize("sid", ["GS-A", "GS-B", "GS-C", "GS-D"])
def test_every_emitted_epistemic_status_is_canonical(sid):
    facts = normalize_rows(scenario_rows(sid), FIXTURE["tenant_id"])
    root = facts[0].agent_ref
    out = {"rm": agent360_behavior(facts, root), "dec": project_decisions(facts)}
    statuses = [d["epistemic_status"] for d in walk(out) if "epistemic_status" in d]
    assert statuses and set(statuses) <= VALID_STATUS
    for d in walk(out):
        if d.get("basis") in {"unknown", "not_observed", "not_applicable"} and "value" in d:
            assert d["value"] is None and d.get("reason"), d


# --- WO-171 replay / determinism --------------------------------------------------

@pytest.mark.parametrize("sid", ["GS-A", "GS-B", "GS-C", "GS-D"])
def test_rebuild_is_identical_under_reorder_and_redelivery(sid):
    rows = scenario_rows(sid)
    t = FIXTURE["tenant_id"]
    shuffled = rows[:] + rows[: len(rows) // 2]  # at-least-once redelivery
    random.Random(7).shuffle(shuffled)
    a, b = normalize_rows(rows, t), normalize_rows(shuffled, t)
    assert [f.event_id for f in a] == [f.event_id for f in b]
    root = a[0].agent_ref
    assert project_decisions(a) == project_decisions(b)
    assert build_behavior_model(a, root) == build_behavior_model(b, root)
    assert agent_journey(a, root) == agent_journey(b, root)


# --- WO-172 synthetic behavioral agents -----------------------------------------------

def synthetic_buyer(agent, n, p_cheapest, p_tool_fail, seed, prefix=""):
    rnd = random.Random(seed)
    events, i = [], 0
    for d in range(n):
        did = f"{agent}-d{d}"
        pick = "cheap" if rnd.random() < p_cheapest else "dear"
        status = "failed" if rnd.random() < p_tool_fail else "succeeded"
        for etype, props in (
            ("agent_decision_started", {}),
            ("agent_tool_invocation_observed", {"toolName": "catalog", "status": status}),
            ("agent_candidate_considered", {"candidateId": f"{did}-cheap", "amount": "10"}),
            ("agent_candidate_considered", {"candidateId": f"{did}-dear", "amount": "25"}),
            ("agent_action_selected", {"candidateId": f"{did}-{pick}"}),
            ("agent_decision_completed", {"candidateSetComplete": True, "outcome": "bought"}),
        ):
            i += 1
            events.append({"messageId": f"{prefix}{agent}-{i:05d}", "type": etype,
                           "timestamp": f"2026-10-{1 + i // 86400:02d}T{(i // 3600) % 24:02d}:{(i // 60) % 60:02d}:{i % 60:02d}Z",
                           "properties": {"agentId": agent, "decisionId": did, **props}})
    return events


@pytest.mark.parametrize("p_cheapest,p_fail", [(0.9, 0.1), (0.2, 0.5)])
def test_model_recovers_known_synthetic_behavior(p_cheapest, p_fail):
    events = synthetic_buyer("syn", 120, p_cheapest, p_fail, seed=11)
    facts = normalize_rows(project(events, "t-syn"), "t-syn")
    model = build_behavior_model(facts, "syn")
    pref = next(p for p in model["preferences"] if p["preference"] == "lowest_price")["rate"]
    lo, hi = pref["interval"]
    assert lo - 0.05 <= p_cheapest <= hi + 0.05
    tool = model["features"]["tool_success_rate"]
    assert tool["interval"][0] - 0.05 <= 1 - p_fail <= tool["interval"][1] + 0.05


# --- WO-173 multi-agent load ---------------------------------------------------------

def test_multi_agent_population_projects_within_budget():
    events = []
    for a in range(200):
        events += synthetic_buyer(f"ag{a:03d}", 8, 0.7, 0.2, seed=a)
    t0 = time.perf_counter()
    rows = project(events, "t-load")
    facts = normalize_rows(rows, "t-load")
    decisions = project_decisions(facts)["decisions"]
    models = [build_behavior_model(facts, f"ag{a:03d}") for a in range(0, 200, 20)]
    elapsed = time.perf_counter() - t0
    assert len(facts) == 200 * 8 * 6 and len(decisions) == 200 * 8
    assert all(m["evidence"]["decisions"] == 8 for m in models)
    assert elapsed < 30, f"projection took {elapsed:.1f}s"


# --- WO-174 partial observability ------------------------------------------------------

def test_missing_families_are_reported_not_imputed():
    events = synthetic_buyer("po", 10, 0.9, 0.0, seed=3)
    blind = [e for e in events if e["type"] not in {"agent_candidate_considered", "agent_decision_started",
                                                   "agent_decision_completed"}]
    facts = normalize_rows(project(blind, "t-po"), "t-po")
    model = build_behavior_model(facts, "po")
    assert model["preferences"] == [], "no preference without observed alternatives"
    for d in project_decisions(facts)["decisions"]:
        assert "candidate_set" in d["missing"]
        assert d["opportunity"]["preference_inference"] == "not_applicable"
    assert "memory" in model["what_aether_cannot_see"]


# --- WO-175 tenant isolation ---------------------------------------------------------

def test_tenant_isolation_across_every_projection():
    a = project(synthetic_buyer("shared-ref", 6, 1.0, 0.0, seed=1), "tenant-a")
    b = project(synthetic_buyer("shared-ref", 6, 0.0, 1.0, seed=2, prefix="b-"), "tenant-b")
    mixed = a + b
    fa, fb = normalize_rows(mixed, "tenant-a"), normalize_rows(mixed, "tenant-b")
    assert {f.tenant_id for f in fa} == {"tenant-a"} and {f.tenant_id for f in fb} == {"tenant-b"}
    ma, mb = build_behavior_model(fa, "shared-ref"), build_behavior_model(fb, "shared-ref")
    assert ma["evidence"]["facts"] == mb["evidence"]["facts"] == 36
    ids_a = {e for d in walk(agent360_behavior(fa, "shared-ref")) for e in d.get("evidence", []) if isinstance(e, str)}
    ids_b = {f.event_id for f in fb}
    assert not ids_a & ids_b
