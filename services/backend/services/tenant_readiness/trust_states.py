"""Tenant Trust States (§3.14).

A *trust state* is an operator- and tenant-visible signal describing why a
tenant's data / intelligence should be treated with caution. Trust states are
**additive and fail-closed**: absence of a signal never fabricates trust, and a
degraded / blocked condition always surfaces a state rather than being hidden.

``derive_trust_states(signals)`` maps a bag of observed ``signals`` to the
applicable trust states, returned in the canonical order below (deterministic).

Two ways to feed the deriver:

* **Explicit** — pass a trust-state name as a truthy key, e.g.
  ``{"replay_in_progress": True}``.
* **Semantic** — pass a domain observation the deriver knows how to interpret,
  e.g. ``{"event_count": 0}`` -> ``no_data`` or ``{"usage": 95, "limit": 100}``
  -> ``quota_near_limit``.

Both may be combined; the result is de-duplicated and canonically ordered.
"""
from __future__ import annotations

from typing import Any


class TrustState:
    """Canonical trust-state constants (§3.14)."""

    NO_DATA = "no_data"
    PARTIAL_DATA = "partial_data"
    CONSENT_MISSING = "consent_missing"
    IDENTITY_PENDING = "identity_pending"
    IDENTITY_CONFLICT = "identity_conflict"
    IDENTITY_RECOMPUTED = "identity_recomputed"
    GRAPH_BLOCKED_BY_POLICY = "graph_blocked_by_policy"
    GRAPH_STALE = "graph_stale"
    MODEL_UNAVAILABLE = "model_unavailable"
    MODEL_BLOCKED_BY_POLICY = "model_blocked_by_policy"
    PROFILE360_STALE = "profile360_stale"
    CONNECTOR_FAILED = "connector_failed"
    CONNECTOR_SIGNATURE_FAILED = "connector_signature_failed"
    WEBHOOK_DISABLED = "webhook_disabled"
    REPLAY_IN_PROGRESS = "replay_in_progress"
    DSR_IN_PROGRESS = "dsr_in_progress"
    REWARD_BLOCKED_BY_CONSENT = "reward_blocked_by_consent"
    ATTRIBUTION_CONFLICT = "attribution_conflict"
    QUOTA_NEAR_LIMIT = "quota_near_limit"
    QUOTA_EXCEEDED = "quota_exceeded"
    FINANCIAL_VALUES_PARTIAL = "financial_values_partial"
    FINANCIAL_VALUES_UNPRICED = "financial_values_unpriced"
    FINANCIAL_VALUES_CONFLICTED = "financial_values_conflicted"


# Canonical, deterministic ordering. derive_trust_states() always returns a
# subset of this tuple, preserving this order.
TRUST_STATES: tuple[str, ...] = (
    TrustState.NO_DATA,
    TrustState.PARTIAL_DATA,
    TrustState.CONSENT_MISSING,
    TrustState.IDENTITY_PENDING,
    TrustState.IDENTITY_CONFLICT,
    TrustState.IDENTITY_RECOMPUTED,
    TrustState.GRAPH_BLOCKED_BY_POLICY,
    TrustState.GRAPH_STALE,
    TrustState.MODEL_UNAVAILABLE,
    TrustState.MODEL_BLOCKED_BY_POLICY,
    TrustState.PROFILE360_STALE,
    TrustState.CONNECTOR_FAILED,
    TrustState.CONNECTOR_SIGNATURE_FAILED,
    TrustState.WEBHOOK_DISABLED,
    TrustState.REPLAY_IN_PROGRESS,
    TrustState.DSR_IN_PROGRESS,
    TrustState.REWARD_BLOCKED_BY_CONSENT,
    TrustState.ATTRIBUTION_CONFLICT,
    TrustState.QUOTA_NEAR_LIMIT,
    TrustState.QUOTA_EXCEEDED,
    TrustState.FINANCIAL_VALUES_PARTIAL,
    TrustState.FINANCIAL_VALUES_UNPRICED,
    TrustState.FINANCIAL_VALUES_CONFLICTED,
)

TRUST_STATE_SET: frozenset[str] = frozenset(TRUST_STATES)


def is_trust_state(value: str) -> bool:
    """Return True iff ``value`` is a recognised trust state."""
    return value in TRUST_STATE_SET


