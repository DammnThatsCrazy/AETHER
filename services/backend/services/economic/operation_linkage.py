"""Provider-neutral economic operation link projections.

These functions connect source-owned records for navigation. They never copy
amounts or replace the lifecycle status owned by the source service.
"""

from __future__ import annotations

import hashlib
from typing import Any

from services.economic.economic360_contracts import (
    EconomicOperationLink,
    EconomicOperationRecordRef,
    EconomicOperationRelation,
    EconomicWarning,
    EconomicWarningCode,
)
from services.operational_intelligence.models import EvidenceRef


def commerce_ledger_operation_link(record: dict[str, Any]) -> EconomicOperationLink:
    """Project exact-reference commerce evidence into an operation link.

    The ledger has already enforced tenant scope and exact ``commerceOrderRef``
    equality. Multiple completed payments and divergent order/payment evidence
    remain conflicts; this mapper does not resolve or sum them.
    """
    tenant_id = _required(record.get("tenantId"), "tenantId")
    operation_ref = _required(record.get("commerceOrderRef"), "commerceOrderRef")
    order = record.get("order")
    payments = record.get("payments") or {}
    ledger_evidence = EvidenceRef(
        id=operation_ref,
        type="transaction",
        source="commerce_order_payment_ledger",
    )

    refs: list[EconomicOperationRecordRef] = []
    order_ref_id: str | None = None
    if isinstance(order, dict):
        order_provider = _required(order.get("provider"), "order.provider")
        order_id = _required(order.get("providerOrderId"), "order.providerOrderId")
        order_ref_id = "order"
        refs.append(
            EconomicOperationRecordRef(
                link_ref_id=order_ref_id,
                source_authority=order_provider,
                record_type="commerce_order",
                record_id=order_id,
                role="order",
                evidence=[
                    EvidenceRef(
                        id=_required(order.get("revisionId"), "order.revisionId"),
                        type="transaction",
                        source=order_provider,
                    )
                ],
                occurred_at=order.get("occurredAt"),
                valid_at=order.get("sourceRevisionAt"),
            )
        )

    payment_refs: list[tuple[str, dict[str, Any]]] = []
    if not isinstance(payments, dict):
        raise ValueError("payments must be a provider-keyed object")
    for index, payment in enumerate(payments.values()):
        if not isinstance(payment, dict):
            raise ValueError("each payment observation must be an object")
        provider = _required(payment.get("provider"), "payment.provider")
        payment_id = _required(payment.get("providerPaymentId"), "payment.providerPaymentId")
        link_ref_id = f"payment-{index}"
        payment_refs.append((link_ref_id, payment))
        refs.append(
            EconomicOperationRecordRef(
                link_ref_id=link_ref_id,
                source_authority=provider,
                record_type="provider_payment",
                record_id=payment_id,
                role="payment",
                evidence=[
                    EvidenceRef(
                        id=payment_id,
                        type="transaction",
                        source=provider,
                    )
                ],
                occurred_at=payment.get("occurredAt"),
            )
        )

    source_state = str(record.get("state") or "unmatched")
    state = {
        "matched": "linked",
        "order_only": "partial",
        "provider_only": "partial",
        "unmatched": "unresolved",
        "conflict": "conflict",
        "amount_conflict": "conflict",
        "multiple_payments": "conflict",
    }.get(source_state, "unresolved")

    relations: list[EconomicOperationRelation] = []
    if state == "linked" and order_ref_id is not None:
        for payment_ref_id, payment in payment_refs:
            if payment.get("status") == "completed":
                relations.append(
                    EconomicOperationRelation(
                        from_link_ref_id=payment_ref_id,
                        relation="fulfills",
                        to_link_ref_id=order_ref_id,
                        source_authority="commerce_order_payment_ledger",
                        evidence=[ledger_evidence],
                    )
                )

    warnings: list[EconomicWarning] = []
    if source_state == "multiple_payments":
        warnings.append(
            EconomicWarning(
                code=EconomicWarningCode.POSSIBLE_DOUBLE_COUNT,
                message=(
                    "multiple completed provider payments reference one order; "
                    "the observations are retained separately and not summed"
                ),
                severity="warning",
            )
        )

    link_digest = hashlib.sha256(
        f"{len(tenant_id)}:{tenant_id}{len(operation_ref)}:{operation_ref}".encode("utf-8")
    ).hexdigest()
    return EconomicOperationLink(
        id=f"commerce:{link_digest}",
        tenant_id=tenant_id,
        operation_ref=operation_ref,
        identity_basis="source_shared_identifier",
        identity_evidence=[ledger_evidence],
        state=state,
        records=refs,
        relations=relations,
        warnings=warnings,
    )


