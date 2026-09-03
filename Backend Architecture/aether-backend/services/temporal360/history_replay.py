"""``graph_history_replay`` — the knowledge-time reconstruction authority (T2.1).

The pending authority temporal360 resolves: reconstruct the graph state Aether
actually had at a knowledge instant τ (system time), from the append-only
mutation ledger + ``graph_fact_versions``. Read-only, digest-verifiable,
tenant-scoped, and never a second history store — the bitemporal ledger stays
the record.

* **KNOWN_THEN** — :meth:`GraphHistoryReplay.known_as_of` replays the ledger
  prefix closed at τ (``recorded_at <= τ``, ledger order, via
  :meth:`repositories.graph_mutation_ledger.GraphMutationLedgerRepository.list_records_known_as_of`)
  into a fresh in-memory graph (:func:`replay_state`) and returns the
  materialized vertices/edges Aether had at τ.
* **KNOWN_NOW** — :meth:`GraphHistoryReplay.known_now` replays the full ledger
  (the current known state).
* **Corrections** — :meth:`GraphHistoryReplay.corrections_between` diffs two
  reconstructed snapshots (topology + property supersessions) so a correction
  surfaces as a change — never as a silent rewrite of history.

Digest-verifiable: a snapshot's ``digest`` is the sha256 over the reconstructed
state, identical to replaying the same prefix again — reconstruct twice and the
digests must match.

No write path: nothing here appends, closes, or mutates canonical state; the
authority only ever reads the ledger and returns reconstructed state.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from repositories.graph_mutation_ledger import GraphMutationLedgerRepository
from shared.common.common import parse_iso
from shared.graph.graph import Edge, Vertex
from shared.graph.mutation_gateway import GraphReplayState, replay_state

# list_records truncates at this ceiling; reconstruction of "known now" reads
# the whole tenant ledger (bounded, paginated reads remain available).
_KNOWN_NOW_LIMIT = 100_000


def _edge_identity(edge: Edge) -> tuple[str, str, str]:
    """An edge's three-part key (the graph's unique edge identity)."""
    return (edge.edge_type, edge.from_vertex_id, edge.to_vertex_id)


def _props_changed(left: dict[str, Any], right: dict[str, Any]) -> bool:
    """True when two property maps differ (supersession of a vertex/edge)."""
    return left != right


def _edge_live(edge: Edge) -> bool:
    """A live edge is one the graph serves today — a revoked edge stays in the
    canonical edge list (flagged ``revoked: True``, exactly the digest view)
    but is no longer live. ``corrections_between`` reasons over live topology,
    so a revocation reads as the edge being removed, not silently rewritten."""
    return not bool((edge.properties or {}).get("revoked"))


@dataclass(frozen=True)
class KnownState:
    """A tenant graph state as Aether knew it at a knowledge instant.

    ``state`` is the materialized reconstruction (vertices/edges + sha256
    ``digest``); ``row_count`` / ``last_offset`` identify the exact ledger
    prefix that produced it, so a reconstruction is reproducible.
    """

    as_of: str
    state: GraphReplayState
    row_count: int
    last_offset: Optional[int]


class GraphHistoryReplay:
    """Read-side knowledge-time reconstruction authority (no write path)."""

    def __init__(
        self, ledger: Optional[GraphMutationLedgerRepository] = None
    ) -> None:
        """``ledger`` may be injected (tests / shared instance); the default is
        the process ledger repository."""
        self._ledger = ledger or GraphMutationLedgerRepository()

    async def known_as_of(
        self,
        tenant_id: str,
        as_of: str,
        *,
        aggregate_id: Optional[str] = None,
    ) -> KnownState:
        """Reconstruct the graph state Aether knew at the knowledge instant
        ``as_of`` (ISO-8601). ``KNOWN_THEN``.

        ``state.edges`` is the canonical edge list — a revoked edge stays in it
        flagged ``revoked: True`` (the digest view); live topology reasoning is
        :meth:`corrections_between`'s job.

        Raises ``BadRequestError`` for an unparseable ``as_of``; never mutates
        the ledger.
        """
        parse_iso(as_of)  # raises BadRequestError — never a silent empty
        rows = await self._ledger.list_records_known_as_of(
            tenant_id, as_of, aggregate_id=aggregate_id
        )
        return self._from_rows(as_of, rows)

    async def known_now(
        self,
        tenant_id: str,
        *,
        aggregate_id: Optional[str] = None,
    ) -> KnownState:
        """Reconstruct the current known state (the full ledger). ``KNOWN_NOW``."""
        rows = await self._ledger.list_records(
            tenant_id, aggregate_id=aggregate_id, limit=_KNOWN_NOW_LIMIT
        )
        return self._from_rows("now", rows)

    async def digest_known_as_of(
        self,
        tenant_id: str,
        as_of: str,
        *,
        aggregate_id: Optional[str] = None,
    ) -> str:
        """The reconstruction digest at τ (deterministic — verifiable)."""
        return (await self.known_as_of(tenant_id, as_of, aggregate_id=aggregate_id)).state.digest

    @staticmethod
    def corrections_between(then: KnownState, now: KnownState) -> dict[str, Any]:
        """Identity + supersession diff of ``now`` relative to ``then``.

        Pure function over live topology: a revoked edge (still present but
        flagged in the canonical list) reads as removed; a live edge whose
        three-part key persists but whose properties were superseded is
        "changed". Returns added/removed/changed vertex ids and edge keys plus
        live counts — the raw material a ``KNOWN_NOW`` vs ``KNOWN_THEN``
        correction story is built from.
        """
        then_vertices = set(then.state.vertices)
        now_vertices = set(now.state.vertices)
        then_edges = {_edge_identity(e) for e in then.state.edges if _edge_live(e)}
        now_edges = {_edge_identity(e) for e in now.state.edges if _edge_live(e)}

        then_v_props = {
            vid: dict(v.properties) for vid, v in then.state.vertices.items()
        }
        now_v_props = {
            vid: dict(v.properties) for vid, v in now.state.vertices.items()
        }
        then_e_props = {
            _edge_identity(e): dict(e.properties)
            for e in then.state.edges
            if _edge_live(e)
        }
        now_e_props = {
            _edge_identity(e): dict(e.properties)
            for e in now.state.edges
            if _edge_live(e)
        }

        shared_vertices = then_vertices & now_vertices
        changed_vertices = sorted(
            vid
            for vid in shared_vertices
            if _props_changed(then_v_props[vid], now_v_props.get(vid, {}))
        )
        shared_edges = then_edges & now_edges
        changed_edges = sorted(
            key
            for key in shared_edges
            if _props_changed(then_e_props[key], now_e_props.get(key, {}))
        )

        return {
            "added_vertices": sorted(now_vertices - then_vertices),
            "removed_vertices": sorted(then_vertices - now_vertices),
            "changed_vertices": changed_vertices,
            "added_edges": sorted(now_edges - then_edges),
            "removed_edges": sorted(then_edges - now_edges),
            "changed_edges": changed_edges,
            "vertex_count": {"then": len(then_vertices), "now": len(now_vertices)},
            "edge_count": {"then": len(then_edges), "now": len(now_edges)},
        }

    @staticmethod
    def _from_rows(as_of: str, rows: list[dict]) -> KnownState:
        state = replay_state(rows)
        return KnownState(
            as_of=as_of,
            state=state,
            row_count=len(rows),
            last_offset=rows[-1].get("ledger_offset") if rows else None,
        )


__all__ = [
    "GraphHistoryReplay",
    "KnownState",
]
