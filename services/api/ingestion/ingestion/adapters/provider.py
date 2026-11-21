"""ProviderIngressAdapter — connector pulls and provider webhooks into Envelope B.

A provider canonical event (``AetherEvent``) reaches the shared Bronze/outbox
transaction through ``connectors.provider_runtime.bridge``. Before this adapter
those rows carried only the flat event dump, so a provider observation could
not say which source instance produced it or which rights decision admitted
its raw record. This adapter gives provider rows the same Envelope-B source
block the SDK path carries:

* ``source.source_type`` — ``connector`` for pulls, ``webhook`` for deliveries;
* ``source.source_relationship`` — from the admitting grant, never the payload;
* ``source.source_instance`` — the grant's source scope
  (``provider-account:<connection>:<account>`` or ``provider-stream:...``);
* ``rights`` — the source id, grant ref and ``rdec_`` decision ref recorded on
  the raw record when it was admitted;
* ``lineage.raw_record_ref`` — the raw record the event was normalized from.

Like every adapter it only builds the envelope; it decides nothing.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping, Optional

from shared.integration_contracts.source_relationship import UNCLASSIFIED
from shared.observation.envelope import (
    RIGHTS_DECISION_REF_PREFIX,
    LineageBlock,
    ObservationBlock,
    ProvenanceBlock,
    RightsReferenceBlock,
    SourceBlock,
    SubjectRef,
    TenancyBlock,
    TemporalBlock,
    UniversalObservationEnvelope,
)

from ingestion.ingestion.adapters.base import UniversalIngressAdapter

PROVIDER_ENVELOPE_SCHEMA_VERSION = "1.0.0"
RIGHTS_ADMISSION_METADATA_KEY = "aether_rights_admission"

_WEBHOOK_MODES = frozenset({"webhook"})


def _parse(value: Any) -> Optional[datetime]:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _admission(raw_record: Any) -> Mapping[str, Any]:
    metadata = getattr(raw_record, "metadata", None) or {}
    admission = metadata.get(RIGHTS_ADMISSION_METADATA_KEY) if isinstance(metadata, Mapping) else None
    return admission if isinstance(admission, Mapping) else {}


class ProviderIngressAdapter(UniversalIngressAdapter):
    """Connector-family adapter: provider canonical event -> Envelope B."""

    adapter_id = "provider_runtime"
    family = "connector"
    credential_class = "MANAGED_CONNECTOR"
    adapter_version = "1.0.0"
    description = (
        "Universal provider runtime pulls and webhooks. Maps a consent-admitted "
        "AetherEvent plus the rights admission recorded on its raw record to "
        "Envelope B; source relationship and instance come from the admitting grant."
    )

    def build_observation_envelope(
        self,
        normalized: Mapping[str, Any],
        *,
        ingress_path: Optional[str] = None,
        raw_record: Any = None,
    ) -> Optional[UniversalObservationEnvelope]:
        """Build the envelope from an ``AetherEvent.model_dump()``.

        Returns None when the event lacks the envelope core, so the bridge keeps
        the flat row and never fails a provider sync on envelope shape.
        """
        event_id = normalized.get("event_id")
        tenant_id = normalized.get("tenant_id")
        event_type = normalized.get("event_type")
        occurred_at = _parse(normalized.get("occurred_at"))
        received_at = _parse(normalized.get("observed_at"))
        if not event_id or not tenant_id or not event_type or occurred_at is None or received_at is None:
            return None

        acquisition_mode = str(getattr(raw_record, "acquisition_mode", "") or "")
        is_webhook = acquisition_mode in _WEBHOOK_MODES
        admission = _admission(raw_record)
        source_id = str(admission.get("source_id") or "") or None
        relationship = str(admission.get("source_relationship") or "") or UNCLASSIFIED
        grant_ref = str(admission.get("source_grant_ref") or "")
        decision_ref = str(admission.get("rights_decision_ref") or "")

        rights = None
        if source_id:
            rights = RightsReferenceBlock(
                source_id=source_id,
                source_grant_refs=[grant_ref] if grant_ref else [],
                rights_decision_refs=(
                    [decision_ref] if decision_ref.startswith(RIGHTS_DECISION_REF_PREFIX) else []
                ),
            )

        subjects: list[SubjectRef] = []
        subject_id = normalized.get("subject_id")
        if subject_id:
            subjects.append(SubjectRef(
                identifier_type="external_customer_id",
                identifier_value=str(subject_id),
                trust_class="OBSERVED",
                namespace=str(normalized.get("provider_identity") or "") or None,
                source="provider",
            ))

        return UniversalObservationEnvelope(
            observation=ObservationBlock(
                observation_id=str(event_id),
                observation_type=str(event_type),
                family=str(normalized.get("event_family") or "") or None,
                occurred_at=occurred_at,
                received_at=received_at,
                ingested_at=datetime.now(timezone.utc),
                schema_version=PROVIDER_ENVELOPE_SCHEMA_VERSION,
            ),
            tenancy=TenancyBlock(tenant_id=str(tenant_id)),
            source=SourceBlock(
                source_type="webhook" if is_webhook else "connector",
                source_relationship=relationship,
                source_provider=str(normalized.get("provider_identity") or "") or None,
                source_instance=source_id,
                source_native_id=str(getattr(raw_record, "provider_record_id", "") or "") or None,
                ingress_path=ingress_path or (f"provider_runtime:{acquisition_mode}" if acquisition_mode else "provider_runtime"),
            ),
            subjects=subjects,
            temporal=TemporalBlock(
                source_time=str(getattr(raw_record, "provider_occurred_at", "") or "") or None,
                clock_source="provider",
            ),
            payload=dict(normalized.get("data") or {}) or None,
            provenance=ProvenanceBlock(
                credential_class="VERIFIED_WEBHOOK" if is_webhook else self.credential_class,
                adapter=self.adapter_id,
                adapter_version=self.adapter_version,
            ),
            lineage=LineageBlock(
                raw_record_ref=str(normalized.get("source_record_id") or "") or None,
                normalization_version=str(normalized.get("normalizer_version") or "") or None,
            ),
            rights=rights,
        )


__all__ = ["ProviderIngressAdapter", "RIGHTS_ADMISSION_METADATA_KEY"]
