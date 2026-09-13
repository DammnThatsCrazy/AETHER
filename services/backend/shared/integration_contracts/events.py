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
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field


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

    @property
    def idempotency_key(self) -> str:
        """Dedup key: sha256(tenant|provider_identity|provider_record_id|version)."""
        material = (
            f"{self.tenant_id}:{self.provider_identity}:"
            f"{self.provider_record_id}:{self.schema_version}"
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

    @property
    def idempotency_key(self) -> str:
        """Dedup key: sha256(tenant|event_type|source_record_id|version)."""
        material = (
            f"{self.tenant_id}:{self.event_type}:"
            f"{self.source_record_id}:{self.schema_version}"
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
) -> AetherEvent:
    """Build an :class:`AetherEvent`, filling derived fields.

    ``provider`` defaults to the family segment of ``provider_identity``;
    ``occurred_at``/``observed_at`` default to the current UTC time.
    """
    now = _utc_now_iso()
    return AetherEvent(
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
    )


__all__ = [
    "AetherEvent",
    "ReadBatch",
    "RawProviderRecord",
    "compute_checksum",
    "make_aether_event",
    "make_raw_record",
    "verify_checksum",
]
