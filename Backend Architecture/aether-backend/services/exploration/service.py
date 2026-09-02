"""Exploration orchestration — plan, execute, and envelope every request.

Ties the planner (per-filter dispositions), the surface adapters (typed reads
with truncation), and facets (cohort-minimum suppression) into the canonical
``ExplorationResultEnvelope``. The applicability report is attached to EVERY
envelope, whether or not the surface has a backend — so a submitted filter is
always accounted for, never silently dropped.
"""

from __future__ import annotations

import time
import uuid
from typing import Any, Optional

from shared.common.common import utc_now
from shared.exploration.generated_surfaces import SURFACE_CAPABILITIES
from shared.exploration.models import (
    ApplicabilityReport,
    ExplorationCompleteness,
    ExplorationContextV1,
    ExplorationExecution,
    ExplorationOpRecord,
    ExplorationOpResult,
    ExplorationPagination,
    ExplorationResultEnvelope,
    ExplorationScope,
    ExplorationSession,
    ExplorationTruth,
    TemporalSelection,
)

from services.exploration.adapters import AdapterContext, AdapterResult, get_adapter
from services.exploration.facets import FacetResult, compute_facets
from services.exploration.planner import ExplorationPlan, plan_context

from services.exploration.operations import apply_operation
from services.exploration.session import ExplorationSessionRepository

# S1 projection-engine composition (fail-isolated — see _compose_projection).
from shared.intelligence_projections.contracts import (
    ProjectionRequest,
    ProjectionSubject,
)
from shared.intelligence_projections.generated_registry import (
    INTELLIGENCE_PROJECTION_IDS,
    PROJECTION_SUBJECT_KINDS,
)
from shared.projection_engine.conflict import LensConflict, LensNotFound
from shared.projection_engine.lens_registry import (
    lens_registry as default_lens_registry,
)
from shared.projection_engine.lens_set import LensSet
from shared.projection_engine.runtime import runtime
from shared.projection_engine.temporal_modes import parse_temporal_mode


def _as_of(context: ExplorationContextV1) -> Optional[str]:
    temporal = context.temporal
    if temporal.mode in ("as_of", "compare"):
        return temporal.as_of
    return None


def _temporal_warnings(context: ExplorationContextV1) -> list[str]:
    caps = SURFACE_CAPABILITIES.get(context.scope.surface)
    if not caps:
        return []
    mode = context.temporal.mode
    if mode not in caps["supported_temporal_modes"]:
        return [f"temporal_mode_not_supported_by_surface:{mode}"]
    return []


def build_plan(
    context: ExplorationContextV1,
    *,
    redacted_fields: Optional[frozenset[str]] = None,
) -> ExplorationPlan:
    return plan_context(context, redacted_fields=redacted_fields)


def validate(
    context: ExplorationContextV1,
    *,
    redacted_fields: Optional[frozenset[str]] = None,
) -> dict[str, Any]:
    """Validate a context without executing it — dry-run applicability."""
    plan = build_plan(context, redacted_fields=redacted_fields)
    warnings = list(plan.warnings) + _temporal_warnings(context)
    return {
        "normalized_context": context.model_dump(mode="json"),
        "surface": plan.surface,
        "surface_registered": plan.surface_registered,
        "adapter_available": get_adapter(plan.surface) is not None,
        "applicability": plan.applicability.model_dump(mode="json"),
        "routed_filter_count": len(plan.applied_filters),
        "warnings": warnings,
    }


def _truth_state(adapter_result: Optional[AdapterResult], adapter_available: bool) -> str:
    if not adapter_available:
        return "error"
    if adapter_result is not None and adapter_result.populated:
        return "ready"
    return "empty"


def _envelope(
    context: ExplorationContextV1,
    plan: ExplorationPlan,
    *,
    data: Any,
    adapter_result: Optional[AdapterResult],
    adapter_available: bool,
    started: float,
    extra_warnings: list[str],
) -> ExplorationResultEnvelope:
    truncated = bool(adapter_result and adapter_result.truncation.truncated)
    trunc_reason = adapter_result.truncation.reason if adapter_result else None
    cursor = adapter_result.cursor if adapter_result else None
    total_estimate = (
        adapter_result.truncation.total_estimate if adapter_result else None
    )
    warnings = list(plan.warnings) + _temporal_warnings(context) + extra_warnings
    if adapter_result:
        warnings += list(adapter_result.warnings)
    if not adapter_available:
        warnings.append("surface_backend_not_available_on_this_deployment")

    return ExplorationResultEnvelope(
        query_id=str(uuid.uuid4()),
        normalized_context=context,
        data=data,
        pagination=ExplorationPagination(
            cursor=cursor,
            has_more=bool(truncated or cursor),
            total_estimate=total_estimate,
        ),
        completeness=ExplorationCompleteness(
            complete=(adapter_available and not truncated),
            sampled=False,
            truncated=truncated,
            truncation_reason=trunc_reason,
        ),
        truth=ExplorationTruth(
            overall_state=_truth_state(adapter_result, adapter_available),
            dimensions=[],
            freshness_watermark=utc_now().isoformat(),
        ),
        applicability=plan.applicability,
        execution=ExplorationExecution(
            duration_ms=(time.monotonic() - started) * 1000.0,
            cache_status="bypass",
            adapters=[plan.surface] if adapter_available else [],
        ),
        warnings=warnings,
    )


