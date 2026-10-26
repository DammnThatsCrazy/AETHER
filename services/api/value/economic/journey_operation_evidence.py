"""Exact-reference commerce evidence attached to canonical subject scopes."""

from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import datetime
from typing import Any, Optional

from graph.operational_intelligence.models import EvidenceRef

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


async def journey_commerce_operation_evidence(
    tenant_id: str,
    journey_id: str,
    *,
    as_of: Optional[str] = None,
    max_steps: int = 10_000,
    max_order_refs: int = 500,
) -> dict[str, Any]:
    """Read operation links and payment facts from explicit journey-step refs.

    No joins are made on identity, amount, timestamp, order ID, or payment ID.
    Monetary facts remain separate by order, payment, adjustment, and
    settlement; this function never aggregates them into a journey total.
    """
    max_steps = min(max(int(max_steps), 1), 10_000)
    max_order_refs = min(max(int(max_order_refs), 1), 1_000)
    from journeys.measurement.repositories.journey_repo import JourneyRepository
    from journeys.measurement.repositories.journey_step_repo import JourneyStepRepository
    from value.commerce.order_payment_reconciliation import CommerceOrderPaymentLedger
    from value.economic.operation_linkage import commerce_ledger_operation_link

    journey = await JourneyRepository().get_current(tenant_id, journey_id)
    if journey is None:
        return {
            "journey_id": journey_id,
            "join_basis": "explicit_journey_step_commerce_order_ref",
            "operation_links": [],
            "payment_facts": [],
            "reason": "journey_not_found",
            "amounts_included": True,
            "operation_link_amounts_included": False,
            "facts_are_aggregated": False,
            "order_reference_count": 0,
            "invalid_order_reference_count": 0,
            "ledger_read_errors": 0,
            "invalid_ledger_records": 0,
            "as_of": as_of,
        }
    if (
        str(journey.get("tenant_id")) != tenant_id
        or str(journey.get("journey_id")) != journey_id
        or not journey.get("is_current")
        or not journey.get("journey_version_id")
    ):
        return {
            "journey_id": journey_id,
            "join_basis": "explicit_journey_step_commerce_order_ref",
            "operation_links": [],
            "payment_facts": [],
            "association_evidence": [],
            "reason": "journey_current_version_scope_invalid",
            "evidence_truncated": True,
            "as_of": as_of,
        }

    repo = JourneyStepRepository()
    version_id = str(journey.get("journey_version_id"))
    refs: list[str] = []
    seen_refs: set[str] = set()
    association_evidence: list[dict[str, Any]] = []
    scanned = 0
    cursor: Optional[str] = None
    truncated = False
    invalid_reference_count = 0
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
            if not isinstance(step, dict):
                invalid_reference_count += 1
                continue
            step_id = str(step.get("step_id") or "").strip()
            activity_id = str(step.get("activity_id") or "").strip()
            if (
                str(step.get("tenant_id")) != tenant_id
                or str(step.get("journey_id")) != journey_id
                or str(step.get("journey_version_id")) != version_id
                or not step_id
                or not activity_id
                or step.get("activity_status") in {"tombstoned", "deleted", "consent_restricted"}
            ):
                invalid_reference_count += 1
                continue
            summary = step.get("evidence_summary")
            if isinstance(summary, str):
                try:
                    summary = json.loads(summary)
                except (TypeError, ValueError):
                    summary = None
            if not isinstance(summary, dict):
                continue
            created_at = step.get("created_at")
            if isinstance(created_at, datetime):
                created_at = created_at.isoformat()
            step_evidence = EvidenceRef(
                id=step_id,
                type="event",
                source="journey_steps",
                observedAt=created_at if isinstance(created_at, str) else None,
            ).model_dump(mode="json")

            def admit_reference(value: Any) -> None:
                nonlocal truncated, invalid_reference_count
                reference = _valid_order_reference(value)
                if reference is None:
                    if value is not None:
                        invalid_reference_count += 1
                    return
                if reference in seen_refs:
                    return
                seen_refs.add(reference)
                if len(refs) >= max_order_refs:
                    truncated = True
                    return
                refs.append(reference)
                association_evidence.append(
                    {
                        "commerceOrderRef": reference,
                        "subjectKind": "journey",
                        "subjectId": journey_id,
                        "journeyVersionId": version_id,
                        "stepId": step_id,
                        "activityId": activity_id,
                        "evidence": step_evidence,
                    }
                )

            values = summary.get("commerce_order_refs", [])
            if isinstance(values, str):
                values = [values]
            if isinstance(values, list):
                for value in values:
                    admit_reference(value)
            admit_reference(summary.get("commerce_order_ref"))
        if len(page) < min(500, max_steps - (scanned - len(page))):
            break
        cursor = str(page[-1].get("step_position", ""))
        if scanned >= max_steps:
            remaining = await repo.list_by_version(tenant_id, version_id, limit=1, cursor=cursor)
            truncated = bool(remaining)

    truncated = truncated or bool(invalid_reference_count)

    ledger = CommerceOrderPaymentLedger()

    async def read_reference(
        reference: str,
    ) -> tuple[str, Optional[dict[str, Any]], bool]:
        try:
            record = (
                await ledger.get_as_of(tenant_id, reference, as_of)
                if as_of
                else await ledger.get(tenant_id, reference)
            )
        except Exception:  # noqa: BLE001 - one unavailable reference stays partial
            return reference, None, True
        return reference, record, False

    semaphore = asyncio.Semaphore(16)

    async def bounded_read(
        reference: str,
    ) -> tuple[str, Optional[dict[str, Any]], bool]:
        async with semaphore:
            return await read_reference(reference)

    resolved = await asyncio.gather(*(bounded_read(reference) for reference in refs))
    links: list[dict[str, Any]] = []
    payment_facts: list[dict[str, Any]] = []
    ledger_read_errors = 0
    invalid_ledger_records = 0
    unresolved_order_references = 0
    for reference, record, failed in resolved:
        if failed:
            ledger_read_errors += 1
            continue
        if record is None:
            unresolved_order_references += 1
            continue
        if (
            not isinstance(record, dict)
            or record.get("tenantId") != tenant_id
            or record.get("commerceOrderRef") != reference
        ):
            invalid_ledger_records += 1
            continue
        try:
            link = commerce_ledger_operation_link(record).model_dump(mode="json")
            facts = _commerce_payment_facts(record, as_of=as_of)
        except Exception:  # noqa: BLE001 - malformed stored evidence stays partial
            invalid_ledger_records += 1
            continue
        links.append(link)
        payment_facts.extend(facts)
    truncated = truncated or bool(
        ledger_read_errors or invalid_ledger_records or unresolved_order_references
    )

    return {
        "journey_id": journey_id,
        "join_basis": "explicit_journey_step_commerce_order_ref",
        "operation_links": links,
        "payment_facts": payment_facts,
        "association_evidence": association_evidence,
        "amounts_included": True,
        "operation_link_amounts_included": False,
        "facts_are_aggregated": False,
        "unlinked_evidence": "not_inferred",
        "order_reference_count": len(refs),
        "unresolved_order_references": unresolved_order_references,
        "invalid_order_reference_count": invalid_reference_count,
        "ledger_read_errors": ledger_read_errors,
        "invalid_ledger_records": invalid_ledger_records,
        "steps_scanned": scanned,
        "evidence_truncated": truncated,
        "as_of": as_of,
    }


