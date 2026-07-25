"""HTTP surface for the Kyber operations plane.

Four planes behind one router: the exception queue an operator reads instead of
watching dashboards, the incidents those exceptions roll up into, the governed
commands that change platform state, and the containment switches that stop it.

Every route authorizes through ``require_kyber_access``. The import is lazy and
its failure mode is a dependency that **denies** — there is no deployment slice
in which these routes answer without an authorization decision having been
recorded.

The command routes authorize twice, and the second time is the one that matters.
A command's capability and action class come from its *spec*, which is only
known once the body has been read: ``activate_kill_switch`` is class 5 and
``retry_job`` is class 2, and a single dependency cannot declare both. So the
dependency declares the floor — a live, device-bound, directory-fresh workforce
session, via the self capability every authenticated principal holds — and the
handler then calls ``resolve_access_context`` with the spec's real capability,
disclosure and action class. That second call is the full evaluator, step-up
included, and it writes its own decision row. Declaring the ceiling on the
dependency instead would deny a retry to an operator who legitimately holds only
``kyber.command.retry``; declaring the floor and stopping there would be no gate
at all.

That second call resolves the operator's tenant scope from what the *request*
names — a path param, a query param, the ``X-Kyber-Tenant`` header or
``request.state`` — and a command names its targets in its **body**, which that
resolution never reads. ``tenant_scope="required"`` therefore proves only that
the caller holds *a* scope for *some* tenant, while ``tenant_ids`` decides what
the command acts on. :func:`_assert_tenants_within_scope` closes that gap by
matching every named tenant against the scope the evaluator actually granted,
on the request *and* again on every later transition of the same command.

The router is deliberately not mounted here. The application assembles it, so
mounting the Kyber ops plane is one explicit act rather than an import side
effect.
"""
from __future__ import annotations

from typing import Any, Callable, Iterable, Optional

from fastapi import APIRouter, Body, Depends, Path, Query, Request
from pydantic import BaseModel, Field

from shared.common.common import APIResponse, ForbiddenError
from shared.logger.logger import get_logger, metrics

from ..access.capabilities import (
    ACTION_CLASS_ANNOTATE,
    ACTION_CLASS_FLEET_DESTRUCTIVE,
    ACTION_CLASS_HIGH_IMPACT,
    ACTION_CLASS_READ,
    SELF_CAPABILITY,
)
from ..access.disclosure import DisclosureLevel
from .commands import command_service
from .containment import containment_service
from .contracts import now_iso
from .correlation import incident_correlator
from .exceptions import exception_service
from .registry import COMMAND_REGISTRY, require_command_spec

logger = get_logger("aether.kyber.ops.routes")

router = APIRouter(prefix="/v1/kyber/ops", tags=["Kyber Operations"])

INCIDENT_READ = "kyber.incident.read"
INCIDENT_MANAGE = "kyber.incident.manage"
INCIDENT_CLOSE = "kyber.incident.close"
AUDIT_READ = "kyber.audit.read"
PAUSE_CAPABILITY = "kyber.command.pause"
KILL_SWITCH_CAPABILITY = "kyber.command.kill_switch"

#: The floor for the command lifecycle routes. It proves a live, authorized
#: workforce session and grants nothing; the spec's own capability is enforced
#: by the nested authorization inside each handler.
COMMAND_FLOOR_CAPABILITY = SELF_CAPABILITY


def _require(capability: str, **kwargs: Any) -> Callable[..., Any]:
    """Build the Kyber access dependency, or a dependency that denies.

    A missing authorization module must never read as "no authorization
    required", so the fallback refuses rather than passing the request through.
    """
    try:
        from services.kyber.access.dependencies import require_kyber_access
    except ImportError:  # pragma: no cover - only while the access plane is absent
        logger.error(
            f"kyber access dependency unavailable; ops routes will deny "
            f"capability={capability}"
        )

        async def _deny() -> None:
            raise ForbiddenError("Kyber access control is unavailable")

        return _deny
    return require_kyber_access(capability, **kwargs)


