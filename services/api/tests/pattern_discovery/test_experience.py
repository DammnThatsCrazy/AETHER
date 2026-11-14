"""The end-user experience: surfaced-by-default feed, what's new since I last
looked, patterns on the graph, and the segment lenses."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from intelligence.pattern_discovery import routes as pd_routes
from intelligence.pattern_discovery.contracts import KIND_SEQUENCE, KIND_SHARED_ATTRIBUTE
from intelligence.pattern_discovery.graphview import keys_for_ids, overlay, pattern_subgraph
from intelligence.pattern_discovery.service import PatternDiscoveryService, set_service
from repositories.repos import reset_in_memory_stores
from shared.auth.auth import Permissions, Role, TenantContext
from shared.common.common import AetherError

from .scenarios import T, FakeEventReader, FakeRiskStore, consent_reader, fraud_ring, normal_traffic


@pytest.fixture(autouse=True)
def _clean():
    reset_in_memory_stores()
    yield
    reset_in_memory_stores()


class _Graph:
    async def get_edges_for_tenant(self, tenant_id, limit=1000, **kw):
        return [], False

    async def get_vertices_for_tenant(self, tenant_id, limit=1000, **kw):
        return []


def _ring_with_segments(day=2):
    rows = fraud_ring(day)
    for r in rows:
        r["properties"].update(utm_campaign="spring_sale", channel="Email", country="ng")
    return rows


def _svc(rows, *, notifier=None, consent=None):
    notes = []

    async def default_notifier(tenant_id, surfaced, *, run_id):
        notes.append((tenant_id, [p["pattern_id"] for p in surfaced], run_id))
        return {"id": "notif-1"}

    svc = PatternDiscoveryService(event_reader=FakeEventReader(rows), risk_store=FakeRiskStore(),
                                  consent_reader=consent or consent_reader(), graph_client=_Graph(),
                                  notifier=notifier or default_notifier)
    svc.notes = notes
    return svc


# ── What's new since I last looked ───────────────────────────────────────────

@pytest.mark.asyncio
async def test_monday_then_thursday():
    svc = _svc(normal_traffic(1, 1))
    await svc.run(T)
    monday = await svc.whats_new(T, viewer_id="u1")
    assert monday["since_source"] == "default_lookback" and monday["new"] == []
    seen = await svc.mark_seen(T, viewer_id="u1")
    # Thursday: the backend surfaced the ring on its own.
    svc._event_reader = FakeEventReader(normal_traffic(4, 4) + _ring_with_segments(4))
    run = await svc.run(T)
    assert run["newly_surfaced"] >= 5 and run["notification_id"] == "notif-1"
    thursday = await svc.whats_new(T, viewer_id="u1")
    assert thursday["since_source"] == "last_seen" and thursday["since"] == seen["last_seen_at"]
    assert len(thursday["new"]) >= 5 and thursday["digest"]["new"]["count"] == len(thursday["new"])
    assert "campaign=spring_sale" in thursday["digest"]["new"]["by_segment"]
    # Another viewer never looked: same patterns, measured from the default lookback.
    other = await svc.whats_new(T, viewer_id="u2")
    assert {p["pattern_id"] for p in other["new"]} >= {p["pattern_id"] for p in thursday["new"]}
    await svc.mark_seen(T, viewer_id="u1")
    assert (await svc.whats_new(T, viewer_id="u1"))["new"] == []


@pytest.mark.asyncio
async def test_changed_and_retired_patterns_are_reported():
    svc = _svc(normal_traffic(2, 2) + fraud_ring(2))
    await svc.run(T)
    before = datetime.now(timezone.utc).isoformat()
    pid = (await svc.list_patterns(T, kind=KIND_SEQUENCE))["items"][0]["pattern_id"]
    await svc.registry.mutate(T, pid, lambda r: dict(r, changed_at=datetime.now(timezone.utc).isoformat()))
    other = (await svc.list_patterns(T, kind=KIND_SHARED_ATTRIBUTE))["items"][0]["pattern_id"]
    await svc.deprecate(T, other, actor="u1", reason="dismantled; no longer relevant")
    out = await svc.whats_new(T, viewer_id="u9", since=before)
    assert pid in {p["pattern_id"] for p in out["changed"]}
    assert other in {p["pattern_id"] for p in out["retired"]}


@pytest.mark.asyncio
async def test_sections_flag_new_rows_per_viewer_and_scope():
    svc = _svc(normal_traffic(1, 1))
    await svc.run(T)
    await svc.mark_seen(T, viewer_id="u1", scope="profile360:user:r0")
    svc._event_reader = FakeEventReader(normal_traffic(4, 4) + fraud_ring(4))
    await svc.run(T)
    section = await svc.section(T, "user:r0", "profile360", viewer_id="u1")
    assert section["scope"] == "profile360:user:r0" and section["last_seen_at"]
    assert section["new_count"] >= 1 and all(r["is_new"] for r in section["emerging_patterns"])
    scoped = await svc.whats_new(T, viewer_id="u1", scope="profile360:user:r0")
    assert scoped["new"] and all("pattern_id" in p for p in scoped["new"])


@pytest.mark.asyncio
async def test_entity_scopes_respect_consent_and_bad_scopes_are_refused():
    from intelligence.pattern_discovery.registry import LifecycleError

    svc = _svc(normal_traffic(2, 2) + fraud_ring(2), consent=consent_reader(frozenset({"r0"})))
    await svc.run(T)
    out = await svc.whats_new(T, viewer_id="u1", scope="profile360:user:r0")
    assert out["withheld"] is True and out["new"] == []
    with pytest.raises(LifecycleError):
        await svc.whats_new(T, viewer_id="u1", scope="nonsense")


@pytest.mark.asyncio
async def test_notifications_are_limited_to_notable_new_patterns(monkeypatch):
    from intelligence.pattern_discovery import feed

    created = []

    async def fake_create(tenant_id, **kw):
        created.append(kw)
        return {"id": "n1"}

    monkeypatch.setattr("journeys.notification_intelligence.inbox.create_inbox_notification", fake_create)
    low = [{"pattern_id": "p1", "status": "surfaced", "severity": "low", "title": "x"}]
    assert await feed.notify_new_patterns(T, low, run_id="r") is None
    high = [{"pattern_id": f"p{i}", "status": "surfaced", "severity": "critical" if i == 0 else "high",
             "title": f"pattern {i}"} for i in range(4)]
    await feed.notify_new_patterns(T, high, run_id="r")
    assert created[0]["severity"] == "P1" and created[0]["title"] == "4 new patterns surfaced"
    assert created[0]["dedupe_key"].startswith(f"pattern_discovery:{T}:")
    assert created[0]["link"] == "/patterns?view=new"


# ── Patterns on the graph ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_pattern_subgraph_shows_members_and_shared_attributes():
    svc = _svc(normal_traffic(2, 2) + fraud_ring(2))
    await svc.run(T)
    pid = (await svc.list_patterns(T, kind=KIND_SHARED_ATTRIBUTE))["items"][0]["pattern_id"]
    graph = await svc.pattern_graph(T, pid)
    roles = {n["role"] for n in graph["nodes"]}
    assert {"pattern", "member", "attribute"} <= roles
    members = [n for n in graph["nodes"] if n["role"] == "member"]
    assert len(members) == 14
    types = {e["type"] for e in graph["edges"]}
    assert "MEMBER_OF_PATTERN" in types and any(t.startswith("USES_") for t in types)
    composite = (await svc.list_patterns(T, kind="cross_domain"))["items"][0]["pattern_id"]
    cgraph = await svc.pattern_graph(T, composite)
    assert any(n["role"] == "member_pattern" for n in cgraph["nodes"])
    assert await svc.pattern_graph(T, "missing") is None


@pytest.mark.asyncio
async def test_graph_overlay_matches_raw_and_prefixed_ids_and_skips_hidden():
    svc = _svc(normal_traffic(2, 2) + fraud_ring(2))
    await svc.run(T)
    out = await svc.graph_overlay(T, ["r0", "user:r1", "u5", "nobody"])
    assert set(out["by_node"]) >= {"r0", "user:r1"}
    assert out["patterns"] and all("r0" in p["members_in_view"] or "user:r1" in p["members_in_view"]
                                   for p in out["patterns"])
    target = out["patterns"][0]["pattern_id"]
    await svc.curate(T, target, actor="u1", action="hide")
    again = await svc.graph_overlay(T, ["r0", "user:r1"])
    assert target not in {p["pattern_id"] for p in again["patterns"]}


def test_overlay_helpers_are_pure():
    lookup = keys_for_ids(["abc", "agent:x"])
    assert lookup["user:abc"] == "abc" and lookup["agent:x"] == "agent:x" and lookup["user:x"] == "agent:x"
    rec = {"pattern_id": "p", "status": "surfaced", "affected_entity_keys": ["user:abc"], "kind": "sequence"}
    assert overlay(["abc"], [rec])["by_node"] == {"abc": ["p"]}
    assert pattern_subgraph({**rec, "evidence": []})["nodes"][0]["role"] == "pattern"


# ── Segment lenses ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_campaign_geographic_and_communication_lenses():
    svc = _svc(normal_traffic(2, 2) + _ring_with_segments(2))
    await svc.run(T)
    ring = (await svc.list_patterns(T, kind=KIND_SHARED_ATTRIBUTE))["items"][0]
    assert "campaign=spring_sale" in ring["segment_keys"] and "geography=NG" in ring["segment_keys"]
    campaign = await svc.lens(T, "campaign360", "spring_sale")
    assert campaign["counts"]["total"] >= 5 and campaign["groups"]
    assert {g["heading"] for g in campaign["groups"]} >= {"Recurring sequences"}
    geo = await svc.lens(T, "geographic360", "ng")
    assert geo["counts"]["total"] == campaign["counts"]["total"]
    email = await svc.lens(T, "communication360", "EMAIL")
    assert email["counts"]["total"] >= 5
    assert (await svc.lens(T, "communication360", "all"))["counts"]["total"] >= email["counts"]["total"]
    assert (await svc.lens(T, "campaign360", "winter"))["counts"]["total"] == 0


@pytest.mark.asyncio
async def test_journey_lens_is_entity_scoped_and_consent_gated():
    from intelligence.pattern_discovery.registry import LifecycleError

    svc = _svc(normal_traffic(2, 2) + fraud_ring(2), consent=consent_reader(frozenset({"r5"})))
    await svc.run(T)
    journey = await svc.lens(T, "journey360", "r0")
    kinds = {p["kind"] for p in journey["patterns"]}
    assert "sequence" in kinds and "shared_attribute_cluster" not in kinds
    assert (await svc.lens(T, "journey360", "r5"))["withheld"] is True
    with pytest.raises(LifecycleError):
        await svc.lens(T, "astrology360", "x")


# ── HTTP ─────────────────────────────────────────────────────────────────────

def test_experience_routes_over_http():
    svc = _svc(normal_traffic(2, 2) + _ring_with_segments(2))
    set_service(svc)
    try:
        app = FastAPI()

        @app.exception_handler(AetherError)
        async def _err(request, exc):
            return JSONResponse(status_code=exc.code.value, content=exc.to_dict())

        tenant = TenantContext(tenant_id=T, user_id="viewer-1", role=Role.VIEWER,
                               permissions=[Permissions.READ, Permissions.WRITE])

        @app.middleware("http")
        async def _inject(request, call_next):
            request.state.tenant = tenant
            return await call_next(request)

        app.include_router(pd_routes.router)
        c = TestClient(app, raise_server_exceptions=False)
        assert c.post("/v1/intelligence/patterns/runs", json={}).status_code == 200
        new = c.get("/v1/intelligence/patterns/whats-new").json()["data"]
        assert new["new"]
        assert c.post("/v1/intelligence/patterns/whats-new/seen", json={"scope": "feed"}).status_code == 200
        assert c.get("/v1/intelligence/patterns/whats-new").json()["data"]["new"] == []
        assert c.get("/v1/intelligence/patterns/whats-new", params={"scope": "bad"}).status_code == 400
        lens = c.get("/v1/intelligence/patterns/lenses/campaign360/spring_sale").json()["data"]
        assert lens["counts"]["total"] >= 5
        assert c.get("/v1/intelligence/patterns/lenses/nope/x").status_code == 400
        pid = lens["patterns"][0]["pattern_id"]
        assert c.get(f"/v1/intelligence/patterns/{pid}/graph").json()["data"]["nodes"]
        ov = c.post("/v1/intelligence/patterns/graph-overlay", json={"node_ids": ["r0"]}).json()["data"]
        assert ov["by_node"]["r0"]
        cur = c.post(f"/v1/intelligence/patterns/{pid}/curate", json={"action": "pin"})
        assert cur.status_code == 200 and cur.json()["data"]["pinned"] is True
        assert c.post(f"/v1/intelligence/patterns/{pid}/curate", json={"action": "explode"}).status_code == 422
        assert c.get("/v1/intelligence/patterns", params={"feed": True}).json()["data"]["items"][0]["pattern_id"] == pid
    finally:
        set_service(None)
