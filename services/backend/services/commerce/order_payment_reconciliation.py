"""Tenant-scoped, exact-reference order/payment evidence reconciliation.

This ledger links independently observed commerce orders and completed payment
observations only when both carry the same explicit ``commerce_order_ref``.
It never joins on amount, time, email, or customer identity and does not write
graph facts or assert processor payout settlement.
"""

from __future__ import annotations

import hashlib
from decimal import Decimal, InvalidOperation
from typing import Any

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
        }
        key = _key(tenant_id, ref)
        record = await self._store.get(key) or {
            "tenantId": tenant_id,
            "commerceOrderRef": ref,
            "payments": {},
            "createdAt": occurred_at,
        }
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
        payment = {
            "provider": _required(provider, "provider"),
            "providerPaymentId": payment_id,
            "amount": _decimal_text(amount),
            "currency": _currency(currency),
            "status": _required(status, "status"),
            "occurredAt": occurred_at,
        }
        key = _key(tenant_id, ref)
        record = await self._store.get(key) or {
            "tenantId": tenant_id,
            "commerceOrderRef": ref,
            "payments": {},
            "createdAt": occurred_at,
        }
        record.setdefault("payments", {})[payment_id] = payment
        record["updatedAt"] = occurred_at
        self._reconcile(record)
        await self._store.set(key, record)
        return record

    async def get(self, tenant_id: str, commerce_order_ref: str) -> dict[str, Any] | None:
        ref = _required(commerce_order_ref, "commerce_order_ref")
        return await self._store.get(_key(tenant_id, ref))

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


__all__ = ["CommerceOrderPaymentLedger"]