async def campaign_commerce_operation_evidence(
    tenant_id: str,
    campaign_id: str,
    *,
    as_of: Optional[str] = None,
    max_activities: int = 1_000,
    max_order_refs: int = 500,
) -> dict[str, Any]:
    """Read payment evidence linked by an exact canonical campaign activity ref."""
    return await _canonical_activity_commerce_operation_evidence(
        tenant_id,
        subject_kind="campaign",
        subject_id=campaign_id,
        as_of=as_of,
        max_activities=max_activities,
        max_order_refs=max_order_refs,
    )


async def entity_commerce_operation_evidence(
    tenant_id: str,
    entity_id: str,
    *,
    as_of: Optional[str] = None,
    max_activities: int = 1_000,
    max_order_refs: int = 500,
) -> dict[str, Any]:
    """Read payment evidence linked by an exact canonical profile activity ref."""
    return await _canonical_activity_commerce_operation_evidence(
        tenant_id,
        subject_kind="entity",
        subject_id=entity_id,
        as_of=as_of,
        max_activities=max_activities,
        max_order_refs=max_order_refs,
    )


async def _canonical_activity_commerce_operation_evidence(
    tenant_id: str,
    *,
    subject_kind: str,
    subject_id: str,
    as_of: Optional[str],
    max_activities: int,
    max_order_refs: int,
) -> dict[str, Any]:
    """Read exact refs for a caller-validated canonical Campaign or Profile.

    Campaign callers validate against CampaignRegistry; entity callers
    validate against IdentityRepository before entering this function. Each
    activity row must carry both the exact canonical subject key and an
    explicit commerce order reference. Ledger reads then use only that exact
    reference under the same tenant. No attribution or identity is inferred
    from amounts, timestamps, or provider order/payment IDs.
    """
    max_activities = min(max(int(max_activities), 1), 1_000)
    max_order_refs = min(max(int(max_order_refs), 1), 1_000)
    dimensions = {
        "campaign": (
            "campaign_id",
            "list_commerce_by_campaign",
            "explicit_campaign_scoped_canonical_activity_commerce_order_ref",
        ),
        "entity": (
            "profile_id",
            "list_commerce_by_profile",
            "explicit_canonical_profile_scoped_activity_commerce_order_ref",
        ),
    }
    dimension = dimensions.get(subject_kind)
    if dimension is None:
        raise ValueError("commerce evidence supports only canonical campaign or entity subjects")
    scope_field, reader_method, join_basis = dimension
    subject_key = f"{subject_kind}_id"

    try:
        from journeys.measurement.repositories.activity_repo import ActivityRepository

        rows = await getattr(ActivityRepository(), reader_method)(
            tenant_id,
            subject_id,
            limit=max_activities + 1,
            as_of=as_of,
        )
    except Exception:  # noqa: BLE001 - a source outage remains an explicit partial state
        return {
            subject_key: subject_id,
            "join_basis": join_basis,
            "operation_links": [],
            "payment_facts": [],
            "association_evidence": [],
            "amounts_included": True,
            "operation_link_amounts_included": False,
            "facts_are_aggregated": False,
            "reason": "canonical_subject_activity_repository_unavailable",
            "activity_scan_count": 0,
            "order_reference_count": 0,
            "unresolved_order_references": 0,
            "invalid_order_reference_count": 0,
            "ledger_read_errors": 0,
            "invalid_ledger_records": 0,
            "evidence_truncated": True,
            "as_of": as_of,
        }

    truncated = len(rows) > max_activities
    scanned_rows = rows[:max_activities]
    refs: list[str] = []
    seen_refs: set[str] = set()
    invalid_reference_count = 0
    association_evidence: list[dict[str, Any]] = []
    from graph.operational_intelligence.models import EvidenceRef

    for row in scanned_rows:
        if (
            str(row.get("tenant_id", "")) != tenant_id
            or str(row.get(scope_field, "")) != subject_id
            or row.get("activity_family") != "commerce"
            or row.get("activity_status") in {"tombstoned", "deleted", "consent_restricted"}
        ):
            continue
        reference = _valid_order_reference(row.get("commerce_order_ref"))
        if reference is None:
            if row.get("commerce_order_ref") is not None:
                invalid_reference_count += 1
            continue
        activity_id = str(row.get("activity_id") or "").strip()
        if not activity_id:
            invalid_reference_count += 1
            continue
        if reference not in seen_refs:
            seen_refs.add(reference)
            if len(refs) < max_order_refs:
                refs.append(reference)
            else:
                truncated = True
        association_evidence.append(
            {
                "commerceOrderRef": reference,
                "subjectKind": subject_kind,
                "subjectId": subject_id,
                "activityId": activity_id,
                "silverTable": row.get("silver_table"),
                "evidence": EvidenceRef(
                    id=activity_id,
                    type="event",
                    source=str(
                        row.get("silver_table") or row.get("source_system") or "canonical_activity"
                    ),
                    observedAt=row.get("server_received_at"),
                ).model_dump(mode="json"),
            }
        )

    truncated = truncated or bool(invalid_reference_count)

    from value.commerce.order_payment_reconciliation import CommerceOrderPaymentLedger
    from value.economic.operation_linkage import commerce_ledger_operation_link

    ledger = CommerceOrderPaymentLedger()

    async def read_reference(reference: str) -> tuple[str, Optional[dict[str, Any]], bool]:
        try:
            record = (
                await ledger.get_as_of(tenant_id, reference, as_of)
                if as_of
                else await ledger.get(tenant_id, reference)
            )
        except Exception:  # noqa: BLE001 - one unavailable order remains partial
            return reference, None, True
        return reference, record, False

    semaphore = asyncio.Semaphore(16)

    async def bounded_read(reference: str) -> tuple[str, Optional[dict[str, Any]], bool]:
        async with semaphore:
            return await read_reference(reference)

    resolved = await asyncio.gather(*(bounded_read(reference) for reference in refs))
    links: list[dict[str, Any]] = []
    payment_facts: list[dict[str, Any]] = []
    ledger_read_errors = 0
    invalid_ledger_records = 0
    unresolved_order_references = 0
    for reference, record, read_error in resolved:
        if read_error:
            ledger_read_errors += 1
            continue
        if record is None:
            unresolved_order_references += 1
            continue
        if (
            str(record.get("tenantId", "")) != tenant_id
            or str(record.get("commerceOrderRef", "")) != reference
        ):
            invalid_ledger_records += 1
            continue
        try:
            links.append(commerce_ledger_operation_link(record).model_dump(mode="json"))
            payment_facts.extend(
                _commerce_payment_facts(record, as_of=as_of, join_basis=join_basis)
            )
        except Exception:  # noqa: BLE001 - malformed source evidence remains partial
            invalid_ledger_records += 1

    truncated = truncated or bool(
        ledger_read_errors or invalid_ledger_records or unresolved_order_references
    )
    return {
        subject_key: subject_id,
        "join_basis": join_basis,
        "operation_links": links,
        "payment_facts": payment_facts,
        "association_evidence": association_evidence,
        "amounts_included": True,
        "operation_link_amounts_included": False,
        "facts_are_aggregated": False,
        "unlinked_evidence": "not_inferred",
        "activity_scan_count": len(scanned_rows),
        "order_reference_count": len(refs),
        "unresolved_order_references": unresolved_order_references,
        "invalid_order_reference_count": invalid_reference_count,
        "ledger_read_errors": ledger_read_errors,
        "invalid_ledger_records": invalid_ledger_records,
        "evidence_truncated": truncated,
        "as_of": as_of,
    }


