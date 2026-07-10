"""Route-level tests: feature-flag 404s, tenant isolation, intake path,
permission gates, and graph mutation shapes."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

TENANT = "t-stable-a"
OTHER_TENANT = "t-stable-b"
USDC_BASE = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"

_FLAGS_ON = SimpleNamespace(
    ingestion_enabled=True, valuation_enabled=True, flows_enabled=True,
    graph_enabled=True, profile360_enabled=True, api_enabled=True,
    noesis_enabled=True, kyber_enabled=True,
)
_FLAGS_OFF = SimpleNamespace(
    ingestion_enabled=False, valuation_enabled=False, flows_enabled=False,
    graph_enabled=False, profile360_enabled=False, api_enabled=False,
    noesis_enabled=False, kyber_enabled=False,
)


class _FakeTenant:
    def __init__(self, tenant_id: str, permissions: set[str] | None = None):
        self.tenant_id = tenant_id
        self.is_platform_admin = False
        self._permissions = permissions

    def require_permission(self, perm: str) -> None:
        if self._permissions is not None and perm not in self._permissions:
            raise PermissionError(f"missing {perm}")


def _build_app(tenant: _FakeTenant) -> TestClient:
    from services.stablecoin.routes import router

    app = FastAPI()

    @app.exception_handler(PermissionError)
    async def _perm(request, exc):
        return JSONResponse(status_code=403, content={"error": str(exc)})

    app.include_router(router)

    @app.middleware("http")
    async def _inject_tenant(request: Request, call_next):
        request.state.tenant = tenant
        return await call_next(request)

    return TestClient(app)


def _observation_payload(index: int = 1) -> dict:
    return {
        "observation_type": "transfer",
        "chain_id": "eip155:8453",
        "transaction_hash": "0x" + f"{index:064x}",
        "log_or_instruction_index": index,
        "contract_or_mint": USDC_BASE,
        "amount_atomic": "1000000",
        "from_address": "0xfrom",
        "to_address": "0xto",
        "observed_at": "2026-07-08T12:00:00+00:00",
    }


def test_flag_off_returns_404(monkeypatch):
    from config.settings import settings

    monkeypatch.setattr(settings, "stablecoin", _FLAGS_OFF)
    client = _build_app(_FakeTenant(TENANT))
    assert client.get("/v1/stablecoins/assets").status_code == 404
    assert client.post("/v1/stablecoins/observations", json=_observation_payload()).status_code == 404


def test_ingest_and_list_with_tenant_isolation(monkeypatch):
    from config.settings import settings

    monkeypatch.setattr(settings, "stablecoin", _FLAGS_ON)

    client_a = _build_app(_FakeTenant(TENANT))
    created = client_a.post("/v1/stablecoins/observations", json=_observation_payload(1))
    assert created.status_code == 201, created.text
    assert created.json()["inserted"] is True

    replay = client_a.post("/v1/stablecoins/observations", json=_observation_payload(1))
    assert replay.json()["inserted"] is False

    listed = client_a.get("/v1/stablecoins/observations")
    assert listed.status_code == 200
    assert listed.json()["count"] == 1

    client_b = _build_app(_FakeTenant(OTHER_TENANT))
    other = client_b.get("/v1/stablecoins/observations")
    assert other.json()["count"] == 0  # tenant isolation


def test_execution_claim_is_rejected(monkeypatch):
    from config.settings import settings

    monkeypatch.setattr(settings, "stablecoin", _FLAGS_ON)
    client = _build_app(_FakeTenant(TENANT))
    payload = _observation_payload(2)
    payload["execution_by_aether"] = True
    response = client.post("/v1/stablecoins/observations", json=payload)
    assert response.status_code == 422


def test_cross_tenant_payload_is_rejected(monkeypatch):
    from config.settings import settings

    monkeypatch.setattr(settings, "stablecoin", _FLAGS_ON)
    client = _build_app(_FakeTenant(TENANT))
    payload = _observation_payload(3)
    payload["tenant_id"] = OTHER_TENANT
    response = client.post("/v1/stablecoins/observations", json=payload)
    assert response.status_code in (403, 422)


def test_support_requires_manage_permission(monkeypatch):
    from config.settings import settings
    from shared.auth.auth import Permissions

    monkeypatch.setattr(settings, "stablecoin", _FLAGS_ON)
    reader = _FakeTenant(TENANT, permissions={Permissions.STABLECOINS_READ})
    client = _build_app(reader)
    response = client.post("/v1/stablecoins/support", json={
        "subject_entity_ref": {"kind": "organization", "id": "org-1"},
        "deployment_id": "usdc:eip155:8453",
        "capability": "accept_payment",
        "support_status": "production_active",
        "evidence_type": "observed_settlement",
    })
    assert response.status_code == 403


def test_graph_mutations_are_tenant_scoped_and_deterministic():
    from services.stablecoin.graph_mutations import build_observation_mutations

    observation = {
        "tenant_id": TENANT,
        "observation_id": "scobs_x",
        "from_wallet_id": "w1",
        "to_wallet_id": "w2",
        "amount_decimal": "1",
        "deployment_id": "usdc:eip155:8453",
        "observed_at": "2026-07-08T12:00:00Z",
    }
    vertices, edges = build_observation_mutations(observation)
    assert all(v.properties.get("tenant_id") == TENANT for v in vertices)
    assert len(edges) == 1
    key_one = edges[0].properties["idempotency_key"]
    _, edges_again = build_observation_mutations(observation)
    assert edges_again[0].properties["idempotency_key"] == key_one

    # Cross-tenant entity refs never produce an H2H edge.
    observation["from_entity_ref"] = {"kind": "human", "id": "h1", "tenant_id": TENANT}
    observation["to_entity_ref"] = {"kind": "human", "id": "h2", "tenant_id": OTHER_TENANT}
    _, edges_mixed = build_observation_mutations(observation)
    assert all(e.edge_type != "SENT_STABLECOIN_TO" for e in edges_mixed)
