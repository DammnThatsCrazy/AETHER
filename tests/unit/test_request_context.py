"""Canonical request-context and correlation-header behavior."""
from __future__ import annotations

import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2] / "Backend Architecture" / "aether-backend"
sys.path.insert(0, str(BACKEND))

from shared.context.request_context import (  # noqa: E402
    CORRELATION_HEADER,
    LEGACY_REQUEST_ID_HEADER,
    RequestContext,
    resolve_correlation_id,
)


class _Headers(dict):
    def get(self, key, default=None):  # case-sensitive is fine for these tests
        return super().get(key, default)


class TestCorrelationResolution:
    def test_canonical_header_wins(self):
        headers = _Headers({CORRELATION_HEADER: "corr-1", LEGACY_REQUEST_ID_HEADER: "req-1"})
        assert resolve_correlation_id(headers) == "corr-1"

    def test_legacy_header_accepted(self):
        headers = _Headers({LEGACY_REQUEST_ID_HEADER: "req-2"})
        assert resolve_correlation_id(headers) == "req-2"

    def test_minted_when_absent(self):
        minted = resolve_correlation_id(_Headers())
        assert minted
        assert len(minted) >= 32


class TestRequestContext:
    def test_request_id_aliases_correlation_id(self):
        ctx = RequestContext(correlation_id="corr-9")
        assert ctx.request_id == "corr-9"

    def test_with_tenant_enrichment_is_immutable(self):
        ctx = RequestContext(correlation_id="corr-3", path="/v1/x")
        enriched = ctx.with_tenant("tenant-a", actor_id="user-1", plan_tier="P2")
        assert enriched.tenant_id == "tenant-a"
        assert enriched.actor_id == "user-1"
        assert enriched.plan_tier == "P2"
        assert enriched.correlation_id == "corr-3"
        assert ctx.tenant_id is None  # original untouched

    def test_log_fields(self):
        ctx = RequestContext(correlation_id="corr-4", tenant_id="t1", path="/v1/y")
        fields = ctx.to_log_fields()
        assert fields == {"correlation_id": "corr-4", "tenant_id": "t1", "path": "/v1/y"}


class TestMiddlewareCorrelationEndToEnd:
    """Exercise the real middleware with a minimal app (public path)."""

    def _build_app(self):
        import os

        os.environ.setdefault("AETHER_ENV", "local")
        from fastapi import FastAPI
        from middleware.middleware import register_middleware

        app = FastAPI()
        register_middleware(app)

        @app.get("/v1/health")  # public path — skips auth
        async def health():
            return {"ok": True}

        return app

    def test_correlation_header_roundtrip(self):
        from fastapi.testclient import TestClient

        client = TestClient(self._build_app())
        resp = client.get("/v1/health", headers={CORRELATION_HEADER: "corr-e2e"})
        assert resp.status_code == 200
        assert resp.headers[CORRELATION_HEADER] == "corr-e2e"
        assert resp.headers[LEGACY_REQUEST_ID_HEADER] == "corr-e2e"

    def test_legacy_request_id_roundtrip(self):
        from fastapi.testclient import TestClient

        client = TestClient(self._build_app())
        resp = client.get("/v1/health", headers={LEGACY_REQUEST_ID_HEADER: "req-e2e"})
        assert resp.status_code == 200
        assert resp.headers[CORRELATION_HEADER] == "req-e2e"
        assert resp.headers[LEGACY_REQUEST_ID_HEADER] == "req-e2e"

    def test_both_headers_minted_when_absent(self):
        from fastapi.testclient import TestClient

        client = TestClient(self._build_app())
        resp = client.get("/v1/health")
        assert resp.status_code == 200
        minted = resp.headers[CORRELATION_HEADER]
        assert minted
        assert resp.headers[LEGACY_REQUEST_ID_HEADER] == minted
