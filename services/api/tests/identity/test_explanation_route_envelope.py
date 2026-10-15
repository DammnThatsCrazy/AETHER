"""The explanation route answers 200 with the standard envelope, not a response-validation 500."""

from __future__ import annotations

import dataclasses
import types

from fastapi import FastAPI
from fastapi.testclient import TestClient

from config.settings import settings
from identity.identity import routes

PAYLOAD = {
    "canonical_entity_id": "ent-1",
    "confidence": 0.93,
    "confidence_band": "high",
    "source_identities": [],
    "positive_evidence": [],
    "negative_evidence": [],
    "ignored_evidence": [],
    "graph_version": "v1",
    "resolution_decision_summary": "linked by verified email",
}


class _Explainability:
    async def get_profile_identity_explanation(self, profile_id, tenant_id):
        return dict(PAYLOAD)


def _client(monkeypatch) -> TestClient:
    enabled = dataclasses.replace(settings.identity_continuity, explainability_enabled=True)
    monkeypatch.setattr(settings, "identity_continuity", enabled, raising=False)
    app = FastAPI()
    app.include_router(routes.router)
    app.dependency_overrides[routes._get_explainability_service] = lambda: _Explainability()

    @app.middleware("http")
    async def tenant(request, call_next):
        request.state.tenant = types.SimpleNamespace(tenant_id="t-1", require_permission=lambda p: None)
        return await call_next(request)

    return TestClient(app)


def test_explanation_is_returned_in_the_standard_envelope(monkeypatch):
    response = _client(monkeypatch).get("/v1/identity/profiles/p-1/identity/explanation")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "success"
    assert body["data"]["canonical_entity_id"] == "ent-1"
