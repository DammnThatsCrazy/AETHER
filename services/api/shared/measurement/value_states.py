"""Canonical value-state vocabulary for the Measurement Integrity Plane.

Every metric a calculator emits carries exactly one :class:`ValueState`. The
state is the honest story of *why* a number is (or is not) present. The core
invariant of the whole plane:

* ``OBSERVED`` / ``ESTIMATED`` — the data supports a real number, so ``value``
  MUST be a finite float.
* every other state — the number is not supported (not enough data, not
  applicable, inputs missing, degraded pipeline), so ``value`` MUST be ``None``.

This is what makes "no metric is reported as a real number unless the data
supports it" enforceable rather than aspirational: a calculator can never quietly
return ``0`` on missing data — it returns ``(None, <non-value-bearing state>)``.
"""

from __future__ import annotations

from enum import Enum


class ValueState(str, Enum):
    """Why a measurement value is present, or honestly absent."""

    OBSERVED = "observed"
    ESTIMATED = "estimated"
    INSUFFICIENT_DATA = "insufficient_data"
    NOT_APPLICABLE = "not_applicable"
    MISSING_INPUTS = "missing_inputs"
    DEGRADED = "degraded"


# Parallel const tuple for iteration / validation / cross-language parity.
VALUE_STATES: tuple[str, ...] = tuple(state.value for state in ValueState)

# The only states under which a real ``value`` may (and must) be present.
_VALUE_BEARING: frozenset[ValueState] = frozenset({ValueState.OBSERVED, ValueState.ESTIMATED})


def requires_value(state: ValueState | str) -> bool:
    """Return True only for states that require a real numeric ``value``.

    ``True``  → state is OBSERVED or ESTIMATED; ``value`` must be a finite number.
    ``False`` → any other state; ``value`` must be ``None``.

    Accepts either a :class:`ValueState` member or its string value.
    """

    return ValueState(state) in _VALUE_BEARING
