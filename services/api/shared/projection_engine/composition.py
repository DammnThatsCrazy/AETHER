"""Cross-360 composition (A8 projection engine, slice S6).

A 360 is an intelligence projection over canonical Aether truth — never a
competing system of record (ADR-010). :mod:`composition` layers that doctrine
onto MULTI-360 orchestration: running two, three, or (for the context family)
all three context leaves over the SAME tenant-scoped subject and returning a
deterministic composite (:class:`CompositionResult`) while every member
projection stays fail-isolated.

The five public entry points:

* :func:`compose_economic_outcome` — economic360 + outcome360 (value view).
* :func:`compose_outcome_infrastructure` — outcome360 + infrastructure360
  (condition → outcome seam).
* :func:`compose_economic_infrastructure` — economic360 + infrastructure360
  (condition → economic effect seam).
* :func:`compose_operational_value_triangle` — the operational-value triangle:
  infrastructure condition -> outcome -> economic effect, running all three.
* :func:`compose_context_triad` — the context-360 WHERE × WHEN × WHO triad
  (geographic360 + temporal360 + population360): the Context Intelligence 360
  family rule is that spatiotemporal analysis is *composition of the three
  projections, never a fourth backend* — this entry point is that composition.

Composition laws
----------------

Each member projection is named by the registry 360 id it serves and mapped to
its real engine overlay lens (``economic`` / ``outcome`` / ``infrastructure``
for the operational-value family; ``temporal`` / ``geographic`` / ``population``
for the context family, where ``population360`` is the WHO/cohort leaf and
geographic is the WHERE leaf — all defined in ``generated_lenses.py``, never
hardcoded ids outside that generated vocabulary). The composition forms one
:class:`LensSet` whose base is the engine default (``standard``) and whose
overlays are the member lenses, then composes it over the subject kind with
``compose_lenses``:

* **Identity / idempotence / order stability** come from the shared algebra —
  the same member set always yields the same ordered lens frame regardless of
  request order.
* **Capability** — a member lens that cannot apply to the subject kind (its
  ``applicableSubjectKinds`` excludes it) is dropped by the algebra as a
  ``CAPABILITY_MISSING`` :class:`~shared.projection_engine.conflict.IncompatibleLens`.
  That member does NOT run: it is recorded as a typed :class:`CompositionConflict`
  (content-free reason) and the surviving members still compose.
* A member whose overlay composes but whose provider is absent degrades with a
  content-free ``CAPABILITY_MISSING`` reason (the executor's fail-closed
  fully-degraded result) — never an exception.

Members run through a :class:`ProjectionExecutor` (callers inject their own —
e.g. over a fresh ``ProviderRegistry`` of stubs — by passing ``executor=``);
each run inherits the engine's fail-isolation, so a raising provider degrades
its member rather than the whole composition. Provider diagnostics never reach
the composition's reasons — only engine-computed, content-free text.

Result shape
------------

:class:`CompositionResult` is a plain dataclass (NOT a ``ProjectionResult`` — a
composed 360 has no single registry ``projectionId`` and therefore no
``ProjectionResult`` home). It carries:

* ``members`` — the requested member projection ids, deterministic (sorted).
* ``composed_lens_ids`` — the lens frame that survived composition.
* ``sections`` — the flattened top-level view: ONE section per distinct section
  id across the member results (the UNION of member section vocabularies, no
  duplicates). outcome360 / economic360 both render the five-slot measurement
  vocabulary and infrastructure360 renders ``deployments`` in place of
  ``outcomes``; when two members render the same id, the first member in member
  order wins at the top level and the overlap is otherwise preserved in
  ``member_results`` (nothing is silently dropped).
* ``claims`` — the deduplicated union of member claims.
* ``member_results`` — every requested member's FULL result, keyed by id, so
  per-member depth is never lost.
* ``degraded_members`` — the members that could not participate.
* ``conflicts`` — typed :class:`CompositionConflict` entries (member + conflict
  class + content-free reason).
* ``degradation`` — the engine :class:`ProjectionDegradation` summary (``none``
  when every member composed cleanly, ``partial`` when some member degraded,
  ``full`` when no member produced sections).
* ``digest`` — a deterministic sha256 over the composed content (stable across
  identical runs).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from shared.intelligence_projections.contracts import (
    ClaimEnvelope,
    ProjectionDegradation,
    ProjectionRequest,
    ProjectionResult,
    ProjectionSection,
    ProjectionSubject,
)
from shared.intelligence_projections.generated_registry import (
    INTELLIGENCE_PROJECTIONS_CONTRACT_VERSION,
)
from shared.projection_engine.conflict import (
    ConflictClass,
    LensConflict,
    LensNotFound,
)
from shared.projection_engine.degradation import summarize_degradation
from shared.projection_engine.digest import canonical_json
from shared.projection_engine.executor import ProjectionExecutor
from shared.projection_engine.lens_composition import (
    Composition,
    IncompatibleLens,
    compose_lenses,
)
from shared.projection_engine.lens_registry import lens_registry
from shared.projection_engine.lens_set import LensSet
from shared.projection_engine.temporal_modes import TemporalMode

# ── Member registry ids → engine overlay lens ids ────────────────────────────
# The overlay ids are real generated lenses (``generated_lenses.py``); the
# registry base lens every overlay declares is ``standard``.
_MEMBER_OVERLAY_LENS: dict[str, str] = {
    "economic360": "economic",
    "infrastructure360": "infrastructure",
    "outcome360": "outcome",
    # The context-360 family: WHERE × WHEN × WHO. All three overlay lenses
    # already exist; composition never builds a fourth (spatiotemporal) 360.
    "geographic360": "geographic",
    "population360": "population",
    "temporal360": "temporal",
}

_MEMBERS = (
    "economic360",
    "infrastructure360",
    "outcome360",
)

# The context-360 leaves. The three overlay lenses intersect on the ``entity``
# subject kind (temporal: campaign/entity/episode/relationship/source;
# geographic: entity/population/source; population: cluster/entity/population),
# so an entity subject composes all three; for other kinds the inapplicable
# members drop as typed CAPABILITY_MISSING conflicts.
_CONTEXT_MEMBERS = (
    "geographic360",
    "population360",
    "temporal360",
)

_BASE_LENS = "standard"


@dataclass(frozen=True)
class CompositionContext:
    """The tenant-scoped basis a composition runs its member projections on.

    ``subject`` is the single subject every member 360 is asked about (a 360 is
    an intelligence projection over canonical truth — the members never see a
    different subject or tenant). ``temporal_mode`` is an engine
    :class:`~shared.projection_engine.temporal_modes.TemporalMode`; ``None``
    means the live view.
    """

    tenant_id: str
    subject: ProjectionSubject
    include_sections: Optional[list[str]] = None
    include_claims: bool = False
    temporal_mode: Optional[TemporalMode] = None


@dataclass(frozen=True)
class CompositionConflict:
    """One typed, content-free reason a member could not compose.

    ``conflict_class`` is the engine :class:`ConflictClass` (``CAPABILITY_MISSING``
    when a member provider is absent or a member lens cannot apply to the
    subject kind; the algebra never fabricates HARD_CONFLICT for a recoverable
    capability drop). ``reason`` is engine-computed and never echoes a provider
    diagnostic.
    """

    member: str
    conflict_class: ConflictClass
    reason: str


@dataclass(frozen=True)
class CompositionResult:
    """The composite of N member 360s over one tenant-scoped subject.

    ``sections`` is the flattened union view (one section per distinct id); the
    full per-member output lives in ``member_results`` so a composed 360 is one
    projection over the subject, never N stacked results, while no member
    content is lost.
    """

    members: tuple[str, ...]
    tenant_id: str
    subject: ProjectionSubject
    composed_lens_ids: tuple[str, ...]
    sections: list[ProjectionSection]
    claims: list[ClaimEnvelope]
    member_results: dict[str, ProjectionResult] = field(default_factory=dict)
    degradation: Optional[ProjectionDegradation] = None
    conflicts: tuple[CompositionConflict, ...] = ()
    degraded_members: tuple[str, ...] = ()
    digest: Optional[str] = None


# Module-level default executor over the shared ``projection_registry``; tests
# inject a fresh-executor-on-a-fresh-registry through the ``executor=`` keyword.
_default_executor = ProjectionExecutor()


# ── Public compositions ───────────────────────────────────────────────────────


async def compose_economic_outcome(
    context: CompositionContext,
    *,
    executor: Optional[ProjectionExecutor] = None,
) -> CompositionResult:
    """Compose economic360 + outcome360 over ``context``'s subject."""
    return await _compose(("economic360", "outcome360"), context, executor=executor)


