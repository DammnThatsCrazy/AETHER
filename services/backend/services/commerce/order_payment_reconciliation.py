"""Tenant-scoped, exact-reference order/payment evidence reconciliation.

This ledger links independently observed commerce orders and completed payment
observations only when both carry the same explicit ``commerce_order_ref``.
It never joins on amount, time, email, or customer identity and does not write
graph facts or assert processor payout settlement.
"""

from __future__ import annotations

import hashlib
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from shared.common.common import utc_now
from shared.temporal.instant import coerce_utc_lenient, parse_instant_strict
from shared.store import DurableStore, get_store


def _key(tenant_id: str, ref: str) -> str:
    digest = hashlib.sha256(ref.encode("utf-8")).hexdigest()
    return f"{tenant_id}:{digest}"


class CommerceOrderPaymentLedger:
    """Replay-safe ledger for exact-reference commerce reconciliation."""

    def __init__(self, store: DurableStore | None = None) -> None:
        self._store = store or get_store("commerce_order_payment_evidence")

    async def record_order(
        self,
        tenant_id: str,
        *,
        commerce_order_ref: str,
        provider: str,
        provider_order_id: str,
        amount: str,
        currency: str,
        revision_id: str,
        source_revision_at: str | None,
        occurred_at: str,
    ) -> dict[str, Any]:
        """Upsert the authoritative order snapshot under its exact reference."""
        ref = _required(commerce_order_ref, "commerce_order_ref")
        order = {
            "provider": _required(provider, "provider"),
            "providerOrderId": _required(provider_order_id, "provider_order_id"),
            "amount": _decimal_text(amount),
            "currency": _currency(currency),
            "revisionId": _required(revision_id, "revision_id"),
            "sourceRevisionAt": source_revision_at or occurred_at,
            "occurredAt": occurred_at,
            "observedAt": utc_now().isoformat(),
        }
        key = _key(tenant_id, ref)
        record = await self._store.get(key) or {
            "tenantId": tenant_id,
            "commerceOrderRef": ref,
            "payments": {},
            "createdAt": occurred_at,
        }
        revision_history = record.get("orderRevisions")
        if not isinstance(revision_history, list):
            revision_history = []
        if not revision_history and isinstance(record.get("order"), dict):
            revision_history.append(record["order"])
        record["orderRevisions"] = revision_history
        prior_revision = next(
            (
                row for row in revision_history
                if row.get("revisionId") == order["revisionId"]
            ),
            None,
        )
        comparable_fields = (
            "provider", "providerOrderId", "amount", "currency", "revisionId",
            "sourceRevisionAt", "occurredAt",
        )
        if prior_revision is None:
            revision_history.append(order)
        elif any(prior_revision.get(field) != order.get(field) for field in comparable_fields):
            record["state"] = "conflict"
            record["conflictReason"] = "order_revision_id_reused_with_divergent_evidence"

        prior = record.get("order")
        if not prior:
            record["order"] = order
        elif prior.get("providerOrderId") != order["providerOrderId"]:
            record["state"] = "conflict"
            record["conflictReason"] = "reference_maps_to_multiple_orders"
        elif prior.get("revisionId") != order["revisionId"]:
            prior_revision_at = str(prior.get("sourceRevisionAt") or "")
            next_revision_at = str(order.get("sourceRevisionAt") or "")
            if next_revision_at > prior_revision_at:
                record["order"] = order
            elif next_revision_at == prior_revision_at:
                record["state"] = "conflict"
                record["conflictReason"] = "divergent_order_revisions_with_equal_source_time"
        record["updatedAt"] = max(str(record.get("updatedAt") or ""), occurred_at)
        self._reconcile(record)
        await self._store.set(key, record)
        return record

    async def record_payment(
        self,
        tenant_id: str,
        *,
        commerce_order_ref: str,
        provider: str,
        provider_payment_id: str,
        amount: str,
        currency: str,
        status: str,
        occurred_at: str,
    ) -> dict[str, Any]:
        """Record a provider payment only when its payload explicitly supplies
        the commerce reference. Callers must enforce their provider signature
        and payment status before invoking this method.
        """
        ref = _required(commerce_order_ref, "commerce_order_ref")
        payment_id = _required(provider_payment_id, "provider_payment_id")
        payment_provider = _required(provider, "provider").lower()
        payment = {
            "provider": payment_provider,
            "providerPaymentId": payment_id,
            "amount": _decimal_text(amount),
            "currency": _currency(currency),
            "status": _required(status, "status"),
            "occurredAt": occurred_at,
            "observedAt": utc_now().isoformat(),
        }
        key = _key(tenant_id, ref)
        record = await self._store.get(key) or {
            "tenantId": tenant_id,
            "commerceOrderRef": ref,
            "payments": {},
            "createdAt": occurred_at,
        }
        # Provider IDs are unique only inside their provider's namespace.
        # Include the provider in the key so equal IDs from distinct rails are
        # retained as two payment observations rather than overwriting one.
        payment_key = f"{payment_provider}:{payment_id}"
        payments = record.setdefault("payments", {})
        observations = record.setdefault("paymentObservations", [])
        if not isinstance(observations, list):
            observations = record["paymentObservations"] = []
        if not observations:
            observations.extend(
                row.copy() for row in payments.values() if isinstance(row, dict)
            )
        prior_payment = payments.get(payment_key)
        if prior_payment is None:
            payments[payment_key] = payment
            observations.append(payment.copy())
        elif any(
            prior_payment.get(field) != payment.get(field)
            for field in ("provider", "providerPaymentId", "amount", "currency", "status")
        ):
            record["state"] = "conflict"
            record["conflictReason"] = "provider_payment_id_reused_with_divergent_evidence"
            if not any(
                all(prior.get(field) == payment.get(field) for field in (
                    "provider", "providerPaymentId", "amount", "currency", "status", "occurredAt"
                ))
                for prior in observations
                if isinstance(prior, dict)
            ):
                observations.append(payment.copy())
        record["updatedAt"] = max(str(record.get("updatedAt") or ""), occurred_at)
        self._reconcile(record)
        await self._store.set(key, record)
        return record

    async def record_adjustment(
        self,
        tenant_id: str,
        *,
        commerce_order_ref: str,
        provider: str,
        adjustment_id: str,
        reverses_payment_id: str,
        amount: str,
        currency: str,
        occurred_at: str,
        adjustment_type: str = "refund",
    ) -> dict[str, Any]:
        """Persist an explicit provider correction/refund as a separate fact.

        Callers must verify provider authority before recording. The relation
        to a payment is created only from the explicit provider payment ID.
        """
        if adjustment_type != "refund":
            raise ValueError("unsupported commerce adjustment type")
        ref = _required(commerce_order_ref, "commerce_order_ref")
        adjustment = {
            "provider": _required(provider, "provider").lower(),
            "adjustmentId": _required(adjustment_id, "adjustment_id"),
            "adjustmentType": adjustment_type,
            "reversesPaymentId": _required(reverses_payment_id, "reverses_payment_id"),
            "amount": _decimal_text(amount),
            "currency": _currency(currency),
            "occurredAt": _required(occurred_at, "occurred_at"),
            "observedAt": utc_now().isoformat(),
        }
        key = _key(tenant_id, ref)
        record = await self._store.get(key) or {
            "tenantId": tenant_id,
            "commerceOrderRef": ref,
            "payments": {},
            "createdAt": occurred_at,
        }
        adjustments = record.setdefault("adjustments", {})
        observations = record.setdefault("adjustmentObservations", [])
        adjustment_key = f"{adjustment['provider']}:{adjustment['adjustmentId']}"
        prior = adjustments.get(adjustment_key)
        if prior is None:
            adjustments[adjustment_key] = adjustment
            observations.append(adjustment.copy())
        elif any(
            prior.get(field) != adjustment.get(field)
            for field in (
                "provider", "adjustmentId", "adjustmentType", "reversesPaymentId",
                "amount", "currency", "occurredAt",
            )
        ):
            record["state"] = "conflict"
            record["conflictReason"] = "provider_adjustment_id_reused_with_divergent_evidence"
            if not any(
                all(row.get(field) == adjustment.get(field) for field in (
                    "provider", "adjustmentId", "adjustmentType", "reversesPaymentId",
                    "amount", "currency", "occurredAt",
                ))
                for row in observations
                if isinstance(row, dict)
            ):
                observations.append(adjustment.copy())
        record["updatedAt"] = max(str(record.get("updatedAt") or ""), occurred_at)
        await self._store.set(key, record)
        return record

    async def get(self, tenant_id: str, commerce_order_ref: str) -> dict[str, Any] | None:
        ref = _required(commerce_order_ref, "commerce_order_ref")
        return await self._store.get(_key(tenant_id, ref))

    async def get_as_of(
        self, tenant_id: str, commerce_order_ref: str, as_of: str
    ) -> dict[str, Any] | None:
        """Reconstruct the ledger knowledge available at ``as_of``.

        Source-valid order revisions are selected only from rows observed by
        the cutoff. Provider payment evidence is likewise bounded by its
        first-observed time. This is a read-only projection; the stored ledger
        and source-owned status are not changed.
        """
        cutoff = parse_instant_strict(as_of)
        current = await self.get(tenant_id, commerce_order_ref)
        if current is None:
            return None

        snapshot = {
            key: value for key, value in current.items()
            if key not in {"order", "payments", "adjustments", "state", "conflictReason", "matchedPaymentIds", "matchedPayments"}
        }
        revisions = current.get("orderRevisions")
        if not isinstance(revisions, list):
            revisions = [current["order"]] if isinstance(current.get("order"), dict) else []
        known_revisions = [
            row for row in revisions
            if isinstance(row, dict)
            and _known_by(row.get("observedAt"), cutoff, current.get("createdAt"))
        ]
        if known_revisions:
            provider_order_ids = {str(row.get("providerOrderId") or "") for row in known_revisions}
            revision_groups: dict[str, list[dict[str, Any]]] = {}
            time_groups: dict[str, list[dict[str, Any]]] = {}
            for row in known_revisions:
                revision_groups.setdefault(str(row.get("revisionId") or ""), []).append(row)
                time_groups.setdefault(
                    str(row.get("sourceRevisionAt") or row.get("occurredAt") or ""), []
                ).append(row)
            if len(provider_order_ids) > 1:
                snapshot["conflictReason"] = "reference_maps_to_multiple_orders"
            elif any(
                len({tuple(row.get(field) for field in (
                    "provider", "providerOrderId", "amount", "currency", "revisionId",
                    "sourceRevisionAt", "occurredAt",
                )) for row in group}) > 1
                for group in revision_groups.values()
            ):
                snapshot["conflictReason"] = "order_revision_id_reused_with_divergent_evidence"
            elif any(
                len({tuple(row.get(field) for field in (
                    "provider", "providerOrderId", "amount", "currency", "revisionId",
                )) for row in group}) > 1
                for group in time_groups.values()
            ):
                snapshot["conflictReason"] = "divergent_order_revisions_with_equal_source_time"
            known_revisions.sort(key=lambda row: (
                _time_key(row.get("sourceRevisionAt") or row.get("occurredAt")),
                _time_key(row.get("observedAt") or current.get("createdAt")),
                str(row.get("revisionId") or ""),
            ))
            snapshot["orderRevisions"] = known_revisions
            snapshot["order"] = known_revisions[-1]

        observations = current.get("paymentObservations")
        if not isinstance(observations, list):
            observations = [
                row for row in (current.get("payments") or {}).values()
                if isinstance(row, dict)
            ]
        known_payments = [
            row for row in observations
            if isinstance(row, dict)
            and _known_by(row.get("observedAt"), cutoff, current.get("createdAt"))
        ]
        payment_map: dict[str, dict[str, Any]] = {}
        payment_groups: dict[str, list[dict[str, Any]]] = {}
        for payment in known_payments:
            key = f"{payment.get('provider')}:{payment.get('providerPaymentId')}"
            payment_map[key] = payment
            payment_groups.setdefault(key, []).append(payment)
        if any(
            len({tuple(row.get(field) for field in (
                "provider", "providerPaymentId", "amount", "currency", "status"
            )) for row in group}) > 1
            for group in payment_groups.values()
        ):
            snapshot["conflictReason"] = "provider_payment_id_reused_with_divergent_evidence"
        snapshot["paymentObservations"] = known_payments
        snapshot["payments"] = payment_map

        adjustment_observations = current.get("adjustmentObservations")
        if not isinstance(adjustment_observations, list):
            adjustment_observations = list((current.get("adjustments") or {}).values())
        known_adjustments = [
            row for row in adjustment_observations
            if isinstance(row, dict)
            and _known_by(row.get("observedAt"), cutoff, current.get("createdAt"))
        ]
        snapshot["adjustmentObservations"] = known_adjustments
        snapshot["adjustments"] = {
            f"{row.get('provider')}:{row.get('adjustmentId')}": row
            for row in known_adjustments
        }

        # A conflict is knowable only if its conflicting observations had both
        # arrived by the cutoff. Reconciliation recomputes the visible state.
        if not snapshot.get("conflictReason"):
            adjustment_groups: dict[tuple[Any, Any], list[dict[str, Any]]] = {}
            for row in known_adjustments:
                adjustment_groups.setdefault(
                    (row.get("provider"), row.get("adjustmentId")), []
                ).append(row)
            if any(
                len({tuple(row.get(field) for field in (
                    "provider", "adjustmentId", "adjustmentType", "reversesPaymentId",
                    "amount", "currency", "occurredAt",
                )) for row in group}) > 1
                for group in adjustment_groups.values()
            ):
                snapshot["conflictReason"] = "provider_adjustment_id_reused_with_divergent_evidence"
        self._reconcile(snapshot)
        return snapshot

    async def list_for_tenant(self, tenant_id: str, *, limit: int = 100) -> list[dict[str, Any]]:
        records = await self._store.find(tenantId=tenant_id)
        records.sort(key=lambda row: row.get("updatedAt", ""), reverse=True)
        return records[: max(1, min(limit, 500))]

    @staticmethod
    def _reconcile(record: dict[str, Any]) -> None:
        if record.get("conflictReason"):
            record["state"] = "conflict"
            return
        order = record.get("order")
        payments = list((record.get("payments") or {}).values())
        if not order:
            record["state"] = "provider_only" if payments else "unmatched"
            return
        eligible = [payment for payment in payments if payment.get("status") == "completed"]
        if not eligible:
            record["state"] = "order_only"
            return
        if any(
            payment.get("currency") != order.get("currency")
            or Decimal(payment["amount"]) != Decimal(order["amount"])
            for payment in eligible
        ):
            record["state"] = "amount_conflict"
            return
        # More than one successful payment is surfaced; the ledger never sums
        # or deduplicates distinct processor payment IDs into order value.
        record["state"] = "matched" if len(eligible) == 1 else "multiple_payments"
        record["matchedPaymentIds"] = [p["providerPaymentId"] for p in eligible]
        record["matchedPayments"] = [
            {
                "provider": payment["provider"],
                "providerPaymentId": payment["providerPaymentId"],
            }
            for payment in eligible
        ]


def _required(value: str, field: str) -> str:
    result = str(value or "").strip()
    if not result or len(result) > 512 or any(
        ord(char) < 32 or ord(char) == 127 for char in result
    ):
        raise ValueError(f"{field} must be a non-empty value of at most 512 characters")
    return result


def _decimal_text(value: str) -> str:
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("amount must be an exact decimal string") from exc
    if not amount.is_finite():
        raise ValueError("amount must be finite")
    return format(amount, "f")


def _currency(value: str) -> str:
    currency = _required(value, "currency").upper()
    if len(currency) != 3 or not currency.isalpha():
        raise ValueError("currency must be a three-letter code")
    return currency


def _time_key(value: Any) -> str:
    parsed = coerce_utc_lenient(value)
    return parsed.isoformat() if parsed is not None else ""


def _known_by(observed_at: Any, cutoff: datetime, legacy_time: Any = None) -> bool:
    value = observed_at or legacy_time
    if value is None:
        return False
    parsed = coerce_utc_lenient(value)
    return parsed is not None and parsed <= cutoff


__all__ = ["CommerceOrderPaymentLedger"]
