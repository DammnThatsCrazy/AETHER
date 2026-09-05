"""Milestone M6 independent-evidence grouping for the M7 fidelity engine (D-04).

This module fills the documented seam the M7 relationship-fidelity engine
expects at ``services.relationship_promotion.evidence_independence``
(``shared/relationship_fidelity/evidence.py`` declares the seam as
``M6_EVIDENCE_INDEPENDENCE_MODULE`` / ``M6_RESOLVE_FACTORY`` and imports it
defensively via :func:`load_m6_independence_resolver`). The public callable is
:func:`resolve_independent_groups`; the engine calls it directly as
``candidate(relationship_ref=..., tenant_id=..., observations=...)`` and accepts
only an :class:`IndependentEvidenceAccount` return (or ``None`` => independence
UNKNOWN).

Semantics
---------
The caller (the promotion -> fidelity runtime chain, or a test) passes
observations ALREADY SCOPED to the single relationship pair identified by
``relationship_ref``. Milestone M6's authoritative grouping
(``shared/relationship_spine/evidence.py``) is endpoint-aware — it buckets by
``(predicate, source_entity_id, target_entity_id)`` — while M7 observations carry
no endpoints. Endpoint binding is therefore the CALLER's responsibility; this
module performs the grouping step M6 defines WITHIN a candidate: independent
units are independent source-lineage groups.

Grouping algorithm
------------------
1. Only observations with a usable (non-empty after ``strip()``) ``source_key``
   can establish independence. Observations with an empty/missing source identity
   are NOT attributable to an independent source: they are excluded from grouping
   (no independent unit is fabricated for them). If NO observation carries a
   usable source identity, ``None`` is returned — independence stays UNKNOWN,
   never a fabricated 0.
2. Attributable observations are grouped by distinct ``source_key`` lineage; each
   distinct source becomes one :class:`EvidenceGroup`. A group's
   ``correlation_family`` is set to the shared non-``None`` family ONLY when ALL
   of that source's members carry the same non-``None`` family; otherwise it is
   ``None``. ``group_id`` is a stable deterministic string derived from
   ``relationship_ref`` + ``source_key`` (``"<relationship_ref>::<source_key>"``).
   Groups are returned sorted by ``group_id`` for determinism.
3. ``independent_evidence_count`` / ``independent_source_count`` default from the
   produced groups (see :class:`IndependentEvidenceAccount.__post_init__`): the
   number of distinct independent source lineages that observed the relationship
   is a measurement, never a fabricated figure.
4. The account stamps ``provided_by`` with this module's exact factory path so
   engine coverage provenance is honest.

Honesty
-------
* UNKNOWN is never fabricated into a number and never read as 0. A resolver that
  cannot attribute any observation returns ``None`` (the engine degrades to
  UNKNOWN), never an empty/zero account.
* The seam is SAFE: unexpected failures inside this module are converted to
  ``None`` so a promotion-side defect can never break the fidelity path with an
  uncaught exception. Deliberate ``ValueError``/``TypeError`` inputs degrade to
  ``None`` the same way.
* This module is dependency-light and importable in isolation: importing it has
  no side effects and requires no app settings, database, or runtime wiring.
"""

from __future__ import annotations

from typing import Optional, Sequence

from shared.relationship_fidelity.evidence import (
    EvidenceGroup,
    IndependentEvidenceAccount,
    Observation,
)

# The producer string stamped onto every account this module returns. It matches
# the documented M6 seam factory path verbatim; engine coverage
# (``services/relationship_fidelity/engine.py`` ``_build_coverage``) surfaces it
# as ``coverage.independent_account`` so provenance is honest.
PROVIDED_BY: str = (
    "services.relationship_promotion.evidence_independence::resolve_independent_groups"
)


def _usable_source_key(observation: Observation) -> str:
    """Return the trimmed source identity, or ``""`` when it is unusable."""
    return (observation.source_key or "").strip()


def _group_correlation_family(members: Sequence[Observation]) -> Optional[str]:
    """Correlation family shared by ALL members, else ``None``.

    A group carries a family only when every one of its members labels the same
    non-``None`` ``correlation_family``. Any member without that label (``None``
    or a different family) makes the group's family unshared => ``None``.
    """
    distinct = {o.correlation_family for o in members if o.correlation_family is not None}
    if len(distinct) != 1:
        return None
    family = next(iter(distinct))
    if not all(o.correlation_family is not None for o in members):
        return None
    return family


def resolve_independent_groups(
    *,
    relationship_ref: str,
    tenant_id: str,
    observations: Sequence[Observation],
) -> Optional[IndependentEvidenceAccount]:
    """Group raw observations into independent source-lineage evidence units.

    Observations are treated as already scoped to the single relationship pair
    identified by ``relationship_ref`` (the caller owns endpoint binding). Each
    distinct usable ``source_key`` becomes one independent :class:`EvidenceGroup`
    (M6's within-candidate grouping); observations with no usable source identity
    are excluded and never given a fabricated independent unit.

    Returns an :class:`IndependentEvidenceAccount` when at least one observation
    is attributable to an independent source lineage, else ``None`` (independence
    UNKNOWN — never a fabricated 0). The engine degrades ``None`` to UNKNOWN and
    logs; this resolver never raises through the seam.

    Args:
        relationship_ref: The relationship-pair reference the observations are
            scoped to (used only for deterministic ``group_id`` derivation).
        tenant_id: The tenant namespace (accepted for interface symmetry; the
            caller has already scoped observations, so grouping does not branch
            on tenant).
        observations: Raw fidelity observations for the single relationship pair.
    """
    try:
        attributable: dict[str, list[Observation]] = {}
        for observation in observations:
            source_key = _usable_source_key(observation)
            if not source_key:
                # Not attributable to an independent source lineage. Exclude —
                # never fabricate an independent unit for un-attributable evidence.
                continue
            attributable.setdefault(source_key, []).append(observation)

        if not attributable:
            # No usable source identity anywhere => independence genuinely cannot
            # be determined (UNKNOWN, never an empty/zero account).
            return None

        groups: list[EvidenceGroup] = []
        for source_key in sorted(attributable):
            members = sorted(attributable[source_key], key=lambda o: o.observation_id)
            groups.append(
                EvidenceGroup(
                    group_id=f"{relationship_ref}::{source_key}",
                    observation_ids=tuple(o.observation_id for o in members),
                    source_key=source_key,
                    correlation_family=_group_correlation_family(members),
                )
            )
        groups.sort(key=lambda g: g.group_id)
        return IndependentEvidenceAccount(
            groups=tuple(groups),
            provided_by=PROVIDED_BY,
        )
    except Exception:
        # The seam is safe: any unexpected failure degrades to UNKNOWN (None)
        # rather than propagating into the fidelity engine. This deliberately
        # includes ValueError/TypeError raised for malformed inputs.
        return None


__all__ = [
    "PROVIDED_BY",
    "resolve_independent_groups",
]
