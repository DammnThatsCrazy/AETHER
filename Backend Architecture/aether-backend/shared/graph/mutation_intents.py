"""Small builders that turn an already-formed graph write into a
:class:`~shared.graph.mutation_gateway.MutationIntent` (WP2.5).

Direct graph writers migrating onto the canonical
:class:`~shared.graph.mutation_gateway.GraphMutationGateway` express each
``add_edge`` / ``upsert_vertex`` / ``add_vertex`` / ``revoke_edge`` call as a
``MutationIntent``. These helpers keep that translation uniform and DRY across
the ~30 migrated writer packages while preserving the identity-writer pattern
proof: the Edge / Vertex object is passed through **unchanged** (so ``off`` mode
projects exactly what the writer wrote today), and the ledger metadata — actor,
subject, causality class, evidence — travels on the intent, where it only
materialises in ``shadow`` / ``enforce`` modes.

None of these builders mutate the passed Edge / Vertex properties. Fields that
are ``None`` are simply omitted from the ledger record.
"""

from __future__ import annotations

from typing import Optional

from shared.graph.graph import Edge, Vertex
from shared.graph.mutation_gateway import EdgeRevocation, MutationIntent


def _confidence(properties: dict) -> Optional[float]:
    raw = (properties or {}).get("confidence")
    if raw is None:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def _rights_kwargs(properties: dict) -> dict:
    """Carry reference-only IRRL context from a projected graph object."""
    values = properties or {}
    envelope_refs = values.get("rights_envelope_refs") or []
    envelope_id = values.get("rights_envelope_id") or values.get("envelope_ref")
    if not envelope_id and envelope_refs:
        envelope_id = envelope_refs[0]
    decision_refs = values.get("rights_decision_refs") or []
    decision_id = values.get("rights_decision_id")
    if not decision_id and decision_refs:
        decision_id = decision_refs[0]
    return {
        "rights_decision_id": decision_id,
        "rights_envelope_id": envelope_id,
        "rights_policy_set_ref": values.get("rights_policy_set_ref"),
        "rights_lineage_set_hash": values.get("rights_lineage_set_hash"),
        "rights_source_grant_refs": values.get("rights_source_grant_refs")
        or values.get("source_grant_refs"),
    }


def edge_intent(
    edge: Edge,
    *,
    operation: str = "edge_created",
    tenant_id: Optional[str] = None,
    actor_kind: Optional[str] = None,
    actor_id: Optional[str] = None,
    subject_kind: Optional[str] = None,
    subject_id: Optional[str] = None,
    source_event_id: Optional[str] = None,
    causality_class: str = "observed_sequence",
    reason_code: Optional[str] = None,
    confidence: Optional[float] = None,
    evidence_refs: Optional[list[str]] = None,
    consent_refs: Optional[list[str]] = None,
    correlation_id: Optional[str] = None,
    valid_from: Optional[str] = None,
    valid_to: Optional[str] = None,
) -> MutationIntent:
    """Express one edge write as a gateway intent (edge passed through as-is).

    ``tenant_id`` / ``actor_kind`` / ``actor_id`` / ``source_event_id`` /
    ``confidence`` fall back to the corresponding edge properties when not given
    explicitly, so a writer that already built canonical properties (via
    ``build_edge_properties``) does not have to repeat them. In particular a
    writer that canonicalised ``actor_kind`` on the edge (e.g. ``"service"``)
    but omits it here gets that same actor_kind on the ledger record and CIS
    context, instead of a hardcoded ``"system"`` that would disagree with the
    projected edge.
    """
    props = edge.properties or {}
    return MutationIntent(
        operation=operation,
        tenant_id=tenant_id if tenant_id is not None else str(props.get("tenant_id", "")),
        edge=edge,
        actor_kind=actor_kind
        if actor_kind is not None
        else (props.get("actor_kind") or "system"),
        actor_id=actor_id if actor_id is not None else props.get("actor_id"),
        subject_kind=subject_kind,
        subject_id=subject_id,
        source_event_id=source_event_id
        if source_event_id is not None
        else (props.get("source_event_id") or None),
        causality_class=causality_class,
        reason_code=reason_code,
        confidence=confidence if confidence is not None else _confidence(props),
        evidence_refs=evidence_refs,
        consent_refs=consent_refs,
        correlation_id=correlation_id,
        valid_from=valid_from,
        valid_to=valid_to,
        **_rights_kwargs(props),
    )


def vertex_intent(
    vertex: Vertex,
    *,
    operation: str,
    tenant_id: Optional[str] = None,
    actor_kind: str = "system",
    actor_id: Optional[str] = None,
    subject_kind: Optional[str] = None,
    subject_id: Optional[str] = None,
    source_event_id: Optional[str] = None,
    causality_class: str = "observed_sequence",
    reason_code: Optional[str] = None,
    correlation_id: Optional[str] = None,
) -> MutationIntent:
    """Express one vertex write as a gateway intent.

    ``operation`` must be a node operation from the taxonomy:
    ``node_created`` projects via ``add_vertex`` (matching a direct
    ``add_vertex`` call); every other node operation (e.g. ``node_versioned``)
    projects via ``upsert_vertex`` (matching a direct ``upsert_vertex`` call).
    """
    props = vertex.properties or {}
    return MutationIntent(
        operation=operation,
        tenant_id=tenant_id if tenant_id is not None else str(props.get("tenant_id", "")),
        vertex=vertex,
        actor_kind=actor_kind,
        actor_id=actor_id,
        subject_kind=subject_kind if subject_kind is not None else vertex.vertex_type,
        subject_id=subject_id if subject_id is not None else vertex.vertex_id,
        source_event_id=source_event_id,
        causality_class=causality_class,
        reason_code=reason_code,
        correlation_id=correlation_id,
        **_rights_kwargs(props),
    )


def revocation_intent(
    *,
    from_vertex_id: str,
    to_vertex_id: str,
    edge_type: str,
    reason: str,
    tenant_id: str,
    operation: str = "edge_expired",
    actor_kind: str = "system",
    actor_id: Optional[str] = None,
    subject_kind: Optional[str] = None,
    subject_id: Optional[str] = None,
    reason_code: Optional[str] = None,
    causality_class: str = "declared_reason",
    source_event_id: Optional[str] = None,
    correlation_id: Optional[str] = None,
) -> MutationIntent:
    """Express one soft-revoke as a gateway intent (never a hard delete).

    ``operation`` should be a revoke operation from the taxonomy
    (``edge_expired`` / ``edge_tombstoned`` / ``identity_split``); regardless,
    the gateway projects it through ``GraphClient.revoke_edge`` and replay
    treats it as a revocation.
    """
    return MutationIntent(
        operation=operation,
        tenant_id=tenant_id,
        revocation=EdgeRevocation(
            from_vertex_id=from_vertex_id,
            to_vertex_id=to_vertex_id,
            edge_type=edge_type,
            reason=reason,
        ),
        actor_kind=actor_kind,
        actor_id=actor_id,
        subject_kind=subject_kind,
        subject_id=subject_id if subject_id is not None else from_vertex_id,
        reason_code=reason_code if reason_code is not None else reason,
        causality_class=causality_class,
        source_event_id=source_event_id,
        correlation_id=correlation_id,
    )


__all__ = ["edge_intent", "vertex_intent", "revocation_intent"]
