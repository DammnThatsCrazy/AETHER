"""HTTP surface for the Kyber Graph.

Eight routes across four disclosure levels, ordered from least to most
revealing: platform topology (D0), fleet aggregates and cohorts (D1), then one
scoped tenant's graph (D3). That ordering is the product: an operator answers
"is the platform healthy?" without touching a tenant, narrows to "which cohort
is degraded?" still without touching a tenant, and only then — with a
purpose-bound scope naming one tenant — reaches that tenant's own entities.

Every route authorizes through ``require_kyber_access``. The import is lazy and
its failure mode is a dependency that **denies**: there is no deployment slice
in which these routes answer without an authorization decision having been
recorded.

The router is deliberately not mounted here. The application assembles it, so
mounting the Kyber graph plane is one explicit act rather than an import side
effect.
"""
from __future__ import annotations

from typing import Any, Callable, Optional

from fastapi import APIRouter, Depends, Path, Query, Request
from pydantic import BaseModel, Field

from shared.common.common import APIResponse, ForbiddenError
from shared.logger.logger import get_logger

from ..access.capabilities import ACTION_CLASS_READ
from ..access.disclosure import DisclosureLevel
from .blast_radius import DELEGATED_SUBJECTS, kyber_blast_radius_service
from .cohorts import CohortDefinition, cohort_service
from .contracts import now_iso
from .fleet import DEFAULT_READ_LIMIT, fleet_projection_service
from .scoped_gateway import (
    MAX_RESULT_BUDGET,
    MAX_TRAVERSAL_DEPTH,
    get_store,
    scoped_tenant_graph_gateway,
)

logger = get_logger("aether.kyber.graph.routes")

router = APIRouter(prefix="/v1/kyber/graph", tags=["Kyber Graph"])

PLATFORM_CAPABILITY = "kyber.graph.platform.read"
FLEET_CAPABILITY = "kyber.graph.fleet.read"
COHORT_CAPABILITY = "kyber.graph.cohort.read"
TENANT_CAPABILITY = "kyber.graph.tenant.read"

#: Node types the D0 platform surface may return. Every one of them is platform
#: topology; none may legitimately carry a ``tenant_id`` (see
#: ``TENANT_SCOPED_NODE_TYPES`` in ``contracts``). Enumerating them explicitly
#: is what makes this surface a *constant* number of queries — one per type,
#: independent of how many tenants the fleet has — and what stops a tenant-scoped
#: node type from ever appearing on a D0 route.
PLATFORM_NODE_TYPES: tuple[str, ...] = (
    "OlympusPlatform",
    "Environment",
    "Region",
    "Service",
    "WorkerRole",
    "Release",
    "Deployment",
    "FeatureSurface",
    "ModelDeployment",
)

#: Per-type bound on the platform topology read.
PLATFORM_NODE_LIMIT = 200


def _require(capability: str, **kwargs: Any) -> Callable[..., Any]:
    """Build the Kyber access dependency, or a dependency that denies.

    A missing authorization module must never read as "no authorization
    required", so the fallback refuses rather than passing the request through.
    """
    try:
        from services.kyber.access.dependencies import require_kyber_access
    except ImportError:  # pragma: no cover - only while the access plane is absent
        logger.error(
            f"kyber access dependency unavailable; graph routes will deny "
            f"capability={capability}"
        )

        async def _deny() -> None:
            raise ForbiddenError("Kyber access control is unavailable")

        return _deny
    return require_kyber_access(capability, **kwargs)


# ── Request bodies ───────────────────────────────────────────────────────────


class CohortRequest(BaseModel):
    """A cohort definition submitted by an operator.

    ``minimum_size`` may be raised but not lowered below the service's absolute
    floor; a definition asking for less is normalised upward rather than
    rejected, so the caller always learns what was actually stored.
    """

    name: str = Field(min_length=1, max_length=200)
    filters: dict[str, Any] = Field(default_factory=dict)
    minimum_size: int = Field(default=3, ge=1, le=10_000)


