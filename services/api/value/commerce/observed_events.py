"""Bounded Commerce360 reads of canonical Silver event observations.

Silver carries accepted source assertions. These reads disclose only records
with an exact product or offer key; Commerce360 separately resolves that key
against the tenant catalog before admitting the result.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from repositories.repos import AnalyticsRepository
from shared.intelligence_projections.contracts import ProjectionSubject


CommerceObservationSlot = Literal["exposures", "cart_checkout"]
_TABLE_BY_SLOT = {
    "exposures": "silver_exposure_facts",
    "cart_checkout": "silver_commerce_flow_facts",
}
_FLOW_TYPES = frozenset(
    {
        "cart_item_added",
        "cart_item_removed",
        "cart_updated",
        "checkout_started",
        "checkout_step_completed",
    }
)
_LIMIT = 500


def _instant(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        result = value
    elif isinstance(value, str):
        try:
            result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    return result.astimezone(timezone.utc) if result.tzinfo is not None else None


def _identifier(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    if not value or len(value) > 512 or any(ord(char) < 32 for char in value):
        return None
    return value


class RepositoryCommerceObservedEventSource:
    """Return exact, time-bounded Silver observations without raw payloads."""

    def __init__(self, repository: AnalyticsRepository | None = None) -> None:
        if repository is None:
            from dependencies.providers import get_cache

            repository = AnalyticsRepository(get_cache())
        self._repository = repository

    async def read(
        self,
        tenant_id: str,
        subject: ProjectionSubject,
        *,
        slot: CommerceObservationSlot,
        as_of: str,
        historical: bool,
    ) -> dict[str, Any]:
        scope = {
            "tenantId": tenant_id,
            "subjectKind": subject.kind,
            "subjectId": subject.id,
        }
        base: dict[str, Any] = {
            "_scope": scope,
            "slot": slot,
            "asOf": as_of,
            "sourceState": "unknown",
            "reason": "commerce_observation_source_unavailable",
            "records": [],
            "truncated": False,
            "sourceCompleteness": "unknown",
            "authorityRefs": [
                "commerce_product_offer_graph",
                _TABLE_BY_SLOT[slot],
                "source_provenance",
            ],
        }
        anchor = _instant(as_of)
        if subject.kind not in {"product", "offer"} or anchor is None:
            return {**base, "reason": "commerce_observation_subject_or_anchor_invalid"}
        filters = {"tenant_id": tenant_id}
        if slot == "exposures":
            filters.update({"content_type": subject.kind, "content_id": subject.id})
        else:
            filters.update({"subject_kind": subject.kind, "subject_id": subject.id})
        try:
            rows = await self._repository.query_silver(
                _TABLE_BY_SLOT[slot], filters, limit=_LIMIT + 1
            )
        except Exception:  # noqa: BLE001 - missing table/source is explicit unknown
            return base

        records: list[dict[str, Any]] = []
        invalid = 0
        for row in rows[:_LIMIT]:
            if (
                row.get("tenant_id") != tenant_id
                or (
                    slot == "exposures"
                    and (row.get("content_type"), row.get("content_id"))
                    != (subject.kind, subject.id)
                )
                or (
                    slot == "cart_checkout"
                    and (row.get("subject_kind"), row.get("subject_id"))
                    != (subject.kind, subject.id)
                )
            ):
                invalid += 1
                continue
            source_id = _identifier(str(row.get("source_event_id") or ""))
            event_type = _identifier(row.get("source_event_type"))
            occurred = _instant(row.get("occurred_at"))
            received = _instant(row.get("received_at"))
            if not source_id or not event_type or occurred is None:
                invalid += 1
                continue
            if slot == "cart_checkout" and event_type not in _FLOW_TYPES:
                invalid += 1
                continue
            if (
                occurred > anchor
                or (received is not None and received > anchor)
                or (historical and received is None)
            ):
                continue
            record = {
                "sourceEventId": source_id,
                "eventType": event_type,
                "subjectKind": subject.kind,
                "subjectId": subject.id,
                "occurredAt": occurred.isoformat(),
                "receivedAt": received.isoformat() if received else None,
                "sourceTable": _TABLE_BY_SLOT[slot],
                "consentSnapshotId": _identifier(row.get("consent_snapshot_id")),
            }
            if slot == "cart_checkout":
                record["cartId"] = _identifier(row.get("cart_id"))
                record["checkoutId"] = _identifier(row.get("checkout_id"))
            records.append(record)
        truncated = len(rows) > _LIMIT
        if not records:
            return {
                **base,
                "reason": (
                    "commerce_observation_rows_invalid_or_truncated"
                    if invalid or truncated
                    else "no_exact_source_observation_source_coverage_unknown"
                ),
                "truncated": truncated,
                "sourceCompleteness": "partial" if invalid or truncated else "unknown",
            }
        return {
            **base,
            "sourceState": "degraded",
            "reason": (
                "commerce_observation_rows_invalid_or_truncated"
                if invalid or truncated
                else "source_asserted_observations_coverage_and_freshness_unknown"
            ),
            "records": records,
            "truncated": truncated,
            "sourceCompleteness": "partial" if invalid or truncated else "unknown",
        }


__all__ = ["CommerceObservationSlot", "RepositoryCommerceObservedEventSource"]
