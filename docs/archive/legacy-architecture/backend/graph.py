"""
Aether Shared — @aether/graph
Neptune/Neo4j query builders, graph traversal helpers, vertex/edge factories.
Used by: Identity, Analytics, Agent services.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from shared.logger.logger import get_logger

logger = get_logger("aether.graph")


# ═══════════════════════════════════════════════════════════════════════════
# VERTEX & EDGE TYPES (from spec Section 4)
# ═══════════════════════════════════════════════════════════════════════════

class VertexType:
    USER = "User"
    SESSION = "Session"
    PAGE_VIEW = "PageView"
    EVENT = "Event"
    DEVICE = "Device"
    COMPANY = "Company"
    CAMPAIGN = "Campaign"
    EXTERNAL_DATA = "ExternalData"
    # Multi-actor journey v1
    ACTOR = "Actor"
    JOURNEY = "Journey"
    DELEGATION = "Delegation"


class EdgeType:
    HAS_SESSION = "HAS_SESSION"
    VIEWED_PAGE = "VIEWED_PAGE"
    TRIGGERED_EVENT = "TRIGGERED_EVENT"
    USED_DEVICE = "USED_DEVICE"
    BELONGS_TO = "BELONGS_TO"
    ATTRIBUTED_TO = "ATTRIBUTED_TO"
    RESOLVED_AS = "RESOLVED_AS"
    ENRICHED_BY = "ENRICHED_BY"
    # Multi-actor journey v1
    REPRESENTS = "REPRESENTS"          # Actor -> User (typed projection)
    OWNS = "OWNS"                      # Actor -> Actor
    DELEGATES_TO = "DELEGATES_TO"      # Actor -> Actor
    MANAGES = "MANAGES"                # Actor -> Actor
    COLLABORATES_WITH = "COLLABORATES_WITH"
    HAS_JOURNEY = "HAS_JOURNEY"        # Actor -> Journey
    CONTAINS_SESSION = "CONTAINS_SESSION"  # Journey -> Session
    PRECEDED_BY = "PRECEDED_BY"        # Journey -> Journey
    CONTINUED_FROM = "CONTINUED_FROM"  # Journey -> Journey
    TRIGGERED_BY = "TRIGGERED_BY"      # Event -> Event (causality)
    INFLUENCED_BY = "INFLUENCED_BY"    # Event -> Event (causality)


# ═══════════════════════════════════════════════════════════════════════════
# VERTEX / EDGE FACTORIES
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class Vertex:
    vertex_type: str
    vertex_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    properties: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_gremlin(self) -> str:
        """Generate a Gremlin addV() traversal string."""
        props = "".join(
            f".property('{k}', '{v}')" for k, v in self.properties.items()
        )
        return (
            f"g.addV('{self.vertex_type}')"
            f".property('id', '{self.vertex_id}')"
            f".property('created_at', '{self.created_at}')"
            f"{props}"
        )


@dataclass
class Edge:
    edge_type: str
    from_vertex_id: str
    to_vertex_id: str
    properties: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_gremlin(self) -> str:
        """Generate a Gremlin addE() traversal string."""
        props = "".join(
            f".property('{k}', '{v}')" for k, v in self.properties.items()
        )
        return (
            f"g.V('{self.from_vertex_id}')"
            f".addE('{self.edge_type}')"
            f".to(g.V('{self.to_vertex_id}'))"
            f".property('created_at', '{self.created_at}')"
            f"{props}"
        )


# ═══════════════════════════════════════════════════════════════════════════
# GRAPH CLIENT (stub — replace with gremlinpython or Neptune SDK)
# ═══════════════════════════════════════════════════════════════════════════

class GraphClient:
    """
    Stub graph client. In production, use gremlinpython connecting to Neptune.
    """

    def __init__(self):
        self._vertices: dict[str, Vertex] = {}
        self._edges: list[Edge] = []

    async def add_vertex(self, vertex: Vertex) -> str:
        self._vertices[vertex.vertex_id] = vertex
        logger.info(f"Graph ADD_V {vertex.vertex_type} id={vertex.vertex_id}")
        return vertex.vertex_id

    async def add_edge(self, edge: Edge) -> None:
        self._edges.append(edge)
        logger.info(
            f"Graph ADD_E {edge.edge_type} "
            f"{edge.from_vertex_id} → {edge.to_vertex_id}"
        )

    async def get_vertex(self, vertex_id: str) -> Optional[Vertex]:
        return self._vertices.get(vertex_id)

    async def get_neighbors(
        self,
        vertex_id: str,
        edge_type: Optional[str] = None,
        direction: str = "out",  # "out", "in", "both"
    ) -> list[Vertex]:
        """Traverse edges from a vertex."""
        results = []
        for edge in self._edges:
            match = False
            if direction in ("out", "both") and edge.from_vertex_id == vertex_id:
                if edge_type is None or edge.edge_type == edge_type:
                    target = self._vertices.get(edge.to_vertex_id)
                    if target:
                        results.append(target)
            if direction in ("in", "both") and edge.to_vertex_id == vertex_id:
                if edge_type is None or edge.edge_type == edge_type:
                    target = self._vertices.get(edge.from_vertex_id)
                    if target:
                        results.append(target)
        return results

    async def query(self, gremlin: str) -> list[dict]:
        """Execute a raw Gremlin query. Stub returns empty."""
        logger.info(f"Graph QUERY: {gremlin[:100]}...")
        # --- PRODUCTION ---
        # return await self._connection.submit(gremlin)
        return []

    async def upsert_vertex(self, vertex: Vertex) -> str:
        """Insert or update a vertex by ID."""
        existing = self._vertices.get(vertex.vertex_id)
        if existing:
            existing.properties.update(vertex.properties)
            logger.info(f"Graph UPSERT_V (updated) {vertex.vertex_id}")
        else:
            await self.add_vertex(vertex)
        return vertex.vertex_id
