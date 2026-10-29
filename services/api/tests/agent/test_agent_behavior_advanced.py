"""Attribution, Value/Risk/Trust, drift, counterfactuals, population and adversarial
intelligence (WO-090–WO-103, WO-140–WO-161)."""
from __future__ import annotations

import json
from pathlib import Path

from ingestion.silver.projectors.agent_execution_projector import AgentExecutionProjector
from intelligence.agent_behavior.decisions import project_decisions
from intelligence.agent_behavior.dynamics import (
    adaptation, counterfactual_without_constraint, decision_attribution, detect_drift, influence_graph, snapshot,
)
from intelligence.agent_behavior.facts import normalize_rows
from intelligence.agent_behavior.model import build_behavior_model
from intelligence.agent_behavior.population import (
    adversarial_signals, behavioral_syndicates, contagion, demand_graph, identity_discontinuity,
    market_compatibility, strategic_episodes, swarm_episodes,
)
from intelligence.agent_behavior.responsibility import infer_influence
from intelligence.risk360.agent_behavior_signals import (
    signals_from_adversarial, signals_from_authority_checks, signals_from_behavior_model, signals_from_drift,
)
from intelligence.risk360.agent_trust import reputation_profile, trust_profile
from value.attribution.agent_behavior_value import attribute

T = "tenant-adv"
FIXTURE = json.loads((Path(__file__).resolve().parents[4] / "tests/fixtures/agent_behavior/golden_scenarios.json").read_text())


def facts(*events, tenant=T, base="2026-10-22T10"):
    rows = []
    for i, (etype, agent, props) in enumerate(events):
        rows.extend(AgentExecutionProjector().project({
            "messageId": f"x-{i:04d}", "type": etype, "tenantId": tenant,
            "timestamp": f"{base}:{(i // 60) % 60:02d}:{i % 60:02d}Z",
            "properties": {"agentId": agent, **props},
        }).rows)
    return normalize_rows(rows, tenant)


def scenario_facts(sid):
    s = next(x for x in FIXTURE["scenarios"] if x["id"] == sid)
    rows = []
    for ev in s["events"]:
        rows.extend(AgentExecutionProjector().project({
            "messageId": ev["id"], "type": ev["type"], "tenantId": FIXTURE["tenant_id"], "timestamp": ev["at"],
            "properties": {"agentId": ev["agent"], **ev["properties"]}}).rows)
    return normalize_rows(rows, FIXTURE["tenant_id"])


def _shop(i, pick="cheap", deny=False):
    d = f"d{i}"
    ev = [
        ("agent_source_consulted", "buyer", {"decisionId": d, "sourceRef": "web:reviews"}),
        ("agent_candidate_considered", "buyer", {"decisionId": d, "candidateId": f"cheap-{i}", "amount": "10"}),
        ("agent_candidate_considered", "buyer", {"decisionId": d, "candidateId": f"dear-{i}", "amount": "30"}),
    ]
    if deny:
        ev.append(("agent_policy_evaluated", "buyer", {"decisionId": d, "decision": "deny", "policyId": "p"}))
    else:
        ev += [("agent_action_selected", "buyer", {"decisionId": d, "candidateId": f"{pick}-{i}", "recommendedBy": "advisor"}),
               ("agent_decision_completed", "buyer", {"decisionId": d, "candidateSetComplete": True, "outcome": "ok"})]
    return ev


def test_decision_attribution_is_association_not_cause():
    fs = facts(*_shop(0))
    [env] = project_decisions(fs)["decisions"]
    att = decision_attribution(env, fs)
    kinds = {f["factor"]: f for f in att["factors"]}
    assert att["attribution_type"] == "evidence_association"
    assert kinds["information_consulted"]["detail"] == "web:reviews"
    assert kinds["recommendation"]["basis"] == "declared"
    assert kinds["price_position"]["detail"] == "lowest_permitted_price"


def test_influence_graph_mixes_states_and_finds_cycles():
    fs = facts(("agent_subagent_spawned", "a", {"parentAgentId": "a", "childAgentId": "b"}),
               ("agent_delegated_task", "b", {"delegatedToAgentId": "a"}))
    g = influence_graph(fs, [infer_influence("c", "a", {"shared_egress": ["x"]})])
    assert g["by_state"] == {"observed": 2, "declared": 0, "inferred": 1}
    assert ["a", "b"] in g["cycles"]


