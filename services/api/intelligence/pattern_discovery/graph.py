"""Graph reads for motif discovery and governed graph promotion.

**Reads.** :func:`tenant_graph_edges` pulls the tenant's canonical graph
edges (bounded, revoked edges excluded) and labels each endpoint with its
vertex type, so the motif detector looks for unregistered structure in the
real graph, not only in edges derived from this window's events.

**Promotion.** When a reviewer promotes a pattern, :func:`project_promotion`
writes graph intelligence through the canonical
:class:`~shared.graph.mutation_gateway.GraphMutationGateway` (never directly):

* one ``RiskCluster`` vertex per pattern, ``claim_state: attributed``,
  carrying the pattern id, kind, verdict and evidence fingerprint;
* one ``MEMBER_OF_CLUSTER`` edge from each *canonical, consented* subject the
  Risk360 promotion resolved, ``causality_class: inferred_influence``.

Only subjects that got a Risk360 signal get an edge, so the graph never holds
a membership the risk plane refused (unresolved identity or withheld consent).
Deprecating a promoted pattern soft-revokes those edges
(:func:`revoke_promotion`). Writes are idempotent: the vertex id and edge
idempotency keys derive from the pattern and subject.
"""
from __future__ import annotations

from typing import Any, Optional

from shared.logger.logger import get_logger

from .contracts import content_hash

logger = get_logger("aether.pattern_discovery.graph")

EDGE_TYPE = "MEMBER_OF_CLUSTER"
MAX_GRAPH_EDGES = 20_000
ACTOR = "pattern_discovery"


def cluster_vertex_id(pattern_id: str) -> str:
    return f"pdc_{content_hash(pattern_id, 24)}"


