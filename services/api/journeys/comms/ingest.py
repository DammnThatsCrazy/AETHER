"""Comms ingest bridge — routes normalized provider events into the standard
Bronze → bus → Silver pipeline (Phase 12).

Connectors and the generic signed webhook normalize provider payloads into
canonical communication events; this module gives them one durable entry
point that matches the /v1/batch contract:

    durable Bronze write → SDK_EVENTS_VALIDATED publish → worker fan-out

Campaign/flow catalog records (klaviyo.campaign, klaviyo.flow, …) register
in the canonical campaign registry instead — no second registry (ADR-C9).
Nothing here calls a model; the critical path is
authenticate → verify → validate → dedupe → durable write → acknowledge.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Optional

from shared.common.common import BadRequestError
from shared.logger.logger import get_logger, metrics
from journeys.comms.contracts import COMMUNICATION_EVENT_TYPES

logger = get_logger("aether.comms.ingest")

# Connector catalog record types → campaign registry sync.
_CATALOG_EVENT_SUFFIXES = (".campaign", ".flow")
# Provider profile records → provider identity bridge (identity evidence only;
# these are not communication facts and never become touchpoints).
_PROFILE_EVENT_SUFFIXES = (".profile",)


async def ingest_normalized_events(
    tenant_id: str,
    events: list[Any],
    *,
    source_connector_id: Optional[str] = None,
) -> dict[str, int]:
    """Persist and publish a batch of connector-normalized events.

    ``events`` are NormalizedEvent instances or dicts with
    event_type/external_id/occurred_at/properties. Returns counters:
    ``{"communications": n, "catalog": n, "skipped": n}``.
    """
    counts = {"communications": 0, "catalog": 0, "identities": 0, "skipped": 0}
    for event in events:
        data = event.model_dump() if hasattr(event, "model_dump") else dict(event)
        event_type = data.get("event_type", "")
        if event_type in COMMUNICATION_EVENT_TYPES:
            # WS-B3 (C class): a consent-denied communication event is dropped
            # entirely — nothing about it is written, published, identity-bridged,
            # suppression-recorded, or metered (fail-closed, never partial).
            ingested = await _ingest_communication(tenant_id, data, source_connector_id)
            if not ingested:
                counts["skipped"] += 1
                continue
            # Provider identity evidence carried on the event (best-effort;
            # the communication fact is preserved regardless of resolution).
            await _record_identity(tenant_id, data)
            # Suppression signals (unsubscribe/complaint/hard-bounce/suppressed)
            # update the canonical suppression authority (best-effort).
            await _record_suppression(tenant_id, data)
            # Billable usage metering (dedupe-safe; §20).
            await _meter_event(tenant_id, data)
            counts["communications"] += 1
        elif any(event_type.endswith(s) for s in _CATALOG_EVENT_SUFFIXES):
            await _register_catalog_record(tenant_id, data, source_connector_id)
            counts["catalog"] += 1
        elif any(event_type.endswith(s) for s in _PROFILE_EVENT_SUFFIXES):
            # Provider profile records are identity evidence only.
            if await _record_identity(tenant_id, data):
                counts["identities"] += 1
            else:
                counts["skipped"] += 1
        else:
            counts["skipped"] += 1
    if counts["communications"]:
        metrics.increment(
            "comms_events_ingested_total",
            counts["communications"],
            labels={"tenant_id": tenant_id, "source": data.get("source", "unknown")},
        )
    return counts


async def _ingest_communication(
    tenant_id: str,
    data: dict[str, Any],
    source_connector_id: Optional[str],
) -> bool:
    """Durable Bronze write, then bus publish (mirrors /v1/batch ordering).

    Returns True when the event was persisted + published, False when the
    WS-B3 ingress consent gate dropped it (never a partial write).
    """
    properties = dict(data.get("properties") or {})
    if source_connector_id:
        properties.setdefault("source_connector_id", source_connector_id)

    # WS-B3 connector/comm consent (C class). scrubbing sensitive values from
    # properties is the MANDATORY minimization layer and runs UNCONDITIONALLY —
    # it is never gated by the per-path flag (redaction never rejects). The
    # shared ingress decision then runs for EVERY communication event: tenant
    # data-policy removal of fingerprinting always, and the per-subject (S)
    # server-receipt rejection only when the connector S-gate is enabled AND the
    # event resolves a purpose + a subject under the authoritative flag. A
    # denial drops the event — no Bronze, no publish.
    from config.settings import settings
    from ingestion.ingestion.generated_registry import EVENT_CONSENT_PURPOSE
    from ingestion.ingestion.validation import (
        evaluate_ingress_decision,
        scrub_sensitive_fields,
    )

    properties, _ = scrub_sensitive_fields(properties)
    event_type = str(data.get("event_type") or "")
    provider = properties.get("provider") or data.get("source") or "webhook"
    provider_account_id = properties.get("provider_account_id") or provider
    provider_recipient_id = properties.get("provider_recipient_id")
    provider_profile_id = properties.get("provider_profile_id") or properties.get(
        "provider_profile"
    )
    recipient_identity = None
    try:
        from journeys.comms.identity_bridge import resolve_provider_recipient_identity

        recipient_identity = await resolve_provider_recipient_identity(
            tenant_id,
            str(provider),
            str(provider_account_id),
            provider_recipient_id=(str(provider_recipient_id) if provider_recipient_id else None),
            provider_profile_id=(str(provider_profile_id) if provider_profile_id else None),
        )
    except Exception:  # noqa: BLE001 - an unavailable identity link stays unknown
        recipient_identity = None
    canonical_recipient_id = (
        recipient_identity.get("canonical_entity_id") if recipient_identity is not None else None
    )
    source_agent_id = properties.get("agent_id")
    sender_identity = None
    if isinstance(source_agent_id, str) and source_agent_id.strip():
        try:
            sender_identity = await _resolve_agent_sender_binding(
                tenant_id, source_agent_id.strip()
            )
        except Exception:  # noqa: BLE001 - unresolved agent sender stays unknown
            sender_identity = None

    # Connector fields that look canonical are source claims. Drop them before
    # creating the normalized event; only the verified bridge result below may
    # supply a canonical recipient to downstream projectors.
    for key in (
        "recipient_entity_id",
        "profile_id",
        "sender_entity_id",
        "consent_snapshot_id",
        "consentSnapshotId",
        "consent_purpose",
        "consent_subject_id",
        "consent_evaluation_state",
        "consent_identity_binding_id",
    ):
        properties.pop(key, None)
    if canonical_recipient_id:
        properties["recipient_entity_id"] = canonical_recipient_id
        properties["profile_id"] = canonical_recipient_id

    mapped_purpose = EVENT_CONSENT_PURPOSE.get(event_type)
    purpose = mapped_purpose
    if not settings.ingress_consent.connector_comms_consent_enforcement_enabled:
        # S-class server-receipt escalation disabled for this connector path:
        # fall back to the unconditional scrub + data-policy decision (no
        # per-subject lookup or purpose gate; the event is processed under C/T
        # minimization).
        purpose = None
    allowed, reason_code, decisions = await evaluate_ingress_decision(
        tenant_id=tenant_id,
        subject_id=canonical_recipient_id,
        anonymous_id=None,
        purpose=purpose,
        fingerprint_obj=properties,
        include_receipt_id=True,
    )
    if not allowed:
        logger.warning(
            "comms_ingest_consent_denied event=%s tenant=%s type=%s reason=%s",
            data.get("external_id") or data.get("id"),
            tenant_id,
            event_type,
            reason_code,
        )
        return False

    consent_decision = next(
        (
            item
            for item in decisions
            if item.get("control") == "consent_authority" and item.get("outcome") == "allowed"
        ),
        {},
    )
    receipt_id = consent_decision.get("receipt_id")
    receipt_id = receipt_id if isinstance(receipt_id, str) and receipt_id else None
    consent_recorded = bool(
        receipt_id and canonical_recipient_id and recipient_identity is not None
    )

    event_id = str(data.get("external_id") or uuid.uuid4())
    # Deterministic event id namespaced by provider so replays dedupe.
    normalized = {
        "event_id": f"{provider}:{event_id}",
        "tenant_id": tenant_id,
        "event_type": data.get("event_type"),
        "event_family": "comms",
        "session_id": properties.get("session_id"),
        "anonymous_id": properties.get("anonymous_id"),
        "user_id": canonical_recipient_id,
        "properties": properties,
        "context": {
            "tenantId": tenant_id,
            "sourceConnectorId": source_connector_id,
            "recipientEntityId": canonical_recipient_id,
            "recipientIdentityBindingId": (
                recipient_identity.get("identity_id") if recipient_identity else None
            ),
            "senderEntityId": (
                sender_identity.get("canonical_entity_id") if sender_identity else None
            ),
            "senderIdentityBindingId": (
                sender_identity.get("identity_evidence_id") if sender_identity else None
            ),
            "senderIdentityEvidenceSource": (
                sender_identity.get("identity_evidence_source") if sender_identity else None
            ),
            "consentPurpose": mapped_purpose,
            "consentEvidenceState": "recorded" if consent_recorded else "unknown",
            "consentSnapshotId": receipt_id if consent_recorded else None,
            "consentSubjectEntityId": (canonical_recipient_id if consent_recorded else None),
            "consentIdentityBindingId": (
                recipient_identity.get("identity_id")
                if consent_recorded and recipient_identity
                else None
            ),
            "consentAuthority": ("server_consent_authority" if consent_recorded else None),
        },
        # Provider-reported occurrence time; providers that send no timestamp
        # (Mailchimp) emit the empty "unknown" sentinel — fall back to received
        # time so Bronze never stores an empty occurrence.
        "timestamp": data.get("occurred_at") or _now(),
        "received_at": _now(),
        "ingested_at": _now(),
        "batch_id": f"connector:{provider}",
        "schema_version": "1.0.0",
        "source": "connector",
    }
    participant_roster = data.get("participant_roster")
    participant_roster_authoring = data.get("participant_roster_authoring")
    participant_authoring_context = None
    if participant_roster is not None:
        from journeys.communication360.contracts import ParticipantRosterAssertion
        from journeys.communication360.participant_writer import ParticipantBindingAuthoringContext

        try:
            participant_roster = ParticipantRosterAssertion.model_validate(participant_roster)
        except Exception as exc:  # noqa: BLE001 - contract failures do not reach Bronze
            raise BadRequestError("participant roster does not match the typed contract") from exc
        raw_event_id = data.get("external_id")
        raw_occurred_at = data.get("occurred_at")
        if not isinstance(raw_event_id, str) or not raw_event_id.strip():
            raise BadRequestError("participant roster events require external_id")
        if (
            not isinstance(raw_occurred_at, str)
            or not raw_occurred_at.strip()
        ):
            raise BadRequestError("participant roster events require occurred_at")
        try:
            parsed_occurred_at = datetime.fromisoformat(
                raw_occurred_at.strip().replace("Z", "+00:00")
            )
        except ValueError as exc:
            raise BadRequestError("participant roster occurred_at must include an ISO timestamp") from exc
        if parsed_occurred_at.tzinfo is None or parsed_occurred_at.utcoffset() is None:
            raise BadRequestError("participant roster occurred_at must include a timezone")
        if data.get("source") and str(data["source"]).strip() != str(provider).strip():
            raise BadRequestError("participant roster provider namespace does not match source")
        if participant_roster.provider_account_id != str(provider_account_id).strip():
            raise BadRequestError("participant roster provider account does not match event account")
        if not isinstance(participant_roster_authoring, dict):
            raise BadRequestError("participant roster lacks verified authoring context")
        try:
            participant_authoring_context = ParticipantBindingAuthoringContext(
                actor_id=str(participant_roster_authoring["actor_id"]),
                credential_class=str(participant_roster_authoring["credential_class"]),
                signature_verified=participant_roster_authoring["signature_verified"] is True,
                authentication_method=str(
                    participant_roster_authoring["authentication_method"]
                ),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise BadRequestError("participant roster lacks verified authoring context") from exc
        if (
            not participant_authoring_context.signature_verified
            or participant_authoring_context.authentication_method != "tenant_webhook_hmac"
            or not participant_authoring_context.actor_id.strip()
            or not participant_authoring_context.credential_class.strip()
        ):
            raise BadRequestError("participant roster lacks verified authoring context")
        # Retain the typed assertion and route-created source-authentication
        # envelope in Bronze so a retry can reproduce the same authoring
        # decision. The roster contract contains metadata-only identifiers;
        # message content remains outside this fact path.
        normalized["participantRoster"] = participant_roster.model_dump(
            mode="json", exclude_none=True
        )
        normalized["participantRosterAuthoring"] = {
            "actor_id": participant_authoring_context.actor_id,
            "credential_class": participant_authoring_context.credential_class,
            "signature_verified": True,
            "authentication_method": "tenant_webhook_hmac",
        }

    from repositories.lake import BronzeRepository

    bronze = BronzeRepository("sdk_events")
    await bronze.ingest(
        source="connector",
        source_tag=f"connector:{provider}:{tenant_id}",
        provider_record_id=normalized["event_id"],
        payload=normalized,
        schema_version="1.0.0",
        entity_id=normalized.get("user_id") or "",
        entity_type="user",
        tenant_id=tenant_id,
    )

    if participant_roster is not None:
        # The route only adds this authoring envelope after verifying the
        # tenant webhook HMAC. Missing or malformed context fails closed. The
        # roster write follows consent and durable Bronze, but precedes bus
        # publication; deterministic fact keys make client retries idempotent.
        from journeys.communication360.participant_writer import ParticipantBindingWriter

        await ParticipantBindingWriter().write_roster(
            tenant_id=tenant_id,
            provider=str(provider),
            event_id=event_id,
            event_type=event_type,
            occurred_at=str(data.get("occurred_at") or ""),
            roster=participant_roster,
            authoring_context=participant_authoring_context,
            policy_context={
                "consent_receipt_id": receipt_id if consent_recorded else None,
                "consent_authority": (
                    "server_consent_authority" if consent_recorded else None
                ),
            },
        )

    try:
        from dependencies.providers import get_registry
        from shared.events.events import Event, Topic

        registry = get_registry()
        await registry.producer.publish(
            Event(
                topic=Topic.SDK_EVENTS_VALIDATED,
                tenant_id=tenant_id,
                source_service="comms.ingest",
                payload=normalized,
            )
        )
    except Exception as exc:
        # Bronze is durable; a replay of the Bronze range recovers the publish.
        logger.warning("comms_ingest_publish_failed event=%s: %s", normalized["event_id"], exc)
        metrics.increment("comms_ingest_publish_failures_total", labels={"tenant_id": tenant_id})
    return True


async def _record_identity(tenant_id: str, data: dict[str, Any]) -> bool:
    """Record provider identity evidence into the bridge (§13). Best-effort."""
    try:
        from journeys.comms.identity_bridge import record_identity_from_event

        result = await record_identity_from_event(tenant_id, data)
        return result is not None
    except Exception as exc:  # pragma: no cover - never break ingest
        logger.warning("comms_identity_bridge_failed: %s", exc)
        return False


async def _resolve_agent_sender_binding(
    tenant_id: str, source_agent_ref: str
) -> Optional[dict[str, str]]:
    """Reuse Agent360's exact tenant deployment/binding/entity authority."""
    from actions.agent.agent360_provider import RepositoryAgent360Source

    batch = await RepositoryAgent360Source().actor_identity(tenant_id, source_agent_ref)
    if batch.truncated or batch.scope_mismatch:
        return None
    rows = [
        row
        for row in batch.rows
        if isinstance(row, dict)
        and row.get("tenant_id") == tenant_id
        and row.get("agent_id") == source_agent_ref
    ]
    if not rows:
        return None
    # A malformed matching resolution row makes the handoff unknown. Silently
    # dropping it could make a conflicting Agent360 result look unique.
    if any(
        not isinstance(row.get("canonical_agent_entity_id"), str)
        or not row["canonical_agent_entity_id"].strip()
        or not isinstance(row.get("identity_evidence_source"), str)
        or not row["identity_evidence_source"].strip()
        or not isinstance(row.get("identity_evidence_id"), str)
        or not row["identity_evidence_id"].strip()
        for row in rows
    ):
        return None
    canonical_ids = {row["canonical_agent_entity_id"] for row in rows}
    if len(canonical_ids) != 1:
        return None
    canonical_id = next(iter(canonical_ids))
    evidence = {
        (row["identity_evidence_source"], row["identity_evidence_id"])
        for row in rows
        if row["canonical_agent_entity_id"] == canonical_id
    }
    if len(evidence) != 1:
        return None
    evidence_source, evidence_id = next(iter(evidence))
    return {
        "canonical_entity_id": canonical_id,
        "identity_evidence_source": evidence_source,
        "identity_evidence_id": evidence_id,
    }


