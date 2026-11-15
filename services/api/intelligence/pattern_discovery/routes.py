"""Pattern Discovery HTTP surface.

Tenant routes (``/v1/intelligence/patterns``) act on the authenticated tenant
only; a caller-supplied tenant id is never trusted. Kyber routes
(``/v1/kyber/patterns``) are operator-only and name the tenant explicitly.

Endpoints:
    GET  /v1/intelligence/patterns                       list (feed=true: surfaced default view; status / kind)
    GET  /v1/intelligence/patterns/stats                 counts, calibration, baseline health
    GET  /v1/intelligence/patterns/whats-new             new / changed / retired since the viewer last looked
    POST /v1/intelligence/patterns/whats-new/seen        mark a scope seen
    GET  /v1/intelligence/patterns/lenses/{lens}/{subject}  campaign / geographic / communication / journey lens
    POST /v1/intelligence/patterns/graph-overlay         patterns touching the graph nodes in view
    GET  /v1/intelligence/patterns/{pattern_id}/graph    the pattern as a renderable subgraph
    GET  /v1/intelligence/patterns/runs                  recent discovery runs
    POST /v1/intelligence/patterns/runs                  run discovery (write)
    POST /v1/intelligence/patterns/extract               schema-on-read preview (no persistence)
    GET  /v1/intelligence/patterns/entities/{entity}     emerging-pattern context for one entity
    GET  /v1/intelligence/patterns/{pattern_id}          detail with similar patterns
    POST /v1/intelligence/patterns/{pattern_id}/curate   hide / unhide / pin / unpin / rename (write)
    POST /v1/intelligence/patterns/{pattern_id}/review   optional verdict (write)
    POST /v1/intelligence/patterns/{pattern_id}/promote  promote to Risk360 (admin)
    POST /v1/intelligence/patterns/{pattern_id}/deprecate

    GET  /v1/profile/{user_id}/patterns                  Profile 360 discovered-pattern section
    GET  /v1/agent/{agent_id}/patterns                   Agent 360 discovered-pattern section
    GET  /v1/risk360/{kind}/{id}/patterns                Risk 360 pattern findings

    GET  /v1/kyber/patterns/queue                        surfaced feed for a tenant (operator)
    GET  /v1/kyber/patterns/stats
    POST /v1/kyber/patterns/runs
    GET  /v1/kyber/patterns/{pattern_id}
    POST /v1/kyber/patterns/{pattern_id}/curate
    POST /v1/kyber/patterns/{pattern_id}/review
    POST /v1/kyber/patterns/{pattern_id}/promote
    POST /v1/kyber/patterns/{pattern_id}/deprecate
"""
from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, Query, Request

from governance.security.request_context import require_kyber_operator
from shared.auth.auth import Permissions
from shared.common.common import (
    APIResponse, BadRequestError, ForbiddenError, NotFoundError, UnauthorizedError,
)

from .contracts import (
    PATTERN_KINDS, PATTERN_STATUSES, CurateRequest, DeprecateRequest, DiscoveryRunRequest, ExtractRequest,
    PromoteRequest, ReviewRequest,
)
from pydantic import BaseModel, ConfigDict, Field

from .registry import LifecycleError


class SeenRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scope: str = Field("feed", min_length=1, max_length=400)
    at: Optional[str] = Field(default=None, max_length=64)


class OverlayRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    node_ids: list[str] = Field(..., min_length=1, max_length=500)
from .service import get_service

router = APIRouter(prefix="/v1/intelligence/patterns", tags=["Pattern Discovery"])
profile_router = APIRouter(prefix="/v1/profile", tags=["Profile 360"])
agent_router = APIRouter(prefix="/v1/agent", tags=["Agent"])
risk_router = APIRouter(prefix="/v1/risk360", tags=["Risk 360"])
kyber_router = APIRouter(
    prefix="/v1/kyber/patterns",
    tags=["Kyber Pattern Discovery"],
    dependencies=[Depends(require_kyber_operator)],
)

_SERVING_STATE_ATTRS = ("tenant_status", "organization_status", "membership_status", "credential_status")


def _tenant(request: Request, permission: str) -> tuple[str, str]:
    """(tenant_id, actor_id) of the authenticated caller, after permission checks."""
    tenant = getattr(request.state, "tenant", None)
    tenant_id = getattr(tenant, "tenant_id", None)
    if not tenant_id:
        raise UnauthorizedError("authentication required")
    if getattr(tenant, "is_suspended", False) or any(
        getattr(tenant, attr, "active") != "active" for attr in _SERVING_STATE_ATTRS
    ):
        raise ForbiddenError("Tenant account is suspended")
    tenant.require_permission(permission)
    actor = getattr(tenant, "user_id", None) or getattr(tenant, "api_key_id", None) or f"tenant:{tenant_id}"
    return tenant_id, str(actor)