def _valid_order_reference(value: Any) -> Optional[str]:
    if not isinstance(value, str):
        return None
    reference = value.strip()
    if (
        not reference
        or len(reference) > 512
        or any(ord(char) < 32 or ord(char) == 127 for char in reference)
    ):
        return None
    return reference


def _commerce_payment_facts(
    record: dict[str, Any],
    *,
    as_of: Optional[str],
    join_basis: str = "explicit_journey_step_commerce_order_ref",
) -> list[dict[str, Any]]:
    """Project source-owned ledger amounts as separate, typed-evidence facts."""
    from graph.operational_intelligence.models import EvidenceRef

    state = str(record.get("state") or "unmatched")
    conflict_reason = record.get("conflictReason")
    operation_ref = str(record.get("commerceOrderRef") or "")
    facts: list[dict[str, Any]] = []

    def add_fact(
        *,
        fact_kind: str,
        source_record: dict[str, Any],
        record_id_field: str,
        evidence_id_field: Optional[str] = None,
        lifecycle_state: str,
    ) -> None:
        amount = source_record.get("amount")
        currency = source_record.get("currency")
        record_id = source_record.get(record_id_field)
        evidence_id = source_record.get(evidence_id_field or record_id_field)
        provider = source_record.get("provider")
        if not isinstance(amount, str) or not isinstance(currency, str):
            return
        if (
            not isinstance(record_id, str)
            or not record_id
            or not isinstance(provider, str)
            or not provider.strip()
        ):
            return
        if not isinstance(evidence_id, str) or not evidence_id:
            # Older order snapshots may predate revision IDs. The canonical
            # provider order ID is still a real source reference in that case.
            evidence_id = record_id
        evidence = EvidenceRef(
            id=evidence_id,
            type="transaction",
            source=provider,
            observedAt=source_record.get("_recordObservedAt")
            or source_record.get("observedAt"),
        )
        evidence_refs = [evidence.model_dump(mode="json")]
        tx_hash = source_record.get("txHash")
        if (
            fact_kind == "payment"
            and isinstance(tx_hash, str)
            and tx_hash.strip()
            and len(tx_hash.strip()) <= 512
            and all(ord(char) >= 32 and ord(char) != 127 for char in tx_hash.strip())
        ):
            evidence_refs.append(
                EvidenceRef(
                    id=tx_hash.strip(),
                    type="transaction",
                    source=provider,
                    observedAt=source_record.get("observedAt"),
                ).model_dump(mode="json")
            )
        reference_digest = hashlib.sha256(operation_ref.encode("utf-8")).hexdigest()[:16]
        fact_digest = hashlib.sha256(
            json.dumps(source_record, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()[:12]
        facts.append(
            {
                "factId": (
                    f"commerce:{reference_digest}:{fact_kind}:{provider}:"
                    f"{evidence_id}:{fact_digest}"
                ),
                "kind": fact_kind,
                "commerceOrderRef": operation_ref,
                "joinBasis": join_basis,
                "amount": amount,
                "currency": currency,
                "amountUsd": amount if currency.upper() == "USD" else None,
                "normalizationState": (
                    "native_currency_usd" if currency.upper() == "USD" else "not_normalized"
                ),
                "lifecycleState": lifecycle_state,
                "reconciliationState": state,
                "conflictReason": conflict_reason,
                "provider": provider,
                "sourceRecordId": record_id,
                "evidenceRecordId": evidence_id,
                "occurredAt": source_record.get("occurredAt"),
                "observedAt": source_record.get("observedAt"),
                "ledgerCreatedAt": record.get("createdAt"),
                "ledgerUpdatedAt": record.get("updatedAt"),
                "asOf": as_of,
                "evidence": evidence_refs,
            }
        )
        if fact_kind == "payment":
            for field in _PAYMENT_SOURCE_DETAIL_FIELDS:
                value = source_record.get(field)
                if value is not None:
                    facts[-1][field] = value
        if fact_kind == "order":
            facts[-1]["providerOrderId"] = source_record.get("providerOrderId")
            facts[-1]["revisionId"] = source_record.get("revisionId")
            facts[-1]["sourceRevisionAt"] = source_record.get("sourceRevisionAt")
        elif fact_kind == "refund":
            facts[-1]["adjustmentType"] = source_record.get("adjustmentType")
            facts[-1]["reversesPaymentId"] = source_record.get("reversesPaymentId")
        elif fact_kind == "settlement":
            payment_refs = source_record.get("settlesPaymentRefs")
            if isinstance(payment_refs, list):
                facts[-1]["settlesPaymentRefs"] = [
                    {
                        "provider": payment_ref.get("provider"),
                        "providerPaymentId": payment_ref.get("providerPaymentId"),
                    }
                    for payment_ref in payment_refs
                    if isinstance(payment_ref, dict)
                    and isinstance(payment_ref.get("provider"), str)
                    and isinstance(payment_ref.get("providerPaymentId"), str)
                ]

    order_revisions = record.get("orderRevisions")
    if not isinstance(order_revisions, list) or not order_revisions:
        order = record.get("order")
        order_revisions = [order] if isinstance(order, dict) else []
    for order_revision in order_revisions:
        if isinstance(order_revision, dict):
            # The provider order ID identifies the operation, while the ledger's
            # revision ID is the evidence for this particular order snapshot.
            # Keep every stored revision so divergent revisions remain visible.
            add_fact(
                fact_kind="order",
                source_record=order_revision,
                record_id_field="providerOrderId",
                evidence_id_field="revisionId",
                lifecycle_state=state,
            )

    payment_observations = record.get("paymentObservations")
    if not isinstance(payment_observations, list) or not payment_observations:
        payment_observations = list((record.get("payments") or {}).values())
    for payment in _collapse_compatible_payment_observations(payment_observations):
        if isinstance(payment, dict):
            add_fact(
                fact_kind="payment",
                source_record=payment,
                record_id_field="providerPaymentId",
                lifecycle_state=str(payment.get("status") or "unknown"),
            )

    adjustment_observations = record.get("adjustmentObservations")
    if not isinstance(adjustment_observations, list) or not adjustment_observations:
        adjustment_observations = list((record.get("adjustments") or {}).values())
    for adjustment in adjustment_observations:
        if isinstance(adjustment, dict):
            adjustment_type = str(adjustment.get("adjustmentType") or "unknown")
            add_fact(
                fact_kind="refund" if adjustment_type == "refund" else "adjustment",
                source_record=adjustment,
                record_id_field="adjustmentId",
                lifecycle_state=adjustment_type,
            )

    settlement_observations = record.get("settlementObservations")
    if not isinstance(settlement_observations, list) or not settlement_observations:
        settlement_observations = list((record.get("settlements") or {}).values())
    for settlement in settlement_observations:
        if isinstance(settlement, dict):
            add_fact(
                fact_kind="settlement",
                source_record=settlement,
                record_id_field="providerSettlementId",
                lifecycle_state=str(settlement.get("status") or "unknown"),
            )

    return facts


def _collapse_compatible_payment_observations(
    observations: list[Any],
) -> list[dict[str, Any]]:
    """Keep one value fact per payment when a later snapshot only adds details.

    The ledger retains each observed snapshot for as-of reconstruction. Once a
    snapshot is selected for a projection, compatible snapshots with the same
    provider payment ID can be folded into one fact. Any divergent amount,
    lifecycle, timestamp, rail, or network evidence remains separate so the
    existing conflict state stays visible.
    """
    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    ungrouped: list[dict[str, Any]] = []
    for row in observations:
        if not isinstance(row, dict):
            continue
        provider = row.get("provider")
        payment_id = row.get("providerPaymentId")
        if (
            not isinstance(provider, str)
            or not provider
            or not isinstance(payment_id, str)
            or not payment_id
        ):
            ungrouped.append(row)
            continue
        groups.setdefault((provider, payment_id), []).append(row)

    collapsed: list[dict[str, Any]] = list(ungrouped)
    stable_fields = (
        "provider",
        "providerPaymentId",
        "amount",
        "currency",
        "status",
        "occurredAt",
    )
    for rows in groups.values():
        if len(rows) == 1:
            collapsed.append(rows[0])
            continue
        divergent = any(
            len({row.get(field) for row in rows}) > 1 for field in stable_fields
        ) or any(
            len({row.get(field) for row in rows if row.get(field) is not None}) > 1
            for field in _PAYMENT_SOURCE_DETAIL_FIELDS
        )
        if divergent:
            collapsed.extend(rows)
            continue
        merged = dict(rows[0])
        merged["_recordObservedAt"] = rows[0].get("observedAt")
        for row in rows[1:]:
            for field in _PAYMENT_SOURCE_DETAIL_FIELDS:
                if row.get(field) is not None:
                    merged[field] = row[field]
            if row.get("observedAt") is not None:
                merged["observedAt"] = row["observedAt"]
        collapsed.append(merged)
    return collapsed


__all__ = [
    "campaign_commerce_operation_evidence",
    "entity_commerce_operation_evidence",
    "journey_commerce_operation_evidence",
]
