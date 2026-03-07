"""
Aether Shared — @aether/graph
Neptune/Neo4j query builders, graph traversal helpers, vertex/edge factories.
Used by: Identity, Analytics, Agent services.
"""

from __future__ import annotations

import re
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

    # Identity Resolution
    DEVICE_FINGERPRINT = "DeviceFingerprint"
    IP_ADDRESS = "IPAddress"
    LOCATION = "Location"
    EMAIL = "Email"
    PHONE = "Phone"
    WALLET = "Wallet"
    IDENTITY_CLUSTER = "IdentityCluster"

    # Intelligence Graph — Actor nodes
    AGENT = "Agent"
    SERVICE = "Service"
    CONTRACT = "Contract"
    PROTOCOL = "Protocol"

    # Intelligence Graph — Record nodes
    PAYMENT = "Payment"
    ACTION_RECORD = "ActionRecord"


class EdgeType:
    HAS_SESSION = "HAS_SESSION"
    VIEWED_PAGE = "VIEWED_PAGE"
    TRIGGERED_EVENT = "TRIGGERED_EVENT"
    USED_DEVICE = "USED_DEVICE"
    BELONGS_TO = "BELONGS_TO"
    ATTRIBUTED_TO = "ATTRIBUTED_TO"
    RESOLVED_AS = "RESOLVED_AS"
    ENRICHED_BY = "ENRICHED_BY"

    # Identity Resolution
    HAS_FINGERPRINT = "HAS_FINGERPRINT"
    SEEN_FROM_IP = "SEEN_FROM_IP"
    LOCATED_IN = "LOCATED_IN"
    HAS_EMAIL = "HAS_EMAIL"
    HAS_PHONE = "HAS_PHONE"
    OWNS_WALLET = "OWNS_WALLET"
    MEMBER_OF_CLUSTER = "MEMBER_OF_CLUSTER"
    SIMILAR_TO = "SIMILAR_TO"
    IP_MAPS_TO = "IP_MAPS_TO"

    # Intelligence Graph — Human-to-Agent (H2A)
    LAUNCHED_BY = "LAUNCHED_BY"           # Agent → User who created it
    DELEGATES = "DELEGATES"               # User → Agent (task delegation)
    INTERACTS_WITH = "INTERACTS_WITH"     # User → Protocol

    # Intelligence Graph — Economic edges
    PAYS = "PAYS"                         # Agent/User → Agent/Service
    CONSUMES = "CONSUMES"                 # Agent → Service (API consumption)
    HIRED = "HIRED"                       # Agent → Agent (task hiring)

    # Intelligence Graph — Protocol / On-Chain (A2A)
    DEPLOYED = "DEPLOYED"                 # Agent → Contract
    CALLED = "CALLED"                     # Agent/User → Contract
    COMPOSED_WITH = "COMPOSED_WITH"       # Contract → Contract
    UPGRADED = "UPGRADED"                 # Contract → Contract (proxy upgrade)
    GOVERNED_BY = "GOVERNED_BY"           # Protocol → Contract (governance)
    DEPENDS_ON = "DEPENDS_ON"             # Agent → Agent (dependency)

    # Intelligence Graph — Action tracking
    PERFORMED_ACTION = "PERFORMED_ACTION"  # Agent → ActionRecord


# ═══════════════════════════════════════════════════════════════════════════
# SAFE VALUE ESCAPING
# ═══════════════════════════════════════════════════════════════════════════

_GREMLIN_UNSAFE = re.compile(r"['\"\\\x00-\x1f`;]")


def _escape_gremlin(value: Any) -> str:
    """Escape a value for safe Gremlin string interpolation."""
    s = str(value)
    return _GREMLIN_UNSAFE.sub(lambda m: "\\" + m.group(0), s)


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
        """Generate a Gremlin addV() traversal string with escaped values."""
        props = "".join(
            f".property('{_escape_gremlin(k)}', '{_escape_gremlin(v)}')"
            for k, v in self.properties.items()
        )
        return (
            f"g.addV('{_escape_gremlin(self.vertex_type)}')"
            f".property('id', '{_escape_gremlin(self.vertex_id)}')"
            f".property('created_at', '{_escape_gremlin(self.created_at)}')"
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
        """Generate a Gremlin addE() traversal string with escaped values."""
        props = "".join(
            f".property('{_escape_gremlin(k)}', '{_escape_gremlin(v)}')"
            for k, v in self.properties.items()
        )
        return (
            f"g.V('{_escape_gremlin(self.from_vertex_id)}')"
            f".addE('{_escape_gremlin(self.edge_type)}')"
            f".to(g.V('{_escape_gremlin(self.to_vertex_id)}'))"
            f".property('created_at', '{_escape_gremlin(self.created_at)}')"
            f"{props}"
        )


# ═══════════════════════════════════════════════════════════════════════════
# GRAPH CLIENT (stub — replace with gremlinpython or Neptune SDK)
# ═══════════════════════════════════════════════════════════════════════════

class GraphClient:
    """
    Stub graph client with async lifecycle.
    In production, use gremlinpython connecting to Neptune.
    """

    def __init__(self) -> None:
        self._vertices: dict[str, Vertex] = {}
        self._edges: list[Edge] = []
        self._connected = False

    async def connect(self) -> None:
        self._connected = True
        logger.info("GraphClient connected (in-memory stub)")

    async def close(self) -> None:
        self._vertices.clear()
        self._edges.clear()
        self._connected = False
        logger.info("GraphClient closed")

    async def add_vertex(self, vertex: Vertex) -> str:
        self._vertices[vertex.vertex_id] = vertex
        logger.info(f"Graph ADD_V {vertex.vertex_type} id={vertex.vertex_id}")
        return vertex.vertex_id

    async def add_edge(self, edge: Edge) -> None:
        self._edges.append(edge)
        logger.info(
            f"Graph ADD_E {edge.edge_type} "
            f"{edge.from_vertex_id} -> {edge.to_vertex_id}"
        )

    async def get_vertex(self, vertex_id: str) -> Optional[Vertex]:
        return self._vertices.get(vertex_id)

    async def get_neighbors(
        self,
        vertex_id: str,
        edge_type: Optional[str] = None,
        direction: str = "out",
    ) -> list[Vertex]:
        """Traverse edges from a vertex."""
        results: list[Vertex] = []
        for edge in self._edges:
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

    async def health_check(self) -> bool:
        return self._connected or True  # Stub always healthy