def _operator(request: Request) -> str:
    actor = require_kyber_operator(request)
    return str(getattr(actor, "actor_id", None) or "kyber_operator")


def _validate_filters(status: Optional[str], kind: Optional[str]) -> None:
    if status and status not in PATTERN_STATUSES:
        raise BadRequestError(f"status must be one of {list(PATTERN_STATUSES)}")
    if kind and kind not in PATTERN_KINDS:
        raise BadRequestError(f"kind must be one of {list(PATTERN_KINDS)}")


def _validate_kinds(kinds: Optional[list[str]]) -> None:
    unknown = sorted(set(kinds or []) - set(PATTERN_KINDS))
    if unknown:
        raise BadRequestError(f"unknown pattern kinds: {unknown}")


def _ok(data: Any) -> dict:
    return APIResponse(data=data).to_dict()


# ── Shared handlers ──────────────────────────────────────────────────────────

async def _run(tenant_id: str, body: DiscoveryRunRequest, actor: str) -> dict:
    _validate_kinds(body.kinds)
    return await get_service().run(
        tenant_id, window_hours=body.window_hours, max_events=body.max_events, kinds=body.kinds,
        events=body.events, edges=body.edges, include_store=body.include_store, requested_by=actor,
    )


async def _detail(tenant_id: str, pattern_id: str) -> dict:
    row = await get_service().get_pattern(tenant_id, pattern_id)
    if row is None:
        raise NotFoundError("pattern")
    return row


async def _review(tenant_id: str, pattern_id: str, body: ReviewRequest, actor: str) -> dict:
    try:
        row = await get_service().review(tenant_id, pattern_id, reviewer_id=actor, verdict=body.verdict,
                                         reason=body.reason, duplicate_of=body.duplicate_of)
    except LifecycleError as exc:
        raise BadRequestError(str(exc))
    if row is None:
        raise NotFoundError("pattern")
    return row


async def _curate(tenant_id: str, pattern_id: str, body: CurateRequest, actor: str) -> dict:
    try:
        row = await get_service().curate(tenant_id, pattern_id, actor=actor, action=body.action,
                                         title=body.title, reason=body.reason)
    except LifecycleError as exc:
        raise BadRequestError(str(exc))
    if row is None:
        raise NotFoundError("pattern")
    return row


async def _promote(tenant_id: str, pattern_id: str, body: PromoteRequest, actor: str) -> dict:
    try:
        row = await get_service().promote(tenant_id, pattern_id, reviewer_id=actor, reason=body.reason)
    except LifecycleError as exc:
        raise BadRequestError(str(exc))
    if row is None:
        raise NotFoundError("pattern")
    return row


async def _deprecate(tenant_id: str, pattern_id: str, body: DeprecateRequest, actor: str) -> dict:
    try:
        row = await get_service().deprecate(tenant_id, pattern_id, actor=actor, reason=body.reason)
    except LifecycleError as exc:
        raise BadRequestError(str(exc))
    if row is None:
        raise NotFoundError("pattern")
    return row


# ── Tenant routes ────────────────────────────────────────────────────────────