async def compose_outcome_infrastructure(
    context: CompositionContext,
    *,
    executor: Optional[ProjectionExecutor] = None,
) -> CompositionResult:
    """Compose outcome360 + infrastructure360 over ``context``'s subject."""
    return await _compose(("infrastructure360", "outcome360"), context, executor=executor)


async def compose_economic_infrastructure(
    context: CompositionContext,
    *,
    executor: Optional[ProjectionExecutor] = None,
) -> CompositionResult:
    """Compose economic360 + infrastructure360 over ``context``'s subject."""
    return await _compose(("economic360", "infrastructure360"), context, executor=executor)


async def compose_operational_value_triangle(
    context: CompositionContext,
    *,
    executor: Optional[ProjectionExecutor] = None,
) -> CompositionResult:
    """Run the operational-value triangle — all three 360 members.

    Infrastructure condition -> outcome -> economic effect: the three members
    run over the same subject and compose into one result. Members whose lens
    cannot apply to the subject kind (or whose provider is absent) degrade
    independently; the survivors still compose.
    """
    return await _compose(_MEMBERS, context, executor=executor)


async def compose_context_triad(
    context: CompositionContext,
    *,
    executor: Optional[ProjectionExecutor] = None,
) -> CompositionResult:
    """Compose the context-360 triad — geographic360 × temporal360 × population360.

    The Context Intelligence 360 family rule: spatiotemporal analysis is
    composition of the three projections, never a fourth backend. The three
    context leaves run over the same tenant-scoped subject and compose into one
    result. The context overlays intersect on ``entity`` subject kinds, so an
    entity subject composes all three; a population/source/cluster subject drops
    whichever member lens cannot apply as a typed CAPABILITY_MISSING conflict —
    the survivors still compose, and no member content is silently lost.
    """
    return await _compose(_CONTEXT_MEMBERS, context, executor=executor)


