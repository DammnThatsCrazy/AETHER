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
    order_revisions = record.get("orderRevisions")
    if not isinstance(order_revisions, list) or not order_revisions:
        order_revisions = [order] if isinstance(order, dict) else []
    for index, order_revision in enumerate(order_revisions):
        if not isinstance(order_revision, dict):
            continue
        order_provider = _required(order_revision.get("provider"), "order.provider")
        order_id = _required(
            order_revision.get("providerOrderId"), "order.providerOrderId"
        )
        revision_id = _required(order_revision.get("revisionId"), "order.revisionId")
        is_current_revision = (
            isinstance(order, dict)
            and order.get("revisionId") == revision_id
            and order.get("providerOrderId") == order_id
        )
        link_ref_id = "order" if is_current_revision else f"order-revision-{index}"
        if is_current_revision:
            order_ref_id = link_ref_id
        refs.append(
            EconomicOperationRecordRef(
                link_ref_id=link_ref_id,
                source_authority=order_provider,
                record_type="commerce_order",
                record_id=order_id,
                role="order",
                evidence=[
                    EvidenceRef(
                        id=revision_id,
                        type="transaction",
                        source=order_provider,
                    )
                ],
                occurred_at=order_revision.get("occurredAt"),
                valid_at=order_revision.get("sourceRevisionAt"),
                observed_at=order_revision.get("observedAt"),
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
    authorization: Any | None = None,
    execution: dict[str, Any] | None = None,
    requirement: Any | None = None,
) -> EconomicOperationLink:
    """Project an agent intent and explicitly linked settlement events.

    ``SettlementEventRepository`` records carry the tenant and ``intent_id``;
    only events matching both are included. Authorization and execution
    references are included only when their authoritative tenant-scoped source
    records are supplied by the caller.
    """
    tenant_id = _required(intent.get("tenant_id"), "intent.tenant_id")
    intent_id = _required(intent.get("intent_id"), "intent.intent_id")
    raw_metadata = intent.get("metadata")
    intent_metadata = raw_metadata if isinstance(raw_metadata, dict) else {}
    authorization_ref = (
        intent.get("authorization_id") or intent_metadata.get("authorization_id")
    )
    execution_ref = intent.get("execution_id") or intent_metadata.get("execution_id")
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
            observed_at=intent.get("created_at"),
        )
    ]
    relations: list[EconomicOperationRelation] = []
    settlement_ref_ids = {
        str(settlement.get("settlement_event_id") or ""): f"settlement-{index}"
        for index, settlement in enumerate(settlement_events)
        if settlement.get("tenant_id") == tenant_id
        and settlement.get("intent_id") == intent_id
        and settlement.get("agent_id") == intent.get("agent_id")
        and settlement.get("settlement_event_id")
    }

    if authorization is not None and requirement is not None:
        auth_data = (
            authorization.model_dump(mode="json")
            if hasattr(authorization, "model_dump")
            else dict(authorization)
        )
        requirement_data = (
            requirement.model_dump(mode="json")
            if hasattr(requirement, "model_dump")
            else dict(requirement)
        )
        auth_id = _required(
            auth_data.get("authorization_id"), "authorization.authorization_id"
        )
        auth_matches = (
            auth_data.get("tenant_id") == tenant_id
            and auth_id == authorization_ref
            and auth_data.get("challenge_id") == intent_id
        )
        requirement_matches = (
            requirement_data.get("tenant_id") == tenant_id
            and requirement_data.get("challenge_id") == intent_id
            and requirement_data.get("requester_type") == "agent"
            and requirement_data.get("requester_id") == intent.get("agent_id")
        )
        if auth_matches and requirement_matches:
            requirement_evidence = EvidenceRef(
                id=intent_id,
                type="transaction",
                source="x402_payment_requirements",
            )
            auth_evidence = EvidenceRef(
                id=auth_id,
                type="transaction",
                source="x402_authorizations",
            )
            refs.append(
                EconomicOperationRecordRef(
                    link_ref_id="authorization",
                    source_authority="x402_commerce_store",
                    record_type="payment_authorization",
                    record_id=auth_id,
                    role="authorization",
                    evidence=[auth_evidence],
                    occurred_at=auth_data.get("authorized_at"),
                )
            )
            relations.append(
                EconomicOperationRelation(
                    from_link_ref_id="intent",
                    relation="authorized_by",
                    to_link_ref_id="authorization",
                    source_authority="x402_commerce_store",
                    evidence=[intent_evidence, requirement_evidence, auth_evidence],
                )
            )

    if execution is not None:
        execution_id = _required(execution.get("execution_id"), "execution.execution_id")
        if (
            execution.get("tenant_id") == tenant_id
            and execution.get("agent_id") == intent.get("agent_id")
            and execution_id == execution_ref
        ):
            execution_evidence = EvidenceRef(
                id=str(execution.get("outcome_event_id") or execution_id),
                type="event",
                source="agent_executions",
            )
            refs.append(
                EconomicOperationRecordRef(
                    link_ref_id="execution",
                    source_authority="agent_execution_repository",
                    record_type="agent_execution",
                    record_id=execution_id,
                    role="execution",
                    evidence=[execution_evidence],
                    occurred_at=execution.get("started_at"),
                    observed_at=execution.get("created_at"),
                )
            )
            relations.append(
                EconomicOperationRelation(
                    from_link_ref_id="intent",
                    relation="executed_as",
                    to_link_ref_id="execution",
                    source_authority="payment_intents",
                    evidence=[intent_evidence, execution_evidence],
                )
            )

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
        raw_settlement_metadata = settlement.get("metadata")
        metadata = raw_settlement_metadata if isinstance(raw_settlement_metadata, dict) else {}
        evidence_source = str(
            metadata.get("source_service")
            or metadata.get("source_kind")
            or "settlement_events"
        )
        settlement_evidence = EvidenceRef(
            id=_required(settlement.get("tx_hash"), "settlement.tx_hash")
            if settlement.get("tx_hash")
            else settlement_id,
            type="transaction",
            source=evidence_source,
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
                observed_at=settlement.get("created_at"),
            )
        )
        reversal_ref = metadata.get("reverses_settlement_event_id")
        reversed_link_ref = settlement_ref_ids.get(str(reversal_ref or ""))
        if reversed_link_ref and str(reversal_ref) != settlement_id:
            relations.append(
                EconomicOperationRelation(
                    from_link_ref_id=link_ref_id,
                    relation="reverses",
                    to_link_ref_id=reversed_link_ref,
                    source_authority="settlement_events",
                    evidence=[
                        settlement_evidence,
                        EvidenceRef(
                            id=str(reversal_ref),
                            type="transaction",
                            source="settlement_events",
                        ),
                    ],
                )
            )
        else:
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
        state="linked" if len(refs) > 1 else "partial",
        records=refs,
        relations=relations,
    )


def _required(value: Any, field: str) -> str:
    result = str(value or "").strip()
    if not result:
        raise ValueError(f"{field} must be a non-empty value")
    return result


__all__ = ["agent_intent_operation_link", "commerce_ledger_operation_link"]
