"""The Tenant Mirror over surfaces that read relational stores, not graph vertices.

Each resolver calls Aether's own route handler under a read-only tenant context,
behind the scoped gateway's gate. So these tests check three things: the mirror's
answer equals the handler's, the reach stays inside one tenant and read-only, and
a failure or a missing identifier never looks like an empty tenant.
"""
from __future__ import annotations

import os
import sys
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest

BACKEND = Path(__file__).resolve().parents[2] / "services" / "api"
sys.path.insert(0, str(BACKEND))
os.environ.setdefault("AETHER_ENV", "local")
os.environ.setdefault("JWT_SECRET", "kyber-mirror-store-test")

from fastapi import Depends, Query  # noqa: E402

from governance.kyber.access.contracts import AccessScope  # noqa: E402
from governance.kyber.access.disclosure import DisclosureLevel  # noqa: E402
from governance.kyber.graph import scoped_gateway, surface_reads  # noqa: E402
from governance.kyber.graph.repository import KyberGraphStore  # noqa: E402
from governance.kyber.graph.scoped_gateway import TENANT_GRAPH_CAPABILITY  # noqa: E402
from governance.kyber.graph.surface_reads import (  # noqa: E402
    NEIGHBORHOOD_SURFACES,
    SURFACE_READ_PARAMS,
    _call,
    _READERS,
    _tenant_request,
)
from governance.kyber.mirror.service import (  # noqa: E402
    SURFACE_VERTEX_TYPES,
    TenantMirrorService,
    reset_gateway,
)
from repositories.repos import reset_in_memory_stores  # noqa: E402
from shared.common.common import BadRequestError, ForbiddenError, NotFoundError, utc_now  # noqa: E402

TENANT = "tenant-store-alpha"
OTHER_TENANT = "tenant-store-beta"
ENV = "test"


class _Context:
    def __init__(self, disclosure: DisclosureLevel, tenant: str = TENANT) -> None:
        self.scope = AccessScope(
            operator_id="op", session_id="sess", device_id="dev", environment=ENV, tenant_id=tenant,
            purpose="incident_response", reason="investigating a reported discrepancy", status="active",
            expires_at=(utc_now() + timedelta(minutes=30)).isoformat(),
        )
        self.capabilities = frozenset({TENANT_GRAPH_CAPABILITY})
        self.granted_disclosure = disclosure
        self.tenant_id = None
        self.environment = ENV
        self.operator_id = "op"
        self.session_id = "sess"
        self.device_id = "dev"

    def masks_identifiers(self) -> bool:
        return self.granted_disclosure <= DisclosureLevel.D2_TENANT_MASKED


def _request(disclosure: DisclosureLevel = DisclosureLevel.D3_TENANT_VISIBLE) -> Any:
    return SimpleNamespace(state=SimpleNamespace(kyber_context=_Context(disclosure)))


@pytest.fixture(autouse=True)
def _world():
    from shared.graph.graph import GraphClient, _InMemoryGraphBackend

    reset_in_memory_stores()
    reset_gateway()
    graph = GraphClient.__new__(GraphClient)
    graph._backend = _InMemoryGraphBackend()
    graph._mode = "local"
    scoped_gateway.set_tenant_graph(graph)
    scoped_gateway.set_store(KyberGraphStore())
    yield graph
    scoped_gateway.reset_store()
    scoped_gateway.reset_tenant_graph()
    reset_in_memory_stores()


async def _group(tenant: str = TENANT) -> str:
    from identity.population.routes import population_repo

    population_id = str(uuid4())
    await population_repo.insert(population_id, {
        "population_id": population_id, "tenant_id": tenant, "name": "Northwind buyers",
        "population_type": "segment", "created_at": utc_now().isoformat(),
    })
    return population_id


# ── Coverage ─────────────────────────────────────────────────────────────────


def test_every_parity_surface_has_a_resolver_and_every_store_surface_a_reader():
    service = TenantMirrorService()
    assert set(service.parity_required_ids()) == set(SURFACE_VERTEX_TYPES) | set(SURFACE_READ_PARAMS)
    assert set(SURFACE_READ_PARAMS) - NEIGHBORHOOD_SURFACES == set(_READERS)


def test_none_of_the_store_surfaces_stays_exempt():
    routes = {entry["aether_route"]: entry for entry in TenantMirrorService().manifest["surfaces"]}
    for route in ("/relationships", "/syndicates", "/journeys", "/episodes", "/communications", "/signals", "/risk"):
        assert routes[route]["tenant_parity_required"] is True
    assert routes["/relationships/:entityId"]["mirror_params"] == ["entity_id"]