class BlastRadiusRequest(BaseModel):
    """One bounded blast-radius review of one graph subject.

    There is deliberately no ``tenant_id`` field. The agent and capability forms
    of this question are per tenant by construction and already have a
    tenant-scoped operator surface in the agent-access plane; accepting a tenant
    in this D0 body would create an unscoped per-tenant read, which is exactly
    the shape the scoped gateway exists to prevent.
    """

    subject_type: str = Field(min_length=1, max_length=64)
    subject_id: str = Field(min_length=1, max_length=512)
    environment: Optional[str] = Field(default=None, max_length=64)
    max_depth: int = Field(default=MAX_TRAVERSAL_DEPTH, ge=1, le=MAX_TRAVERSAL_DEPTH)


# ── D0 — platform topology ───────────────────────────────────────────────────


@router.get("/platform")
async def read_platform_graph(
    request: Request,
    environment: Optional[str] = Query(default=None, max_length=64),
    context: Any = Depends(
        _require(
            PLATFORM_CAPABILITY,
            disclosure=DisclosureLevel.D0_PLATFORM_TOPOLOGY,
            action_class=ACTION_CLASS_READ,
        )
    ),
) -> dict[str, Any]:
    """Platform topology: services, releases, deployments, feature surfaces.

    Costs one query per platform node type — a constant — never one per tenant.
    An unavailable store reports ``state: "no_data"`` with the missing input
    named; it never reports an empty platform as a healthy one.
    """
    store = get_store()
    if store is None:
        return APIResponse(
            data={
                "available": False,
                "environment": environment,
                "nodes": {},
                "counts": {},
                "by_health": {},
                "state": "no_data",
                "truncated": False,
                "totals_known": False,
                "missing_inputs": ["kyber_graph_store:unavailable"],
                "queries_issued": 0,
                "computed_at": now_iso(),
            }
        ).to_dict()

    nodes: dict[str, list[dict[str, Any]]] = {}
    counts: dict[str, int] = {}
    health: dict[str, int] = {}
    missing: list[str] = []
    truncated = False
    queries = 0

    for node_type in PLATFORM_NODE_TYPES:
        queries += 1
        try:
            found = list(
                await store.find_nodes(
                    node_type=node_type,
                    environment=environment,
                    limit=PLATFORM_NODE_LIMIT + 1,
                )
            )
        except Exception as exc:
            logger.warning(f"kyber: platform topology read failed for {node_type}: {exc}")
            missing.append(f"kyber_graph_nodes:{node_type}:read_failed")
            continue
        if len(found) > PLATFORM_NODE_LIMIT:
            truncated = True
            missing.append(f"kyber_graph_nodes:{node_type}:scan_truncated")
            found = found[:PLATFORM_NODE_LIMIT]

        rendered: list[dict[str, Any]] = []
        for node in found:
            # Defensive: a platform node type carrying a tenant is a modelling
            # error, and surfacing it here would turn D0 into a tenant read.
            if getattr(node, "tenant_id", None):
                missing.append(f"kyber_graph_nodes:{node_type}:tenant_scoped_node_excluded")
                continue
            rendered.append(
                {
                    "node_key": getattr(node, "node_key", None),
                    "node_type": getattr(node, "node_type", None),
                    "display_name": getattr(node, "display_name", None),
                    "environment": getattr(node, "environment", None),
                    "health": getattr(node, "health", "unknown"),
                }
            )
            health[str(getattr(node, "health", "unknown"))] = (
                health.get(str(getattr(node, "health", "unknown")), 0) + 1
            )
        nodes[node_type] = rendered
        counts[node_type] = len(rendered)

    total = sum(counts.values())
    state = _platform_state(health, total=total, complete=not missing)
    return APIResponse(
        data={
            "available": True,
            "environment": environment,
            "nodes": nodes,
            "counts": counts,
            "node_count": total,
            "by_health": health,
            "state": state,
            "truncated": truncated,
            "totals_known": not missing,
            "missing_inputs": sorted(set(missing)),
            "queries_issued": queries,
            "computed_at": now_iso(),
        },
        meta={"granted_disclosure": _disclosure_token(context)},
    ).to_dict()


def _platform_state(health: dict[str, int], *, total: int, complete: bool) -> str:
    """Worst observed health, but only when the read was complete.

    No nodes is ``no_data`` and an incomplete read is ``unknown``. Neither is
    ever ``healthy`` — the same rule the fleet surface follows, for the same
    reason.
    """
    if total == 0:
        return "no_data"
    if not complete:
        return "unknown"
    for candidate in ("failing", "degraded", "healthy"):
        if health.get(candidate):
            return candidate
    return "unknown"


