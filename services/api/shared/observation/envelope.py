"""UniversalObservationEnvelope — Envelope B, the canonical server-side
observation model (SDK + Universal Ingestion Alignment blueprint Point 2 /
Invariant #1 "one observation model after adapters").

Every ingress adapter (SDK, webhook, connector, feed, import, harness,
replay — WS-B) builds this envelope; the universal ingestion gateway validates
it before the durable Bronze write. This module is the **runtime model**;
``packages/shared/contracts/observation-envelope-registry.json`` is the
canonical field registry it is bound to, and ``packages/shared/
observation-envelope.ts`` is the passive TS contract mirror. All three are
held in lock-step by ``tests/contracts/test_observation_envelope_parity.py``.

Scope boundary (deliberate): WS-A5 ships the *model*, not the enforcement.
Structural validation (types, curated vocabularies when a value is present) is
performed here so a mis-built envelope fails loudly; source-trust evaluation,
consent/privacy policy, idempotency and sequencing are the WS-B gateway's job
and are intentionally absent.

Naming reconciliations from the blueprint are recorded in the registry's
``naming_resolutions``; this model uses the §3 Envelope-B block names.
``source_type``/``identifier_type``/``trust_class``/``credential_class`` are
checked against the curated vocabularies declared there. ``temporal.source_time``
carries the *raw source clock claim* verbatim (string, never reinterpreted) —
the same evidence-preservation rule as ``EventTemporalEnvelope``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, field_validator

# --- Curated vocabularies (mirrors of observation-envelope-registry.json) -----

SOURCE_TYPES: tuple[str, ...] = (
    "sdk",
    "webhook",
    "connector",
    "feed",
    "import",
    "harness",
    "replay",
)

IDENTIFIER_TYPES: tuple[str, ...] = (
    "anonymous_id",
    "user_id",
    "account_id",
    "email_hash",
    "phone_hash",
    "wallet_address",
    "device_id",
    "session_id",
    "organization_user_id",
    "agent_id",
    "service_account_id",
    "external_customer_id",
    "provider_account_id",
)

CREDENTIAL_CLASSES: tuple[str, ...] = (
    "PUBLIC_CLIENT",
    "TRUSTED_CLIENT",
    "TENANT_SERVER",
    "VERIFIED_WEBHOOK",
    "MANAGED_CONNECTOR",
    "AETHER_INTERNAL",
    "OPERATOR_REPLAY",
)

# Field-authority trust classes, rank-ordered OBSERVED..OPERATOR_ASSERTED.
# Owned by event-registry.json#trustClasses; the parity test asserts this
# frozenset equals generated_registry.TRUST_CLASS_ORDER so it can never drift.
TRUST_CLASSES: frozenset[str] = frozenset(
    {
        "OBSERVED",
        "SOURCE_ASSERTED",
        "SOURCE_REFERENCE",
        "CLIENT_HINT",
        "SERVER_STAMPED",
        "RESOLVED",
        "DERIVED",
        "INFERRED",
        "PREDICTED",
        "OPERATOR_ASSERTED",
    }
)


def _require_member(value: str, allowed: frozenset[str] | tuple[str, ...], label: str) -> str:
    if value not in allowed:
        raise ValueError(f"{label} {value!r} not in curated vocabulary: {sorted(allowed)}")
    return value


class ObservationBlock(BaseModel):
    """Envelope identity + occurrence/receipt/ingest instants + schema version."""

    model_config = ConfigDict(extra="forbid")

    observation_id: str
    observation_type: str
    family: Optional[str] = None
    occurred_at: datetime
    received_at: datetime
    ingested_at: datetime
    schema_version: str


class TenancyBlock(BaseModel):
    """Tenant provenance (Invariant #6). Every observation names its tenant."""

    model_config = ConfigDict(extra="forbid")

    tenant_id: str
    deployment_id: Optional[str] = None
    environment: Optional[str] = None


class SourceBlock(BaseModel):
    """Ingress source provenance (Invariant #7)."""

    model_config = ConfigDict(extra="forbid")

    source_type: str
    source_provider: Optional[str] = None
    source_instance: Optional[str] = None
    source_native_id: Optional[str] = None
    ingress_path: Optional[str] = None

    @field_validator("source_type")
    @classmethod
    def _source_type_known(cls, v: str) -> str:
        return _require_member(v, SOURCE_TYPES, "source_type")


class SubjectRef(BaseModel):
    """One entity an observation is about: identifier + role + trust class.

    ``trust_class`` is a field-authority class (event-registry trustClasses);
    the SDK may assert at most ``CLIENT_HINT`` — the WS-A3 SDK boundary. The
    SDK adapter derives it from ``EVENT_FIELD_TRUST`` when available.
    """

    model_config = ConfigDict(extra="forbid")

    identifier_type: str
    identifier_value: str
    actor_role: Optional[str] = None
    trust_class: str = "OBSERVED"
    namespace: Optional[str] = None
    verification_hint: Optional[str] = None
    source: Optional[str] = None

    @field_validator("identifier_type")
    @classmethod
    def _identifier_type_known(cls, v: str) -> str:
        return _require_member(v, IDENTIFIER_TYPES, "identifier_type")

    @field_validator("trust_class")
    @classmethod
    def _trust_class_known(cls, v: str) -> str:
        return _require_member(v, TRUST_CLASSES, "trust_class")


class TemporalBlock(BaseModel):
    """Source-clock evidence (Invariant #11) — never discarded.

    ``source_time`` is the raw source clock claim (string) preserved verbatim;
    the canonical instants live on :class:`ObservationBlock`.
    """

    model_config = ConfigDict(extra="forbid")

    source_time: Optional[str] = None
    timezone: Optional[str] = None
    utc_offset: Optional[str] = None
    clock_source: Optional[str] = None
    sequence: Optional[str] = None
    temporal_quality: Optional[str] = None


class CorrelationBlock(BaseModel):
    """Correlation context (Invariant #12). Canonical correlation is additive;
    source-native correlation values are never overwritten during normalization."""

    model_config = ConfigDict(extra="forbid")

    correlation_id: Optional[str] = None
    causation_id: Optional[str] = None
    trace_id: Optional[str] = None
    span_id: Optional[str] = None
    parent_observation_id: Optional[str] = None


class PrivacyBlock(BaseModel):
    """Consent + privacy-policy evidence (Invariant #9). Stamped by the gateway;
    never trusted from the source. ``purposes`` reference consent-registry ids."""

    model_config = ConfigDict(extra="forbid")

    consent_snapshot: Optional[str] = None
    purposes: list[str] = []
    GPC: Optional[bool] = None
    DNT: Optional[bool] = None
    policy_decisions: list[str] = []


class ProvenanceBlock(BaseModel):
    """Ingress trust evidence: credential class + signature disposition + the
    adapter that built this envelope."""

    model_config = ConfigDict(extra="forbid")

    credential_class: Optional[str] = None
    signature_status: Optional[str] = None
    adapter: Optional[str] = None
    adapter_version: Optional[str] = None
    source_trust: Optional[str] = None

    @field_validator("credential_class")
    @classmethod
    def _credential_class_known(cls, v: str) -> str:
        return _require_member(v, CREDENTIAL_CLASSES, "credential_class")


class QualityBlock(BaseModel):
    """Validation/quality disposition assigned by the gateway (Invariant #10).
    Degraded dispositions are never collapsed into ``accepted``."""

    model_config = ConfigDict(extra="forbid")

    completeness: Optional[str] = None
    freshness: Optional[str] = None
    sequencing_state: Optional[str] = None
    validation_state: Optional[str] = None


class LineageBlock(BaseModel):
    """Evidence lineage back to the durable raw record (Invariant #14)."""

    model_config = ConfigDict(extra="forbid")

    raw_record_ref: Optional[str] = None
    normalization_version: Optional[str] = None
    validation_version: Optional[str] = None


class UniversalObservationEnvelope(BaseModel):
    """Canonical observation after adapters, before the gateway.

    The full blueprint §3 tree. ``acquisition``/``application``/``surface``/
    ``device``/``network``/``payload`` are passthrough sub-envelopes of the
    committed A-side vocabulary (EventContext / AcquisitionEvidence) — their
    fields are not re-declared here (see the registry's ``passthrough_blocks``).
    """

    model_config = ConfigDict(extra="forbid")

    observation: ObservationBlock
    tenancy: TenancyBlock
    source: SourceBlock
    subjects: list[SubjectRef] = []

    temporal: Optional[TemporalBlock] = None
    correlation: Optional[CorrelationBlock] = None

    # Passthrough A-side sub-envelopes (registry passthrough_blocks).
    acquisition: Optional[dict[str, Any]] = None
    application: Optional[dict[str, Any]] = None
    surface: Optional[dict[str, Any]] = None
    device: Optional[dict[str, Any]] = None
    network: Optional[dict[str, Any]] = None
    payload: Optional[dict[str, Any]] = None

    privacy: Optional[PrivacyBlock] = None
    provenance: Optional[ProvenanceBlock] = None
    quality: Optional[QualityBlock] = None
    lineage: Optional[LineageBlock] = None

    def to_bronze_additive(self) -> dict:
        """JSON-safe additive persistence dict (excludes unset optionals)."""
        return self.model_dump(mode="json", exclude_none=True)