async def _run_adapter(
    plan: ExplorationPlan,
    context: ExplorationContextV1,
    *,
    request: Any,
    graph: Any,
    cache: Any,
    limit: int,
    cursor: Optional[str],
) -> Optional[AdapterResult]:
    adapter = get_adapter(plan.surface)
    if adapter is None:
        return None
    ctx = AdapterContext(
        tenant_id=context.scope.tenant_id,
        context=context,
        applied_filters=plan.applied_filters,
        as_of=_as_of(context),
        limit=limit,
        cursor=cursor,
        request=request,
        graph=graph,
        cache=cache,
    )
    return await adapter.execute(ctx)


async def execute_query(
    context: ExplorationContextV1,
    *,
    request: Any = None,
    graph: Any = None,
    cache: Any = None,
    limit: int = 100,
    cursor: Optional[str] = None,
    redacted_fields: Optional[frozenset[str]] = None,
) -> ExplorationResultEnvelope:
    started = time.monotonic()
    plan = build_plan(context, redacted_fields=redacted_fields)
    adapter_available = get_adapter(plan.surface) is not None
    adapter_result = await _run_adapter(
        plan, context, request=request, graph=graph, cache=cache,
        limit=limit, cursor=cursor,
    )
    return _envelope(
        context, plan,
        data=(adapter_result.data if adapter_result else None),
        adapter_result=adapter_result,
        adapter_available=adapter_available,
        started=started,
        extra_warnings=[],
    )


def _facet_records(adapter_result: Optional[AdapterResult]) -> list[dict[str, Any]]:
    """Flatten an adapter result into faceable record dicts (graph nodes)."""
    if adapter_result is None or not isinstance(adapter_result.data, dict):
        return []
    nodes = adapter_result.data.get("nodes")
    if isinstance(nodes, list):
        return [n for n in nodes if isinstance(n, dict)]
    return []


async def execute_facets(
    context: ExplorationContextV1,
    fields: list[str],
    *,
    request: Any = None,
    graph: Any = None,
    cache: Any = None,
    limit: int = 500,
    redacted_fields: Optional[frozenset[str]] = None,
) -> ExplorationResultEnvelope:
    started = time.monotonic()
    plan = build_plan(context, redacted_fields=redacted_fields)
    adapter_available = get_adapter(plan.surface) is not None
    caps = SURFACE_CAPABILITIES.get(plan.surface)
    extra_warnings: list[str] = []
    if caps is not None and not caps.get("supports_facets", False):
        extra_warnings.append("surface_does_not_support_facets")

    adapter_result = await _run_adapter(
        plan, context, request=request, graph=graph, cache=cache,
        limit=limit, cursor=None,
    )
    records = _facet_records(adapter_result)
    facet_result: FacetResult = compute_facets(records, fields)

    return _envelope(
        context, plan,
        data=facet_result.model_dump(mode="json"),
        adapter_result=adapter_result,
        adapter_available=adapter_available,
        started=started,
        extra_warnings=extra_warnings + facet_result.warnings,
    )


# ── Exploration sessions + operations (S5) ────────────────────────────────────

_sessions = ExplorationSessionRepository()

_VALID_SUBJECT_KINDS = frozenset(PROJECTION_SUBJECT_KINDS)
_DEFAULT_SUBJECT_KIND = "entity"


def _empty_context(tenant_id: str) -> ExplorationContextV1:
    """A minimal pre-op context for REJECTED results that had no input context."""
    return ExplorationContextV1(
        scope=ExplorationScope(tenant_id=tenant_id, surface="graph"),
        temporal=TemporalSelection(mode="window", field="occurred_at", timezone="UTC"),
    )


