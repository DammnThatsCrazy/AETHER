"""Exploration routes — flag gating, tenant scope, and the /v1/explore family."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from exploration_fakes import FakeGraphNode, FakeGraphResponse, context, fake_graph_runner

from shared.auth.auth import TenantContext
from shared.common.common import ForbiddenError, NotFoundError

TENANT = "t1"


def _request(tenant_id=TENANT, permissions=None):
    tenant = TenantContext(
        tenant_id=tenant_id,
        user_id="u1",
        permissions=permissions if permissions is not None else ["read", "write"],
    )
    return SimpleNamespace(state=SimpleNamespace(tenant=tenant))


def _enable(monkeypatch, enabled=True):
    import services.exploration.routes as routes

    monkeypatch.setattr(
        routes, "settings", SimpleNamespace(exploration=SimpleNamespace(enabled=enabled))
    )


def _patch_graph(monkeypatch, response):
    import services.exploration.adapters.graph as gadapter

    monkeypatch.setattr(gadapter, "run_universal_graph_query", fake_graph_runner(response))


class TestFlagGating:
    async def test_handlers_404_when_flag_off(self, monkeypatch):
        import services.exploration.routes as routes

        _enable(monkeypatch, enabled=False)
        req = _request()
        with pytest.raises(NotFoundError, match="feature not enabled"):
            await routes.validate_context(req, routes.ValidateRequest(context=context("graph")))
        with pytest.raises(NotFoundError, match="feature not enabled"):
            await routes.list_views(req, limit=100, offset=0)


class TestValidate:
    async def test_validate_reports_every_filter(self, monkeypatch):
        import services.exploration.routes as routes

        _enable(monkeypatch)
        ctx = context("graph", [
            {"field": "entity.id", "op": "eq", "value": "e1"},
            {"field": "made.up", "op": "eq", "value": "x"},
        ])
        resp = await routes.validate_context(_request(), routes.ValidateRequest(context=ctx))
        entries = resp.data["applicability"]["entries"]
        assert len(entries) == 2
        assert resp.data["adapter_available"] is True

    async def test_scope_tenant_mismatch_forbidden(self, monkeypatch):
        import services.exploration.routes as routes

        _enable(monkeypatch)
        ctx = context("graph", tenant_id="other-tenant")
        with pytest.raises(ForbiddenError):
            await routes.validate_context(_request(), routes.ValidateRequest(context=ctx))


class TestQueryAndFacets:
    async def test_query_returns_envelope_with_applicability(self, monkeypatch):
        import services.exploration.routes as routes

        _enable(monkeypatch)
        _patch_graph(monkeypatch, FakeGraphResponse([FakeGraphNode("e1"), FakeGraphNode("e2")]))
        ctx = context("graph", [{"field": "entity.id", "op": "eq", "value": "e1"}])
        resp = await routes.query_surface(
            _request(), routes.QueryRequest(context=ctx), graph=None, cache=None
        )
        env = resp.data["envelope"]
        assert env["truth"]["overall_state"] == "ready"
        assert len(env["applicability"]["entries"]) == 1
        assert env["execution"]["adapters"] == ["graph"]

    async def test_unavailable_adapter_uses_canonical_error_truth(self, monkeypatch):
        import services.exploration.routes as routes

        _enable(monkeypatch)
        resp = await routes.query_surface(
            _request(),
            routes.QueryRequest(context=context("temporal_observatory")),
            graph=None,
            cache=None,
        )
        env = resp.data["envelope"]
        assert env["truth"]["overall_state"] == "error"
        assert env["execution"]["adapters"] == []
        assert "surface_backend_not_available_on_this_deployment" in env["warnings"]

    async def test_facets_suppress_small_cohorts(self, monkeypatch):
        import services.exploration.routes as routes

        _enable(monkeypatch)
        nodes = (
            [FakeGraphNode(f"big{i}", {"city": "Metropolis"}) for i in range(30)]
            + [FakeGraphNode(f"sm{i}", {"city": "Smallville"}) for i in range(5)]
        )
        _patch_graph(monkeypatch, FakeGraphResponse(nodes))
        ctx = context("geo")
        resp = await routes.facet_surface(
            _request(), routes.FacetRequest(context=ctx, fields=["geography.city"]),
            graph=None, cache=None,
        )
        facet = resp.data["envelope"]["data"]["facets"][0]
        assert [b["value"] for b in facet["buckets"]] == ["Metropolis"]
        assert facet["suppressed_bucket_count"] == 1


class TestSavedViews:
    async def test_view_roundtrip_and_tenant_isolation(self, monkeypatch):
        import services.exploration.routes as routes

        _enable(monkeypatch)
        req = _request()
        created = await routes.upsert_view(
            req, routes.ViewUpsertRequest(name="my view", context=context("graph"))
        )
        view_id = created.data["view"]["view_id"]

        got = await routes.get_view(req, view_id)
        assert got.data["view"]["name"] == "my view"

        listed = await routes.list_views(req, limit=100, offset=0)
        assert len(listed.data["views"]) == 1

        # Another tenant sees nothing and cannot fetch the view.
        other = await routes.list_views(_request("t2"), limit=100, offset=0)
        assert other.data["views"] == []
        with pytest.raises(NotFoundError):
            await routes.get_view(_request("t2"), view_id)

        deleted = await routes.delete_view(req, view_id)
        assert deleted.data["deleted"] == view_id

    async def test_write_requires_write_permission(self, monkeypatch):
        import services.exploration.routes as routes

        _enable(monkeypatch)
        with pytest.raises(Exception):
            await routes.upsert_view(
                _request(permissions=["read"]),
                routes.ViewUpsertRequest(name="x", context=context("graph")),
            )


class TestLinkResolver:
    async def test_link_retargets_surface_and_reports_applicability(self, monkeypatch):
        import services.exploration.routes as routes

        _enable(monkeypatch)
        # A device filter is applied on graph but not-applicable on temporal_observatory.
        ctx = context("graph", [{"field": "device.os", "op": "eq", "value": "ios"}])
        resp = await routes.resolve_link(
            _request(), routes.LinkResolveRequest(context=ctx, to="temporal_observatory")
        )
        assert resp.data["link"]["to"] == "temporal_observatory"
        assert resp.data["link"]["context"]["scope"]["surface"] == "temporal_observatory"
        entry = resp.data["applicability"]["entries"][0]
        assert entry["disposition"] == "not_applicable"
        assert resp.data["adapter_available"] is False
