"""Lens composition conflicts (A8 projection engine).

A composition conflict is a typed statement about WHY two lenses (or a lens
and the requested projection) cannot compose cleanly. Every conflict class
carries a resolution policy — the composition algebra is deterministic: a
conflict never silently mutates a result, it either suppresses the affected
section, rejects at compile time, lets a dominant lens win, or degrades.

Conflicts are engine-computed (never provider-controlled), so their reasons are
safe to surface. Provider diagnostics never reach here.
"""

from __future__ import annotations

import enum
from typing import Optional

from shared.intelligence_projections.errors import ProjectionError


class ConflictClass(enum.Enum):
    """The type of a lens-composition conflict."""

    HARD_CONFLICT = "hard_conflict"  # contradictory lenses — suppress the section
    SOFT_CONFLICT = "soft_conflict"  # lenses disagree on presentation — dominant wins
    PARAMETER_CONFLICT = "parameter_conflict"  # illegal combination — reject at compile
    TEMPORAL_CONFLICT = "temporal_conflict"  # a lens cannot honor the requested temporal mode
    POLICY_CONFLICT = "policy_conflict"  # governance forbids rendering under this lens set
    GRAIN_CONFLICT = "grain_conflict"  # disparate aggregation grains — coarsest wins
    CAPABILITY_MISSING = "capability_missing"  # the lens cannot apply to the subject/kind


class ConflictResolution(enum.Enum):
    """The deterministic resolution policy for a conflict class."""

    SUPPRESS_SECTION = "suppress_section"  # drop the affected section from the result
    REJECT_AT_COMPILE = "reject_at_compile"  # raise before any provider runs
    DOMINANT_WINS = "dominant_wins"  # the dominant lens's view wins; others suppressed
    COARSEST_WINS = "coarsest_wins"  # keep the coarsest grain, drop finer grains
    DEGRADE = "degrade"  # drop the offending lens, degrade the affected section


RESOLUTION_BY_CLASS: dict[ConflictClass, ConflictResolution] = {
    ConflictClass.HARD_CONFLICT: ConflictResolution.SUPPRESS_SECTION,
    ConflictClass.SOFT_CONFLICT: ConflictResolution.DOMINANT_WINS,
    ConflictClass.PARAMETER_CONFLICT: ConflictResolution.REJECT_AT_COMPILE,
    ConflictClass.TEMPORAL_CONFLICT: ConflictResolution.DEGRADE,
    ConflictClass.POLICY_CONFLICT: ConflictResolution.SUPPRESS_SECTION,
    ConflictClass.GRAIN_CONFLICT: ConflictResolution.COARSEST_WINS,
    ConflictClass.CAPABILITY_MISSING: ConflictResolution.DEGRADE,
}


class LensConflict(ProjectionError):
    """A lens-composition conflict raised (or recorded) by the composition
    algebra.

    ``conflict_class`` names the :class:`ConflictClass`; ``resolution`` is its
    deterministic policy. The projection-id context is optional — a conflict
    may be detected before a projection id is chosen.
    """

    def __init__(
        self,
        message: str,
        conflict_class: ConflictClass,
        *,
        lens_id: Optional[str] = None,
        projection_id: Optional[str] = None,
    ) -> None:
        super().__init__(
            message,
            projection_id=projection_id,
            context={"conflict_class": conflict_class.value},
        )
        self.conflict_class = conflict_class
        self.resolution = RESOLUTION_BY_CLASS[conflict_class]
        self.lens_id = lens_id


class LensNotFound(LensConflict):
    """A lens id does not resolve in the lens registry."""

    def __init__(self, lens_id: str, *, projection_id: Optional[str] = None) -> None:
        super().__init__(
            f"no lens {lens_id!r} in the lens registry",
            ConflictClass.PARAMETER_CONFLICT,
            lens_id=lens_id,
            projection_id=projection_id,
        )


__all__ = [
    "ConflictClass",
    "ConflictResolution",
    "LensConflict",
    "LensNotFound",
    "RESOLUTION_BY_CLASS",
]
