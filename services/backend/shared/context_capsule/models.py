"""Hand-authored context-capsule models.

TS twins: the ``LocationObservation`` and ``ContextCapsule`` interfaces in
``packages/shared/context-capsule.ts`` (emitted by
``scripts/generate_platform_contracts.py``). The taxonomy tuples live in
``shared.context_capsule.generated_taxonomy`` — regenerate, never edit.
Field-level parity and hash determinism are enforced by
``tests/contracts/test_context_capsule_parity.py``.

Privacy shape: there is deliberately NO raw-IP field and NO lat/lon pair —
the finest location grain in the contract is a coarse cell plus an accuracy
radius, and network facts are carried only as likelihood scores.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict


class LocationObservation(BaseModel):
    """One privacy-shaped location observation (no raw IP, no lat/lon)."""

    model_config = ConfigDict(extra="forbid")

    observation_id: str
    tenant_id: str
    subject_type: Optional[str] = None
    subject_id: Optional[str] = None
    session_id: Optional[str] = None
    source_event_id: Optional[str] = None
    source: str
    semantics: str
    precision_class: str
    country_code: Optional[str] = None
    region_code: Optional[str] = None
    city: Optional[str] = None
    coarse_cell: Optional[str] = None
    accuracy_radius_meters: Optional[float] = None
    confidence: Optional[float] = None
    observed_at: datetime
    received_at: Optional[datetime] = None
    provider: Optional[str] = None
    provider_database_version: Optional[str] = None
    vpn_likelihood: Optional[float] = None
    proxy_likelihood: Optional[float] = None
    tor_likelihood: Optional[float] = None
    datacenter_likelihood: Optional[float] = None
    consent_snapshot_id: Optional[str] = None
    retention_class: Optional[str] = None
    suppression_state: Optional[str] = None
    schema_version: Optional[str] = None


class ContextCapsule(BaseModel):
    """Versioned context capsule for a session slice.

    ``context_hash`` should carry :func:`capsule_hash` of the capsule so a
    logically-identical successor can be detected without field-by-field
    comparison.
    """

    model_config = ConfigDict(extra="forbid")

    capsule_id: str
    tenant_id: str
    session_id: Optional[str] = None
    capsule_version: int
    valid_from: datetime
    valid_to: Optional[datetime] = None
    actor_id: Optional[str] = None
    actor_kind: Optional[str] = None
    canonical_entity_id: Optional[str] = None
    identity_confidence: Optional[float] = None
    device_id: Optional[str] = None
    device_platform: Optional[str] = None
    device_class: Optional[str] = None
    app_version: Optional[str] = None
    sdk_name: Optional[str] = None
    sdk_version: Optional[str] = None
    network_observation_id: Optional[str] = None
    network_connection_type: Optional[str] = None
    network_asn_class: Optional[str] = None
    network_vpn_likelihood: Optional[float] = None
    network_proxy_likelihood: Optional[float] = None
    network_datacenter_likelihood: Optional[float] = None
    geo_resolved_location_id: Optional[str] = None
    geo_source_semantics: Optional[str] = None
    geo_country_code: Optional[str] = None
    geo_region_code: Optional[str] = None
    geo_city: Optional[str] = None
    geo_coarse_cell: Optional[str] = None
    geo_confidence: Optional[float] = None
    geo_conflict_state: Optional[str] = None
    campaign_id: Optional[str] = None
    campaign_source: Optional[str] = None
    campaign_medium: Optional[str] = None
    journey_id: Optional[str] = None
    journey_stage: Optional[str] = None
    prior_capsule_id: Optional[str] = None
    consent_snapshot_id: Optional[str] = None
    policy_jurisdiction: Optional[str] = None
    retention_class: Optional[str] = None
    suppression_state: Optional[str] = None
    source_event_id: Optional[str] = None
    schema_version: Optional[str] = None
    context_hash: Optional[str] = None


# Explicit allowlist of the fields that define capsule IDENTITY. Lineage and
# bookkeeping fields (capsule_id, capsule_version, valid_from/valid_to,
# prior_capsule_id, source_event_id, context_hash) are deliberately excluded:
# two capsules describing the same logical context hash identically even when
# minted at different times or from different source events.
CAPSULE_HASH_FIELDS: tuple[str, ...] = (
    "tenant_id",
    "session_id",
    "actor_id",
    "actor_kind",
    "device_id",
    "device_platform",
    "device_class",
    "network_connection_type",
    "network_asn_class",
    "network_vpn_likelihood",
    "network_proxy_likelihood",
    "network_datacenter_likelihood",
    "geo_resolved_location_id",
    "geo_source_semantics",
    "geo_country_code",
    "geo_region_code",
    "geo_city",
    "geo_coarse_cell",
    "geo_confidence",
    "geo_conflict_state",
    "campaign_id",
    "campaign_source",
    "campaign_medium",
    "journey_stage",
    "consent_snapshot_id",
    "schema_version",
)


def capsule_hash(capsule: ContextCapsule) -> str:
    """Deterministic sha256 over the capsule's identity fields.

    Canonical JSON (sorted keys, compact separators) over the explicit
    :data:`CAPSULE_HASH_FIELDS` allowlist — so the hash is independent of
    construction/key order and of every excluded lineage field.
    """
    payload = {field: getattr(capsule, field) for field in CAPSULE_HASH_FIELDS}
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


__all__ = [
    "LocationObservation",
    "ContextCapsule",
    "CAPSULE_HASH_FIELDS",
    "capsule_hash",
]
