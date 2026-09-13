"""CP-12 typed-availability helpers.

Blueprint CP-12: ``missing``, ``empty``, ``zero``, ``degraded`` and
``not_applicable`` remain distinct — no operator health surface may fabricate
``zero``/``empty`` to represent missing evidence. Every helper here is therefore
*explicit* about the label it emits:

* ``available``  — authoritative evidence exists and is usable.
* ``empty``      — the surface exists but legitimately has no rows/values.
* ``missing``    — evidence is absent (the durable record does not exist).
* ``degraded``   — evidence exists but is partial/stale/lower-quality.
* ``not_applicable`` — the dimension intentionally does not apply.
* ``unknown``    — the authority was unreachable or gave no signal.

Only helpers that have a defensible mapping to one of these six emit a value;
everything ambiguous resolves to ``unknown`` (never ``empty``/``missing`` for
each other).
"""

from __future__ import annotations

from typing import Optional

from services.managed_integrations.contracts import (
    INTEGRATION_AVAILABILITY_VALUES,
    IntegrationAvailability,
)

# CredentialReadiness-state string values (mirrors shared/certification/readiness
# without importing the enum here — the literal is the stable contract).
_READY_AVAILABLE = frozenset(
    {"connection_validated", "sandbox_validated", "partner_live"}
)
_READY_DEGRADED = frozenset({"credential_supplied", "degraded", "suspended"})
_READY_MISSING = frozenset(
    {"scaffolded", "credential_waiting", "revoked", "disabled"}
)


def is_availability(value: str) -> bool:
    """True when ``value`` is one of the six CP-12 availability labels."""
    return value in INTEGRATION_AVAILABILITY_VALUES


def assert_availability(value: str) -> IntegrationAvailability:
    """Fail loudly on a non-CP-12 label so a typo can never widen the surface."""
    if not is_availability(value):
        raise ValueError(
            f"{value!r} is not a CP-12 availability label; "
            f"expected one of {INTEGRATION_AVAILABILITY_VALUES}"
        )
    return value  # type: ignore[return-value]


def availability_from_presence(
    present: Optional[bool], *, absent: str = "missing"
) -> str:
    """Map pure presence/absence to availability without fabricating ``empty``.

    ``present=True``  -> ``available``.
    ``present=False`` -> ``absent`` (default ``missing`` — a caller that means
    ``empty`` must pass ``absent="empty"`` explicitly).
    ``present=None``  -> ``unknown`` (the authority gave no signal).
    """
    if present is None:
        return "unknown"
    if present:
        return "available"
    if absent not in INTEGRATION_AVAILABILITY_VALUES:
        raise ValueError(f"{absent!r} is not a CP-12 availability label")
    return absent


def availability_from_readiness(state: Optional[str]) -> str:
    """Map a capability activation ``readiness_state`` to capability availability.

    Explicit labels: a validated/live capability is ``available``; a supplied-
    but-unvalidated, degraded or suspended one is ``degraded``; a not-yet
    supplied / revoked / disabled one is ``missing``. Absent state -> ``missing``
    (no capability row); never ``empty``.
    """
    if not state:
        return "missing"
    key = str(state).lower().replace("-", "_")
    if key in _READY_AVAILABLE:
        return "available"
    if key in _READY_DEGRADED:
        return "degraded"
    if key in _READY_MISSING:
        return "missing"
    return "unknown"
