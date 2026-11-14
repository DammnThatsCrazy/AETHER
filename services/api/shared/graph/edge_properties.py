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

from shared.agent_lineage.vocabulary import RELATIONSHIP_STATUSES


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
    # Agent-lineage edge semantics (see LINEAGE_EDGE_PROPERTIES below):
    "relationship_confidence", "authority_ref", "observed_at",
    "source_namespace", "relationship_status", "resolution_method",
    # Bitemporal valid-time (external truth window):
    "valid_to",          # ISO-8601; when this fact stops being true in the world
    "recorded_at",       # ISO-8601; when Aether first recorded this edge (system-time)
    "superseded_at",     # ISO-8601; when a later write superseded this edge (system-time)
    # Causality classification (required for prediction/attribution edges):
    "causality_class",   # observed_sequence|correlation|attributed_influence|inferred_influence|experiment_incremental|direct_cause
    # Campaign / journey context:
    "campaign_id",       # campaign that produced this edge
    "journey_id",        # journey this edge belongs to
    "journey_version",   # version of the journey definition
    "step_index",        # ordinal position within the journey
    # Grouping / membership provenance (population360 P3.1 — MEMBER_OF edges):
    "membership_state",      # active | left | expired — the membership's lifecycle state
    "definition_version",    # immutable population-definition version the membership was computed under
    "membership_basis",      # rule | graph | ml_model | similarity | manual | inferred
    "population_type",       # segment | cohort | cluster | ... (PopulationType value)
    "evidence_refs",         # list of EvidenceRef ids grounding this membership fact
    # Location-fact provenance (geographic360 G4.2 — LOCATED_AT / OBSERVED_IN /
    # UNDER_JURISDICTION edges). Precision is typed and never exceeds evidence:
    # a downgrade is recorded as precision_state, never a silent coarsening.
    "location_role",         # LOCATION_ROLES value (primary_residence, observed_presence, ...)
    "precision_class",       # country | region | city | coarse_cell | precise (location ladder)
    "precision_state",       # full | precision_reduced | suppressed — typed downgrade
    "region_type",           # REGION_TYPES value carried on a located-at Region edge
    "coarse_cell",           # H3 cell string when location precision is cell-granular
})

# Agent-lineage edge semantics (High-Cardinality Agent Lineage work order §30).
# Durable semantic edges only (spawn / delegation / authorization / principal /
# deployment / on-behalf-of): every principal<->agent relationship retains its
# evidence (invariant 13). ``valid_from`` / ``valid_to`` are the bitemporal
# fields above; the rest are carried here. Mirrors LINEAGE_EDGE_PROPERTIES in
# packages/shared/graph-contract.ts.
LINEAGE_EDGE_PROPERTIES: tuple[str, ...] = (
    "evidence_refs",            # list[str]: ids of the evidence rows grounding the edge
    "relationship_confidence",  # float in [0.0, 1.0] as string; None when not assessed
    "authority_ref",            # delegation / mandate / approval record the edge rests on
    "valid_from",
    "valid_to",
    "observed_at",              # ISO-8601; when the relationship was last observed
    "source_namespace",         # namespace of the reporting source
    "relationship_status",      # RELATIONSHIP_STATUSES
    "resolution_method",        # LINEAGE_RESOLUTION_METHODS
)

# How a lineage relationship was established. Only ``deterministic``,
# ``authority_record`` and ``attested`` can establish principal control; the
# rest are claims or weak signals and must stay labelled as such.
LINEAGE_RESOLUTION_METHODS: tuple[str, ...] = (
    "deterministic",
    "authority_record",
    "attested",
    "provider_asserted",
    "tenant_declared",
    "source_reported",
    "probabilistic",
    "manual",
)

LINEAGE_EDGE_PROPERTY_KEYS: frozenset[str] = frozenset(LINEAGE_EDGE_PROPERTIES)


def build_lineage_edge_properties(
    *,
    evidence_refs: list[str],
    resolution_method: str,
    relationship_status: str = "unknown",
    relationship_confidence: float | None = None,
    authority_ref: str = "",
    observed_at: str = "",
    source_namespace: str = "",
    valid_to: str = "",
) -> dict:
    """Return the lineage edge properties to merge into ``build_edge_properties``.

    Fails closed: an edge without evidence, or with a status / resolution
    method outside the vocabulary, is rejected rather than written. Unknown
    confidence is omitted (never defaulted to a number) so unknown never
    becomes a value.
    """
    refs = [r for r in evidence_refs if isinstance(r, str) and r.strip()]
    if not refs:
        raise ValueError("lineage edges must retain at least one evidence ref")
    if relationship_status not in RELATIONSHIP_STATUSES:
        raise ValueError(f"unknown relationship_status {relationship_status!r}")
    if resolution_method not in LINEAGE_RESOLUTION_METHODS:
        raise ValueError(f"unknown resolution_method {resolution_method!r}")
    props: dict = {
        "evidence_refs": refs,
        "relationship_status": relationship_status,
        "resolution_method": resolution_method,
    }
    if relationship_confidence is not None:
        if not 0.0 <= relationship_confidence <= 1.0:
            raise ValueError("relationship_confidence must be within [0.0, 1.0]")
        props["relationship_confidence"] = str(relationship_confidence)
    if authority_ref:
        props["authority_ref"] = authority_ref
    if observed_at:
        props["observed_at"] = observed_at
    if source_namespace:
        props["source_namespace"] = source_namespace
    if valid_to:
        props["valid_to"] = valid_to
    return props


# Valid causality classes — prediction edges must NOT use direct_cause
# unless backed by a held-out experiment (experiment_incremental or above).
CAUSALITY_CLASSES: frozenset[str] = frozenset({
    "observed_sequence",      # time-ordered without causal claim
    "correlation",            # statistical co-occurrence
    "attributed_influence",   # attribution model output
    "inferred_influence",     # ML-inferred causal path
    "experiment_incremental", # measured via A/B or geo experiment
    "direct_cause",           # established causal mechanism
})

# The four bitemporal fields that together model valid-time and system-time.
# valid_from is in REQUIRED_EDGE_PROPERTIES (open-ended start is always mandatory).
# The other three are optional — set by callers that manage bitemporal history.
BITEMPORAL_EDGE_PROPERTIES: frozenset[str] = frozenset({
    "valid_from",        # valid-time start (required; defaults to write time)
    "valid_to",          # valid-time end (null = still valid)
    "recorded_at",       # system-time when edge was recorded by Aether
    "superseded_at",     # system-time when a later revision superseded this edge
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
    valid_to: str = "",
    recorded_at: str = "",
    superseded_at: str = "",
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
    if valid_to:
        props["valid_to"] = valid_to
    if recorded_at:
        props["recorded_at"] = recorded_at
    if superseded_at:
        props["superseded_at"] = superseded_at
    props.update(extra)
    return props