def _assert_tenants_within_scope(
    context: Any, spec: Any, tenant_ids: Iterable[str]
) -> None:
    """Every tenant a tenant-scoped command names must BE the scope's tenant.

    The authority compared against is ``context.scope.tenant_id`` — the tenant
    the durable :class:`~services.kyber.access.contracts.AccessScope` was
    granted for — and never ``context.tenant_id``, which is only what the client
    asserted through a header it controls. A client-provided tenant id may be
    compared; it must never grant. Fleet visibility is not unrestricted
    cross-tenant access, and a mismatch is a denial rather than a silent rescope
    for the same reason it is one in
    :mod:`services.kyber.graph.scoped_gateway`: answering about tenant A a
    request that named tenant B would make the audit trail lie about what was
    asked for.

    Two shapes are refused outright, and both are decisions rather than
    oversights:

    **Zero tenants.** A tenant-scoped command with an empty ``tenant_ids`` has
    nothing to check and nothing to contain: ``_containment_refusal`` iterates
    that list and so checks no tenant, the audit row records no tenant, and the
    blast radius is assessed over an empty set. There is no scope such a command
    is inside, so it is refused as ``scope_missing`` — the same answer the
    scoped graph gateway gives a read that names no tenant.

    **Several tenants.** A session holds at most one active scope
    (:mod:`services.kyber.access.scopes`), so a command naming two distinct
    tenants can never be wholly inside the authority its operator actually
    holds. It is refused rather than executed over the subset that happens to
    match: a partial execution would leave an operator believing a command ran
    against tenants it silently skipped, which is worse than a refusal they can
    see. Note the rule is stated per tenant, not as a count — naming one tenant
    twice is still one tenant, and the refusal falls out of the comparison.

    A genuinely fleet-wide command is not impossible, it simply needs an
    authority that does not exist yet: a scope covering several tenants, or a
    spec that declares itself un-scoped (``tenant_scoped=False``, which this
    function returns early for). Until one of those exists, refusing is the
    honest reading of what the operator was granted.

    Raises:
        shared.common.common.ForbiddenError: With ``denial_reason``
            ``scope_missing`` or ``scope_tenant_mismatch``.
    """
    if not getattr(spec, "tenant_scoped", False):
        return

    command_type = getattr(spec, "command_type", "?")
    named = [str(tenant) for tenant in (tenant_ids or ())]
    if not named:
        raise _refuse_command(
            "scope_missing",
            command_type,
            f"{command_type!r} is tenant-scoped but named no tenant; a command "
            f"with no target cannot be matched against an access scope",
        )

    scope = getattr(context, "scope", None)
    scope_tenant = str(getattr(scope, "tenant_id", "") or "")
    if not scope_tenant:
        raise _refuse_command(
            "scope_missing",
            command_type,
            f"{command_type!r} is tenant-scoped and no tenant access scope was "
            f"resolved for this session",
        )

    outside = sorted({tenant for tenant in named if tenant != scope_tenant})
    if outside:
        raise _refuse_command(
            "scope_tenant_mismatch",
            command_type,
            f"{command_type!r} names {len(outside)} tenant(s) the active access "
            f"scope was not granted for; the command is refused rather than run "
            f"against the tenants that do match",
            extra={"tenants_outside_scope": outside},
        )


def _refuse_command(
    reason: str,
    command_type: str,
    detail: str,
    *,
    extra: Optional[dict[str, Any]] = None,
) -> ForbiddenError:
    """Build one command-plane denial, counting and logging it.

    Returned rather than raised so each call site reads as a single ``raise``
    and the gate stays legible in one function, matching the scoped graph
    gateway. Counted because this refusal happens *after*
    ``resolve_access_context`` has already recorded an allow, so without a
    metric of its own it would leave no trace an operator could aggregate.
    """
    metrics.increment(
        "kyber_command_denied_total", labels={"reason": reason, "command_type": command_type}
    )
    logger.warning(f"kyber: command denied reason={reason} command_type={command_type}")
    return ForbiddenError(detail, details={"denial_reason": reason, **(extra or {})})


async def _authorize_command(
    request: Request, command_type: str, tenant_ids: Iterable[str]
) -> tuple[Any, Any]:
    """Authorize against the command's own capability, class and target tenants.

    Returns ``(context, spec)``. Deliberately not wrapped in a ``try/except``:
    if the access plane cannot be imported this raises, and a 500 on a command
    route is the correct outcome — an unauthorized state change is not.

    ``tenant_ids`` is a required argument rather than something read off the
    body here, because the four lifecycle routes source it differently: the
    request route has the caller's body, and the later transitions must use the
    tenants **already stored on the command**. A scope can lapse or be reopened
    on another tenant between requesting a command and executing it, so the
    match is made again on every transition rather than trusted from the first
    one — the same reason the scoped graph gateway re-checks a scope the route
    dependency already resolved.
    """
    from services.kyber.access.dependencies import resolve_access_context

    spec = require_command_spec(command_type)
    context = await resolve_access_context(
        request,
        spec.capability_id,
        disclosure=DisclosureLevel.D4_EVENT_EVIDENCE,
        action_class=spec.action_class,
        tenant_scope="required" if spec.tenant_scoped else "none",
    )
    _assert_tenants_within_scope(context, spec, tenant_ids)
    return context, spec


