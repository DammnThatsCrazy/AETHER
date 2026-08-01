"""HTTP surface for the Kyber Mission aggregate.

Every route on this router authorizes through the workforce identity plane and
nothing else. A mission is an operator concept — it is read and steered by an
Olympus Labs operator holding a live, device-bound workforce session, never by a
tenant's own auth. There is no ``request.state.tenant`` anywhere below; the only
identity that reaches these handlers is the one
``services.kyber.access.dependencies`` resolved.

Capability reuse is deliberate. Reading a mission is reading the same
reliability surface an incident exposes, so ``MISSION_READ`` **is**
``kyber.incident.read`` rather than a newly minted capability — a new capability
nobody grants would make every mission route deny in practice.

The per-mission routes authorize in two steps, the same shape the command routes
use and for the same reason: a mission's tenant is not in the request path, it is
on the loaded row. The route dependency proves a live, capable workforce session
(the floor); the handler then loads the mission and calls
``resolve_access_context`` again with ``tenant_scope="required"``, and
:func:`_assert_mission_in_scope` matches the mission's tenant against the scope
the evaluator actually granted. Declaring the scope on the dependency could not
work — the tenant is unknown until the row is read — and skipping the second call
would let any workforce session read any tenant's mission.

The router is intentionally not mounted here; ``main.py`` includes it behind the
``kyber_missions.missions_enabled`` flag.
"""
from __future__ import annotations

from typing import Any, Callable, Optional

from fastapi import APIRouter, Body, Depends, Path, Query, Request
from pydantic import BaseModel, Field

from shared.common.common import APIResponse, ForbiddenError
from shared.logger.logger import get_logger, metrics

from ..access.capabilities import ACTION_CLASS_ANNOTATE, ACTION_CLASS_READ
from ..access.disclosure import DisclosureLevel
from .mission_contracts import MonitoringCondition, now_iso
from .mission_repository import monitoring_condition_repository
from .missions import mission_service

logger = get_logger("aether.kyber.ops.mission_routes")

router = APIRouter(prefix="/v1/kyber/missions", tags=["Kyber Missions"])

#: Reading a mission is reading the reliability surface an incident exposes, so
#: the capability is reused verbatim — never a new capability nobody has been
#: granted.
MISSION_READ = "kyber.incident.read"


def _require(capability: str, **kwargs: Any) -> Callable[..., Any]:
    """Build the Kyber access dependency, or a dependency that denies.

    A missing authorization module must never read as "no authorization
    required", so the fallback refuses rather than passing the request through —
    the same fail-closed shape ``services.kyber.ops.routes._require`` uses.
    """
    try:
        from services.kyber.access.dependencies import require_kyber_access
    except ImportError:  # pragma: no cover - only while the access plane is absent
        logger.error(
            f"kyber access dependency unavailable; mission routes will deny "
            f"capability={capability}"
        )

        async def _deny() -> None:
            raise ForbiddenError("Kyber access control is unavailable")

        return _deny
    return require_kyber_access(capability, **kwargs)


async def _authorize_mission(request: Request, tenant_id: str) -> Any:
    """Authorize a per-mission read against the mission's own tenant scope.

    The floor dependency already proved a live workforce session. This resolves
    the operator's tenant access scope (``tenant_scope="required"``) and returns
    the context; :func:`_assert_mission_in_scope` then proves the scope was
    granted for *this mission's* tenant. Not wrapped in try/except: if the access
    plane cannot be imported this raises, and a 500 on an unauthorized mission
    read is the correct outcome.
    """
    from services.kyber.access.dependencies import resolve_access_context

    context = await resolve_access_context(
        request,
        MISSION_READ,
        disclosure=DisclosureLevel.D3_TENANT_VISIBLE,
        action_class=ACTION_CLASS_READ,
        tenant_scope="required",
    )
    _assert_mission_in_scope(context, tenant_id)
    return context


def _assert_mission_in_scope(context: Any, tenant_id: str) -> None:
    """The mission's tenant must BE the tenant the access scope was granted for.

    Compared against ``context.scope.tenant_id`` — the durable scope the
    evaluator granted — never ``context.tenant_id``, which is only what the
    client asserted through a header. A mismatch is a denial, not a silent
    rescope, mirroring ``services.kyber.ops.routes._assert_tenants_within_scope``.
    """
    scope = getattr(context, "scope", None)
    scope_tenant = str(getattr(scope, "tenant_id", "") or "")
    if not scope_tenant:
        metrics.increment("kyber_mission_denied_total", labels={"reason": "scope_missing"})
        raise ForbiddenError(
            "reading a mission requires a tenant access scope",
            details={"denial_reason": "scope_missing"},
        )
    if scope_tenant != tenant_id:
        metrics.increment(
            "kyber_mission_denied_total", labels={"reason": "scope_tenant_mismatch"}
        )
        raise ForbiddenError(
            "the active access scope was not granted for this mission's tenant",
            details={"denial_reason": "scope_tenant_mismatch"},
        )


def _disclosure_token(context: Any) -> Optional[str]:
    granted = getattr(context, "granted_disclosure", None)
    if granted is None:
        return None
    try:
        return DisclosureLevel(int(granted)).name_token
    except (TypeError, ValueError):  # pragma: no cover - exotic context
        return None


def _meta(context: Any) -> dict[str, Any]:
    return {"granted_disclosure": _disclosure_token(context)}


# ── Request bodies ───────────────────────────────────────────────────────────


class MonitoringConditionRequest(BaseModel):
    """One recurring check an operator attaches to a live mission."""

    condition_type: str = Field(min_length=1, max_length=128)
    expected_state: Any = None
    window: Any = None
    escalation_policy: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


