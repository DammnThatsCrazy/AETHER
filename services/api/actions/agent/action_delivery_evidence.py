"""Fail-closed, bounded reads of canonical delivery evidence for action dispatches."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote

from shared.temporal.instant import parse_instant_strict

_MAX_JOBS = 20
_MAX_OUTCOMES = 50


async def read_action_delivery_evidence(
    *, tenant_id: str, dispatch: dict[str, Any],
    intents: Any = None, jobs: Any = None, receipts: Any = None,
    links: Any = None, outcomes: Any = None,
) -> tuple[dict[str, Any], bool]:
    """Read connector-reported delivery and verified callback evidence.

    The only accepted path is dispatch -> deterministic action intent -> job ->
    provider receipt -> external resource link. Missing records are represented
    as unknown evidence; malformed, truncated, cross-tenant, or ambiguous reads
    fail closed and return ``complete=False``.
    """
    from repositories.delivery_repos import (
        DeliveryIntentRepository, DeliveryJobRepository, ProviderReceiptRepository,
        ExternalResourceLinkRepository, ExternalOutcomeEventRepository,
        ProviderExecutionVerificationRepository,
    )

    intents = intents or DeliveryIntentRepository()
    jobs = jobs or DeliveryJobRepository()
    receipts = receipts or ProviderReceiptRepository()
    links = links or ExternalResourceLinkRepository()
    outcomes = outcomes or ExternalOutcomeEventRepository()
    verifications = ProviderExecutionVerificationRepository()
    empty = {
        "connectorReceiptRead": "unknown",
        "connectorReceiptReason": "action_delivery_evidence_missing",
        "connectorReportedDeliveries": [],
        "verifiedCallbacks": [],
        "independentExecutionVerifications": [],
    }
    try:
        dispatch_id = dispatch.get("dispatch_id")
        dispatch_created = parse_instant_strict(dispatch.get("created_at"))
        now = datetime.now(timezone.utc)
        if (not isinstance(dispatch_id, str) or not dispatch_id.strip()
                or dispatch.get("id") != dispatch_id
                or dispatch.get("tenant_id") != tenant_id or dispatch_created > now):
            return empty, False
        intent_id = f"action-{dispatch_id}"
        intent = await intents.find_by_id(intent_id)
        if intent is None:
            return empty, True
        if (not isinstance(intent, dict) or intent.get("id") != intent_id
                or intent.get("tenant_id") != tenant_id or intent.get("source_type") != "action"
                or intent.get("source_id") != dispatch_id):
            return empty, False
        intent_created = parse_instant_strict(intent.get("created_at"))
        if intent_created < dispatch_created or intent_created > now:
            return empty, False

        job_rows = await jobs.find_many(filters={"tenant_id": tenant_id, "intent_id": intent_id},
                                        limit=_MAX_JOBS + 1)
        if not isinstance(job_rows, list) or len(job_rows) > _MAX_JOBS:
            return empty, False
        seen_jobs: set[str] = set()
        deliveries: list[dict[str, Any]] = []
        callbacks: list[dict[str, Any]] = []
        for job in job_rows:
            if not isinstance(job, dict):
                return empty, False
            job_id, provider = job.get("id"), job.get("provider_adapter")
            if (job.get("tenant_id") != tenant_id or job.get("intent_id") != intent_id
                    or not isinstance(job_id, str) or not job_id.strip()
                    or not isinstance(provider, str) or not provider.strip()
                    or job_id in seen_jobs):
                return empty, False
            seen_jobs.add(job_id)
            job_created = parse_instant_strict(job.get("created_at"))
            if job_created < intent_created or job_created > now:
                return empty, False
            receipt_rows = await receipts.find_many(
                filters={"tenant_id": tenant_id, "intent_id": intent_id, "job_id": job_id}, limit=3
            )
            if not isinstance(receipt_rows, list) or len(receipt_rows) > 2:
                return empty, False
            if not receipt_rows:
                continue
            if len(receipt_rows) != 1 or not isinstance(receipt_rows[0], dict):
                return empty, False
            receipt = receipt_rows[0]
            receipt_id, external_id = receipt.get("id"), receipt.get("external_id")
            if (receipt.get("tenant_id") != tenant_id or receipt.get("intent_id") != intent_id
                    or receipt.get("job_id") != job_id or receipt.get("provider_adapter") != provider
                    or not isinstance(receipt_id, str) or not receipt_id.strip()
                    or not isinstance(external_id, str) or not external_id.strip()
                    or external_id.startswith("sim-")):
                return empty, False
            delivered = parse_instant_strict(receipt.get("delivered_at"))
            receipt_created = parse_instant_strict(receipt.get("created_at"))
            if (delivered < job_created or receipt_created < delivered
                    or delivered > now or receipt_created > now):
                return empty, False
            link_rows = await links.find_many(
                filters={"tenant_id": tenant_id, "intent_id": intent_id, "receipt_id": receipt_id}, limit=3
            )
            if not isinstance(link_rows, list) or len(link_rows) > 2:
                return empty, False
            if len(link_rows) != 1 or not isinstance(link_rows[0], dict):
                return empty, False
            link = link_rows[0]
            if (link.get("tenant_id") != tenant_id or link.get("intent_id") != intent_id
                    or link.get("receipt_id") != receipt_id or link.get("provider") != provider
                    or link.get("external_id") != external_id
                    or link.get("aether_object_type") != "action"
                    or link.get("aether_object_id") != dispatch_id):
                return empty, False
            link_created = parse_instant_strict(link.get("created_at"))
            if link_created < delivered or link_created > now:
                return empty, False
            deliveries.append({
                "intentId": intent_id, "jobId": job_id, "receiptId": receipt_id,
                "provider": provider, "externalId": external_id, "deliveredAt": delivered.isoformat(),
                "independentExecutionVerifications": [],
                "evidenceRef": {"id": receipt_id, "type": "event", "source": "provider_receipts",
                                "observedAt": delivered.isoformat(),
                                "uri": f"store://provider_receipts/{quote(receipt_id, safe='')}"},
            })
            verification_rows = await verifications.find_for_receipt(tenant_id, receipt_id)
            if not isinstance(verification_rows, list) or len(verification_rows) > 1:
                return empty, False
            if verification_rows:
                import hashlib
                import json
                verification = verification_rows[0]
                association = dispatch.get("journey_action_association") or dispatch.get("risk_action_association")
                config = job.get("provider_config") or {}
                provider_site = str(config.get("base_url") or config.get("site_url") or "").rstrip("/")
                payload_hash = hashlib.sha256(json.dumps(
                    job.get("payload"), sort_keys=True, separators=(",", ":"), allow_nan=False,
                ).encode()).hexdigest()
                subject_kind = (
                    "journey" if dispatch.get("journey_action_association")
                    else association.get("subject_kind") if isinstance(association, dict) else None
                )
                if (not isinstance(verification, dict) or not isinstance(association, dict)
                        or not isinstance(verification.get("id"), str) or not verification.get("id", "").strip()
                        or verification.get("verified") is not True
                        or verification.get("verification_kind") != "credential_bound_provider_resource_readback"
                        or verification.get("provider") != provider or provider != "jira"
                        or dispatch.get("target_type") != provider
                        or job.get("idempotency_key") != dispatch_id
                        or job.get("payload") != dispatch.get("payload")
                        or not provider_site or verification.get("provider_site") != provider_site
                        or verification.get("requested_payload_sha256") != payload_hash
                        or verification.get("tenant_id") != tenant_id
                        or verification.get("dispatch_id") != dispatch_id
                        or verification.get("intent_id") != intent_id or verification.get("job_id") != job_id
                        or verification.get("receipt_id") != receipt_id
                        or verification.get("external_id") != external_id
                        or verification.get("association_record_id") != association.get("record_id")
                        or verification.get("subject_id") != association.get("subject_id")
                        or not subject_kind or verification.get("subject_kind") != subject_kind
                        or verification.get("provider_resource_identity") != f"{provider}:{external_id}"
                        or verification.get("policy_decision_id") != dispatch.get("dispatch_policy_decision_id")):
                    return empty, False
                from actions.agent.dispatch_authority import read_dispatch_authorization
                authorization = await read_dispatch_authorization(
                    tenant_id=tenant_id, action_id=dispatch.get("action_id", ""), dispatch=dispatch)
                if (authorization is None
                        or authorization.get("decision_id") != verification.get("policy_decision_id")
                        or authorization.get("evaluated_at") != verification.get("policy_evaluated_at")):
                    return empty, False
                observed = parse_instant_strict(verification.get("observed_at"))
                created_verification = parse_instant_strict(verification.get("created_at"))
                if observed < delivered or observed > now or created_verification < observed or created_verification > now:
                    return empty, False
                deliveries[-1]["independentExecutionVerifications"].append({
                    "id": verification.get("id"), "provider": provider,
                    "verificationKind": verification["verification_kind"],
                    "observedAt": observed.isoformat(),
                    "policyDecisionId": verification.get("policy_decision_id"),
                    "policyEvaluatedAt": verification.get("policy_evaluated_at"),
                    "subjectId": verification.get("subject_id"),
                    "providerResourceIdentity": verification.get("provider_resource_identity"),
                    "evidenceRef": {"id": verification.get("id"), "type": "event",
                                    "source": "provider_execution_verifications",
                                    "observedAt": observed.isoformat(),
                                    "uri": f"store://provider_execution_verifications/{quote(str(verification.get('id')), safe='')}"},
                })
            deliveries[-1]["executionVerificationStatus"] = (
                "verified" if deliveries[-1]["independentExecutionVerifications"]
                else "not_verified" if provider == "jira" else "unsupported"
            )
            outcome_rows = await outcomes.find_many(
                filters={"tenant_id": tenant_id, "intent_id": intent_id, "receipt_id": receipt_id},
                limit=_MAX_OUTCOMES + 1,
            )
            if not isinstance(outcome_rows, list) or len(outcome_rows) > _MAX_OUTCOMES:
                return empty, False
            seen_outcomes: set[str] = set()
            for event in outcome_rows:
                if not isinstance(event, dict):
                    return empty, False
                if event.get("producer_provenance") != "verified_callback":
                    continue
                event_id = event.get("id")
                if (not isinstance(event_id, str) or not event_id.strip() or event_id in seen_outcomes
                        or event.get("tenant_id") != tenant_id or event.get("intent_id") != intent_id
                        or event.get("receipt_id") != receipt_id or event.get("provider") != provider
                        or event.get("external_id") != external_id
                        or event.get("signature_authority") not in {
                            "external_provider_signature", "tenant_owned_webhook_signature"
                        }):
                    return empty, False
                seen_outcomes.add(event_id)
                occurred = parse_instant_strict(event.get("occurred_at"))
                ingested = parse_instant_strict(event.get("ingested_at"))
                if occurred < delivered or occurred > now or ingested < occurred or ingested > now:
                    return empty, False
                callbacks.append({
                    "id": event_id, "provider": provider,
                    "signatureAuthority": event["signature_authority"],
                    "outcomeType": event.get("outcome_type"), "occurredAt": occurred.isoformat(),
                    "evidenceRef": {"id": event_id, "type": "event", "source": "external_outcome_events",
                                    "observedAt": ingested.isoformat(),
                                    "uri": f"store://external_outcome_events/{quote(event_id, safe='')}"},
                })
        if deliveries:
            verification_records = [verification for delivery in deliveries
                                    for verification in delivery.get("independentExecutionVerifications", [])]
            return {"connectorReceiptRead": "complete", "connectorReceiptReason": "",
                    "connectorReportedDeliveries": deliveries, "verifiedCallbacks": callbacks,
                    "independentExecutionVerifications": verification_records}, True
        return {**empty, "connectorReceiptReason": "provider_receipt_unavailable"}, True
    except Exception:  # noqa: BLE001 - evidence failures never infer a provider effect
        return empty, False