# ── Composition engine ────────────────────────────────────────────────────────


async def _compose(
    members: tuple[str, ...],
    context: CompositionContext,
    *,
    executor: Optional[ProjectionExecutor] = None,
) -> CompositionResult:
    """Run the composition for ``members`` (sorted, deterministic)."""
    ordered_members = tuple(sorted(members))
    executor_ = executor or _default_executor
    mode = context.temporal_mode or TemporalMode.LIVE

    lens_set = LensSet(
        base_lens=_BASE_LENS,
        overlays=tuple(_MEMBER_OVERLAY_LENS[m] for m in ordered_members),
    )
    # An ILLEGAL frame is a request bug — but a composition must never crash the
    # plane, so it degrades to a typed full degradation instead of raising.
    try:
        composition = compose_lenses(
            lens_set,
            subject_kind=context.subject.kind,
            registry=lens_registry,
        )
    except (LensConflict, LensNotFound) as exc:
        return _completely_degraded(ordered_members, context, exc)

    member_by_overlay = {lens: member for member, lens in _MEMBER_OVERLAY_LENS.items()}
    frame_set = LensSet(
        base_lens=composition.ordered_lens_ids[0],
        overlays=composition.ordered_lens_ids[1:],
    )

    conflicts: list[CompositionConflict] = []
    degraded_members: list[str] = []
    member_results: dict[str, ProjectionResult] = {}

    for incompatible in composition.incompatible:
        member = member_by_overlay.get(incompatible.lens_id)
        if member is None:
            continue
        degraded_members.append(member)
        conflicts.append(
            CompositionConflict(
                member=member,
                conflict_class=incompatible.conflict_class,
                reason=incompatible.reason,
            )
        )

    for member in ordered_members:
        if member in degraded_members:
            # Never run a member whose lens cannot apply to the subject kind.
            member_results[member] = _degraded_member_result(
                member,
                context,
                reason=_reason_for(conflicts, member),
            )
            continue
        result = await _run_member(member, context, frame_set, mode, executor_)
        member_results[member] = result
        if len(result.sections) == 0:
            # No sections → the member did not participate (absent provider or a
            # provider failure). Content-free, engine-computed reasons only.
            degraded_members.append(member)
            conflicts.append(
                CompositionConflict(
                    member=member,
                    conflict_class=ConflictClass.CAPABILITY_MISSING,
                    reason=_member_unavailable_reason(member, result),
                )
            )

    sections = _flatten_sections(ordered_members, member_results)
    claims = _flatten_claims(ordered_members, member_results)

    reasons = [c.reason for c in conflicts]
    degradation = summarize_degradation(
        reasons=reasons,
        conflicted_lenses=([inc.lens_id for inc in composition.incompatible] or None),
        degraded_count=len(degraded_members),
        total_sections=len(sections),
    )

    return CompositionResult(
        members=ordered_members,
        tenant_id=context.tenant_id,
        subject=context.subject,
        composed_lens_ids=composition.ordered_lens_ids,
        sections=sections,
        claims=claims,
        member_results=member_results,
        degradation=degradation,
        conflicts=tuple(conflicts),
        degraded_members=tuple(degraded_members),
        digest=_compose_digest(ordered_members, context, composition, sections, claims),
    )


