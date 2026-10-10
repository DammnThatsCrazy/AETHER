"""Engine-level temporal modes (A8 projection engine).

The engine reasons about time with a RICHER mode vocabulary than the four
registry surface modes (``window`` / ``as_of`` / ``compare`` / ``relative``).
Each engine :class:`TemporalMode` dispatches onto exactly one registry surface
mode via :func:`dispatch_temporal_mode` — the richer mode NEVER leaks onto the
wire contract (``ProjectionRequest.temporalMode`` carries a registry surface
mode), so the engine can add modes without widening the registry vocab or
breaking the cross-registry validator.
"""

from __future__ import annotations

import enum
from typing import Optional


class TemporalMode(enum.Enum):
    """How the engine interprets time for a projection run.

    * ``LIVE`` — the live, current-state view (surface mode ``window``).
    * ``AS_OF`` — a single point-in-time snapshot (surface mode ``as_of``).
    * ``KNOWN_THEN`` — what was known at the time (as-of with knowledge-state
      semantics; still a point-in-time snapshot).
    * ``KNOWN_NOW`` — the present knowledge applied to a past point
      (as-of with look-back semantics).
    * ``COMPARE`` — two windows compared (surface mode ``compare``).
    * ``CORRECTION_DIFF`` — what changed between two snapshots (a compare).
    * ``PLAYBACK`` — a relative window replayed forward (surface mode
      ``relative``).
    * ``SIMULATION`` — a hypothetical / modeled window (surface mode
      ``relative``; never presents modeled state as observed truth).
    """

    LIVE = "live"
    AS_OF = "as_of"
    KNOWN_THEN = "known_then"
    KNOWN_NOW = "known_now"
    COMPARE = "compare"
    CORRECTION_DIFF = "correction_diff"
    PLAYBACK = "playback"
    SIMULATION = "simulation"


# Engine mode -> registry-surface temporal mode. The surface vocabulary is the
# projection registry's ``temporalModes`` (window / as_of / compare / relative).
_ENGINE_TO_SURFACE: dict[TemporalMode, str] = {
    TemporalMode.LIVE: "window",
    TemporalMode.AS_OF: "as_of",
    TemporalMode.KNOWN_THEN: "as_of",
    TemporalMode.KNOWN_NOW: "as_of",
    TemporalMode.COMPARE: "compare",
    TemporalMode.CORRECTION_DIFF: "compare",
    TemporalMode.PLAYBACK: "relative",
    TemporalMode.SIMULATION: "relative",
}

_REGISTRY_SURFACE_MODES = frozenset({"window", "as_of", "compare", "relative"})

_SIMULATION_OR_PLAYBACK = frozenset({TemporalMode.PLAYBACK, TemporalMode.SIMULATION})


def dispatch_temporal_mode(mode: TemporalMode) -> str:
    """The registry-surface temporal mode an engine mode dispatches onto."""
    return _ENGINE_TO_SURFACE[mode]


def parse_temporal_mode(value: Optional[str]) -> Optional[TemporalMode]:
    """Parse a string into a :class:`TemporalMode` (``None`` when absent)."""
    if value is None:
        return None
    try:
        return TemporalMode(value)
    except ValueError:
        return None


def supported_surface_mode(mode: TemporalMode, lens_temporal_modes: list[str]) -> bool:
    """Whether a lens (declaring ``temporal_modes``) supports an engine mode.

    A lens supports a mode when it declares the dispatched surface mode. When
    the lens declares no temporal modes, it is presumed to support any mode
    (an empty declaration means "unconstrained", not "supports nothing").
    """
    if not lens_temporal_modes:
        return True
    return dispatch_temporal_mode(mode) in set(lens_temporal_modes)


def is_simulation_or_playback(mode: Optional[TemporalMode]) -> bool:
    """True for PLAYBACK / SIMULATION — never presented as observed truth."""
    return mode in _SIMULATION_OR_PLAYBACK


__all__ = [
    "TemporalMode",
    "dispatch_temporal_mode",
    "is_simulation_or_playback",
    "parse_temporal_mode",
    "supported_surface_mode",
]