def _disclosure_token(context: Any) -> Optional[str]:
    """The level this response was rendered at, for the client to display."""
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


class ResolveExceptionRequest(BaseModel):
    note: Optional[str] = Field(default=None, max_length=2000)


class SuppressExceptionRequest(BaseModel):
    """Suppression is the one transition that hides something without fixing it."""

    reason: str = Field(min_length=1, max_length=2000)


class UpdateIncidentRequest(BaseModel):
    """Everything an operator may change on an incident, plus a note.

    ``next_action`` is first among equals: it is what a returning operator reads
    to pick the response back up, and an incident with none is an incident
    nobody can resume.
    """

    status: Optional[str] = Field(default=None, max_length=32)
    severity: Optional[str] = Field(default=None, max_length=16)
    root_cause: Optional[str] = Field(default=None, max_length=2000)
    last_action: Optional[str] = Field(default=None, max_length=1000)
    next_action: Optional[str] = Field(default=None, max_length=1000)
    blocked_by: Optional[str] = Field(default=None, max_length=1000)
    pending_verification: Optional[list[str]] = None
    note: Optional[str] = Field(default=None, max_length=2000)


class ResolveIncidentRequest(BaseModel):
    root_cause: Optional[str] = Field(default=None, max_length=2000)


class CommandRequestBody(BaseModel):
    """One intent to change platform state.

    ``idempotency_key`` is required and has no default. Generating one here
    would make every retry a fresh command, which is precisely the duplicate
    execution the unique index exists to prevent.
    """

    command_type: str = Field(min_length=1, max_length=128)
    reason: str = Field(min_length=1, max_length=2000)
    idempotency_key: str = Field(min_length=1, max_length=256)
    tenant_ids: list[str] = Field(default_factory=list)
    resource_ids: list[str] = Field(default_factory=list)
    rollback_plan: Optional[str] = Field(default=None, max_length=4000)
    typed_confirmation: Optional[str] = Field(default=None, max_length=128)
    approval_mode: str = Field(default="solo", pattern="^(solo|small_team)$")
    qualified_operators: int = Field(default=1, ge=1, le=1000)
    incident_id: Optional[str] = Field(default=None, max_length=128)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ContainmentRequest(BaseModel):
    scope: str = Field(min_length=1, max_length=32)
    control: str = Field(min_length=1, max_length=64)
    target: Optional[str] = Field(default=None, max_length=256)
    reason: str = Field(min_length=1, max_length=2000)


class SafeModeRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=2000)


# ── Exceptions ───────────────────────────────────────────────────────────────


@router.get("/exceptions")
async def read_exception_queue(
    request: Request,
    bucket: Optional[str] = Query(default=None, max_length=32),
    status: Optional[str] = Query(default="open", max_length=32),
    limit: int = Query(default=100, ge=1, le=500),
    context: Any = Depends(
        _require(
            INCIDENT_READ,
            disclosure=DisclosureLevel.D1_FLEET_AGGREGATE,
            action_class=ACTION_CLASS_READ,
        )
    ),
) -> dict[str, Any]:
    """The operator queue: buckets in urgency order, score-sorted within.

    The ordering is part of the contract, not a display preference — a security
    exposure outranks any volume of low-risk warnings by construction, and the
    arithmetic that produced each rank travels with the row.
    """
    data = await exception_service.queue(bucket=bucket, status=status, limit=limit)  # type: ignore[arg-type]
    return APIResponse(data=data, meta=_meta(context)).to_dict()


@router.get("/exceptions/{exception_id}")
async def read_exception(
    request: Request,
    exception_id: str = Path(min_length=1, max_length=128),
    context: Any = Depends(
        _require(
            INCIDENT_READ,
            disclosure=DisclosureLevel.D1_FLEET_AGGREGATE,
            action_class=ACTION_CLASS_READ,
        )
    ),
) -> dict[str, Any]:
    """One exception, with the priority inputs that ranked it."""
    exc = await exception_service.get(exception_id)
    return APIResponse(
        data={"found": exc is not None, "exception": exc.model_dump() if exc else None},
        meta=_meta(context),
    ).to_dict()