async def _run_member(
    member: str,
    context: CompositionContext,
    lens_set: LensSet,
    mode: TemporalMode,
    executor: ProjectionExecutor,
) -> ProjectionResult:
    """Run one member through the executor, fail-isolated."""
    request = ProjectionRequest(
        projectionId=member,
        tenantId=context.tenant_id,
        subject=context.subject,
        includeSections=list(context.include_sections) if context.include_sections else None,
        includeClaims=context.include_claims or None,
    )
    try:
        return await executor.execute(
            request,
            lens_set=lens_set,
            temporal_mode=mode,
        )
    except Exception:  # noqa: BLE001 - one member must never crash the composition
        return _degraded_member_result(
            member,
            context,
            reason=f"member projection {member!r} failed",
        )


# ── Merging ───────────────────────────────────────────────────────────────────


def _flatten_sections(
    members: tuple[str, ...],
    results: dict[str, ProjectionResult],
) -> list[ProjectionSection]:
    """The deterministic top-level UNION of member sections (no duplicate ids).

    Members render in ``members`` order; the first render of a section id wins
    at the top level. Every member's own render stays available under
    ``member_results``.
    """
    seen: set[str] = set()
    flattened: list[ProjectionSection] = []
    for member in members:
        result = results.get(member)
        if result is None:
            continue
        for section in result.sections:
            if section.id in seen:
                continue
            seen.add(section.id)
            flattened.append(section)
    return flattened