async def _compose_projection(
    context: ExplorationContextV1, tenant_id: str
) -> tuple[Optional[dict[str, Any]], str, list[str]]:
    """S1 engine composition for a post-op context.

    Returns ``(projection_summary, status, warnings)``. FAIL-ISOLATED: a
    non-projection surface yields ``(None, "applied", [])``; a registered
    projection id without a provider, an invalid lens frame, or any engine
    error yields a static-reason summary (``{"available": False, "reason":
    <static key>}``) with ``status="degraded"`` — NEVER an exception, NEVER an
    echoed provider diagnostic.
    """
    surface = context.scope.surface
    if surface not in INTELLIGENCE_PROJECTION_IDS:
        return None, "applied", []

    if surface not in runtime.available_projection_ids():
        return {"available": False, "reason": "provider_unavailable"}, "degraded", []

    try:
        if context.lens_set:
            LensSet.from_request(
                context.lens_set, registry=default_lens_registry
            ).validate(default_lens_registry)
    except (LensConflict, LensNotFound):
        return {"available": False, "reason": "lens_frame_invalid"}, "degraded", []

    focus = context.selection.focused if context.selection else None
    if focus is not None and focus.kind in _VALID_SUBJECT_KINDS:
        subject = ProjectionSubject(kind=focus.kind, id=focus.id)
    else:
        subject = ProjectionSubject(kind=_DEFAULT_SUBJECT_KIND, id="current")

    engine_mode = parse_temporal_mode(context.temporal_mode)
    try:
        result = await runtime.execute_projection(
            ProjectionRequest(
                projectionId=surface,
                tenantId=tenant_id,
                subject=subject,
                lensIds=context.lens_set,
                temporalMode=context.temporal_mode,
            ),
            lens_ids=context.lens_set,
            temporal_mode=engine_mode,
        )
    except Exception:  # noqa: BLE001 - fail-isolated composition
        return {"available": False, "reason": "projection_failed"}, "degraded", []

    degradation_state = result.degradation.level if result.degradation is not None else None
    summary = {
        "digest": result.digest,
        "lensIds": result.lensIds,
        "temporalMode": result.temporalMode,
        "degradationState": degradation_state,
        "suppressedSections": result.suppressedSections,
        "available": True,
    }
    return summary, "applied", []


async def create_session(
    context: ExplorationContextV1, *, tenant_id: str, session_id: Optional[str] = None
) -> ExplorationSession:
    """Create and persist a new exploration session seeded with ``context``."""
    sid = session_id or str(uuid.uuid4())
    now = utc_now().isoformat()
    session = ExplorationSession(
        session_id=sid,
        tenant_id=tenant_id,
        surface=context.scope.surface,
        seed_context=context,
        current_context=context,
        lens_set=context.lens_set,
        temporal_mode=context.temporal_mode,
        operations=[],
        op_count=0,
        created_at=now,
        updated_at=now,
    )
    await _sessions.upsert_scoped(tenant_id, sid, session.model_dump(mode="json"))
    return session


async def load_session(tenant_id: str, session_id: str) -> Optional[ExplorationSession]:
    record = await _sessions.get_scoped(tenant_id, session_id)
    if record is None:
        return None
    return _sessions.to_session(record)


async def list_sessions(
    tenant_id: str, limit: int = 100, offset: int = 0
) -> list[dict[str, Any]]:
    return await _sessions.list_scoped(tenant_id, limit=limit, offset=offset)


async def delete_session(tenant_id: str, session_id: str) -> bool:
    return await _sessions.delete_scoped(tenant_id, session_id)


async def _session_persistence_op(
    operation: str,
    context: Optional[ExplorationContextV1],
    tenant_id: str,
    session_id: Optional[str],
) -> ExplorationOpResult:
    """SAVE / LOAD — session-repository ops (no context transform)."""
    fallback_context = context if context is not None else _empty_context(tenant_id)
    if session_id is None:
        return ExplorationOpResult(
            session_id=None,
            op_number=0,
            operation=operation,
            context=fallback_context,
            status="rejected",
            reason=f"{operation.lower()}_requires_session_id",
        )
    session = await load_session(tenant_id, session_id)
    if session is None:
        return ExplorationOpResult(
            session_id=session_id,
            op_number=0,
            operation=operation,
            context=fallback_context,
            status="rejected",
            reason="session_not_found",
        )
    if operation == "SAVE":
        session.updated_at = utc_now().isoformat()
        await _sessions.upsert_scoped(
            tenant_id, session_id, session.model_dump(mode="json")
        )
    # LOAD — adopt the stored session's current_context.
    return ExplorationOpResult(
        session_id=session_id,
        op_number=session.op_count,
        operation=operation,
        context=session.current_context,
        status="applied",
        reason=None,
    )


