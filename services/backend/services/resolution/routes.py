"""
Aether Service — Retired legacy identity-resolution routes.

These three routes failed closed (503) while the legacy graph surface lacked
tenant isolation. The resolution engine, its event consumer and its pending /
audit / config routes were never wired to anything that produced data and are
deleted; identity resolution is owned by ``services.identity``. What remains is
the fail-closed tombstone for the routes a client could still be calling. It is
removed with the last caller (the Aether profile page's identity-cluster read).
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

router = APIRouter(prefix="/v1/resolution", tags=["Identity Resolution"])


def _legacy_graph_unavailable() -> None:
    """Fail closed while this legacy graph surface lacks tenant isolation."""
    raise HTTPException(
        status_code=503,
        detail="Legacy identity graph resolution is unavailable",
    )


@router.get("/cluster/{user_id}")
async def get_cluster(
    user_id: str,
    request: Request,
):
    """Unavailable until the legacy graph cluster read is tenant scoped."""
    _legacy_graph_unavailable()


@router.post("/pending/{decision_id}/approve")
async def approve_resolution(
    decision_id: str,
    request: Request,
):
    """Unavailable until approval uses a tenant-safe graph mutation path."""
    tenant = request.state.tenant
    tenant.require_permission("write")
    _legacy_graph_unavailable()


@router.post("/batch")
async def trigger_batch_job(
    request: Request,
):
    """Unavailable until batch matching uses tenant-safe graph reads."""
    tenant = request.state.tenant
    tenant.require_permission("write")
    _legacy_graph_unavailable()
