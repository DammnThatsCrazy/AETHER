"""Graph-promotion review resolve — service + route (#6).

With ``graph_promotion_review_enabled`` on, a low-confidence pair is deferred to
a ``graph_promotion_candidate`` review item instead of being auto-projected.
Operator disposition then either promotes exactly that pair's canonical edge
through the governed ``project_pair`` seam (``approve``) or resolves the item
without projecting (``reject``). The Kyber route carries the same fail-closed
workforce authz as the other kyber semantic surfaces.
"""

from __future__ import annotations

import dataclasses
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from config.settings import settings
from repositories.repos import reset_in_memory_stores
from services.semantic_intelligence import graph_projector as projector_mod
from services.semantic_intelligence import service as service_mod
from services.semantic_intelligence.engine import get_store, set_store
from services.semantic_intelligence.graph_projector import project_tenant
from services.semantic_intelligence.repositories.base_fact_repo import (
    SemanticFactRepository,
)
from services.semantic_intelligence.repositories.review_queue_repo import (
    SemanticReviewQueueRepository,
)
from services.semantic_intelligence.routes import kyber_router, router
from services.semantic_intelligence.service import SemanticIntelligenceService
from services.semantic_intelligence.store import DurableSemanticSentimentStore
from shared.common.common import AetherError, ForbiddenError
from shared.graph.graph import EdgeType, GraphClient

TENANT = "tenant_review"
SOURCE = "profile_alice"
TARGET = "prod_widget"


@pytest.fixture(autouse=True)
def _isolate():
    reset_in_memory_stores()
    projector_mod._TENANT_PROJECT_LOCKS.clear()
    original = get_store()
    set_store(DurableSemanticSentimentStore())
    service_mod.set_semantic_service(SemanticIntelligenceService())
    yield
    set_store(original)
    service_mod.set_semantic_service(SemanticIntelligenceService())
    reset_in_memory_stores()
    projector_mod._TENANT_PROJECT_LOCKS.clear()


async def _graph() -> GraphClient:
    client = GraphClient()
    await client.connect()
    return client


async def _semantic_edges(client: GraphClient, source: str) -> list:
    return list(await client.get_edges(source, edge_type=EdgeType.SEMANTIC_RELATES_TO))


def _enforce_review(monkeypatch) -> None:
    monkeypatch.setattr(
        settings,
        "semantic",
        dataclasses.replace(settings.semantic, graph_promotion_review_enabled=True),
    )


async def _upsert_relationship(tenant: str, source: str, target: str, confidence: float) -> None:
    repo = SemanticFactRepository("gold_relationship_semantic_state", mode="gold")
    rel = f"rel:{source}->{target}"
    await repo.upsert(
        {
            "id": f"raw_{tenant}_{source}_{target}",
            "tenant_id": tenant,
            "subject_ref": rel,
            "occurred_at": "2026-01-01T00:00:00+00:00",
            "idempotency_key": f"gold_relationship:{tenant}:{rel}:test",
            "data": {
                "source_ref": source,
                "target_ref": target,
                "relationship_ref": rel,
                "relationship_layer": "EXCLUDED",
                "stance_alignment": 0.5,
                "trust_signal": 0.5,
                "interaction_quality": "positive",
                "influence_direction": "source_to_target",
                "confidence": confidence,
                "reducer_version": "weighted-reducer.v1",
                "valid_from": "2026-01-01T00:00:00+00:00",
            },
        }
    )


async def _enqueue_candidate(monkeypatch, client: GraphClient) -> str:
    """Defer a low-confidence pair and return the review item id."""
    _enforce_review(monkeypatch)
    await _upsert_relationship(TENANT, SOURCE, TARGET, confidence=0.1)
    report = await project_tenant(TENANT, graph_client=client)
    assert report.deferred_review == 1
    assert report.projected == 0
    items = await SemanticReviewQueueRepository().list_open(TENANT, "graph_promotion_candidate")
    assert len(items) == 1
    return items[0]["id"]


# ── service: approve / reject ────────────────────────────────────────────────


async def test_resolve_approve_projects_pair_and_resolves_item(monkeypatch):
    client = await _graph()
    item_id = await _enqueue_candidate(monkeypatch, client)
    service = service_mod.get_semantic_service()

    result = await service.resolve_promotion_candidate(
        TENANT, item_id, "approve", graph_client=client
    )

    assert result is not None
    assert result["disposition"] == "approved"
    assert result["projected"] is True
    assert result["resolved"] is True
    # The deferred pair's canonical edge is now live in the graph.
    live = [e for e in await _semantic_edges(client, SOURCE) if not e.properties.get("revoked")]
    assert [e.to_vertex_id for e in live] == [TARGET]
    # The review item is no longer open.
    assert await SemanticReviewQueueRepository().list_open(TENANT, "graph_promotion_candidate") == []