def agent_intent_operation_link(
    intent: dict[str, Any],
    settlement_events: list[dict[str, Any]],
) -> EconomicOperationLink:
    """Project an agent intent and explicitly linked settlement events.

    ``SettlementEventRepository`` records carry the tenant and ``intent_id``;
    only events matching both are included. Intent authorization/execution IDs
    are intentionally omitted until their authoritative evidence records are
    available to this projection.
    """
    tenant_id = _required(intent.get("tenant_id"), "intent.tenant_id")
    intent_id = _required(intent.get("intent_id"), "intent.intent_id")
    intent_evidence = EvidenceRef(
        id=intent_id,
        type="transaction",
        source="payment_intents",
    )
    refs = [
        EconomicOperationRecordRef(
            link_ref_id="intent",
            source_authority="agent_payment_intent",
            record_type="payment_intent",
            record_id=intent_id,
            role="payment_intent",
            evidence=[intent_evidence],
            occurred_at=intent.get("occurred_at"),
        )
    ]
    relations: list[EconomicOperationRelation] = []
    for index, settlement in enumerate(settlement_events):
        if (
            settlement.get("tenant_id") != tenant_id
            or settlement.get("intent_id") != intent_id
            or settlement.get("agent_id") != intent.get("agent_id")
        ):
            continue
        settlement_id = _required(
            settlement.get("settlement_event_id"), "settlement.settlement_event_id"
        )
        link_ref_id = f"settlement-{index}"
        provider = str(settlement.get("provider") or "settlement_events")
        settlement_evidence = EvidenceRef(
            id=_required(settlement.get("tx_hash"), "settlement.tx_hash")
            if settlement.get("tx_hash")
            else settlement_id,
            type="transaction",
            source=provider,
        )
        refs.append(
            EconomicOperationRecordRef(
                link_ref_id=link_ref_id,
                source_authority=provider,
                record_type="settlement_event",
                record_id=settlement_id,
                role="settlement",
                evidence=[settlement_evidence],
                occurred_at=settlement.get("occurred_at"),
            )
        )
        relations.append(
            EconomicOperationRelation(
                from_link_ref_id="intent",
                relation="has_settlement_event",
                to_link_ref_id=link_ref_id,
                source_authority="settlement_events",
                evidence=[intent_evidence, settlement_evidence],
            )
        )

    digest = hashlib.sha256(
        f"{len(tenant_id)}:{tenant_id}{len(intent_id)}:{intent_id}".encode("utf-8")
    ).hexdigest()
    return EconomicOperationLink(
        id=f"agent:{digest}",
        tenant_id=tenant_id,
        operation_ref=intent_id,
        identity_basis="source_shared_identifier",
        identity_evidence=[intent_evidence],
        state="linked" if relations else "partial",
        records=refs,
        relations=relations,
    )


def _required(value: Any, field: str) -> str:
    result = str(value or "").strip()
    if not result:
        raise ValueError(f"{field} must be a non-empty value")
    return result


__all__ = ["agent_intent_operation_link", "commerce_ledger_operation_link"]
