"""Population360 intelligence-projection provider (population360 P3.4).

Population360 is Aether's **contextual WHO / WHAT SET projection** — a governed,
read-only answer to "who is in this set, how did membership change, and how do
sets overlap and compose?" over the registry's ``subjectKinds: [entity,
population, cluster]``. It projects ``summary`` / ``state`` / ``timeline`` /
``evidence`` / ``findings`` over canonical population truth — never a competing
population store. The provider answers:

* for a **population / cluster subject** — that definition's posture: active
  membership count and composition (basis / confidence band / entity type), its
  snapshot history with consecutive snapshot **deltas**, its **overlap** against
  sibling populations, its immutable **definition transitions**, and the
  definition's membership semantics;
* for an **entity subject** — which population definitions it belongs to, with
  what membership state, and its own join/leave transition timeline.

Read-only, fail-isolated, tenant-scoped, evidence-grounded, and honest:

* It raises only :class:`ProjectionError` subclasses; the registry fail-isolates
  anything else, and backing-source failures degrade sections (typed
  ``degraded`` / ``missing``) instead of raising or fabricating.
* ``unknown`` subjects, an ``empty`` cohort, a ``missing`` snapshot source and a
  ``not_applicable`` surface stay distinct typed states — never coerced into
  ``0`` / ``false`` / ``empty``. A definition with no membership observation is
  ``unknown``, never a fabricated ``0`` member count.
* Every count / transition / overlap / definition claim names its grounding rows
  as reused canonical :class:`EvidenceRef` (membership rows, definition-version
  rows, snapshot rows).
* Read caps (member sample, sibling scan, evidence/transition lists) are surfaced
  as warnings when hit so an overlap / composition / count never pretends to be
  exact when it was bounded.

Canonical reads happen only through the injected :class:`Population360Reader`
seam; the default reads the Phase-3 population registries. The governed human
**demographic lens** (``services/population360.demographics`` — no
``Demographic360`` backend, standing rule 6) is carried as an injectable
component and served when a request explicitly names it via ``lensIds``; the lens
degrades honestly (``missing``) while ``profile360`` is ``in_flight`` and lifts
when it lands. Imports of the population stores stay inside the reader so
importing this module never requires a database.
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
from services.operational_intelligence.models import EvidenceRef

from services.population360.demographics import (
    DemographicLens,
    SmallCellSuppression,
)

# Sections the registry declares for population360 (matches outputSections order).
OUTPUT_SECTIONS: tuple[str, ...] = (
    "summary",
    "state",
    "timeline",
    "evidence",
    "findings",
)

# The registry surface modes population360 supports (window/relative only — no
# knowledge-time reconstruction here; that belongs to the temporal360 dep).
# ``relative`` is served as ``window`` (its natural parent), always honestly.
SUPPORTED_TEMPORAL_MODES: frozenset[str] = frozenset({"window", "relative"})

# The lensId a caller names to ask for the human demographic lens on a cohort.
DEMOGRAPHIC_LENS_ID = "demographic"

# Read bounds (honesty caps, not silent truncation — each cap surfaces when hit).
MEMBER_SAMPLE_CAP = 200        # members carried for composition/evidence/overlap
SIBLING_SCAN_CAP = 20          # sibling populations scanned for overlap surprises
SIBLING_MEMBER_CAP = 1000      # member ids read per sibling for overlap scoring
EVIDENCE_CAP = 100             # evidence refs listed in the evidence section
TRANSITION_CAP = 100           # transitions listed in the timeline section
OVERLAP_SURPRISE_MIN = 0.5     # overlap-surprise finding threshold (jaccard)

# Confidence band edges for composition.
CONFIDENCE_BANDS: tuple[tuple[float, str], ...] = (
    (0.4, "low"),
    (0.7, "medium"),
    (0.9, "high"),
    (1.0, "very_high"),
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


def _iso_aware(value: Optional[str]) -> str:
    """Normalise an ISO string for chronological sorting (all are UTC ISO)."""
    return value or ""


def _row_active(row: dict) -> bool:
    """A materialised membership row is active unless it says otherwise.

    Mirrors ``services.population.registry._membership_is_active``: governed rows
    carry ``membership_state`` (P3.1); pre-governance legacy rows carry only
    ``status="active"`` and are treated as active.
    """
    state = row.get("membership_state") or row.get("status") or "active"
    return state == "active"


# ── Canonical posture model (normalised read output) ──────────────────────────


@dataclass(frozen=True)
class MembershipRow:
    """One membership materialisation row (governed current-state, P3.1)."""

    population_id: str
    entity_id: str
    entity_type: str
    basis: str
    confidence: float
    reason: str
    membership_state: str
    definition_version: str
    source_tag: str
    joined_at: str
    left_at: str
    leave_reason: str


@dataclass(frozen=True)
class SiblingCandidate:
    """A sibling tenant population a population-subject overlap can be scored on."""

    population_id: str
    name: str
    population_type: str
    active_member_ids: tuple[str, ...]
    member_ids_truncated: bool


@dataclass(frozen=True)
class PopulationPosture:
    """Canonical population facts one population/cluster subject projects over."""

    population_id: str
    name: str
    population_type: str
    status: str
    definition_version: str
    consent_purpose: str
    created_at: str
    updated_at: str
    active_member_count: int                    # authoritative (over owned rows)
    members_sample: tuple[MembershipRow, ...]   # capped sample for composition
    members_truncated: bool
    snapshots: tuple[dict[str, Any], ...]       # snapshot rows, oldest -> newest
    definition_transitions: tuple[dict[str, Any], ...]  # version rows, oldest first
    siblings: tuple[SiblingCandidate, ...]      # capped sibling scan
    siblings_truncated: bool


@dataclass(frozen=True)
class EntityPosture:
    """Canonical facts one entity subject projects over (its memberships)."""

    entity_id: str
    # Enriched membership rows (incl. inactive); each carries the owning
    # population's name/type/status the reader verified is tenant-owned.
    memberships: tuple[dict[str, Any], ...]


@dataclass(frozen=True)
class SubjectView:
    """What the reader resolved for the requested subject (or why not)."""

    kind: str  # subject kind echoed
    id: str
    posture: Optional[PopulationPosture | EntityPosture]
    # None posture + reason => the plane has no owned observation of the subject.
    missing_reason: Optional[str]


# ── Canonical read seam (injected in tests; registry-backed in production) ────


class Population360Reader(Protocol):
    """The read authority a Population360 projection reconstructs from."""

    async def view(
        self, *, tenant_id: str, subject_kind: str, subject_id: str
    ) -> SubjectView:
        ...


def _membership_row(m: dict) -> MembershipRow:
    return MembershipRow(
        population_id=str(m.get("population_id", "")),
        entity_id=str(m.get("entity_id", "")),
        entity_type=str(m.get("entity_type", "user")),
        basis=str(m.get("basis", "unknown")),
        confidence=float(m.get("confidence", 0.0) or 0.0),
        reason=str(m.get("reason", "")),
        membership_state=str(m.get("membership_state") or m.get("status") or "active"),
        definition_version=str(m.get("definition_version") or "1"),
        source_tag=str(m.get("source_tag", "")),
        joined_at=str(m.get("joined_at") or ""),
        left_at=str(m.get("left_at") or ""),
        leave_reason=str(m.get("leave_reason") or ""),
    )


class PopulationRepositoryReader:
    """Default reader over the Phase-3 population registries (read-only).

    All reads are tenant-scoped; every posture value is materialised only from
    rows whose ``tenant_id`` equals the requesting tenant. A population id that
    is missing OR belongs to another tenant resolves to a ``None`` posture with a
    missing reason — never a cross-tenant leak.
    """

    async def view(
        self, *, tenant_id: str, subject_kind: str, subject_id: str
    ) -> SubjectView:
        from services.population.registry import (
            definition_repo,
            membership_repo,
            population_repo,
        )
        from services.population.scheduler import snapshot_repo

        if subject_kind in ("population", "cluster"):
            population = await population_repo.find_by_id(subject_id)
            if population is None or population.get("tenant_id") != tenant_id:
                return SubjectView(
                    kind=subject_kind,
                    id=subject_id,
                    posture=None,
                    missing_reason=(
                        "the population plane has no owned observation of this "
                        "subject"
                    ),
                )

            # Membership rows owned by THIS population, then tenant-filtered
            # (belt-and-braces fail-closed tenant scoping over the write-path
            # invariant that membership rows carry the population's tenant).
            rows = await membership_repo.find_many(
                filters={"population_id": subject_id}, limit=10000
            )
            owned = [m for m in rows if m.get("tenant_id") == tenant_id]
            active_rows = [m for m in owned if _row_active(m)]
            members_truncated = len(active_rows) > MEMBER_SAMPLE_CAP
            member_sample = tuple(
                _membership_row(m) for m in active_rows[:MEMBER_SAMPLE_CAP]
            )

            snapshots = await snapshot_repo.find_many(
                filters={"population_id": subject_id}, limit=10000
            )
            snapshots = sorted(
                (s for s in snapshots if s.get("tenant_id") == tenant_id),
                key=lambda r: _iso_aware(r.get("snapshot_at")),
            )

            transitions = await definition_repo.history(subject_id)

            # Sibling overlap scan (same tenant by construction; bounded, and the
            # bound is surfaced when hit).
            sibling_rows = await population_repo.query_populations(
                tenant_id=tenant_id, limit=SIBLING_SCAN_CAP + 1
            )
            siblings: list[SiblingCandidate] = []
            for sib in sibling_rows:
                if sib.get("id") == subject_id:
                    continue
                ids = await membership_repo.find_many(
                    filters={"population_id": sib.get("id", "")},
                    limit=SIBLING_MEMBER_CAP + 1,
                )
                active_ids = [m.get("entity_id", "") for m in ids if _row_active(m)]
                siblings.append(
                    SiblingCandidate(
                        population_id=str(sib.get("id", "")),
                        name=str(sib.get("name", "")),
                        population_type=str(sib.get("population_type", "")),
                        active_member_ids=tuple(active_ids[:SIBLING_MEMBER_CAP]),
                        member_ids_truncated=len(active_ids) > SIBLING_MEMBER_CAP,
                    )
                )
                if len(siblings) >= SIBLING_SCAN_CAP:
                    break

            posture = PopulationPosture(
                population_id=str(population["id"]),
                name=str(population.get("name", "")),
                population_type=str(population.get("population_type", "")),
                status=str(population.get("status", "")),
                definition_version=str(population.get("definition_version") or "1"),
                consent_purpose=str(population.get("consent_purpose") or "analytics"),
                created_at=str(population.get("created_at") or ""),
                updated_at=str(population.get("updated_at") or ""),
                active_member_count=len(active_rows),
                members_sample=member_sample,
                members_truncated=members_truncated,
                snapshots=tuple(snapshots),
                definition_transitions=tuple(transitions),
                siblings=tuple(siblings),
                siblings_truncated=len(sibling_rows) > SIBLING_SCAN_CAP,
            )
            return SubjectView(
                kind=subject_kind, id=subject_id, posture=posture, missing_reason=None
            )

        if subject_kind == "entity":
            from services.population.registry import membership_repo, population_repo

            rows = await membership_repo.find_many(
                filters={"entity_id": subject_id}, limit=10000
            )
            owned = [m for m in rows if m.get("tenant_id") == tenant_id]
            if not owned:
                return SubjectView(
                    kind="entity",
                    id=subject_id,
                    posture=None,
                    missing_reason=(
                        "the population plane has no membership observation of "
                        "this subject"
                    ),
                )
            enriched: list[dict[str, Any]] = []
            for m in owned:
                group = await population_repo.find_by_id(m.get("population_id", ""))
                same_tenant = group is not None and group.get("tenant_id") == tenant_id
                enriched.append({
                    **m,
                    "population_name": (group or {}).get("name", "") if same_tenant else "",
                    "population_type": (
                        (group or {}).get("population_type", "") if same_tenant else ""
                    ),
                    "population_status": (
                        (group or {}).get("status", "") if same_tenant else ""
                    ),
                })
            return SubjectView(
                kind="entity",
                id=subject_id,
                posture=EntityPosture(entity_id=subject_id, memberships=tuple(enriched)),
                missing_reason=None,
            )

        # Any other subject kind is not this plane's.
        return SubjectView(
            kind=subject_kind,
            id=subject_id,
            posture=None,
            missing_reason=(
                f"subject kind {subject_kind!r} is not a population360 subject"
            ),
        )


# ── Pure derivation helpers ───────────────────────────────────────────────────


def _snapshot_deltas(snapshots: tuple[dict[str, Any], ...]) -> list[dict[str, Any]]:
    """member_count change between consecutive snapshots (pure)."""
    deltas: list[dict[str, Any]] = []
    previous: Optional[int] = None
    for snapshot in snapshots:
        count = int(snapshot.get("member_count") or 0)
        deltas.append({
            "snapshot_at": snapshot.get("snapshot_at"),
            "member_count": count,
            "delta": (count - previous) if previous is not None else None,
        })
        previous = count
    return deltas


def _latest_snapshot(snapshots: tuple[dict[str, Any], ...]) -> Optional[dict[str, Any]]:
    return snapshots[-1] if snapshots else None


def _confidence_band(confidence: float) -> str:
    for edge, band in CONFIDENCE_BANDS:
        if confidence <= edge:
            return band
    return "very_high"


def _composition(
    members: tuple[MembershipRow, ...], active_member_count: int
) -> dict[str, Any]:
    """Membership composition by basis / confidence band / entity type (pure).

    Distributions are computed over the *sample*; the composition block names
    both the authoritative count and how many members the distribution covers so
    a truncated sample can never be mistaken for an exact census.
    """
    by_basis: dict[str, int] = {}
    by_band: dict[str, int] = {}
    by_type: dict[str, int] = {}
    for m in members:
        by_basis[m.basis] = by_basis.get(m.basis, 0) + 1
        band = _confidence_band(m.confidence)
        by_band[band] = by_band.get(band, 0) + 1
        by_type[m.entity_type] = by_type.get(m.entity_type, 0) + 1
    return {
        "member_count": active_member_count,
        "distribution_covers": len(members),
        "by_basis": by_basis,
        "by_confidence_band": by_band,
        "by_entity_type": by_type,
    }


def _overlap_scores(posture: PopulationPosture) -> list[dict[str, Any]]:
    """Jaccard overlap of the subject population against scanned siblings (pure).

    Only computed when the subject's own active member set is fully known (the
    sample is not truncated); a truncated subject sample makes any overlap
    number unsound, so the caller surfaces that instead. A sibling whose member
    set was capped is scored over its partial set and flagged
    ``member_ids_truncated`` so the score is never mistaken for exact.
    """
    if posture.members_truncated or not posture.members_sample:
        return []
    own_ids = {m.entity_id for m in posture.members_sample}
    scores: list[dict[str, Any]] = []
    for sibling in posture.siblings:
        if not sibling.active_member_ids:
            continue
        sibling_ids = set(sibling.active_member_ids)
        intersection = len(own_ids & sibling_ids)
        if intersection == 0:
            continue
        union = len(own_ids | sibling_ids)
        scores.append({
            "population_id": sibling.population_id,
            "name": sibling.name,
            "population_type": sibling.population_type,
            "overlap_count": intersection,
            "jaccard": round(intersection / union, 4),
            "member_ids_truncated": sibling.member_ids_truncated,
        })
    return sorted(scores, key=lambda s: s["jaccard"], reverse=True)


def _population_evidence(posture: PopulationPosture) -> list[EvidenceRef]:
    """EvidenceRefs for definition versions + snapshots of one population."""
    refs: list[EvidenceRef] = []
    for version in posture.definition_transitions:
        refs.append(
            EvidenceRef(
                id=(
                    f"definition:{posture.population_id}:"
                    f"{version.get('definition_version', '')}"
                ),
                type="event",
                source="population_definition_versions",
                observedAt=version.get("created_at") or None,
            )
        )
    for snapshot in posture.snapshots:
        refs.append(
            EvidenceRef(
                id=f"snapshot:{posture.population_id}:{snapshot.get('snapshot_at', '')}",
                type="event",
                source="population_snapshots",
                observedAt=snapshot.get("snapshot_at") or None,
            )
        )
    return refs


def _membership_evidence(members: tuple[MembershipRow, ...]) -> list[EvidenceRef]:
    """One EvidenceRef per membership row (the rows behind count claims)."""
    refs: list[EvidenceRef] = []
    for m in members:
        refs.append(
            EvidenceRef(
                id=f"membership:{m.population_id}:{m.entity_id}",
                type="relationship",
                source="population_memberships",
                observedAt=m.joined_at or None,
            )
        )
    return refs


def _entity_evidence(memberships: tuple[dict[str, Any], ...]) -> list[EvidenceRef]:
    refs: list[EvidenceRef] = []
    for m in memberships:
        refs.append(
            EvidenceRef(
                id=f"membership:{m.get('population_id', '')}:{m.get('entity_id', '')}",
                type="relationship",
                source="population_memberships",
                observedAt=m.get("joined_at") or None,
            )
        )
    return refs


def _dedupe_evidence(*groups: list[EvidenceRef]) -> list[EvidenceRef]:
    seen: set[str] = set()
    refs: list[EvidenceRef] = []
    for group in groups:
        for ref in group:
            if ref.id in seen:
                continue
            seen.add(ref.id)
            refs.append(ref)
    return refs


def _worst_state(dims: list[dict[str, Any]]) -> str:
    """Most severe typed state among dimensions (available is best)."""
    return min(
        (d["state"] for d in dims),
        key=lambda s: _STATE_RANK.get(s, 100),
    )


# ── Provider ──────────────────────────────────────────────────────────────────


class Population360Provider:
    """Intelligence-projection provider for ``population360`` (read-only)."""

    projection_id = "population360"
    contract_version = INTELLIGENCE_PROJECTIONS_CONTRACT_VERSION
    graph_mutation_policy = "read_only"

    def __init__(
        self,
        reader: Optional[Population360Reader] = None,
        demographic_lens: Optional[DemographicLens] = None,
        small_cell_suppression: Optional[SmallCellSuppression] = None,
    ) -> None:
        # Injected canonical reader (test seam); default reads the population
        # registries.
        self._reader = reader if reader is not None else PopulationRepositoryReader()
        self._demographics = (
            demographic_lens if demographic_lens is not None else DemographicLens()
        )
        self._suppression = (
            small_cell_suppression
            if small_cell_suppression is not None
            else SmallCellSuppression()
        )

    # ── IntelligenceProjectionProvider ─────────────────────────────────────

    async def project(
        self,
        request: ProjectionRequest,
        context: ProjectionContext,
    ) -> ProjectionResult:
        """Run one read-only Population360 projection over canonical truth."""
        tenant_id = request.tenantId
        subject = request.subject
        surface_mode = (
            request.temporalMode
            if request.temporalMode in SUPPORTED_TEMPORAL_MODES
            else "window"
        )

        view = await self._safe_view(tenant_id, subject.kind, subject.id)
        demo = await self._demographic_dim(request, view)

        sections = [
            self._summary_section(request, view, surface_mode),
            self._state_section(request, view, demo, surface_mode),
            self._timeline_section(request, view, surface_mode),
            self._evidence_section(request, view),
            self._findings_section(request, view, demo, surface_mode),
        ]
        claims = self._build_claims(request, view)

        return ProjectionResult(
            projectionId=self.projection_id,
            tenantId=tenant_id,
            contractVersion=self.contract_version,
            sections=sections,
            claims=claims,
            dependencyState=list(context.dependencyState),
            asOf=_utc_now_iso(),
            generatedAt=_utc_now_iso(),
            degradedReasons=[],
            temporalMode=surface_mode,
            lensIds=request.lensIds,
        )

    # ── Section builders ───────────────────────────────────────────────────

    def _summary_section(
        self,
        request: ProjectionRequest,
        view: SubjectView,
        surface_mode: str,
    ) -> ProjectionSection:
        """summary — the subject's population posture under the surface mode."""
        subject = request.subject
        posture = view.posture
        warnings: list[str] = []
        if view.missing_reason:
            warnings.append(view.missing_reason)
        if isinstance(posture, PopulationPosture):
            if posture.members_truncated:
                warnings.append(
                    "composition covers a capped member sample "
                    f"(first {MEMBER_SAMPLE_CAP}); the count stays authoritative"
                )
            latest = _latest_snapshot(posture.snapshots)
            deltas = _snapshot_deltas(posture.snapshots)
            latest_delta = deltas[-1] if deltas else None
            return ProjectionSection(
                id="summary",
                state="available",  # type: ignore[arg-type]
                title="Population posture",
                content={
                    "subject": {"kind": subject.kind, "id": subject.id},
                    "population": {
                        "id": posture.population_id,
                        "name": posture.name,
                        "population_type": posture.population_type,
                        "status": posture.status,
                        "definition_version": posture.definition_version,
                    },
                    "member_count": posture.active_member_count,
                    "composition": _composition(
                        posture.members_sample, posture.active_member_count
                    ),
                    "snapshot": latest,
                    "snapshot_delta": latest_delta,
                    "definition_transition_count": len(posture.definition_transitions),
                    "effective_temporal_mode": surface_mode,
                    "freshness": {
                        "latest_snapshot_at": (latest or {}).get("snapshot_at"),
                        "population_updated_at": posture.updated_at,
                    },
                },
                warnings=warnings or None,
            )
        if isinstance(posture, EntityPosture):
            memberships = posture.memberships
            active = [m for m in memberships if _row_active(m)]
            by_type: dict[str, int] = {}
            by_state: dict[str, int] = {}
            for m in memberships:
                t = m.get("population_type", "")
                by_type[t] = by_type.get(t, 0) + 1
                s = m.get("membership_state") or m.get("status") or "active"
                by_state[s] = by_state.get(s, 0) + 1
            return ProjectionSection(
                id="summary",
                state="available" if memberships else "empty",  # type: ignore[arg-type]
                title="Population posture",
                content={
                    "subject": {"kind": subject.kind, "id": subject.id},
                    "membership_count": len(active),
                    "membership_episode_count": len(memberships),
                    "membership_state_distribution": by_state,
                    "population_type_distribution": by_type,
                    "effective_temporal_mode": surface_mode,
                },
                warnings=warnings or None,
            )
        return ProjectionSection(
            id="summary",
            state="unknown",  # type: ignore[arg-type]
            title="Population posture",
            content={
                "subject": {"kind": subject.kind, "id": subject.id},
                "member_count": None,
            },
            warnings=warnings or None,
        )

    def _state_section(
        self,
        request: ProjectionRequest,
        view: SubjectView,
        demo: Optional[dict[str, Any]],
        surface_mode: str,
    ) -> ProjectionSection:
        """state — typed per-dimension state (unknown != empty != 0 != missing)."""
        posture = view.posture
        dims: list[dict[str, Any]] = []

        if isinstance(posture, PopulationPosture):
            dims.append({"id": "population_known", "state": "available", "reason": None})
            # The count is a real read over owned rows; 0 is a genuine observation
            # once the definition is known, never a fabricated absence.
            dims.append({"id": "membership_count", "state": "available", "reason": None})
            # Snapshot history — never fabricated.
            if posture.snapshots:
                latest = posture.snapshots[-1]
                stale = _iso_aware(latest.get("snapshot_at")) < _iso_aware(
                    posture.updated_at
                )
                dims.append({
                    "id": "snapshot_history",
                    "state": "stale" if stale else "available",
                    "reason": (
                        "latest snapshot predates the population's last update; "
                        "counts may have drifted"
                        if stale
                        else None
                    ),
                })
            else:
                dims.append({
                    "id": "snapshot_history",
                    "state": "missing",
                    "reason": "no population snapshot has ever been taken",
                })
            if posture.definition_transitions:
                dims.append({
                    "id": "definition_versioning",
                    "state": "available",
                    "reason": None,
                })
            else:
                dims.append({
                    "id": "definition_versioning",
                    "state": "degraded",
                    "reason": "no immutable definition-version contract recorded",
                })
            if demo is not None:
                dims.append(demo)
        elif isinstance(posture, EntityPosture):
            memberships = posture.memberships
            active = [m for m in memberships if _row_active(m)]
            if memberships:
                dims.append({
                    "id": "membership_observation",
                    "state": "available",
                    "reason": None,
                })
                dims.append({
                    "id": "current_memberships",
                    "state": "available" if active else "empty",
                    "reason": None if active else "all recorded memberships are inactive",
                })
            else:
                dims.append({
                    "id": "membership_observation",
                    "state": "unknown",
                    "reason": "the population plane has no membership observation of this subject",
                })
        else:
            dims.append({
                "id": "subject",
                "state": "unknown",
                "reason": view.missing_reason or "no population-plane observation",
            })

        worst = _worst_state(dims)
        return ProjectionSection(
            id="state",
            state=worst,  # type: ignore[arg-type]
            title="Population state",
            content={"dimensions": dims},
            warnings=[d["reason"] for d in dims if d["reason"] is not None] or None,
        )

    def _timeline_section(
        self,
        request: ProjectionRequest,
        view: SubjectView,
        surface_mode: str,
    ) -> ProjectionSection:
        """timeline — ordered transitions, each evidence-grounded."""
        posture = view.posture
        warnings: list[str] = []
        if view.missing_reason:
            warnings.append(view.missing_reason)

        if isinstance(posture, PopulationPosture):
            events: list[dict[str, Any]] = [
                {
                    "at": posture.created_at,
                    "kind": "population_created",
                    "population_id": posture.population_id,
                    "population_type": posture.population_type,
                }
            ]
            for version in posture.definition_transitions:
                events.append({
                    "at": version.get("created_at") or "",
                    "kind": "definition_version",
                    "definition_version": version.get("definition_version"),
                    "supersedes_version": version.get("supersedes_version"),
                    "reason": version.get("reason"),
                    "created_by": version.get("created_by"),
                })
            deltas = _snapshot_deltas(posture.snapshots)
            for d in deltas:
                events.append({
                    "at": d["snapshot_at"],
                    "kind": "snapshot",
                    "member_count": d["member_count"],
                    "member_count_delta": d["delta"],
                })
            events = [e for e in events if e["at"]]  # never guess an un-timed event
            events.sort(key=lambda e: e["at"], reverse=True)
            if len(events) > TRANSITION_CAP:
                warnings.append(f"transition list capped at {TRANSITION_CAP}")
                events = events[:TRANSITION_CAP]
            if posture.members_truncated:
                warnings.append(
                    "composition below covers a capped member sample, not the "
                    "authoritative count"
                )
            return ProjectionSection(
                id="timeline",
                state="available" if events else "missing",  # type: ignore[arg-type]
                title="Population timeline",
                content={
                    "snapshot_series": deltas,
                    "count": len(events),
                    "events": events,
                },
                warnings=warnings or None,
            )

        if isinstance(posture, EntityPosture):
            events: list[dict[str, Any]] = []
            for m in posture.memberships:
                events.append({
                    "at": m.get("joined_at") or "",
                    "kind": "membership_join",
                    "population_id": m.get("population_id"),
                    "population_name": m.get("population_name", ""),
                    "population_type": m.get("population_type", ""),
                    "basis": m.get("basis"),
                    "confidence": m.get("confidence"),
                    "definition_version": m.get("definition_version", "1"),
                    "membership_state": m.get("membership_state") or m.get("status"),
                    "reason": m.get("reason"),
                })
                if m.get("left_at"):
                    events.append({
                        "at": m.get("left_at") or "",
                        "kind": "membership_leave",
                        "population_id": m.get("population_id"),
                        "population_name": m.get("population_name", ""),
                        "population_type": m.get("population_type", ""),
                        "leave_reason": m.get("leave_reason"),
                    })
            events = [e for e in events if e["at"]]
            events.sort(key=lambda e: e["at"], reverse=True)
            if len(events) > TRANSITION_CAP:
                warnings.append(f"transition list capped at {TRANSITION_CAP}")
                events = events[:TRANSITION_CAP]
            return ProjectionSection(
                id="timeline",
                state="available" if events else "empty",  # type: ignore[arg-type]
                title="Membership timeline",
                content={"count": len(events), "events": events},
                warnings=warnings or None,
            )

        return ProjectionSection(
            id="timeline",
            state="missing",  # type: ignore[arg-type]
            title="Timeline",
            content={"count": 0, "events": []},
            warnings=warnings or None,
        )

    def _evidence_section(
        self,
        request: ProjectionRequest,
        view: SubjectView,
    ) -> ProjectionSection:
        """evidence — the reused EvidenceRefs grounding timeline + findings."""
        posture = view.posture
        if isinstance(posture, PopulationPosture):
            refs = _dedupe_evidence(
                _population_evidence(posture),
                _membership_evidence(posture.members_sample),
            )
        elif isinstance(posture, EntityPosture):
            refs = _dedupe_evidence(_entity_evidence(posture.memberships))
        else:
            refs = []
        truncated = len(refs) > EVIDENCE_CAP
        if truncated:
            refs = refs[:EVIDENCE_CAP]
        return ProjectionSection(
            id="evidence",
            state="available" if refs else "empty",  # type: ignore[arg-type]
            title="Evidence",
            content={
                "count": len(refs),
                "evidence": [e.model_dump(mode="json") for e in refs],
            },
            warnings=[f"evidence list capped at {EVIDENCE_CAP}"] if truncated else None,
        )

    def _findings_section(
        self,
        request: ProjectionRequest,
        view: SubjectView,
        demo: Optional[dict[str, Any]],
        surface_mode: str,
    ) -> ProjectionSection:
        """findings — definition transitions, anomalies, overlap, staleness."""
        findings: list[dict[str, Any]] = []
        posture = view.posture

        if view.missing_reason:
            findings.append({
                "code": "subject.unknown",
                "level": "info",
                "message": view.missing_reason,
            })

        if isinstance(posture, PopulationPosture):
            if len(posture.definition_transitions) > 1:
                latest = posture.definition_transitions[-1]
                findings.append({
                    "code": "population.definition_transition",
                    "level": "info",
                    "message": (
                        f"definition advanced to v{latest.get('definition_version')} "
                        f"({latest.get('reason')})"
                    ),
                })
            if posture.active_member_count == 0 and posture.snapshots:
                findings.append({
                    "code": "population.emptied",
                    "level": "info",
                    "message": "population currently has no active members",
                })
            # Counts may have drifted since the last snapshot.
            if posture.snapshots:
                latest = posture.snapshots[-1]
                if _iso_aware(latest.get("snapshot_at")) < _iso_aware(posture.updated_at):
                    findings.append({
                        "code": "population.stale_counts",
                        "level": "warning",
                        "message": (
                            "materialised member count may have drifted since the "
                            "latest snapshot"
                        ),
                    })
            elif posture.active_member_count > 0:
                findings.append({
                    "code": "population.unsnapshotted",
                    "level": "warning",
                    "message": "members exist but no snapshot has ever been taken",
                })
            low_confidence = [m for m in posture.members_sample if m.confidence < 0.5]
            if low_confidence:
                findings.append({
                    "code": "population.low_confidence_members",
                    "level": "warning",
                    "message": (
                        f"{len(low_confidence)} sampled member(s) carry confidence "
                        "below 0.5"
                    ),
                })
            # Overlap surprises — only scored when the sample is not truncated.
            scores = _overlap_scores(posture)
            if posture.members_truncated and posture.siblings:
                findings.append({
                    "code": "population.overlap_truncated",
                    "level": "warning",
                    "message": (
                        "overlap not computed: this population's member sample was "
                        "capped"
                    ),
                })
            elif any(s["member_ids_truncated"] for s in scores):
                findings.append({
                    "code": "population.overlap_truncated",
                    "level": "warning",
                    "message": (
                        "some overlap scores were computed over a truncated sibling "
                        "member set and are partial, not exact"
                    ),
                })
            surprises = [s for s in scores if s["jaccard"] >= OVERLAP_SURPRISE_MIN]
            if surprises:
                top = surprises[0]
                findings.append({
                    "code": "population.overlap_surprise",
                    "level": "info",
                    "message": (
                        f"population overlaps {top['name']} "
                        f"({int(round(top['jaccard'] * 100))}% jaccard)"
                    ),
                })
            if posture.siblings_truncated:
                findings.append({
                    "code": "population.overlap_scan_truncated",
                    "level": "info",
                    "message": (
                        f"sibling overlap scan capped at {SIBLING_SCAN_CAP} "
                        "populations"
                    ),
                })
        elif isinstance(posture, EntityPosture):
            memberships = posture.memberships
            states = {m.get("membership_state") or m.get("status") for m in memberships}
            if len(memberships) > 1:
                findings.append({
                    "code": "entity.multi_membership",
                    "level": "info",
                    "message": (
                        f"subject belongs to {len(memberships)} population "
                        "definition(s)"
                    ),
                })
            if "left" in states or "expired" in states:
                findings.append({
                    "code": "entity.has_inactive_memberships",
                    "level": "info",
                    "message": "subject has recorded left/expired memberships",
                })
            low = [m for m in memberships if float(m.get("confidence", 0.0) or 0.0) < 0.5]
            if low:
                findings.append({
                    "code": "entity.low_confidence_membership",
                    "level": "warning",
                    "message": f"{len(low)} membership(s) carry confidence below 0.5",
                })

        # A requested-but-unavailable demographic lens is a finding, never silent.
        if demo is not None and demo["state"] not in ("available", "empty"):
            findings.append({
                "code": f"demographics.{demo['state']}",
                "level": "info" if demo["state"] == "not_applicable" else "warning",
                "message": demo["reason"] or f"demographic lens is {demo['state']}",
            })

        return ProjectionSection(
            id="findings",
            state="available",  # type: ignore[arg-type]
            title="Population findings",
            content={
                "findings": findings,
                "evidence_count": len(self._evidence_for_claims(view)),
            },
        )

    # ── Demographic lens (opt-in via lensIds) ──────────────────────────────

    async def _demographic_dim(
        self,
        request: ProjectionRequest,
        view: SubjectView,
    ) -> Optional[dict[str, Any]]:
        """Render the demographic lens dim ONLY when a caller explicitly asks.

        The lens is a governed human lens over canonical profile facts. It is
        dormant unless the request names :data:`DEMOGRAPHIC_LENS_ID` — otherwise
        every population360 projection on a human cohort would carry a
        perpetually-``missing`` dimension while ``profile360`` is ``in_flight``,
        mislabelling the whole projection as missing. When asked, the lens result
        is served as a typed state dimension (``available`` / ``missing`` /
        ``unknown`` / ``degraded`` / ``not_applicable`` / ``empty``) — it lifts
        when ``profile360`` lands.
        """
        if not request.lensIds or DEMOGRAPHIC_LENS_ID not in request.lensIds:
            return None
        posture = view.posture
        if not isinstance(posture, PopulationPosture):
            return None
        # Only a uniformly-human cohort can carry the demographic lens.
        sample_types = {m.entity_type for m in posture.members_sample}
        if sample_types and sample_types != {"user"}:
            return {
                "id": "demographics",
                "state": "not_applicable",
                "reason": (
                    "cohort members are not uniformly human; no demographic lens "
                    "applies"
                ),
            }
        member_ids = [m.entity_id for m in posture.members_sample]
        if not member_ids:
            return {
                "id": "demographics",
                "state": "empty",
                "reason": "the population has no active members to aggregate",
            }
        result = await self._demographics.lens_for_population(
            tenant_id=request.tenantId,
            subject_kind=request.subject.kind,
            entity_ids=member_ids,
            suppression=self._suppression,
        )
        reason = result.reason
        if posture.members_truncated and result.state in ("available", "unknown"):
            reason = (reason + " " if reason else "") + (
                "aggregated over a capped member sample, not the full cohort"
            )
        return {
            "id": "demographics",
            "state": result.state,
            "reason": reason,
        }

    # ── Claims ─────────────────────────────────────────────────────────────

    def _build_claims(
        self,
        request: ProjectionRequest,
        view: SubjectView,
    ) -> list[ClaimEnvelope]:
        """Evidence-grounded claims (requiresEvidence: every claim is grounded)."""
        claims: list[ClaimEnvelope] = []
        subject = request.subject  # canonical subject — never re-derived
        posture = view.posture
        refs = self._evidence_for_claims(view)

        if isinstance(posture, PopulationPosture):
            claims.append(
                ClaimEnvelope(
                    id="summary.member_count",
                    kind="population_membership",
                    subject=subject,
                    evidenceRefs=refs[:5],
                    claims=[
                        f"population {posture.name} has {posture.active_member_count} "
                        "active member(s)",
                        (
                            "membership materialised under definition "
                            f"v{posture.definition_version}"
                        ),
                        f"population type {posture.population_type}",
                    ],
                )
            )
            if len(posture.definition_transitions) > 1:
                claims.append(
                    ClaimEnvelope(
                        id="transitions.definition_history",
                        kind="population_definition",
                        subject=subject,
                        evidenceRefs=_population_evidence(posture)[:5],
                        claims=[
                            f"{len(posture.definition_transitions)} immutable "
                            "definition version(s) recorded",
                        ],
                    )
                )
        elif isinstance(posture, EntityPosture):
            active = [m for m in posture.memberships if _row_active(m)]
            claims.append(
                ClaimEnvelope(
                    id="summary.memberships",
                    kind="population_membership",
                    subject=subject,
                    evidenceRefs=refs[:5],
                    claims=[
                        f"subject belongs to {len(active)} population definition(s) "
                        "as an active member",
                        f"{len(posture.memberships)} membership episode(s) recorded",
                    ],
                )
            )
        else:
            claims.append(
                ClaimEnvelope(
                    id="summary.unknown",
                    kind="population_subject",
                    subject=subject,
                    evidenceRefs=[],
                    claims=[
                        "the population plane has no observation of this subject",
                    ],
                )
            )
        return claims

    def _evidence_for_claims(self, view: SubjectView) -> list[EvidenceRef]:
        posture = view.posture
        if isinstance(posture, PopulationPosture):
            return _dedupe_evidence(
                _population_evidence(posture),
                _membership_evidence(posture.members_sample),
            )
        if isinstance(posture, EntityPosture):
            return _dedupe_evidence(_entity_evidence(posture.memberships))
        return []

    # ── Canonical read helper (defensive) ─────────────────────────────────

    async def _safe_view(
        self,
        tenant_id: str,
        subject_kind: str,
        subject_id: str,
    ) -> SubjectView:
        """A reader failure degrades the subject view, never raises."""
        try:
            return await self._reader.view(
                tenant_id=tenant_id, subject_kind=subject_kind, subject_id=subject_id
            )
        except Exception:  # noqa: BLE001 - backing authority unavailable -> degrade
            return SubjectView(
                kind=subject_kind,
                id=subject_id,
                posture=None,
                missing_reason="the population read authority was unavailable",
            )


def register_provider(registry: ProviderRegistry) -> None:
    """Register :class:`Population360Provider` on a provider registry.

    Deliberately NOT called at import time: the global ``projection_registry``
    is only mutated by the runtime wiring layer, never by provider modules.
    """
    registry.register(Population360Provider(), source="services/population360")


__all__ = [
    "DEMOGRAPHIC_LENS_ID",
    "OUTPUT_SECTIONS",
    "Population360Provider",
    "Population360Reader",
    "PopulationRepositoryReader",
    "SUPPORTED_TEMPORAL_MODES",
    "SubjectView",
    "register_provider",
]
