"""Presentation-only readiness mapping for the intelligence projection plane (P0.7).

``implementationState`` in the projection registry
(``packages/shared/contracts/intelligence-projection-registry.json``) is REPO
METADATA describing how far a projection has been converged onto the projection
plane — it is NOT readiness. This module exposes the plane's hand-written,
PRESENTATION-ONLY vocabulary: a total mapping from the four registry
implementation states onto display tokens a UI may render.

The mapping is hand-written (never generated), mirroring the repo's hand-bound
``packages/shared/contracts/readiness-vocabulary.json`` pattern. It satisfies
the readiness doctrine:

* ``presentationIsNotCertification`` — tokens here are a separate presentation
  spelling layer (the vocabulary spells ``live`` for the certification token
  ``partner_live``); they never enter the certification ladder, carry no rank,
  and are never written into a certification record or an evidence manifest.
* ``productionReadyNeverInferred`` — ``production_ready`` is a claim DIMENSION
  on the certification plane's ``ReadinessDimensions``, never a state. This
  module structurally cannot emit it (asserted at import time, and the token
  set is closed and documented).

The tokens are projection-convergence tokens, not capability-health tokens:
``queued`` (registered on the plane, convergence not started — the tetris
queued piece), ``converging`` (existing work being converged — the honest state
of every in-flight projection today), ``converged`` (fully on the plane),
``retired`` (deprecated / pulled from the plane). ``implemented`` is
deliberately NOT used as a presentation spelling because it is an *alias* of
the certification token ``credential_waiting`` — reusing it would blur the
presentation/certification boundary the readiness vocabulary draws.

The vocabulary is provably DISJOINT from the certification plane's
``CredentialReadiness`` enum — proven by tests, NOT by a runtime import: this
module is self-contained and never imports the certification plane (a runtime
dependency in either direction would couple the two planes).
"""

from __future__ import annotations

from typing import Final, Mapping

from shared.intelligence_projections.errors import ProjectionError
from shared.intelligence_projections.generated_registry import (
    PROJECTION_IMPLEMENTATION_STATES,
)

# Hand-written, presentation-only vocabulary for projection convergence status.
# Keyed by the registry's implementation states (registered | in_flight |
# implemented | deprecated); values are the closed presentation-token set.
IMPLEMENTATION_STATE_PRESENTATION: Final[Mapping[str, str]] = {
    "registered": "queued",
    "in_flight": "converging",
    "implemented": "converged",
    "deprecated": "retired",
}

# The closed set of presentation tokens this plane may emit. Every value above
# is a member; nothing else is ever produced by :func:`presentation_token`.
PRESENTATION_TOKENS: Final[frozenset[str]] = frozenset(
    IMPLEMENTATION_STATE_PRESENTATION.values()
)

# The claim dimension that must never appear as a state token (readiness
# doctrine: production_ready is never inferred and never a state).
_FORBIDDEN_PRESENTATION_TOKEN: Final[str] = "production_ready"

# ---------------------------------------------------------------------------
# Import-time honesty — the vocabulary cannot drift from the doctrine.
# ---------------------------------------------------------------------------

# Covers EXACTLY the generated registry implementation states (no rot when the
# registry adds a state, and no orphan presentation spelling).
assert set(IMPLEMENTATION_STATE_PRESENTATION) == frozenset(
    PROJECTION_IMPLEMENTATION_STATES
), (
    "IMPLEMENTATION_STATE_PRESENTATION must cover exactly the generated "
    f"registry implementation states {sorted(PROJECTION_IMPLEMENTATION_STATES)}"
)

# Closed set: every state maps to exactly one token (bijective, no aliasing).
assert len(PRESENTATION_TOKENS) == len(IMPLEMENTATION_STATE_PRESENTATION), (
    "PRESENTATION_TOKENS must be a closed set with one token per state"
)

# Never contains production_ready (a claim dimension, never a state).
assert _FORBIDDEN_PRESENTATION_TOKEN not in PRESENTATION_TOKENS, (
    "the presentation vocabulary must never contain production_ready"
)

# Every token is a well-formed lower_snake identifier (mirrors the generated
# registries' _require_idents discipline).
assert all(
    token.isidentifier() and token == token.lower()
    for token in PRESENTATION_TOKENS
), "presentation tokens must be lower_snake identifiers"


def presentation_token(implementation_state: str) -> str:
    """Return the presentation-only token for a registry implementation state.

    Maps one of the four generated implementation states
    (``registered`` | ``in_flight`` | ``implemented`` | ``deprecated``) onto the
    closed presentation vocabulary. Raises :class:`ProjectionError` for any
    unknown state — never a bare ``KeyError`` — so a UI can classify the
    failure instead of string-matching.

    Args:
        implementation_state: A registry ``implementationState`` value.

    Returns:
        The presentation-only token for UI display.

    Raises:
        ProjectionError: If ``implementation_state`` is not one of the four
            generated registry states.
    """
    try:
        return IMPLEMENTATION_STATE_PRESENTATION[implementation_state]
    except KeyError:
        raise ProjectionError(
            f"unknown implementation state {implementation_state!r}; expected "
            f"one of {sorted(IMPLEMENTATION_STATE_PRESENTATION)}",
            context={"implementation_state": implementation_state},
        ) from None


__all__ = [
    "IMPLEMENTATION_STATE_PRESENTATION",
    "PRESENTATION_TOKENS",
    "presentation_token",
]