@router.post("/exceptions/{exception_id}/acknowledge")
async def acknowledge_exception(
    request: Request,
    exception_id: str = Path(min_length=1, max_length=128),
    context: Any = Depends(
        _require(
            INCIDENT_MANAGE,
            disclosure=DisclosureLevel.D4_EVENT_EVIDENCE,
            action_class=ACTION_CLASS_ANNOTATE,
        )
    ),
) -> dict[str, Any]:
    """Claim an exception. It stays in the queue — it now has an owner."""
    exc = await exception_service.acknowledge(
        exception_id, actor_id=getattr(context, "operator_id", "unknown")
    )
    return APIResponse(data={"exception": exc.model_dump()}, meta=_meta(context)).to_dict()


@router.post("/exceptions/{exception_id}/resolve")
async def resolve_exception(
    request: Request,
    body: ResolveExceptionRequest = Body(default_factory=ResolveExceptionRequest),
    exception_id: str = Path(min_length=1, max_length=128),
    context: Any = Depends(
        _require(
            INCIDENT_CLOSE,
            disclosure=DisclosureLevel.D4_EVENT_EVIDENCE,
            action_class=ACTION_CLASS_ANNOTATE,
        )
    ),
) -> dict[str, Any]:
    """Close an exception out.

    It leaves the compression set, so the same condition recurring opens a fresh
    row rather than reviving this one — a recurrence after a fix is new
    information.
    """
    exc = await exception_service.resolve(
        exception_id, actor_id=getattr(context, "operator_id", "unknown"), note=body.note
    )
    return APIResponse(data={"exception": exc.model_dump()}, meta=_meta(context)).to_dict()


@router.post("/exceptions/{exception_id}/suppress")
async def suppress_exception(
    request: Request,
    body: SuppressExceptionRequest,
    exception_id: str = Path(min_length=1, max_length=128),
    context: Any = Depends(
        _require(
            INCIDENT_CLOSE,
            disclosure=DisclosureLevel.D4_EVENT_EVIDENCE,
            action_class=ACTION_CLASS_ANNOTATE,
        )
    ),
) -> dict[str, Any]:
    """Silence an exception, with a mandatory recorded reason."""
    exc = await exception_service.suppress(
        exception_id,
        actor_id=getattr(context, "operator_id", "unknown"),
        reason=body.reason,
    )
    return APIResponse(data={"exception": exc.model_dump()}, meta=_meta(context)).to_dict()


# ── Incidents ────────────────────────────────────────────────────────────────


@router.get("/incidents")
async def list_incidents(
    request: Request,
    status: Optional[str] = Query(default="open", max_length=32),
    limit: int = Query(default=100, ge=1, le=500),
    context: Any = Depends(
        _require(
            INCIDENT_READ,
            disclosure=DisclosureLevel.D1_FLEET_AGGREGATE,
            action_class=ACTION_CLASS_READ,
        )
    ),
) -> dict[str, Any]:
    """Incidents by status, worst-priority first."""
    incidents = await incident_correlator.list_incidents(status=status, limit=limit)
    return APIResponse(
        data={
            "incidents": [incident.model_dump() for incident in incidents],
            "count": len(incidents),
            "status_filter": status,
            "generated_at": now_iso(),
        },
        meta=_meta(context),
    ).to_dict()


# Declared before ``/incidents/{incident_id}`` so the literal path is not
# swallowed by the parameterised one.
@router.get("/incidents/resume-cards")
async def read_resume_cards(
    request: Request,
    limit: int = Query(default=50, ge=1, le=200),
    context: Any = Depends(
        _require(
            INCIDENT_READ,
            disclosure=DisclosureLevel.D1_FLEET_AGGREGATE,
            action_class=ACTION_CLASS_READ,
        )
    ),
) -> dict[str, Any]:
    """What a returning operator needs to resume each half-finished response.

    Deterministic fields only: last action, next action, what is blocking, and
    what is still pending verification. The card has to be readable when no
    summariser is available.
    """
    cards = await incident_correlator.resume_cards(limit=limit)
    return APIResponse(
        data={"cards": cards, "count": len(cards), "generated_at": now_iso()},
        meta=_meta(context),
    ).to_dict()


