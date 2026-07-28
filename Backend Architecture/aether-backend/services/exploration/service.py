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
    ExplorationPagination,
    ExplorationResultEnvelope,
    ExplorationTruth,
)

from services.exploration.adapters import AdapterContext, AdapterResult, get_adapter
from services.exploration.facets import FacetResult, compute_facets
from services.exploration.planner import ExplorationPlan, plan_context


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


__all__ = [
    "build_plan",
    "validate",
    "execute_query",
    "execute_facets",
    "ApplicabilityReport",
]