async def _record_suppression(tenant_id: str, data: dict[str, Any]) -> None:
    """Record a canonical suppression when the event carries one. Best-effort."""
    try:
        from journeys.comms.suppression_authority import SuppressionAuthorityService

        await SuppressionAuthorityService().record_from_event(tenant_id, data)
    except Exception as exc:  # pragma: no cover - never break ingest
        logger.warning("comms_suppression_authority_failed: %s", exc)


async def _meter_event(tenant_id: str, data: dict[str, Any]) -> None:
    """Emit billable usage metering for one canonical event. Best-effort."""
    try:
        from journeys.comms.metering import record_event_usage

        props = data.get("properties") or {}
        provider = props.get("provider") or data.get("source") or "webhook"
        event_id = str(data.get("external_id") or "")
        if event_id:
            await record_event_usage(
                tenant_id,
                event_type=data.get("event_type", ""),
                event_id=f"{provider}:{event_id}",
                provider=provider,
            )
    except Exception as exc:  # pragma: no cover - metering never breaks ingest
        logger.warning("comms_event_metering_failed: %s", exc)


async def _register_catalog_record(
    tenant_id: str,
    data: dict[str, Any],
    source_connector_id: Optional[str],
) -> None:
    """Campaign/flow catalog record → canonical campaign registry + message dims."""
    properties = data.get("properties") or {}
    provider = data.get("source", "unknown")
    external_id = (
        properties.get("external_campaign_id")
        or properties.get("external_flow_id")
        or data.get("external_id")
    )
    if not external_id:
        return
    try:
        from journeys.campaign.registry import CampaignRegistryService

        registry = CampaignRegistryService()
        campaign = await registry.upsert_external_campaign(
            tenant_id,
            platform=provider,
            external_account_id=properties.get("provider_account_id") or provider,
            external_campaign_id=str(external_id),
            external_campaign_name=properties.get("name"),
            external_status=properties.get("status"),
            source_connector_id=source_connector_id,
            channel=properties.get("channel") or "email",
        )
        # Message dimension rows ride along when the provider includes them.
        for message in properties.get("messages") or []:
            from journeys.comms.repository import CampaignMessageRepository

            await CampaignMessageRepository().upsert_message(
                {
                    "tenant_id": tenant_id,
                    "campaign_id": str(campaign["campaign_id"]),
                    "provider": provider,
                    "provider_account_id": properties.get("provider_account_id"),
                    "external_message_id": str(
                        message.get("id") or message.get("external_message_id")
                    ),
                    "external_template_id": message.get("template_id"),
                    "name": message.get("name"),
                    "sequence_step": message.get("sequence_step"),
                    "variant_id": message.get("variant_id"),
                    "channel": properties.get("channel") or "email",
                    "source_connector_id": source_connector_id,
                }
            )
    except Exception as exc:
        logger.warning(
            "comms_catalog_register_failed provider=%s external_id=%s: %s",
            provider,
            external_id,
            exc,
        )
        metrics.increment("comms_catalog_failures_total", labels={"tenant_id": tenant_id})


def _now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()