@router.get("")
async def list_patterns(
    request: Request,
    status: Optional[str] = Query(None),
    feed: bool = Query(False, description="Default surfaced view: visible statuses, pinned first"),
    queue: bool = Query(False, description="Deprecated alias of feed"),
    kind: Optional[str] = Query(None),
    min_confidence: float = Query(0.0, ge=0.0, le=1.0),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    tenant_id, _ = _tenant(request, Permissions.READ)
    _validate_filters(status, kind)
    return _ok(await get_service().list_patterns(
        tenant_id, status=status, feed=feed or queue, kind=kind, min_confidence=min_confidence,
        limit=limit, offset=offset,
    ))


@router.get("/stats")
async def pattern_stats(request: Request):
    tenant_id, _ = _tenant(request, Permissions.READ)
    return _ok(await get_service().stats(tenant_id))


@router.get("/whats-new")
async def whats_new(request: Request, scope: str = Query("feed", max_length=400),
                    since: Optional[str] = Query(None, max_length=64)):
    """New, changed and retired patterns since this viewer last looked at ``scope``."""
    tenant_id, actor = _tenant(request, Permissions.READ)
    try:
        return _ok(await get_service().whats_new(tenant_id, viewer_id=actor, scope=scope, since=since))
    except LifecycleError as exc:
        raise BadRequestError(str(exc))


@router.post("/whats-new/seen")
async def mark_seen(body: SeenRequest, request: Request):
    """Record that this viewer has looked at ``scope`` (now, or at ``at``)."""
    tenant_id, actor = _tenant(request, Permissions.READ)
    try:
        return _ok(await get_service().mark_seen(tenant_id, viewer_id=actor, scope=body.scope, at=body.at))
    except LifecycleError as exc:
        raise BadRequestError(str(exc))


@router.get("/lenses/{lens}/{subject}")
async def lens_view(lens: str, subject: str, request: Request):
    """Campaign / Geographic / Communications / Journey 360 pattern lens."""
    tenant_id, actor = _tenant(request, Permissions.READ)
    try:
        return _ok(await get_service().lens(tenant_id, lens, subject, viewer_id=actor))
    except LifecycleError as exc:
        raise BadRequestError(str(exc))


@router.post("/graph-overlay")
async def graph_overlay(body: OverlayRequest, request: Request):
    """Which surfaced patterns touch the graph nodes currently in view."""
    tenant_id, _ = _tenant(request, Permissions.READ)
    return _ok(await get_service().graph_overlay(tenant_id, body.node_ids))


@router.get("/runs")
async def list_runs(request: Request, limit: int = Query(20, ge=1, le=200)):
    tenant_id, _ = _tenant(request, Permissions.READ)
    return _ok(await get_service().list_runs(tenant_id, limit=limit))


@router.post("/runs")
async def run_discovery(body: DiscoveryRunRequest, request: Request):
    tenant_id, actor = _tenant(request, Permissions.WRITE)
    return _ok(await _run(tenant_id, body, actor))


@router.post("/extract")
async def extract(body: ExtractRequest, request: Request):
    tenant_id, _ = _tenant(request, Permissions.READ)
    return _ok(get_service().extract(tenant_id, body.payload, event_type=body.event_type, text=body.text))


@router.get("/entities/{entity_key:path}")
async def entity_patterns(entity_key: str, request: Request):
    tenant_id, _ = _tenant(request, Permissions.READ)
    if ":" not in entity_key or len(entity_key) > 512:
        raise BadRequestError("entity must be a kind:id reference such as user:123 or agent:abc")
    return _ok(await get_service().entity_context(tenant_id, entity_key))


@router.get("/{pattern_id}")
async def get_pattern(pattern_id: str, request: Request):
    tenant_id, _ = _tenant(request, Permissions.READ)
    return _ok(await _detail(tenant_id, pattern_id))


@router.get("/{pattern_id}/graph")
async def pattern_graph(pattern_id: str, request: Request):
    """The pattern as a small graph: members, shared attributes, links."""
    tenant_id, _ = _tenant(request, Permissions.READ)
    graph = await get_service().pattern_graph(tenant_id, pattern_id)
    if graph is None:
        raise NotFoundError("pattern")
    return _ok(graph)


@router.post("/{pattern_id}/review")
async def review_pattern(pattern_id: str, body: ReviewRequest, request: Request):
    tenant_id, actor = _tenant(request, Permissions.WRITE)
    return _ok(await _review(tenant_id, pattern_id, body, actor))


@router.post("/{pattern_id}/curate")
async def curate_pattern(pattern_id: str, body: CurateRequest, request: Request):
    """Hide, unhide, pin, unpin or rename an automatically surfaced pattern."""
    tenant_id, actor = _tenant(request, Permissions.WRITE)
    return _ok(await _curate(tenant_id, pattern_id, body, actor))


@router.post("/{pattern_id}/promote")
async def promote_pattern(pattern_id: str, body: PromoteRequest, request: Request):
    tenant_id, actor = _tenant(request, Permissions.ADMIN)
    return _ok(await _promote(tenant_id, pattern_id, body, actor))


@router.post("/{pattern_id}/deprecate")
async def deprecate_pattern(pattern_id: str, body: DeprecateRequest, request: Request):
    tenant_id, actor = _tenant(request, Permissions.WRITE)
    return _ok(await _deprecate(tenant_id, pattern_id, body, actor))


# ── 360 sections ─────────────────────────────────────────────────────────────

_RISK_SUBJECT_KINDS = {"entity": "entity", "user": "user", "agent": "agent", "wallet": "wallet",
                       "anon": "anon", "session": "session"}


def _ref(raw: str) -> str:
    raw = (raw or "").strip()
    if not raw or len(raw) > 400 or "/" in raw:
        raise BadRequestError("invalid entity id")
    return raw


@profile_router.get("/{user_id}/patterns")
async def profile_patterns(user_id: str, request: Request):
    """Discovered patterns involving this profile (Profile 360 section)."""
    tenant_id, actor = _tenant(request, Permissions.READ)
    return _ok(await get_service().section(tenant_id, f"user:{_ref(user_id)}", "profile360", viewer_id=actor))


@agent_router.get("/{agent_id}/patterns")
async def agent_patterns(agent_id: str, request: Request):
    """Discovered patterns involving this agent (Agent 360 section)."""
    tenant_id, actor = _tenant(request, Permissions.READ)
    return _ok(await get_service().section(tenant_id, f"agent:{_ref(agent_id)}", "agent360", viewer_id=actor))


@risk_router.get("/{subject_kind}/{subject_id}/patterns")
async def risk_patterns(subject_kind: str, subject_id: str, request: Request):
    """Pattern-based findings for a Risk 360 subject."""
    tenant_id, actor = _tenant(request, Permissions.READ)
    kind = _RISK_SUBJECT_KINDS.get(subject_kind)
    if kind is None:
        raise BadRequestError(f"subject_kind must be one of {sorted(_RISK_SUBJECT_KINDS)}")
    return _ok(await get_service().section(tenant_id, f"{kind}:{_ref(subject_id)}", "risk360", viewer_id=actor))


# ── Kyber operator routes ────────────────────────────────────────────────────

def _tenant_param(tenant_id: str) -> str:
    tenant_id = (tenant_id or "").strip()
    if not tenant_id or len(tenant_id) > 200:
        raise BadRequestError("tenant_id is required")
    return tenant_id


@kyber_router.get("/queue")
async def kyber_queue(
    request: Request,
    tenant_id: str = Query(...),
    status: Optional[str] = Query(None),
    kind: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    _operator(request)
    _validate_filters(status, kind)
    return _ok(await get_service().list_patterns(
        _tenant_param(tenant_id), status=status, feed=status is None, kind=kind, limit=limit, offset=offset,
    ))


@kyber_router.get("/stats")
async def kyber_stats(request: Request, tenant_id: str = Query(...)):
    _operator(request)
    return _ok(await get_service().stats(_tenant_param(tenant_id)))


@kyber_router.post("/runs")
async def kyber_run(body: DiscoveryRunRequest, request: Request, tenant_id: str = Query(...)):
    actor = _operator(request)
    return _ok(await _run(_tenant_param(tenant_id), body, f"kyber:{actor}"))


@kyber_router.get("/whats-new")
async def kyber_whats_new(request: Request, tenant_id: str = Query(...), scope: str = Query("feed", max_length=400),
                          since: Optional[str] = Query(None, max_length=64)):
    actor = _operator(request)
    try:
        return _ok(await get_service().whats_new(_tenant_param(tenant_id), viewer_id=f"kyber:{actor}",
                                                 scope=scope, since=since))
    except LifecycleError as exc:
        raise BadRequestError(str(exc))


@kyber_router.post("/whats-new/seen")
async def kyber_mark_seen(body: SeenRequest, request: Request, tenant_id: str = Query(...)):
    actor = _operator(request)
    try:
        return _ok(await get_service().mark_seen(_tenant_param(tenant_id), viewer_id=f"kyber:{actor}",
                                                 scope=body.scope, at=body.at))
    except LifecycleError as exc:
        raise BadRequestError(str(exc))


@kyber_router.get("/{pattern_id}/graph")
async def kyber_pattern_graph(pattern_id: str, request: Request, tenant_id: str = Query(...)):
    _operator(request)
    graph = await get_service().pattern_graph(_tenant_param(tenant_id), pattern_id)
    if graph is None:
        raise NotFoundError("pattern")
    return _ok(graph)


@kyber_router.get("/{pattern_id}")
async def kyber_detail(pattern_id: str, request: Request, tenant_id: str = Query(...)):
    _operator(request)
    return _ok(await _detail(_tenant_param(tenant_id), pattern_id))


@kyber_router.post("/{pattern_id}/review")
async def kyber_review(pattern_id: str, body: ReviewRequest, request: Request, tenant_id: str = Query(...)):
    actor = _operator(request)
    return _ok(await _review(_tenant_param(tenant_id), pattern_id, body, f"kyber:{actor}"))


@kyber_router.post("/{pattern_id}/curate")
async def kyber_curate(pattern_id: str, body: CurateRequest, request: Request, tenant_id: str = Query(...)):
    actor = _operator(request)
    return _ok(await _curate(_tenant_param(tenant_id), pattern_id, body, f"kyber:{actor}"))


@kyber_router.post("/{pattern_id}/promote")
async def kyber_promote(pattern_id: str, body: PromoteRequest, request: Request, tenant_id: str = Query(...)):
    actor = _operator(request)
    return _ok(await _promote(_tenant_param(tenant_id), pattern_id, body, f"kyber:{actor}"))


@kyber_router.post("/{pattern_id}/deprecate")
async def kyber_deprecate(pattern_id: str, body: DeprecateRequest, request: Request, tenant_id: str = Query(...)):
    actor = _operator(request)
    return _ok(await _deprecate(_tenant_param(tenant_id), pattern_id, body, f"kyber:{actor}"))