@router.get("/incidents/{incident_id}")
async def read_incident(
    request: Request,
    incident_id: str = Path(min_length=1, max_length=128),
    context: Any = Depends(
        _require(
            INCIDENT_READ,
            disclosure=DisclosureLevel.D1_FLEET_AGGREGATE,
            action_class=ACTION_CLASS_READ,
        )
    ),
) -> dict[str, Any]:
    """One incident with its timeline: signals, correlations and commands.

    Each signal carries the ``correlation_basis`` that attached it, so a wrong
    correlation is auditable rather than mysterious.
    """
    incident = await incident_correlator.get_incident(incident_id)
    if incident is None:
        return APIResponse(
            data={"found": False, "incident": None}, meta=_meta(context)
        ).to_dict()
    signals = await incident_correlator.signals_for(incident_id)
    commands = await command_service.list_commands(status=None, limit=100)
    return APIResponse(
        data={
            "found": True,
            "incident": incident.model_dump(),
            "resume_card": incident_correlator.resume_card(incident),
            "timeline": [signal.model_dump() for signal in signals],
            "correlations": (incident.metadata or {}).get("correlations", []),
            "weak_links": (incident.metadata or {}).get("weak_links", []),
            "commands": [
                row for row in commands if row.get("incident_id") == incident_id
            ],
            "generated_at": now_iso(),
        },
        meta=_meta(context),
    ).to_dict()


@router.get("/incidents/{incident_id}/signals")
async def read_incident_signals(
    request: Request,
    incident_id: str = Path(min_length=1, max_length=128),
    limit: int = Query(default=200, ge=1, le=1000),
    context: Any = Depends(
        _require(
            INCIDENT_READ,
            disclosure=DisclosureLevel.D1_FLEET_AGGREGATE,
            action_class=ACTION_CLASS_READ,
        )
    ),
) -> dict[str, Any]:
    """Every signal attributed to an incident, oldest observation first."""
    signals = await incident_correlator.signals_for(incident_id, limit=limit)
    return APIResponse(
        data={
            "incident_id": incident_id,
            "signals": [signal.model_dump() for signal in signals],
            "count": len(signals),
        },
        meta=_meta(context),
    ).to_dict()


@router.patch("/incidents/{incident_id}")
async def update_incident(
    request: Request,
    body: UpdateIncidentRequest,
    incident_id: str = Path(min_length=1, max_length=128),
    context: Any = Depends(
        _require(
            INCIDENT_MANAGE,
            disclosure=DisclosureLevel.D4_EVENT_EVIDENCE,
            action_class=ACTION_CLASS_ANNOTATE,
        )
    ),
) -> dict[str, Any]:
    """Apply an operator update. Nothing clears a field that was not named."""
    fields = {key: value for key, value in body.model_dump().items() if value is not None}
    incident = await incident_correlator.update_incident(
        incident_id, actor_id=getattr(context, "operator_id", "unknown"), **fields
    )
    return APIResponse(
        data={
            "incident": incident.model_dump(),
            "resume_card": incident_correlator.resume_card(incident),
        },
        meta=_meta(context),
    ).to_dict()


@router.post("/incidents/{incident_id}/resolve")
async def resolve_incident(
    request: Request,
    body: ResolveIncidentRequest = Body(default_factory=ResolveIncidentRequest),
    incident_id: str = Path(min_length=1, max_length=128),
    context: Any = Depends(
        _require(
            INCIDENT_CLOSE,
            disclosure=DisclosureLevel.D4_EVENT_EVIDENCE,
            action_class=ACTION_CLASS_ANNOTATE,
        )
    ),
) -> dict[str, Any]:
    """Resolve an incident, recording the root cause on the record itself."""
    incident = await incident_correlator.resolve_incident(
        incident_id,
        actor_id=getattr(context, "operator_id", "unknown"),
        root_cause=body.root_cause,
    )
    return APIResponse(data={"incident": incident.model_dump()}, meta=_meta(context)).to_dict()


# ── Commands ─────────────────────────────────────────────────────────────────


# Declared before ``/commands/{command_id}`` so the literal path wins.
@router.get("/commands/types")
async def list_command_types(
    request: Request,
    context: Any = Depends(
        _require(
            COMMAND_FLOOR_CAPABILITY,
            disclosure=DisclosureLevel.D0_PLATFORM_TOPOLOGY,
            action_class=ACTION_CLASS_READ,
        )
    ),
) -> dict[str, Any]:
    """The command catalog: what exists, what authorises it, what verifies it.

    Readable by any authenticated operator. Knowing that
    ``activate_kill_switch`` exists confers nothing — running it needs
    ``kyber.command.kill_switch``, a class 5 ceiling and a live step-up — and
    hiding the catalog would only mean an operator discovers their authority by
    trying things.
    """
    return APIResponse(
        data={
            "types": [
                spec.model_dump() for spec in sorted(
                    COMMAND_REGISTRY.values(), key=lambda item: (item.action_class, item.command_type)
                )
            ],
            "count": len(COMMAND_REGISTRY),
            "generated_at": now_iso(),
        },
        meta=_meta(context),
    ).to_dict()


