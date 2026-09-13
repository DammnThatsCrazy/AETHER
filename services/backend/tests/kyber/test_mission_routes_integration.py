"""Route-level integration tests for the mounted ``/v1/kyber/missions`` plane.

The unit suite drives ``MissionService`` and the scope logic directly. These
tests exercise the **HTTP surface**: a scoped FastAPI app that mounts the real
``mission_router`` and asserts the workforce-identity floor guard rejects an
unauthenticated request at the edge (the mission plane never falls back to
tenant auth). Authorized reads and scope enforcement are covered at the service
seam in ``test_mission_reconstruction.py`` / ``test_mission_scope_enforcement.py``.

The plane is flag-gated OFF in production (mounted only when
``KYBER_MISSIONS_ENABLED=true``); here the router is included unconditionally,
which is exactly what the gate does when the flag is on.
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from shared.common.common import AetherError
from services.kyber.ops.mission_routes import router as mission_router


def _client() -> TestClient:
    app = FastAPI()

    @app.exception_handler(AetherError)
    async def _handle(_request: Request, exc: AetherError) -> JSONResponse:
        return JSONResponse(status_code=exc.code.value, content=exc.to_dict())

    app.include_router(mission_router)
    return TestClient(app, raise_server_exceptions=False)


def test_mission_routes_are_mounted_under_the_kyber_prefix() -> None:
    paths = {getattr(r, "path", "") for r in mission_router.routes}
    assert any(p.startswith("/v1/kyber/missions") for p in paths), paths


@pytest.mark.parametrize(
    "method,path",
    [
        ("get", "/v1/kyber/missions"),
        ("get", "/v1/kyber/missions/kms_nonexistent"),
        ("get", "/v1/kyber/missions/kms_nonexistent/timeline"),
        ("get", "/v1/kyber/missions/kms_nonexistent/monitoring"),
    ],
)
def test_mission_reads_deny_unauthenticated_requests(method: str, path: str) -> None:
    """No Kyber workforce session -> the floor guard denies (never tenant auth)."""
    resp = getattr(_client(), method)(path)
    # Denied at the workforce-identity floor: unauthorized/forbidden, and never a
    # 200 or a 404 (which would mean the guard was bypassed or the route missing).
    assert resp.status_code in (401, 403), f"{path} -> {resp.status_code}: {resp.text}"
