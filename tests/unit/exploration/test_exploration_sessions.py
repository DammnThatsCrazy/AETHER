"""Exploration sessions + operations — persistence, orchestration, routes, S1.

Covers the tenant-qualified session repository, the service orchestration
(OPEN is the initialization op with ``op_number=0`` and no history record;
every other op appends a record and bumps ``op_count``; rejected ops persist
without mutating current context), the fail-isolated S1 projection-engine
composition (a non-projection surface yields ``projection=None``; a registered
projection without a provider degrades to a static reason; a live provider
composes), and the /v1/explore session/operation route family.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from exploration_fakes import context

from shared.auth.auth import TenantContext
from shared.common.common import ForbiddenError, NotFoundError
from shared.exploration.models import PivotSpec

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


def _session_payload(tenant_id: str, surface: str = "graph") -> dict:
    seed = context(surface, tenant_id=tenant_id)
    return {
        "session_id": "s1",
        "tenant_id": tenant_id,
        "surface": surface,
        "seed_context": seed.model_dump(mode="json"),
        "current_context": seed.model_dump(mode="json"),
        "operations": [],
        "op_count": 0,
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-01-01T00:00:00Z",
    }


class TestSessionRepository:
    async def test_roundtrip_and_tenant_qualification(self):
        from services.exploration.session import ExplorationSessionRepository

        repo = ExplorationSessionRepository()
        stored = await repo.upsert_scoped("t1", "s1", _session_payload("t1"))
        assert stored["session_id"] == "s1"
        assert "id" not in stored  # repo-internal envelope stripped

        got = await repo.get_scoped("t1", "s1")
        assert got is not None
        assert got["surface"] == "graph"

        # The same session id under ANOTHER tenant is a DIFFERENT record.
        await repo.upsert_scoped("t2", "s1", _session_payload("t2", surface="table"))
        other = await repo.get_scoped("t2", "s1")
        assert other["surface"] == "table"
        assert (await repo.get_scoped("t1", "s1"))["surface"] == "graph"

        listed = await repo.list_scoped("t1")
        assert [r["session_id"] for r in listed] == ["s1"]

        assert await repo.delete_scoped("t1", "s1") is True
        assert await repo.get_scoped("t1", "s1") is None
        # t2's record survives the tenant-scoped delete.
        assert await repo.get_scoped("t2", "s1") is not None

    async def test_get_scoped_rechecks_tenant(self):
        from services.exploration.session import ExplorationSessionRepository

        repo = ExplorationSessionRepository()
        # Insert directly under t2's qualified id but with t1's tenant field —
        # a corrupted/foreign row the scoped reader must refuse.
        await repo.insert(repo._record_id("t2", "s1"), _session_payload("t1"))
        assert await repo.find_by_id("t2:s1") is not None  # physically present
        assert await repo.get_scoped("t2", "s1") is None  # tenant mismatch → refused
        assert await repo.get_scoped("t1", "s1") is None  # wrong qualified id

    async def test_to_session_roundtrip(self):
        from services.exploration.session import ExplorationSessionRepository

        repo = ExplorationSessionRepository()
        stored = await repo.upsert_scoped("t1", "s1", _session_payload("t1"))
        session = repo.to_session(stored)
        assert session.session_id == "s1"
        assert session.tenant_id == "t1"
        assert session.operations == []
        assert session.op_count == 0
        assert session.seed_context.scope.tenant_id == "t1"


class TestSessionService:
    async def test_create_and_load_roundtrip(self):
        from services.exploration import service as svc

        seed = context("graph")
        session = await svc.create_session(seed, tenant_id="t1")
        assert session.session_id
        assert session.tenant_id == "t1"
        assert session.surface == "graph"
        assert session.op_count == 0
        assert session.operations == []

        loaded = await svc.load_session("t1", session.session_id)
        assert loaded is not None
        assert loaded.seed_context == seed
        assert loaded.current_context == seed

    async def test_open_is_initialization_op(self):
        from services.exploration import service as svc

        seed = context("graph", [{"field": "entity.type", "op": "eq", "value": "human"}])
        result = await svc.execute_operation(seed, "OPEN", tenant_id="t1")
        assert result.op_number == 0
        assert result.operation == "OPEN"
        assert result.status == "applied"
        assert result.projection is None  # graph is not a projection surface

        session = await svc.load_session("t1", result.session_id)
        assert session is not None
        assert session.op_count == 0  # OPEN records no history
        assert session.operations == []
        assert session.current_context.population == seed.population

    async def test_pivot_appends_record_and_bumps_count(self):
        from services.exploration import service as svc

        opened = await svc.execute_operation(context("graph"), "OPEN", tenant_id="t1")
        sid = opened.session_id
        result = await svc.execute_operation(
            None, "PIVOT", tenant_id="t1", session_id=sid,
            pivot=PivotSpec(target_surface="table"),
        )
        assert result.op_number == 1
        assert result.status == "applied"
        assert result.projection is None

        session = await svc.load_session("t1", sid)
        assert session.op_count == 1
        assert len(session.operations) == 1
        assert session.operations[0].operation == "PIVOT"
        assert session.operations[0].status == "applied"
        assert session.current_context.scope.surface == "table"

    async def test_reset_restores_seed(self):
        from services.exploration import service as svc

        seed = context("graph", [{"field": "entity.type", "op": "eq", "value": "human"}])
        opened = await svc.execute_operation(seed, "OPEN", tenant_id="t1")
        sid = opened.session_id
        await svc.execute_operation(
            None, "PIVOT", tenant_id="t1", session_id=sid,
            pivot=PivotSpec(target_surface="map"),
        )
        result = await svc.execute_operation(None, "RESET", tenant_id="t1", session_id=sid)
        assert result.op_number == 2
        assert result.status == "applied"

        session = await svc.load_session("t1", sid)
        assert session.op_count == 2
        assert len(session.operations) == 2
        assert session.current_context.scope.surface == "graph"
        assert session.current_context.population == seed.population

    async def test_rejected_op_records_without_mutating(self):
        from services.exploration import service as svc

        seed = context("profile360")
        opened = await svc.execute_operation(seed, "OPEN", tenant_id="t1")
        sid = opened.session_id
        result = await svc.execute_operation(
            None, "LENS_ADD", tenant_id="t1", session_id=sid, lens_ids=["bogus_lens"]
        )
        assert result.status == "rejected"
        assert result.reason == "unknown_lens_id:bogus_lens"
        assert result.projection is None

        session = await svc.load_session("t1", sid)
        assert session.op_count == 1  # rejected ops still count
        assert len(session.operations) == 1
        assert session.operations[0].status == "rejected"
        assert session.operations[0].reason == "unknown_lens_id:bogus_lens"
        assert session.current_context == seed  # untouched

    async def test_session_not_found(self):
        from services.exploration import service as svc

        result = await svc.execute_operation(
            None, "PIVOT", tenant_id="t1", session_id="ghost",
            pivot=PivotSpec(target_surface="table"),
        )
        assert result.status == "rejected"
        assert result.reason == "session_not_found"

    async def test_open_requires_seed_context(self):
        from services.exploration import service as svc

        result = await svc.execute_operation(None, "OPEN", tenant_id="t1")
        assert result.status == "rejected"
        assert result.reason == "open_requires_seed_context"

    async def test_tenant_isolation_across_sessions(self):
        from services.exploration import service as svc

        opened = await svc.execute_operation(context("graph"), "OPEN", tenant_id="t1")
        sid = opened.session_id
        assert await svc.load_session("t2", sid) is None
        result = await svc.execute_operation(
            None, "PIVOT", tenant_id="t2", session_id=sid,
            pivot=PivotSpec(target_surface="table"),
        )
        assert result.status == "rejected"
        assert result.reason == "session_not_found"

    async def test_save_and_load_persistence_ops(self):
        from services.exploration import service as svc

        seed = context("graph", [{"field": "entity.type", "op": "eq", "value": "human"}])
        opened = await svc.execute_operation(seed, "OPEN", tenant_id="t1")
        sid = opened.session_id
        await svc.execute_operation(
            None, "PIVOT", tenant_id="t1", session_id=sid,
            pivot=PivotSpec(target_surface="table"),
        )
        saved = await svc.execute_operation(None, "SAVE", tenant_id="t1", session_id=sid)
        assert saved.status == "applied"
        loaded = await svc.execute_operation(None, "LOAD", tenant_id="t1", session_id=sid)
        assert loaded.status == "applied"
        assert loaded.context.scope.surface == "table"


class TestS1Convergence:
    async def test_registered_projection_without_provider_degrades(self):
        from services.exploration import service as svc

        seed = context("profile360")
        result = await svc.execute_operation(seed, "OPEN", tenant_id="t1")
        assert result.status == "degraded"
        assert result.projection == {"available": False, "reason": "provider_unavailable"}
        # Fail-isolated: no exception, no echoed provider diagnostic.
        assert result.reason is None

    async def test_registered_projection_with_provider_composes(self):
        from services.exploration import service as svc
        from services.infrastructure.provider import register_provider
        from shared.intelligence_projections.registry import projection_registry
        from shared.projection_engine.runtime import runtime

        registered = False
        if "infrastructure360" not in runtime.available_projection_ids():
            try:
                register_provider(projection_registry)
                registered = True
            except Exception as exc:  # noqa: BLE001 - environment incompatible
                pytest.skip(f"could not register infrastructure360 provider: {exc}")
        try:
            result = await svc.execute_operation(
                context("infrastructure360"), "OPEN", tenant_id="t1"
            )
            assert result.status == "applied"
            assert result.projection is not None
            assert result.projection["available"] is True
            assert result.projection["digest"]
        finally:
            if registered:
                projection_registry.unregister("infrastructure360")

    async def test_lens_add_then_converges_on_projection_surface(self):
        from services.exploration import service as svc

        seed = context("profile360")
        opened = await svc.execute_operation(seed, "OPEN", tenant_id="t1")
        sid = opened.session_id
        result = await svc.execute_operation(
            None, "LENS_ADD", tenant_id="t1", session_id=sid,
            lens_ids=["standard", "fraud"],
        )
        assert result.status == "degraded"  # profile360 has no provider → degrades
        session = await svc.load_session("t1", sid)
        assert session.current_context.lens_set == ["standard", "fraud"]
        assert session.current_context.temporal_mode == "live"


class TestSessionRoutes:
    async def test_create_get_list_delete_roundtrip(self, monkeypatch):
        import services.exploration.routes as routes

        _enable(monkeypatch)
        req = _request()
        created = await routes.create_session(
            req, routes.SessionCreateRequest(context=context("graph"))
        )
        sid = created.data["session"]["session_id"]
        assert created.data["session"]["op_count"] == 0

        got = await routes.get_session(req, sid)
        assert got.data["session"]["surface"] == "graph"

        listed = await routes.list_sessions(req, limit=100, offset=0)
        assert [s["session_id"] for s in listed.data["sessions"]] == [sid]

        # Another tenant sees nothing and cannot fetch the session.
        other = await routes.list_sessions(_request("t2"), limit=100, offset=0)
        assert other.data["sessions"] == []
        with pytest.raises(NotFoundError):
            await routes.get_session(_request("t2"), sid)

        deleted = await routes.delete_session(req, sid)
        assert deleted.data["deleted"] == sid
        with pytest.raises(NotFoundError):
            await routes.get_session(req, sid)

    async def test_create_scope_tenant_mismatch_forbidden(self, monkeypatch):
        import services.exploration.routes as routes

        _enable(monkeypatch)
        ctx = context("graph", tenant_id="other-tenant")
        with pytest.raises(ForbiddenError):
            await routes.create_session(
                _request(), routes.SessionCreateRequest(context=ctx)
            )

    async def test_write_requires_write_permission(self, monkeypatch):
        import services.exploration.routes as routes

        _enable(monkeypatch)
        with pytest.raises(Exception):
            await routes.create_session(
                _request(permissions=["read"]),
                routes.SessionCreateRequest(context=context("graph")),
            )

    async def test_operations_endpoint_applies_pivot(self, monkeypatch):
        import services.exploration.routes as routes

        _enable(monkeypatch)
        req = _request()
        created = await routes.create_session(
            req, routes.SessionCreateRequest(context=context("graph"))
        )
        sid = created.data["session"]["session_id"]

        resp = await routes.apply_session_operation(
            req,
            sid,
            routes.SessionOperationRequest(
                operation="PIVOT", pivot=PivotSpec(target_surface="table")
            ),
        )
        assert resp.data["result"]["op_number"] == 1
        assert resp.data["result"]["status"] == "applied"
        assert resp.data["session"]["op_count"] == 1
        assert resp.data["session"]["current_context"]["scope"]["surface"] == "table"

    async def test_operations_endpoint_unknown_session_rejects(self, monkeypatch):
        import services.exploration.routes as routes

        _enable(monkeypatch)
        resp = await routes.apply_session_operation(
            _request(),
            "ghost",
            routes.SessionOperationRequest(
                operation="PIVOT", pivot=PivotSpec(target_surface="table")
            ),
        )
        assert resp.data["result"]["status"] == "rejected"
        assert resp.data["result"]["reason"] == "session_not_found"
        assert resp.data["session"] is None

    async def test_session_handlers_404_when_flag_off(self, monkeypatch):
        import services.exploration.routes as routes

        _enable(monkeypatch, enabled=False)
        with pytest.raises(NotFoundError, match="feature not enabled"):
            await routes.list_sessions(_request(), limit=100, offset=0)
        with pytest.raises(NotFoundError, match="feature not enabled"):
            await routes.create_session(
                _request(), routes.SessionCreateRequest(context=context("graph"))
            )
