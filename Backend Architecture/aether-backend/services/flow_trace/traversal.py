"""Flow-of-Funds Trace — BFS traversal engine.

Iteratively explores the transfer graph from an anchor entity, collecting
upstream and downstream paths, identifying source/sink/aggregation nodes,
detecting cycles, and tagging flow patterns.
"""

from __future__ import annotations

import uuid
from collections import deque
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Optional

from repositories.repos import TransferRepository
from services.flow_trace.models import FlowNodeKind, FlowTracePath, FlowTraceNode, PatternTag
from shared.logger.logger import get_logger

logger = get_logger("aether.service.flow_trace")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _to_usd(amount_str: str) -> float:
    try:
        return float(Decimal(str(amount_str)))
    except InvalidOperation:
        return 0.0


class FlowTraceEngine:
    """BFS-based flow-of-funds traversal over the transfer ledger."""

    def __init__(self, transfer_repo: TransferRepository) -> None:
        self._transfers = transfer_repo

    async def trace(
        self,
        tenant_id: str,
        anchor_entity_id: str,
        direction: str = "downstream",
        max_hops: int = 6,
        min_amount_usd: Optional[float] = None,
    ) -> dict[str, Any]:
        """Run a full BFS traversal and return a structured trace result.

        Returns a dict with:
            nodes, paths, source_nodes, sink_nodes, aggregation_points,
            cycle_detected, cycle_nodes, pattern_tags
        """
        nodes: dict[str, FlowTraceNode] = {}
        paths: list[FlowTracePath] = []
        visited_edges: set[tuple[str, str]] = set()
        cycle_nodes: list[str] = []
        cycle_detected = False
        trace_id = str(uuid.uuid4())

        # BFS state: (entity_id, hop, current_path_nodes, current_path_amt)
        queue: deque[tuple[str, int, list[str], float]] = deque()
        queue.append((anchor_entity_id, 0, [anchor_entity_id], 0.0))
        visited_bfs: dict[str, int] = {anchor_entity_id: 0}  # entity_id → min hop reached

        # Register anchor node
        nodes[anchor_entity_id] = FlowTraceNode(
            id=str(uuid.uuid4()),
            entity_id=anchor_entity_id,
            entity_type="user",
            hop=0,
            total_received_usd=0.0,
            total_sent_usd=0.0,
        )

        while queue:
            current_id, hop, path_nodes, path_amt = queue.popleft()

            if hop >= max_hops:
                continue

            # Fetch outbound transfers if going downstream or both
            if direction in ("downstream", "both"):
                outbound = await self._transfers.find_many(
                    filters={"from_entity_id": current_id, "tenant_id": tenant_id},
                    limit=200,
                )
                for t in outbound:
                    dst = t.get("to_entity_id", "")
                    if not dst:
                        continue
                    amt = _to_usd(t.get("amount", "0"))
                    if min_amount_usd is not None and amt < min_amount_usd:
                        continue

                    edge_key = (current_id, dst)
                    if edge_key in visited_edges:
                        continue
                    visited_edges.add(edge_key)

                    # Update destination node stats
                    if dst not in nodes:
                        nodes[dst] = FlowTraceNode(
                            id=str(uuid.uuid4()),
                            entity_id=dst,
                            entity_type="user",
                            hop=hop + 1,
                            total_received_usd=0.0,
                            total_sent_usd=0.0,
                        )
                    nodes[dst].total_received_usd += amt
                    if current_id in nodes:
                        nodes[current_id].total_sent_usd += amt

                    new_path = path_nodes + [dst]
                    new_amt = path_amt + amt

                    if dst in path_nodes:
                        # Cycle detected
                        cycle_detected = True
                        cycle_start = path_nodes.index(dst)
                        cycle_nodes = list(dict.fromkeys(path_nodes[cycle_start:] + [dst]))
                        paths.append(FlowTracePath(
                            id=str(uuid.uuid4()),
                            trace_id=trace_id,
                            path_nodes=new_path,
                            path_edges=[],
                            hop_count=len(new_path) - 1,
                            total_amount_usd=new_amt,
                            risk_score=0.0,
                            pattern_tags=["round_trip"],
                            contains_cycle=True,
                            passes_through_sink=False,
                            passes_through_source=False,
                            discovered_at=_utc_now(),
                        ))
                        continue

                    if hop + 1 <= visited_bfs.get(dst, 9999):
                        visited_bfs[dst] = hop + 1
                        queue.append((dst, hop + 1, new_path, new_amt))

            # Fetch inbound transfers if going upstream or both
            if direction in ("upstream", "both"):
                inbound = await self._transfers.find_many(
                    filters={"to_entity_id": current_id, "tenant_id": tenant_id},
                    limit=200,
                )
                for t in inbound:
                    src = t.get("from_entity_id", "")
                    if not src:
                        continue
                    amt = _to_usd(t.get("amount", "0"))
                    if min_amount_usd is not None and amt < min_amount_usd:
                        continue

                    edge_key = (src, current_id)
                    if edge_key in visited_edges:
                        continue
                    visited_edges.add(edge_key)

                    if src not in nodes:
                        nodes[src] = FlowTraceNode(
                            id=str(uuid.uuid4()),
                            entity_id=src,
                            entity_type="user",
                            hop=hop + 1,
                            total_received_usd=0.0,
                            total_sent_usd=0.0,
                        )
                    nodes[src].total_sent_usd += amt
                    if current_id in nodes:
                        nodes[current_id].total_received_usd += amt

                    new_path = [src] + path_nodes
                    new_amt = path_amt + amt

                    if src in path_nodes:
                        cycle_detected = True
                        cycle_nodes = list(dict.fromkeys([src] + path_nodes))
                        continue

                    if hop + 1 <= visited_bfs.get(src, 9999):
                        visited_bfs[src] = hop + 1
                        queue.append((src, hop + 1, new_path, new_amt))

        # Identify structural nodes
        source_nodes = self._identify_sources(nodes, anchor_entity_id)
        sink_nodes = self._identify_sinks(nodes, anchor_entity_id)
        aggregation_points = self._identify_aggregation_points(nodes)

        # Build terminal paths (leaf-to-anchor or anchor-to-leaf)
        if not paths:
            for node_id, node in nodes.items():
                if node_id == anchor_entity_id:
                    continue
                path_data = [anchor_entity_id, node_id] if direction == "downstream" else [node_id, anchor_entity_id]
                paths.append(FlowTracePath(
                    id=str(uuid.uuid4()),
                    trace_id=trace_id,
                    path_nodes=path_data,
                    path_edges=[],
                    hop_count=node.hop,
                    total_amount_usd=node.total_received_usd + node.total_sent_usd,
                    risk_score=0.0,
                    pattern_tags=self._tag_patterns(node, sink_nodes, source_nodes, cycle_detected),
                    contains_cycle=False,
                    passes_through_sink=node_id in sink_nodes,
                    passes_through_source=node_id in source_nodes,
                    discovered_at=_utc_now(),
                ))

        pattern_tags = list({tag for p in paths for tag in p.pattern_tags})

        return {
            "trace_id": trace_id,
            "nodes": list(nodes.values()),
            "paths": paths,
            "source_nodes": source_nodes,
            "sink_nodes": sink_nodes,
            "aggregation_points": aggregation_points,
            "cycle_detected": cycle_detected,
            "cycle_nodes": cycle_nodes,
            "pattern_tags": pattern_tags,
        }

    def _identify_sources(self, nodes: dict[str, FlowTraceNode], anchor_id: str) -> list[str]:
        """Source nodes: high out-flow, low in-flow (injection points)."""
        sources = []
        for eid, node in nodes.items():
            if eid == anchor_id:
                continue
            if node.total_sent_usd > 0 and node.total_received_usd == 0:
                sources.append(eid)
            elif node.total_sent_usd > 0 and node.total_sent_usd > node.total_received_usd * 2:
                sources.append(eid)
        return sources

    def _identify_sinks(self, nodes: dict[str, FlowTraceNode], anchor_id: str) -> list[str]:
        """Sink nodes: high in-flow, zero or minimal out-flow (final recipients)."""
        sinks = []
        for eid, node in nodes.items():
            if eid == anchor_id:
                continue
            if node.total_received_usd > 0 and node.total_sent_usd == 0:
                sinks.append(eid)
            elif node.total_received_usd > 0 and node.total_received_usd > node.total_sent_usd * 2:
                sinks.append(eid)
        return sinks

    def _identify_aggregation_points(self, nodes: dict[str, FlowTraceNode]) -> list[str]:
        """Aggregation points: receive from many, send to few (converging flows)."""
        # Proxy: nodes with high total received and total sent (both non-zero)
        aggregation = []
        for eid, node in nodes.items():
            if node.total_received_usd > 0 and node.total_sent_usd > 0:
                ratio = node.total_received_usd / max(node.total_sent_usd, 1.0)
                if 0.5 < ratio < 2.0 and (node.total_received_usd + node.total_sent_usd) > 0:
                    aggregation.append(eid)
        return aggregation

    def _tag_patterns(
        self,
        node: FlowTraceNode,
        sink_nodes: list[str],
        source_nodes: list[str],
        cycle_detected: bool,
    ) -> list[PatternTag]:
        """Tag a single path node with applicable pattern labels."""
        tags: list[PatternTag] = []
        if cycle_detected:
            tags.append("round_trip")
        if node.entity_id in sink_nodes:
            tags.append("mule_chain")
        if node.entity_id in source_nodes and node.total_sent_usd > 10_000:
            tags.append("dispersion")
        if node.total_received_usd > 0 and node.total_sent_usd > 0:
            if abs(node.total_received_usd - node.total_sent_usd) / max(node.total_received_usd, 1) < 0.05:
                tags.append("layering")
        return tags
