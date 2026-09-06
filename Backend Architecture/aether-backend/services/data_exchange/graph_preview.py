"""Data Exchange Plane — graph-preview adapter (M3).

Thin, non-mutating adapter over the canonical import graph-preview seam
(``services/imports/commit.graph_preview`` — the pure planner that returns the
vertices/edges a commit *would* produce without staging anything).  The Data
Exchange envelope exposes it at ``POST /v1/data-exchange/imports/{import_id}/
preview/graph`` with an optional ``mapping_version`` pin so a caller can ask
for a preview against a specific version of the import's mapping.
"""

from __future__ import annotations

from typing import Awaitable, Callable, Optional

from repositories.imports_repo import get_imports_repository
from shared.common.common import BadRequestError, ConflictError

GraphPreviewSeam = Callable[[str, str], Awaitable[dict]]
LatestMappingSeam = Callable[[str, str], Awaitable[Optional[dict]]]


async def _canonical_graph_preview(tenant_id: str, import_id: str) -> dict:
    """Canonical import graph-preview (non-mutating) — the seam we proxy."""
    from services.imports.commit import graph_preview

    return await graph_preview(tenant_id, import_id)


async def _latest_mapping_seam(tenant_id: str, import_id: str) -> Optional[dict]:
    return await get_imports_repository().get_latest_mapping(tenant_id, import_id)


async def preview_graph(
    tenant_id: str,
    import_id: str,
    *,
    mapping_version: Optional[int] = None,
    preview_seam: Optional[GraphPreviewSeam] = None,
    mapping_seam: Optional[LatestMappingSeam] = None,
) -> dict:
    """Preview the graph a commit of this import would produce.

    When ``mapping_version`` is supplied the preview is pinned to that mapping
    version and raises ``ConflictError`` when the import's latest mapping has
    moved on — a stale preview must not be mistaken for the current one.
    """
    if mapping_version is not None and int(mapping_version) < 1:
        raise BadRequestError("mapping_version must be >= 1")
    preview_seam = preview_seam or _canonical_graph_preview
    mapping_seam = mapping_seam or _latest_mapping_seam

    if mapping_version is not None:
        mapping = await mapping_seam(tenant_id, import_id)
        latest_version = int((mapping or {}).get("version") or 1)
        if latest_version != int(mapping_version):
            raise ConflictError(
                f"requested mapping_version {int(mapping_version)} does not match the "
                f"import's latest mapping version {latest_version}"
            )

    payload = await preview_seam(tenant_id, import_id)
    payload["import_id"] = import_id
    if mapping_version is not None:
        payload["mapping_version"] = int(mapping_version)
    return payload


__all__ = ["preview_graph"]