# ── D1 — fleet aggregates ────────────────────────────────────────────────────


@router.get("/fleet")
async def read_fleet_summary(
    request: Request,
    environment: Optional[str] = Query(default=None, max_length=64),
    context: Any = Depends(
        _require(
            FLEET_CAPABILITY,
            disclosure=DisclosureLevel.D1_FLEET_AGGREGATE,
            action_class=ACTION_CLASS_READ,
        )
    ),
) -> dict[str, Any]:
    """Every projection's fleet aggregate, in a single projection-table query.

    Carries ``computed_at``, the oldest row's age and ``stale``, because a fleet
    number without freshness cannot be acted on. Counts only: no tenant is named
    at D1.
    """
    data = await fleet_projection_service.summary(environment=environment)
    return APIResponse(
        data=data, meta={"granted_disclosure": _disclosure_token(context)}
    ).to_dict()


@router.get("/fleet/{projection}")
async def read_fleet_projection(
    request: Request,
    projection: str = Path(min_length=1, max_length=128),
    environment: Optional[str] = Query(default=None, max_length=64),
    limit: int = Query(default=DEFAULT_READ_LIMIT, ge=1, le=2000),
    context: Any = Depends(
        _require(
            FLEET_CAPABILITY,
            disclosure=DisclosureLevel.D1_FLEET_AGGREGATE,
            action_class=ACTION_CLASS_READ,
        )
    ),
) -> dict[str, Any]:
    """One projection's fleet aggregate. Exactly one query, whatever the fleet size."""
    data = await fleet_projection_service.read(
        projection, environment=environment, limit=limit
    )
    return APIResponse(
        data=data, meta={"granted_disclosure": _disclosure_token(context)}
    ).to_dict()


# ── D1 — cohorts ─────────────────────────────────────────────────────────────


@router.post("/cohorts")
async def define_cohort(
    request: Request,
    body: CohortRequest,
    context: Any = Depends(
        _require(
            COHORT_CAPABILITY,
            disclosure=DisclosureLevel.D1_FLEET_AGGREGATE,
            action_class=ACTION_CLASS_READ,
        )
    ),
) -> dict[str, Any]:
    """Store a cohort definition.

    A cohort is a saved query over fleet aggregates, not platform state, so it
    stays at the read action class — the same reasoning
    ``kyber.export.create`` uses. Its risk lives in the disclosure ceiling and
    in the minimum cohort size, not in the class.
    """
    stored = await cohort_service.define(
        CohortDefinition(
            name=body.name,
            filters=body.filters,
            minimum_size=body.minimum_size,
            created_by=getattr(context, "operator_id", None),
        )
    )
    return APIResponse(
        data={
            "cohort": stored.model_dump(),
            "normalised": stored.filters != body.filters
            or stored.minimum_size != body.minimum_size,
        },
        meta={"granted_disclosure": _disclosure_token(context)},
    ).to_dict()


@router.get("/cohorts/{cohort_id}")
async def evaluate_cohort(
    request: Request,
    cohort_id: str = Path(min_length=1, max_length=128),
    environment: Optional[str] = Query(default=None, max_length=64),
    context: Any = Depends(
        _require(
            COHORT_CAPABILITY,
            disclosure=DisclosureLevel.D1_FLEET_AGGREGATE,
            action_class=ACTION_CLASS_READ,
        )
    ),
) -> dict[str, Any]:
    """Evaluate a cohort over fleet projections.

    A cohort resolving below its minimum size is *suppressed* and says so; it
    does not come back as an empty aggregate, because an operator who cannot
    distinguish suppression from absence will read "no members" as "nothing to
    worry about". Member identifiers require ``kyber.graph.fleet.read``.
    """
    data = await cohort_service.evaluate(
        cohort_id,
        environment=environment,
        capabilities=getattr(context, "capabilities", frozenset()) or frozenset(),
    )
    return APIResponse(
        data=data, meta={"granted_disclosure": _disclosure_token(context)}
    ).to_dict()


# ── D3 — one scoped tenant ───────────────────────────────────────────────────


