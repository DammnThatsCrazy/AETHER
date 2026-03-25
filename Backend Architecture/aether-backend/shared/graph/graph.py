"""
Aether Shared — @aether/graph
Neptune/Neo4j query builders, graph traversal helpers, vertex/edge factories.
Used by: Identity, Analytics, Agent services.

Backend selection:
- AETHER_ENV=local → in-memory graph (no Neptune required)
- AETHER_ENV=staging/production → Neptune via websocket (gremlinpython)
  Set NEPTUNE_ENDPOINT env var to the Neptune cluster endpoint.
"""

from __future__ import annotations

import os
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from shared.logger.logger import get_logger

logger = get_logger("aether.graph")

# Optional gremlinpython import
try:
    from gremlin_python.driver.driver_remote_connection import DriverRemoteConnection
    from gremlin_python.process.anonymous_traversal import traversal
    from gremlin_python.process.graph_traversal import GraphTraversalSource, __
    from gremlin_python.process.traversal import T, Cardinality
    GREMLIN_AVAILABLE = True
except ImportError:
    GREMLIN_AVAILABLE = False


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

    # Web3 Coverage — Registry-native graph objects
    CHAIN = "Chain"
    TOKEN = "Token"
    TOKEN_POSITION = "TokenPosition"
    POOL = "Pool"
    VAULT = "Vault"
    MARKET = "Market"
    STRATEGY = "Strategy"
    APP = "App"
    FRONTEND_DOMAIN = "FrontendDomain"
    GOVERNANCE_SPACE = "GovernanceSpace"
    GOVERNANCE_PROPOSAL = "GovernanceProposal"
    BRIDGE_ROUTE = "BridgeRoute"
    NFT_COLLECTION = "NftCollection"
    DEPLOYER_ENTITY = "DeployerEntity"
    MARKET_VENUE = "MarketVenue"
    CONTRACT_SYSTEM = "ContractSystem"
    PROTOCOL_VERSION = "ProtocolVersion"
    UNKNOWN_CONTRACT = "UnknownContract"


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

    # Intelligence Graph — Agent-to-Human (A2H)
    NOTIFIES = "NOTIFIES"                 # Agent → User (alerts, status updates)
    RECOMMENDS = "RECOMMENDS"             # Agent → User (agent-initiated suggestions)
    DELIVERS_TO = "DELIVERS_TO"           # Agent → User (task result delivery)
    ESCALATES_TO = "ESCALATES_TO"         # Agent → User (human-in-the-loop escalation)

    # Intelligence Graph — Action tracking
    PERFORMED_ACTION = "PERFORMED_ACTION"  # Agent → ActionRecord

    # ── Web3 Coverage — Wallet ↔ Entity edges ──────────────────────────
    USES_PROTOCOL = "USES_PROTOCOL"           # Wallet → Protocol
    USES_APP = "USES_APP"                     # Wallet → App
    TOUCHES_DOMAIN = "TOUCHES_DOMAIN"         # Wallet → FrontendDomain
    HOLDS_TOKEN = "HOLDS_TOKEN"               # Wallet → Token
    BRIDGES_VIA = "BRIDGES_VIA"               # Wallet → BridgeRoute
    PARTICIPATES_IN = "PARTICIPATES_IN"       # Wallet → GovernanceSpace
    VOTES_ON = "VOTES_ON"                     # Wallet → GovernanceProposal
    DELEGATES_TO = "DELEGATES_TO"             # Wallet → Wallet (governance delegation)
    LINKED_TO_SOCIAL = "LINKED_TO_SOCIAL"     # Wallet → User (social identity)
    TRADED_ON = "TRADED_ON"                   # Wallet → MarketVenue
    EXPOSED_TO = "EXPOSED_TO"                 # Profile/Wallet → Protocol/Token/Asset

    # ── Web3 Coverage — Contract/Protocol topology ─────────────────────
    INSTANCE_OF = "INSTANCE_OF"               # Contract → ContractSystem
    PART_OF_SYSTEM = "PART_OF_SYSTEM"         # ContractSystem → Protocol
    SUCCESSOR_OF = "SUCCESSOR_OF"             # ProtocolVersion → ProtocolVersion
    MIGRATED_TO = "MIGRATED_TO"               # Contract → Contract (migration)
    CONTROLS = "CONTROLS"                     # DeployerEntity → Contract
    DEPLOYED_ON = "DEPLOYED_ON"               # Protocol/Contract → Chain

    # ── Web3 Coverage — App/Frontend attribution ───────────────────────
    FRONTS_PROTOCOL = "FRONTS_PROTOCOL"       # App/FrontendDomain → Protocol
    ASSOCIATED_WITH = "ASSOCIATED_WITH"       # FrontendDomain → ContractSystem
    SERVED_BY = "SERVED_BY"                   # Protocol → FrontendDomain

    # ── Web3 Coverage — Market/Token edges ─────────────────────────────
    TOKEN_OF = "TOKEN_OF"                     # Token → Protocol
    TRADED_ON_VENUE = "TRADED_ON_VENUE"       # Token → MarketVenue
    POOL_FOR = "POOL_FOR"                     # Pool → Token (pair tokens)
    GOVERNED_BY_SPACE = "GOVERNED_BY_SPACE"   # Protocol → GovernanceSpace

    # ── Web3 Coverage — Classification edges ───────────────────────────
    LATER_CLASSIFIED_AS = "LATER_CLASSIFIED_AS"  # UnknownContract → Protocol/ContractSystem


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
# ENVIRONMENT HELPERS
# ═══════════════════════════════════════════════════════════════════════════