@router.get("/commands")
async def list_commands(
    request: Request,
    status: Optional[str] = Query(default="open", max_length=32),
    command_type: Optional[str] = Query(default=None, max_length=128),
    limit: int = Query(default=100, ge=1, le=500),
    context: Any = Depends(
        _require(
            AUDIT_READ,
            disclosure=DisclosureLevel.D4_EVENT_EVIDENCE,
            action_class=ACTION_CLASS_READ,
        )
    ),
) -> dict[str, Any]:
    """Commands by status. ``status=open`` includes ``executed_unverified``.

    That inclusion is the point of the queue: a command whose postconditions
    were never confirmed is still an open question, however long ago the call
    returned.
    """
    rows = await command_service.list_commands(
        status=status, command_type=command_type, limit=limit
    )
    return APIResponse(
        data={"commands": rows, "count": len(rows), "status_filter": status},
        meta=_meta(context),
    ).to_dict()


@router.get("/commands/{command_id}")
async def read_command(
    request: Request,
    command_id: str = Path(min_length=1, max_length=128),
    context: Any = Depends(
        _require(
            AUDIT_READ,
            disclosure=DisclosureLevel.D4_EVENT_EVIDENCE,
            action_class=ACTION_CLASS_READ,
        )
    ),
) -> dict[str, Any]:
    """One command with its execution and its verification.

    ``verification: null`` is a real answer and must be rendered as "not
    verified", never omitted — that is the difference between a question nobody
    asked and one that is still open.
    """
    data = await command_service.describe(command_id)
    return APIResponse(data=data, meta=_meta(context)).to_dict()


@router.post("/commands")
async def request_command(
    request: Request,
    body: CommandRequestBody,
    context: Any = Depends(
        _require(
            COMMAND_FLOOR_CAPABILITY,
            disclosure=DisclosureLevel.D0_PLATFORM_TOPOLOGY,
            action_class=ACTION_CLASS_READ,
        )
    ),
) -> dict[str, Any]:
    """Request a governed command. Requesting is not executing.

    The dependency above only proved a live session. The real gate is the nested
    authorization on the next line, which evaluates the *spec's* capability,
    disclosure and action class — step-up included — and writes its own decision
    row.
    """
    authorized, spec = await _authorize_command(request, body.command_type, body.tenant_ids)
    command = await command_service.request(
        command_type=body.command_type,
        requested_by=getattr(authorized, "operator_id", "unknown"),
        reason=body.reason,
        idempotency_key=body.idempotency_key,
        tenant_ids=body.tenant_ids,
        resource_ids=body.resource_ids,
        session_id=getattr(getattr(authorized, "session", None), "session_id", None),
        device_id=getattr(authorized, "device_id", None),
        environment=getattr(authorized, "environment", "local"),
        capabilities=getattr(authorized, "capabilities", None),
        role_template_ids=list(getattr(authorized, "role_template_ids", ()) or ()),
        approval_mode=body.approval_mode,  # type: ignore[arg-type]
        qualified_operators=body.qualified_operators,
        rollback_plan=body.rollback_plan,
        typed_confirmation=body.typed_confirmation,
        incident_id=body.incident_id,
        policy_decision_id=getattr(
            getattr(authorized, "decision", None), "policy_decision_id", None
        ),
        metadata=body.metadata,
    )
    return APIResponse(
        data={
            "command": command.model_dump(),
            "spec": spec.model_dump(),
            "approval_gaps": command.metadata.get("approval_gaps", []),
            "executable": not command.metadata.get("approval_gaps"),
        },
        meta=_meta(authorized),
    ).to_dict()


@router.post("/commands/{command_id}/dry-run")
async def dry_run_command(
    request: Request,
    command_id: str = Path(min_length=1, max_length=128),
    context: Any = Depends(
        _require(
            COMMAND_FLOOR_CAPABILITY,
            disclosure=DisclosureLevel.D0_PLATFORM_TOPOLOGY,
            action_class=ACTION_CLASS_READ,
        )
    ),
) -> dict[str, Any]:
    """Resolve and bind the handler without calling it.

    Nothing is dispatched. What the operator gets back is proof that the handler
    exists, that the arguments bind against its real signature, and which
    containment switch the command will flip.
    """
    command = await command_service.require(command_id)
    authorized, _spec = await _authorize_command(
        request, command.command_type, command.tenant_ids
    )
    plan = await command_service.dry_run(
        command_id, actor_id=getattr(authorized, "operator_id", "unknown")
    )
    return APIResponse(data={"plan": plan}, meta=_meta(authorized)).to_dict()


