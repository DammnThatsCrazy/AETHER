"""Loopback-only local development session bootstrap.

This router is mounted only for local/dev backend environments. It creates
real tenant, user, and durable session records and never returns a reusable API
key or a hardcoded credential.
"""
from __future__ import annotations

from fastapi import APIRouter, FastAPI, Request, Response

from config.settings import settings
from repositories.repos import AdminRepository, UserRepository
from services.auth.sessions import session_service
from shared.common.common import APIResponse, ForbiddenError

router = APIRouter(prefix="/v1/auth", tags=["Auth — Local Development"])

_TENANT_ID = "local-development"
_USER_ID = "local-development-user"
_PERMISSIONS = [
    "read",
    "write",
    "ingest",
    "analytics",
    "admin",
    "billing",
    "campaign:manage",
    "consent:manage",
    "agent:manage",
    "agent:approve",
    "kyber:operator",
    "x402:read",
    "x402:write",
]


def mount_development_auth(app: FastAPI, environment: str) -> None:
    """Mount this router only for explicitly local backend profiles."""
    if environment in {"local", "dev"}:
        app.include_router(router)


def _is_loopback(request: Request) -> bool:
    host = request.client.host if request.client else ""
    return host in {"127.0.0.1", "::1", "localhost", "testclient"}


@router.post("/development-session")
async def create_development_session(request: Request, response: Response):
    """Create a random, durable session for a backend-owned local identity."""
    if settings.env.value not in {"local", "dev"}:
        raise ForbiddenError("Development sessions are disabled")
    if not _is_loopback(request):
        raise ForbiddenError("Development sessions require a loopback client")

    await AdminRepository().insert(
        _TENANT_ID,
        {
            "tenant_id": _TENANT_ID,
            "name": "Local development",
            "contact_email": None,
            "plan_tier": "P1",
            "status": "active",
            "data_origin": "local_development_control_plane",
        },
    )
    await UserRepository().insert(
        _USER_ID,
        {
            "user_id": _USER_ID,
            "tenant_id": _TENANT_ID,
            "email": "local-development@localhost.invalid",
            "name": "Local developer",
            "status": "active",
            "auth_provider": "development_session",
        },
    )
    issue = await session_service.create_session(
        _TENANT_ID,
        principal_id=_USER_ID,
        idle_minutes=settings.trust_plane.session_idle_minutes,
        absolute_minutes=settings.trust_plane.session_absolute_minutes,
        permissions=_PERMISSIONS,
        metadata={"source": "loopback_development_session"},
    )
    response.set_cookie(
        key=issue.cookie_name,
        value=issue.token,
        max_age=issue.cookie_max_age,
        httponly=True,
        secure=False,
        samesite="lax",
        path="/",
    )
    return APIResponse(
        data={
            "tenant_id": _TENANT_ID,
            "user_id": _USER_ID,
            "role": "operator",
            "groups": ["local-development"],
            "session": issue.public_dict(),
            "message": "Backend development session created.",
        }
    ).to_dict()