async def test_resolve_reject_resolves_item_without_projecting(monkeypatch):
    client = await _graph()
    item_id = await _enqueue_candidate(monkeypatch, client)
    service = service_mod.get_semantic_service()

    result = await service.resolve_promotion_candidate(
        TENANT, item_id, "reject", graph_client=client
    )

    assert result is not None
    assert result["disposition"] == "rejected"
    assert result["projected"] is False
    assert result["resolved"] is True
    # Nothing was projected for the rejected pair...
    assert await _semantic_edges(client, SOURCE) == []
    # ...and the item is resolved (removed from the open queue).
    assert await SemanticReviewQueueRepository().list_open(TENANT, "graph_promotion_candidate") == []


async def test_resolve_unknown_item_returns_none(monkeypatch):
    _enforce_review(monkeypatch)
    service = service_mod.get_semantic_service()
    result = await service.resolve_promotion_candidate(
        TENANT, "srq_does_not_exist", "approve", graph_client=await _graph()
    )
    assert result is None


async def test_resolve_approve_consent_restricted_pair_is_forbidden(monkeypatch):
    """A pair consent-restricted AFTER deferral can never be promoted (fail-closed).

    Approval re-reads the pair's CURRENT Gold row; a ``consent_restricted`` status
    (e.g. a DSR revocation landing while the item sat in review) must abort the
    promotion with ``ForbiddenError`` — never project a revoked-consent edge — and
    must not resolve the item, so an operator can still reject it.
    """
    client = await _graph()
    item_id = await _enqueue_candidate(monkeypatch, client)
    rel = f"rel:{SOURCE}->{TARGET}"
    restricted = await SemanticFactRepository(
        "gold_relationship_semantic_state", mode="gold"
    ).tombstone_by_subject(TENANT, rel)
    assert restricted == 1
    service = service_mod.get_semantic_service()

    with pytest.raises(ForbiddenError):
        await service.resolve_promotion_candidate(
            TENANT, item_id, "approve", graph_client=client
        )

    # Fail-closed: nothing projected, and the item stays OPEN for re-disposition.
    assert await _semantic_edges(client, SOURCE) == []
    still_open = await SemanticReviewQueueRepository().list_open(
        TENANT, "graph_promotion_candidate"
    )
    assert len(still_open) == 1


# ── route: workforce authz ───────────────────────────────────────────────────


def _kyber_app(tenant=None) -> TestClient:
    app = FastAPI()

    @app.exception_handler(AetherError)
    async def aether_error_handler(request, exc):
        from fastapi.responses import JSONResponse

        return JSONResponse(status_code=exc.code.value, content=exc.to_dict())

    if tenant is not None:

        @app.middleware("http")
        async def _inject_tenant(request, call_next):
            request.state.tenant = tenant
            return await call_next(request)

    app.include_router(router)
    app.include_router(kyber_router)
    return TestClient(app)


def test_resolve_route_requires_workforce_operator():
    # Unauthenticated: require_kyber_operator fails closed with 401.
    unauthenticated = _kyber_app().post(
        "/v1/kyber/semantic/review-queue/srq_x/resolve",
        json={"disposition": "approve"},
        headers={"x-tenant-id": "tenant_a"},
    )
    assert unauthenticated.status_code == 401

    # A plain tenant admin is not a Kyber operator: 403.
    tenant_admin = SimpleNamespace(
        tenant_id="tenant_a",
        user_id="user_a",
        permissions=["admin"],
        is_admin=True,
        is_suspended=False,
        has_permission=lambda permission: True,
    )
    denied = _kyber_app(tenant_admin).post(
        "/v1/kyber/semantic/review-queue/srq_x/resolve",
        json={"disposition": "approve"},
    )
    assert denied.status_code == 403


def test_resolve_route_operator_validates_disposition_and_missing_item():
    operator_perm = settings.security_governance.kyber_operator_permission
    operator = SimpleNamespace(
        tenant_id="olympus_op",
        user_id="op_1",
        permissions=[operator_perm, "admin"],
        is_admin=True,
        is_suspended=False,
        has_permission=lambda permission: True,
    )
    app = _kyber_app(operator)

    # An operator is past authz: a bad disposition is a 400.
    bad = app.post(
        "/v1/kyber/semantic/review-queue/srq_x/resolve",
        json={"disposition": "maybe"},
    )
    assert bad.status_code == 400

    # A well-formed disposition for a non-existent item is a 404.
    missing = app.post(
        "/v1/kyber/semantic/review-queue/srq_missing/resolve",
        json={"disposition": "approve"},
    )
    assert missing.status_code == 404
