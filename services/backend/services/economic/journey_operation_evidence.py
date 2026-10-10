"""Exact-reference commerce evidence reads attached to canonical journeys."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Optional


async def journey_commerce_operation_evidence(
    tenant_id: str,
    journey_id: str,
    *,
    as_of: Optional[str] = None,
    max_steps: int = 10_000,
) -> dict[str, Any]:
    """Read operation links only from explicit refs in persisted journey steps.

    No joins are made on identity, amount, timestamp, order ID, or payment ID.
    The result contains only the source-reference contract, not copied values.
    """
    from services.measurement.repositories.journey_repo import JourneyRepository
    from services.measurement.repositories.journey_step_repo import JourneyStepRepository
    from services.commerce.order_payment_reconciliation import CommerceOrderPaymentLedger
    from services.economic.operation_linkage import commerce_ledger_operation_link

    journey = await JourneyRepository().get_current(tenant_id, journey_id)
    if journey is None:
        return {
            "journey_id": journey_id,
            "join_basis": "explicit_journey_step_commerce_order_ref",
            "operation_links": [],
            "reason": "journey_not_found",
            "amounts_included": False,
            "as_of": as_of,
        }

    repo = JourneyStepRepository()
    version_id = str(journey.get("journey_version_id"))
    refs: set[str] = set()
    scanned = 0
    cursor: Optional[str] = None
    truncated = False
    while scanned < max_steps:
        page = await repo.list_by_version(
            tenant_id,
            version_id,
            limit=min(500, max_steps - scanned),
            cursor=cursor,
        )
        if not page:
            break
        scanned += len(page)
        for step in page:
            summary = step.get("evidence_summary")
            if isinstance(summary, str):
                try:
                    summary = json.loads(summary)
                except (TypeError, ValueError):
                    summary = None
            if not isinstance(summary, dict):
                continue
            values = summary.get("commerce_order_refs", [])
            if isinstance(values, str):
                values = [values]
            if isinstance(values, list):
                refs.update(
                    value.strip() for value in values
                    if isinstance(value, str) and value.strip()
                )
            single = summary.get("commerce_order_ref")
            if isinstance(single, str) and single.strip():
                refs.add(single.strip())
        if len(page) < min(500, max_steps - (scanned - len(page))):
            break
        cursor = str(page[-1].get("step_position", ""))
        if scanned >= max_steps:
            remaining = await repo.list_by_version(
                tenant_id, version_id, limit=1, cursor=cursor
            )
            truncated = bool(remaining)

    ledger = CommerceOrderPaymentLedger()
    links = []
    for reference in sorted(refs):
        record = (
            await ledger.get_as_of(tenant_id, reference, as_of)
            if as_of
            else await ledger.get(tenant_id, reference)
        )
        if record is not None:
            links.append(commerce_ledger_operation_link(record).model_dump(mode="json"))

    return {
        "journey_id": journey_id,
        "join_basis": "explicit_journey_step_commerce_order_ref",
        "operation_links": links,
        "amounts_included": False,
        "unlinked_evidence": "not_inferred",
        "steps_scanned": scanned,
        "evidence_truncated": truncated,
        "as_of": as_of,
    }


__all__ = ["journey_commerce_operation_evidence"]
