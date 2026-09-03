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

Recompute + erasure honesty (temporal360 T2.3): reconstruction persists nothing
and rebuilds from the ledger prefix at every read, so no cached artifact needs a
DSR component and no stale snapshot can outlive a canonical change. A row that
arrives late (``recorded_at <= tau`` appended after an earlier answer) is
honoured by the next read at the same ``tau`` — the fuller prefix, recomputed
idempotently. An erasure is a terminal canonical state (the append-only ledger
tombstones the vertex/edge rather than deleting the row): KNOWN_NOW serves the
erased state and never resurrects the pre-erasure live fact, while KNOWN_THEN
before the erase remains the honest audit record of what was known then.

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


def _row_is_revocation(row: dict) -> bool:
    """True for an edge-revocation ledger row (the canonical close-and-append
    revocation the gateway writes carries ``payload.kind == edge_revocation``)."""
    return ((row.get("payload") or {}).get("kind")) == "edge_revocation"


def _row_touches_subject(row: dict, subject_id: str) -> bool:
    """Whether a ledger row concerns ``subject_id``: the row's own aggregate
    (a vertex write's aggregate is its vertex id; an edge's aggregate is its
    three-part key — both match a subject) or, for an incident edge, one of
    its endpoints. Vertex writes for OTHER vertices never mention this subject,
    so this set is exactly the subject's own evolution."""
    payload = row.get("payload") or {}
    if str(row.get("aggregate_id") or "") == subject_id:
        return True
    if payload.get("vertex_id") == subject_id:
        return True
    if payload.get("from_vertex_id") == subject_id:
        return True
    if payload.get("to_vertex_id") == subject_id:
        return True
    return False


def _prop_delta(
    before: dict[str, Any], after: dict[str, Any]
) -> dict[str, dict[str, Any]]:
    """Keys whose value changed between two property maps (supersession)."""
    return {
        key: {"before": before.get(key), "after": after.get(key)}
        for key in set(before) | set(after)
        if before.get(key) != after.get(key)
    }


@dataclass(frozen=True)
class SubjectEvent:
    """One ledger transition touching a subject, in ledger order.

    ``kind`` is the derived transition — ``vertex_created`` /
    ``vertex_superseded`` for the subject's own node rows, ``edge_added`` /
    ``edge_revoked`` for incident edge rows. ``changed`` carries the
    superseded properties (before/after) for a vertex supersession. Every
    event names its source ledger row (``mutation_id`` + ``ledger_offset``) so
    a timeline entry is evidence-grounded.
    """

    recorded_at: str
    ledger_offset: int
    kind: str
    operation: str
    aggregate_type: str
    aggregate_id: str
    mutation_id: str
    valid_from: Optional[str] = None
    vertex_id: Optional[str] = None
    edge_type: Optional[str] = None
    from_vertex_id: Optional[str] = None
    to_vertex_id: Optional[str] = None
    changed: Optional[dict[str, dict[str, Any]]] = None
    reason: Optional[str] = None


