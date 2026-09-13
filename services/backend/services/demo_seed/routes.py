from __future__ import annotations

import hmac
import os

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel

from services.security.request_context import require_kyber_operator
from shared.common.common import APIResponse

from .service import DemoSeedService

_LOOPBACK_HOSTS = {"127.0.0.1", "::1", "localhost", "testclient"}


class SeedRequest(BaseModel):
    tenant_id: str
    namespace: str = "aether-demo-v1"


class ResetRequest(SeedRequest):
    confirmation: str


def _authorize_backend_identity(
    request: Request, *, tenant_id: str, permission: str,
) -> None:
    """Require an identity established by the normal backend auth middleware."""
    tenant = getattr(request.state, "tenant", None)
    if tenant is not None:
        if getattr(tenant, "tenant_id", None) != tenant_id:
            raise HTTPException(status_code=403, detail="cross-tenant demo access denied")
        tenant.require_permission(permission)
        return
    # Never trust the mere presence of request.state.operator. The canonical
    # gate verifies the configured kyber:operator grant / workforce context.
    try:
        require_kyber_operator(request)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=401, detail="backend authentication required") from exc


def build_demo_seed_status_router() -> APIRouter:
    """Authenticated status/disclosure endpoint, safe to mount in every env."""
    router = APIRouter(prefix="/v1/demo-seed", tags=["demo-seed-status"])

    @router.get("/status")
    async def status(
        request: Request,
        tenant_id: str | None = None,
        namespace: str = "aether-demo-v1",
    ):
        authenticated_tenant = getattr(request.state, "tenant", None)
        resolved_tenant_id = tenant_id or getattr(
            authenticated_tenant, "tenant_id", None,
        )
        if not resolved_tenant_id:
            raise HTTPException(
                status_code=422,
                detail="tenant_id is required for operator demo status",
            )
        _authorize_backend_identity(
            request, tenant_id=resolved_tenant_id, permission="read",
        )
        return APIResponse(data=await DemoSeedService().status(
            tenant_id=resolved_tenant_id, namespace=namespace,
        )).to_dict()

    return router


def build_demo_seed_mutation_router() -> APIRouter:
    """Authenticated loopback mutation routes for local in-memory backends."""
    environment = os.getenv("AETHER_ENV", "").lower()
    if environment not in {"local", "test"}:
        raise RuntimeError("demo seed mutation routes may only be mounted in local/test")
    expected_token = os.getenv("AETHER_DEMO_ROUTE_TOKEN", "")
    if not expected_token:
        raise RuntimeError("AETHER_DEMO_ROUTE_TOKEN is required to mount demo seed routes")

    router = APIRouter(prefix="/v1/demo-seed", tags=["local-demo-seed-mutations"])

    def authorize(
        request: Request,
        *,
        tenant_id: str,
        token: str,
    ) -> None:
        _authorize_backend_identity(request, tenant_id=tenant_id, permission="write")
        host = request.client.host if request.client else ""
        if host not in _LOOPBACK_HOSTS:
            raise HTTPException(status_code=403, detail="demo seed route is loopback-only")
        if not hmac.compare_digest(token, expected_token):
            raise HTTPException(status_code=401, detail="invalid demo seed route token")

    @router.post("")
    async def seed(body: SeedRequest, request: Request, x_aether_demo_token: str = Header(default="")):
        authorize(request, tenant_id=body.tenant_id, token=x_aether_demo_token)
        return (await DemoSeedService(environment=environment).seed(
            tenant_id=body.tenant_id,
            namespace=body.namespace,
            actor="local-in-process-route",
        )).to_dict()

    @router.get("/verify")
    async def verify(
        tenant_id: str,
        namespace: str,
        request: Request,
        x_aether_demo_token: str = Header(default=""),
    ):
        authorize(request, tenant_id=tenant_id, token=x_aether_demo_token)
        return await DemoSeedService(environment=environment).verify(
            tenant_id=tenant_id, namespace=namespace,
        )

    @router.post("/reset")
    async def reset(body: ResetRequest, request: Request, x_aether_demo_token: str = Header(default="")):
        authorize(request, tenant_id=body.tenant_id, token=x_aether_demo_token)
        return await DemoSeedService(environment=environment).reset(
            tenant_id=body.tenant_id,
            namespace=body.namespace,
            confirmation=body.confirmation,
            actor="local-in-process-route",
        )

    return router
