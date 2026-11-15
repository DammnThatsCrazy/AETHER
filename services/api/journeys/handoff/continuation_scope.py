"""Handoff continuation scope: which anonymous IDs one journey spans.

A redeemed handoff is explicit, server-verified evidence that one party
controlled both sessions at redemption time (see ``service.py``). The journey
compiler uses that evidence to continue an anonymous journey across devices:
the activity of every anonymous ID reachable through redeemed handoffs is
compiled into ONE journey, owned by a deterministic root.

This is journey linkage, not identity resolution. No profile is merged, no
anonymous ID is rewritten, and nothing here is visible to identity resolution.
The walk is tenant-scoped and bounded; a truncated walk is reported, never
silently widened.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

from repositories.journey_handoff_repo import get_journey_handoff_repository

MAX_ANONYMOUS_IDS = 16
MAX_HOPS = 8


@dataclass(frozen=True)
class ContinuationScope:
    """Anonymous IDs linked by redeemed handoffs, plus the deterministic root.

    ``root_anonymous_id`` is the source of the oldest redeemed handoff in the
    scope (the device the journey started on), or the seed itself when nothing
    is linked. Ordering is by handoff creation then handoff ID, so every worker
    picks the same root for the same rows.
    """

    root_anonymous_id: str
    anonymous_ids: tuple[str, ...]
    handoffs: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    truncated: bool = False

    @property
    def linked(self) -> bool:
        return len(self.anonymous_ids) > 1


def _single(seed: str) -> ContinuationScope:
    return ContinuationScope(root_anonymous_id=seed, anonymous_ids=(seed,))


async def resolve_continuation_scope(
    tenant_id: str,
    seeds: Iterable[str],
    *,
    max_anonymous_ids: int = MAX_ANONYMOUS_IDS,
    max_hops: int = MAX_HOPS,
) -> ContinuationScope:
    """Breadth-first walk of redeemed handoffs from ``seeds`` (tenant-scoped)."""
    ordered_seeds = sorted({str(s) for s in seeds if s})
    if not ordered_seeds:
        raise ValueError("at least one anonymous ID seed is required")
    repo = get_journey_handoff_repository()
    seen: set[str] = set(ordered_seeds)
    frontier = list(ordered_seeds)
    handoffs: dict[str, dict[str, Any]] = {}
    truncated = False
    hops = 0
    while frontier:
        if hops >= max_hops:
            truncated = True
            break
        hops += 1
        rows = await repo.redeemed_for_anonymous_ids(tenant_id, frontier)
        next_frontier: list[str] = []
        for row in rows:
            if row.get("tenant_id") not in (None, tenant_id):
                continue  # defence in depth; the repository already scopes by tenant
            handoffs.setdefault(str(row["handoff_id"]), row)
            for end in (row.get("source_anonymous_id"), row.get("redeemed_anonymous_id")):
                if not end or end in seen:
                    continue
                if len(seen) >= max_anonymous_ids:
                    truncated = True
                    continue
                seen.add(end)
                next_frontier.append(end)
        frontier = sorted(next_frontier)
    if not handoffs:
        return _single(ordered_seeds[0]) if len(ordered_seeds) == 1 else ContinuationScope(
            root_anonymous_id=ordered_seeds[0], anonymous_ids=tuple(ordered_seeds),
        )
    ordered = sorted(handoffs.values(), key=lambda r: (str(r.get("created_at")), str(r["handoff_id"])))
    root = next(
        (str(r["source_anonymous_id"]) for r in ordered if r.get("source_anonymous_id") in seen),
        ordered_seeds[0],
    )
    return ContinuationScope(
        root_anonymous_id=root,
        anonymous_ids=tuple(sorted(seen)),
        handoffs=tuple(ordered),
        truncated=truncated,
    )
