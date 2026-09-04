"""Temporal360 intelligence-projection provider (phase 2, workstreams T2.2/T2.3).

Temporal360 is Aether's **contextual time projection** over canonical Aether
truth — never a competing system of record (ADR-010). It answers the two time
questions the bitemporal graph stores separately but has never served as one
surface:

* **valid time** — "what was true of this subject during window W?" (KNOWN_NOW
  state + its event timeline, sliced to the requested window);
* **knowledge time** — "what did Aether know at τ, and what does it know now?"
  (KNOWN_THEN vs KNOWN_NOW via the :class:`~services.temporal360.history_replay.GraphHistoryReplay`
  authority the program built in T2.1).

The provider is read-only, fail-isolated, tenant-scoped and evidence-grounded:

* It raises ONLY :class:`ProjectionError` subclasses; the registry
  fail-isolates anything else.
* It degrades sections / temporal modes (typed ``degraded`` / ``missing`` /
  ``unknown`` states, typed reasons) instead of raising or silently relabeling a
  knowledge-time answer as a valid-time one.
* An ``unknown`` subject, an empty window, and ``not_applicable`` reconstruction
  are distinct states — never coerced into ``0`` / ``false`` / ``empty``.
* Every timeline entry and claim names its source ledger ``mutation_id`` as a
  reused canonical :class:`EvidenceRef`.

Canonical reads happen only inside :meth:`Temporal360Provider.project` through
an injected :class:`TemporalReader` seam; the default reads the
``graph_history_replay`` authority. Imports stay lazy/defensive: importing this
module must never require a database.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional, Protocol

# Lightweight plane imports — always importable.
from shared.intelligence_projections.contracts import (
    ClaimEnvelope,
    ProjectionContext,
    ProjectionRequest,
    ProjectionResult,
    ProjectionSection,
)
from shared.intelligence_projections.generated_registry import (
    INTELLIGENCE_PROJECTIONS_CONTRACT_VERSION,
)
from shared.intelligence_projections.provider import IntelligenceProjectionProvider
from shared.intelligence_projections.registry import ProviderRegistry

# Reused canonical primitives (never redefined here).
from services.operational_intelligence.models import EvidenceRef, TimeRangeFilter

from services.temporal360.history_replay import (
    GraphHistoryReplay,
    SubjectEvent,
    SubjectHistory,
)

# Sections the registry declares for temporal360 (matches outputSections order).
OUTPUT_SECTIONS: tuple[str, ...] = (
    "summary",
    "state",
    "timeline",
    "evidence",
    "findings",
)

# The four registry surface modes temporal360 supports.
SUPPORTED_TEMPORAL_MODES: frozenset[str] = frozenset(
    {"window", "as_of", "compare", "relative"}
)

# Section-state severity (lowest index wins the section's typed state).
_STATE_RANK = {
    "available": 0,
    "not_applicable": 1,
    "empty": 2,
    "unknown": 3,
    "degraded": 4,
    "missing": 5,
    "suppressed": 6,
    "stale": 7,
}


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── Canonical read seam (injected in tests; ledger-backed in production) ────


class TemporalReader(Protocol):
    """The read authority a Temporal360 projection reconstructs from.

    ``subject_history`` returns a subject's local history (timeline events +
    reconstructed vertex state) at the given anchor — the whole ledger
    (KNOWN_NOW) when ``as_of`` is None, else the prefix closed at τ
    (KNOWN_THEN).
    """

    async def subject_history(
        self,
        *,
        tenant_id: str,
        subject_id: str,
        as_of: Optional[str] = None,
    ) -> SubjectHistory:
        ...


class LedgerTemporalReader:
    """Default reader over the ``graph_history_replay`` authority."""

    def __init__(self, replay: Optional[GraphHistoryReplay] = None) -> None:
        self._replay = replay if replay is not None else GraphHistoryReplay()

    async def subject_history(
        self,
        *,
        tenant_id: str,
        subject_id: str,
        as_of: Optional[str] = None,
    ) -> SubjectHistory:
        return await self._replay.subject_history(
            tenant_id, subject_id, as_of=as_of
        )


# ── Knowledge anchor ────────────────────────────────────────────────────────


@dataclass(frozen=True)
class _KnowledgeAnchor:
    """What temporal question this request asks, resolved and typed.

    ``engine_mode`` is one of ``KNOWN_NOW`` / ``KNOWN_THEN`` / ``COMPARE`` —
    the honest label for what is served. A reconstruction request without its
    as-of instant is answered as KNOWN_NOW but flagged ``degraded`` with a
    typed reason (never silently relabeled).
    """

    surface_mode: str
    engine_mode: str
    as_of: Optional[str]
    requires_then: bool
    window_from: Optional[str]
    window_to: Optional[str]
    degraded: bool
    degraded_reason: Optional[str]


def _resolve_anchor(
    mode: Optional[str], time_range: Optional[TimeRangeFilter]
) -> _KnowledgeAnchor:
    """Map a registry surface mode onto what this provider serves.

    ``window``/``relative`` project KNOWN_NOW (optionally sliced to a window);
    ``as_of``/``compare`` reconstruct KNOWN_THEN at the as-of instant carried in
    ``timeRange.from``. An ``as_of``/``compare`` without that instant degrades
    to KNOWN_NOW with a typed reason — the provider never relabels silently.
    """
    surface = mode or "window"
    window_from = time_range.from_ if time_range else None
    window_to = time_range.to if time_range else None

    if surface in ("window", "relative"):
        return _KnowledgeAnchor(
            surface_mode=surface,
            engine_mode="KNOWN_NOW",
            as_of=None,
            requires_then=False,
            window_from=window_from,
            window_to=window_to,
            degraded=False,
            degraded_reason=None,
        )

    if surface in ("as_of", "compare"):
        as_of = window_from  # a single instant = the knowledge cutoff τ
        if as_of is not None:
            return _KnowledgeAnchor(
                surface_mode=surface,
                engine_mode="KNOWN_THEN" if surface == "as_of" else "COMPARE",
                as_of=as_of,
                requires_then=True,
                window_from=None,
                window_to=None,
                degraded=False,
                degraded_reason=None,
            )
        return _KnowledgeAnchor(
            surface_mode=surface,
            engine_mode="KNOWN_NOW",
            as_of=None,
            requires_then=False,
            window_from=None,
            window_to=None,
            degraded=True,
            degraded_reason=(
                f"{surface!r} needs an as-of instant (timeRange.from); none was "
                "provided — answered as known-now, never relabeled"
            ),
        )

    return _KnowledgeAnchor(
        surface_mode=surface,
        engine_mode="KNOWN_NOW",
        as_of=None,
        requires_then=False,
        window_from=window_from,
        window_to=window_to,
        degraded=True,
        degraded_reason=(
            f"unsupported temporal mode {surface!r}; answered as known-now "
            "(window), never silently relabeled"
        ),
    )


# ── Subject-correction diff (pure) ──────────────────────────────────────────


def _subject_corrections(
    then: SubjectHistory, now: SubjectHistory
) -> dict[str, Any]:
    """KNOWN_THEN(τ) vs KNOWN_NOW corrections for one subject (pure).

    Vertex property supersessions plus the LIVE-topology edge diff (an edge
    recorded as added but since revoked is not live — liveness comes from the
    reconstruction's final state, never from event presence). The honest
    correction story a ``findings`` section is built from. Never mutates.
    """
    then_vertex = then.vertex or {}
    now_vertex = now.vertex or {}
    changed_keys = sorted(
        k
        for k in set(then_vertex) | set(now_vertex)
        if then_vertex.get(k) != now_vertex.get(k)
    )

    then_live = set(then.live_edges)
    now_live = set(now.live_edges)

    return {
        "vertex_changed_keys": changed_keys,
        "edges_revoked_since": sorted(then_live - now_live),
        "edges_added_since": sorted(now_live - then_live),
        "supersessions_since": max(0, now.vertex_supersessions - then.vertex_supersessions),
        "event_count": {"then": then.event_count, "now": now.event_count},
    }


def _events_in_window(
    events: tuple[SubjectEvent, ...], time_range: Optional[TimeRangeFilter]
) -> tuple[list[SubjectEvent], bool]:
    """Slice events by the requested valid window.

    Returns ``(events, bounded)`` — ``bounded`` is False when no window bounds
    were given (nothing was filtered). An event with no valid-from is excluded
    from a bounded slice rather than guessed into it.
    """
    if time_range is None or (time_range.from_ is None and time_range.to is None):
        return list(events), False
    window_from = time_range.from_
    window_to = time_range.to

    def _inside(e: SubjectEvent) -> bool:
        vf = e.valid_from
        if vf is None:
            return False
        if window_from is not None and vf < window_from:
            return False
        if window_to is not None and vf > window_to:
            return False
        return True

    return [e for e in events if _inside(e)], True


# ── Provider ────────────────────────────────────────────────────────────────


class Temporal360Provider:
    """Intelligence-projection provider for ``temporal360`` (read-only)."""

    projection_id = "temporal360"
    contract_version = INTELLIGENCE_PROJECTIONS_CONTRACT_VERSION
    graph_mutation_policy = "read_only"

    def __init__(self, reader: Optional[TemporalReader] = None) -> None:
        # Injected canonical reader (test seam); default reads the replay
        # authority over the ledger.
        self._reader = reader if reader is not None else LedgerTemporalReader()

    # ── IntelligenceProjectionProvider ─────────────────────────────────────

    async def project(
        self,
        request: ProjectionRequest,
        context: ProjectionContext,
    ) -> ProjectionResult:
        """Run one read-only Temporal360 projection over canonical Aether truth."""
        tenant_id = request.tenantId
        subject = request.subject
        anchor = _resolve_anchor(request.temporalMode, request.timeRange)

        history_now, now_ok = await self._safe_subject_history(
            tenant_id, subject.id, as_of=None
        )
        history_then, then_ok = (
            await self._safe_subject_history(tenant_id, subject.id, as_of=anchor.as_of)
            if anchor.requires_then
            else (None, True)
        )
        # A failed reconstruction read is a degraded anchor, not a silent KNOWN_NOW.
        read_failed = not now_ok or (anchor.requires_then and not then_ok)

        # What is SERVED for display: KNOWN_THEN serves the state at τ (an
        # as_of answer); COMPARE and KNOWN_NOW serve the current state. A
        # reconstruction that failed falls back to KNOWN_NOW, already flagged.
        served = history_now
        if (
            anchor.engine_mode == "KNOWN_THEN"
            and history_then is not None
            and then_ok
        ):
            served = history_then

        corrections = (
            _subject_corrections(history_then, history_now)
            if history_then is not None and history_now is not None
            else None
        )
        # Only window/relative slice the served timeline by the request window;
        # for as_of/compare the instant in timeRange.from is a knowledge cutoff,
        # not a display window.
        if anchor.surface_mode in ("window", "relative"):
            window_events, bounded = _events_in_window(
                served.events if served else (), request.timeRange
            )
        else:
            window_events, bounded = (list(served.events) if served else []), False

        sections = [
            self._summary_section(request, anchor, served, read_failed),
            self._state_section(
                anchor, served, window_events, bounded, read_failed
            ),
            self._timeline_section(request, anchor, served, window_events, bounded),
            self._evidence_section(request, history_now, history_then),
            self._findings_section(
                request, anchor, served, corrections, window_events, bounded
            ),
        ]
        claims = self._build_claims(request, anchor, served, corrections)

        return ProjectionResult(
            projectionId=self.projection_id,
            tenantId=tenant_id,
            contractVersion=self.contract_version,
            sections=sections,
            claims=claims,
            dependencyState=list(context.dependencyState),
            asOf=anchor.as_of or _utc_now_iso(),
            generatedAt=_utc_now_iso(),
            degradedReasons=[],
            temporalMode=anchor.surface_mode,
            lensIds=request.lensIds,
        )

    # ── Section builders ───────────────────────────────────────────────────

    def _summary_section(
        self,
        request: ProjectionRequest,
        anchor: _KnowledgeAnchor,
        history: Optional[SubjectHistory],
        read_failed: bool,
    ) -> ProjectionSection:
        """summary — the subject's temporal posture under the requested anchor."""
        present = bool(history and history.present)
        event_count = history.event_count if history else 0
        warnings: list[str] = []
        if read_failed:
            warnings.append(
                "the reconstruction authority was unavailable; sections are "
                "degraded, not fabricated"
            )
        if anchor.degraded and anchor.degraded_reason:
            warnings.append(anchor.degraded_reason)

        state: str = "degraded" if read_failed or anchor.degraded else (
            "available" if present or event_count else "missing"
        )
        return ProjectionSection(
            id="summary",
            state=state,  # type: ignore[arg-type]
            title="Temporal posture",
            content={
                "subject": {
                    "kind": request.subject.kind,
                    "id": request.subject.id,
                },
                "mode": anchor.engine_mode,
                "asOf": anchor.as_of,
                "subject_known": present or event_count > 0,
                "vertex_present": present,
                "event_count": event_count,
                "first_recorded": history.first_recorded if history else None,
                "last_recorded": history.last_recorded if history else None,
            },
            warnings=warnings or None,
        )

    def _state_section(
        self,
        anchor: _KnowledgeAnchor,
        history: Optional[SubjectHistory],
        window_events: list[SubjectEvent],
        bounded: bool,
        read_failed: bool,
    ) -> ProjectionSection:
        """state — typed per-dimension temporal state (unknown != empty != 0)."""
        subject_known = bool(history and (history.present or history.event_count))

        dims: list[dict[str, Any]] = []
        dims.append(
            {
                "id": "subject_known",
                "state": "available" if subject_known else "unknown",
                "reason": None if subject_known else "the ledger records no activity for this subject",
            }
        )
        # Reconstruction is the section's core authority; window/relative never
        # claim a KNOWN_THEN they did not run.
        if anchor.requires_then:
            if read_failed:
                dims.append(
                    {
                        "id": "knowledge_reconstruction",
                        "state": "degraded",
                        "reason": "the graph_history_replay authority was unavailable",
                    }
                )
            else:
                dims.append(
                    {
                        "id": "knowledge_reconstruction",
                        "state": "available",
                        "reason": None,
                    }
                )
        else:
            dims.append(
                {
                    "id": "knowledge_reconstruction",
                    "state": "not_applicable",
                    "reason": "no knowledge-time reconstruction requested",
                }
            )
        # A bounded window with no observation is unknown, never empty-by-omission.
        if anchor.surface_mode in ("window", "relative") or not anchor.requires_then:
            if not subject_known:
                dims.append(
                    {
                        "id": "activity_in_window",
                        "state": "unknown",
                        "reason": "no subject activity is known",
                    }
                )
            elif bounded and not window_events:
                dims.append(
                    {
                        "id": "activity_in_window",
                        "state": "unknown",
                        "reason": "no observation falls in the requested window",
                    }
                )
            else:
                dims.append(
                    {
                        "id": "activity_in_window",
                        "state": "available",
                        "reason": None,
                    }
                )

        if anchor.degraded and anchor.degraded_reason:
            dims.append(
                {
                    "id": "mode",
                    "state": "degraded",
                    "reason": anchor.degraded_reason,
                }
            )

        worst_state = _worst_dimension(dims)
        warnings = [d["reason"] for d in dims if d["reason"] is not None]
        return ProjectionSection(
            id="state",
            state=worst_state,
            title="Temporal state",
            content={
                "mode": anchor.engine_mode,
                "dimensions": dims,
            },
            warnings=warnings or None,
        )

    def _timeline_section(
        self,
        request: ProjectionRequest,
        anchor: _KnowledgeAnchor,
        history: Optional[SubjectHistory],
        window_events: list[SubjectEvent],
        bounded: bool,
    ) -> ProjectionSection:
        """timeline — ordered subject transitions, each evidence-grounded."""
        if history is None or (not history.present and history.event_count == 0):
            return ProjectionSection(
                id="timeline",
                state="missing",
                title="Timeline",
                content={
                    "mode": anchor.engine_mode,
                    "count": 0,
                    "events": [],
                },
                warnings=[
                    "the ledger records no activity for this subject; nothing is "
                    "timelined"
                ],
            )

        if bounded and not window_events:
            return ProjectionSection(
                id="timeline",
                state="unknown",
                title="Timeline",
                content={
                    "mode": anchor.engine_mode,
                    "window": {
                        "from": request.timeRange.from_ if request.timeRange else None,
                        "to": request.timeRange.to if request.timeRange else None,
                    },
                    "count": 0,
                    "total": history.event_count,
                    "events": [],
                },
                warnings=["no observation falls in the requested window"],
            )

        return ProjectionSection(
            id="timeline",
            state="available",
            title="Timeline",
            content={
                "mode": anchor.engine_mode,
                "asOf": anchor.as_of,
                "window": {
                    "from": request.timeRange.from_ if request.timeRange else None,
                    "to": request.timeRange.to if request.timeRange else None,
                },
                "count": len(window_events),
                "total": history.event_count,
                "events": [_event_to_dict(e) for e in window_events],
            },
        )

    def _evidence_section(
        self,
        request: ProjectionRequest,
        history_now: Optional[SubjectHistory],
        history_then: Optional[SubjectHistory],
    ) -> ProjectionSection:
        """evidence — the reused EvidenceRefs grounding timeline + findings."""
        refs = _evidence_from_histories(request, history_now, history_then)
        return ProjectionSection(
            id="evidence",
            state="available" if refs else "empty",
            title="Evidence",
            content={
                "count": len(refs),
                "evidence": [e.model_dump(mode="json") for e in refs],
            },
        )

    def _findings_section(
        self,
        request: ProjectionRequest,
        anchor: _KnowledgeAnchor,
        history: Optional[SubjectHistory],
        corrections: Optional[dict[str, Any]],
        window_events: list[SubjectEvent],
        bounded: bool,
    ) -> ProjectionSection:
        """findings — derived correction/supersession/staleness notices."""
        findings: list[dict[str, Any]] = []
        if anchor.degraded and anchor.degraded_reason:
            findings.append(
                {
                    "code": "mode.degraded",
                    "level": "warning",
                    "message": anchor.degraded_reason,
                }
            )
        if history is None or (not history.present and history.event_count == 0):
            findings.append(
                {
                    "code": "subject.unknown",
                    "level": "info",
                    "message": "the ledger records no activity for this subject",
                }
            )
        else:
            if corrections and corrections["vertex_changed_keys"]:
                findings.append(
                    {
                        "code": "correction.vertex_superseded",
                        "level": "warning",
                        "message": (
                            "subject state corrected since as-of: "
                            + ", ".join(corrections["vertex_changed_keys"])
                        ),
                    }
                )
            if corrections and corrections["edges_revoked_since"]:
                findings.append(
                    {
                        "code": "correction.edge_revoked",
                        "level": "warning",
                        "message": (
                            "incident relationship revoked since as-of: "
                            + "; ".join(
                                "→".join(filter(None, key))
                                for key in corrections["edges_revoked_since"]
                            )
                        ),
                    }
                )
            if corrections and corrections["edges_added_since"]:
                findings.append(
                    {
                        "code": "correction.edge_added",
                        "level": "info",
                        "message": (
                            "incident relationship added since as-of: "
                            + "; ".join(
                                "→".join(filter(None, key))
                                for key in corrections["edges_added_since"]
                            )
                        ),
                    }
                )
            if bounded and not window_events:
                findings.append(
                    {
                        "code": "window.no_observations",
                        "level": "info",
                        "message": (
                            "the requested window has no recorded observation "
                            "for this subject"
                        ),
                    }
                )
        return ProjectionSection(
            id="findings",
            state="available",
            title="Temporal findings",
            content={
                "findings": findings,
                "evidence_count": len(
                    _evidence_from_histories(request, history, None)
                ),
            },
        )

    # ── Claims ─────────────────────────────────────────────────────────────

    def _build_claims(
        self,
        request: ProjectionRequest,
        anchor: _KnowledgeAnchor,
        history: Optional[SubjectHistory],
        corrections: Optional[dict[str, Any]],
    ) -> list[ClaimEnvelope]:
        """Evidence-grounded claims (requiresEvidence: every claim is grounded)."""
        claims: list[ClaimEnvelope] = []
        subject = request.subject  # canonical subject — never re-derived
        refs = _evidence_from_histories(request, history, None)

        known = bool(history and (history.present or history.event_count))
        claims.append(
            ClaimEnvelope(
                id="summary.subject_known",
                kind="temporal_subject",
                subject=subject,
                evidenceRefs=refs[:5],
                claims=[
                    (
                        f"subject is known to the graph (events: {history.event_count})"
                        if known
                        else "subject is not known to the graph"
                    ),
                    f"served under {anchor.engine_mode}",
                ],
            )
        )
        if history and history.present:
            claims.append(
                ClaimEnvelope(
                    id="summary.vertex_state",
                    kind="temporal_vertex",
                    subject=subject,
                    evidenceRefs=refs[:5],
                    claims=[
                        f"vertex supersessions: {history.vertex_supersessions}",
                        f"incident edge adds: {history.incident_edge_adds}",
                        f"incident edge revocations: {history.incident_edge_revocations}",
                    ],
                )
            )
        if corrections and (
            corrections["vertex_changed_keys"]
            or corrections["edges_revoked_since"]
            or corrections["edges_added_since"]
        ):
            claims.append(
                ClaimEnvelope(
                    id="corrections.since_as_of",
                    kind="knowledge_correction",
                    subject=subject,
                    evidenceRefs=refs[:5],
                    claims=[
                        "state known now differs from state known at as-of",
                        f"{len(corrections['vertex_changed_keys'])} vertex "
                        "supersession(s) since as-of",
                        f"{len(corrections['edges_revoked_since'])} incident "
                        "edge revocation(s) since as-of",
                    ],
                )
            )
        return claims

    # ── Canonical read helpers (defensive) ─────────────────────────────────

    async def _safe_subject_history(
        self,
        tenant_id: str,
        subject_id: str,
        *,
        as_of: Optional[str],
    ) -> tuple[Optional[SubjectHistory], bool]:
        """Reconstructed subject history; a reader failure degrades, never raises."""
        try:
            history = await self._reader.subject_history(
                tenant_id=tenant_id, subject_id=subject_id, as_of=as_of
            )
            return history, True
        except Exception:  # noqa: BLE001 - backing authority unavailable -> degrade
            return None, False


# ── Pure helpers ────────────────────────────────────────────────────────────


def _worst_dimension(dims: list[dict[str, Any]]) -> str:
    """Most severe typed state among dimensions (available is best)."""
    return min(
        (d["state"] for d in dims),
        key=lambda s: _STATE_RANK.get(s, 100),
    )


def _event_to_dict(event: SubjectEvent) -> dict[str, Any]:
    return {
        "kind": event.kind,
        "recorded_at": event.recorded_at,
        "ledger_offset": event.ledger_offset,
        "operation": event.operation,
        "valid_from": event.valid_from,
        "vertex_id": event.vertex_id,
        "edge_type": event.edge_type,
        "from_vertex_id": event.from_vertex_id,
        "to_vertex_id": event.to_vertex_id,
        "changed": event.changed,
        "mutation_id": event.mutation_id,
        "reason": event.reason,
    }


def _evidence_from_histories(
    request: ProjectionRequest,
    *histories: Optional[SubjectHistory],
) -> list[EvidenceRef]:
    """One EvidenceRef per unique source mutation across the histories."""
    seen: set[str] = set()
    refs: list[EvidenceRef] = []
    for history in histories:
        if history is None:
            continue
        for event in history.events:
            if event.mutation_id in seen:
                continue
            seen.add(event.mutation_id)
            refs.append(
                EvidenceRef(
                    id=f"mutation:{event.mutation_id}",
                    type="event",
                    source="graph_mutation_ledger",
                    observedAt=event.recorded_at or None,
                )
            )
    return refs


def register_provider(registry: ProviderRegistry) -> None:
    """Register :class:`Temporal360Provider` on a provider registry.

    Deliberately NOT called at import time: the global ``projection_registry``
    is only mutated by the runtime wiring layer, never by provider modules.
    """
    registry.register(Temporal360Provider(), source="services/temporal360")


__all__ = [
    "LedgerTemporalReader",
    "OUTPUT_SECTIONS",
    "SUPPORTED_TEMPORAL_MODES",
    "Temporal360Provider",
    "TemporalReader",
    "register_provider",
]