def _is_zero(signals: dict[str, Any], key: str) -> bool:
    """True when ``key`` is present and equals 0 (explicit emptiness)."""
    return key in signals and signals.get(key) == 0


def derive_trust_states(signals: dict[str, Any]) -> list[str]:
    """Map observed ``signals`` to the applicable trust states.

    Returns a de-duplicated list in canonical :data:`TRUST_STATES` order.
    Never raises on unknown keys — unrecognised signals are simply ignored.
    """
    signals = signals or {}
    states: set[str] = set()

    # 1) Explicit: a trust-state name passed as a truthy flag.
    for state in TRUST_STATES:
        if signals.get(state) is True:
            states.add(state)

    # 2) Semantic derivations.

    # Data volume / completeness.
    if (
        _is_zero(signals, "event_count")
        or signals.get("has_data") is False
        or signals.get("data_state") == "none"
    ):
        states.add(TrustState.NO_DATA)
    if signals.get("data_state") == "partial":
        states.add(TrustState.PARTIAL_DATA)

    # Consent.
    if (
        signals.get("consent_present") is False
        or _is_zero(signals, "consent_snapshots")
    ):
        states.add(TrustState.CONSENT_MISSING)

    # Identity resolution lifecycle.
    identity_status = signals.get("identity_status")
    if identity_status == "pending":
        states.add(TrustState.IDENTITY_PENDING)
    elif identity_status == "conflict":
        states.add(TrustState.IDENTITY_CONFLICT)
    elif identity_status == "recomputed":
        states.add(TrustState.IDENTITY_RECOMPUTED)

    # Graph projection.
    if signals.get("graph_policy_blocked") is True:
        states.add(TrustState.GRAPH_BLOCKED_BY_POLICY)
    if signals.get("graph_stale") is True:
        states.add(TrustState.GRAPH_STALE)

    # Model policy / availability.
    if signals.get("model_available") is False:
        states.add(TrustState.MODEL_UNAVAILABLE)
    if signals.get("model_policy_blocked") is True:
        states.add(TrustState.MODEL_BLOCKED_BY_POLICY)

    # Profile 360 freshness.
    if signals.get("profile360_stale") is True:
        states.add(TrustState.PROFILE360_STALE)

    # Connectors.
    if signals.get("connector_status") == "failed":
        states.add(TrustState.CONNECTOR_FAILED)
    if signals.get("connector_signature_valid") is False:
        states.add(TrustState.CONNECTOR_SIGNATURE_FAILED)

    # Generic webhook (V1 default disabled). An explicit False means the
    # connector plane confirmed the generic webhook is off.
    if signals.get("generic_webhook_enabled") is False:
        states.add(TrustState.WEBHOOK_DISABLED)

    # In-flight lifecycle operations.
    if signals.get("replay_in_progress") is True:
        states.add(TrustState.REPLAY_IN_PROGRESS)
    if signals.get("dsr_in_progress") is True:
        states.add(TrustState.DSR_IN_PROGRESS)

    # Rewards / attribution.
    if signals.get("reward_blocked_by_consent") is True:
        states.add(TrustState.REWARD_BLOCKED_BY_CONSENT)
    if signals.get("attribution_conflict") is True:
        states.add(TrustState.ATTRIBUTION_CONFLICT)

    # Quota. Accept a precomputed quota_state, or derive from usage/limit.
    quota = signals.get("quota_state")
    if quota is None and "usage" in signals and "limit" in signals:
        from .quota import quota_state as _quota_state

        quota = _quota_state(signals["usage"], signals["limit"])
    if quota == TrustState.QUOTA_NEAR_LIMIT:
        states.add(TrustState.QUOTA_NEAR_LIMIT)
    elif quota == TrustState.QUOTA_EXCEEDED:
        states.add(TrustState.QUOTA_EXCEEDED)

    # Financial value semantics.
    financial = signals.get("financial_value_status")
    if financial == "partial":
        states.add(TrustState.FINANCIAL_VALUES_PARTIAL)
    elif financial == "unpriced":
        states.add(TrustState.FINANCIAL_VALUES_UNPRICED)
    elif financial == "conflicted":
        states.add(TrustState.FINANCIAL_VALUES_CONFLICTED)

    return [state for state in TRUST_STATES if state in states]