@router.post("/commands/{command_id}/approve")
async def approve_command(
    request: Request,
    command_id: str = Path(min_length=1, max_length=128),
    context: Any = Depends(
        _require(
            COMMAND_FLOOR_CAPABILITY,
            disclosure=DisclosureLevel.D0_PLATFORM_TOPOLOGY,
            action_class=ACTION_CLASS_READ,
        )
    ),
) -> dict[str, Any]:
    """Add one approval.

    Self-approval, an unqualified approver and the same operator approving twice
    are all refused *and* audited by the approval policy. A rejection nobody can
    see is not evidence.
    """
    command = await command_service.require(command_id)
    authorized, _spec = await _authorize_command(
        request, command.command_type, command.tenant_ids
    )
    updated = await command_service.approve(
        command_id,
        approver_id=getattr(authorized, "operator_id", "unknown"),
        role_template_ids=list(getattr(authorized, "role_template_ids", ()) or ()),
    )
    return APIResponse(
        data={
            "command": updated.model_dump(),
            "approval_gaps": updated.metadata.get("approval_gaps", []),
        },
        meta=_meta(authorized),
    ).to_dict()


@router.post("/commands/{command_id}/execute")
async def execute_command(
    request: Request,
    command_id: str = Path(min_length=1, max_length=128),
    context: Any = Depends(
        _require(
            COMMAND_FLOOR_CAPABILITY,
            disclosure=DisclosureLevel.D0_PLATFORM_TOPOLOGY,
            action_class=ACTION_CLASS_READ,
        )
    ),
) -> dict[str, Any]:
    """Dispatch the command, then go and check whether it worked.

    A 200 from this route is not a claim of success. Read
    ``command.status``: ``verified`` means the postconditions were checked and
    held; ``executed_unverified`` means the call returned and at least one
    postcondition failed or could not be determined — the failing check is named
    in ``verification.failure_reason``.
    """
    command = await command_service.require(command_id)
    authorized, _spec = await _authorize_command(
        request, command.command_type, command.tenant_ids
    )
    result = await command_service.execute(
        command_id, actor_id=getattr(authorized, "operator_id", "unknown")
    )
    return APIResponse(data=result, meta=_meta(authorized)).to_dict()


@router.post("/commands/{command_id}/verify")
async def verify_command(
    request: Request,
    command_id: str = Path(min_length=1, max_length=128),
    context: Any = Depends(
        _require(
            COMMAND_FLOOR_CAPABILITY,
            disclosure=DisclosureLevel.D0_PLATFORM_TOPOLOGY,
            action_class=ACTION_CLASS_READ,
        )
    ),
) -> dict[str, Any]:
    """Re-run the postconditions of a command that already executed.

    This is the ONLY route out of ``executed_unverified``. Some checks are
    answerable only once the platform catches up — a job that was queued when
    the first verification ran may have succeeded since — so a command that
    honestly could not be confirmed at execution time needs a way to be
    confirmed later.

    Without this route the state would be a dead end, and a dead end is how
    ``executed_unverified`` degrades into decoration: an operator who cannot
    ever resolve it learns to read it as "probably fine", which is precisely the
    reading the status exists to prevent. Note what this route still is not — a
    way to *declare* a command verified. It re-runs the checks; the checks
    decide.
    """
    command = await command_service.require(command_id)
    authorized, _spec = await _authorize_command(
        request, command.command_type, command.tenant_ids
    )
    result = await command_service.verify(
        command_id, actor_id=getattr(authorized, "operator_id", "unknown")
    )
    return APIResponse(data=result, meta=_meta(authorized)).to_dict()


# ── Containment ──────────────────────────────────────────────────────────────


@router.get("/containment")
async def read_containment(
    request: Request,
    context: Any = Depends(
        _require(
            INCIDENT_READ,
            disclosure=DisclosureLevel.D1_FLEET_AGGREGATE,
            action_class=ACTION_CLASS_READ,
        )
    ),
) -> dict[str, Any]:
    """Every active switch, plus whether safe mode is on and what it preserves.

    ``preserved_in_safe_mode`` is on the response deliberately: safe mode does
    not stop ingestion, and an operator who assumes it did will draw the wrong
    conclusion from a quiet pipeline.
    """
    data = await containment_service.describe()
    return APIResponse(data=data, meta=_meta(context)).to_dict()


