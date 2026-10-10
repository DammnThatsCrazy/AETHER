"""Aether — Rights Authority: rollout-mode guard (off | shadow | warn | enforce).

Activation posture for the ``rights_irrl`` authority. Blueprint §16 (migration
strategy) requires rollout to be **per gate, no global hard flip**:

    Rollout modes per gate: OFF | SHADOW | WARN | ENFORCE.

This module is intentionally self-contained and additive: it exposes the mode
vocabulary, a parser, and small guard helpers a consumer (revocation pipeline,
model-training adapter, a future HTTP route, resolver callers) can consult to
decide how hard to act. It wires **nothing** by itself.

Mode semantics (matching blueprint §1.5/§13 fail-closed doctrine and the §16
migration ladder):

- ``off`` — the authority is inert. No decisions are recorded and nothing is
  denied by this gate; a consumer that consults the guard should behave exactly
  as it did before the authority existed.
- ``shadow`` — evaluation runs and decisions are **recorded** for comparison,
  but no downstream behaviour is denied or altered.
- ``warn`` — decisions are recorded and denials are surfaced as warnings; a
  consumer may block on a warning when it already has a blocking path, but the
  gate itself does not hard-enforce.
- ``enforce`` — decisions are recorded and denials **bind**; consumers must act
  on a denial.

Important limitation (deliberate): a rollout mode only binds when the consumer
that consults it actually acts on the decision it returns. Recording a decision
in ``enforce`` does not by itself delete data, stop training, or block a graph
mutation — downstream enforcement is a separate seam (graph/spine propagation,
revocation pipeline execution, artifact-store deletion adapters). This module is
the *guard*; it is not the *executor*.
"""
from __future__ import annotations

import enum
import logging
import os
from typing import Any, Optional

logger = logging.getLogger("aether.rights_irrl.rollout")

# Canonical env/config key. Absent/invalid ⇒ ``off`` (activation is explicit).
ROLLOUT_ENV_VAR = "RIGHTS_AUTHORITY_ROLLOUT"
# Fail-closed default: an unset or unparseable value never activates anything.
DEFAULT_ROLLOUT_MODE = "off"


class RolloutMode(str, enum.Enum):
    """Rollout modes per gate (blueprint §16). Values are canonical lowercase."""

    OFF = "off"
    SHADOW = "shadow"
    WARN = "warn"
    ENFORCE = "enforce"

    @classmethod
    def _missing_(cls, value: Any) -> Optional["RolloutMode"]:
        # Normalise arbitrary spelling to the canonical snake value.
        normalized = str(value or "").strip().lower().replace("-", "_")
        for member in cls:
            if member.value == normalized:
                return member
        return None


# In-process override consulted before the environment. Lets a long-running
# process (or a test) pin a mode without re-spawning with a new env var.
_OVERRIDE: Optional[RolloutMode] = None


def parse_rollout_mode(
    value: Any,
    *,
    default: RolloutMode = RolloutMode.OFF,
) -> RolloutMode:
    """Parse an arbitrary rollout-mode value into a :class:`RolloutMode`.

    Accepts ``OFF | SHADOW | WARN | ENFORCE`` in any case/spelling (hyphens are
    mapped to underscores). Unknown, empty, or unparseable values return
    ``default`` (``off`` unless overridden) — an invalid value never activates
    enforcement. That is the fail-closed choice: turning an operator typo into
    ``enforce`` would be a fail-open.
    """
    if value is None or isinstance(value, RolloutMode):
        return value if isinstance(value, RolloutMode) else default
    try:
        return RolloutMode(value)
    except (ValueError, TypeError):
        logger.warning(
            "unknown rollout mode %r; defaulting to %r (fail closed)",
            value,
            default.value,
        )
        return default


def configure_rollout(value: Any) -> RolloutMode:
    """Pin the in-process rollout mode (override). ``None`` clears the override.

    This is the configuration seam for non-env callers (route registration,
    process startup). It returns the mode now in effect.
    """
    global _OVERRIDE
    if value is None:
        _OVERRIDE = None
        return current_mode()
    mode = parse_rollout_mode(value)
    _OVERRIDE = mode
    return mode


def reset_rollout() -> None:
    """Clear any in-process override so the env/default path governs again."""
    global _OVERRIDE
    _OVERRIDE = None


def current_mode() -> RolloutMode:
    """The rollout mode in effect: override → env → ``off``."""
    if _OVERRIDE is not None:
        return _OVERRIDE
    raw = os.getenv(ROLLOUT_ENV_VAR)
    if raw is None:
        return RolloutMode.OFF
    return parse_rollout_mode(raw)


def mode_label() -> str:
    """Canonical string label for the mode in effect (e.g. ``"enforce"``)."""
    return current_mode().value


def is_active() -> bool:
    """Whether the gate is doing anything at all (``off`` is inert)."""
    return current_mode() is not RolloutMode.OFF


def record_decisions() -> bool:
    """Whether decisions should be persisted/recorded under the current mode.

    True for ``shadow``/``warn``/``enforce``; False only for ``off`` (an inert
    gate must not fabricate durable state).
    """
    return is_active()


def enforce_denials() -> bool:
    """Whether denials are hard-enforced (True only in ``enforce``).

    A consumer that cannot honour the binding semantics of ``enforce`` must not
    claim enforcement; it should consult :func:`current_mode` and act within its
    own authority (e.g. surface a warning in ``warn``).
    """
    return current_mode() is RolloutMode.ENFORCE


def describe() -> dict[str, Any]:
    """Machine-readable snapshot of the guard state (logging/diagnostics)."""
    mode = current_mode()
    return {
        "mode": mode.value,
        "source": "override" if _OVERRIDE is not None else (
            "env" if os.getenv(ROLLOUT_ENV_VAR) is not None else "default"
        ),
        "active": is_active(),
        "record_decisions": record_decisions(),
        "enforce_denials": enforce_denials(),
    }


__all__ = [
    "DEFAULT_ROLLOUT_MODE",
    "ROLLOUT_ENV_VAR",
    "RolloutMode",
    "configure_rollout",
    "current_mode",
    "describe",
    "enforce_denials",
    "is_active",
    "mode_label",
    "parse_rollout_mode",
    "record_decisions",
    "reset_rollout",
]
