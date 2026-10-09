"""Provider-neutral event envelopes and the raw-read batch.

The Universal Provider Runtime normalizes every provider signal into one of two
envelopes:

* :class:`RawProviderRecord` — the *provider-shaped* unit an adapter returns
  (poll rows, webhook deliveries, report rows, stream records). It preserves the
  provider's own ids, timestamps, and payload so later stages can audit lineage.
* :class:`AetherEvent` — the *normalized* unit downstream consumers receive. Its
  ``event_type`` is provider-NEUTRAL (``commerce.order.created``); all provider
  specifics live in ``context``.

Both envelopes carry an :attr:`~RawProviderRecord.idempotency_key` so ingestion
can dedupe exactly once per ``(tenant, provider, provider-record)`` or
``(tenant, event_type, source-record)`` pair. :class:`ReadBatch` is the payload
type a pull/report adapter returns (paged, cursor-addressable).

``checksum`` on :class:`RawProviderRecord` is the sha256 of the canonical JSON
form of ``payload`` (``json.dumps(..., sort_keys=True, separators=(",", ":"))``)
so the provider record is tamper-evident from the moment an adapter produces it.
:func:`verify_checksum` checks a stored checksum against the payload; a checksum
that is ``""`` (never computed) or stale (payload mutated after construction)
verifies as ``False`` — unverified is never treated as verified.

Determinism contract for normalization
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
``AetherEvent.event_id`` DEFAULTS to a random ``uuid4().hex``. That default is
fine for envelope-level generation, but a normalizer (see :mod:`normalization`)
MUST override ``event_id`` with a value derived deterministically from its
:class:`RawProviderRecord` (e.g. the record's
:attr:`~RawProviderRecord.idempotency_key`) so re-normalizing the same record
yields byte-identical output for replay/debug. The random default must never be
trusted for replay-stable output.

Tenant safety
~~~~~~~~~~~~~
``RawProviderRecord.tenant_id`` defaults to ``""`` (the seam mandates the
default). :attr:`~RawProviderRecord.idempotency_key` is scoped by ``tenant_id``,
so ingestion MUST populate ``tenant_id`` before dedupe — otherwise records from
different tenants that share a ``provider_record_id`` would collide on the same
key.
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_serializer, model_validator

from shared.integration_contracts.source_objects import event_revision_id_for_parts

_GENERATED_UUID4_EVENT_ID_RE = re.compile(r"^[0-9a-f]{12}4[0-9a-f]{3}[89ab][0-9a-f]{15}$")


def _utc_now_iso() -> str:
    """Current UTC time in ISO-8601 form (server-now for the envelopes)."""
    return datetime.now(timezone.utc).isoformat()


def compute_checksum(payload: dict[str, Any]) -> str:
    """sha256 of the canonical JSON form of ``payload``.

    Canonical form is stable under key order (``sort_keys=True``) and uses
    compact separators, so structurally-equal payloads always checksum equal.
    ``payload`` must be JSON-serializable; ``json.dumps`` raises ``TypeError``
    for non-serializable values (e.g. ``datetime``, ``Decimal``).
    """
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def verify_checksum(record: RawProviderRecord) -> bool:
    """True iff ``record.checksum`` matches the canonical checksum of its payload.

    An empty ``checksum`` (never computed) or a stale one (the ``payload`` dict
    mutated after construction) verifies as ``False`` — unverified is never
    treated as verified.
    """
    return record.checksum != "" and record.checksum == compute_checksum(record.payload)


class ReadBatch(BaseModel):
    """A page of raw provider records plus cursor state for the next read."""

    model_config = ConfigDict(extra="forbid")

    records: list["RawProviderRecord"] = Field(default_factory=list)
    next_cursor: Optional[str] = None
    has_more: bool = False


class RawProviderRecord(BaseModel):
    """One provider-shaped unit produced by an acquisition adapter.

    ``payload`` is the provider's own data, untouched. ``checksum`` is the
    sha256 of the canonical JSON form of ``payload`` (see :func:`compute_checksum`);
    :func:`make_raw_record` fills it automatically.
    """

    model_config = ConfigDict(extra="forbid")

    record_id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    provider_identity: str  # "family.product.capability"
    tenant_id: str = ""
    connection_id: str = ""
    account_id: str = ""
    provider_record_type: str = ""  # e.g. "order"
    provider_record_id: str  # provider's own id (dedup input)
    # Additive revision identity for mutable provider objects.  V1 producers
    # leave these empty and retain their historical Bronze keys.
    source_account_key: Optional[str] = None
    source_account_realm: Optional[Literal["live", "test"]] = None
    source_object_type: Optional[str] = None
    source_object_id: Optional[str] = None
    source_revision_key: Optional[str] = None
    stream_id: Optional[str] = None
    acquisition_mode: str = "poll"  # sdk|webhook|poll|report|stream|import|reconciliation
    observed_at: str = ""  # ISO-8601 UTC; "" when unknown, make_raw_record fills server-now
    provider_occurred_at: Optional[str] = None
    payload_schema_version: Optional[str] = None
    cursor: Optional[str] = None
    webhook_delivery_id: Optional[str] = None
    checksum: str = ""  # sha256 of canonical JSON payload
    payload: dict[str, Any]
    metadata: dict[str, Any] = Field(default_factory=dict)
    schema_version: str = "1"

    @model_validator(mode="after")
    def _complete_source_revision(self) -> "RawProviderRecord":
        fields = (
            self.source_account_key,
            self.source_account_realm,
            self.source_object_type,
            self.source_object_id,
            self.source_revision_key,
        )
        if any(value is not None for value in fields):
            if not self.tenant_id or not all(value and value.strip() for value in fields):
                raise ValueError(
                    "source revision requires tenant, source account, live/test realm, object type, "
                    "object id, and revision key"
                )
            if not self.source_revision_key.startswith(("snapshot:", "event:")):
                raise ValueError("source revision key must start with snapshot: or event:")
            if self.schema_version != "2":
                raise ValueError("source revision records require envelope schema_version 2")
        elif self.schema_version == "2":
            raise ValueError("envelope schema_version 2 requires source revision fields")
        return self

    @property
    def bronze_provider_record_id(self) -> str:
        """Bounded Bronze key for one source revision, with legacy v1 fallback.

        Native ``provider_record_id`` remains separate in the envelope.  The
        revision key intentionally excludes acquisition mode and connection ID,
        so a verified poll and webhook for one state can converge.
        """
        if self.source_revision_key is None:
            return self.provider_record_id
        material = json.dumps(
            [
                self.source_account_key,
                self.source_account_realm,
                self.source_object_type,
                self.source_object_id,
                self.source_revision_key,
            ],
            ensure_ascii=False,
            separators=(",", ":"),
        )
        return "source-revision-v2:" + hashlib.sha256(material.encode("utf-8")).hexdigest()

    @property
    def idempotency_key(self) -> str:
        """Dedup key: sha256(tenant|provider_identity|provider_record_id|version)."""
        material = (
            f"{self.tenant_id}:{self.provider_identity}:"
            f"{self.bronze_provider_record_id}:{self.schema_version}"
        )
        return hashlib.sha256(material.encode("utf-8")).hexdigest()[:32]


class AetherEvent(BaseModel):
    """Provider-NEUTRAL event handed to downstream consumers.

    ``event_type`` uses the canonical ``domain.resource.action`` vocabulary
    (e.g. ``commerce.order.created``); ``provider`` and ``provider_identity``
    retain lineage back to the source provider. Provider-specific details go in
    ``context`` (acquisition_mode, connection_id, raw provider event type, ...).

    Determinism: ``event_id`` defaults to a random ``uuid4().hex``. A normalizer
    MUST supply a deterministic ``event_id`` derived from its source record
    (e.g. ``RawProviderRecord.idempotency_key``) so re-normalizing the same
    record yields byte-identical output; never rely on the random default for
    replay-stable output.
    """

    model_config = ConfigDict(extra="forbid")

    event_id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    # Schema v2 uses ``event_id`` as the immutable interpretation/revision ID.
    # The stable logical fact identity remains separate so changed mappings or
    # normalizers can append a revision without changing what fact they refer to.
    logical_event_id: Optional[str] = None
    event_revision_id: Optional[str] = None
    mapping_version: Optional[str] = None
    normalizer_version: Optional[str] = None
    source_revision_key: Optional[str] = None
    canonical_payload_digest: Optional[str] = None
    event_type: str  # provider-NEUTRAL: commerce.order.created
    event_family: str  # "commerce" | "comms" | ...
    tenant_id: str
    provider: str  # provider family ("shopify")
    provider_identity: str  # full "family.product.capability"
    source_record_id: str  # lineage -> RawProviderRecord.record_id
    occurred_at: str  # ISO-8601 UTC
    observed_at: str
    account_id: str = ""
    subject_id: Optional[str] = None
    actor_id: Optional[str] = None
    data: dict[str, Any]
    context: dict[str, Any] = Field(
        default_factory=dict
    )  # acquisition_mode, connection_id, raw provider event type, ...
    schema_version: str = "1"

    @model_validator(mode="after")
    def _validate_event_revision(self) -> "AetherEvent":
        extension = (
            self.logical_event_id,
            self.event_revision_id,
            self.mapping_version,
            self.normalizer_version,
            self.source_revision_key,
            self.canonical_payload_digest,
        )
        if self.schema_version != "2":
            if any(value is not None for value in extension):
                raise ValueError("event revision fields require schema_version 2")
            return self

        if not all(value and value.strip() for value in extension):
            raise ValueError("schema_version 2 requires complete event revision fields")
        if self.event_id != self.event_revision_id:
            raise ValueError("schema_version 2 event_id must equal event_revision_id")
        if not re.fullmatch(r"erev_v1_[0-9a-f]{64}", self.event_id):
            raise ValueError("schema_version 2 event_id must be an erev_v1 SHA-256 ID")
        if not re.fullmatch(r"[0-9a-f]{64}", self.canonical_payload_digest or ""):
            raise ValueError("canonical_payload_digest must be a lowercase SHA-256 hex digest")
        expected = event_revision_id_for_parts(
            logical_event_id=self.logical_event_id or "",
            event_schema_version=self.schema_version,
            mapping_version=self.mapping_version or "",
            normalizer_version=self.normalizer_version or "",
            canonical_payload_digest=self.canonical_payload_digest or "",
        )
        if self.event_revision_id != expected:
            raise ValueError("event_revision_id does not match the immutable interpretation tuple")
        return self

    @property
    def event_id_needs_stable_fallback(self) -> bool:
        """Whether ``event_id`` is the model's generated random default.

        UUID4-shaped IDs are also treated as generated defaults after a
        serialization boundary, when ``model_fields_set`` cannot distinguish
        the model default from an explicitly supplied value.
        """
        return "event_id" not in self.model_fields_set or bool(
            _GENERATED_UUID4_EVENT_ID_RE.fullmatch(self.event_id)
        )

    @model_serializer(mode="wrap")
    def _serialize_event(self, handler):
        """Keep the serialized v1 envelope byte-shape unchanged."""
        payload = handler(self)
        if self.schema_version != "2":
            for key in (
                "logical_event_id",
                "event_revision_id",
                "mapping_version",
                "normalizer_version",
                "source_revision_key",
                "canonical_payload_digest",
            ):
                payload.pop(key, None)
        return payload

    @property
    def idempotency_key(self) -> str:
        """Return the historical v1 or revision-aware v2 dedup key."""
        if self.schema_version == "2":
            material = f"{self.tenant_id}:{self.event_id}:{self.schema_version}"
            return hashlib.sha256(material.encode("utf-8")).hexdigest()[:32]
        material = (
            f"{self.tenant_id}:{self.event_type}:{self.source_record_id}:{self.schema_version}"
        )
        return hashlib.sha256(material.encode("utf-8")).hexdigest()[:32]


# ── Convenience constructors ───────────────────────────────────────────────


def make_raw_record(
    *,
    provider_identity: str,
    provider_record_id: str,
    payload: dict[str, Any],
    tenant_id: str = "",
    connection_id: str = "",
    account_id: str = "",
    provider_record_type: str = "",
    source_account_key: Optional[str] = None,
    source_account_realm: Optional[Literal["live", "test"]] = None,
    source_object_type: Optional[str] = None,
    source_object_id: Optional[str] = None,
    source_revision_key: Optional[str] = None,
    stream_id: Optional[str] = None,
    acquisition_mode: str = "poll",
    observed_at: Optional[str] = None,
    provider_occurred_at: Optional[str] = None,
    payload_schema_version: Optional[str] = None,
    cursor: Optional[str] = None,
    webhook_delivery_id: Optional[str] = None,
    checksum: Optional[str] = None,
    metadata: Optional[dict[str, Any]] = None,
    schema_version: str = "1",
) -> RawProviderRecord:
    """Build a :class:`RawProviderRecord`, filling the derived fields.

    ``observed_at`` defaults to the current UTC time (server now); ``checksum``
    is computed from ``payload`` when not supplied. Nothing here touches
    randomness/time beyond those two derived defaults.
    """
    return RawProviderRecord(
        provider_identity=provider_identity,
        tenant_id=tenant_id,
        connection_id=connection_id,
        account_id=account_id,
        provider_record_type=provider_record_type,
        provider_record_id=provider_record_id,
        source_account_key=source_account_key,
        source_account_realm=source_account_realm,
        source_object_type=source_object_type,
        source_object_id=source_object_id,
        source_revision_key=source_revision_key,
        stream_id=stream_id,
        acquisition_mode=acquisition_mode,
        observed_at=observed_at if observed_at is not None else _utc_now_iso(),
        provider_occurred_at=provider_occurred_at,
        payload_schema_version=payload_schema_version,
        cursor=cursor,
        webhook_delivery_id=webhook_delivery_id,
        checksum=checksum if checksum is not None else compute_checksum(payload),
        payload=payload,
        metadata=metadata or {},
        schema_version=schema_version,
    )


def deterministic_v1_event_id_for_source_record(
    *,
    tenant_id: str,
    provider_identity: str,
    event_type: str,
    source_record_id: str,
) -> str:
    """Derive a replay-stable v1 event identity from its persisted raw record.

    The versioned, JSON-encoded tuple avoids delimiter ambiguity. The
    ``source_record_id`` is assigned by raw persistence before normalization,
    so repeating normalization of that Bronze record produces one event ID.
    """
    parts = (tenant_id, provider_identity, event_type, source_record_id)
    if any(not value or not value.strip() for value in parts):
        raise ValueError("v1 event identity requires tenant, provider, type, and raw source record")
    material = json.dumps(
        ["1", *parts],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    digest = hashlib.sha256(material.encode("utf-8")).hexdigest()
    return f"pevt_v1_{digest}"


def make_aether_event(
    *,
    provider_identity: str,
    event_type: str,
    event_family: str,
    tenant_id: str,
    source_record_id: str,
    data: dict[str, Any],
    provider: Optional[str] = None,
    occurred_at: Optional[str] = None,
    observed_at: Optional[str] = None,
    account_id: str = "",
    subject_id: Optional[str] = None,
    actor_id: Optional[str] = None,
    context: Optional[dict[str, Any]] = None,
    schema_version: str = "1",
    event_id: Optional[str] = None,
    logical_event_id: Optional[str] = None,
    event_revision_id: Optional[str] = None,
    mapping_version: Optional[str] = None,
    normalizer_version: Optional[str] = None,
    source_revision_key: Optional[str] = None,
    canonical_payload_digest: Optional[str] = None,
) -> AetherEvent:
    """Build an :class:`AetherEvent`, filling derived fields.

    ``provider`` defaults to the family segment of ``provider_identity``;
    ``occurred_at``/``observed_at`` default to the current UTC time. For schema
    v2, the canonical digest and immutable event revision ID are derived when
    the logical ID and all version/source fields are provided. Schema v1 keeps
    its historical random event ID and serialized shape.
    """
    now = _utc_now_iso()
    if schema_version == "2":
        if canonical_payload_digest is None:
            canonical_payload_digest = compute_checksum(
                {"event_type": event_type, "event_family": event_family, "data": data}
            )
        if (
            logical_event_id is not None
            and mapping_version is not None
            and normalizer_version is not None
            and canonical_payload_digest is not None
        ):
            derived_revision_id = event_revision_id_for_parts(
                logical_event_id=logical_event_id,
                event_schema_version=schema_version,
                mapping_version=mapping_version,
                normalizer_version=normalizer_version,
                canonical_payload_digest=canonical_payload_digest,
            )
            if event_revision_id is None:
                event_revision_id = derived_revision_id
            if event_id is None:
                event_id = event_revision_id

    values = dict(
        event_type=event_type,
        event_family=event_family,
        tenant_id=tenant_id,
        provider=provider if provider is not None else provider_identity.split(".")[0],
        provider_identity=provider_identity,
        source_record_id=source_record_id,
        occurred_at=occurred_at if occurred_at is not None else now,
        observed_at=observed_at if observed_at is not None else now,
        account_id=account_id,
        subject_id=subject_id,
        actor_id=actor_id,
        data=data,
        context=context or {},
        schema_version=schema_version,
        logical_event_id=logical_event_id,
        event_revision_id=event_revision_id,
        mapping_version=mapping_version,
        normalizer_version=normalizer_version,
        source_revision_key=source_revision_key,
        canonical_payload_digest=canonical_payload_digest,
    )
    if event_id is not None:
        values["event_id"] = event_id
    return AetherEvent(**values)


__all__ = [
    "AetherEvent",
    "ReadBatch",
    "RawProviderRecord",
    "compute_checksum",
    "deterministic_v1_event_id_for_source_record",
    "make_aether_event",
    "make_raw_record",
    "verify_checksum",
]