# ── Routes ───────────────────────────────────────────────────────────────────


@router.get("")
@router.get("/")
async def list_missions(
    request: Request,
    status: Optional[str] = Query(default="open", max_length=48),
    limit: int = Query(default=100, ge=1, le=500),
    context: Any = Depends(
        _require(
            MISSION_READ,
            disclosure=DisclosureLevel.D1_FLEET_AGGREGATE,
            action_class=ACTION_CLASS_READ,
        )
    ),
) -> dict[str, Any]:
    """Missions by status, workforce-scoped.

    A fleet-aggregate read: the workforce session is the scope. When the caller
    holds a durable scope for one tenant the list is narrowed to that tenant,
    so a scoped operator sees their tenant's missions rather than the fleet's.
    """
    rows = await mission_service._missions.list_by_status(status, limit=limit)
    scope = getattr(context, "scope", None)
    scope_tenant = str(getattr(scope, "tenant_id", "") or "")
    if scope_tenant:
        rows = [row for row in rows if str(row.get("tenant_id") or "") == scope_tenant]
    return APIResponse(
        data={
            "missions": rows,
            "count": len(rows),
            "status_filter": status,
            "generated_at": now_iso(),
        },
        meta=_meta(context),
    ).to_dict()


@router.get("/{mission_id}")
async def read_mission(
    request: Request,
    mission_id: str = Path(min_length=1, max_length=128),
    context: Any = Depends(
        _require(
            MISSION_READ,
            disclosure=DisclosureLevel.D1_FLEET_AGGREGATE,
            action_class=ACTION_CLASS_READ,
        )
    ),
) -> dict[str, Any]:
    """One mission composed into a full view, scoped to its tenant.

    The floor dependency proved a live session; the mission is loaded, then the
    tenant scope is resolved and matched against the mission's tenant before the
    view is composed.
    """
    mission = await mission_service.require(mission_id)
    authorized = await _authorize_mission(request, mission.tenant_id)
    view = await mission_service.reconstruct(
        mission_id, scope_tenant=getattr(getattr(authorized, "scope", None), "tenant_id", None)
    )
    return APIResponse(data={"mission_view": view.model_dump(mode="json")}, meta=_meta(authorized)).to_dict()


@router.get("/{mission_id}/timeline")
async def read_mission_timeline(
    request: Request,
    mission_id: str = Path(min_length=1, max_length=128),
    context: Any = Depends(
        _require(
            MISSION_READ,
            disclosure=DisclosureLevel.D1_FLEET_AGGREGATE,
            action_class=ACTION_CLASS_READ,
        )
    ),
) -> dict[str, Any]:
    """The mission's merged, time-ordered timeline, scoped to its tenant."""
    mission = await mission_service.require(mission_id)
    authorized = await _authorize_mission(request, mission.tenant_id)
    timeline = await mission_service.timeline(
        mission_id, scope_tenant=getattr(getattr(authorized, "scope", None), "tenant_id", None)
    )
    return APIResponse(
        data={"mission_id": mission_id, "timeline": timeline, "count": len(timeline)},
        meta=_meta(authorized),
    ).to_dict()


@router.get("/{mission_id}/monitoring")
async def read_mission_monitoring(
    request: Request,
    mission_id: str = Path(min_length=1, max_length=128),
    context: Any = Depends(
        _require(
            MISSION_READ,
            disclosure=DisclosureLevel.D1_FLEET_AGGREGATE,
            action_class=ACTION_CLASS_READ,
        )
    ),
) -> dict[str, Any]:
    """Every monitoring condition a mission scheduled, scoped to its tenant."""
    mission = await mission_service.require(mission_id)
    authorized = await _authorize_mission(request, mission.tenant_id)
    rows = await monitoring_condition_repository.list_for_mission(mission_id)
    return APIResponse(
        data={
            "mission_id": mission_id,
            "conditions": rows,
            "count": len(rows),
        },
        meta=_meta(authorized),
    ).to_dict()


@router.post("/{mission_id}/monitoring")
async def add_mission_monitoring(
    request: Request,
    body: MonitoringConditionRequest,
    mission_id: str = Path(min_length=1, max_length=128),
    context: Any = Depends(
        _require(
            MISSION_READ,
            disclosure=DisclosureLevel.D1_FLEET_AGGREGATE,
            action_class=ACTION_CLASS_READ,
        )
    ),
) -> dict[str, Any]:
    """Attach one monitoring condition to a live mission, scoped to its tenant.

    Writing a condition is an operator annotation on the mission, so the
    second authorization asks for the annotate action class; the mission's
    tenant is still matched against the granted scope before anything is written.
    """
    mission = await mission_service.require(mission_id)
    from services.kyber.access.dependencies import resolve_access_context

    authorized = await resolve_access_context(
        request,
        MISSION_READ,
        disclosure=DisclosureLevel.D3_TENANT_VISIBLE,
        action_class=ACTION_CLASS_ANNOTATE,
        tenant_scope="required",
    )
    _assert_mission_in_scope(authorized, mission.tenant_id)

    condition = MonitoringCondition(
        mission_id=mission_id,
        tenant_id=mission.tenant_id,
        condition_type=body.condition_type,
        expected_state=body.expected_state,
        window=body.window,
        escalation_policy=body.escalation_policy,
        metadata=body.metadata,
    )
    stored = await monitoring_condition_repository.save_or_update(
        condition.model_dump(mode="json")
    )
    return APIResponse(data={"condition": stored}, meta=_meta(authorized)).to_dict()


__all__ = ["MISSION_READ", "MonitoringConditionRequest", "router"]
