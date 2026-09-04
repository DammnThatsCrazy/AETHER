"""Semantic graph projector — project Gold relationship state into the graph.

Scheduled projector (WorkerSpec ``semantic_graph_projector``, gated on
``settings.semantic.graph_projector_enabled``) that, per tenant, reads the
durable ``gold_relationship_semantic_state`` projections and writes one directed
governed EDGE per relationship (``source_ref -> target_ref``) into the
intelligence graph **through the canonical mutation gateway** — never a direct
graph write. This is what closes the "Gold is computed but never reaches the
graph" gap: the relationship Gold the reducers already maintain becomes a
first-class, governed ``SEMANTIC_RELATES_TO`` edge that overlays and graph
consumers can read back.

Governance / safety:

* Every write goes through :class:`GraphMutationGateway.apply` with an
  :func:`edge_intent` (projection) or :func:`revocation_intent` (revocation).
  The gateway's mode (``off`` / ``shadow`` / ``enforce``, from
  ``settings.temporal_observatory.mutation_gateway_mode``) decides whether the
  mutation is also recorded in the append-only ledger — the projector never
  bypasses that. In ``off`` (the default) the edge is projected to the graph
  without a ledger row; in ``shadow`` / ``enforce`` it flows through the ledger.
* Every projected edge is **canonical before it reaches the gateway**: the
  projector builds the edge with the graph's canonical
  :func:`build_edge_properties` (``tenant_id``, ``idempotency_key``,
  ``actor_kind``, ``actor_id``, ``schema_version``, ``provenance``,
  ``valid_from``, ``confidence``) in **all** gateway modes. The gateway only
  canonicalises in ``shadow``/``enforce``; in ``off`` mode it hands the edge
  straight to ``GraphClient.add_edge``, whose Neptune path rejects a write
  missing any required property.
* ``SEMANTIC_RELATES_TO`` is mapped to the ``EXCLUDED`` relationship layer (a
  derived analytics overlay, not a human/agent interaction), so enforce-mode
  validation does not require a consent purpose.
* **Atomic, convergent writes.** Each edge carries a deterministic
  ``idempotency_key`` derived from the Gold row's natural key
  ``(tenant_id, source_ref, target_ref, relationship_ref)``, so every replica
  computing the same row derives the same edge identity. The per-tenant sweep
  additionally runs under an asyncio lock (one process), the gateway dedupes on
  the key in ``enforce`` mode, and the reconciliation pass collapses any
  duplicate a replica race appended. There is no blind check-then-create.
* **Reconciliation.** Before projecting the current Gold set, the projector lists
  the tenant's existing projected edges and revokes (through the gateway's
  revocation path, never a direct write) every projection whose ``(source,
  target)`` pair no longer has a Gold row — retention / erasure / recomputation
  removing the underlying fact otherwise left the edge alive forever. Stale,
  legacy (pre-canonicalisation), and replica-duplicate projections for a pair
  that still has Gold are also revoked so the sweep re-projects exactly one
  canonical edge per surviving pair.
* **Full Gold set read.** The projector supplies an explicit
  ``SEMANTIC_GOLD_RELATIONSHIP_READ_LIMIT`` to the repository's limit-only read
  (far above the 500-row default) so a tenant with more than 500 relationships
  is not silently truncated at the first page on every scheduled pass.
* Tenant isolation: every edge carries the tenant on both ``tenantId`` and
  ``tenant_id`` properties, the idempotency read filters on it, and the
  reconciliation scan returns only this tenant's edges — so one tenant's
  projection is never matched, replaced, or revoked because of another's.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
from dataclasses import dataclass, field
from typing import Any, Optional

from config.settings import settings
from shared.common.common import utc_now
from shared.graph.edge_properties import build_edge_properties
from shared.graph.graph import (
    Edge,
    EdgeType,
    Vertex,
    VertexType,
    _InMemoryGraphBackend,
    get_graph_client,
)
from shared.graph.mutation_gateway import GraphMutationGateway
from shared.graph.mutation_intents import edge_intent, revocation_intent, vertex_intent
from shared.logger.logger import get_logger, metrics

from . import reducers
from .repositories.base_fact_repo import SemanticFactRepository
from .repositories.review_queue_repo import SemanticReviewQueueRepository

logger = get_logger("aether.semantic.graph_projector")

_UNKNOWN_SUBJECT = "unknown_subject"
_PROJECT_INTERVAL_S = int(os.getenv("SEMANTIC_GRAPH_PROJECTOR_INTERVAL_S", str(6 * 3600)))

# The governed edge type for a semantic relationship projection. Declared on
# ``EdgeType`` and mapped to ``RelationshipLayer.EXCLUDED`` in
# ``shared/graph/relationship_layers.py`` (a derived analytics overlay).
SEMANTIC_EDGE_TYPE = EdgeType.SEMANTIC_RELATES_TO


# The semantic reducer's stable, deterministic pair identity (see
# ``reducers.relationship_ref``). Reused as the edge's ``correlation_id`` so
# every replica computing the same Gold row derives the same correlation.
def _relationship_ref_of(data: dict[str, Any], source: str, target: str) -> str:
    rel = data.get("relationship_ref")
    if rel:
        return str(rel)
    return f"rel:{source}->{target}"


# The salient Gold fields whose change constitutes a genuine content revision of
# a projected relationship edge — the recomputed values a graph consumer reads.
# ``computed_at`` is deliberately EXCLUDED: it is wall-clock and changes on every
# recompute even when nothing else did, so folding it in would churn an unchanged
# edge on every sweep and break replica determinism.
_RELATIONSHIP_CONTENT_FIELDS = (
    "stance_alignment",
    "trust_signal",
    "interaction_quality",
    "influence_direction",
    "confidence",
    "reducer_version",
)


def _content_revision(data: dict[str, Any], fields: tuple[str, ...]) -> str:
    """Deterministic short digest of the salient Gold ``fields``.

    Folded into the projected edge/vertex identity so a RECOMPUTED Gold row with
    the SAME endpoints but CHANGED content yields a NEW identity (re-projected),
    while unchanged content yields the SAME identity (skipped, no churn). Pure
    over the field values — no wall-clock, no randomness — so every replica
    computing the same revision derives the same digest (idempotency-key /
    gateway-dedup convergence across replicas).
    """
    parts = [f"{key}={data.get(key)!r}" for key in fields]
    return hashlib.sha256("|".join(parts).encode()).hexdigest()[:16]


# Auto-projection confidence floor for the consent/quality promotion policy
# (``graph_promotion_review_enabled``). An edge whose bounded confidence is below
# this is deferred to the review queue instead of auto-projected. Kept simple and
# honest: a single bounded-confidence predicate, env-overridable.
_AUTO_PROJECT_MIN_CONFIDENCE = float(
    os.getenv("SEMANTIC_GRAPH_AUTO_PROJECT_MIN_CONFIDENCE", "0.5")
)


# Explicit full-set read bound for the per-tenant Gold sweep.
# ``SemanticFactRepository.list_by_tenant`` is a limit-only read (no
# offset/cursor yet); the projector passes an explicit cap far above the
# 500-row default so a tenant with more relationships is not truncated at the
# first page on every pass. True cursor pagination belongs in the repository
# (out of this module's ownership); this bound keeps the sweep a single bounded
# read while eliminating the silent first-page truncation.
_GOLD_RELATIONSHIP_READ_LIMIT = int(
    os.getenv("SEMANTIC_GOLD_RELATIONSHIP_READ_LIMIT", str(100_000))
)

# Per-tenant asyncio lock: serialises projector sweeps within one process so
# concurrent ``semantic_graph_projector`` passes cannot both observe "no edge"
# and append a duplicate. Cross-process convergence is carried by the stable
# idempotency key (gateway dedup in enforce mode) and the reconciliation pass.
_TENANT_PROJECT_LOCKS: dict[str, asyncio.Lock] = {}


@dataclass
class ProjectionReport:
    """Per-tenant projector outcome."""

    tenant_id: str
    relationships_seen: int = 0
    projected: int = 0
    skipped_existing: int = 0
    revoked: int = 0
    deferred_review: int = 0
    vertices_projected: int = 0
    vertices_skipped_existing: int = 0
    failed: int = 0
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "tenant_id": self.tenant_id,
            "relationships_seen": self.relationships_seen,
            "projected": self.projected,
            "skipped_existing": self.skipped_existing,
            "revoked": self.revoked,
            "deferred_review": self.deferred_review,
            "vertices_projected": self.vertices_projected,
            "vertices_skipped_existing": self.vertices_skipped_existing,
            "failed": self.failed,
            "errors": self.errors[:10],
        }


def _tenant_of(props: dict[str, Any]) -> str:
    return str(props.get("tenantId") or props.get("tenant_id") or "")


def _bounded_confidence(raw: Any) -> float:
    """Parse a Gold confidence into a valid [0.0, 1.0] float (1.0 on garbage)."""
    try:
        value = float(raw) if raw is not None else 1.0
    except (TypeError, ValueError):
        value = 1.0
    return max(0.0, min(1.0, value))


def edge_from_relationship(tenant_id: str, data: dict[str, Any]) -> Optional[Edge]:
    """Build the governed, canonical edge for one ``gold_relationship_semantic_state`` row.

    Returns ``None`` when the row cannot be projected (missing/degenerate
    endpoints), never a partial edge.

    The edge is built with the graph's canonical
    :func:`build_edge_properties` so it carries the full required property set
    (``tenant_id``, ``idempotency_key``, ``actor_kind``, ``actor_id``,
    ``schema_version``, ``provenance``, ``valid_from``, ``confidence``) **before
    reaching the gateway**. The projector cannot rely on the gateway's
    shadow/enforce-only canonicalisation: in the default ``off`` mode the
    gateway passes the edge straight to ``GraphClient.add_edge``, whose Neptune
    path rejects a write missing any required property.
    """
    source = str(data.get("source_ref") or "").strip()
    target = str(data.get("target_ref") or "").strip()
    if not source or not target or source == target:
        return None
    if _UNKNOWN_SUBJECT in (source, target):
        return None
    rel_ref = _relationship_ref_of(data, source, target)
    # Fold the Gold row's CONTENT into the edge identity: a recomputed row with
    # the same endpoints but changed salient content yields a new
    # ``source_event_id`` component -> new ``idempotency_key`` -> the sweep
    # re-projects it (and reconciliation revokes the stale prior key), while
    # unchanged content keeps the same key and is skipped. The changed key also
    # avoids the enforce-mode gateway/ledger dedup (keyed on idempotency_key), so
    # a genuine content change is never suppressed. ``correlation_id`` stays the
    # bare pair ref for traceability.
    content_rev = _content_revision(data, _RELATIONSHIP_CONTENT_FIELDS)
    identity_ref = f"{rel_ref}@{content_rev}"
    props = build_edge_properties(
        tenant_id=tenant_id,
        edge_type=SEMANTIC_EDGE_TYPE,
        from_vertex_id=source,
        to_vertex_id=target,
        actor_kind="system",
        actor_id="semantic_graph_projector",
        provenance="semantic_relationship_gold",
        valid_from=str(data.get("valid_from") or utc_now().isoformat()),
        confidence=_bounded_confidence(data.get("confidence")),
        source_event_id=identity_ref,
        correlation_id=rel_ref,
        content_revision=content_rev,
    )
    semantic: dict[str, Any] = {
        # camelCase alias the overlay / read paths expect, in addition to the
        # canonical snake_case ``tenant_id`` set by ``build_edge_properties``.
        "tenantId": tenant_id,
        "relationship_ref": rel_ref,
        "relationship_layer": data.get("relationship_layer"),
        "stance_alignment": data.get("stance_alignment"),
        "trust_signal": data.get("trust_signal"),
        "interaction_quality": data.get("interaction_quality"),
        "influence_direction": data.get("influence_direction"),
        # ``confidence`` is deliberately NOT re-added here. ``props`` already
        # carries the canonical property from ``build_edge_properties``, built
        # from the bounded ``_bounded_confidence(...)`` result; re-adding the RAW
        # Gold value here would overwrite that clamp during the ``props.update``
        # below and let malformed / out-of-range Gold confidence escape the
        # defensive path (enforce mode would reject the edge under the
        # validator's [0.0, 1.0] rule; off mode would persist invalid data).
        "reducer_version": data.get("reducer_version"),
        "valid_from": data.get("valid_from"),
    }
    props.update({k: v for k, v in semantic.items() if v is not None})
    return Edge(
        edge_type=SEMANTIC_EDGE_TYPE,
        from_vertex_id=source,
        to_vertex_id=target,
        properties=props,
    )


async def _already_projected(
    graph_client: Any,
    tenant_id: str,
    source: str,
    target: str,
    idempotency_key: str,
) -> bool:
    """True when this tenant already has a LIVE canonical edge ``source -> target``.

    Matching is by the deterministic ``idempotency_key`` (derived from the Gold
    row's natural key), never just endpoints: a same-pair edge carrying a
    different key is a stale revision (or a legacy non-canonical write) that the
    reconciliation pass must replace, not skip.
    """
    existing = await graph_client.get_edges(source, edge_type=SEMANTIC_EDGE_TYPE)
    return any(
        e.to_vertex_id == target
        and not (e.properties or {}).get("revoked")
        and _tenant_of(e.properties or {}) == tenant_id
        and str((e.properties or {}).get("idempotency_key") or "") == idempotency_key
        for e in existing
    )


async def _list_projected_edges_for_tenant(graph_client: Any, tenant_id: str) -> list[Any]:
    """Every LIVE ``SEMANTIC_RELATES_TO`` edge currently projected for the tenant.

    Uses the flat backend edge store when available (in-memory / local, where the
    edge's source vertex is not required to exist in the graph), otherwise a
    tenant-scoped scan over the tenant's OWN vertices via
    ``get_vertices_for_tenant`` — the predicate is pushed into the query, never a
    global ``get_all_vertices`` page filtered afterwards (silent truncation; the
    scoped-read gate ``validate_graph_scoped_reads.py`` forbids it). Only edges
    tagged with this tenant are returned, so reconciliation never touches another
    tenant's projection.
    """
    backend = getattr(graph_client, "_backend", None)
    if backend is None:
        await graph_client.connect()
        backend = getattr(graph_client, "_backend", None)
    if isinstance(backend, _InMemoryGraphBackend):
        return [
            e
            for e in backend._edges
            if e.edge_type == SEMANTIC_EDGE_TYPE
            and _tenant_of(e.properties or {}) == tenant_id
            and not (e.properties or {}).get("revoked")
        ]
    # Retain EVERY distinct returned edge. A ``seen`` dict keyed by
    # ``(edge_type, from_vertex_id, to_vertex_id)`` collapsed two live
    # replica-raced edges with the same tuple BEFORE ``_reconcile_projections``
    # grouped and counted them: reconciliation then saw one canonical edge and
    # took its ``len(edges) == 1`` keep path, leaving the duplicate live
    # forever. Distinct edges (even byte-identical ones — a replica race writes
    # the same ``idempotency_key``) must all reach reconciliation so the
    # duplicate is revoked and the sweep re-projects exactly one. Deduplicate
    # only by object identity: the same backend Edge object could otherwise be
    # observed twice, but that is not a real duplicate and must not be counted
    # as one.
    projected: list[Any] = []
    seen_ids: set[int] = set()
    for vertex in await graph_client.get_vertices_for_tenant(
        tenant_id, limit=_GOLD_RELATIONSHIP_READ_LIMIT
    ):
        for edge in await graph_client.get_edges(
            vertex.vertex_id,
            edge_type=SEMANTIC_EDGE_TYPE,
            direction="out",
            include_revoked=True,
        ):
            if _tenant_of(edge.properties or {}) != tenant_id:
                continue
            if (edge.properties or {}).get("revoked"):
                continue
            if id(edge) in seen_ids:
                continue
            seen_ids.add(id(edge))
            projected.append(edge)
    return projected


async def _revoke_projection(
    gateway: GraphMutationGateway,
    tenant_id: str,
    source: str,
    target: str,
    *,
    mode_override: Optional[str] = None,
) -> None:
    """Soft-revoke one tenant's projected edge through the gateway (never direct).

    ``mode_override`` is only forwarded when set, so the default call path stays
    byte-identical to the pre-override signature for foreign callers (e.g. the
    privacy erasure handler) that pass a gateway which does not accept the kwarg.
    """
    intent = revocation_intent(
        from_vertex_id=source,
        to_vertex_id=target,
        edge_type=SEMANTIC_EDGE_TYPE,
        reason="gold_relationship_removed",
        tenant_id=tenant_id,
        actor_kind="system",
        actor_id="semantic_graph_projector",
    )
    if mode_override is not None:
        await gateway.apply(intent, mode_override=mode_override)
    else:
        await gateway.apply(intent)


async def _reconcile_projections(
    graph_client: Any,
    gateway: GraphMutationGateway,
    tenant_id: str,
    expected: dict[tuple[str, str], Edge],
    report: ProjectionReport,
    *,
    mode_override: Optional[str] = None,
) -> None:
    """Revoke the tenant's stale projected edges against the current Gold set.

    Runs BEFORE the write sweep. Every live projection whose ``(source, target)``
    pair no longer has a Gold row is revoked through the gateway's revocation
    path — retention / erasure / recomputation removing the underlying fact would
    otherwise leave the edge alive indefinitely. A pair that still has Gold but
    whose live projection(s) are stale, legacy (pre-canonicalisation), or a
    replica duplicate is also revoked, so the sweep re-projects exactly one
    canonical edge below. ``revoke_edge`` matches by ``(from, to, edge_type,
    tenant)`` — it cannot keep one of several matching edges — so keeping the
    surviving edge is delegated to the sweep's idempotency-key check.
    """
    existing = await _list_projected_edges_for_tenant(graph_client, tenant_id)
    by_pair: dict[tuple[str, str], list[Any]] = {}
    for edge in existing:
        by_pair.setdefault((edge.from_vertex_id, edge.to_vertex_id), []).append(edge)
    for (source, target), edges in by_pair.items():
        expected_edge = expected.get((source, target))
        if expected_edge is None:
            # No Gold row for this pair — every live projection is stale.
            await _revoke_projection(
                gateway, tenant_id, source, target, mode_override=mode_override
            )
            report.revoked += len(edges)
            continue
        expected_key = str(expected_edge.properties.get("idempotency_key") or "")
        live_matching = [
            e
            for e in edges
            if str((e.properties or {}).get("idempotency_key") or "") == expected_key
        ]
        if live_matching and len(edges) == 1:
            # Exactly one canonical live edge for a still-current pair: keep.
            continue
        # Stale / legacy / duplicate projection(s): revoke so the sweep
        # re-projects exactly one canonical edge below.
        await _revoke_projection(
            gateway, tenant_id, source, target, mode_override=mode_override
        )
        report.revoked += len(edges)


def _tenant_project_lock(tenant_id: str) -> asyncio.Lock:
    lock = _TENANT_PROJECT_LOCKS.get(tenant_id)
    if lock is None:
        lock = asyncio.Lock()
        _TENANT_PROJECT_LOCKS[tenant_id] = lock
    return lock


# ── Consent/quality promotion policy ─────────────────────────────────────────


def _auto_project_ok(data: dict[str, Any]) -> bool:
    """Auto-project predicate for the promotion policy (simple + honest).

    An edge auto-projects when its bounded confidence clears
    ``_AUTO_PROJECT_MIN_CONFIDENCE`` and the Gold row is not explicitly flagged
    low-trust. Otherwise the sweep defers it to the review queue instead of
    projecting. Only consulted when ``graph_promotion_review_enabled`` is on.
    """
    if data.get("low_trust") is True:
        return False
    return _bounded_confidence(data.get("confidence")) >= _AUTO_PROJECT_MIN_CONFIDENCE


async def _enqueue_promotion_review(
    tenant_id: str, edge: Edge, data: dict[str, Any]
) -> None:
    """Enqueue one ``graph_promotion_candidate`` review item (tenant-scoped)."""
    source, target = edge.from_vertex_id, edge.to_vertex_id
    rel_ref = _relationship_ref_of(data, source, target)
    await SemanticReviewQueueRepository().enqueue(
        tenant_id,
        "graph_promotion_candidate",
        subject_ref=rel_ref,
        source_event_id=rel_ref,
        payload={
            "source_ref": source,
            "target_ref": target,
            "reason": "below_auto_project_confidence"
            if data.get("low_trust") is not True
            else "low_trust_flagged",
            "confidence": _bounded_confidence(data.get("confidence")),
        },
    )


# ── Entity Gold as governed vertices ─────────────────────────────────────────

# Salient entity Gold fields whose change constitutes a new vertex content
# revision — mirrors ``_RELATIONSHIP_CONTENT_FIELDS`` for the edge path.
_ENTITY_CONTENT_FIELDS = (
    "semantic_summary",
    "dominant_stance",
    "confidence",
    "observation_count",
    "reducer_version",
)


def _entity_vertex_id(tenant_id: str, entity_ref: str) -> str:
    """Deterministic, tenant-scoped vertex id for an entity Gold projection.

    The tenant is folded into the id so two tenants sharing an ``entity_ref``
    never upsert onto the same vertex — the same tenant-isolation guarantee the
    edge path carries on its properties.
    """
    return f"sem_entity:{tenant_id}:{entity_ref}"


def _dominant_stance(data: dict[str, Any]) -> Optional[str]:
    dist = data.get("stance_distribution")
    if isinstance(dist, dict) and dist:
        return str(max(dist.items(), key=lambda kv: (kv[1], kv[0]))[0])
    return None


def vertex_from_entity(tenant_id: str, data: dict[str, Any]) -> Optional[Vertex]:
    """Build the governed vertex for one ``gold_entity_semantic_state`` row.

    Carries the tenant (``tenantId`` + ``tenant_id``) and only the salient Gold
    signal — entity ref, semantic summary, dominant stance, bounded confidence,
    observation count — never raw content. The vertex id is deterministic and
    tenant-scoped so recomputation upserts the same vertex; a ``content_revision``
    property lets the sweep skip an unchanged vertex. Returns ``None`` for a
    missing / degenerate entity ref.
    """
    entity_ref = str(data.get("entity_ref") or data.get("subject_ref") or "").strip()
    if not entity_ref or entity_ref == _UNKNOWN_SUBJECT:
        return None
    dominant = _dominant_stance(data)
    enriched = {**data, "dominant_stance": dominant}
    props: dict[str, Any] = {
        # Both tenant spellings: ``tenantId`` for the overlay/read paths and the
        # canonical ``tenant_id`` the ledger/digest resolve on.
        "tenantId": tenant_id,
        "tenant_id": tenant_id,
        "entity_ref": entity_ref,
        "semantic_summary": data.get("semantic_summary"),
        "dominant_stance": dominant,
        "confidence": _bounded_confidence(data.get("confidence")),
        "observation_count": data.get("observation_count"),
        "provenance": "semantic_entity_gold",
        "content_revision": _content_revision(enriched, _ENTITY_CONTENT_FIELDS),
    }
    props = {k: v for k, v in props.items() if v is not None}
    return Vertex(
        vertex_type=VertexType.ENTITY,
        vertex_id=_entity_vertex_id(tenant_id, entity_ref),
        properties=props,
    )


async def _project_tenant_vertices(
    graph_client: Any,
    gateway: GraphMutationGateway,
    tenant_id: str,
    report: ProjectionReport,
    mode_override: Optional[str],
) -> None:
    """Upsert one governed vertex per entity Gold row through the gateway.

    Idempotent + tenant-scoped like the edge path: a vertex whose live
    projection already carries the same ``content_revision`` (and this tenant) is
    skipped; otherwise it is upserted via ``vertex_intent(..., 'node_versioned')``
    so the gateway governs the write (never a direct ``upsert_vertex``).
    """
    repo = SemanticFactRepository(reducers._GOLD_ENTITY_TABLE, mode="gold")
    rows = await repo.list_by_tenant(tenant_id, limit=_GOLD_RELATIONSHIP_READ_LIMIT)
    for data in rows:
        vertex = vertex_from_entity(tenant_id, data)
        if vertex is None:
            continue
        try:
            existing = await graph_client.get_vertex(vertex.vertex_id)
            if (
                existing is not None
                and _tenant_of(existing.properties or {}) == tenant_id
                and str((existing.properties or {}).get("content_revision") or "")
                == str(vertex.properties.get("content_revision") or "")
            ):
                report.vertices_skipped_existing += 1
                continue
            await gateway.apply(
                vertex_intent(
                    vertex,
                    operation="node_versioned",
                    tenant_id=tenant_id,
                ),
                mode_override=mode_override,
            )
            report.vertices_projected += 1
        except Exception as exc:  # noqa: BLE001 — isolate one vertex's failure
            report.failed += 1
            report.errors.append(f"vertex {vertex.vertex_id}: {exc}")
            metrics.increment("semantic_graph_projection_error_total")


async def project_tenant(
    tenant_id: str,
    *,
    gateway: Optional[GraphMutationGateway] = None,
    graph_client: Optional[Any] = None,
) -> ProjectionReport:
    """Project one tenant's relationship Gold into the graph, idempotently.

    ``graph_client`` / ``gateway`` are injectable for tests so the existence
    check and the write target the same graph; production passes neither and
    uses the process-wide client + gateway.

    The whole sweep runs under a per-tenant asyncio lock so concurrent worker
    passes in one process cannot both observe "no edge" and append a duplicate.
    Cross-process convergence is carried by the stable edge idempotency key
    (deduplicated by the gateway in enforce mode) plus the reconciliation pass,
    which also revokes projections whose Gold row has disappeared.
    """
    graph_client = graph_client or get_graph_client()
    gw = gateway or GraphMutationGateway(graph_client=graph_client)
    repo = SemanticFactRepository(reducers._GOLD_RELATIONSHIP_TABLE, mode="gold")
    report = ProjectionReport(tenant_id=tenant_id)
    # Force the gateway mode ladder for the projector's own writes when the
    # deployment set it (`''` -> None -> inherit the global mode).
    mode_override = settings.semantic.graph_projector_gateway_mode or None
    review_enabled = settings.semantic.graph_promotion_review_enabled

    async with _tenant_project_lock(tenant_id):
        rows = await repo.list_by_tenant(tenant_id, limit=_GOLD_RELATIONSHIP_READ_LIMIT)
        expected: dict[tuple[str, str], Edge] = {}
        edges_to_write: list[tuple[Edge, dict[str, Any]]] = []
        for data in rows:
            edge = edge_from_relationship(tenant_id, data)
            if edge is None:
                continue
            report.relationships_seen += 1
            expected[(edge.from_vertex_id, edge.to_vertex_id)] = edge
            edges_to_write.append((edge, data))
        # Revoke stale / removed / duplicate projections first, then project the
        # current Gold set so each surviving pair ends with exactly one canonical
        # edge (the sweep's idempotency-key check is what "keeps" it).
        await _reconcile_projections(
            graph_client, gw, tenant_id, expected, report, mode_override=mode_override
        )
        for edge, data in edges_to_write:
            idem_key = str(edge.properties.get("idempotency_key") or "")
            try:
                if await _already_projected(
                    graph_client,
                    tenant_id,
                    edge.from_vertex_id,
                    edge.to_vertex_id,
                    idem_key,
                ):
                    report.skipped_existing += 1
                    continue
                # Consent/quality promotion policy (flag-gated): an edge failing
                # the auto-project predicate is deferred to the review queue
                # instead of auto-projected. Flag OFF (default) -> auto-project
                # every edge, unchanged behavior.
                if review_enabled and not _auto_project_ok(data):
                    await _enqueue_promotion_review(tenant_id, edge, data)
                    report.deferred_review += 1
                    continue
                await gw.apply(
                    edge_intent(
                        edge,
                        operation="edge_created",
                        tenant_id=tenant_id,
                        subject_kind="entity",
                        subject_id=edge.to_vertex_id,
                        causality_class="observed_sequence",
                    ),
                    mode_override=mode_override,
                )
                report.projected += 1
            except Exception as exc:  # noqa: BLE001 — isolate one edge's failure
                report.failed += 1
                report.errors.append(f"{edge.from_vertex_id}->{edge.to_vertex_id}: {exc}")
                metrics.increment("semantic_graph_projection_error_total")

        # Entity Gold as governed VERTICES (flag-gated; edges-only when off).
        if settings.semantic.graph_vertex_projection_enabled:
            await _project_tenant_vertices(
                graph_client, gw, tenant_id, report, mode_override
            )
    if report.projected:
        metrics.increment("semantic_graph_edges_projected_total", report.projected)
    if report.revoked:
        metrics.increment("semantic_graph_edges_revoked_total", report.revoked)
    if report.vertices_projected:
        metrics.increment(
            "semantic_graph_vertices_projected_total", report.vertices_projected
        )
    return report


async def project_pair(
    tenant_id: str,
    source_ref: str,
    target_ref: str,
    *,
    gateway: Optional[GraphMutationGateway] = None,
    graph_client: Optional[Any] = None,
) -> ProjectionReport:
    """Project exactly one relationship pair's canonical edge through the gateway.

    Public seam the review-approval route calls: it reads that ONE pair's current
    ``gold_relationship_semantic_state`` row and projects exactly that one
    canonical edge (same ``edge_from_relationship`` + gateway write path as the
    sweep), BYPASSING the promotion review policy — approval already decided the
    edge should be promoted. A stale (different-key / legacy) live projection for
    the pair is revoked first so the pair ends with exactly one canonical edge;
    an already-current edge is skipped (no churn). Tenant-scoped throughout.
    """
    graph_client = graph_client or get_graph_client()
    gw = gateway or GraphMutationGateway(graph_client=graph_client)
    repo = SemanticFactRepository(reducers._GOLD_RELATIONSHIP_TABLE, mode="gold")
    report = ProjectionReport(tenant_id=tenant_id)
    mode_override = settings.semantic.graph_projector_gateway_mode or None
    rel_ref = reducers.relationship_ref(source_ref, target_ref)

    rows = await repo.list_by_tenant(
        tenant_id, subject=rel_ref, limit=_GOLD_RELATIONSHIP_READ_LIMIT
    )
    data = next(
        (
            r
            for r in rows
            if str(r.get("source_ref") or "") == source_ref
            and str(r.get("target_ref") or "") == target_ref
        ),
        None,
    )
    if data is None:
        return report
    edge = edge_from_relationship(tenant_id, data)
    if edge is None:
        return report
    report.relationships_seen += 1
    idem_key = str(edge.properties.get("idempotency_key") or "")

    async with _tenant_project_lock(tenant_id):
        if await _already_projected(
            graph_client, tenant_id, source_ref, target_ref, idem_key
        ):
            report.skipped_existing += 1
            return report
        # A stale live projection (different key — e.g. approving recomputed
        # content) is superseded so the pair ends with exactly one canonical edge.
        existing = await graph_client.get_edges(source_ref, edge_type=SEMANTIC_EDGE_TYPE)
        stale = [
            e
            for e in existing
            if e.to_vertex_id == target_ref
            and not (e.properties or {}).get("revoked")
            and _tenant_of(e.properties or {}) == tenant_id
        ]
        if stale:
            await _revoke_projection(
                gw, tenant_id, source_ref, target_ref, mode_override=mode_override
            )
            report.revoked += len(stale)
        await gw.apply(
            edge_intent(
                edge,
                operation="edge_created",
                tenant_id=tenant_id,
                subject_kind="entity",
                subject_id=edge.to_vertex_id,
                causality_class="observed_sequence",
            ),
            mode_override=mode_override,
        )
        report.projected += 1
    return report


async def project_once() -> list[ProjectionReport]:
    """One projector pass across every tenant with relationship Gold.

    Tenants are enumerated from the durable relationship-Gold table; a deployment
    on the in-memory store (local/CI) has no rows there, so the pass is a no-op —
    matching the flag being off by default.

    A tenant whose sweep RAISES (e.g. the reconciliation list/revoke phase
    fails) is isolated into a per-tenant :class:`ProjectionReport` marked failed
    and the pass CONTINUES with the remaining tenants. Without this, one
    persistently failing early tenant would abort the whole pass — the outer
    supervised loop only catches after ``project_once`` exits — and starve every
    later tenant until the next interval.
    """
    tenants = await SemanticFactRepository(reducers._GOLD_RELATIONSHIP_TABLE).distinct_tenants()
    reports: list[ProjectionReport] = []
    for tenant_id in tenants:
        try:
            report = await project_tenant(tenant_id)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 — isolate one tenant's failure
            metrics.increment("semantic_graph_projection_error_total")
            logger.error(
                "semantic graph projector tenant sweep failed tenant=%s: %s",
                tenant_id,
                exc,
                exc_info=True,
            )
            report = ProjectionReport(tenant_id=tenant_id, failed=1, errors=[str(exc)])
        if report.failed:
            logger.warning("semantic graph projector partial: %s", report.to_dict())
        reports.append(report)
    return reports


async def run_semantic_graph_projector_loop(
    interval_seconds: Optional[int] = None,
) -> None:
    """Supervised loop: project relationship Gold into the graph on an interval."""
    interval = int(interval_seconds if interval_seconds is not None else _PROJECT_INTERVAL_S)
    logger.info("semantic graph projector worker started interval=%ss", interval)
    while True:
        try:
            await project_once()
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # pragma: no cover — defensive supervision
            metrics.increment("semantic_graph_projection_error_total")
            logger.error("semantic graph projector pass failed: %s", exc, exc_info=True)
        await asyncio.sleep(interval)


def build_semantic_graph_projector_coro() -> Any:
    """Zero-arg coroutine factory for the ``semantic_graph_projector`` WorkerSpec."""
    return run_semantic_graph_projector_loop()
