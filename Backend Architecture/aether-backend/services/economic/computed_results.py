"""computed_results production writer (agent 1E — economic write-path closure).

Closes the Phase-0 gap for the economic domain: ``computed_results`` had a
repository (``services/computation/repositories.py``) but no production writer —
nothing persisted canonical computation results from the gold materializer or the
economic aggregation surface, so a restatement left no durable trail and
consumers could never observe *which* canonical result backed a gold row.

This module provides the production write seam:

  * :func:`persist_computed_results` — durable, idempotent writer for a set of
    :class:`CanonicalResult` values (or a dict keyed by definition id as produced
    by ``services.computation.campaign.canonical_campaign_metrics``). Re-writing
    the same scope (same ``context_hash``) for the same definition collapses into
    a no-op — at-least-once by construction, never a duplicate ``computed_results``
    row and never a spurious conflict raised to the caller.
  * :func:`campaign_computation_context` — a :class:`ComputationContext` for a
    campaign/journey scope with the canonical campaign/journey dimensions, so the
    gold materializer and the economic read surface reference the same scope
    identity (and therefore the same ``context_hash``).

Writer semantics follow ``ComputedResultsRepository`` exactly: rows are immutable
by supersession — an active row is never overwritten, only superseded — so the
writer never destroys evidence. A caller that needs to *correct* a result uses
``supersede`` (not this writer).

Observation-only: this module never signs, sends, or mutates external state.
"""

from __future__ import annotations

from typing import Any, Iterable, Optional, Union

from services.computation.campaign import (
    CampaignAggregates,
    canonical_campaign_metrics,
)
from services.computation.repositories import (
    ComputationConflictError,
    ComputedResultsRepository,
    get_computation_repository,
)
from shared.computation.context import ComputationContext
from shared.computation.result import CanonicalResult
from shared.computation.runtime import new_run_id
from shared.logger.logger import get_logger, metrics

logger = get_logger("aether.service.economic.computed_results")

ResultSet = Union[
    list[CanonicalResult],
    dict[str, CanonicalResult],
]


def campaign_computation_context(
    tenant_id: str,
    *,
    subject_type: str,
    subject_id: str,
    event_time_start: Optional[str],
    event_time_end: Optional[str],
    native_currency: str = "USD",
    journey_version: Optional[str] = None,
    campaign_mapping_version: Optional[str] = None,
    as_of: Optional[str] = None,
) -> ComputationContext:
    """A canonical scope for campaign/journey economics.

    Deterministic per ``(tenant, subject, window, currency, versions)`` — two
    materializations of the same window produce the same ``context_hash()``, so
    the writer's idempotency key is stable across crashes/restarts.
    """
    return ComputationContext(
        tenant_id=tenant_id,
        subject_type=subject_type,
        subject_id=subject_id,
        grain="daily",
        dimensions={
            "domain": "campaign",
            "subject_type": subject_type,
            "subject_id": subject_id,
        },
        event_time_start=event_time_start,
        event_time_end=event_time_end,
        native_currency=native_currency,
        reporting_currency=native_currency,
        as_of=as_of,
        journey_version=journey_version,
        campaign_mapping_version=campaign_mapping_version,
    )


def _result_to_row(result: CanonicalResult, *, run_id: Optional[str]) -> dict[str, Any]:
    """Normalize a CanonicalResult into the ComputedResultsRepository row shape.

    The repository expects a flat dict keyed on its columns; ``model_dump`` gives
    us the envelope (plus ``subject``/``scope``/``quality`` … which the repo's
    ``_row()`` tolerates by ``setdefault`` — unknown keys are only persisted via
    the ``data`` JSONB blob, so the full envelope survives in ``data``).
    """
    payload = result.model_dump(mode="json")
    payload["result_id"] = result.result_id
    payload["definition_id"] = result.definition_id
    payload["definition_version"] = result.definition_version
    payload["tenant_id"] = result.tenant_id
    payload["status"] = result.status.value
    payload["value_type"] = result.value_type.value if hasattr(result.value_type, "value") else str(result.value_type)
    payload["unit"] = result.unit
    payload["currency"] = result.currency
    payload["context_hash"] = result.context_hash
    payload["run_id"] = run_id or result.run_id
    payload["computed_at"] = result.computed_at
    return payload


async def persist_computed_results(
    results: ResultSet,
    *,
    tenant_id: str,
    repo: Optional[ComputedResultsRepository] = None,
    run_id: Optional[str] = None,
) -> dict[str, Any]:
    """Persist canonical results to ``computed_results`` (idempotent writer).

    Accepts a ``list[CanonicalResult]`` or a ``dict`` keyed by definition id (the
    shape returned by ``canonical_campaign_metrics``). Each result is written
    through ``ComputedResultsRepository.insert_result``; an active result that
    already exists for the same ``(tenant, definition, version, context_hash)``
    (a replay of the same scope after a crash/restart) is treated as already
    recorded — never a duplicate, never a raised conflict.

    Returns ``{"recorded": n, "already_recorded": m, "run_id": run_id}``.
    """
    if not tenant_id:
        raise ValueError("tenant_id is required to persist computed results")
    repo = repo or get_computation_repository()
    run_id = run_id or new_run_id()
    values: Iterable[CanonicalResult]
    if isinstance(results, dict):
        values = results.values()
    else:
        values = results

    recorded = 0
    already = 0
    failed: list[str] = []
    for result in values:
        if result.tenant_id and result.tenant_id != tenant_id:
            raise ValueError(
                f"result {result.result_id} tenant {result.tenant_id!r} does not match "
                f"writer tenant {tenant_id!r}"
            )
        row = _result_to_row(result, run_id=run_id)
        try:
            await repo.insert_result(row)
            recorded += 1
        except ComputationConflictError:
            # Same scope re-materialized after a crash: the active result already
            # exists and is identical (same deterministic context). No-op.
            already += 1
    metrics.increment(
        "economic_computed_results_recorded",
        value=recorded,
        labels={"tenant_id": tenant_id},
    )
    if recorded or already:
        logger.info(
            "computed_results write: tenant=%s recorded=%d already_recorded=%d",
            tenant_id, recorded, already,
        )
    return {
        "tenant_id": tenant_id,
        "run_id": run_id,
        "recorded": recorded,
        "already_recorded": already,
        "failed": failed,
    }


async def persist_campaign_metrics(
    tenant_id: str,
    aggregates: CampaignAggregates,
    context: ComputationContext,
    *,
    repo: Optional[ComputedResultsRepository] = None,
    run_id: Optional[str] = None,
) -> dict[str, Any]:
    """Persist the canonical campaign metrics for one campaign scope.

    Thin convenience over :func:`persist_computed_results` for the gold
    materializer: compute ``canonical_campaign_metrics`` for ``aggregates`` and
    write every result durably.
    """
    return await persist_computed_results(
        canonical_campaign_metrics(context, aggregates),
        tenant_id=tenant_id,
        repo=repo,
        run_id=run_id,
    )


__all__ = [
    "campaign_computation_context",
    "persist_computed_results",
    "persist_campaign_metrics",
]
