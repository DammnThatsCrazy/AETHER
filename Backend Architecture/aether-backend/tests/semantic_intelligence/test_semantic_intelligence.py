from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from fastapi import FastAPI
from shared.common.common import AetherError
from services.semantic_intelligence.models import SemanticObservation, SentimentObservation
from services.semantic_intelligence.routes import router, kyber_router


def test_contract_enforces_canonical_campaign_id():
    with pytest.raises(ValueError):
        SemanticObservation(
            tenant_id="tenant_a",
            source_event_id="evt_1",
            source_type="chat",
            actor_ref="profile_1",
            actor_type="profile",
            primary_subject_ref="product_x",
            campaign_id="external-google-123",
        )


def test_sentiment_requires_target_subject():
    with pytest.raises(ValueError):
        SentimentObservation(
            semantic_observation_id="sem_1",
            tenant_id="tenant_a",
            actor_ref="profile_1",
            target_subject_ref="",
            source_event_id="evt_1",
            valence=0.5,
            arousal=0.5,
        )


def test_end_to_end_semantic_sentiment_and_tenant_isolation():
    app = FastAPI()

    @app.exception_handler(AetherError)
    async def aether_error_handler(request, exc):
        from fastapi.responses import JSONResponse

        return JSONResponse(status_code=exc.code.value, content=exc.to_dict())

    app.include_router(router)
    app.include_router(kyber_router)
    client = TestClient(app)
    body = {
        "source_event_id": "evt_sem_1",
        "source_type": "customer_chat",
        "actor_ref": "profile_1",
        "primary_subject_ref": "product_x",
        "target_type": "product",
        "content": "I support product_x but I am angry about pricing and may cancel.",
        "campaign_id": "camp_123",
        "consent_snapshot_id": "consent_1",
    }
    created = client.post(
        "/v1/semantic/observations", json=body, headers={"x-tenant-id": "tenant_a"}
    )
    assert created.status_code == 200, created.text
    data = created.json()["data"]
    assert data["semantic_observation"]["stance"] == "supportive"
    assert data["sentiment_observations"][0]["target_subject_ref"] == "product_x"
    obs_id = data["semantic_observation"]["observation_id"]

    same_tenant = client.get(
        f"/v1/semantic/observations/{obs_id}", headers={"x-tenant-id": "tenant_a"}
    )
    assert same_tenant.status_code == 200
    other_tenant = client.get(
        f"/v1/semantic/observations/{obs_id}", headers={"x-tenant-id": "tenant_b"}
    )
    assert other_tenant.status_code == 404

    state = client.get("/v1/semantic/entities/product_x", headers={"x-tenant-id": "tenant_a"})
    assert state.status_code == 200
    assert state.json()["data"]["semantic_state"]["observation_count"] >= 1


def _kyber_app(tenant=None) -> TestClient:
    """Bare test app; when a tenant is given, inject it like the auth middleware."""
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


def test_kyber_requires_operator_scope():
    """require_kyber_operator fails closed: 401 unauthenticated, 403 for a
    tenant admin (never an operator), 200 only with the operator permission."""
    from types import SimpleNamespace

    from config.settings import settings

    unauthenticated = _kyber_app().get(
        "/v1/kyber/semantic/fleet-health", headers={"x-tenant-id": "tenant_a"}
    )
    assert unauthenticated.status_code == 401

    tenant_admin = SimpleNamespace(
        tenant_id="tenant_a",
        user_id="user_a",
        permissions=["admin"],
        is_admin=True,
        is_suspended=False,
        has_permission=lambda permission: True,
    )
    denied = _kyber_app(tenant_admin).get("/v1/kyber/semantic/fleet-health")
    assert denied.status_code == 403

    operator_perm = settings.security_governance.kyber_operator_permission
    operator = SimpleNamespace(
        tenant_id="olympus_op",
        user_id="op_1",
        permissions=[operator_perm, "admin"],
        is_admin=True,
        is_suspended=False,
        has_permission=lambda permission: True,
    )
    allowed = _kyber_app(operator).get("/v1/kyber/semantic/fleet-health")
    assert allowed.status_code == 200
    assert allowed.json()["data"]["cross_tenant_contamination"] is False


def test_campaign_graph_population_and_cascade_routes_return_real_observation_data():
    app = FastAPI()

    @app.exception_handler(AetherError)
    async def aether_error_handler(request, exc):
        from fastapi.responses import JSONResponse

        return JSONResponse(status_code=exc.code.value, content=exc.to_dict())

    from services.semantic_intelligence.routes import (
        campaign_router,
        graph_router,
        population_router,
    )

    app.include_router(router)
    app.include_router(campaign_router)
    app.include_router(graph_router)
    app.include_router(population_router)
    client = TestClient(app)
    headers = {"x-tenant-id": "tenant_cascade"}
    for idx, actor in enumerate(["profile_a", "profile_b"]):
        response = client.post(
            "/v1/semantic/observations",
            json={
                "source_event_id": f"evt_cascade_{idx}",
                "source_type": "social_post",
                "actor_ref": actor,
                "primary_subject_ref": "product_y",
                "target_type": "product",
                "content": "I support product_y and recommend the product pricing campaign",
                "campaign_id": "camp_semantic",
            },
            headers=headers,
        )
        assert response.status_code == 200

    impact = client.get("/v1/campaigns/camp_semantic/semantic-impact", headers=headers)
    assert impact.status_code == 200
    assert impact.json()["data"]["observation_count"] == 2

    overlay = client.post(
        "/v1/graph/semantic-overlay", json={"subject_ref": "product_y"}, headers=headers
    )
    assert overlay.status_code == 200
    assert len(overlay.json()["data"]["node_overlays"]) == 2

    compare = client.post(
        "/v1/population/semantic-compare", json={"subjects": ["product_y"]}, headers=headers
    )
    assert compare.status_code == 200
    assert compare.json()["data"]["subjects"][0]["observation_count"] == 2

    cascades = client.get("/v1/semantic/cascades", headers=headers)
    assert cascades.status_code == 200
    assert cascades.json()["data"]["insufficient_data"] is False
    assert cascades.json()["data"]["cascades"][0]["breadth"] == 2
