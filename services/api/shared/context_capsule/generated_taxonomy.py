# DO NOT EDIT — generated from packages/shared/contracts/context-capsule-registry.json
# Run: python scripts/generate_platform_contracts.py
"""Generated context-capsule taxonomy (location sources/semantics, states, retention)."""

from __future__ import annotations

CONTEXT_CAPSULE_CONTRACT_VERSION = "1.0.0"

# Where a location observation came from.
LOCATION_SOURCES: tuple[str, ...] = (
    "server_network_ip",
    "device_coarse",
    "device_precise",
    "verified_venue",
    "tenant_supplied_venue",
    "qr_or_checkin",
    "shipping_address",
    "billing_address",
    "payment_instrument_country",
    "provider_reported",
    "organization_registered",
    "agent_execution_region",
    "server_execution_region",
    "imported_historical",
)

# What a location observation actually means.
LOCATION_SEMANTICS: tuple[str, ...] = (
    "network_egress",
    "likely_physical_presence",
    "verified_physical_presence",
    "declared_address",
    "commercial_destination",
    "billing_jurisdiction",
    "organization_location",
    "execution_region",
    "venue_association",
    "unknown",
)

# Coarsest-to-finest location precision classes.
LOCATION_PRECISION_CLASSES: tuple[str, ...] = (
    "country",
    "region",
    "city",
    "coarse_cell",
    "precise",
)

# Agreement state between concurrent location observations.
LOCATION_CONFLICT_STATES: tuple[str, ...] = ("none", "explainable", "unresolved", "contradictory")

# Interpreted context state for a subject at capsule time.
CONTEXT_STATES: tuple[str, ...] = (
    "normal_primary",
    "normal_secondary",
    "expected_recurring",
    "temporary_travel",
    "transient",
    "new_context",
    "returning_to_baseline",
    "commute_pattern",
    "network_egress_only",
    "possible_vpn",
    "possible_datacenter",
    "location_uncertain",
    "location_conflict",
    "improbable_transition",
    "not_applicable",
    "suppressed",
    "insufficient_evidence",
)

# Named retention classes (constraints in CONTEXT_RETENTION_CLASSES).
CONTEXT_RETENTION_CLASS_NAMES: tuple[str, ...] = (
    "coarse_location_observation",
    "context_capsule",
    "derived_baseline",
    "ephemeral_network_token",
    "precise_location_observation",
    "raw_ip",
)

# Retention constraint attached to each retention class.
CONTEXT_RETENTION_CLASSES: dict[str, dict[str, int | bool]] = {
    "coarse_location_observation": {"maxDays": 30},
    "context_capsule": {"inheritsStrictest": True},
    "derived_baseline": {"aggregateOnly": True},
    "ephemeral_network_token": {"maxHours": 24},
    "precise_location_observation": {"tenantPolicy": True},
    "raw_ip": {"maxHours": 0},
}

# Why a new context capsule superseded the previous one.
CAPSULE_TRANSITION_TYPES: tuple[str, ...] = (
    "session_start",
    "device_change",
    "network_change",
    "location_cluster_change",
    "campaign_change",
    "consent_change",
    "identity_resolved",
    "actor_change",
    "journey_handoff",
    "runtime_change",
    "precision_upgrade",
)

__all__ = [
    "CONTEXT_CAPSULE_CONTRACT_VERSION",
    "LOCATION_SOURCES",
    "LOCATION_SEMANTICS",
    "LOCATION_PRECISION_CLASSES",
    "LOCATION_CONFLICT_STATES",
    "CONTEXT_STATES",
    "CONTEXT_RETENTION_CLASS_NAMES",
    "CONTEXT_RETENTION_CLASSES",
    "CAPSULE_TRANSITION_TYPES",
]
