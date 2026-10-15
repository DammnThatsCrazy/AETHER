"""Typed degradation (A8 projection engine).

The engine degrades a result with a level (``none`` / ``partial`` / ``full``)
and content-free reasons, and maps every engine degradation onto a registered
``SectionState`` from the projection registry's vocab (never a parallel
vocabulary — enforced by the ``degradation_vocab`` validator rule).

``SectionState`` values here are the registered states (``available`` /
``empty`` / ``missing`` / ``degraded`` / ``not_applicable`` / ``unknown`` /
``suppressed`` / ``stale``); the mapping below is the engine's single point of
truth for "what a degraded section may say".
"""

from __future__ import annotations

import enum
from typing import Optional

from shared.intelligence_projections.contracts import ProjectionDegradation


class DegradationLevel(enum.Enum):
    """Overall result degradation level."""

    NONE = "none"  # every requested section available
    PARTIAL = "partial"  # some sections suppressed / degraded / missing
    FULL = "full"  # the projection could not be satisfied


# Engine degradation -> registered SectionState vocab.
# (``suppressed`` and ``stale`` are A8 additions to the registry sectionStates.)
_DEGRADED_SECTION_STATE = "degraded"
_SUPPRESSED_SECTION_STATE = "suppressed"
_STALE_SECTION_STATE = "stale"


def degraded_section_state() -> str:
    return _DEGRADED_SECTION_STATE


def suppressed_section_state() -> str:
    return _SUPPRESSED_SECTION_STATE


def stale_section_state() -> str:
    return _STALE_SECTION_STATE


def summarize_degradation(
    *,
    reasons: list[str],
    conflicted_lenses: Optional[list[str]] = None,
    missing_dependencies: Optional[list[str]] = None,
    suppressed_count: int = 0,
    degraded_count: int = 0,
    total_sections: int = 0,
) -> ProjectionDegradation:
    """Build the engine-level :class:`ProjectionDegradation` for a result.

    The level is derived from the section outcome: zero unsatisfied sections
    and no failure signal (reasons / conflicted lenses / missing dependencies)
    is ``none``; the target projection itself failed — no sections were
    produced, or every section is suppressed/degraded — is ``full``; otherwise
    ``partial``. Reasons are engine-computed and never echo a provider
    diagnostic.
    """
    unsatisfied = suppressed_count + degraded_count
    has_signal = (
        bool(reasons)
        or bool(conflicted_lenses)
        or bool(missing_dependencies)
        or unsatisfied > 0
    )
    if not has_signal:
        level = DegradationLevel.NONE
    elif total_sections == 0 or (total_sections and unsatisfied >= total_sections):
        level = DegradationLevel.FULL
    else:
        level = DegradationLevel.PARTIAL
    return ProjectionDegradation(
        level=level.value,
        reasons=reasons,
        conflictedLenses=conflicted_lenses,
        missingDependencies=missing_dependencies,
    )


__all__ = [
    "DegradationLevel",
    "degraded_section_state",
    "stale_section_state",
    "summarize_degradation",
    "suppressed_section_state",
]
