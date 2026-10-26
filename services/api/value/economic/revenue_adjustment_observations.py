"""Bounded Value360 observations from canonical conversion revenue adjustments.

These rows are adjustment events, not recognized revenue or attribution. The
reader accepts only conversion IDs already admitted by the exact tenant and
subject conversion inventory and never adds amounts across currencies.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Protocol
from urllib.parse import quote

from graph.operational_intelligence.models import EvidenceRef
from shared.intelligence_projections.contracts import ProjectionRequest
from shared.temporal.instant import try_parse_instant

_MAX_CONVERSIONS = 25
_MAX_ADJUSTMENTS_PER_CONVERSION = 20
_MAX_TOTAL_ADJUSTMENTS = 500
_JOIN_BASIS = {
    "conversion": "exact_canonical_conversion_id",
    "profile": "exact_canonical_profile_conversion_id",
    "entity": "exact_canonical_profile_conversion_id",
    "account": "exact_tenant_conversion_account_id",
    "cluster": "exact_canonical_conversion_cluster_id",
    "campaign": "canonical_campaign_touchpoint_or_attribution_conversion_join",
    "journey": "current_tenant_journey_version_conversion_ids",
    "agent": "validated_agent_identity_exact_conversion_agent_id",
}


class AdjustmentSource(Protocol):
    async def list_for_conversion(
        self,
        tenant_id: str,
        conversion_id: str,
        *,
        limit: int,
        after: datetime | None = None,
        before: datetime | None = None,
    ) -> list[dict[str, Any]]: ...


def _text(value: Any, *, limit: int = 128) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    if not stripped or len(stripped) > limit or any(ord(char) < 32 for char in stripped):
        return None
    return stripped


def _instant(value: Any) -> str | None:
    if isinstance(value, datetime):
        value = value.isoformat()
    if not isinstance(value, str):
        return None
    parsed, _ = try_parse_instant(value)
    return parsed.isoformat() if parsed is not None else None


def _amount(value: Any) -> str | None:
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return format(amount, "f") if amount.is_finite() else None


def _conversion_ref(raw: Any, conversion_id: str) -> EvidenceRef | None:
    if not isinstance(raw, list):
        return None
    for candidate in raw:
        try:
            ref = EvidenceRef.model_validate(candidate)
        except Exception:  # noqa: BLE001 - malformed evidence fails closed
            continue
        if (
            ref.id == conversion_id
            and ref.type == "transaction"
            and ref.source == "canonical_conversions"
            and ref.uri == f"store://canonical_conversions/{quote(conversion_id, safe='')}"
        ):
            return ref
    return None


async def read_revenue_adjustments(
    request: ProjectionRequest,
    conversion_inventory: dict[str, Any],
    *,
    source: AdjustmentSource | None = None,
    conversion_inventory_unwindowed_for_adjustments: bool = False,
) -> dict[str, Any]:
    """Read exact adjustment events, exposing every coverage or scope gap."""
    base: dict[str, Any] = {
        "tenantId": request.tenantId,
        "subject": request.subject.model_dump(),
        "canonicalAuthorityRefs": ["canonical_conversions", "revenue_adjustments"],
        "joinBasis": conversion_inventory.get("joinBasis"),
        "state": "unknown",
        "reason": "canonical_conversion_inventory_unavailable_for_adjustment_join",
        "completeness": "unknown",
        "records": [],
        "recordCount": 0,
        "conversionCountRead": 0,
        "truncated": False,
        "invalidRecordCount": 0,
        "readErrorCount": 0,
        "timeScope": "current_adjustment_rows_not_bitemporal",
        "limitations": [
            "adjustments_are_not_recognized_revenue_or_attributed_value",
            "source_completeness_and_historical_replay_are_unknown",
            "amounts_are_native_currency_observations_not_summed",
        ],
    }
    if request.asOf is not None or request.temporalMode in {"as_of", "compare", "relative"}:
        return {**base, "reason": "revenue_adjustment_history_not_bitemporal"}
    window = request.timeRange is not None
    window_cohort_partial = window and not conversion_inventory_unwindowed_for_adjustments
    after: datetime | None = None
    before: datetime | None = None
    if window:
        if request.timeRange.from_ is not None:
            after, issue = try_parse_instant(request.timeRange.from_)
            if issue is not None:
                return {**base, "reason": "revenue_adjustment_event_window_invalid"}
        if request.timeRange.to is not None:
            before, issue = try_parse_instant(request.timeRange.to)
            if issue is not None:
                return {**base, "reason": "revenue_adjustment_event_window_invalid"}
        if after is not None and before is not None and before <= after:
            return {**base, "reason": "revenue_adjustment_event_window_invalid"}
        base["timeScope"] = {
            "mode": "current_adjustment_event_time_window",
            "fromExclusive": after.isoformat() if after is not None else None,
            "toExclusive": before.isoformat() if before is not None else None,
            "historicalState": "unknown",
        }
        if window_cohort_partial:
            base["limitations"].append(
                "conversion_inventory_is_windowed_by_conversion_time_so_older_conversions_adjusted_in_window_may_be_missing"
            )
    inventory_state = conversion_inventory.get("state")
    if (
        inventory_state not in {"available", "degraded", "empty"}
        or conversion_inventory.get("joinBasis") != _JOIN_BASIS.get(request.subject.kind)
    ):
        return base
    rows = conversion_inventory.get("records")
    if not isinstance(rows, list):
        return {**base, "reason": "canonical_conversion_inventory_result_invalid"}
    if inventory_state == "empty" and rows:
        return {**base, "reason": "canonical_conversion_inventory_state_conflict"}
    if inventory_state == "empty" and not rows:
        if window_cohort_partial:
            return {
                **base,
                "reason": "windowed_conversion_inventory_cannot_prove_adjustment_absence",
            }
        return {
            **base,
            "state": "empty",
            "reason": "no_canonical_conversions_for_adjustment_join",
            "completeness": "bounded_read",
        }

    if source is None:
        try:
            from journeys.measurement.repositories.adjustment_repo import AdjustmentRepository

            source = AdjustmentRepository()
        except Exception:  # noqa: BLE001 - unavailable authority is explicit
            return {**base, "state": "missing", "reason": "revenue_adjustment_repository_unavailable"}

    from journeys.measurement.contracts import AdjustmentType

    allowed_types = {item.value for item in AdjustmentType}
    read_errors = 0
    invalid_rows = 0
    source_partial = (
        window_cohort_partial
        or inventory_state == "degraded"
        or conversion_inventory.get("completeness") not in {"complete", "bounded_read"}
    )
    truncated = len(rows) > _MAX_CONVERSIONS
    observed: list[dict[str, Any]] = []
    seen_conversion_ids: set[str] = set()
    seen_adjustment_ids: set[str] = set()
    for conversion in rows[:_MAX_CONVERSIONS]:
        if not isinstance(conversion, dict):
            invalid_rows += 1
            continue
        conversion_id = _text(conversion.get("conversionId"))
        if conversion_id is None or conversion_id in seen_conversion_ids:
            invalid_rows += 1
            continue
        if request.subject.kind == "conversion" and conversion_id != request.subject.id:
            invalid_rows += 1
            continue
        conversion_ref = _conversion_ref(conversion.get("evidenceRefs"), conversion_id)
        if conversion_ref is None:
            invalid_rows += 1
            continue
        seen_conversion_ids.add(conversion_id)
        if len(observed) >= _MAX_TOTAL_ADJUSTMENTS:
            truncated = True
            break
        limit = min(
            _MAX_ADJUSTMENTS_PER_CONVERSION,
            _MAX_TOTAL_ADJUSTMENTS - len(observed),
        )
        try:
            window_kwargs = {"after": after, "before": before} if window else {}
            adjustment_rows = await source.list_for_conversion(
                request.tenantId, conversion_id, limit=limit + 1, **window_kwargs
            )
        except Exception:  # noqa: BLE001 - preserve already-read exact events
            read_errors += 1
            continue
        if not isinstance(adjustment_rows, list):
            read_errors += 1
            continue
        if len(adjustment_rows) > limit:
            truncated = True
        for row in adjustment_rows[:limit]:
            if not isinstance(row, dict):
                invalid_rows += 1
                continue
            adjustment_id = _text(row.get("adjustment_id"))
            adjustment_type = _text(row.get("adjustment_type"), limit=32)
            amount = _amount(row.get("amount"))
            currency = _text(row.get("currency"), limit=16)
            occurred_at = _instant(row.get("occurred_at"))
            parsed_occurred_at = (
                try_parse_instant(occurred_at)[0] if occurred_at is not None else None
            )
            if (
                row.get("tenant_id") != request.tenantId
                or row.get("conversion_id") != conversion_id
                or adjustment_id is None
                or adjustment_id in seen_adjustment_ids
                or adjustment_type not in allowed_types
                or amount is None
                or currency is None
                or not currency.isascii()
                or not currency.isalnum()
                or occurred_at is None
                or (window and parsed_occurred_at is None)
                or (after is not None and parsed_occurred_at is not None and parsed_occurred_at <= after)
                or (before is not None and parsed_occurred_at is not None and parsed_occurred_at >= before)
            ):
                invalid_rows += 1
                continue
            ref = EvidenceRef(
                id=adjustment_id,
                type="transaction",
                source="revenue_adjustments",
                observedAt=_instant(row.get("created_at")),
                uri=f"store://revenue_adjustments/{quote(adjustment_id, safe='')}",
            )
            seen_adjustment_ids.add(adjustment_id)
            observed.append(
                {
                    "adjustmentId": adjustment_id,
                    "conversionId": conversion_id,
                    "adjustmentType": adjustment_type,
                    "amount": amount,
                    "currency": currency.upper(),
                    "occurredAt": occurred_at,
                    "sourceEventId": _text(row.get("source_event_id")),
                    "connectorRecordId": _text(row.get("connector_record_id")),
                    "evidenceRefs": [
                        conversion_ref.model_dump(mode="json"),
                        ref.model_dump(mode="json"),
                    ],
                }
            )

    incomplete = source_partial or truncated or bool(read_errors) or bool(invalid_rows)
    state = (
        "degraded" if incomplete and observed else "unknown" if incomplete else "available" if observed else "empty"
    )
    reason = (
        "revenue_adjustment_exact_scope_or_record_invalid" if invalid_rows
        else "revenue_adjustment_read_failed" if read_errors
        else "revenue_adjustment_read_truncated" if truncated
        else "canonical_conversion_inventory_partial_for_adjustments" if source_partial
        else "no_revenue_adjustments_for_exact_conversions" if not observed
        else None
    )
    return {
        **base,
        "state": state,
        "reason": reason,
        "completeness": "partial" if incomplete else "bounded_read",
        "records": observed,
        "recordCount": len(observed),
        "conversionCountRead": len(seen_conversion_ids),
        "truncated": truncated,
        "invalidRecordCount": invalid_rows,
        "readErrorCount": read_errors,
    }