@router.get("/tenants/{tenant_id}")
async def read_tenant_graph(
    request: Request,
    tenant_id: str = Path(min_length=1, max_length=128),
    vertex_type: Optional[str] = Query(default=None, max_length=64),
    limit: int = Query(default=MAX_RESULT_BUDGET, ge=1, le=MAX_RESULT_BUDGET),
    context: Any = Depends(
        _require(
            TENANT_CAPABILITY,
            disclosure=DisclosureLevel.D3_TENANT_VISIBLE,
            action_class=ACTION_CLASS_READ,
            tenant_scope="required",
        )
    ),
) -> dict[str, Any]:
    """One page of one tenant's own graph, through the scoped gateway.

    The gateway re-checks the scope even though the dependency already did: this
    handler is not the only caller, and a scope can expire between the
    authorization and the read.
    """
    data = await scoped_tenant_graph_gateway.query(
        request, tenant_id=tenant_id, vertex_type=vertex_type, limit=limit
    )
    return APIResponse(
        data=data, meta={"granted_disclosure": _disclosure_token(context)}
    ).to_dict()


@router.get("/tenants/{tenant_id}/entities/{vertex_id}")
async def read_tenant_entity_neighborhood(
    request: Request,
    tenant_id: str = Path(min_length=1, max_length=128),
    vertex_id: str = Path(min_length=1, max_length=512),
    depth: int = Query(default=1, ge=1, le=MAX_TRAVERSAL_DEPTH),
    context: Any = Depends(
        _require(
            TENANT_CAPABILITY,
            disclosure=DisclosureLevel.D3_TENANT_VISIBLE,
            action_class=ACTION_CLASS_READ,
            tenant_scope="required",
        )
    ),
) -> dict[str, Any]:
    """A bounded neighbourhood around one of the tenant's own entities.

    An entity that does not exist and an entity belonging to another tenant
    return the same ``found: false`` shape, so this route cannot be used as a
    cross-tenant existence oracle.
    """
    data = await scoped_tenant_graph_gateway.neighborhood(
        request, tenant_id=tenant_id, vertex_id=vertex_id, depth=depth
    )
    return APIResponse(
        data=data, meta={"granted_disclosure": _disclosure_token(context)}
    ).to_dict()


# ── D0 — blast radius ────────────────────────────────────────────────────────


@router.post("/blast-radius")
async def review_blast_radius(
    request: Request,
    body: BlastRadiusRequest,
    context: Any = Depends(
        _require(
            PLATFORM_CAPABILITY,
            disclosure=DisclosureLevel.D0_PLATFORM_TOPOLOGY,
            action_class=ACTION_CLASS_READ,
        )
    ),
) -> dict[str, Any]:
    """What a change to one platform subject can reach.

    Per subject, never summed across the fleet — ``kyber_ops_routes.py`` records
    why: a cross-tenant total would hide exactly the tenants whose inputs were
    missing. Agent and capability subjects are answered by the agent-access
    plane's own tenant-scoped review; asking for one here returns the missing
    input that names it rather than a partial answer.
    """
    result = await kyber_blast_radius_service.for_subject(
        subject_type=body.subject_type,
        subject_id=body.subject_id,
        environment=body.environment,
        max_depth=body.max_depth,
    )
    payload = result.model_dump()
    if body.subject_type.strip().lower() in DELEGATED_SUBJECTS:
        payload["delegated_surface"] = "GET /v1/capability/kyber/ops/blast-radius?tenant_id=…"
    return APIResponse(
        data=payload, meta={"granted_disclosure": _disclosure_token(context)}
    ).to_dict()


def _disclosure_token(context: Any) -> Optional[str]:
    """The level this response was rendered at, for the client to display."""
    granted = getattr(context, "granted_disclosure", None)
    if granted is None:
        return None
    try:
        return DisclosureLevel(int(granted)).name_token
    except (TypeError, ValueError):  # pragma: no cover - exotic context
        return None


__all__ = [
    "COHORT_CAPABILITY",
    "FLEET_CAPABILITY",
    "PLATFORM_CAPABILITY",
    "PLATFORM_NODE_LIMIT",
    "PLATFORM_NODE_TYPES",
    "TENANT_CAPABILITY",
    "BlastRadiusRequest",
    "CohortRequest",
    "router",
]