async def execute_operation(
    context: Optional[ExplorationContextV1],
    operation: str,
    *,
    tenant_id: str,
    request: Any = None,
    session_id: Optional[str] = None,
    pivot=None,
    lens_ids: Optional[list[str]] = None,
    temporal: Optional[TemporalSelection] = None,
    filter_group=None,
    focus=None,
    temporal_mode: Optional[str] = None,
) -> ExplorationOpResult:
    """Apply one operation to a session (load-or-create), persist, compose S1.

    ``SAVE``/``LOAD`` are intercepted here (session-repository ops). ``OPEN``
    creates the session with ``context`` as the seed and returns ``op_number=0``
    with no history record (the initialization op). Every other operation runs
    through the pure ``apply_operation`` on ``session.current_context``; an
    applied (or degraded) op appends a record and bumps ``op_count``, a rejected
    op appends a rejected record without mutating the context.
    """
    if operation in ("SAVE", "LOAD"):
        return await _session_persistence_op(operation, context, tenant_id, session_id)

    if operation == "OPEN":
        if context is None:
            return ExplorationOpResult(
                session_id=session_id,
                op_number=0,
                operation=operation,
                context=_empty_context(tenant_id),
                status="rejected",
                reason="open_requires_seed_context",
            )
        session = await create_session(
            context, tenant_id=tenant_id, session_id=session_id
        )
        new_context, rejection, warnings = apply_operation(context, "OPEN", seed=context)
        # OPEN is the initialization op — compose but do not record.
        projection, comp_status, comp_warnings = await _compose_projection(
            new_context, tenant_id
        )
        return ExplorationOpResult(
            session_id=session.session_id,
            op_number=0,
            operation="OPEN",
            context=new_context,
            status=comp_status,
            reason=rejection,
            warnings=warnings + comp_warnings,
            projection=projection,
        )

    if session_id is None:
        return ExplorationOpResult(
            session_id=None,
            op_number=0,
            operation=operation,
            context=context if context is not None else _empty_context(tenant_id),
            status="rejected",
            reason="session_not_found",
        )
    session = await load_session(tenant_id, session_id)
    if session is None:
        return ExplorationOpResult(
            session_id=session_id,
            op_number=0,
            operation=operation,
            context=context if context is not None else _empty_context(tenant_id),
            status="rejected",
            reason="session_not_found",
        )

    op_number = len(session.operations) + 1
    now = utc_now().isoformat()
    new_context, rejection, warnings = apply_operation(
        session.current_context,
        operation,
        pivot=pivot,
        lens_ids=lens_ids,
        temporal=temporal,
        filter_group=filter_group,
        focus=focus,
        seed=session.seed_context,
        temporal_mode=temporal_mode,
    )

    if rejection is not None:
        session.operations.append(
            ExplorationOpRecord(
                op_number=op_number,
                operation=operation,
                context=session.current_context,  # pre-op unchanged
                status="rejected",
                reason=rejection,
                applied_at=now,
            )
        )
        session.op_count += 1
        session.updated_at = now
        await _sessions.upsert_scoped(
            tenant_id, session.session_id, session.model_dump(mode="json")
        )
        return ExplorationOpResult(
            session_id=session.session_id,
            op_number=op_number,
            operation=operation,
            context=session.current_context,
            status="rejected",
            reason=rejection,
            warnings=warnings,
        )

    projection, comp_status, comp_warnings = await _compose_projection(
        new_context, tenant_id
    )
    status = comp_status  # "applied" or "degraded"
    session.operations.append(
        ExplorationOpRecord(
            op_number=op_number,
            operation=operation,
            context=new_context,  # snapshot AFTER the op
            status=status,
            reason=None,
            applied_at=now,
        )
    )
    session.op_count += 1
    session.current_context = new_context
    session.updated_at = now
    await _sessions.upsert_scoped(
        tenant_id, session.session_id, session.model_dump(mode="json")
    )
    return ExplorationOpResult(
        session_id=session.session_id,
        op_number=op_number,
        operation=operation,
        context=new_context,
        status=status,
        reason=None,
        warnings=warnings + comp_warnings,
        projection=projection,
    )


__all__ = [
    "build_plan",
    "validate",
    "execute_query",
    "execute_facets",
    "create_session",
    "load_session",
    "list_sessions",
    "delete_session",
    "execute_operation",
    "ApplicabilityReport",
]