def _is_local_env() -> bool:
    return os.getenv("AETHER_ENV", "local").lower() == "local"


def _neptune_endpoint() -> str:
    return os.getenv("NEPTUNE_ENDPOINT", "")


# ═══════════════════════════════════════════════════════════════════════════
# IN-MEMORY BACKEND (local/dev)
# ═══════════════════════════════════════════════════════════════════════════

class _InMemoryGraphBackend:
    """Dict-based graph for local development."""

    def __init__(self) -> None:
        self._vertices: dict[str, Vertex] = {}
        self._edges: list[Edge] = []

    async def add_vertex(self, vertex: Vertex) -> str:
        self._vertices[vertex.vertex_id] = vertex
        return vertex.vertex_id

    async def add_edge(self, edge: Edge) -> None:
        self._edges.append(edge)

    async def get_vertex(self, vertex_id: str) -> Optional[Vertex]:
        return self._vertices.get(vertex_id)

    async def get_neighbors(
        self, vertex_id: str, edge_type: Optional[str] = None, direction: str = "out",
    ) -> list[Vertex]:
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
        logger.debug(f"In-memory graph QUERY (no-op): {gremlin[:80]}...")
        return []

    async def upsert_vertex(self, vertex: Vertex) -> str:
        existing = self._vertices.get(vertex.vertex_id)
        if existing:
            existing.properties.update(vertex.properties)
        else:
            self._vertices[vertex.vertex_id] = vertex
        return vertex.vertex_id

    async def ping(self) -> bool:
        return True

    async def close(self) -> None:
        self._vertices.clear()
        self._edges.clear()


# ═══════════════════════════════════════════════════════════════════════════
# NEPTUNE BACKEND (production via gremlinpython)
# ═══════════════════════════════════════════════════════════════════════════

class _NeptuneGraphBackend:
    """Real Neptune graph backend using gremlinpython."""

    def __init__(self, endpoint: str) -> None:
        if not GREMLIN_AVAILABLE:
            raise RuntimeError(
                "gremlinpython is required for Neptune: pip install gremlinpython>=3.7"
            )
        self._endpoint = endpoint
        self._connection: Optional[Any] = None
        self._g: Optional[Any] = None

    async def _ensure_connected(self) -> Any:
        if self._g is None:
            url = f"wss://{self._endpoint}:8182/gremlin"
            self._connection = DriverRemoteConnection(url, "g")
            self._g = traversal().withRemote(self._connection)
            logger.info(f"Neptune connected: {self._endpoint}")
        return self._g

    async def add_vertex(self, vertex: Vertex) -> str:
        g = await self._ensure_connected()
        t = g.addV(vertex.vertex_type).property(T.id, vertex.vertex_id)
        t = t.property("created_at", vertex.created_at)
        for k, v in vertex.properties.items():
            t = t.property(k, str(v))
        t.next()
        logger.info(f"Neptune ADD_V {vertex.vertex_type} id={vertex.vertex_id}")
        return vertex.vertex_id

    async def add_edge(self, edge: Edge) -> None:
        g = await self._ensure_connected()
        t = g.V(edge.from_vertex_id).addE(edge.edge_type).to(__.V(edge.to_vertex_id))
        t = t.property("created_at", edge.created_at)
        for k, v in edge.properties.items():
            t = t.property(k, str(v))
        t.next()
        logger.info(
            f"Neptune ADD_E {edge.edge_type} "
            f"{edge.from_vertex_id} -> {edge.to_vertex_id}"
        )

    async def get_vertex(self, vertex_id: str) -> Optional[Vertex]:
        g = await self._ensure_connected()
        try:
            result = g.V(vertex_id).valueMap(True).next()
            return Vertex(
                vertex_type=result.get(T.label, "unknown"),
                vertex_id=str(result.get(T.id, vertex_id)),
                properties={
                    k: v[0] if isinstance(v, list) and len(v) == 1 else v
                    for k, v in result.items()
                    if k not in (T.id, T.label)
                },
            )
        except StopIteration:
            return None
        except Exception as e:
            logger.error(f"Neptune get_vertex error for {vertex_id}: {e}")
            return None

    async def get_neighbors(
        self, vertex_id: str, edge_type: Optional[str] = None, direction: str = "out",
    ) -> list[Vertex]:
        g = await self._ensure_connected()
        results: list[Vertex] = []
        try:
            if direction == "out":
                t = g.V(vertex_id).outE()
            elif direction == "in":
                t = g.V(vertex_id).inE()
            else:
                t = g.V(vertex_id).bothE()

            if edge_type:
                t = t.hasLabel(edge_type)

            if direction == "out":
                t = t.inV()
            elif direction == "in":
                t = t.outV()
            else:
                t = t.otherV()

            for v_map in t.valueMap(True).toList():
                results.append(Vertex(
                    vertex_type=v_map.get(T.label, "unknown"),
                    vertex_id=str(v_map.get(T.id, "")),
                    properties={
                        k: v[0] if isinstance(v, list) and len(v) == 1 else v
                        for k, v in v_map.items()
                        if k not in (T.id, T.label)
                    },
                ))
        except Exception as e:
            logger.error(f"Neptune get_neighbors error for {vertex_id}: {e}")
        return results

    async def query(self, gremlin: str) -> list[dict]:
        g = await self._ensure_connected()
        try:
            # Submit raw Gremlin string via the connection's client
            if self._connection and hasattr(self._connection, '_client'):
                result = self._connection._client.submit(gremlin).all().result()
                return [dict(r) if hasattr(r, 'items') else {"value": r} for r in result]
        except Exception as e:
            logger.error(f"Neptune raw query error: {e}")
        return []

    async def upsert_vertex(self, vertex: Vertex) -> str:
        g = await self._ensure_connected()
        try:
            # Try to find existing vertex first
            existing = g.V(vertex.vertex_id).hasNext()
            if existing:
                t = g.V(vertex.vertex_id)
                for k, v in vertex.properties.items():
                    t = t.property(Cardinality.single, k, str(v))
                t.next()
            else:
                await self.add_vertex(vertex)
        except Exception:
            await self.add_vertex(vertex)
        return vertex.vertex_id

    async def ping(self) -> bool:
        try:
            g = await self._ensure_connected()
            g.V().limit(1).hasNext()
            return True
        except Exception:
            return False

    async def close(self) -> None:
        if self._connection:
            self._connection.close()
            self._connection = None
            self._g = None
            logger.info("Neptune connection closed")


