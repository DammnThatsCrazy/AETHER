"""Segmented / seasonal baselines, agent detectors, ML windows, cross-run
correlation, feedback tuning, duplicate merging and graph promotion."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from intelligence.pattern_discovery.baselines import empty_baseline, seasonal_expected_rate
from intelligence.pattern_discovery.contracts import (
    KIND_AGENT_INTERACTION, KIND_AGENT_SPAWN, KIND_AGENT_TOOL_SIGNATURE, KIND_CROSS_DOMAIN,
    KIND_OUTLIER, KIND_SEGMENT_SHIFT, KIND_SEQUENCE, KIND_SHARED_ATTRIBUTE, KIND_TEMPORAL_BURST,
    KIND_TRAFFIC_ANOMALY,
)
from intelligence.pattern_discovery.detectors.frame import DetectorConfig
from intelligence.pattern_discovery.detectors.ml_windows import window_features
from intelligence.pattern_discovery.engine import run_discovery
from intelligence.pattern_discovery.extraction import extract_events
from intelligence.pattern_discovery.ml import score_windows
from intelligence.pattern_discovery.scoring import review_threshold, tuned_config
from intelligence.pattern_discovery.service import PatternDiscoveryService
from repositories.repos import reset_in_memory_stores

from .scenarios import T, FakeEventReader, FakeRiskStore, consent_reader, ev, fraud_ring, normal_traffic

BASE = datetime(2026, 11, 2, 8, tzinfo=timezone.utc)  # a Monday


@pytest.fixture(autouse=True)
def _clean():
    reset_in_memory_stores()
    yield
    reset_in_memory_stores()


def _learn(rows_by_run):
    baseline = empty_baseline(T)
    for rows in rows_by_run:
        baseline = run_discovery(T, rows, baseline=baseline).apply_to_baseline(baseline)
    return baseline


# ── Segmented baselines ──────────────────────────────────────────────────────

def _geo_traffic(day, ng_declines=0, seed=0):
    rows, i = [], seed * 10_000
    base = BASE + timedelta(days=day)
    for u in range(120):
        country = ["US", "GB", "NG", "DE"][u % 4]
        t = base + timedelta(minutes=u * 3)
        for et, props in (("login", {}), ("checkout", {"status": "succeeded"})):
            i += 1
            rows.append(ev(i, "user_id", f"g{u}", et, t, country=country, **props))
            t += timedelta(seconds=30)
    for k in range(ng_declines):
        i += 1
        rows.append(ev(i, "user_id", f"n{k}", "checkout", base + timedelta(minutes=k * 5),
                       country="NG", status="declined"))
    return rows


def test_a_shift_confined_to_one_country_is_reported_and_global_traffic_is_not():
    baseline = _learn([_geo_traffic(0, 2, 1), _geo_traffic(1, 2, 2)])
    result = run_discovery(T, _geo_traffic(2, 40, 3), baseline=baseline, kinds=[KIND_SEGMENT_SHIFT])
    shifts = {r["signature"]["segment"]: r for r in result.records}
    assert "geography=NG" in shifts
    assert shifts["geography=NG"]["signature"]["token"] == "checkout!fail"
    assert "geographic" in shifts["geography=NG"]["risk_categories"]
    assert not any(seg.startswith("entity_kind=") for seg in shifts)  # a single-valued dimension


def test_segment_shift_requires_history():
    result = run_discovery(T, _geo_traffic(2, 40), baseline=empty_baseline(T), kinds=[KIND_SEGMENT_SHIFT])
    assert result.records == []


# ── Seasonality ──────────────────────────────────────────────────────────────

def _hourly(day, hour, n, token="report_export", offset=0):
    base = (BASE + timedelta(days=day)).replace(hour=hour)
    return [ev(offset + i, "user_id", f"s{i % 30}", token, base + timedelta(seconds=i * 20)) for i in range(n)]


def test_seasonal_baseline_learns_hour_of_week():
    rows = _hourly(0, 9, 60) + _hourly(0, 15, 2, offset=1000)
    baseline = _learn([rows, [dict(r, event_id=r["event_id"] + "b") for r in rows]])
    slot = BASE.weekday() * 24 + 9
    assert seasonal_expected_rate(baseline, "report_export", slot) == pytest.approx(60, rel=0.01)


def test_an_expected_weekly_peak_is_not_a_burst_but_an_off_hours_one_is():
    weekly = [_hourly(7 * w, 9, 60, offset=w * 1000) + _hourly(7 * w, 13, 1, offset=w * 1000 + 500) for w in range(3)]
    baseline = _learn(weekly)
    peak = run_discovery(T, _hourly(21, 9, 60, offset=9000) + _hourly(21, 13, 1, offset=9500),
                         baseline=baseline, kinds=[KIND_TEMPORAL_BURST])
    assert peak.records == []
    off = run_discovery(T, _hourly(21, 9, 60, offset=9000) + _hourly(21, 13, 60, offset=9600),
                        baseline=baseline, kinds=[KIND_TEMPORAL_BURST])
    assert len(off.records) == 1
    assert off.records[0]["baseline"]["source"] == "seasonal_baseline"


# ── Cohort-aware outliers ────────────────────────────────────────────────────

def test_agents_are_compared_with_agents_not_people():
    rows, i = [], 0
    for u in range(30):
        for k in range(3):
            i += 1
            rows.append(ev(i, "user_id", f"p{u}", "browse", BASE + timedelta(minutes=u, seconds=k)))
    for a in range(25):
        for k in range(200):  # every agent is busy: normal for agents
            i += 1
            rows.append(ev(i, "agent_id", f"a{a}", "tool_call", BASE + timedelta(minutes=a, seconds=k)))
    result = run_discovery(T, rows, baseline=empty_baseline(T), kinds=[KIND_OUTLIER])
    assert not any(r["signature"]["cohort"] == "agent" for r in result.records)


# ── Agent detectors ──────────────────────────────────────────────────────────

def _agent_world():
    rows, i = [], 0
    for a in range(20):  # ordinary agents, each spawning 0-1 workers
        i += 1
        rows.append(ev(i, "agent_id", f"ag{a}", "agent_started", BASE + timedelta(minutes=a), principal_id=f"own{a}"))
        if a % 2:
            i += 1
            rows.append(ev(i, "agent_id", f"ag{a}_w", "agent_started", BASE + timedelta(minutes=a, seconds=5),
                           parent_agent=f"ag{a}"))
    for k in range(12):  # one orchestrator spawning 12 workers in a minute
        i += 1
        rows.append(ev(i, "agent_id", f"orch_w{k}", "agent_started", BASE + timedelta(hours=1, seconds=k * 4),
                       parent_agent="orch"))
    for a in range(6):  # six agents for six different people running one playbook
        t = BASE + timedelta(hours=2, minutes=a * 10)
        for tool in ("wallet_scan", "price_quote", "swap_execute"):
            i += 1
            rows.append(ev(i, "agent_id", f"play{a}", "tool_call", t, tool_name=tool, principal_id=f"person{a}"))
            t += timedelta(seconds=10)
    for a in range(4):  # a ring of agents paying each other across principals
        i += 1
        rows.append(ev(i, "agent_id", f"ring{a}", "agent_payment", BASE + timedelta(hours=3, minutes=a),
                       counterparty_agent=f"ring{(a + 1) % 4}", principal_id=f"owner{a}"))
    return rows


def test_agent_detectors_find_spawning_playbooks_and_rings():
    result = run_discovery(T, _agent_world(), baseline=empty_baseline(T),
                           kinds=[KIND_AGENT_SPAWN, KIND_AGENT_TOOL_SIGNATURE, KIND_AGENT_INTERACTION])
    by_kind = {}
    for r in result.records:
        by_kind.setdefault(r["kind"], []).append(r)
    spawn = by_kind[KIND_AGENT_SPAWN]
    assert [r["signature"]["parent"] for r in spawn] == ["agent:orch"]
    tools = by_kind[KIND_AGENT_TOOL_SIGNATURE][0]
    assert tools["signature"]["tools"] == ["wallet_scan", "price_quote", "swap_execute"]
    assert sum(1 for k in tools["affected_entity_keys"] if k.startswith("user:person")) == 6
    ring = by_kind[KIND_AGENT_INTERACTION][0]
    assert {f"agent:ring{a}" for a in range(4)} <= set(ring["affected_entity_keys"])
    for r in result.records:
        assert any(c["id"] == "principal_may_be_a_victim" for c in r["competing_explanations"])


def test_an_agent_row_names_the_agent_as_actor_and_the_person_as_principal():
    ex = extract_events([ev(1, "agent_id", "bot1", "tool_call", BASE, tool_name="search") | {"user_id": "u7"}], T)
    e = ex.events[0]
    assert e.entity == "agent:bot1" and e.principal == "user:u7" and e.token == "tool:search"
    assert ("DELEGATED_BY", "user:u7") in e.counterparties


# ── ML window scoring ────────────────────────────────────────────────────────

class _Resp:
    def __init__(self, status, body):
        self.status_code, self._body = status, body

    def json(self):
        return self._body


class _MLClient:
    def __init__(self, scorer=None, status=200, raise_exc=None):
        self.scorer, self.status, self.raise_exc, self.payloads = scorer, status, raise_exc, []

    async def post(self, path, json=None, timeout=None):
        if self.raise_exc:
            raise self.raise_exc
        self.payloads.append((path, json))
        preds = [{"anomaly_score": self.scorer(f)} for f in json["instances"]]
        return _Resp(self.status, {"predictions": preds})


def test_window_features_match_the_model_contract():
    rows = normal_traffic(1, 1, users=20) + fraud_ring(1)
    windows = window_features(extract_events(rows, T).events)
    expected = {"traffic_volume", "conversion_rate", "avg_session_duration", "bounce_rate", "error_rate",
                "api_latency_p99", "bot_traffic_ratio", "unique_visitors", "revenue"}
    assert windows and all(set(w["features"]) == expected for w in windows)
    assert all(0 <= w["features"]["error_rate"] <= 1 and 0 <= w["features"]["bot_traffic_ratio"] <= 1 for w in windows)
    assert all("api_latency_p99" in w["unobserved_features"] for w in windows)


@pytest.mark.asyncio
async def test_ml_scores_become_a_traffic_anomaly_pattern():
    rows = normal_traffic(1, 1, users=40) + fraud_ring(1)
    ex = extract_events(rows, T)
    client = _MLClient(lambda f: 0.9 if f["error_rate"] > 0.3 else 0.1)
    scores, report = await score_windows(ex, client)
    assert report["status"] == "scored" and report["flagged"] >= 1
    assert client.payloads[0][0] == "/v1/predict/batch" and client.payloads[0][1]["model"] == "anomaly_detection"
    result = run_discovery(T, rows, baseline=empty_baseline(T), kinds=[KIND_TRAFFIC_ANOMALY],
                           extraction=ex, ml_window_scores=scores)
    assert len(result.records) == 1 and result.records[0]["kind"] == KIND_TRAFFIC_ANOMALY
    assert result.records[0]["confidence"] <= 0.6


@pytest.mark.asyncio
async def test_ml_failures_are_reported_not_raised():
    ex = extract_events(normal_traffic(1, 1, users=5), T)
    scores, report = await score_windows(ex, _MLClient(raise_exc=ConnectionError("down")))
    assert scores == {} and report["status"] == "unreachable"
    scores, report = await score_windows(ex, _MLClient(lambda f: 0.1, status=404))
    assert scores == {} and report["status"] == "http_404"


# ── Feedback tuning ──────────────────────────────────────────────────────────

def test_noisy_kinds_get_stricter_and_trusted_kinds_more_sensitive():
    cal = {"sequence": {"factor": 0.6, "precision_estimate": 0.1, "useful": 0, "noise": 8},
           "lockstep": {"factor": 1.4, "precision_estimate": 0.9, "useful": 8, "noise": 0},
           "behavioral_outlier": {"factor": 1.0, "precision_estimate": 0.5, "useful": 1, "noise": 1}}
    cfg, changes = tuned_config(DetectorConfig(), cal)
    assert cfg.sequence_min_lift > DetectorConfig().sequence_min_lift
    assert cfg.lockstep_min_entities < DetectorConfig().lockstep_min_entities
    assert "outlier_z" not in changes  # too few verdicts to tune
    assert review_threshold("sequence", cal) > review_threshold("lockstep", cal)


# ── Cross-run correlation, duplicates and graph promotion (service) ──────────

class _Graph:
    """Minimal in-memory graph client recording gateway writes."""

    def __init__(self):
        self.vertices, self.edges, self.revoked = {}, [], []

    async def get_edges_for_tenant(self, tenant_id, limit=1000, **kw):
        return [e for e in self.edges if e.properties.get("tenant_id") == tenant_id], False

    async def get_vertices_for_tenant(self, tenant_id, limit=1000, **kw):
        return [v for v in self.vertices.values() if v.properties.get("tenant_id") == tenant_id]


def _svc(rows, graph=None):
    async def resolver(tenant_id, key):
        return ("entity", key.split(":", 1)[1]) if key.startswith("user:") else None

    return PatternDiscoveryService(event_reader=FakeEventReader(rows), risk_store=FakeRiskStore(),
                                   subject_resolver=resolver, consent_reader=consent_reader(),
                                   graph_client=graph or _Graph())


@pytest.mark.asyncio
async def test_cross_run_correlation_links_today_with_yesterday():
    rows = normal_traffic(2, 2) + fraud_ring(2)
    svc = _svc(rows)
    first = await svc.run(T, kinds=[KIND_SHARED_ATTRIBUTE])
    assert first["patterns_detected"] >= 1
    second = await svc.run(T, kinds=[KIND_SEQUENCE, KIND_CROSS_DOMAIN])
    composites = [p for p in second["patterns"] if p["kind"] == KIND_CROSS_DOMAIN]
    assert composites
    detail = await svc.get_pattern(T, composites[0]["pattern_id"])
    members = detail["evidence"][0]["detail"]["members"]
    assert detail["evidence"][0]["detail"]["cross_run"] is True
    assert {m["kind"] for m in members} >= {KIND_SEQUENCE, KIND_SHARED_ATTRIBUTE}
    assert any(m["from_earlier_run"] for m in members) and any(not m["from_earlier_run"] for m in members)


@pytest.mark.asyncio
async def test_duplicate_verdict_merges_into_the_canonical_pattern():
    svc = _svc(normal_traffic(2, 2) + fraud_ring(2))
    await svc.run(T)
    items = (await svc.list_patterns(T))["items"]
    lock = [i for i in items if i["kind"] == "lockstep"]
    assert len(lock) >= 2
    canonical, dup = lock[0]["pattern_id"], lock[1]["pattern_id"]
    await svc.review(T, dup, reviewer_id="a", verdict="duplicate", reason="same coordinated ring", duplicate_of=canonical)
    target = await svc.registry.get(T, canonical)
    assert [d["pattern_id"] for d in target["duplicates"]] == [dup]
    assert target["review_history"][-1]["decision"] == "merged_duplicate"
    before = target["occurrence_count"]
    await svc.run(T)  # the duplicate is re-detected; merging is idempotent
    again = await svc.registry.get(T, canonical)
    assert len(again["duplicates"]) == 1 and again["occurrence_count"] >= before


@pytest.mark.asyncio
async def test_promotion_projects_governed_graph_membership_and_deprecation_revokes_it(monkeypatch):
    applied = []

    class _Gateway:
        def __init__(self, graph_client=None):
            pass

        async def apply(self, intent):
            applied.append(intent)

    monkeypatch.setattr("shared.graph.mutation_gateway.GraphMutationGateway", _Gateway)
    svc = _svc(normal_traffic(2, 2) + fraud_ring(2))
    await svc.run(T)
    pid = (await svc.list_patterns(T, kind=KIND_SHARED_ATTRIBUTE))["items"][0]["pattern_id"]
    await svc.review(T, pid, reviewer_id="a", verdict="malicious", reason="card farm confirmed by ops")
    promoted = await svc.promote(T, pid, reviewer_id="a", reason="graph and risk promotion")
    proj = promoted["promotion"]["graph_projection"]
    assert proj["status"] == "projected" and proj["edges"] == 14
    assert len(applied) == 15  # one RiskCluster vertex + 14 membership edges
    deprecated = await svc.deprecate(T, pid, actor="a", reason="ring dismantled; retire the pattern")
    assert deprecated["promotion"]["graph_revocation"]["revoked"] == 14
    assert len(applied) == 29


@pytest.mark.asyncio
async def test_motifs_read_the_canonical_graph():
    from shared.graph.graph import Edge, Vertex

    graph = _Graph()
    for ring in range(3):
        ids = [f"c{ring}_{k}" for k in range(3)]
        for k, vid in enumerate(ids):
            graph.vertices[vid] = Vertex(vertex_type="User", vertex_id=vid, properties={"tenant_id": T})
            graph.edges.append(Edge(edge_type="REFERRED", from_vertex_id=vid, to_vertex_id=ids[(k + 1) % 3],
                                    properties={"tenant_id": T}))
    svc = _svc(normal_traffic(2, 2, users=10), graph=graph)
    out = await svc.run(T, kinds=["novel_motif"])
    assert out["coverage"]["graph"]["edges"] == 9
    motifs = [p for p in out["patterns"] if p["kind"] == "novel_motif"]
    assert motifs and motifs[0]["affected_entity_count"] == 9


# ── 360 sections ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_profile_agent_and_risk_sections():
    svc = _svc(normal_traffic(2, 2) + fraud_ring(2) + _agent_world())
    await svc.run(T)
    profile = await svc.section(T, "user:r0", "profile360")
    assert profile["withheld"] is False and profile["surface"] == "profile360"
    assert profile["emerging_patterns"] and profile["unresolved_identity_overlaps"]
    assert any(e["entity"].startswith("user:r") for e in profile["similar_profiles"])
    agent = await svc.section(T, "agent:play0", "agent360")
    assert agent["tool_call_signatures"] and agent["cross_principal_behavior"]
    orch = await svc.section(T, "agent:orch", "agent360")
    assert orch["spawning_anomalies"]
    risk = await svc.section(T, "user:r0", "risk360")
    assert risk["pattern_findings"] and risk["campaigns"]
    finding = risk["pattern_findings"][0]
    assert finding["evidence_coverage"]["items"] >= 1 and finding["review_status"]


@pytest.mark.asyncio
async def test_sections_are_withheld_without_consent():
    svc = PatternDiscoveryService(event_reader=FakeEventReader(normal_traffic(2, 2) + fraud_ring(2)),
                                  risk_store=FakeRiskStore(), consent_reader=consent_reader(frozenset({"r0"})),
                                  graph_client=_Graph())
    await svc.run(T)
    for surface in ("profile360", "risk360"):
        out = await svc.section(T, "user:r0", surface)
        assert out["withheld"] is True and out["counts"]["total"] == 0


def test_section_routes_over_http():
    from fastapi import FastAPI
    from fastapi.responses import JSONResponse
    from fastapi.testclient import TestClient

    from intelligence.pattern_discovery import routes as pd_routes
    from intelligence.pattern_discovery.service import set_service
    from shared.auth.auth import Permissions, Role, TenantContext
    from shared.common.common import AetherError

    svc = _svc(normal_traffic(2, 2) + fraud_ring(2))
    set_service(svc)
    try:
        app = FastAPI()

        @app.exception_handler(AetherError)
        async def _err(request, exc):
            return JSONResponse(status_code=exc.code.value, content=exc.to_dict())

        tenant = TenantContext(tenant_id=T, user_id="u", role=Role.VIEWER, permissions=[Permissions.READ, Permissions.WRITE])

        @app.middleware("http")
        async def _inject(request, call_next):
            request.state.tenant = tenant
            return await call_next(request)

        for r in (pd_routes.router, pd_routes.profile_router, pd_routes.agent_router, pd_routes.risk_router):
            app.include_router(r)
        client = TestClient(app, raise_server_exceptions=False)
        assert client.post("/v1/intelligence/patterns/runs", json={}).status_code == 200
        assert client.get("/v1/profile/r0/patterns").json()["data"]["surface"] == "profile360"
        assert client.get("/v1/agent/orch/patterns").json()["data"]["surface"] == "agent360"
        assert client.get("/v1/risk360/user/r0/patterns").json()["data"]["pattern_findings"]
        assert client.get("/v1/risk360/planet/r0/patterns").status_code == 400
    finally:
        set_service(None)


# ── Scheduler ────────────────────────────────────────────────────────────────

class _Jobs:
    def __init__(self):
        self.enqueued = []

    async def enqueue(self, tenant_id, job_type, payload, idempotency_key=None):
        self.enqueued.append((tenant_id, job_type, idempotency_key))


def _settings(enabled=True, scheduler=True, minutes=360):
    from types import SimpleNamespace

    return SimpleNamespace(pattern_discovery=SimpleNamespace(
        enabled=enabled, scheduler_enabled=scheduler, scheduler_interval_minutes=minutes))


@pytest.mark.asyncio
async def test_sweep_enqueues_one_idempotent_job_per_tenant_per_interval():
    from intelligence.pattern_discovery.jobs import JOB_TYPE, sweep_once

    async def tenants():
        return ["t1", "t2"]

    jobs = _Jobs()
    now = datetime(2026, 11, 14, 10, 5, tzinfo=timezone.utc)
    assert await sweep_once(now, tenants=tenants, jobs=jobs, settings=_settings()) == 2
    await sweep_once(now + timedelta(minutes=30), tenants=tenants, jobs=jobs, settings=_settings())
    keys = [k for _t, _j, k in jobs.enqueued]
    assert all(j == JOB_TYPE for _t, j, _k in jobs.enqueued)
    assert keys[0] == keys[2] and keys[1] == keys[3]  # same interval bucket -> same idempotency key
    later = _Jobs()
    await sweep_once(now + timedelta(hours=7), tenants=tenants, jobs=later, settings=_settings())
    assert later.enqueued[0][2] != keys[0]


@pytest.mark.asyncio
async def test_sweep_is_inert_unless_both_flags_are_on():
    from intelligence.pattern_discovery.jobs import sweep_once

    async def tenants():
        return ["t1"]

    jobs = _Jobs()
    assert await sweep_once(tenants=tenants, jobs=jobs, settings=_settings(enabled=False)) == 0
    assert await sweep_once(tenants=tenants, jobs=jobs, settings=_settings(scheduler=False)) == 0
    assert jobs.enqueued == []


@pytest.mark.asyncio
async def test_job_handler_runs_discovery_for_the_job_tenant():
    from types import SimpleNamespace

    from intelligence.pattern_discovery import jobs as jobs_mod
    from intelligence.pattern_discovery.service import set_service

    set_service(_svc(normal_traffic(2, 2) + fraud_ring(2)))
    try:
        outcome = await jobs_mod.run_job({}, SimpleNamespace(tenant_id=T))
        assert outcome.status == "succeeded" and outcome.result["patterns_detected"] >= 5
    finally:
        set_service(None)
    jobs_mod.register_pattern_discovery_handlers()
    from workers.jobs.handlers import HANDLER_REGISTRY

    assert jobs_mod.JOB_TYPE in HANDLER_REGISTRY