@pytest.mark.parametrize("surface", ["signals", "risk", "syndicates", "journeys", "episodes", "communications"])
async def test_each_list_surface_renders_every_source_without_a_failed_read(surface):
    envelope = await TenantMirrorService().render(_request(), tenant_id=TENANT, surface=surface)
    assert envelope.tenantVisible["sources"]
    assert all(value is not None for value in envelope.tenantVisible["sources"].values())
    assert envelope.parity_comparable is True


# ── Parity with the tenant's own handler ─────────────────────────────────────


async def test_the_mirror_returns_exactly_what_the_tenant_handler_returns():
    from identity.population.routes import get_group, list_groups

    population_id = await _group()
    service = TenantMirrorService()
    listed = await service.render(_request(), tenant_id=TENANT, surface="syndicates")
    tenant_answer = await list_groups(request=_tenant_request(TENANT), population_type=None, limit=200)
    assert listed.tenantVisible["sources"]["groups"]["groups"] == tenant_answer["data"]["groups"]
    assert len(tenant_answer["data"]["groups"]) == 1

    detail = await service.render(
        _request(), tenant_id=TENANT, surface="syndicates-syndicateId", params={"syndicate_id": population_id},
    )
    own = await get_group(population_id, _tenant_request(TENANT))
    assert detail.tenantVisible["sources"]["group"] == own["data"]
    assert detail.tenantVisible["params"] == {"syndicate_id": population_id}


async def test_a_surface_reaching_its_page_limit_is_not_comparable(monkeypatch):
    monkeypatch.setitem(surface_reads._READERS, "signals", _limited_signals)
    envelope = await TenantMirrorService().render(_request(), tenant_id=TENANT, surface="signals")
    assert envelope.tenantVisible["truncated"] is True
    assert envelope.parity_comparable is False


async def _limited_signals(reads: Any, params: Any, graph: Any) -> None:
    async def page(request: Any, limit: int = 2) -> list[dict]:
        return [{"id": 1}, {"id": 2}]

    await reads.take("inbox", page, limit=2)


# ── Inside one tenant, read-only ─────────────────────────────────────────────


async def test_a_foreign_id_is_the_same_404_as_a_missing_one():
    foreign = await _group(OTHER_TENANT)
    service = TenantMirrorService()
    for syndicate_id in (foreign, "does-not-exist"):
        with pytest.raises(NotFoundError):
            await service.render(
                _request(), tenant_id=TENANT, surface="syndicates-syndicateId", params={"syndicate_id": syndicate_id},
            )


