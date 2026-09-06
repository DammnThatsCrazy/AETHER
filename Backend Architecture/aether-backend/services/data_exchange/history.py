"""Data Exchange Plane — unified artifact history (M4).

Sub-router under ``/v1/data-exchange/artifacts``.  A **read adapter** over the
M1 ``data_artifacts`` repository: it renders canonical envelope state (artifact
statuses, formats, directions) in the Data Exchange vocabulary for the M6
history surface.  No engine logic lives here.

Route map (frozen in ``docs/plans/data-exchange-api.md`` M4):

- ``GET /v1/data-exchange/artifacts``           → ``{artifacts:[...], count}``
  — unified history across imports/exports/reports/transfers from
  ``data_artifacts`` (query ``limit, offset, direction?, artifact_type?,
  status_filter?``).  This is the **M6 unified-history source.**
- ``GET /v1/data-exchange/artifacts/{artifact_id}`` → full
  ``DataArtifactContract``-shaped meta.

Both routes are tenant-scoped: every read is rooted at the authenticated tenant
id and the repository refuses cross-tenant rows.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Query, Request

from repositories.data_artifacts import (
    DataArtifactRepository,
    get_data_artifact_repository,
)
from services.data_exchange.authz import require_data_exchange
from services.data_exchange.routes_export import artifact_payload
from shared.logger.logger import get_logger

logger = get_logger("aether.data_exchange.history")

router = APIRouter(
    prefix="/v1/data-exchange/artifacts", tags=["Data Exchange — Artifacts"]
)


def _tenant(request: Request) -> object:
    tenant = request.state.tenant
    require_data_exchange(tenant, "data_exchange.read", "admin")
    return tenant


# ── core logic (DB-free testable) ───────────────────────────────────────────


async def list_artifacts_history(
    tenant_id: str,
    *,
    limit: int = 50,
    offset: int = 0,
    direction: Optional[str] = None,
    artifact_type: Optional[str] = None,
    status_filter: Optional[str] = None,
    artifact_repo: Optional[DataArtifactRepository] = None,
) -> dict:
    """Unified artifact history for one tenant across all directions/types."""
    repo = artifact_repo if artifact_repo is not None else get_data_artifact_repository()
    rows = await repo.list_for_tenant(
        tenant_id,
        limit=limit,
        offset=offset,
        direction=direction,
        artifact_type=artifact_type,
        status=status_filter,
    )
    return {"artifacts": [artifact_payload(r) for r in rows], "count": len(rows)}


async def get_artifact_history(
    tenant_id: str,
    artifact_id: str,
    *,
    artifact_repo: Optional[DataArtifactRepository] = None,
) -> dict:
    """Full DataArtifactContract-shaped meta for one artifact (tenant-scoped)."""
    repo = artifact_repo if artifact_repo is not None else get_data_artifact_repository()
    row = await repo.get(tenant_id, artifact_id)
    return artifact_payload(row)


# ── routes ──────────────────────────────────────────────────────────────────


@router.get("")
async def list_artifacts_route(
    request: Request,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    direction: Optional[str] = Query(default=None),
    artifact_type: Optional[str] = Query(default=None, alias="artifact_type"),
    status_filter: Optional[str] = Query(default=None, alias="status_filter"),
):
    """Unified artifact history — the M6 unified-history feed."""
    tenant = _tenant(request)
    return await list_artifacts_history(
        tenant.tenant_id,
        limit=limit,
        offset=offset,
        direction=direction,
        artifact_type=artifact_type,
        status_filter=status_filter,
    )


@router.get("/{artifact_id}")
async def get_artifact_route(artifact_id: str, request: Request):
    """Full DataArtifactContract-shaped meta for one artifact."""
    tenant = _tenant(request)
    return await get_artifact_history(tenant.tenant_id, artifact_id)