def test_value_classes_and_finality_never_blend_currencies():
    roles_agent = {"decision_actor": {"value": "buyer"}, "execution_actor": {"value": "buyer"}}
    roles_human_sel = {"decision_actor": {"value": "person"}, "execution_actor": {"value": "buyer"}}
    roles_infl = {"decision_actor": {"value": "person"}, "execution_actor": {"value": "person"},
                  "influencing_actor": {"value": "buyer"}}
    out = attribute([
        {"event_id": "e1", "amount": "10.10", "currency": "USD", "roles": roles_agent},
        {"event_id": "e2", "amount": "0.20", "currency": "USD", "roles": roles_agent},
        {"event_id": "e3", "amount": "5", "currency": "EUR", "roles": roles_human_sel},
        {"event_id": "e4", "amount": "1", "currency": "USD", "roles": roles_infl},
    ], agent_refs={"buyer"}, confirmed_settlements={"e1"})
    totals = {(t["class"], t["currency"], t["finality"]): t["amount"] for t in out["totals"]}
    assert totals[("agent_selected_and_executed", "USD", "confirmed")] == "10.10"
    assert totals[("agent_selected_and_executed", "USD", "reported")] == "0.20"
    assert totals[("agent_executed_human_selected", "EUR", "reported")] == "5"
    assert totals[("agent_influenced", "USD", "reported")] == "1"


def test_risk_signals_trust_and_reputation_stay_separate():
    fs = facts(*[e for i in range(6) for e in _shop(i, deny=True)])
    model = build_behavior_model(fs, "buyer")
    sigs = signals_from_behavior_model(T, model)
    assert any(s.source == "agent_behavior.repeated_authority_denials" for s in sigs)
    assert all(s.score is None and s.subject_kind == "agent" for s in sigs)
    assert signals_from_authority_checks(T, "buyer", [{"status": "outside", "evidence": ["e"]},
                                                       {"status": "inside"}])[0].claim_state.value == "observed"
    trust = trust_profile(model, [{"status": "outside"}, {"status": "inside"}])
    assert trust["authority_compliance"]["rate"] == 0.5 and "reputation" in trust["not"]
    rep = reputation_profile("buyer", [{"source": "store", "rating": 4}, {"source": "store", "rating": 2}])
    assert rep["sources"][0]["mean_rating"] == 3.0 and rep["kind"] == "reputation"


def test_drift_needs_interval_separation_and_names_config_changes():
    good = facts(*[("agent_tool_invocation_observed", "a", {"toolName": "t", "status": "succeeded"})] * 30)
    bad = facts(*[("agent_tool_invocation_observed", "a", {"toolName": "t", "status": "failed"})] * 30,
                base="2026-10-23T10")
    m1, m2 = build_behavior_model(good, "a"), build_behavior_model(bad, "a")
    s1, s2 = snapshot(m1, ("2026-10-22", "2026-10-22T23")), snapshot(m2, ("2026-10-23", "2026-10-23T23"))
    drift = detect_drift(s1, s2, [{"first_seen": "2026-10-23T05", "model_id": "m2"}])
    assert drift["status"] == "drift_detected" and drift["dimensions"][0]["feature"] == "tool_success_rate"
    assert drift["coincident_configuration_changes"] and "not a proven cause" in drift["explanation_note"]
    assert detect_drift(s1, s1)["status"] == "no_drift_detected"
    assert signals_from_drift(T, "a", drift)[0].claim_state.value == "inferred"
    tiny = snapshot(build_behavior_model(good[:2], "a"), ("x", "y"))
    assert detect_drift(tiny, s2)["status"] == "no_drift_detected"


def test_adaptation_and_counterfactual():
    fs = facts(*[("agent_tool_invocation_observed", "a", {"toolName": t, "status": s}) for t, s in [
        ("x", "succeeded"), ("x", "succeeded"), ("x", "failed"), ("y", "succeeded"), ("y", "succeeded"),
        ("y", "succeeded")]])
    [row] = adaptation(fs, "a")
    assert row["tool"] == "x" and row["adaptation"] == "reduced_use"
    hist = facts(*[e for i in range(6) for e in _shop(i)] + _shop(9, deny=True))
    model = build_behavior_model(hist, "buyer")
    blocked = next(d for d in project_decisions(hist)["decisions"] if d["decision_id"] == "d9")
    cf = counterfactual_without_constraint(blocked, hist, model["preferences"])
    assert cf["status"] == "hypothetical" and cf["likely_choice"] == "cheap-9" and cf["basis"] == "inferred"
    assert cf["label"] == "counterfactual — not observed"
    assert counterfactual_without_constraint(project_decisions(facts(*_shop(1)))["decisions"][0], hist, [])["status"] \
        == "not_applicable"