@dataclass(frozen=True)
class SubjectHistory:
    """A subject's own local history reconstructed from its ledger rows.

    ``vertex`` is the subject's reconstructed property state at the anchor
    (``as_of``); ``present`` is whether that vertex is known. ``events`` are
    the subject's ordered transitions. ``digest`` is sha256 over the
    subject-scoped prefix (replaying exactly those rows reproduces it), so a
    subject timeline is verifiable exactly like a full reconstruction.
    """

    subject_id: str
    as_of: Optional[str]
    present: bool
    vertex: Optional[dict[str, Any]]
    first_recorded: Optional[str]
    last_recorded: Optional[str]
    event_count: int
    events: tuple[SubjectEvent, ...]
    live_edges: tuple[tuple[str, str, str], ...]
    vertex_supersessions: int
    incident_edge_adds: int
    incident_edge_revocations: int
    digest: str


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

    async def subject_history(
        self,
        tenant_id: str,
        subject_id: str,
        *,
        as_of: Optional[str] = None,
    ) -> SubjectHistory:
        """A subject's local history reconstructed from its own ledger rows.

        KNOWN_THEN (``as_of`` set, prefix closed at τ) or KNOWN_NOW (full
        ledger). The subject's own node rows (its supersessions) and the
        incident edge rows (adds/revocations) are replayed in ledger order into
        an ordered :class:`SubjectEvent` timeline plus the reconstructed vertex
        state — the raw material a ``timeline``/``findings`` section is built
        from. Read-only and digest-verifiable (``digest`` reproduces when the
        same subject rows are replayed); never mutates the ledger.

        A vertex the ledger never mentions is ``present: False`` with no events
        — an honest ``unknown`` subject, never a fabricated empty one.
        """
        if as_of is not None:
            rows = await self._ledger.list_records_known_as_of(
                tenant_id, as_of
            )
        else:
            rows = await self._ledger.list_records(
                tenant_id, limit=_KNOWN_NOW_LIMIT
            )
        subject_rows = [r for r in rows if _row_touches_subject(r, subject_id)]
        return self._history_from_rows(subject_id, as_of, subject_rows)

    # ── Subject-history reconstruction (pure, unit-testable) ───────────────

    @staticmethod
    def _history_from_rows(
        subject_id: str, as_of: Optional[str], rows: list[dict]
    ) -> SubjectHistory:
        """Replay subject-scoped rows into a :class:`SubjectHistory`.

        Pure and deterministic: the same rows always produce the same events
        and digest. Node rows carry the subject's vertex supersessions;
        incident edge rows carry adds/revocations.
        """
        vertex_props: Optional[dict[str, Any]] = None
        live_edges: set[tuple[str, str, str]] = set()
        events: list[SubjectEvent] = []
        supersessions = 0
        edge_adds = 0
        edge_revocations = 0

        for row in rows:
            payload = row.get("payload") or {}
            kind = payload.get("kind")
            operation = row.get("operation", "")
            common = dict(
                recorded_at=str(row.get("recorded_at") or ""),
                ledger_offset=int(row.get("ledger_offset") or 0),
                operation=operation,
                aggregate_type=str(row.get("aggregate_type") or ""),
                aggregate_id=str(row.get("aggregate_id") or ""),
                mutation_id=str(row.get("mutation_id") or ""),
                valid_from=row.get("valid_from"),
            )

            if kind == "node" and payload.get("vertex_id") == subject_id:
                new_props = dict(payload.get("properties") or {})
                if vertex_props is None:
                    events.append(
                        SubjectEvent(
                            kind="vertex_created",
                            vertex_id=subject_id,
                            changed=_prop_delta({}, new_props) or None,
                            **common,
                        )
                    )
                else:
                    delta = _prop_delta(vertex_props, new_props)
                    supersessions += 1
                    events.append(
                        SubjectEvent(
                            kind="vertex_superseded",
                            vertex_id=subject_id,
                            changed=delta or None,
                            **common,
                        )
                    )
                vertex_props = new_props

            elif kind == "edge" and _row_touches_subject(row, subject_id):
                key = (
                    str(payload["edge_type"]),
                    str(payload["from_vertex_id"]),
                    str(payload["to_vertex_id"]),
                )
                if key in live_edges:
                    # A live edge is never re-added (changes revoke-then-re-add);
                    # a duplicate would be a ledger anomaly — skip the noise.
                    continue
                live_edges.add(key)
                edge_adds += 1
                events.append(
                    SubjectEvent(
                        kind="edge_added",
                        edge_type=key[0],
                        from_vertex_id=key[1],
                        to_vertex_id=key[2],
                        **common,
                    )
                )

            elif _row_is_revocation(row) and _row_touches_subject(row, subject_id):
                key = (
                    str(payload.get("edge_type", "")),
                    str(payload.get("from_vertex_id", "")),
                    str(payload.get("to_vertex_id", "")),
                )
                if key in live_edges:
                    live_edges.remove(key)
                edge_revocations += 1
                events.append(
                    SubjectEvent(
                        kind="edge_revoked",
                        edge_type=key[0] or None,
                        from_vertex_id=key[1] or None,
                        to_vertex_id=key[2] or None,
                        reason=payload.get("reason"),
                        **common,
                    )
                )

        return SubjectHistory(
            subject_id=subject_id,
            as_of=as_of,
            present=vertex_props is not None,
            vertex=dict(vertex_props) if vertex_props is not None else None,
            first_recorded=events[0].recorded_at if events else None,
            last_recorded=events[-1].recorded_at if events else None,
            event_count=len(events),
            events=tuple(events),
            live_edges=tuple(sorted(live_edges)),
            vertex_supersessions=supersessions,
            incident_edge_adds=edge_adds,
            incident_edge_revocations=edge_revocations,
            digest=replay_state(rows).digest,
        )

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
    "SubjectEvent",
    "SubjectHistory",
]
