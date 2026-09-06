"""Reconciled Control Plane — read-only operator surface (Phase 0).

Mounts under ``/v1/admin/kyber/managed-integrations`` (mounted in main.py behind
``settings.reconciled_control.kyber_route_enabled``, default OFF). Every handler
is operator-gated via :func:`require_kyber_operator` — an Aether tenant can never
read the fleet surface.

Phase-0 scope discipline: this router has **no** POST/PUT/DELETE. It exposes the
durable ``managed_integrations`` registration rows and the evidence ``reconcile_runs``
rows (desired-vs-observed classification + DRAFT change summaries). Nothing here
mutates an integration — applying a ChangeSet is explicitly deferred (CP-08
boundary). The repo singleton injection seam mirrors provider_runtime so tests
can point the routes at an in-memory store.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Query, Request

from shared.common.common import APIResponse, BadRequestError, NotFoundError
from shared.logger.logger import get_logger

from services.managed_integrations.contracts import (
    MANAGED_DRIFT_TYPES,
    MANAGED_INTEGRATION_KINDS,
    RECONCILE_RESULT_VALUES,
)
from services.managed_integrations.repository import (
    get_managed_integration_repository,
    get_reconcile_run_repository,
)

logger = get_logger("aether.managed_integrations.routes")

admin_router = APIRouter(
    prefix="/v1/admin/kyber/managed-integrations",
    tags=["Admin — Kyber Managed Integrations (Reconciled Control Plane)"],
)


def _require_operator(request: Request):
    """Fail-closed Kyber operator gate (Aether tenants denied, not 404'd)."""
    from services.security.request_context import require_kyber_operator

    return require_kyber_operator(request)


def _validate_last_reconcile_result(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    if value not in RECONCILE_RESULT_VALUES:
        raise BadRequestError(
            f"invalid last_reconcile_result {value!r} — expected one of "
            f"{RECONCILE_RESULT_VALUES}"
        )
    return value


def _validate_integration_kind(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    if value not in MANAGED_INTEGRATION_KINDS:
        raise BadRequestError(
            f"invalid integration_kind {value!r} — expected one of the managed "
            f"integration kinds (§6)"
        )
    return value


@admin_router.get("")
async def list_managed_integrations(
    request: Request,
    tenant_id: Optional[str] = Query(default=None, description="Narrow to one tenant"),
    environment_id: Optional[str] = Query(
        default=None, description="Narrow to one environment"
    ),
    integration_kind: Optional[str] = Query(default=None),
    last_reconcile_result: Optional[str] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    """Registered managed integrations (operator aggregate/read).

    No filters -> fleet-wide newest-last-seen-first view. Filters are ANDed.
    ``last_reconcile_result`` accepts the §32 result labels. Rows are durable
    registration facts (``managed_integrations``), never derived.
    """
    _require_operator(request)
    last_reconcile_result = _validate_last_reconcile_result(last_reconcile_result)
    integration_kind = _validate_integration_kind(integration_kind)
    repo = get_managed_integration_repository()
    rows = await repo.list(
        tenant_id=tenant_id,
        environment_id=environment_id,
        integration_kind=integration_kind,
        last_reconcile_result=last_reconcile_result,
        limit=limit,
        offset=offset,
    )
    return APIResponse(
        data={"managed_integrations": rows, "count": len(rows)}
    ).to_dict()


@admin_router.get("/{managed_integration_id}")
async def get_managed_integration(
    managed_integration_id: str,
    request: Request,
    tenant_id: Optional[str] = Query(default=None),
    environment_id: Optional[str] = Query(default=None),
):
    """One managed integration + its newest reconcile run + drift summary.

    Scoped when both ``tenant_id`` and ``environment_id`` are supplied (refuses
    absent rows). With neither supplied the operator aggregate lookup by the
    global ``managed_integration_id`` key is used. Supplying exactly one scope
    parameter is an error — a partial scope cannot be honoured safely.
    """
    _require_operator(request)
    mi_repo = get_managed_integration_repository()
    if (tenant_id is None) != (environment_id is None):
        raise BadRequestError(
            "supply both tenant_id and environment_id to scope the lookup, or "
            "neither for the aggregate lookup"
        )
    if tenant_id is not None and environment_id is not None:
        row = await mi_repo.get(tenant_id, environment_id, managed_integration_id)
    else:
        row = await mi_repo.get_by_key(managed_integration_id)
    if row is None:
        raise NotFoundError("managed integration")

    rr_repo = get_reconcile_run_repository()
    latest = await rr_repo.latest_for_integration(
        tenant_id=str(row.get("tenant_id") or ""),
        environment_id=str(row.get("environment_id") or ""),
        managed_integration_id=managed_integration_id,
    )
    return APIResponse(
        data={
            "managed_integration": row,
            "last_reconcile_run": latest,
            # Constants echoed for operator convenience (contract is stable).
            "reconcile_results": list(RECONCILE_RESULT_VALUES),
            "drift_types": list(MANAGED_DRIFT_TYPES),
        }
    ).to_dict()
