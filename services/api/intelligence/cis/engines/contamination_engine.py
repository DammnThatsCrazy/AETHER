"""
CIS Contamination Scoring Engine
Origin tracing, recursive hallucination chain detection, unstable agent detection,
and contamination propagation graph construction.

Uses existing GraphTraversalEngine.temporal_bfs() for ancestry traversal.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional, TYPE_CHECKING

from shared.logger.logger import get_logger

if TYPE_CHECKING:
    from shared.cis.clickhouse import ClickHouseClient
    from shared.cis.provenance import ProvenanceTracker

logger = get_logger("aether.cis.contamination_engine")


@dataclass
class ContaminationForensicsReport:
    node_id: str
    tenant_id: str
    origin_nodes: list[dict[str, Any]] = field(default_factory=list)
    propagation_path: list[str] = field(default_factory=list)
    affected_nodes_count: int = 0
    hallucination_chains: list[dict[str, Any]] = field(default_factory=list)
    unstable_agents: list[str] = field(default_factory=list)
    max_contamination_score: float = 0.0
    computed_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


class HallucinationChainDetector:
    """
    Detects recursive ungrounded claim chains where claim_N cites claim_N-1
    with no terminal external source within max_depth hops.
    """

    def __init__(self, max_depth: int = 5) -> None:
        self.max_depth = max_depth

    def detect(
        self,
        generation_id: str,
        citation_graph: dict[str, list[str]],
        external_sources: set[str],
    ) -> list[dict[str, Any]]:
        """
        citation_graph: maps generation_id → list of cited generation_ids
        external_sources: set of IDs known to be externally grounded

        Returns list of detected hallucination chains.
        """
        chains: list[dict[str, Any]] = []
        visited: set[str] = set()

        def _dfs(node: str, path: list[str], depth: int) -> None:
            if depth > self.max_depth or node in visited:
                return
            visited.add(node)
            path = path + [node]
            if node in external_sources:
                return  # grounded — chain terminates safely
            citations = citation_graph.get(node, [])
            if not citations:
                # Terminal ungrounded node — this is the end of a hallucination chain
                if len(path) >= 2:
                    chains.append({
                        "chain": path,
                        "length": len(path),
                        "terminal_node": node,
                    })
                return
            for cited in citations:
                _dfs(cited, path, depth + 1)

        _dfs(generation_id, [], 0)
        return chains


class UnstableAgentDetector:
    """Cross-references cis_mutation_analytics quarantine rate to find unstable agents."""

    def __init__(self, ch_client: "ClickHouseClient") -> None:
        self._ch = ch_client

    async def detect(self, tenant_id: str, min_mutations: int = 5) -> list[str]:
        """Returns agent_ids with quarantine_rate > 50% and >= min_mutations."""
        try:
            rows = await self._ch.query(
                """
                SELECT agent_id,
                       countIf(risk_band = 'quarantine') AS quarantine_count,
                       count() AS total_count
                FROM cis_mutation_analytics
                WHERE tenant_id = {tenant_id:String}
                  AND agent_id != ''
                GROUP BY agent_id
                HAVING total_count >= {min_mutations:Int32}
                   AND quarantine_count / total_count > 0.5
                """,
                {"tenant_id": tenant_id, "min_mutations": min_mutations},
            )
            return [r["agent_id"] for r in rows]
        except Exception as e:
            logger.debug(f"UnstableAgentDetector query failed: {e}")
            return []


class ContaminationEngine:
    """
    Builds contamination forensics reports for a given node.
    Uses existing GraphTraversalEngine.temporal_bfs() for ancestor tracing.
    """

    def __init__(
        self,
        ch_client: "ClickHouseClient",
        provenance_tracker: "ProvenanceTracker",
        graph_client: Optional[Any] = None,
    ) -> None:
        self._ch = ch_client
        self._provenance = provenance_tracker
        self._graph = graph_client
        self._hallucination_detector = HallucinationChainDetector()
        self._unstable_agent_detector = UnstableAgentDetector(ch_client)

    async def build_forensics_report(
        self, node_id: str, tenant_id: str
    ) -> ContaminationForensicsReport:
        report = ContaminationForensicsReport(node_id=node_id, tenant_id=tenant_id)

        # 1. Trace ancestry via graph BFS if graph client is available
        ancestor_ids: list[str] = []
        if self._graph is not None:
            try:
                from shared.graph.traversal import GraphTraversalEngine
                traversal = GraphTraversalEngine(self._graph)
                ancestors = await traversal.temporal_bfs(node_id, depth=5)
                ancestor_ids = [v.vertex_id for v in ancestors if v.vertex_id != node_id]
            except Exception as e:
                logger.debug(f"Graph traversal skipped: {e}")

        # 2. Cross-reference provenance records for contamination
        contaminated_ancestors: list[dict[str, Any]] = []
        for aid in ancestor_ids:
            rec = await self._provenance.get(aid, tenant_id)
            if rec and rec.contamination_score > 0.3:
                contaminated_ancestors.append({
                    "node_id": aid,
                    "contamination_score": rec.contamination_score,
                    "synthetic_flag": rec.synthetic_flag,
                    "origin_agent_id": rec.origin_agent_id,
                })

        contaminated_ancestors.sort(key=lambda x: x["contamination_score"], reverse=True)
        report.origin_nodes = contaminated_ancestors[:10]
        report.propagation_path = [a["node_id"] for a in contaminated_ancestors]
        report.affected_nodes_count = len(ancestor_ids)

        if contaminated_ancestors:
            report.max_contamination_score = contaminated_ancestors[0]["contamination_score"]

        # 3. Detect unstable agents
        report.unstable_agents = await self._unstable_agent_detector.detect(tenant_id)

        # 4. Write propagation record to ClickHouse
        if contaminated_ancestors:
            row = {
                "event_id": str(uuid.uuid4()),
                "tenant_id": tenant_id,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "origin_node_id": contaminated_ancestors[0]["node_id"] if contaminated_ancestors else node_id,
                "affected_node_ids": ancestor_ids[:50],
                "affected_node_count": len(ancestor_ids),
                "propagation_depth": min(5, len(ancestor_ids)),
                "contamination_score": report.max_contamination_score,
                "contamination_type": "ancestry",
                "causality_chain": report.propagation_path[:10],
                "source_agent_id": contaminated_ancestors[0].get("origin_agent_id", "") if contaminated_ancestors else "",
                "resolved": 0,
                "source_service": "cis.contamination_engine",
            }
            await self._ch.insert("cis_contamination_propagation", [row])

        return report
