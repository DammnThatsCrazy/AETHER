"""SDK-adapter mapping: validated SDK event -> UniversalObservationEnvelope.

WS-A5 flag-gated adoption (default OFF, `AETHER_OBSERVATION_ENVELOPE_ENABLED`):
given the normalized SDK payload produced by
``services/ingestion/validation.build_normalized_payload`` (plus the temporal
envelope stamped by ``_apply_temporal_enforcement``), build the canonical
Envelope-B observation and persist it additively as
``normalized["observation_envelope"]``. The flat SDK dict remains the
consumption surface until WS-B converges every adapter onto Envelope B
(Invariant #1); consumers are untouched by the additive key.

Subject ``trust_class`` is derived from the generated ``EVENT_FIELD_TRUST``
(WS-A2) where present and never exceeds the WS-A3 public-SDK boundary
(<= CLIENT_HINT): ``user_id`` -> CLIENT_HINT (fallback), ``anonymous_id`` ->
OBSERVED. The mapping only emits blocks it can fill from evidence already on
the normalized payload; source-trust evaluation, consent/privacy policy,
idempotency ordering and raw-record lineage are the WS-B gateway's scope and
deliberately stay unset here.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping, Optional

from services.ingestion.generated_registry import EVENT_FIELD_TRUST
from shared.logger.logger import get_logger
from shared.observation.envelope import (
    CorrelationBlock,
    ObservationBlock,
    ProvenanceBlock,
    SourceBlock,
    SubjectRef,
    TemporalBlock,
    TenancyBlock,
    UniversalObservationEnvelope,
)

logger = get_logger("aether.service.ingestion.observation_envelope")

ENVELOPE_SCHEMA_VERSION = "1.0.0"

# Fallback trust classes for the two identifiers the SDK asserts. Derived from
# EVENT_FIELD_TRUST when the event declares an override; otherwise userId is a
# client hint and anonymous_id is a server-observed client claim.
_USER_ID_TRUST_FALLBACK = "CLIENT_HINT"
_ANONYMOUS_ID_TRUST = "OBSERVED"


def _parse_dt(value: Optional[str]) -> Optional[datetime]:
    """Parse an ISO-8601 instant; server stamps are UTC, client claims keep
    their zone (``Z`` normalized). Returns None when unparseable."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


def _subject_trust(event_type: str, field_path: str, fallback: str) -> str:
    declared = EVENT_FIELD_TRUST.get(event_type, {}).get(field_path, {})
    if isinstance(declared, dict):
        declared_class = declared.get("trustClass")
        if isinstance(declared_class, str) and declared_class:
            return declared_class
    return fallback


def _utc_offset_str(offset_minutes: Optional[int]) -> Optional[str]:
    if offset_minutes is None:
        return None
    sign = "+" if offset_minutes >= 0 else "-"
    minutes = abs(offset_minutes)
    return f"{sign}{minutes // 60:02d}:{minutes % 60:02d}"


