"""Risk Overlay — async graph overlay builders.

Assembles Cytoscape-ready payloads from fraud network or flow trace repo data,
mapping entity members/nodes to risk-scored graph objects.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from repositories.repos import (
    FlowTracePathRepository,
    FlowTraceRepository,
    FraudNetworkEdgeRepository,
    FraudNetworkMemberRepository,
    FraudNetworkRepository,
)
from services.risk_overlay.models import RiskGraphEdge, RiskGraphNode, RiskOverlayGraph
from shared.logger.logger import get_logger

logger = get_logger("aether.service.risk_overlay")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def build_fraud_overlay(
    tenant_id: str,
    network_id: str,
) -> RiskOverlayGraph:
    """Build a risk overlay graph from a fraud network.

    Fetches members and edges from the fraud network repos and
    constructs RiskGraphNode/RiskGraphEdge objects suitable for
    Cytoscape rendering with risk score heat-mapping.
    """
    network_repo = FraudNetworkRepository()
    member_repo = FraudNetworkMemberRepository()
    edge_repo = FraudNetworkEdgeRepository()

    network = await network_repo.get(network_id)
    if not network or network.get("tenant_id") != tenant_id:
        logger.warning("fraud_overlay_network_not_found", extra={"network_id": network_id})
        return RiskOverlayGraph(
            nodes=[], edges=[], node_count=0, edge_count=0,
            overlay_risk_score=0.0, computed_at=_utc_now(),
        )

    member_rows = await member_repo.list_by_network(network_id)
    edge_rows = await edge_repo.list_by_network(network_id)
    anchor_ids = set(network.get("anchor_entity_ids", []))
    sink_ids: set[str] = set()
    source_ids: set[str] = set()

    # Infer sources/sinks from edge direction patterns
    out_entities = {e.get("from_entity_id", "") for e in edge_rows}
    in_entities = {e.get("to_entity_id", "") for e in edge_rows}
    for eid in in_entities - out_entities:
        sink_ids.add(eid)
    for eid in out_entities - in_entities:
        source_ids.add(eid)

    nodes: list[RiskGraphNode] = []
    for m in member_rows:
        eid = m.get("entity_id", "")
        nodes.append(RiskGraphNode(
            id=eid,
            entity_id=eid,
            entity_type=m.get("entity_type", "user"),
            label=f"{m.get('entity_type', 'user')}:{eid[:8]}",
            risk_score=m.get("risk_score", 0.0),
            confidence=m.get("confidence", 0.0),
            role=m.get("role", "unknown"),
            is_source=eid in source_ids,
            is_sink=eid in sink_ids,
            metadata={"is_anchor": eid in anchor_ids},
        ))

    edges: list[RiskGraphEdge] = []
    for e in edge_rows:
        edges.append(RiskGraphEdge(
            id=e.get("id", str(uuid.uuid4())),
            source=e.get("from_entity_id", ""),
            target=e.get("to_entity_id", ""),
            edge_type=e.get("edge_type", "TRANSFERRED"),
            risk_score=e.get("risk_score", 0.0),
            transfer_count=e.get("transfer_count", 0),
            metadata=e.get("metadata", {}),
        ))

    overlay_risk = network.get("risk_score", 0.0)

    return RiskOverlayGraph(
        nodes=nodes,
        edges=edges,
        node_count=len(nodes),
        edge_count=len(edges),
        overlay_risk_score=overlay_risk,
        computed_at=_utc_now(),
    )


async def build_flow_overlay(
    tenant_id: str,
    trace_id: str,
) -> RiskOverlayGraph:
    """Build a risk overlay graph from a flow trace.

    Reconstructs the traversal graph from persisted path data,
    scoring each node by its participation in high-risk paths.
    """
    trace_repo = FlowTraceRepository()
    path_repo = FlowTracePathRepository()

    trace = await trace_repo.get(trace_id)
    if not trace or trace.get("tenant_id") != tenant_id:
        logger.warning("flow_overlay_trace_not_found", extra={"trace_id": trace_id})
        return RiskOverlayGraph(
            nodes=[], edges=[], node_count=0, edge_count=0,
            overlay_risk_score=0.0, computed_at=_utc_now(),
        )

    path_rows = await path_repo.list_by_trace(trace_id)

    # Aggregate risk across all paths per node
    node_risk: dict[str, list[float]] = {}
    edges_seen: dict[tuple[str, str], RiskGraphEdge] = {}

    source_ids = set(trace.get("source_nodes", []))
    sink_ids = set(trace.get("sink_nodes", []))
    anchor_id = trace.get("anchor_entity_id", "")

    for path in path_rows:
        path_nodes = path.get("path_nodes", [])
        path_risk = path.get("risk_score", 0.0)
        for node_id in path_nodes:
            node_risk.setdefault(node_id, []).append(path_risk)
        for i in range(len(path_nodes) - 1):
            src, dst = path_nodes[i], path_nodes[i + 1]
            edge_key = (src, dst)
            if edge_key not in edges_seen:
                edges_seen[edge_key] = RiskGraphEdge(
                    id=str(uuid.uuid4()),
                    source=src,
                    target=dst,
                    edge_type="PART_OF_FLOW_TRACE",
                    risk_score=path_risk,
                    transfer_count=1,
                )
            else:
                existing = edges_seen[edge_key]
                existing.transfer_count += 1
                existing.risk_score = max(existing.risk_score, path_risk)

    nodes: list[RiskGraphNode] = []
    for node_id, risks in node_risk.items():
        avg_risk = sum(risks) / len(risks)
        nodes.append(RiskGraphNode(
            id=node_id,
            entity_id=node_id,
            entity_type="user",
            label=f"entity:{node_id[:8]}",
            risk_score=round(avg_risk, 4),
            confidence=1.0,
            is_source=node_id in source_ids,
            is_sink=node_id in sink_ids,
            metadata={"is_anchor": node_id == anchor_id},
        ))

    overlay_risk = trace.get("risk_score", 0.0)

    return RiskOverlayGraph(
        nodes=nodes,
        edges=list(edges_seen.values()),
        node_count=len(nodes),
        edge_count=len(edges_seen),
        overlay_risk_score=overlay_risk,
        computed_at=_utc_now(),
    )
