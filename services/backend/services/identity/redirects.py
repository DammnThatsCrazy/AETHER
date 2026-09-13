"""Survivor-redirect helper for merged canonical entities.

When two entities merge, the secondary (merged) canonical entity id lives on in
old links, bookmarks, and cached client state. A read for that id must resolve
to the surviving entity instead of returning a stale, frozen record. This
module is the single tenant-scoped seam every identity/profile read route uses
to follow merge tombstones to the survivor and to annotate responses with
``resolved_entity_id`` + ``redirected`` (both additive — original shapes are
preserved).
"""

from __future__ import annotations

from typing import Any


async def resolve_entity_redirect(
    repo: Any, tenant_id: str, entity_id: str, *, max_hops: int = 10
) -> tuple[str, bool]:
    """Return ``(surviving_entity_id, redirected)`` for a canonical entity id.

    ``redirected`` is True only when the requested id differs from the survivor
    (i.e. it was a merged/secondary id). Best-effort: any repository error
    degrades to ``(entity_id, False)`` so a redirect lookup never turns a read
    into a 500.
    """
    if not entity_id:
        return entity_id, False
    try:
        surviving = await repo.resolve_surviving_canonical_entity_id(
            tenant_id, entity_id, max_hops=max_hops
        )
    except Exception:  # pragma: no cover — defensive; reads must not 500 on redirect
        return entity_id, False
    return surviving, (surviving != entity_id)


def redirect_fields(requested_id: str, resolved_id: str) -> dict:
    """Additive response annotation for a (possibly) redirected entity read."""
    return {
        "resolved_entity_id": resolved_id,
        "redirected": resolved_id != requested_id,
    }