def _flatten_claims(
    members: tuple[str, ...],
    results: dict[str, ProjectionResult],
) -> list[ClaimEnvelope]:
    """The deduplicated union of member claims (order-stable)."""
    seen: set[str] = set()
    flattened: list[ClaimEnvelope] = []
    for member in members:
        result = results.get(member)
        if result is None:
            continue
        for claim in result.claims:
            if claim.id in seen:
                continue
            seen.add(claim.id)
            flattened.append(claim)
    return flattened


# ── Degraded-member results ───────────────────────────────────────────────────


def _degraded_member_result(
    member: str,
    context: CompositionContext,
    *,
    reason: str,
) -> ProjectionResult:
    """A valid, content-free fully-degraded member result (no sections)."""
    degradation = summarize_degradation(
        reasons=[reason],
        total_sections=0,
    )
    return ProjectionResult(
        projectionId=member,
        tenantId=context.tenant_id,
        contractVersion=INTELLIGENCE_PROJECTIONS_CONTRACT_VERSION,
        sections=[],
        claims=[],
        dependencyState=[],
        generatedAt=datetime.now(timezone.utc).isoformat(),
        degradedReasons=[reason],
        degradation=degradation,
    )


def _member_unavailable_reason(member: str, result: ProjectionResult) -> str:
    """A content-free reason a member run produced no sections."""
    for reason in result.degradedReasons:
        if "no provider registered" in reason:
            return f"no provider registered for member projection {member!r}"
        # The executor's degraded reasons are content-free (exception class name
        # or the generic provider-failure marker) — safe to pass through.
        return f"member projection {member!r} degraded: {reason}"
    return f"member projection {member!r} produced no sections"


def _reason_for(conflicts: list[CompositionConflict], member: str) -> str:
    for conflict in conflicts:
        if conflict.member == member:
            return conflict.reason
    return f"member projection {member!r} not composed"


# ── Fully-degraded composition (illegal lens frame) ───────────────────────────


def _completely_degraded(
    members: tuple[str, ...],
    context: CompositionContext,
    exc: Exception,
) -> CompositionResult:
    """An ILLEGAL lens frame degrades the whole composition (never raises)."""
    conflict_class = (
        exc.conflict_class if isinstance(exc, LensConflict) else ConflictClass.PARAMETER_CONFLICT
    )
    reason = f"composition lens frame is invalid: {conflict_class.value}"
    conflict = CompositionConflict(
        member=members[0],
        conflict_class=conflict_class,
        reason=reason,
    )
    degradation = summarize_degradation(
        reasons=[reason],
        conflicted_lenses=None,
        degraded_count=len(members),
        total_sections=0,
    )
    member_results = {
        member: _degraded_member_result(member, context, reason=reason)
        for member in members
    }
    return CompositionResult(
        members=members,
        tenant_id=context.tenant_id,
        subject=context.subject,
        composed_lens_ids=(_BASE_LENS,),
        sections=[],
        claims=[],
        member_results=member_results,
        degradation=degradation,
        conflicts=(conflict,),
        degraded_members=members,
        digest=None,
    )


# ── Deterministic composition digest ──────────────────────────────────────────


def _compose_digest(
    members: tuple[str, ...],
    context: CompositionContext,
    composition: Composition,
    sections: list[ProjectionSection],
    claims: list[ClaimEnvelope],
) -> str:
    """A deterministic sha256 over the composed content (stable across reruns)."""
    payload = {
        "members": list(members),
        "tenantId": context.tenant_id,
        "subject": {"kind": context.subject.kind, "id": context.subject.id},
        "lensIds": list(composition.ordered_lens_ids),
        "sections": [s.model_dump(exclude_none=True) for s in sections],
        "claims": [c.model_dump(exclude_none=True) for c in claims],
    }
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


__all__ = [
    "CompositionConflict",
    "CompositionContext",
    "CompositionResult",
    "compose_context_triad",
    "compose_economic_infrastructure",
    "compose_economic_outcome",
    "compose_operational_value_triangle",
    "compose_outcome_infrastructure",
]
