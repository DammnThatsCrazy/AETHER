"""Kyber Graph storage — natural-key upserts over the projection tables.

The Kyber Graph is rebuilt from an append-only ledger, so every write here is a
*replay-safe* write. Two properties carry that weight and are the reason this
module exists instead of raw repository calls at the call sites:

**Idempotence on the natural key.** A node is identified by
``(node_key, environment)`` and an edge by ``(idempotency_key, environment)``
where the edge key is ``source|type|target`` (see
:class:`~services.kyber.graph.contracts.KyberGraphEdge`). Reprojecting the same
ledger range must converge on the same graph, not grow it — at-least-once
delivery plus idempotent upserts is the projector's whole contract, and the
alembic unique indexes (``ux_kyber_graph_nodes_key``,
``ux_kyber_graph_edges_key``) enforce it at the storage layer.

One caveat that shaped the projector: in PostgreSQL a unique index treats NULLs
as distinct, so rows with ``environment IS NULL`` are *not* deduped by
``ux_kyber_graph_nodes_key``. The read-modify-write in this module is what keeps
them single, and every projected node therefore carries an explicit
environment rather than relying on the index alone.

**Monotonic provenance.** Ledger rows can arrive out of order (a retried batch,
a replay racing live projection). An older row must never overwrite newer state,
so an upsert whose ``source_offset`` is behind what is already stored is
discarded rather than applied. Without this, a replay of an old range would roll
the graph backwards and the graph's ``source_offset`` would stop meaning
"as of this point in the ledger".

**Tenant discipline.** ``upsert_node`` refuses a ``tenant_id`` on a node type
outside :data:`TENANT_SCOPED_NODE_TYPES`. That set is the boundary the whole
plane rests on: platform topology holds *references* into tenant data, never
tenant data itself. Silently accepting a tenant on a ``Service`` node would make
tenant isolation a query-time filter, which is exactly the defect class this
plane was built to avoid, so it is a hard error.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Callable, Optional, TypeVar

from pydantic import BaseModel

from repositories.repos import BaseRepository
from services.kyber.graph.contracts import (
    TENANT_SCOPED_NODE_TYPES,
    HealthStatus,
    KyberEdgeType,
    KyberGraphEdge,
    KyberGraphNode,
    KyberNodeType,
    ProjectionOffset,
)
from shared.common.common import BadRequestError, utc_now
from shared.logger.logger import get_logger, metrics

logger = get_logger("aether.kyber.graph.repository")

#: A ``node_key`` is unique per environment, so a natural-key lookup only ever
#: scans the handful of environments that key exists in.
_NATURAL_KEY_SCAN = 200

#: Ceiling on a single edge fan-out read. Traversals that need more than this
#: are truncated by the caller (blast radius reports ``truncated``) rather than
#: silently pulling an unbounded result set.
_MAX_EDGE_FETCH = 5_000

_M = TypeVar("_M", bound=BaseModel)


def _from_row(model: type[_M], row: dict[str, Any]) -> _M:
    """Rebuild a contract model from a stored row, dropping storage columns.

    ``BaseRepository.insert`` stamps ``id``/``created_at``/``updated_at`` onto
    the payload it stores. Filtering to declared fields keeps that storage
    detail out of the model instead of relying on pydantic's extra-field
    handling, which a future ``model_config`` change could flip.
    """
    fields = model.model_fields
    return model(**{key: value for key, value in row.items() if key in fields})


def _edge_row(edge: KyberGraphEdge) -> dict[str, Any]:
    """Storage payload for an edge, with its natural key materialised.

    ``idempotency_key`` is a derived property rather than a field, so
    ``model_dump()`` omits it — but ``ux_kyber_graph_edges_key`` indexes
    ``data->>'idempotency_key'``. Writing it explicitly is what makes the
    database-side uniqueness real instead of decorative.
    """
    row = edge.model_dump()
    row["idempotency_key"] = edge.idempotency_key
    return row


def _is_stale(incoming: Optional[int], stored: Optional[int]) -> bool:
    """True when ``incoming`` provenance is older than what is already stored.

    An absent incoming offset (a topology sync, which has no ledger position)
    is treated as older than any recorded offset: hand-derived topology must not
    clobber ledger-projected state.
    """
    if stored is None:
        return False
    if incoming is None:
        return True
    return incoming < stored


class KyberGraphNodeRepository(BaseRepository):
    """``kyber_graph_nodes`` — one row per ``(node_key, environment)``."""

    def __init__(self) -> None:
        super().__init__("kyber_graph_nodes")


class KyberGraphEdgeRepository(BaseRepository):
    """``kyber_graph_edges`` — one row per ``(idempotency_key, environment)``."""

    def __init__(self) -> None:
        super().__init__("kyber_graph_edges")


class ProjectionOffsetRepository(BaseRepository):
    """``kyber_graph_projection_offsets`` — one row per ``(projection, tenant)``."""

    def __init__(self) -> None:
        super().__init__("kyber_graph_projection_offsets")


class KyberGraphStore:
    """Read/write facade over the three Kyber Graph projection tables.

    Every writer (the ledger projector, the topology sync, the operations
    planes) goes through this one object so the idempotence and monotonicity
    rules live in a single place. The clock is injectable so tests assert on
    timestamps without sleeping.
    """

    def __init__(
        self,
        *,
        nodes: Optional[KyberGraphNodeRepository] = None,
        edges: Optional[KyberGraphEdgeRepository] = None,
        offsets: Optional[ProjectionOffsetRepository] = None,
        clock: Optional[Callable[[], datetime]] = None,
    ) -> None:
        self.nodes = nodes or KyberGraphNodeRepository()
        self.edges = edges or KyberGraphEdgeRepository()
        self.offsets = offsets or ProjectionOffsetRepository()
        self._clock = clock or utc_now

    # ── Clock ────────────────────────────────────────────────────────────────

    def _now(self) -> str:
        return self._clock().isoformat()

    # ── Nodes ────────────────────────────────────────────────────────────────

    async def upsert_node(self, node: KyberGraphNode) -> KyberGraphNode:
        """Insert or converge one node on ``(node_key, environment)``.

        Returns the node as it now stands in storage: the merged row on an
        update, or the *stored* row untouched when ``node`` carries older
        provenance than what is already there.
        """
        self._assert_tenant_discipline(node)
        existing = await self._node_row(node.node_key, node.environment)
        if existing is None:
            row = node.model_dump()
            row["updated_at"] = self._now()
            await self.nodes.insert(node.node_id, row)
            metrics.increment(
                "kyber_graph_nodes_upserted_total",
                labels={"node_type": str(node.node_type), "operation": "insert"},
            )
            return _from_row(KyberGraphNode, row)

        stored = _from_row(KyberGraphNode, existing)
        if _is_stale(node.source_offset, stored.source_offset):
            # Out-of-order arrival. Keep the newer row's provenance and state;
            # the graph must never travel backwards in the ledger.
            metrics.increment(
                "kyber_graph_nodes_upserted_total",
                labels={"node_type": str(node.node_type), "operation": "stale_skip"},
            )
            return stored

        merged = self._merge_node(stored, node)
        await self.nodes.update(existing["id"], merged.model_dump())
        metrics.increment(
            "kyber_graph_nodes_upserted_total",
            labels={"node_type": str(node.node_type), "operation": "update"},
        )
        return merged

    def _merge_node(
        self, stored: KyberGraphNode, incoming: KyberGraphNode
    ) -> KyberGraphNode:
        """Converge ``incoming`` onto ``stored``, keeping identity and origin.

        ``node_id``, ``node_key``, ``environment``, ``valid_from`` and
        ``created_at`` belong to the stored row: the node's identity and when
        the platform first saw it do not change because it was observed again.
        ``health`` only moves on a real observation — ``"unknown"`` is the field
        default and carries no information, so it never overwrites a known
        state with a shrug.
        """
        return stored.model_copy(
            update={
                "node_type": incoming.node_type,
                "tenant_id": incoming.tenant_id or stored.tenant_id,
                "display_name": incoming.display_name or stored.display_name,
                "health": incoming.health if incoming.health != "unknown" else stored.health,
                "properties": {**stored.properties, **incoming.properties},
                "valid_to": incoming.valid_to,
                "source_event_id": incoming.source_event_id or stored.source_event_id,
                "source_offset": (
                    incoming.source_offset
                    if incoming.source_offset is not None
                    else stored.source_offset
                ),
                "evidence_reference": (
                    incoming.evidence_reference or stored.evidence_reference
                ),
                "updated_at": self._now(),
            }
        )

    @staticmethod
    def _assert_tenant_discipline(node: KyberGraphNode) -> None:
        """Refuse a tenant on a node type that must not carry one."""
        if node.tenant_id and node.node_type not in TENANT_SCOPED_NODE_TYPES:
            raise BadRequestError(
                f"node_type {node.node_type!r} may not carry a tenant_id "
                f"(node_key={node.node_key!r}). The Kyber Graph stores platform "
                f"topology and references into tenant data, never tenant data. "
                f"Tenant-scoped types: {sorted(TENANT_SCOPED_NODE_TYPES)}"
            )

    async def get_node(
        self, node_key: str, *, environment: Optional[str] = None
    ) -> Optional[KyberGraphNode]:
        """The node stored under this exact natural key.

        ``environment=None`` selects the row whose environment is unset — it is
        half of the key, not a wildcard. Use :meth:`find_nodes` to search
        across environments.
        """
        row = await self._node_row(node_key, environment)
        return _from_row(KyberGraphNode, row) if row is not None else None

    async def _node_row(
        self, node_key: str, environment: Optional[str]
    ) -> Optional[dict[str, Any]]:
        rows = await self.nodes.find_many({"node_key": node_key}, limit=_NATURAL_KEY_SCAN)
        for row in rows:
            if row.get("environment") == environment:
                return row
        return None

    async def find_nodes(
        self,
        *,
        node_type: Optional[KyberNodeType] = None,
        tenant_id: Optional[str] = None,
        environment: Optional[str] = None,
        health: Optional[HealthStatus] = None,
        limit: int = 500,
    ) -> list[KyberGraphNode]:
        """Nodes matching every supplied predicate. Omitted predicates are open."""
        filters: dict[str, Any] = {}
        if node_type:
            filters["node_type"] = node_type
        if tenant_id:
            filters["tenant_id"] = tenant_id
        if environment:
            filters["environment"] = environment
        if health:
            filters["health"] = health
        rows = await self.nodes.find_many(filters, limit=limit, sort_order="asc")
        return [_from_row(KyberGraphNode, row) for row in rows]

    # ── Edges ────────────────────────────────────────────────────────────────

    async def upsert_edge(self, edge: KyberGraphEdge) -> KyberGraphEdge:
        """Insert or converge one edge on ``(idempotency_key, environment)``.

        The same relationship projected twice is one row: ``source|type|target``
        is the identity, so a duplicate carries no new information beyond its
        provenance.
        """
        existing = await self._edge_row(edge.idempotency_key, edge.environment)
        if existing is None:
            row = _edge_row(edge)
            row["updated_at"] = self._now()
            await self.edges.insert(edge.edge_id, row)
            metrics.increment(
                "kyber_graph_edges_upserted_total",
                labels={"relationship_type": str(edge.relationship_type),
                        "operation": "insert"},
            )
            return _from_row(KyberGraphEdge, row)

        stored = _from_row(KyberGraphEdge, existing)
        if _is_stale(edge.source_offset, stored.source_offset):
            metrics.increment(
                "kyber_graph_edges_upserted_total",
                labels={"relationship_type": str(edge.relationship_type),
                        "operation": "stale_skip"},
            )
            return stored

        merged = stored.model_copy(
            update={
                "tenant_id": edge.tenant_id or stored.tenant_id,
                "properties": {**stored.properties, **edge.properties},
                "valid_to": edge.valid_to,
                "source_event_id": edge.source_event_id or stored.source_event_id,
                "source_offset": (
                    edge.source_offset
                    if edge.source_offset is not None
                    else stored.source_offset
                ),
                "evidence_reference": edge.evidence_reference or stored.evidence_reference,
            }
        )
        row = _edge_row(merged)
        row["updated_at"] = self._now()
        await self.edges.update(existing["id"], row)
        metrics.increment(
            "kyber_graph_edges_upserted_total",
            labels={"relationship_type": str(edge.relationship_type), "operation": "update"},
        )
        return merged

    async def _edge_row(
        self, idempotency_key: str, environment: Optional[str]
    ) -> Optional[dict[str, Any]]:
        rows = await self.edges.find_many(
            {"idempotency_key": idempotency_key}, limit=_NATURAL_KEY_SCAN
        )
        for row in rows:
            if row.get("environment") == environment:
                return row
        return None

    async def edges_from(
        self,
        node_key: str,
        *,
        relationship_type: Optional[KyberEdgeType] = None,
        environment: Optional[str] = None,
        include_expired: bool = False,
        limit: int = 500,
    ) -> list[KyberGraphEdge]:
        """Outbound edges of ``node_key``."""
        return await self._edges_on(
            "source_node_key",
            node_key,
            relationship_type=relationship_type,
            environment=environment,
            include_expired=include_expired,
            limit=limit,
        )

    async def edges_to(
        self,
        node_key: str,
        *,
        relationship_type: Optional[KyberEdgeType] = None,
        environment: Optional[str] = None,
        include_expired: bool = False,
        limit: int = 500,
    ) -> list[KyberGraphEdge]:
        """Inbound edges of ``node_key``."""
        return await self._edges_on(
            "target_node_key",
            node_key,
            relationship_type=relationship_type,
            environment=environment,
            include_expired=include_expired,
            limit=limit,
        )

    async def _edges_on(
        self,
        column: str,
        node_key: str,
        *,
        relationship_type: Optional[KyberEdgeType],
        environment: Optional[str],
        include_expired: bool,
        limit: int,
    ) -> list[KyberGraphEdge]:
        filters: dict[str, Any] = {column: node_key}
        if relationship_type:
            filters["relationship_type"] = relationship_type
        if environment:
            filters["environment"] = environment
        # Expiry is the one predicate the JSONB equality filter cannot express,
        # so it is applied in Python — over-fetch so the post-filter does not
        # silently return fewer than `limit` live edges.
        fetch = limit if include_expired else min(limit * 2, _MAX_EDGE_FETCH)
        rows = await self.edges.find_many(filters, limit=fetch, sort_order="asc")
        edges = [_from_row(KyberGraphEdge, row) for row in rows]
        if not include_expired:
            edges = [edge for edge in edges if edge.valid_to is None]
        return edges[:limit]

    async def expire_edge(self, edge: KyberGraphEdge, *, at: Optional[str] = None) -> None:
        """Close an edge's validity window instead of deleting it.

        Edges are bitemporal: "this dependency existed until Tuesday" is the
        fact an incident review needs, and a deleted row cannot answer it.
        """
        row = await self._edge_row(edge.idempotency_key, edge.environment)
        if row is None:
            logger.debug(
                f"kyber graph: expire_edge on unknown edge {edge.idempotency_key!r}"
            )
            return
        await self.edges.update(row["id"], {"valid_to": at or self._now()})

    # ── Projection offsets ───────────────────────────────────────────────────

    async def offset_for(self, projection: str, tenant_id: str) -> ProjectionOffset:
        """This projection's position in one tenant's ledger.

        An unknown ``(projection, tenant)`` returns a fresh offset at 0 rather
        than ``None``: a projection that has never run and one that has consumed
        nothing are the same starting state, and returning a real object keeps
        the caller from branching on absence.
        """
        row = await self._offset_row(projection, tenant_id)
        if row is None:
            return ProjectionOffset(projection=projection, tenant_id=tenant_id)
        return _from_row(ProjectionOffset, row)

    async def save_offset(self, offset: ProjectionOffset) -> ProjectionOffset:
        """Persist an offset, creating the row on first save."""
        updated = offset.model_copy(update={"updated_at": self._now()})
        row = await self._offset_row(offset.projection, offset.tenant_id)
        payload = updated.model_dump()
        if row is None:
            await self.offsets.insert(updated.offset_id, payload)
            return updated
        # Keep the stored row's identity so a caller holding a stale
        # ProjectionOffset cannot fork a second row for the same tenant.
        payload["offset_id"] = row.get("offset_id", updated.offset_id)
        await self.offsets.update(row["id"], payload)
        return _from_row(ProjectionOffset, payload)

    async def list_offsets(
        self, projection: str, *, limit: int = 1000
    ) -> list[ProjectionOffset]:
        """Every tenant offset for ``projection``.

        The fleet projector needs this to answer "which tenants have I ever
        projected" without a tenant roster of its own.
        """
        rows = await self.offsets.find_many(
            {"projection": projection}, limit=limit, sort_order="asc"
        )
        return [_from_row(ProjectionOffset, row) for row in rows]

    async def _offset_row(
        self, projection: str, tenant_id: str
    ) -> Optional[dict[str, Any]]:
        rows = await self.offsets.find_many(
            {"projection": projection, "tenant_id": tenant_id}, limit=2
        )
        return rows[0] if rows else None


#: Process-wide store. Constructing repositories is cheap, but the in-memory
#: local backend keys its backing dicts by table name, so every instance
#: already observes one consistent view.
kyber_graph_store = KyberGraphStore()


__all__ = [
    "KyberGraphEdgeRepository",
    "KyberGraphNodeRepository",
    "KyberGraphStore",
    "ProjectionOffsetRepository",
    "kyber_graph_store",
]
