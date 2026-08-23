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
import os
from dataclasses import dataclass, field
from typing import Any, Optional

from shared.common.common import utc_now
from shared.graph.edge_properties import build_edge_properties
from shared.graph.graph import Edge, EdgeType, _InMemoryGraphBackend, get_graph_client
from shared.graph.mutation_gateway import GraphMutationGateway
from shared.graph.mutation_intents import edge_intent, revocation_intent
from shared.logger.logger import get_logger, metrics

from . import reducers
from .repositories.base_fact_repo import SemanticFactRepository

logger = get_logger("aether.semantic.graph_projector")

_UNKNOWN_SUBJECT = "unknown_subject"
_PROJECT_INTERVAL_S = int(os.getenv("SEMANTIC_GRAPH_PROJECTOR_INTERVAL_S", str(6 * 3600)))

# The governed edge type for a semantic relationship projection. Declared on
# ``EdgeType`` and mapped to ``RelationshipLayer.EXCLUDED`` in
# ``shared/graph/relationship_layers.py`` (a derived analytics overlay).
SEMANTIC_EDGE_TYPE = EdgeType.SEMANTIC_RELATES_TO


# The semantic reducer's stable, deterministic pair identity (see
# ``reducers.relationship_ref``). Reused as the edge's ``source_event_id`` /
# ``correlation_id`` so every replica computing the same Gold row derives the
# same idempotency key.
def _relationship_ref_of(data: dict[str, Any], source: str, target: str) -> str:
    rel = data.get("relationship_ref")
    if rel:
        return str(rel)
    return f"rel:{source}->{target}"


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
    failed: int = 0
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "tenant_id": self.tenant_id,
            "relationships_seen": self.relationships_seen,
            "projected": self.projected,
            "skipped_existing": self.skipped_existing,
            "revoked": self.revoked,
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
        source_event_id=rel_ref,
        correlation_id=rel_ref,
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
        "confidence": data.get("confidence"),
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
    seen: dict[tuple[str, str, str], Any] = {}
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
            seen[(edge.edge_type, edge.from_vertex_id, edge.to_vertex_id)] = edge
    return list(seen.values())


async def _revoke_projection(
    gateway: GraphMutationGateway, tenant_id: str, source: str, target: str
) -> None:
    """Soft-revoke one tenant's projected edge through the gateway (never direct)."""
    await gateway.apply(
        revocation_intent(
            from_vertex_id=source,
            to_vertex_id=target,
            edge_type=SEMANTIC_EDGE_TYPE,
            reason="gold_relationship_removed",
            tenant_id=tenant_id,
            actor_kind="system",
            actor_id="semantic_graph_projector",
        )
    )


async def _reconcile_projections(
    graph_client: Any,
    gateway: GraphMutationGateway,
    tenant_id: str,
    expected: dict[tuple[str, str], Edge],
    report: ProjectionReport,
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
            await _revoke_projection(gateway, tenant_id, source, target)
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
        await _revoke_projection(gateway, tenant_id, source, target)
        report.revoked += len(edges)


def _tenant_project_lock(tenant_id: str) -> asyncio.Lock:
    lock = _TENANT_PROJECT_LOCKS.get(tenant_id)
    if lock is None:
        lock = asyncio.Lock()
        _TENANT_PROJECT_LOCKS[tenant_id] = lock
    return lock


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

    async with _tenant_project_lock(tenant_id):
        rows = await repo.list_by_tenant(tenant_id, limit=_GOLD_RELATIONSHIP_READ_LIMIT)
        expected: dict[tuple[str, str], Edge] = {}
        edges_to_write: list[Edge] = []
        for data in rows:
            edge = edge_from_relationship(tenant_id, data)
            if edge is None:
                continue
            report.relationships_seen += 1
            expected[(edge.from_vertex_id, edge.to_vertex_id)] = edge
            edges_to_write.append(edge)
        # Revoke stale / removed / duplicate projections first, then project the
        # current Gold set so each surviving pair ends with exactly one canonical
        # edge (the sweep's idempotency-key check is what "keeps" it).
        await _reconcile_projections(graph_client, gw, tenant_id, expected, report)
        for edge in edges_to_write:
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
                await gw.apply(
                    edge_intent(
                        edge,
                        operation="edge_created",
                        tenant_id=tenant_id,
                        subject_kind="entity",
                        subject_id=edge.to_vertex_id,
                        causality_class="observed_sequence",
                    )
                )
                report.projected += 1
            except Exception as exc:  # noqa: BLE001 — isolate one edge's failure
                report.failed += 1
                report.errors.append(f"{edge.from_vertex_id}->{edge.to_vertex_id}: {exc}")
                metrics.increment("semantic_graph_projection_error_total")
    if report.projected:
        metrics.increment("semantic_graph_edges_projected_total", report.projected)
    if report.revoked:
        metrics.increment("semantic_graph_edges_revoked_total", report.revoked)
    return report


async def project_once() -> list[ProjectionReport]:
    """One projector pass across every tenant with relationship Gold.

    Tenants are enumerated from the durable relationship-Gold table; a deployment
    on the in-memory store (local/CI) has no rows there, so the pass is a no-op —
    matching the flag being off by default.
    """
    tenants = await SemanticFactRepository(reducers._GOLD_RELATIONSHIP_TABLE).distinct_tenants()
    reports: list[ProjectionReport] = []
    for tenant_id in tenants:
        report = await project_tenant(tenant_id)
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