def test_gs_b_swarm_demand_and_market():
    fs = scenario_facts("GS-B")
    [swarm] = [s for s in swarm_episodes(fs) if s["tool"] == "wallet_scan"]
    assert swarm["size"] == 15 and swarm["target"] == "wallet:0xdeadbeef"
    dg = demand_graph(fs)
    assert dg["targets_by_demand"][0][0] == "wallet:0xdeadbeef"
    adv = adversarial_signals(fs, [{"status": "outside", "evidence": ["gsb-evt-0001"]}])
    assert {a["kind"] for a in adv} == {"authority_boundary_exceeded"}
    assert signals_from_adversarial(FIXTURE["tenant_id"], "gsb-swarm-root", adv)[0].risk_dimension == "security"


def test_syndicates_are_similarity_not_control_and_contagion_follows_edges():
    models = [build_behavior_model(facts(*[("agent_tool_invocation_observed", a, {"toolName": "scan", "status": "succeeded"})] * 6,
                                         tenant=T), a) for a in ("s1", "s2", "s3")]
    [syn] = behavioral_syndicates(models)
    assert syn["members"] == ["s1", "s2", "s3"] and syn["implies_common_control"] is False
    fs = facts(("agent_tool_invocation_observed", "p", {"toolName": "new"}),
               ("agent_subagent_spawned", "p", {"parentAgentId": "p", "childAgentId": "k"}),
               ("agent_tool_invocation_observed", "k", {"toolName": "new"}),
               ("agent_tool_invocation_observed", "z", {"toolName": "new"}))
    cg = contagion(fs, "new")
    assert cg["linked_adoptions"] == ["k"] and cg["linked_share"] == 1.0 and cg["adopters"] == 3


def test_strategic_negotiation_market_and_discontinuity():
    fs = facts(("agent_quote_received", "seller", {"objectType": "item", "objectId": "i1", "amount": "100"}),
               ("agent_price_evaluated", "buyer", {"objectType": "item", "objectId": "i1", "amount": "80"}),
               ("agent_quote_received", "seller", {"objectType": "item", "objectId": "i1", "amount": "90"}),
               ("agent_transaction_initiated", "buyer", {"objectType": "item", "objectId": "i1", "amount": "90",
                                                         "resourceRef": "merchant:m1"}),
               ("agent_transaction_failed", "buyer", {"resourceRef": "merchant:m1", "errorCode": "3ds"}))
    [ep] = strategic_episodes(fs)
    assert ep["actors"] == ["buyer", "seller"]
    assert ep["negotiation"]["concessions"]["seller"] == "10" and ep["negotiation"]["agreed"] is True
    [mk] = market_compatibility(fs)
    assert mk["target"] == "merchant:m1" and mk["failure_reasons"] == {"3ds": 1}
    a = build_behavior_model(facts(*[("agent_tool_invocation_observed", "q", {"toolName": "alpha", "status": "succeeded"})] * 8), "q")
    b = build_behavior_model(facts(*[("agent_tool_invocation_observed", "q", {"toolName": "omega", "status": "failed"})] * 8), "q")
    assert identity_discontinuity(a, b)["status"] == "discontinuity_suspected"
    assert identity_discontinuity(a, b, [{"model_id": "new"}])["status"] == "explained_change"
    assert identity_discontinuity(a, a)["status"] == "continuous"


def test_adversarial_probing_and_injection():
    fs = facts(("agent_context_received", "a", {"trust": "untrusted"}),
               *[("agent_authorization_denied", "a", {}) for _ in range(3)],
               ("agent_guardrail_observed", "a", {}))
    kinds = {x["kind"] for x in adversarial_signals(fs)}
    assert {"guardrail_triggered", "authority_probing", "injection_suspected"} <= kinds
