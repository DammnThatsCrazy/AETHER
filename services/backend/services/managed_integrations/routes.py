"""Reconciled Control Plane — read-only operator surface (Phase 0-3).

Mounts under ``/v1/admin/kyber/managed-integrations`` (mounted in main.py behind
``settings.reconciled_control.kyber_route_enabled``, default OFF). Every handler
is operator-gated via :func:`require_kyber_operator` — an Aether tenant can never
read the fleet surface (the ``reconciled_control`` governance domain carries no
tenant grant).

Scope discipline: this router has **no** POST/PUT/DELETE. Phase 0 exposes the
durable ``managed_integrations`` registration rows and the evidence ``reconcile_runs``
rows (desired-vs-observed classification + DRAFT change summaries). Phase 1 adds
the durable ``change_sets`` **plan** rows (§32 step 12) — candidate changes with
their blast radius, risk assessment and guard status. Phase 3 adds the review
surface for approvals (§21 role-gated decisions) and ActionRequired exceptions
(§12.14) that automation routes. Nothing here mutates an integration — applying
a ChangeSet is explicitly deferred (CP-08 boundary). The repo singleton
injection seam mirrors provider_runtime so tests can point the routes at an
in-memory store.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Query, Request

from shared.common.common import APIResponse, BadRequestError, NotFoundError
from shared.logger.logger import get_logger

from services.managed_integrations.contracts import (
    ACTION_REQUIRED_STATUSES,
    CHANGE_ACTION_KINDS,
    CHANGE_RISK_CLASSES,
    CHANGESET_STATUSES,
    DRIFT_TAXONOMY_TYPES,
    MANAGED_DRIFT_TYPES,
    MANAGED_INTEGRATION_KINDS,
    RECONCILE_RESULT_VALUES,
)
from services.managed_integrations.change_sets_repository import (
    get_change_set_repository,
)
from services.managed_integrations.execution_records_repository import (
    get_action_required_repository,
    get_change_set_approval_repository,
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


def _validate_change_set_status(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    if value not in CHANGESET_STATUSES:
        raise BadRequestError(
            f"invalid change-set status {value!r} — expected one of the §34 "
            f"statuses: {CHANGESET_STATUSES}"
        )
    return value


# NOTE: the literal ``/change-sets`` routes MUST stay declared before the
# ``/{managed_integration_id}`` capture route below, or FastAPI would swallow
# ``/change-sets`` as a managed-integration id.
@admin_router.get("/change-sets")
async def list_change_sets(
    request: Request,
    tenant_id: Optional[str] = Query(default=None, description="Narrow to one tenant"),
    environment_id: Optional[str] = Query(
        default=None, description="Narrow to one environment"
    ),
    status: Optional[str] = Query(
        default=None, description="Narrow to one §34 ChangeSet status"
    ),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    """ChangeSet plans (operator aggregate/read, §32 step 12 evidence).

    No filters -> fleet-wide newest-created-first view. Filters are ANDed.
    ``status`` accepts the §34 ChangeSet status vocabulary. Plans are candidate
    changes only — Phase 1 never executes them.
    """
    _require_operator(request)
    status = _validate_change_set_status(status)
    repo = get_change_set_repository()
    rows = await repo.list(
        tenant_id=tenant_id,
        environment_id=environment_id,
        status=status,
        limit=limit,
        offset=offset,
    )
    return APIResponse(data={"change_sets": rows, "count": len(rows)}).to_dict()


@admin_router.get("/change-sets/{changeset_id}")
async def get_change_set(
    changeset_id: str,
    request: Request,
    tenant_id: Optional[str] = Query(default=None),
    environment_id: Optional[str] = Query(default=None),
):
    """One ChangeSet plan + its planning vocabularies.

    Scoped when both ``tenant_id`` and ``environment_id`` are supplied (refuses
    absent rows); with neither supplied the operator aggregate lookup by the
    global ``changeset_id`` key is used. Supplying exactly one scope parameter
    is an error — a partial scope cannot be honoured safely.
    """
    _require_operator(request)
    repo = get_change_set_repository()
    if (tenant_id is None) != (environment_id is None):
        raise BadRequestError(
            "supply both tenant_id and environment_id to scope the lookup, or "
            "neither for the aggregate lookup"
        )
    if tenant_id is not None and environment_id is not None:
        row = await repo.get(tenant_id, environment_id, changeset_id)
    else:
        row = await repo.get_by_key(changeset_id)
    if row is None:
        raise NotFoundError("change set")
    return APIResponse(
        data={
            "change_set": row,
            # Constants echoed for operator convenience (contract is stable).
            "change_set_statuses": list(CHANGESET_STATUSES),
            "risk_classes": list(CHANGE_RISK_CLASSES),
            "change_action_kinds": list(CHANGE_ACTION_KINDS),
            "drift_taxonomy_types": list(DRIFT_TAXONOMY_TYPES),
        }
    ).to_dict()


_APPROVAL_DECISIONS = ("approved", "denied")


def _validate_approval_decision(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    if value not in _APPROVAL_DECISIONS:
        raise BadRequestError(
            f"invalid approval decision {value!r} — expected one of "
            f"{_APPROVAL_DECISIONS}"
        )
    return value


def _validate_action_required_status(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    if value not in ACTION_REQUIRED_STATUSES:
        raise BadRequestError(
            f"invalid action-required status {value!r} — expected one of "
            f"{ACTION_REQUIRED_STATUSES} (§12.14)"
        )
    return value


# Phase 3 review surface: approvals + exceptions that automation routes (§39
# required-approval tokens, §32 step 23 / §12.14 ActionRequired). Read-only —
# deciding an approval or resolving an action stays with the role-gated
# surfaces, never here. Literal paths MUST stay declared before the
# /{managed_integration_id} capture route below.
@admin_router.get("/approvals")
async def list_change_set_approvals(
    request: Request,
    tenant_id: Optional[str] = Query(default=None, description="Narrow to one tenant"),
    environment_id: Optional[str] = Query(
        default=None, description="Narrow to one environment"
    ),
    changeset_ref: Optional[str] = Query(default=None),
    decision: Optional[str] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    """ChangeSet approval decisions (operator aggregate/read, §21).

    Fleet-wide newest-decided-first by default; filters ANDed. The approval
    rows record which §21 role granted/denied which required-approval token —
    the review surface for approvals that automation routes.
    """
    _require_operator(request)
    decision = _validate_approval_decision(decision)
    repo = get_change_set_approval_repository()
    rows = await repo.list(
        tenant_id=tenant_id,
        environment_id=environment_id,
        changeset_ref=changeset_ref,
        decision=decision,
        limit=limit,
        offset=offset,
    )
    return APIResponse(data={"approvals": rows, "count": len(rows)}).to_dict()


@admin_router.get("/action-required")
async def list_action_required(
    request: Request,
    tenant_id: Optional[str] = Query(default=None, description="Narrow to one tenant"),
    status: Optional[str] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    """Open/resolved ActionRequired items (operator aggregate/read, §12.14).

    Exceptions that automation routes for operator/tenant action — blocked R2
    rollouts, data-loss decisions, unresolvable changes. Read-only: resolving
    an item stays on the role-gated write surface.
    """
    _require_operator(request)
    status = _validate_action_required_status(status)
    repo = get_action_required_repository()
    rows = await repo.list(tenant_ref=tenant_id, status=status, limit=limit + offset)
    return APIResponse(
        data={"action_required": rows[offset : offset + limit], "count": len(rows)}
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
