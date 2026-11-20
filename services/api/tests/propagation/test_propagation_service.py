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


class FakeFills:
    def __init__(self):
        self.rows = [
            {"tenant_id": T, "trading_account_id": "acct_0x1", "canonical_market_id": "hyperliquid:mainnet:HYPE",
             "fill_id": "f1", "side": "buy", "price": "40", "quantity": "2", "executed_at": at(0),
             "source_refs": ["direction=Open Long"]},
            {"tenant_id": T, "trading_account_id": "acct_0x2", "canonical_market_id": "hyperliquid:mainnet:HYPE",
             "fill_id": "f2", "side": "buy", "price": "41", "quantity": "1", "executed_at": at(45),
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


def sources(pool_rows=()):
    pool = FakePool(list(pool_rows))

    async def pool_factory():
        return pool

    graph = FakeGraph()
    return RepositoryPropagationSources(
        link_service=FakeLinks(), fill_repo=FakeFills(), graph_client=graph, pool_factory=pool_factory,
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


async def test_unavailable_sources_degrade_with_reasons():
    class BrokenGraph:
        async def get_edges_for_tenant(self, *a, **k):
            raise RuntimeError("down")

    async def no_pool():
        return None

    src = RepositoryPropagationSources(
        link_service=FakeLinks(), fill_repo=FakeFills(), graph_client=BrokenGraph(), pool_factory=no_pool,
    )
    result = await PropagationService(src).run(query())
    assert "canonical_graph_authority_unavailable" in result.limitations
    assert "in_app_exposure_store_unavailable" in result.limitations
    assert result.episodes[0].metrics.propagation_radius is None


async def test_live_pull_uses_read_only_adapter_factory():
    pulled = []

    class FakeAdapter:
        def __init__(self, venue, account):
            pulled.append((venue, account))

        async def pull_events(self):
            return [], {"provider_health": "ok"}

    src, _, _ = sources()
    src._adapter_factory = FakeAdapter
    await PropagationService(src).run(query(), include_live=True)
    assert pulled and all(v == "hyperliquid" for v, _ in pulled)


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
    monkeypatch.setattr(settings, "social360", SimpleNamespace(propagation_lens_enabled=True))
    monkeypatch.setattr(service, "PropagationService", FakeService)
    tenant = SimpleNamespace(tenant_id=T, require_permission=granted.append)
    request = SimpleNamespace(state=SimpleNamespace(tenant=tenant))
    body = routes.PropagationRunRequest(window_start=at(-60).isoformat(), window_end=at(600).isoformat())
    response = await routes.create_propagation_run(body, request)
    assert seen["tenant"] == T
    assert response["data"]["tenant_id"] == T
    assert set(granted) == {"analytics", "derivatives:read"}