def build_sdk_observation_envelope(
    normalized: Mapping[str, Any],
    *,
    ingress_path: str = "/v1/batch",
) -> Optional[UniversalObservationEnvelope]:
    """Map an accepted, validated SDK event to a UniversalObservationEnvelope.

    Returns None (not raise) when the normalized payload cannot supply the
    envelope's required core — callers degrade to the flat path with a warning
    so the flag can never take ingestion down.
    """
    event_type = normalized.get("event_type")
    occurred_at = _parse_dt(normalized.get("timestamp"))
    received_at = _parse_dt(normalized.get("received_at"))
    ingested_at = _parse_dt(normalized.get("ingested_at"))
    event_id = normalized.get("event_id")
    tenant_id = normalized.get("tenant_id")
    if not event_id or not tenant_id or not event_type:
        return None
    if occurred_at is None or received_at is None or ingested_at is None:
        logger.warning(
            "observation_envelope: unparseable core instants, skipping envelope "
            "for event_type=%s event_id=%s",
            event_type,
            event_id,
        )
        return None

    context = normalized.get("context") or {}
    if not isinstance(context, dict):
        context = {}

    subjects: list[SubjectRef] = []
    anonymous_id = normalized.get("anonymous_id")
    user_id = normalized.get("user_id")
    if anonymous_id:
        subjects.append(
            SubjectRef(
                identifier_type="anonymous_id",
                identifier_value=str(anonymous_id),
                trust_class=_ANONYMOUS_ID_TRUST,
                source="sdk",
            )
        )
    if user_id:
        subjects.append(
            SubjectRef(
                identifier_type="user_id",
                identifier_value=str(user_id),
                trust_class=_subject_trust(event_type, "userId", _USER_ID_TRUST_FALLBACK),
                source="sdk",
            )
        )

    # WS-C / Invariant #12 (correlation is additive — source-native correlation
    # is never overwritten). The SDK ships correlation either as the nested
    # camelCase ``context.correlation`` dict (the A-side CorrelationContext
    # tuple in packages/shared/events.ts) or as legacy flat
    # context.correlationId/causationId/traceId/spanId keys. We map ONLY those
    # source-native values into the CorrelationBlock: nothing here re-stamps or
    # overwrites an id the source provided, and an explicitly-shipped nested
    # ``correlation`` block wins over any legacy flat keys on the same event.
    # ``parentObservationId`` (camelCase) is carried additively so a native
    # parent link survives end-to-end into the envelope correlation block.
    correlation: Optional[CorrelationBlock] = None
    if isinstance(context.get("correlation"), dict):
        corr = context["correlation"]
        correlation = CorrelationBlock(
            correlation_id=corr.get("correlationId") or context.get("correlationId"),
            causation_id=corr.get("causationId") or context.get("causationId"),
            trace_id=corr.get("traceId") or context.get("traceId"),
            span_id=corr.get("spanId") or context.get("spanId"),
            parent_observation_id=(
                corr.get("parentObservationId") or corr.get("parent_observation_id")
            ),
        )
    elif context.get("correlationId") or context.get("traceId"):
        correlation = CorrelationBlock(
            correlation_id=context.get("correlationId"),
            causation_id=context.get("causationId"),
            trace_id=context.get("traceId"),
            span_id=context.get("spanId"),
        )

    temporal: Optional[TemporalBlock] = None
    temporal_stamp = normalized.get("temporal")
    if isinstance(temporal_stamp, dict):
        sequence = None
        context_sequence = context.get("sequence")
        if isinstance(context_sequence, dict):
            event_sequence = context_sequence.get("event")
            if event_sequence is not None:
                sequence = str(event_sequence)
        temporal = TemporalBlock(
            source_time=temporal_stamp.get("source_timestamp_original"),
            timezone=temporal_stamp.get("source_time_zone"),
            utc_offset=_utc_offset_str(temporal_stamp.get("source_utc_offset_minutes")),
            clock_source=temporal_stamp.get("clock_source"),
            sequence=sequence,
            temporal_quality=temporal_stamp.get("temporal_state"),
        )

    payload = normalized.get("properties")
    payload_block = payload if isinstance(payload, dict) and payload else None

    return UniversalObservationEnvelope(
        observation=ObservationBlock(
            observation_id=str(event_id),
            observation_type=event_type,
            family=normalized.get("event_family"),
            occurred_at=occurred_at,
            received_at=received_at,
            ingested_at=ingested_at,
            schema_version=ENVELOPE_SCHEMA_VERSION,
        ),
        tenancy=TenancyBlock(tenant_id=str(tenant_id)),
        source=SourceBlock(
            source_type="sdk",
            ingress_path=ingress_path,
        ),
        subjects=subjects,
        correlation=correlation,
        temporal=temporal,
        payload=payload_block,
        provenance=ProvenanceBlock(
            adapter="sdk",  # canonical SDK adapter identity (SdkIngressAdapter.adapter_id)
            adapter_version="1.0.0",
        ),
    )
