"""Tenant-scoped non-identity provider objects and logical event identity.

These contracts identify provider-owned objects such as orders and payments.
People, customer accounts, agents, devices, and other identities must use the
existing SourceIdentityRegistry and resolver instead. ``source_account_key``
is the provider's immutable account ID, not a mutable domain or connection ID;
the runtime verifies it against a selected, live-discovered provider account.

The logical event helper is pure. It does not issue canonical object IDs,
publish events, or certify an adapter's revision extraction. A publisher must
persist the full logical tuple and enforce uniqueness before emitting facts.
"""

from __future__ import annotations

import base64
import hashlib
import re
import unicodedata
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from shared.integration_contracts.identity import parse_identity


# This curated vocabulary is deliberately limited to non-identity objects.
# Adding a kind requires a review of whether it belongs in identity resolution.
NON_IDENTITY_OBJECT_TYPES = frozenset(
    {
        "ad",
        "ad_group",
        "campaign",
        "cart",
        "catalog_item",
        "charge",
        "checkout",
        "conversion",
        "creative",
        "credit_note",
        "dispute",
        "event",
        "fulfillment",
        "inventory_item",
        "invoice",
        "issue",
        "ledger_entry",
        "message",
        "order",
        "order_line",
        "payment",
        "payout",
        "price",
        "product",
        "project",
        "receipt",
        "refund",
        "report",
        "return",
        "settlement",
        "shipment",
        "subscription",
        "ticket",
        "transaction",
        "transfer",
        "variant",
        "webhook_event",
    }
)
LOGICAL_EVENT_ID_VERSION = "1"
EVENT_REVISION_ID_VERSION = "1"
_SEMANTIC_SLOT_RE = re.compile(r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+$")
_PROVIDER_FAMILY_RE = re.compile(r"^[a-z][a-z0-9_]*$")
_LOGICAL_EVENT_ID_RE = re.compile(r"^cevt_v1_[a-z2-7]{32}$")
_SHA256_HEX_RE = re.compile(r"^[0-9a-f]{64}$")


def _canonical_text(value: str) -> str:
    return unicodedata.normalize("NFC", value)


def _nonblank(value: str) -> str:
    if not value.strip():
        raise ValueError("source reference values must be nonblank")
    return _canonical_text(value)


class SourceAccountRef(BaseModel):
    """Verified source-account scope used by non-identity object mappings.

    ``account_verification_ref`` names a persisted ProviderAccountRecord. The
    repository checks its provider external ID, selected connection, tenant,
    capability, and realm before every read or write.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    tenant_id: str = Field(min_length=1)
    provider_identity: str = Field(min_length=1)
    source_account_key: str = Field(min_length=1)
    source_account_realm: Literal["live", "test"]
    account_verification_ref: str = Field(min_length=1)

    @field_validator("tenant_id", "source_account_key", "account_verification_ref")
    @classmethod
    def _scope_text(cls, value: str) -> str:
        return _nonblank(value)

    @field_validator("provider_identity")
    @classmethod
    def _valid_identity(cls, value: str) -> str:
        parse_identity(value)
        return value

    @property
    def provider_family(self) -> str:
        return str(parse_identity(self.provider_identity).family)

    @property
    def logical_account_key(self) -> str:
        """The realm is part of account identity across sandbox and live data."""
        return f"{self.source_account_realm}:{self.source_account_key}"


class SourceObjectRef(SourceAccountRef):
    """One provider-owned non-identity object within a verified account."""

    source_object_type: str
    source_object_id: str = Field(min_length=1)

    @field_validator("source_object_type")
    @classmethod
    def _nonidentity_kind(cls, value: str) -> str:
        if value not in NON_IDENTITY_OBJECT_TYPES:
            raise ValueError("source object type is not a reviewed non-identity kind")
        return value

    @field_validator("source_object_id")
    @classmethod
    def _object_id(cls, value: str) -> str:
        return _nonblank(value)

    @property
    def account(self) -> SourceAccountRef:
        return SourceAccountRef.model_validate(
            self.model_dump(include=set(SourceAccountRef.model_fields))
        )


def _length_prefixed(parts: tuple[str, ...]) -> bytes:
    """NFC UTF-8 with 32-bit big-endian lengths; no delimiter ambiguity."""
    encoded = bytearray()
    for part in parts:
        raw = _canonical_text(part).encode("utf-8")
        if len(raw) > 0xFFFFFFFF:
            raise ValueError("logical event identity component is too long")
        encoded.extend(len(raw).to_bytes(4, "big"))
        encoded.extend(raw)
    return bytes(encoded)


def _logical_event_parts(
    *,
    tenant_id: str,
    provider_family: str,
    source_account_realm: Literal["live", "test"],
    source_account_key: str,
    source_object_type: str,
    source_object_id: str,
    source_revision_key: str,
    semantic_slot: str,
) -> tuple[str, ...]:
    """Validate and encode the provider-neutral identity tuple, without I/O."""
    if not _PROVIDER_FAMILY_RE.fullmatch(provider_family):
        raise ValueError("provider_family must be one canonical identity segment")
    if source_account_realm not in ("live", "test"):
        raise ValueError("source_account_realm must be live or test")
    if source_object_type not in NON_IDENTITY_OBJECT_TYPES:
        raise ValueError("source object type is not a reviewed non-identity kind")
    if not _SEMANTIC_SLOT_RE.fullmatch(semantic_slot):
        raise ValueError("semantic_slot must be a dotted provider-neutral token")
    return (
        _nonblank(tenant_id),
        provider_family,
        f"{source_account_realm}:{_nonblank(source_account_key)}",
        source_object_type,
        _nonblank(source_object_id),
        _nonblank(source_revision_key),
        semantic_slot,
    )


def logical_event_id_for_source_parts(
    *,
    tenant_id: str,
    provider_family: str,
    source_account_realm: Literal["live", "test"],
    source_account_key: str,
    source_object_type: str,
    source_object_id: str,
    source_revision_key: str,
    semantic_slot: str,
) -> str:
    """Pure v1 ID encoder for an already-bound provider source/revision tuple.

    This helper does not verify account ownership, issue object IDs, or admit
    a graph write. The repository performs account verification; callers of
    this helper must supply the bound tenant, realm, and immutable account ID
    obtained upstream, not values copied from an untrusted payload.
    """
    parts = _logical_event_parts(
        tenant_id=tenant_id,
        provider_family=provider_family,
        source_account_realm=source_account_realm,
        source_account_key=source_account_key,
        source_object_type=source_object_type,
        source_object_id=source_object_id,
        source_revision_key=source_revision_key,
        semantic_slot=semantic_slot,
    )
    digest = hashlib.sha256(_length_prefixed(parts)).digest()
    return "cevt_v1_" + base64.b32encode(digest).decode("ascii").lower()[:32]


def event_revision_id_for_parts(
    *,
    logical_event_id: str,
    event_schema_version: str,
    mapping_version: str,
    normalizer_version: str,
    canonical_payload_digest: str,
) -> str:
    """Pure identity for one immutable interpretation of a logical fact.

    ``logical_event_id`` stays stable when an interpretation changes. The
    schema, mapping, normalizer and canonical payload digest distinguish each
    accepted interpretation, so durable Bronze/outbox writers can use the
    returned ID as their idempotency key without collapsing revisions.
    """
    if not _LOGICAL_EVENT_ID_RE.fullmatch(logical_event_id):
        raise ValueError("logical_event_id must be a v1 logical provider fact ID")
    if not _SHA256_HEX_RE.fullmatch(canonical_payload_digest):
        raise ValueError("canonical_payload_digest must be a lowercase SHA-256 hex digest")
    parts = (
        _nonblank(logical_event_id),
        _nonblank(event_schema_version),
        _nonblank(mapping_version),
        _nonblank(normalizer_version),
        canonical_payload_digest,
    )
    digest = hashlib.sha256(_length_prefixed(parts)).hexdigest()
    return f"erev_v{EVENT_REVISION_ID_VERSION}_{digest}"


class LogicalEventKey(BaseModel):
    """Stable source-revision and semantic-slot identity for one provider fact."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["1"] = LOGICAL_EVENT_ID_VERSION
    source: SourceObjectRef
    source_revision_key: str = Field(min_length=1)
    semantic_slot: str = Field(min_length=1)

    @field_validator("source_revision_key")
    @classmethod
    def _revision(cls, value: str) -> str:
        return _nonblank(value)

    @field_validator("semantic_slot")
    @classmethod
    def _slot(cls, value: str) -> str:
        if not _SEMANTIC_SLOT_RE.fullmatch(value):
            raise ValueError("semantic_slot must be a dotted provider-neutral token")
        return value

    @property
    def tuple(self) -> tuple[str, ...]:
        source = self.source
        return _logical_event_parts(
            tenant_id=source.tenant_id,
            provider_family=source.provider_family,
            source_account_realm=source.source_account_realm,
            source_account_key=source.source_account_key,
            source_object_type=source.source_object_type,
            source_object_id=source.source_object_id,
            source_revision_key=self.source_revision_key,
            semantic_slot=self.semantic_slot,
        )

    @property
    def full_digest(self) -> str:
        return hashlib.sha256(_length_prefixed(self.tuple)).hexdigest()

    @property
    def event_id(self) -> str:
        source = self.source
        return logical_event_id_for_source_parts(
            tenant_id=source.tenant_id,
            provider_family=source.provider_family,
            source_account_realm=source.source_account_realm,
            source_account_key=source.source_account_key,
            source_object_type=source.source_object_type,
            source_object_id=source.source_object_id,
            source_revision_key=self.source_revision_key,
            semantic_slot=self.semantic_slot,
        )


__all__ = [
    "LOGICAL_EVENT_ID_VERSION",
    "EVENT_REVISION_ID_VERSION",
    "NON_IDENTITY_OBJECT_TYPES",
    "LogicalEventKey",
    "SourceAccountRef",
    "SourceObjectRef",
    "event_revision_id_for_parts",
    "logical_event_id_for_source_parts",
]
