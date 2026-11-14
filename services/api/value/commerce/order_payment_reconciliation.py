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
from shared.store import DurableStore, get_store, update_atomically


def _key(tenant_id: str, ref: str) -> str:
    digest = hashlib.sha256(ref.encode("utf-8")).hexdigest()
    return f"{tenant_id}:{digest}"


_PAYMENT_SOURCE_DETAIL_FIELDS = (
    "paymentRail",
    "flowType",
    "sourceAmount",
    "sourceAsset",
    "sourceChain",
    "destinationAmount",
    "destinationAsset",
    "destinationChain",
    "txHash",
)


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
        def _apply(existing: dict | None) -> dict[str, Any]:
            record = existing or {
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
                # Compare instants, not strings: equivalent ISO-8601 values with
                # different offsets do not sort chronologically as text.
                prior_revision_at = _time_key(prior.get("sourceRevisionAt"))
                next_revision_at = _time_key(order.get("sourceRevisionAt"))
                if next_revision_at > prior_revision_at:
                    record["order"] = order
                elif next_revision_at == prior_revision_at:
                    record["state"] = "conflict"
                    record["conflictReason"] = "divergent_order_revisions_with_equal_source_time"
            record["updatedAt"] = max(str(record.get("updatedAt") or ""), occurred_at)
            self._reconcile(record)
            return record

        return await update_atomically(self._store, key, _apply)

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
        payment_rail: str | None = None,
        flow_type: str | None = None,
        source_amount: str | None = None,
        source_asset: str | None = None,
        source_chain: str | None = None,
        destination_amount: str | None = None,
        destination_asset: str | None = None,
        destination_chain: str | None = None,
        tx_hash: str | None = None,
    ) -> dict[str, Any]:
        """Record a provider payment only when its payload explicitly supplies
        the commerce reference. Callers must enforce their provider signature
        and payment status before invoking this method.
        """
        ref = _required(commerce_order_ref, "commerce_order_ref")
        payment_id = _required(provider_payment_id, "provider_payment_id")
        payment_provider = _required(provider, "provider").lower()
        payment: dict[str, Any] = {
            "provider": payment_provider,
            "providerPaymentId": payment_id,
            "amount": _decimal_text(amount),
            "currency": _currency(currency),
            "status": _required(status, "status"),
            "occurredAt": occurred_at,
            "observedAt": utc_now().isoformat(),
        }
        from connectors.integrations.providers.payment_rails.models import (
            FUNDING_FLOW_TYPES,
            PAYMENT_RAIL_VALUES,
        )

        if payment_rail is not None:
            rail = _required(payment_rail, "payment_rail")
            if rail not in PAYMENT_RAIL_VALUES:
                raise ValueError("payment_rail must use the canonical payment-rail vocabulary")
            payment["paymentRail"] = rail
        if flow_type is not None:
            flow = _required(flow_type, "flow_type")
            if flow not in FUNDING_FLOW_TYPES:
                raise ValueError("flow_type must use the canonical funding-flow vocabulary")
            payment["flowType"] = flow

        for field_name, value in (
            ("sourceAmount", source_amount),
            ("destinationAmount", destination_amount),
        ):
            if value is not None:
                payment[field_name] = _decimal_text(value)
        for field_name, value in (
            ("sourceAsset", source_asset),
            ("sourceChain", source_chain),
            ("destinationAsset", destination_asset),
            ("destinationChain", destination_chain),
            ("txHash", tx_hash),
        ):
            if value is not None:
                payment[field_name] = _required(value, field_name)

        key = _key(tenant_id, ref)
        def _apply(existing: dict | None) -> dict[str, Any]:
            record = existing or {
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
            ) or any(
                prior_payment.get(field) is not None
                and payment.get(field) is not None
                and prior_payment.get(field) != payment.get(field)
                for field in _PAYMENT_SOURCE_DETAIL_FIELDS
            ):
                record["state"] = "conflict"
                record["conflictReason"] = "provider_payment_id_reused_with_divergent_evidence"
                if not any(
                    all(prior.get(field) == payment.get(field) for field in (
                        "provider", "providerPaymentId", "amount", "currency", "status", "occurredAt"
                    ))
                    and all(
                        prior.get(field) == payment.get(field)
                        for field in _PAYMENT_SOURCE_DETAIL_FIELDS
                        if payment.get(field) is not None
                    )
                    for prior in observations
                    if isinstance(prior, dict)
                ):
                    observations.append(payment.copy())
            else:
                # Later exact provider evidence may add source-native payment
                # details. Preserve the earlier observation and expose enrichment
                # only from its own observation time onward.
                merged_payment = dict(prior_payment)
                enriched = False
                for field in _PAYMENT_SOURCE_DETAIL_FIELDS:
                    if merged_payment.get(field) is None and payment.get(field) is not None:
                        merged_payment[field] = payment[field]
                        enriched = True
                if enriched:
                    merged_payment["observedAt"] = payment["observedAt"]
                    payments[payment_key] = merged_payment
                    observations.append(merged_payment.copy())
            record["updatedAt"] = max(str(record.get("updatedAt") or ""), occurred_at)
            self._reconcile(record)
            return record

        return await update_atomically(self._store, key, _apply)

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
        def _apply(existing: dict | None) -> dict[str, Any]:
            record = existing or {
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
            return record

        return await update_atomically(self._store, key, _apply)

    async def record_settlement(
        self,
        tenant_id: str,
        *,
        commerce_order_ref: str,
        provider: str,
        settlement_id: str,
        amount: str,
        currency: str,
        settled_payment_refs: list[dict[str, str]],
        occurred_at: str,
    ) -> dict[str, Any]:
        """Persist a source-authoritative settled outcome.

        Callers must verify the provider event before invoking this method.
        The settlement is linked only to explicitly supplied provider/payment
        IDs; it does not infer constituent payments from an amount or order.
        """
        ref = _required(commerce_order_ref, "commerce_order_ref")
        settlement_provider = _required(provider, "provider").lower()
        if not isinstance(settled_payment_refs, list) or len(settled_payment_refs) > 1000:
            raise ValueError("settled_payment_refs must be a list of at most 1000 references")
        normalized_refs: list[dict[str, str]] = []
        seen_refs: set[tuple[str, str]] = set()
        for item in settled_payment_refs:
            if not isinstance(item, dict):
                raise ValueError("each settled payment reference must be an object")
            payment_provider = _required(item.get("provider"), "payment_ref.provider").lower()
            payment_id = _required(
                item.get("provider_payment_id"), "payment_ref.provider_payment_id"
            )
            pair = (payment_provider, payment_id)
            if pair not in seen_refs:
                seen_refs.add(pair)
                normalized_refs.append({
                    "provider": payment_provider,
                    "providerPaymentId": payment_id,
                })
        normalized_refs.sort(key=lambda item: (item["provider"], item["providerPaymentId"]))
        settlement = {
            "provider": settlement_provider,
            "providerSettlementId": _required(settlement_id, "settlement_id"),
            "status": "settled",
            "amount": _decimal_text(amount),
            "currency": _currency(currency),
            "settlesPaymentRefs": normalized_refs,
            "occurredAt": _required(occurred_at, "occurred_at"),
            "observedAt": utc_now().isoformat(),
        }
        if Decimal(settlement["amount"]) < 0:
            raise ValueError("settlement amount must not be negative")

        key = _key(tenant_id, ref)
        def _apply(existing: dict | None) -> dict[str, Any]:
            record = existing or {
                "tenantId": tenant_id,
                "commerceOrderRef": ref,
                "payments": {},
                "createdAt": occurred_at,
            }
            settlements = record.get("settlements")
            if not isinstance(settlements, dict):
                settlements = record["settlements"] = {}
            observations = record.get("settlementObservations")
            if not isinstance(observations, list):
                observations = record["settlementObservations"] = []
            if not observations:
                observations.extend(
                    row.copy() for row in settlements.values() if isinstance(row, dict)
                )
            settlement_key = f"{settlement_provider}:{settlement['providerSettlementId']}"
            prior = settlements.get(settlement_key)
            compared_fields = (
                "provider", "providerSettlementId", "status", "amount", "currency",
                "settlesPaymentRefs", "occurredAt",
            )
            if prior is None:
                settlements[settlement_key] = settlement
                observations.append(settlement.copy())
            elif any(prior.get(field) != settlement.get(field) for field in compared_fields):
                record["state"] = "conflict"
                record["conflictReason"] = "provider_settlement_id_reused_with_divergent_evidence"
                if not any(
                    all(row.get(field) == settlement.get(field) for field in compared_fields)
                    for row in observations
                    if isinstance(row, dict)
                ):
                    observations.append(settlement.copy())
            record["updatedAt"] = max(str(record.get("updatedAt") or ""), occurred_at)
            self._reconcile(record)
            return record

        return await update_atomically(self._store, key, _apply)

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
            if key not in {
                "order", "payments", "adjustments", "settlements", "state",
                "conflictReason", "matchedPaymentIds", "matchedPayments",
            }
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
        if any(
            len({row.get(field) for row in group if row.get(field) is not None}) > 1
            for group in payment_groups.values()
            for field in _PAYMENT_SOURCE_DETAIL_FIELDS
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

        settlement_observations = current.get("settlementObservations")
        if not isinstance(settlement_observations, list):
            settlement_observations = list((current.get("settlements") or {}).values())
        known_settlements = [
            row for row in settlement_observations
            if isinstance(row, dict)
            and _known_by(row.get("observedAt"), cutoff, current.get("createdAt"))
        ]
        snapshot["settlementObservations"] = known_settlements
        snapshot["settlements"] = {
            f"{row.get('provider')}:{row.get('providerSettlementId')}": row
            for row in known_settlements
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
        if not snapshot.get("conflictReason"):
            settlement_groups: dict[tuple[Any, Any], list[dict[str, Any]]] = {}
            for row in known_settlements:
                settlement_groups.setdefault(
                    (row.get("provider"), row.get("providerSettlementId")), []
                ).append(row)
            if any(
                len({_settlement_fingerprint(row) for row in group}) > 1
                for group in settlement_groups.values()
            ):
                snapshot["conflictReason"] = "provider_settlement_id_reused_with_divergent_evidence"
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


def _time_key(value: Any) -> float:
    """Epoch seconds, so offsets compare as instants (unparseable sorts first)."""
    parsed = coerce_utc_lenient(value)
    return parsed.timestamp() if parsed is not None else float("-inf")


def _settlement_fingerprint(row: dict[str, Any]) -> tuple[Any, ...]:
    refs = row.get("settlesPaymentRefs") or []
    normalized_refs = tuple(
        sorted(
            (
                str(payment_ref.get("provider") or ""),
                str(payment_ref.get("providerPaymentId") or ""),
            )
            for payment_ref in refs
            if isinstance(payment_ref, dict)
        )
    )
    return (
        row.get("provider"), row.get("providerSettlementId"), row.get("status"),
        row.get("amount"), row.get("currency"), normalized_refs, row.get("occurredAt"),
    )


def _known_by(observed_at: Any, cutoff: datetime, legacy_time: Any = None) -> bool:
    value = observed_at or legacy_time
    if value is None:
        return False
    parsed = coerce_utc_lenient(value)
    return parsed is not None and parsed <= cutoff


__all__ = ["CommerceOrderPaymentLedger"]
