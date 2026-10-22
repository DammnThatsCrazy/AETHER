from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from config.settings import PredictionMarketConfig
from value.prediction_markets import routes

PAYLOAD = {"venue": "kalshi", "payload": {"ticker": "KX-1", "status": "open", "last_price": 40}}


class _Tenant:
    tenant_id = "t1"

    def require_permission(self, perm):
        return None


def _client(monkeypatch, cfg):
    monkeypatch.setattr("config.settings.settings", SimpleNamespace(prediction_markets=cfg))
    monkeypatch.setattr(routes, "active_tenant_id", lambda request: "t1")
    app = FastAPI()

    @app.middleware("http")
    async def _tenant(request, call_next):
        request.state.tenant = _Tenant()
        return await call_next(request)

    app.include_router(routes.router)
    return TestClient(app)


def test_disabled_by_default_returns_404(monkeypatch):
    r = _client(monkeypatch, PredictionMarketConfig()).post("/v1/prediction-markets/observations/normalize", json=PAYLOAD)
    assert r.status_code == 404


def test_ingestion_without_venue_flag_returns_404(monkeypatch):
    cfg = PredictionMarketConfig(ingestion_enabled=True)
    r = _client(monkeypatch, cfg).post("/v1/prediction-markets/observations/normalize", json=PAYLOAD)
    assert r.status_code == 404


def test_enabled_normalizes_without_persisting(monkeypatch):
    cfg = PredictionMarketConfig(ingestion_enabled=True, kalshi_enabled=True)
    r = _client(monkeypatch, cfg).post("/v1/prediction-markets/observations/normalize", json=PAYLOAD)
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["market_ref"] == "KX-1" and data["persisted"] is False and data["tenant_id"] == "t1"
    assert data["execution_by_aether"] is False


def test_invalid_payload_is_422(monkeypatch):
    cfg = PredictionMarketConfig(ingestion_enabled=True, polymarket_enabled=True)
    body = {"venue": "polymarket", "payload": {"id": "1", "outcomes": '["Y","N"]', "outcomePrices": '["0.5"]'}}
    r = _client(monkeypatch, cfg).post("/v1/prediction-markets/observations/normalize", json=body)
    assert r.status_code == 422
