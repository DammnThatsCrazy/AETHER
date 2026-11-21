"""Propagation run orchestration over repository sources, and the gated route."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from jsonschema import validate

from intelligence.propagation.contracts import EpisodeClassification, PropagationQuery
from intelligence.propagation.service import PropagationService
from intelligence.propagation.sources import RepositoryPropagationSources

ROOT = Path(__file__).resolve().parents[4]
SCHEMA = json.loads((ROOT / "packages/shared/contracts/propagation-run.schema.json").read_text())
T = "tenant_svc"
T0 = datetime(2026, 11, 2, 9, 0, tzinfo=timezone.utc)


def at(minutes: float) -> datetime:
    return T0 + timedelta(minutes=minutes)


class FakeLinks:
    async def subjects_by_account(self, tenant_id):
        assert tenant_id == T
        return {("hyperliquid", f"0x{i}"): f"u{i}" for i in range(1, 9)}


ADMITTED = ["source_grant_ref=drg_1", "rights_decision_ref=rd_1", "source_id=provider-account:c:a"]


class FakeFills:
    def __init__(self):
        self.rows = [
            {"tenant_id": T, "trading_account_id": "acct_0x1", "canonical_market_id": "hyperliquid:mainnet:HYPE",
             "fill_id": "f1", "side": "buy", "price": "40", "quantity": "2", "executed_at": at(0),
             "source_refs": ["direction=Open Long", *ADMITTED]},
            {"tenant_id": T, "trading_account_id": "acct_0x2", "canonical_market_id": "hyperliquid:mainnet:HYPE",
             "fill_id": "f2", "side": "buy", "price": "41", "quantity": "1", "executed_at": at(45),
             "source_refs": ["direction=Open Long", *ADMITTED]},
            # Written by legacy intake, never admitted under a grant: excluded.
            {"tenant_id": T, "trading_account_id": "acct_0x4", "canonical_market_id": "hyperliquid:mainnet:HYPE",
             "fill_id": "f4", "side": "buy", "price": "41", "quantity": "1", "executed_at": at(20),
             "source_refs": ["direction=Open Long"]},
            {"tenant_id": "other", "trading_account_id": "acct_0x3", "canonical_market_id": "hyperliquid:mainnet:HYPE",
             "fill_id": "f3", "side": "buy", "price": "41", "quantity": "1", "executed_at": at(50)},
        ]

    async def find_many(self, filters, limit=50, order_by="created_at", descending=True):
        # derivatives_fills has no created_at column; the real typed repo would
        # fail in PostgreSQL on its default ordering.
        assert order_by == "executed_at", order_by
        return [r for r in self.rows if all(r.get(k) == v for k, v in filters.items())]


class FakeGraph:
    def __init__(self):
        self.calls = []

    async def get_edges_for_tenant(self, tenant_id, limit=1000, *, edge_types=None, include_revoked=False):
        self.calls.append((tenant_id, tuple(edge_types or ())))
        edge = SimpleNamespace(
            edge_type="FOLLOWS_SOCIAL", from_vertex_id="u2", to_vertex_id="u1",
            properties={"tenant_id": T, "relationship_predicate": "FOLLOWS", "valid_from": at(-500).isoformat(),
                        "evidence_refs": [{"id": "ev:follow"}], "idempotency_key": "e:1"},
        )
        return [edge], False


class FakePool:
    def __init__(self, rows):
        self.rows = rows
        self.args = None

    def acquire(self):
        pool = self

        class _Ctx:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc):
                return False

            async def fetch(self, sql, *args):
                pool.args = args
                return pool.rows

        return _Ctx()


def sources(pool_rows=(), grants=None):
    pool = FakePool(list(pool_rows))

    async def pool_factory():
        return pool

    graph = FakeGraph()
    return RepositoryPropagationSources(
        link_service=FakeLinks(), fill_repo=FakeFills(), graph_client=graph, pool_factory=pool_factory,
        grant_lookup=(grants or FakeGrants()).get_grant,
    ), graph, pool


def query():
    return PropagationQuery(tenant_id=T, window_start=at(-60).isoformat(), window_end=at(600).isoformat())


async def test_service_builds_tenant_run_from_repository_sources():
    in_app = [{"tenant_id": T, "source_event_id": "evt-9", "source_event_type": "content_impression",
               "user_id": "u3", "occurred_at": at(10), "payload": json.dumps({"exposedSubjectRef": "u1"})}]
    src, graph, pool = sources(in_app)
    result = await PropagationService(src).run(query())
    payload = result.to_dict()
    validate(payload, SCHEMA)
    assert graph.calls and graph.calls[0][0] == T and "FOLLOWS_SOCIAL" in graph.calls[0][1]
    assert pool.args[0] == T
    (episode,) = result.episodes
    assert [a.subject_id for a in episode.adopters] == ["u1", "u2"]
    assert episode.metrics.exposed_adopters == 1
    assert episode.paths[0].hops[0].predicate == "FOLLOWS"
    assert episode.baseline.exposed == 2  # u2 (adopted) + u3 (in-app viewer, did not adopt)
    assert episode.classification is EpisodeClassification.INSUFFICIENT_DATA  # groups too small
    assert "unadmitted_fills_excluded" in result.limitations
    assert "u4" not in {a.subject_id for a in episode.adopters}


async def test_unavailable_sources_degrade_with_reasons():
    class BrokenGraph:
        async def get_edges_for_tenant(self, *a, **k):
            raise RuntimeError("down")

    async def no_pool():
        return None

    src = RepositoryPropagationSources(
        link_service=FakeLinks(), fill_repo=FakeFills(), graph_client=BrokenGraph(), pool_factory=no_pool,
        grant_lookup=FakeGrants().get_grant,
    )
    result = await PropagationService(src).run(query())
    assert "canonical_graph_authority_unavailable" in result.limitations
    assert "in_app_exposure_store_unavailable" in result.limitations
    assert result.episodes[0].metrics.propagation_radius is None


async def test_include_live_syncs_linked_accounts_before_reading():
    calls = []

    class FakeSync:
        async def sync_tenant(self, tenant_id):
            calls.append(tenant_id)
            return SimpleNamespace(truncated=False, links=[SimpleNamespace(status="denied")])

    src, _, _ = sources()
    src._account_sync = FakeSync()
    result = await PropagationService(src).run(query(), include_live=True)
    assert calls == [T]
    assert "account_sync_denied" in result.limitations


def test_stored_fill_key_comes_from_the_venue_adapter():
    from intelligence.propagation.sources import _adapter_account_key

    assert _adapter_account_key("hyperliquid", "0xabc") == "acct_0xabc"
    assert _adapter_account_key("dydx", "dydx1abc") == "acct_dydx1abc_0"


async def test_route_is_disabled_by_default(monkeypatch):
    from config.settings import settings
    from intelligence.propagation import routes
    from shared.common.common import ServiceUnavailableError

    monkeypatch.setattr(settings, "social360", SimpleNamespace(propagation_lens_enabled=False))
    request = SimpleNamespace(state=SimpleNamespace(tenant=SimpleNamespace(tenant_id=T, require_permission=lambda p: None)))
    body = routes.PropagationRunRequest(window_start=at(0).isoformat(), window_end=at(10).isoformat())
    with pytest.raises(ServiceUnavailableError):
        await routes.create_propagation_run(body, request)


async def test_route_runs_for_caller_tenant_only(monkeypatch):
    from config.settings import settings
    from intelligence.propagation import routes, service

    seen = {}

    class FakeService:
        async def run(self, q, include_live=False):
            seen["tenant"] = q.tenant_id
            return await PropagationService(sources()[0]).run(q)

    granted = []
    metered = []
    monkeypatch.setattr(settings, "social360", SimpleNamespace(propagation_lens_enabled=True))
    monkeypatch.setattr(service, "PropagationService", FakeService)
    await _entitle(T)
    monkeypatch.setattr(routes, "_meter", _recording_meter(metered))
    tenant = SimpleNamespace(tenant_id=T, require_permission=granted.append)
    request = SimpleNamespace(state=SimpleNamespace(tenant=tenant))
    body = routes.PropagationRunRequest(window_start=at(-60).isoformat(), window_end=at(600).isoformat())
    response = await routes.create_propagation_run(body, request)
    assert seen["tenant"] == T
    assert response["data"]["tenant_id"] == T
    assert set(granted) == {"analytics", "derivatives:read"}
    assert metered == [(T, "run")]


async def _entitle(tenant_id):
    from billing.billing.revops import TenantEntitlementRepository

    await TenantEntitlementRepository().insert(f"ent_{tenant_id}", {
        "tenant_id": tenant_id, "feature_key": "derivatives.enabled", "enabled": True,
    })


def _recording_meter(sink):
    async def meter(tenant_id, result, *, kind, include_live):
        sink.append((tenant_id, kind))
    return meter


async def test_route_requires_the_derivatives_entitlement(monkeypatch):
    from fastapi import HTTPException

    from config.settings import settings
    from intelligence.propagation import routes

    monkeypatch.setattr(settings, "social360", SimpleNamespace(propagation_lens_enabled=True))
    tenant = SimpleNamespace(tenant_id="tenant_unentitled", require_permission=lambda p: None)
    body = routes.PropagationRunRequest(window_start=at(0).isoformat(), window_end=at(10).isoformat())
    with pytest.raises(HTTPException) as exc:
        await routes.create_propagation_run(body, SimpleNamespace(state=SimpleNamespace(tenant=tenant)))
    assert exc.value.status_code == 403 and exc.value.detail["code"] == "derivatives_not_entitled"


async def test_meter_records_one_idempotent_usage_event_per_run():
    from billing.billing.revops import UsageMeteringEventRepository
    from intelligence.propagation import routes

    result = SimpleNamespace(run_id="prun_meter_1", episodes=())
    await routes._meter("tenant_meter", result, kind="run", include_live=False)
    await routes._meter("tenant_meter", result, kind="run", include_live=False)
    rows = await UsageMeteringEventRepository().find_many(
        filters={"tenant_id": "tenant_meter", "event_type": "propagation_run_computed"}, limit=10,
    )
    assert len(rows) <= 1


async def test_capped_link_population_is_a_run_limitation():
    class CappedLinks(FakeLinks):
        async def subjects_by_account_bounded(self, tenant_id):
            return await self.subjects_by_account(tenant_id), True

    src, _, _ = sources()
    src._links = CappedLinks()
    result = await PropagationService(src).run(query())
    assert "venue_account_link_scan_capped" in result.limitations


# ── Saved runs: staleness, recompute, erasure ────────────────────────────────

class FakeGrant:
    def __init__(self, status="active"):
        self.status = SimpleNamespace(value=status)
        self.revoked_at = None if status == "active" else "2026-11-20T00:00:00+00:00"
        # Fields the current-permission rule reads (a tenant BYOD grant).
        self.tenant_id = T
        self.connector_class = "tenant_byod_data"
        self.tenant_lake_allowed = True


class FakeGrants:
    def __init__(self):
        self.status = {"drg_1": "active"}

    async def get_grant(self, grant_id, tenant_id=None):
        return FakeGrant(self.status[grant_id]) if grant_id in self.status else None


class BoundedLinks(FakeLinks):
    def __init__(self):
        self.extra = {}

    async def subjects_by_account_bounded(self, tenant_id):
        return {**(await self.subjects_by_account(tenant_id)), **self.extra}, False


def _store(links, grants):
    from intelligence.propagation.runs import PropagationRunStore
    from intelligence.propagation.service import PropagationService
    from repositories.repos import PropagationRunRepository

    PropagationRunRepository()._store.clear()

    def factory():
        src, _, _ = sources(grants=grants)
        src._links = links
        return PropagationService(src)

    return PropagationRunStore(link_service=links, grant_service=grants, service_factory=factory), factory


async def test_saved_run_is_fresh_then_stale_after_revocation_or_link_change():
    links, grants = BoundedLinks(), FakeGrants()
    store, factory = _store(links, grants)
    service = factory()
    run = await service.run(query())
    record = await store.save(run, service.last_inputs, include_live=False)
    assert record["grant_refs"] == ["drg_1"]
    assert {"u1", "u2"} <= set(record["subject_refs"])
    assert (await store.get(T, run.run_id))["stale"] is False

    links.extra = {("hyperliquid", "0x99"): "u99"}
    assert (await store.get(T, run.run_id))["stale_reasons"] == ["linked_population_changed"]
    links.extra = {}
    grants.status["drg_1"] = "revoked"
    assert (await store.get(T, run.run_id))["stale_reasons"] == ["source_grant_revoked"]
    assert await store.get("another_tenant", run.run_id) is None


async def test_recompute_saves_a_superseding_run():
    links, grants = BoundedLinks(), FakeGrants()
    store, factory = _store(links, grants)
    service = factory()
    run = await service.run(query())
    await store.save(run, service.last_inputs, include_live=False)
    # A newly linked account changes the effective inputs, so the recompute is a
    # different run that supersedes the saved one.
    links.extra[("hyperliquid", "0x99")] = "u99"
    new = await store.recompute(T, run.run_id)
    assert new["run_id"] != run.run_id
    assert new["supersedes"] == run.run_id
    assert {r["run_id"] for r in await store.list(T)} == {run.run_id, new["run_id"]}


async def test_erasure_deletes_runs_naming_the_subject():
    from governance.consent.erasure_planes import (
        PROPAGATION_RUNS_COMPONENT,
        ErasureSubject,
        erase_propagation_runs_plane,
    )

    links, grants = BoundedLinks(), FakeGrants()
    store, factory = _store(links, grants)
    service = factory()
    run = await service.run(query())
    await store.save(run, service.last_inputs, include_live=False)
    receipts = await erase_propagation_runs_plane(ErasureSubject(tenant_id=T, user_id="u2"))
    assert receipts[PROPAGATION_RUNS_COMPONENT].records_impacted == 1
    assert await store.get(T, run.run_id) is None


async def test_fills_under_a_revoked_grant_leave_every_later_computation():
    """Admission when stored is not ongoing permission (Codex P1 on #896)."""
    grants = FakeGrants()
    src, _, _ = sources(grants=grants)
    before = await PropagationService(src).run(query())
    assert before.episodes and before.episodes[0].adopters

    grants.status["drg_1"] = "revoked"
    src_after, _, _ = sources(grants=grants)
    after = await PropagationService(src_after).run(query())
    assert "revoked_grant_fills_excluded" in after.limitations
    assert not any(ep.adopters for ep in after.episodes)


async def test_unreadable_grant_authority_excludes_fills_with_a_reason():
    async def broken(grant_id, tenant_id=None):
        raise RuntimeError("rights store down")

    src = RepositoryPropagationSources(
        link_service=FakeLinks(), fill_repo=FakeFills(), graph_client=FakeGraph(),
        pool_factory=lambda: None, grant_lookup=broken,
    )
    bundle = await src.load(query())
    assert bundle.fill_events == []
    assert "fill_grant_authority_unavailable" in bundle.reasons


async def test_unchanged_recompute_keeps_the_saved_run_intact():
    """An identical recompute must not overwrite or supersede itself (Codex P2 on #896)."""
    links, grants = BoundedLinks(), FakeGrants()
    store, factory = _store(links, grants)
    service = factory()
    run = await service.run(query())
    saved = await store.save(run, service.last_inputs, include_live=False)

    again = await store.recompute(T, run.run_id)
    assert again["run_id"] == run.run_id
    assert again.get("supersedes") is None
    assert again["saved_at"] == saved["saved_at"]
    assert again["stale"] is False


async def test_dydx_default_subaccount_fills_attribute_to_the_linked_address():
    """dYdX keys fills ``acct_<addr>_0``; attribution must still find the link (Codex P2 on #896)."""
    from intelligence.propagation.adoption import adoptions_from_fill_events

    class DydxLinks:
        async def subjects_by_account(self, tenant_id):
            return {("dydx", "dydx1abc"): "u7"}

    class DydxFills(FakeFills):
        def __init__(self):
            self.rows = [{
                "tenant_id": T, "trading_account_id": "acct_dydx1abc_0",
                "canonical_market_id": "dydx:mainnet:BTC-USD", "fill_id": "d1", "side": "buy",
                "price": "50000", "quantity": "1", "executed_at": at(0),
                "source_refs": ["direction=Open Long", *ADMITTED],
            }]

    src = RepositoryPropagationSources(
        link_service=DydxLinks(), fill_repo=DydxFills(), graph_client=FakeGraph(),
        pool_factory=lambda: None, grant_lookup=FakeGrants().get_grant,
    )
    bundle = await src.load(query())
    assert [e["payload"]["linked_account_ref"] for e in bundle.fill_events] == ["dydx1abc"]
    adoptions, reasons = adoptions_from_fill_events(T, bundle.fill_events, bundle.subjects_by_account)
    assert "fill_account_not_linked" not in reasons
    assert [a.subject_id for a in adoptions] == ["u7"]