@router.post("/containment/activate")
async def activate_containment(
    request: Request,
    body: ContainmentRequest,
    context: Any = Depends(
        _require(
            PAUSE_CAPABILITY,
            disclosure=DisclosureLevel.D4_EVENT_EVIDENCE,
            action_class=ACTION_CLASS_HIGH_IMPACT,
            tenant_scope="optional",
        )
    ),
) -> dict[str, Any]:
    """Flip a scoped pause on, with its reach assessed first.

    Idempotent: an already-active switch for the same ``(scope, target,
    control)`` comes back unchanged rather than duplicated.
    """
    switch = await containment_service.activate(
        scope=body.scope,  # type: ignore[arg-type]
        target=body.target,
        control=body.control,
        actor_id=getattr(context, "operator_id", "unknown"),
        reason=body.reason,
    )
    return APIResponse(data={"switch": switch.model_dump()}, meta=_meta(context)).to_dict()


@router.post("/containment/deactivate")
async def deactivate_containment(
    request: Request,
    body: ContainmentRequest,
    context: Any = Depends(
        _require(
            PAUSE_CAPABILITY,
            disclosure=DisclosureLevel.D4_EVENT_EVIDENCE,
            action_class=ACTION_CLASS_HIGH_IMPACT,
            tenant_scope="optional",
        )
    ),
) -> dict[str, Any]:
    """Release a scoped pause. ``released: false`` means none was active."""
    switch = await containment_service.deactivate(
        scope=body.scope,  # type: ignore[arg-type]
        target=body.target,
        control=body.control,
        actor_id=getattr(context, "operator_id", "unknown"),
        reason=body.reason,
    )
    return APIResponse(
        data={"released": switch is not None, "switch": switch.model_dump() if switch else None},
        meta=_meta(context),
    ).to_dict()


@router.post("/containment/safe-mode")
async def activate_safe_mode(
    request: Request,
    body: SafeModeRequest,
    context: Any = Depends(
        _require(
            KILL_SWITCH_CAPABILITY,
            disclosure=DisclosureLevel.D4_EVENT_EVIDENCE,
            action_class=ACTION_CLASS_FLEET_DESTRUCTIVE,
        )
    ),
) -> dict[str, Any]:
    """Freeze the platform to the smallest safe surface.

    Ingestion keeps running. Losing inbound events during an incident turns a
    recoverable outage into permanent data loss, so safe mode stops mutations,
    automation, reward distribution and mirror writes — and says so in the
    response rather than leaving the operator to assume.
    """
    switches = await containment_service.activate_safe_mode(
        actor_id=getattr(context, "operator_id", "unknown"), reason=body.reason
    )
    return APIResponse(
        data={
            "safe_mode": True,
            "switches": [switch.model_dump() for switch in switches],
            "state": await containment_service.describe(),
        },
        meta=_meta(context),
    ).to_dict()


@router.delete("/containment/safe-mode")
async def deactivate_safe_mode(
    request: Request,
    reason: str = Query(default="", max_length=2000),
    context: Any = Depends(
        _require(
            KILL_SWITCH_CAPABILITY,
            disclosure=DisclosureLevel.D4_EVENT_EVIDENCE,
            action_class=ACTION_CLASS_FLEET_DESTRUCTIVE,
        )
    ),
) -> dict[str, Any]:
    """Release safe mode. The marker clears first, so a partial release reports
    itself inactive rather than trapping the platform in a state that looks
    frozen but is not."""
    released = await containment_service.deactivate_safe_mode(
        actor_id=getattr(context, "operator_id", "unknown"), reason=reason
    )
    return APIResponse(
        data={
            "released": [switch.model_dump() for switch in released],
            "state": await containment_service.describe(),
        },
        meta=_meta(context),
    ).to_dict()


__all__ = [
    "AUDIT_READ",
    "COMMAND_FLOOR_CAPABILITY",
    "INCIDENT_CLOSE",
    "INCIDENT_MANAGE",
    "INCIDENT_READ",
    "KILL_SWITCH_CAPABILITY",
    "PAUSE_CAPABILITY",
    "CommandRequestBody",
    "ContainmentRequest",
    "SafeModeRequest",
    "router",
]
