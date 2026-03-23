"""Aether Shared graph client with durable SQLite persistence."""

from __future__ import annotations

import json
import os
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Optional

from shared.logger.logger import get_logger

logger = get_logger("aether.graph")


def _state_dir(component: str) -> Path:
    base = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state"))
    path = base / "aether" / component
    path.mkdir(parents=True, exist_ok=True)
    return path


def _graph_db_path() -> Path:
    explicit = os.environ.get("AETHER_GRAPH_DB_PATH")
    env = os.environ.get("AETHER_ENV", "local").lower()
    if explicit:
        path = Path(explicit)
    elif env == "local":
        path = _state_dir("graph") / "graph.sqlite3"
    else:
        raise RuntimeError(
            "AETHER_GRAPH_DB_PATH must be set in non-local environments to enable persistent graph storage."
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _escape_gremlin(value: Any) -> str:
    return str(value).replace("\\", "\\\\").replace("'", "\\'")


class VertexType(str, Enum):
    USER = "User"
    SESSION = "Session"
    PAGE_VIEW = "PageView"
    EVENT = "Event"
    DEVICE = "Device"
    COMPANY = "Company"
    CAMPAIGN = "Campaign"
    EXTERNAL_DATA = "ExternalData"
    DEVICE_FINGERPRINT = "DeviceFingerprint"
    IP_ADDRESS = "IPAddress"
    LOCATION = "Location"
    EMAIL = "Email"
    PHONE = "Phone"
    WALLET = "Wallet"
    IDENTITY_CLUSTER = "IdentityCluster"
    AGENT = "Agent"
    SERVICE = "Service"
    CONTRACT = "Contract"
    PROTOCOL = "Protocol"
    PAYMENT = "Payment"
    ACTION_RECORD = "ActionRecord"


class EdgeType(str, Enum):
    HAS_SESSION = "HAS_SESSION"
    VIEWED_PAGE = "VIEWED_PAGE"
    TRIGGERED_EVENT = "TRIGGERED_EVENT"
    USED_DEVICE = "USED_DEVICE"
    BELONGS_TO = "BELONGS_TO"
    ATTRIBUTED_TO = "ATTRIBUTED_TO"
    RESOLVED_AS = "RESOLVED_AS"
    ENRICHED_BY = "ENRICHED_BY"
    HAS_FINGERPRINT = "HAS_FINGERPRINT"
    SEEN_FROM_IP = "SEEN_FROM_IP"
    LOCATED_IN = "LOCATED_IN"
    HAS_EMAIL = "HAS_EMAIL"
    HAS_PHONE = "HAS_PHONE"
    OWNS_WALLET = "OWNS_WALLET"
    MEMBER_OF_CLUSTER = "MEMBER_OF_CLUSTER"
    SIMILAR_TO = "SIMILAR_TO"
    IP_MAPS_TO = "IP_MAPS_TO"
    LAUNCHED_BY = "LAUNCHED_BY"
    DELEGATES = "DELEGATES"
    INTERACTS_WITH = "INTERACTS_WITH"
    PAYS = "PAYS"
    CONSUMES = "CONSUMES"
    HIRED = "HIRED"
    DEPLOYED = "DEPLOYED"
    CALLED = "CALLED"
    COMPOSED_WITH = "COMPOSED_WITH"
    UPGRADED = "UPGRADED"
    GOVERNED_BY = "GOVERNED_BY"
    DEPENDS_ON = "DEPENDS_ON"
    NOTIFIES = "NOTIFIES"
    RECOMMENDS = "RECOMMENDS"
    DELIVERS_TO = "DELIVERS_TO"
    ESCALATES_TO = "ESCALATES_TO"
    PERFORMED_ACTION = "PERFORMED_ACTION"


@dataclass
class Vertex:
    vertex_id: str
    vertex_type: str
    properties: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_gremlin(self) -> str:
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
    from_vertex_id: str
    to_vertex_id: str
    edge_type: str
    properties: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_gremlin(self) -> str:
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


class GraphClient:
    """Persistent graph client backed by SQLite adjacency tables."""

    def __init__(self) -> None:
        self._db_path = _graph_db_path()
        self._connected = False
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS vertices (vertex_id TEXT PRIMARY KEY, vertex_type TEXT NOT NULL, properties TEXT NOT NULL, created_at TEXT NOT NULL)"
            )
            conn.execute(
                "CREATE TABLE IF NOT EXISTS edges (id INTEGER PRIMARY KEY AUTOINCREMENT, from_vertex_id TEXT NOT NULL, to_vertex_id TEXT NOT NULL, edge_type TEXT NOT NULL, properties TEXT NOT NULL, created_at TEXT NOT NULL, UNIQUE(from_vertex_id, to_vertex_id, edge_type))"
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_edges_from_type ON edges(from_vertex_id, edge_type)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_edges_to_type ON edges(to_vertex_id, edge_type)")

    async def connect(self) -> None:
        with self._connect() as conn:
            conn.execute("SELECT 1").fetchone()
        self._connected = True
        logger.info("GraphClient connected to durable SQLite graph store")

    async def close(self) -> None:
        self._connected = False
        logger.info("GraphClient closed")

    async def add_vertex(self, vertex: Vertex) -> str:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO vertices(vertex_id, vertex_type, properties, created_at) VALUES (?, ?, ?, ?) ON CONFLICT(vertex_id) DO UPDATE SET vertex_type = excluded.vertex_type, properties = excluded.properties, created_at = excluded.created_at",
                (vertex.vertex_id, vertex.vertex_type, json.dumps(vertex.properties), vertex.created_at),
            )
        return vertex.vertex_id


    async def upsert_vertex(self, vertex: Vertex) -> str:
        return await self.add_vertex(vertex)

    async def add_edge(self, edge: Edge) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO edges(from_vertex_id, to_vertex_id, edge_type, properties, created_at) VALUES (?, ?, ?, ?, ?) ON CONFLICT(from_vertex_id, to_vertex_id, edge_type) DO UPDATE SET properties = excluded.properties, created_at = excluded.created_at",
                (edge.from_vertex_id, edge.to_vertex_id, edge.edge_type, json.dumps(edge.properties), edge.created_at),
            )

    async def get_vertex(self, vertex_id: str) -> Optional[Vertex]:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM vertices WHERE vertex_id = ?", (vertex_id,)).fetchone()
        if row is None:
            return None
        return Vertex(vertex_id=row["vertex_id"], vertex_type=row["vertex_type"], properties=json.loads(row["properties"]), created_at=row["created_at"])

    async def get_neighbors(self, vertex_id: str, edge_type: Optional[str] = None, direction: str = "out") -> list[Vertex]:
        clauses: list[str] = []
        params: list[Any] = []
        if direction in ("out", "both"):
            clauses.append(
                "SELECT v.* FROM edges e JOIN vertices v ON v.vertex_id = e.to_vertex_id WHERE e.from_vertex_id = ?"
            )
            params.append(vertex_id)
            if edge_type is not None:
                clauses[-1] += " AND e.edge_type = ?"
                params.append(edge_type)
        if direction in ("in", "both"):
            clauses.append(
                "SELECT v.* FROM edges e JOIN vertices v ON v.vertex_id = e.from_vertex_id WHERE e.to_vertex_id = ?"
            )
            params.append(vertex_id)
            if edge_type is not None:
                clauses[-1] += " AND e.edge_type = ?"
                params.append(edge_type)
        if not clauses:
            return []
        query = " UNION ".join(clauses)
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [
            Vertex(vertex_id=row["vertex_id"], vertex_type=row["vertex_type"], properties=json.loads(row["properties"]), created_at=row["created_at"])
            for row in rows
        ]

    async def query(self, gremlin: str) -> list[dict]:
        logger.info("Graph QUERY passthrough requested: %s", gremlin[:100])
        if gremlin.strip().lower().startswith("select"):
            with self._connect() as conn:
                rows = conn.execute(gremlin).fetchall()
            return [dict(row) for row in rows]
        raise ValueError("Only SQL SELECT diagnostics are supported by the SQLite graph backend")

    async def health_check(self) -> bool:
        if not self._connected:
            return False
        with self._connect() as conn:
            conn.execute("SELECT COUNT(*) FROM vertices").fetchone()
        return True
