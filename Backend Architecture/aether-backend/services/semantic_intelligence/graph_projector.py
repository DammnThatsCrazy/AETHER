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
  :func:`edge_intent`. The gateway's mode (``off`` / ``shadow`` / ``enforce``,
  from ``settings.temporal_observatory.mutation_gateway_mode``) decides whether
  the mutation is also recorded in the append-only ledger — the projector never
  bypasses that. In ``off`` (the default) the edge is projected to the graph
  without a ledger row; in ``shadow`` / ``enforce`` it flows through the ledger.
* ``SEMANTIC_RELATES_TO`` is mapped to the ``EXCLUDED`` relationship layer (a
  derived analytics overlay, not a human/agent interaction), so enforce-mode
  validation does not require a consent purpose.
* The pass is idempotent: an edge already present for ``(tenant, source,
  target)`` is skipped, so repeated sweeps never duplicate. Re-projecting an
  updated Gold revision as a versioned edge is a deliberate follow-up.
* Tenant isolation: every edge carries the tenant on both ``tenantId`` and
  ``tenant_id`` properties and the idempotency read filters on it, so one
  tenant's projection never matches another's edge.
"""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass, field
from typing import Any, Optional

from shared.graph.graph import Edge, EdgeType, get_graph_client
from shared.graph.mutation_gateway import GraphMutationGateway
from shared.graph.mutation_intents import edge_intent
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


@dataclass
class ProjectionReport:
    """Per-tenant projector outcome."""

    tenant_id: str
    relationships_seen: int = 0
    projected: int = 0
    skipped_existing: int = 0
    failed: int = 0
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "tenant_id": self.tenant_id,
            "relationships_seen": self.relationships_seen,
            "projected": self.projected,
            "skipped_existing": self.skipped_existing,
            "failed": self.failed,
            "errors": self.errors[:10],
        }


def _tenant_of(props: dict[str, Any]) -> str:
    return str(props.get("tenantId") or props.get("tenant_id") or "")


def edge_from_relationship(tenant_id: str, data: dict[str, Any]) -> Optional[Edge]:
    """Build the governed edge for one ``gold_relationship_semantic_state`` row.

    Returns ``None`` when the row cannot be projected (missing/degenerate
    endpoints), never a partial edge.
    """
    source = str(data.get("source_ref") or "").strip()
    target = str(data.get("target_ref") or "").strip()
    if not source or not target or source == target:
        return None
    if _UNKNOWN_SUBJECT in (source, target):
        return None
    props: dict[str, Any] = {
        "tenantId": tenant_id,
        "tenant_id": tenant_id,
        "relationship_ref": data.get("relationship_ref"),
        "relationship_layer": data.get("relationship_layer"),
        "stance_alignment": data.get("stance_alignment"),
        "trust_signal": data.get("trust_signal"),
        "interaction_quality": data.get("interaction_quality"),
        "influence_direction": data.get("influence_direction"),
        "confidence": data.get("confidence"),
        "valid_from": data.get("valid_from"),
        "reducer_version": data.get("reducer_version"),
    }
    props = {k: v for k, v in props.items() if v is not None}
    return Edge(
        edge_type=SEMANTIC_EDGE_TYPE,
        from_vertex_id=source,
        to_vertex_id=target,
        properties=props,
    )


async def _already_projected(
    graph_client: Any, tenant_id: str, source: str, target: str
) -> bool:
    """True when this tenant already has a semantic edge ``source -> target``."""
    existing = await graph_client.get_edges(source, edge_type=SEMANTIC_EDGE_TYPE)
    return any(
        e.to_vertex_id == target and _tenant_of(e.properties or {}) == tenant_id
        for e in existing
    )


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
    """
    graph_client = graph_client or get_graph_client()
    gw = gateway or GraphMutationGateway(graph_client=graph_client)
    repo = SemanticFactRepository(reducers._GOLD_RELATIONSHIP_TABLE, mode="gold")
    report = ProjectionReport(tenant_id=tenant_id)

    for data in await repo.list_by_tenant(tenant_id):
        edge = edge_from_relationship(tenant_id, data)
        if edge is None:
            continue
        report.relationships_seen += 1
        try:
            if await _already_projected(
                graph_client, tenant_id, edge.from_vertex_id, edge.to_vertex_id
            ):
                report.skipped_existing += 1
                continue
            await gw.apply(
                edge_intent(
                    edge,
                    operation="edge_created",
                    tenant_id=tenant_id,
                    actor_kind="system",
                    actor_id="semantic_graph_projector",
                    subject_kind="entity",
                    subject_id=edge.to_vertex_id,
                    source_event_id=str(edge.properties.get("relationship_ref") or ""),
                    causality_class="observed_sequence",
                    confidence=edge.properties.get("confidence"),
                )
            )
            report.projected += 1
        except Exception as exc:  # noqa: BLE001 — isolate one edge's failure
            report.failed += 1
            report.errors.append(f"{edge.from_vertex_id}->{edge.to_vertex_id}: {exc}")
            metrics.increment("semantic_graph_projection_error_total")
    if report.projected:
        metrics.increment("semantic_graph_edges_projected_total", report.projected)
    return report


async def project_once() -> list[ProjectionReport]:
    """One projector pass across every tenant with relationship Gold.

    Tenants are enumerated from the durable relationship-Gold table; a deployment
    on the in-memory store (local/CI) has no rows there, so the pass is a no-op —
    matching the flag being off by default.
    """
    tenants = await SemanticFactRepository(
        reducers._GOLD_RELATIONSHIP_TABLE
    ).distinct_tenants()
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
    interval = int(
        interval_seconds if interval_seconds is not None else _PROJECT_INTERVAL_S
    )
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
