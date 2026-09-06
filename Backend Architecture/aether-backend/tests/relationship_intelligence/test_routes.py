"""Wave 2d/3b route tests — GET /v1/relationships/* read surface.

Behaviors under test:
* flag OFF => honest content-free ``feature_disabled`` degraded state on every
  route (200, never fabricated data);
* flag ON + consent denied => 403, content-free (no subject/entity/tenant leak);
* flag ON + consent granted => thin read helpers drive 200 envelopes;
* unknown stays null in wire output — never rendered as 0.
"""

from __future__ import annotations

import asyncio
import json
import os

os.environ.setdefault("AETHER_ENV", "local")

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from unittest.mock import MagicMock

from services.relationship_fidelity.engine import FIDELITY_MODE_ENV
from services.relationship_intelligence import consent as _consent
from services.relationship_intelligence.routes import router
from shared.common.common import AetherError
from shared.relationship_spine import flags as _spine_flags

SRC = "src-entity-id"
TGT = "tgt-entity-id"
ROUTE_PREFIX = f"/v1/relationships/{SRC}/{TGT}"


def _make_app(tenant_id: str = "tenant-routes", captured: list | None = None) -> FastAPI:
    app = FastAPI()

    @app.exception_handler(AetherError)
    async def error_handler(request: Request, exc: AetherError) -> JSONResponse:
        return JSONResponse(status_code=exc.code.value, content=exc.to_dict())

    @app.middleware("http")
    async def inject_tenant(request, call_next):
        tenant = MagicMock()
        tenant.tenant_id = tenant_id
        tenant.user_id = "user-test"
        tenant.require_permission = MagicMock()
        request.state.tenant = tenant
        if captured is not None:
            captured.append(tenant)
        return await call_next(request)

    app.include_router(router)
    return app


@pytest.fixture
def client():
    return TestClient(_make_app())


def _set_flag(monkeypatch, value: bool) -> None:
    monkeypatch.setattr(_spine_flags, "social360_enabled", lambda: value)


def _grant_consent() -> None:
    _consent.set_default_consent_provider(lambda **kwargs: True)


def _seed_fidelity(tenant_id: str) -> None:
    from services.relationship_intelligence.coordinator import (
        RelationshipSpineCoordinator,
        materialize_observations,
        relationship_ref_for,
    )

    records = [
        {
            "id": "rt1",
            "predicate": "FOLLOWS",
            "direction": "outgoing",
            "source_key": "src-a",
            "observed_at": "2026-08-01T00:00:00Z",
        },
        {
            "id": "rt2",
            "predicate": "FOLLOWS",
            "direction": "incoming",
            "source_key": "src-b",
            "observed_at": "2026-08-20T00:00:00Z",
        },
    ]

    async def _seed():
        coord = RelationshipSpineCoordinator()
        return await coord.run_for_relationship(
            tenant_id=tenant_id,
            relationship_ref=relationship_ref_for(SRC, TGT),
            source_entity_id=SRC,
            target_entity_id=TGT,
            observations=materialize_observations(records),
            enrich_incentives=False,
        )

    asyncio.run(_seed())


# ---------------------------------------------------------------------------
# Tenant read gate
# ---------------------------------------------------------------------------


def test_routes_enforce_read_permission(monkeypatch):
    _set_flag(monkeypatch, False)
    captured: list = []
    with TestClient(_make_app(captured=captured)) as test_client:
        response = test_client.get(f"{ROUTE_PREFIX}/fidelity")
    assert response.status_code == 200
    assert captured
    assert captured[0].require_permission.call_args.args == ("read",)


# ---------------------------------------------------------------------------
# Flag OFF => feature_disabled on every route
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("suffix", ["/fidelity", "/explain", "/influence"])
def test_flag_off_reports_feature_disabled(client, monkeypatch, suffix):
    _set_flag(monkeypatch, False)
    response = client.get(f"{ROUTE_PREFIX}{suffix}")
    assert response.status_code == 200
    body = response.json()
    assert body["data"]["available"] is False
    assert body["data"]["reason_code"] == "feature_disabled"
    assert body["data"]["degraded"] is True
    # content-free: no relationship-specific payload is fabricated
    assert "vector" not in body["data"]
    assert body["meta"]["relationship_ref"] == f"{SRC}::{TGT}"


# ---------------------------------------------------------------------------
# Flag ON => consent gate
# ---------------------------------------------------------------------------


def test_consent_denied_is_403_and_content_free(client, monkeypatch):
    _set_flag(monkeypatch, True)
    response = client.get(f"{ROUTE_PREFIX}/fidelity")
    assert response.status_code == 403
    text = json.dumps(response.json())
    # content-free: no subject/entity/tenant/consent detail ever leaks
    assert SRC not in text
    assert TGT not in text
    assert "tenant-routes" not in text
    assert "consent" not in text


def test_consent_denied_on_explain_and_influence(client, monkeypatch):
    _set_flag(monkeypatch, True)
    for suffix in ("/explain", "/influence"):
        response = client.get(f"{ROUTE_PREFIX}{suffix}")
        assert response.status_code == 403


def test_consent_granted_fidelity_degrades_honestly_with_no_run(client, monkeypatch):
    _set_flag(monkeypatch, True)
    _grant_consent()
    response = client.get(f"{ROUTE_PREFIX}/fidelity")
    assert response.status_code == 200
    body = response.json()["data"]
    assert body["available"] is False
    assert body["reason_code"] == "no_persisted_fidelity_run"
    assert "vector" not in body  # no fabricated vector when nothing persisted


def test_consent_granted_fidelity_reads_persisted_run(client, monkeypatch):
    _set_flag(monkeypatch, True)
    _grant_consent()
    monkeypatch.setenv(FIDELITY_MODE_ENV, "enforce")
    _seed_fidelity("tenant-routes")
    response = client.get(f"{ROUTE_PREFIX}/fidelity")
    assert response.status_code == 200
    body = response.json()["data"]
    assert body["available"] is True
    assert body["kind"] == "fidelity_vector_surface"
    assert body["vector"]["status"] == "current"
    # unknown stays null — never rendered as 0
    assert body["vector"]["outcome_support"] is None


def test_consent_granted_explain_returns_basis(client, monkeypatch):
    _set_flag(monkeypatch, True)
    _grant_consent()
    response = client.get(f"{ROUTE_PREFIX}/explain")
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["available"] is True
    assert "registered_predicates" in data["sections"]
    assert data["sections"]["motifs"]["state"] == "insufficient_data"
    # honesty: fidelity may be unknown (no run) — never a 0 vector
    assert data["sections"]["fidelity"]["available"] is False


def test_consent_granted_influence_is_empty_not_synthesized(client, monkeypatch):
    _set_flag(monkeypatch, True)
    _grant_consent()
    response = client.get(f"{ROUTE_PREFIX}/influence")
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["available"] is False
    assert data["degraded_reason"] == "no_evidence_backed_path"
    decomp = data["decomposition"]
    assert decomp["decision"] == "empty"
    for component in decomp["components"]:
        assert component["value"] is None