async def tenant_graph_edges(tenant_id: str, graph: Optional[Any] = None,
                             limit: int = MAX_GRAPH_EDGES) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Canonical tenant edges as motif input, plus a coverage report."""
    if graph is None:
        from shared.graph.graph import get_graph_client

        graph = get_graph_client()
    try:
        edges, truncated = await graph.get_edges_for_tenant(tenant_id, limit=limit)
        vertices = await graph.get_vertices_for_tenant(tenant_id, limit=limit)
    except Exception as exc:  # noqa: BLE001 - the graph is context, not a dependency
        logger.warning("pattern_discovery.graph_read_failed",
                       extra={"tenant_id": tenant_id, "error_type": type(exc).__name__})
        return [], {"graph": "unavailable", "error_type": type(exc).__name__}
    kinds = {v.vertex_id: str(v.vertex_type or "vertex").lower() for v in vertices}
    out = []
    for e in edges:
        # Discovery's own promotion edges are not evidence for discovery.
        if (e.properties or {}).get("source") == ACTOR:
            continue
        out.append({
            "source": e.from_vertex_id, "target": e.to_vertex_id, "type": e.edge_type,
            "source_kind": kinds.get(e.from_vertex_id, "vertex"),
            "target_kind": kinds.get(e.to_vertex_id, "vertex"),
        })
    return out, {"graph": "ok", "edges": len(out), "truncated": bool(truncated), "vertices": len(kinds)}


async def project_promotion(pattern: dict[str, Any], risk_outcomes: list[dict[str, Any]],
                            graph: Optional[Any] = None) -> dict[str, Any]:
    """Write the promoted pattern into the graph. Returns a report; never raises."""
    from shared.graph.edge_properties import build_edge_properties
    from shared.graph.graph import Edge, Vertex, VertexType, get_graph_client
    from shared.graph.mutation_gateway import GraphMutationGateway
    from shared.graph.mutation_intents import edge_intent, vertex_intent

    graph = graph or get_graph_client()
    tenant_id = pattern["tenant_id"]
    vid = cluster_vertex_id(pattern["pattern_id"])
    members = [o for o in risk_outcomes if o.get("status") == "written" and o.get("subject_id")]
    promoted_at = (pattern.get("promotion") or {}).get("promoted_at") or pattern.get("last_observed_at") or ""
    try:
        gateway = GraphMutationGateway(graph_client=graph)
        await gateway.apply(vertex_intent(
            Vertex(vertex_type=VertexType.RISK_CLUSTER, vertex_id=vid, properties={
                "tenant_id": tenant_id, "source": ACTOR, "pattern_id": pattern["pattern_id"],
                "pattern_kind": pattern.get("kind"), "claim_state": "attributed",
                "verdict": (pattern.get("promotion") or {}).get("verdict"),
                "evidence_fingerprint": pattern.get("evidence_fingerprint"),
                "title": str(pattern.get("title", ""))[:200],
            }),
            operation="node_versioned", tenant_id=tenant_id, actor_id=ACTOR,
            idempotency_key=f"{vid}:{pattern.get('evidence_fingerprint')}",
            causality_class="inferred_influence", reason_code="pattern_promoted",
        ))
        written = 0
        for m in members:
            props = build_edge_properties(
                tenant_id=tenant_id, edge_type=EDGE_TYPE, from_vertex_id=m["subject_id"], to_vertex_id=vid,
                actor_kind="system", actor_id=ACTOR, provenance="pattern_discovery_promotion",
                valid_from=promoted_at, confidence=float(pattern.get("confidence") or 0.0),
                source_event_id=pattern["pattern_id"], consent_purpose="analytics",
                provenance_class="derived", source=ACTOR, pattern_id=pattern["pattern_id"],
                claim_state="attributed", consent_receipt_id=m.get("consent_receipt_id") or "",
            )
            await gateway.apply(edge_intent(
                Edge(edge_type=EDGE_TYPE, from_vertex_id=m["subject_id"], to_vertex_id=vid, properties=props),
                operation="edge_created", tenant_id=tenant_id, actor_id=ACTOR,
                subject_kind=m.get("subject_kind"), subject_id=m["subject_id"],
                causality_class="inferred_influence", reason_code="pattern_promoted",
                confidence=float(pattern.get("confidence") or 0.0),
            ))
            written += 1
    except Exception as exc:  # noqa: BLE001 - graph projection never fails the promotion
        logger.warning("pattern_discovery.graph_projection_failed",
                       extra={"tenant_id": tenant_id, "error_type": type(exc).__name__})
        return {"status": "failed", "vertex_id": vid, "error_type": type(exc).__name__}
    return {"status": "projected", "vertex_id": vid, "edges": written,
            "skipped_subjects": len(risk_outcomes) - len(members)}


async def revoke_promotion(pattern: dict[str, Any], graph: Optional[Any] = None) -> dict[str, Any]:
    """Soft-revoke the membership edges of a promoted pattern being deprecated."""
    from shared.graph.graph import get_graph_client
    from shared.graph.mutation_gateway import GraphMutationGateway
    from shared.graph.mutation_intents import revocation_intent

    promotion = pattern.get("promotion") or {}
    projection = promotion.get("graph_projection") or {}
    if projection.get("status") != "projected":
        return {"status": "nothing_to_revoke"}
    graph = graph or get_graph_client()
    vid = projection["vertex_id"]
    revoked = 0
    try:
        gateway = GraphMutationGateway(graph_client=graph)
        for o in promotion.get("risk_signals") or []:
            if o.get("status") != "written" or not o.get("subject_id"):
                continue
            await gateway.apply(revocation_intent(
                from_vertex_id=o["subject_id"], to_vertex_id=vid, edge_type=EDGE_TYPE,
                reason="pattern_deprecated", tenant_id=pattern["tenant_id"], actor_id=ACTOR,
                subject_kind=o.get("subject_kind"), subject_id=o["subject_id"],
                reason_code="pattern_deprecated",
            ))
            revoked += 1
    except Exception as exc:  # noqa: BLE001
        logger.warning("pattern_discovery.graph_revoke_failed",
                       extra={"tenant_id": pattern.get("tenant_id"), "error_type": type(exc).__name__})
        return {"status": "failed", "error_type": type(exc).__name__, "revoked": revoked}
    return {"status": "revoked", "revoked": revoked, "vertex_id": vid}