async def test_a_tenant_outside_the_scope_is_denied_before_any_handler_runs(monkeypatch):
    async def tripwire(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("a handler ran before the gate")

    monkeypatch.setattr(scoped_gateway, "read_tenant_surface", tripwire)
    with pytest.raises(ForbiddenError):
        await TenantMirrorService().render(_request(), tenant_id=OTHER_TENANT, surface="risk")


async def test_the_synthetic_tenant_cannot_write():
    tenant = _tenant_request(TENANT).state.tenant
    tenant.require_permission("read")
    tenant.require_permission("campaign:read")
    for permission in ("write", "admin", "campaign:manage", "notifications:manage"):
        with pytest.raises(ForbiddenError):
            tenant.require_permission(permission)


# ── Refusals, never empty answers ────────────────────────────────────────────


@pytest.mark.parametrize("params", [None, {"syndicate_id": "  "}, {"syndicate_id": "x" * 129}, {"syndicate_id": "a", "x": "b"}])
async def test_a_bad_identifier_is_refused_rather_than_rendered_empty(params):
    with pytest.raises(BadRequestError):
        await TenantMirrorService().render(
            _request(), tenant_id=TENANT, surface="syndicates-syndicateId", params=params,
        )


async def test_a_vertex_surface_refuses_a_parameter_it_does_not_declare():
    with pytest.raises(BadRequestError):
        await TenantMirrorService().render(_request(), tenant_id=TENANT, surface="graph", params={"entity_id": "x"})


async def test_a_failed_source_is_null_and_blocks_comparison(monkeypatch):
    from governance.data_quality import routes as quality

    async def broken(tenant_id: str) -> None:
        raise RuntimeError("database unavailable at 10.0.0.5")

    monkeypatch.setattr(quality.intelligence_quality_service, "overview", broken)
    envelope = await TenantMirrorService().render(_request(), tenant_id=TENANT, surface="risk")
    assert envelope.tenantVisible["sources"]["data_quality"] is None
    assert envelope.parity_comparable is False
    assert "surface:risk:surface_source:data_quality" in envelope.operatorDiagnostics.quality["missing_inputs"]
    assert envelope.operatorDiagnostics.health["state"] == "degraded"


async def test_a_masked_render_hides_every_identifier_and_is_not_comparable():
    population_id = await _group()
    envelope = await TenantMirrorService().render(
        _request(DisclosureLevel.D2_TENANT_MASKED), tenant_id=TENANT, surface="syndicates-syndicateId",
        params={"syndicate_id": population_id},
    )
    rendered = str(envelope.tenantVisible["sources"]) + str(envelope.tenantVisible["params"])
    assert population_id not in rendered and "Northwind" not in rendered and TENANT not in rendered
    assert envelope.parity_comparable is False


def test_masking_is_fail_closed_on_unknown_strings_and_free_form_keys():
    masked = scoped_gateway._mask_tree({
        "status": "open", "created_at": "2026-01-01", "note": "call Ada", "count": 3,
        "metadata": {"ada@example.com": "x"}, "rows": [{"holder": "Ada"}],
    })
    assert masked["status"] == "open" and masked["created_at"] == "2026-01-01" and masked["count"] == 3
    assert masked["note"].startswith("masked:") and masked["rows"][0]["holder"].startswith("masked:")
    assert "ada@example.com" not in masked["metadata"]


async def test_source_names_never_carry_an_identifier(monkeypatch):
    from identity.entities import routes as entities

    async def listed(tenant_id: str, entity_type: Any = None, limit: int = 100) -> list[dict]:
        return [{"entity_id": "ada-secret-id"}]

    monkeypatch.setattr(entities._entities, "list_by_tenant", listed)
    envelope = await TenantMirrorService().render(
        _request(DisclosureLevel.D2_TENANT_MASKED), tenant_id=TENANT, surface="journeys",
    )
    assert "ada-secret-id" not in str(envelope.tenantVisible["sources"])
    assert "ada-secret-id" not in str(envelope.operatorDiagnostics)


# ── Anchored surfaces ────────────────────────────────────────────────────────


async def test_relationships_walk_from_the_anchor_and_a_foreign_anchor_reads_as_not_found(_world):
    from shared.graph.graph import Edge, Vertex

    anchor = Vertex("entity", str(uuid4()), {"tenantId": TENANT, "label": "anchor"})
    neighbour = Vertex("entity", str(uuid4()), {"tenantId": TENANT, "label": "neighbour"})
    foreign = Vertex("entity", str(uuid4()), {"tenantId": OTHER_TENANT, "label": "foreign"})
    for vertex in (anchor, neighbour, foreign):
        await _world._backend.add_vertex(vertex)
    await _world._backend.add_edge(Edge("SIMILAR_TO", anchor.vertex_id, neighbour.vertex_id, {"tenantId": TENANT}))

    service = TenantMirrorService()
    found = await service.render(
        _request(), tenant_id=TENANT, surface="relationships-entityId", params={"entity_id": anchor.vertex_id},
    )
    walk = found.tenantVisible["sources"]["neighborhood"]
    assert walk["found"] is True
    assert [row["vertex_id"] for row in walk["neighbors"]] == [neighbour.vertex_id]

    refused = await service.render(
        _request(), tenant_id=TENANT, surface="relationships", params={"entity_id": foreign.vertex_id},
    )
    assert refused.tenantVisible["sources"]["neighborhood"]["found"] is False


# ── Handler invocation ───────────────────────────────────────────────────────


async def test_call_fills_query_defaults_unwraps_data_and_rejects_unset_markers():
    seen: dict[str, Any] = {}

    async def handler(request: Any, limit: int = Query(7), flag: bool = False) -> dict:
        seen.update(limit=limit, flag=flag, tenant=request.state.tenant.tenant_id)
        return {"data": {"ok": True}, "timestamp": "volatile"}

    assert await _call(handler, TENANT) == {"ok": True}
    assert seen == {"limit": 7, "flag": False, "tenant": TENANT}

    async def needs_dependency(request: Any, repo: Any = Depends(dict)) -> None:
        return None

    async def needs_query(request: Any, tenantId: str = Query(...)) -> None:
        return None

    async def needs_path_value(request: Any, group_id: str) -> None:
        return None

    for handler_with_marker in (needs_dependency, needs_query, needs_path_value):
        with pytest.raises(TypeError):
            await _call(handler_with_marker, TENANT)
