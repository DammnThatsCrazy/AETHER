"""Silver projector for the canonical ``ai_invocation_observed`` event.

Projects one Bronze event into one ``ai_execution_facts`` record:

- flag-gated on ``settings.ai_economics.execution_facts_enabled``;
- validates the payload against the canonical ``AIInvocationObserved``
  contract (rejecting any payload carrying prompt/completion content);
- computes ``selected_cost``/``cost_basis`` via the cost selection hierarchy
  (billed → provider_reported → calculated → estimated → unknown; unknown
  stays unknown);
- idempotent on (tenant_id, invocation_id): a duplicate with the same
  ``provenance.raw_event_hash`` is skipped, a duplicate with a different
  hash is rejected and metered;
- writes the fact to the durable ``ai_execution_facts`` store with a
  tenant-prefixed key.

``write_execution_fact`` is the single fact-writing seam — internal
recorders (e.g. Noesis telemetry) call it directly rather than going over
HTTP or through the bus.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, Optional

from pydantic import ValidationError

from config.settings import settings
from shared.logger.logger import get_logger, metrics
from shared.store import get_store

from services.economic.ai_costs import CostSelection, select_cost
from services.economic.ai_models import AIExecutionFact, AIInvocationObserved
from services.silver.projectors.base import BaseProjector, ProjectionResult

logger = get_logger("aether.silver.ai_invocation_projector")

AI_EXECUTION_FACTS_STORE = "ai_execution_facts"

# Dispositions returned by write_execution_fact / project_ai_invocation_event.
DISPOSITION_WRITTEN = "written"
DISPOSITION_DUPLICATE = "skipped_duplicate"
DISPOSITION_CONFLICT = "rejected_conflict"
DISPOSITION_INVALID = "rejected_invalid"
DISPOSITION_FLAG_OFF = "skipped_flag_disabled"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def fact_key(tenant_id: str, invocation_id: str) -> str:
    return f"{tenant_id}:{invocation_id}"


def _data_quality_status(observed: AIInvocationObserved, selection: CostSelection) -> str:
    """complete = usage + cost known; partial = usage or cost missing;
    estimated = estimated cost basis; suspect = currency mismatch."""
    if selection.currency_mismatch:
        return "suspect"
    if selection.cost_basis == "estimated":
        return "estimated"
    if not observed.usage_present() or selection.selected_cost is None:
        return "partial"
    return "complete"


async def write_execution_fact(
    observed: AIInvocationObserved,
) -> tuple[str, Optional[AIExecutionFact]]:
    """Compute cost, build the AIExecutionFact, and persist it idempotently.

    Returns (disposition, fact). ``fact`` is None unless disposition is
    ``written``.
    """
    store = get_store(AI_EXECUTION_FACTS_STORE)
    key = fact_key(observed.tenant_id, observed.invocation_id)

    existing = await store.get(key)
    if existing is not None:
        existing_hash = (existing.get("provenance") or {}).get("raw_event_hash")
        if existing_hash == observed.provenance.raw_event_hash:
            metrics.increment(
                "ai_execution_fact_duplicate_total",
                labels={"provider": observed.provider},
            )
            return DISPOSITION_DUPLICATE, None
        metrics.increment(
            "ai_execution_fact_conflict_total",
            labels={"provider": observed.provider},
        )
        logger.warning(
            "ai_execution_fact_conflict tenant=%s invocation=%s: duplicate invocation_id "
            "with different raw_event_hash — rejected",
            observed.tenant_id, observed.invocation_id,
        )
        return DISPOSITION_CONFLICT, None

    selection = await select_cost(observed)
    now = _utc_now_iso()
    fact = AIExecutionFact(
        **observed.model_dump(exclude={"pricing_version"}),
        pricing_version=selection.pricing_version or observed.pricing_version,
        selected_cost=selection.selected_cost,
        cost_basis=selection.cost_basis,
        received_at=now,
        computed_at=now,
        data_quality_status=_data_quality_status(observed, selection),
    )
    await store.set(key, fact.model_dump(mode="json"))
    metrics.increment(
        "ai_execution_fact_written_total",
        labels={"provider": observed.provider, "cost_basis": selection.cost_basis},
    )
    return DISPOSITION_WRITTEN, fact


def _payload_from_event(event: dict[str, Any]) -> dict[str, Any]:
    """Extract the canonical snake_case payload from a Bronze event envelope."""
    payload = dict(event.get("properties") or {})
    ctx = event.get("context") or {}
    payload.setdefault("tenant_id", ctx.get("tenantId") or event.get("tenantId") or "")
    payload.setdefault("observed_at", event.get("timestamp") or _utc_now_iso())
    return payload


async def project_ai_invocation_event(
    event: dict[str, Any],
) -> tuple[str, Optional[AIExecutionFact]]:
    """Async entry point: validate a Bronze event and write the execution fact."""
    if not settings.ai_economics.execution_facts_enabled:
        return DISPOSITION_FLAG_OFF, None
    try:
        observed = AIInvocationObserved.model_validate(_payload_from_event(event))
    except (ValidationError, ValueError) as exc:
        metrics.increment(
            "ai_execution_fact_rejected_total", labels={"reason": "invalid_payload"}
        )
        logger.warning("ai_invocation_observed rejected: %s", exc)
        return DISPOSITION_INVALID, None
    return await write_execution_fact(observed)


class AIInvocationProjector(BaseProjector):
    """Dispatcher-facing projector for ``ai_invocation_observed`` ONLY."""

    handles = frozenset({"ai_invocation_observed"})

    def project(self, event: dict[str, Any]) -> ProjectionResult | None:
        if event.get("type") not in self.handles:
            return None
        if not settings.ai_economics.execution_facts_enabled:
            return ProjectionResult(
                table=AI_EXECUTION_FACTS_STORE, rows=[],
                skipped=True, skip_reason="ai_execution_facts_disabled",
            )

        payload = _payload_from_event(event)
        try:
            observed = AIInvocationObserved.model_validate(payload)
        except (ValidationError, ValueError) as exc:
            metrics.increment(
                "ai_execution_fact_rejected_total", labels={"reason": "invalid_payload"}
            )
            logger.warning("ai_invocation_observed rejected: %s", exc)
            return ProjectionResult(
                table=AI_EXECUTION_FACTS_STORE, rows=[],
                skipped=True, skip_reason="invalid_payload",
            )

        # Durable fact write (cost selection + idempotency) happens on the
        # async seam; the dispatcher path is sync, so schedule accordingly.
        self._schedule_write(observed)

        row = {
            "id": fact_key(observed.tenant_id, observed.invocation_id),
            "tenant_id": observed.tenant_id,
            "provider": observed.provider,
            "model": observed.model,
            "status": observed.status,
            "payload": observed.model_dump(mode="json"),
        }
        return ProjectionResult(table=AI_EXECUTION_FACTS_STORE, rows=[row])

    @staticmethod
    def _schedule_write(observed: AIInvocationObserved) -> None:
        async def _safe_write() -> None:
            try:
                await write_execution_fact(observed)
            except Exception as exc:  # never propagate into the event loop
                logger.warning(
                    "ai_execution_fact write failed invocation=%s: %s",
                    observed.invocation_id, exc,
                )

        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                loop.create_task(_safe_write())
            else:
                loop.run_until_complete(_safe_write())
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning(
                "ai_execution_fact write scheduling failed invocation=%s: %s",
                observed.invocation_id, exc,
            )
