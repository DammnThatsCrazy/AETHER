"""Silver Projection Reconciliation Worker.

Read-only worker that identifies data quality issues in the live graph:
- Orphaned vertices (no edges, no tenant)
- Duplicate edges (same from/to/type pair with different created_at)
- Missing Silver projections (vertex types that should have projections but don't)
- Stale identity versions (identity vertices superseded but not marked as such)

The worker NEVER mutates the graph. It produces a ReconciliationReport
for human or automated review.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel, Field

from shared.graph.graph import GraphClient
from shared.logger.logger import get_logger

logger = get_logger("aether.silver.reconciliation")

# Vertex types that must have at least one outbound Silver projection edge.
_EXPECTED_PROJECTION_VERTEX_TYPES: frozenset[str] = frozenset({
    "User", "Agent", "Device", "Organization",
})

# Edge types used for identity version chains.
_IDENTITY_VERSION_EDGE_TYPES: frozenset[str] = frozenset({
    "SUPERSEDES", "PREVIOUS_VERSION",
})


class ReconciliationReport(BaseModel):
    tenant_id: str
    orphaned_vertex_ids: list[str] = Field(default_factory=list)
    duplicate_edge_ids: list[tuple[str, str, str]] = Field(default_factory=list)
    missing_projection_ids: list[str] = Field(default_factory=list)
    stale_identity_ids: list[str] = Field(default_factory=list)
    computed_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    error_count: int = 0
    errors: list[str] = Field(default_factory=list)


class SilverReconciliationWorker:
    """Read-only graph consistency checker for Silver projection layer."""

    def __init__(self, graph: GraphClient) -> None:
        self._graph = graph

    async def run(self, tenant_id: str) -> ReconciliationReport:
        """Execute all reconciliation checks and return a report."""
        errors: list[str] = []
        report_kwargs: dict = {"tenant_id": tenant_id}

        try:
            report_kwargs["orphaned_vertex_ids"] = await self._find_orphaned_vertices(tenant_id)
        except Exception as exc:
            logger.error(f"orphan check failed: {exc}")
            errors.append(f"orphan_check: {exc}")

        try:
            report_kwargs["duplicate_edge_ids"] = await self._find_duplicate_edges(tenant_id)
        except Exception as exc:
            logger.error(f"duplicate edge check failed: {exc}")
            errors.append(f"duplicate_edge_check: {exc}")

        try:
            report_kwargs["missing_projection_ids"] = await self._find_missing_projections(tenant_id)
        except Exception as exc:
            logger.error(f"missing projection check failed: {exc}")
            errors.append(f"missing_projection_check: {exc}")

        try:
            report_kwargs["stale_identity_ids"] = await self._find_stale_identity_versions(tenant_id)
        except Exception as exc:
            logger.error(f"stale identity check failed: {exc}")
            errors.append(f"stale_identity_check: {exc}")

        report_kwargs["error_count"] = len(errors)
        report_kwargs["errors"] = errors
        return ReconciliationReport(**report_kwargs)

    async def _find_orphaned_vertices(self, tenant_id: str) -> list[str]:
        """Return vertex IDs that have no edges and no tenantId property."""
        all_verts = await self._graph.get_all_vertices(limit=10000)
        orphaned: list[str] = []
        for v in all_verts:
            if v.properties.get("tenantId") != tenant_id:
                continue
            in_edges = await self._graph.get_edges(v.vertex_id, direction="in")
            out_edges = await self._graph.get_edges(v.vertex_id, direction="out")
            if not in_edges and not out_edges:
                orphaned.append(v.vertex_id)
        return orphaned

    async def _find_duplicate_edges(self, tenant_id: str) -> list[tuple[str, str, str]]:
        """Return (from, to, type) tuples for edge pairs that appear more than once."""
        all_verts = await self._graph.get_all_vertices(limit=10000)
        seen: dict[tuple[str, str, str], int] = {}
        duplicates: list[tuple[str, str, str]] = []

        for v in all_verts:
            if v.properties.get("tenantId") != tenant_id:
                continue
            edges = await self._graph.get_edges(v.vertex_id, direction="out")
            for e in edges:
                key = (e.from_vertex_id, e.to_vertex_id, e.edge_type)
                seen[key] = seen.get(key, 0) + 1
                if seen[key] == 2:
                    duplicates.append(key)

        return duplicates

    async def _find_missing_projections(self, tenant_id: str) -> list[str]:
        """Return vertex IDs of types that should have projection edges but don't."""
        all_verts = await self._graph.get_all_vertices(limit=10000)
        missing: list[str] = []
        for v in all_verts:
            if v.properties.get("tenantId") != tenant_id:
                continue
            if v.vertex_type not in _EXPECTED_PROJECTION_VERTEX_TYPES:
                continue
            out_edges = await self._graph.get_edges(v.vertex_id, direction="out")
            has_projection = any(e.edge_type.startswith("PROJECTS_") for e in out_edges)
            if not has_projection:
                missing.append(v.vertex_id)
        return missing

    async def _find_stale_identity_versions(self, tenant_id: str) -> list[str]:
        """Return vertex IDs that appear to be superseded but lack a superseded_at property."""
        all_verts = await self._graph.get_all_vertices(limit=10000)
        stale: list[str] = []
        for v in all_verts:
            if v.properties.get("tenantId") != tenant_id:
                continue
            in_edges = await self._graph.get_edges(v.vertex_id, direction="in")
            is_superseded = any(e.edge_type in _IDENTITY_VERSION_EDGE_TYPES for e in in_edges)
            if is_superseded and not v.properties.get("superseded_at"):
                stale.append(v.vertex_id)
        return stale
