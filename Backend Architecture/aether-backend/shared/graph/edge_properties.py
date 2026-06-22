"""
Aether Shared — @aether/graph/edge_properties

Canonical required property set for graph edges and deterministic
idempotency key generation.

All graph mutation callers should use make_edge_idempotency_key() when
building edge property dicts, and REQUIRED_EDGE_PROPERTIES to know which
fields must be present before calling graph.add_edge().
"""

from __future__ import annotations

import hashlib


# ═══════════════════════════════════════════════════════════════════════════
# REQUIRED EDGE PROPERTY KEYS
# ═══════════════════════════════════════════════════════════════════════════

# These properties MUST appear in edge.properties for every graph write.
# The GraphWriteValidator enforces this in staging/production.
REQUIRED_EDGE_PROPERTIES: frozenset[str] = frozenset({
    "tenant_id",
    "idempotency_key",
    "actor_kind",         # "human" | "agent" | "system"
    "actor_id",
    "schema_version",
    "provenance",
    "valid_from",         # ISO-8601 timestamp
    "confidence",         # float in [0.0, 1.0] as string
})

# These properties are optional but recommended.
OPTIONAL_EDGE_PROPERTIES: frozenset[str] = frozenset({
    "correlation_id",
    "scope_hash",
    "consent_purpose",
    "source_event_id",
})

# Consent-bearing layers require consent_purpose.
CONSENT_REQUIRED_LAYERS: frozenset[str] = frozenset({"H2A", "A2H"})

# Silver-sourced mutations must include source_event_id for traceability.
# provenance_class="silver" triggers this enforcement in write_validator.
SILVER_SOURCED_REQUIRED: frozenset[str] = frozenset({*REQUIRED_EDGE_PROPERTIES, "source_event_id"})

VALID_ACTOR_KINDS: frozenset[str] = frozenset({"human", "agent", "system"})

SCHEMA_VERSION = "1"


# ═══════════════════════════════════════════════════════════════════════════
# IDEMPOTENCY KEY
# ═══════════════════════════════════════════════════════════════════════════

def make_edge_idempotency_key(
    tenant_id: str,
    edge_type: str,
    from_vertex_id: str,
    to_vertex_id: str,
    source_event_id: str = "",
) -> str:
    """Return a deterministic hex digest for the given edge tuple.

    Re-playing the same mutation (same tenant, type, endpoints, and optional
    source event) always produces the same key, making duplicate detection
    trivial at the write boundary.
    """
    raw = f"{tenant_id}:{edge_type}:{from_vertex_id}:{to_vertex_id}:{source_event_id}"
    return hashlib.sha256(raw.encode()).hexdigest()


def build_edge_properties(
    tenant_id: str,
    edge_type: str,
    from_vertex_id: str,
    to_vertex_id: str,
    actor_kind: str,
    actor_id: str,
    provenance: str,
    valid_from: str,
    confidence: float = 1.0,
    source_event_id: str = "",
    correlation_id: str = "",
    scope_hash: str = "",
    consent_purpose: str = "",
    provenance_class: str = "direct",
    schema_version: str = SCHEMA_VERSION,
    **extra: object,
) -> dict:
    """Return a property dict with all required and any extra properties set.

    provenance_class="silver" marks mutations originating from the Silver
    projector layer; write_validator enforces source_event_id for these.
    """
    props: dict = {
        "tenant_id": tenant_id,
        "idempotency_key": make_edge_idempotency_key(
            tenant_id, edge_type, from_vertex_id, to_vertex_id, source_event_id
        ),
        "actor_kind": actor_kind,
        "actor_id": actor_id,
        "schema_version": schema_version,
        "provenance": provenance,
        "valid_from": valid_from,
        "confidence": str(confidence),
        "provenance_class": provenance_class,
    }
    if source_event_id:
        props["source_event_id"] = source_event_id
    if correlation_id:
        props["correlation_id"] = correlation_id
    if scope_hash:
        props["scope_hash"] = scope_hash
    if consent_purpose:
        props["consent_purpose"] = consent_purpose
    props.update(extra)
    return props
