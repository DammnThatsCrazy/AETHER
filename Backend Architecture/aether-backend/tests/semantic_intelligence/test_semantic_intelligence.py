from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from fastapi import FastAPI
from shared.auth.auth import TenantContext
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


def test_kyber_requires_operator_scope():
    app = FastAPI()

    @app.exception_handler(AetherError)
    async def aether_error_handler(request, exc):
        from fastapi.responses import JSONResponse

        return JSONResponse(status_code=exc.code.value, content=exc.to_dict())

    @app.middleware("http")
    async def tenant_context(request, call_next):
        permissions = []
        if request.headers.get("x-test-operator") == "true":
            permissions.append("kyber:operator")
        request.state.tenant = TenantContext(
            tenant_id=request.headers.get("x-tenant-id", "tenant_a"),
            permissions=permissions,
        )
        return await call_next(request)

    app.include_router(router)
    app.include_router(kyber_router)
    client = TestClient(app)
    denied = client.get("/v1/kyber/semantic/fleet-health", headers={"x-tenant-id": "tenant_a"})
    assert denied.status_code == 403
    spoofed = client.get(
        "/v1/kyber/semantic/fleet-health",
        headers={"x-tenant-id": "tenant_a", "x-kyber-operator": "true"},
    )
    assert spoofed.status_code == 403
    allowed = client.get(
        "/v1/kyber/semantic/fleet-health",
        headers={"x-tenant-id": "olympus", "x-test-operator": "true"},
    )
    assert allowed.status_code == 200
    assert allowed.json()["data"]["cross_tenant_contamination"] is False