# ═══════════════════════════════════════════════════════════════════════════
# GRAPH CLIENT (public API — auto-selects backend)
# ═══════════════════════════════════════════════════════════════════════════

class GraphClient:
    """
    Async graph client with automatic backend selection.

    - AETHER_ENV=local → in-memory graph
    - AETHER_ENV=staging/production + NEPTUNE_ENDPOINT → Neptune via gremlinpython
    - Non-local without Neptune → RuntimeError (fail-closed)
    """

    def __init__(self) -> None:
        self._backend: Optional[_InMemoryGraphBackend | _NeptuneGraphBackend] = None
        self._connected = False
        self._mode = "uninitialized"

    async def connect(self) -> None:
        endpoint = _neptune_endpoint()
        if endpoint and GREMLIN_AVAILABLE:
            self._backend = _NeptuneGraphBackend(endpoint)
            if await self._backend.ping():
                self._mode = "neptune"
                logger.info(f"GraphClient connected (Neptune: {endpoint})")
            else:
                if _is_local_env():
                    logger.warning("Neptune not reachable — falling back to in-memory graph")
                    self._backend = _InMemoryGraphBackend()
                    self._mode = "in-memory"
                else:
                    raise RuntimeError(
                        f"Neptune not reachable at {endpoint}. "
                        "Set AETHER_ENV=local for in-memory fallback."
                    )
        elif _is_local_env():
            self._backend = _InMemoryGraphBackend()
            self._mode = "in-memory"
            logger.info("GraphClient connected (in-memory, local mode)")
        else:
            raise RuntimeError(
                "NEPTUNE_ENDPOINT not configured. Required in non-local environments. "
                "Set AETHER_ENV=local for in-memory fallback."
            )
        self._connected = True

    async def close(self) -> None:
        if self._backend:
            await self._backend.close()
        self._connected = False
        logger.info("GraphClient closed")

    async def add_vertex(self, vertex: Vertex) -> str:
        if self._backend is None:
            await self.connect()
        return await self._backend.add_vertex(vertex)  # type: ignore[union-attr]

    async def add_edge(self, edge: Edge) -> None:
        if self._backend is None:
            await self.connect()
        await self._backend.add_edge(edge)  # type: ignore[union-attr]

    async def get_vertex(self, vertex_id: str) -> Optional[Vertex]:
        if self._backend is None:
            await self.connect()
        return await self._backend.get_vertex(vertex_id)  # type: ignore[union-attr]

    async def get_neighbors(
        self,
        vertex_id: str,
        edge_type: Optional[str] = None,
        direction: str = "out",
    ) -> list[Vertex]:
        if self._backend is None:
            await self.connect()
        return await self._backend.get_neighbors(vertex_id, edge_type, direction)  # type: ignore[union-attr]

    async def query(self, gremlin: str) -> list[dict]:
        if self._backend is None:
            await self.connect()
        return await self._backend.query(gremlin)  # type: ignore[union-attr]

    async def upsert_vertex(self, vertex: Vertex) -> str:
        if self._backend is None:
            await self.connect()
        return await self._backend.upsert_vertex(vertex)  # type: ignore[union-attr]

    async def health_check(self) -> bool:
        if self._backend is None:
            return False
        try:
            return await self._backend.ping()
        except Exception:
            return False

    @property
    def mode(self) -> str:
        return self._mode
