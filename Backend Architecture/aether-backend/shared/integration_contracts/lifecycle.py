"""Connection lifecycle state machine (§16).

A single :class:`ConnectionState` enum spans three bands:

* **setup** — bringing a connection from ``AVAILABLE`` to ``CONNECTED``;
* **operational** — a live connection's health/error states;
* **readiness** — pre-setup gates (contract/approval/credentials) and the
  terminal off-ramps (``UNSUPPORTED``, ``DEPRECATED``).

``CONNECTED`` is the hinge between the setup and operational bands (it appears
in both lists in the spec; here it is one member). :data:`TRANSITIONS` is the
explicit legal-move table; :func:`can_transition` reads it.
:func:`from_connector_sync_status` projects the legacy connector sync status
onto a lifecycle state so existing health signals can drive the machine.
"""

from __future__ import annotations

from enum import Enum

from services.integrations.connectors.base import ConnectorSyncStatus


class ConnectionState(str, Enum):
    """Every state a tenant<->provider connection can occupy."""

    # ── Readiness / pre-setup gates ──
    CONTRACT_REQUIRED = "contract_required"
    PROVIDER_APPROVAL_REQUIRED = "provider_approval_required"
    CREDENTIAL_WAITING = "credential_waiting"
    PRODUCT_DEFERRED = "product_deferred"
    CERTIFIED = "certified"
    UNSUPPORTED = "unsupported"
    DEPRECATED = "deprecated"

    # ── Setup band ──
    AVAILABLE = "available"
    AUTHORIZATION_PENDING = "authorization_pending"
    CREDENTIALS_RECEIVED = "credentials_received"
    VERIFYING = "verifying"
    VERIFIED = "verified"
    ACCOUNT_SELECTION_REQUIRED = "account_selection_required"
    CONFIGURATION_REQUIRED = "configuration_required"
    WEBHOOK_REGISTRATION_PENDING = "webhook_registration_pending"
    INITIAL_SYNC_PENDING = "initial_sync_pending"
    INITIAL_SYNC_RUNNING = "initial_sync_running"

    # ── Operational band ──
    CONNECTED = "connected"
    DEGRADED = "degraded"
    RATE_LIMITED = "rate_limited"
    PERMISSION_MISSING = "permission_missing"
    TOKEN_EXPIRING = "token_expiring"
    REAUTHORIZATION_REQUIRED = "reauthorization_required"
    WEBHOOK_INVALID = "webhook_invalid"
    SYNC_FAILED = "sync_failed"
    REVOKED = "revoked"
    DISABLED = "disabled"
    FAILED = "failed"


_S = ConnectionState

# Explicit legal-transition table. A state absent from a source's set is an
# illegal move. Terminal states map to an empty set.
TRANSITIONS: dict[ConnectionState, set[ConnectionState]] = {
    # ── Readiness gates progress toward AVAILABLE ──
    _S.CONTRACT_REQUIRED: {
        _S.PROVIDER_APPROVAL_REQUIRED,
        _S.CREDENTIAL_WAITING,
        _S.UNSUPPORTED,
        _S.DEPRECATED,
    },
    _S.PROVIDER_APPROVAL_REQUIRED: {
        _S.CREDENTIAL_WAITING,
        _S.CONTRACT_REQUIRED,
        _S.DEPRECATED,
    },
    _S.CREDENTIAL_WAITING: {
        _S.AVAILABLE,
        _S.CERTIFIED,
        _S.PRODUCT_DEFERRED,
        _S.UNSUPPORTED,
    },
    _S.PRODUCT_DEFERRED: {_S.CREDENTIAL_WAITING, _S.AVAILABLE},
    _S.CERTIFIED: {_S.AVAILABLE, _S.CONNECTED},
    _S.UNSUPPORTED: {_S.DEPRECATED},
    _S.DEPRECATED: set(),
    # ── Setup band ──
    _S.AVAILABLE: {
        _S.AUTHORIZATION_PENDING,
        _S.CREDENTIALS_RECEIVED,
        _S.VERIFYING,
        _S.DISABLED,
    },
    _S.AUTHORIZATION_PENDING: {
        _S.CREDENTIALS_RECEIVED,
        _S.FAILED,
        _S.AVAILABLE,
    },
    _S.CREDENTIALS_RECEIVED: {_S.VERIFYING, _S.FAILED},
    _S.VERIFYING: {_S.VERIFIED, _S.FAILED, _S.REAUTHORIZATION_REQUIRED},
    _S.VERIFIED: {
        _S.ACCOUNT_SELECTION_REQUIRED,
        _S.CONFIGURATION_REQUIRED,
        _S.WEBHOOK_REGISTRATION_PENDING,
        _S.INITIAL_SYNC_PENDING,
        _S.CONNECTED,
    },
    _S.ACCOUNT_SELECTION_REQUIRED: {
        _S.CONFIGURATION_REQUIRED,
        _S.WEBHOOK_REGISTRATION_PENDING,
        _S.INITIAL_SYNC_PENDING,
        _S.CONNECTED,
    },
    _S.CONFIGURATION_REQUIRED: {
        _S.WEBHOOK_REGISTRATION_PENDING,
        _S.INITIAL_SYNC_PENDING,
        _S.CONNECTED,
    },
    _S.WEBHOOK_REGISTRATION_PENDING: {
        _S.INITIAL_SYNC_PENDING,
        _S.CONNECTED,
        _S.WEBHOOK_INVALID,
    },
    _S.INITIAL_SYNC_PENDING: {_S.INITIAL_SYNC_RUNNING, _S.FAILED},
    _S.INITIAL_SYNC_RUNNING: {_S.CONNECTED, _S.SYNC_FAILED},
    # ── Operational band ──
    _S.CONNECTED: {
        _S.DEGRADED,
        _S.RATE_LIMITED,
        _S.PERMISSION_MISSING,
        _S.TOKEN_EXPIRING,
        _S.REAUTHORIZATION_REQUIRED,
        _S.WEBHOOK_INVALID,
        _S.SYNC_FAILED,
        _S.REVOKED,
        _S.DISABLED,
        _S.FAILED,
        _S.CERTIFIED,
    },
    _S.DEGRADED: {_S.CONNECTED, _S.SYNC_FAILED, _S.FAILED, _S.DISABLED},
    _S.RATE_LIMITED: {_S.CONNECTED, _S.DEGRADED},
    _S.PERMISSION_MISSING: {_S.REAUTHORIZATION_REQUIRED, _S.CONNECTED, _S.FAILED},
    _S.TOKEN_EXPIRING: {_S.REAUTHORIZATION_REQUIRED, _S.CONNECTED},
    _S.REAUTHORIZATION_REQUIRED: {
        _S.AUTHORIZATION_PENDING,
        _S.CREDENTIALS_RECEIVED,
        _S.VERIFYING,
        _S.FAILED,
        _S.REVOKED,
    },
    _S.WEBHOOK_INVALID: {_S.WEBHOOK_REGISTRATION_PENDING, _S.CONNECTED, _S.DEGRADED},
    _S.SYNC_FAILED: {_S.INITIAL_SYNC_PENDING, _S.CONNECTED, _S.DEGRADED, _S.FAILED},
    _S.REVOKED: {_S.AVAILABLE, _S.DISABLED},
    _S.DISABLED: {_S.AVAILABLE},
    _S.FAILED: {_S.AVAILABLE, _S.DISABLED},
}


def can_transition(a: ConnectionState, b: ConnectionState) -> bool:
    """True iff moving from state ``a`` to state ``b`` is legal."""
    return b in TRANSITIONS.get(a, set())


# Projection of the legacy connector sync status onto a lifecycle state.
_SYNC_STATUS_TO_STATE: dict[str, ConnectionState] = {
    "never_synced": ConnectionState.INITIAL_SYNC_PENDING,
    "syncing": ConnectionState.INITIAL_SYNC_RUNNING,
    "healthy": ConnectionState.CONNECTED,
    "degraded": ConnectionState.DEGRADED,
    "failed": ConnectionState.SYNC_FAILED,
    "disabled": ConnectionState.DISABLED,
}


def from_connector_sync_status(s: ConnectorSyncStatus) -> ConnectionState:
    """Map a connector ``ConnectorSyncStatus`` onto a :class:`ConnectionState`."""
    try:
        return _SYNC_STATUS_TO_STATE[s]
    except KeyError as exc:  # pragma: no cover - defensive; Literal is exhaustive
        raise ValueError(f"no lifecycle state for sync status {s!r}") from exc


# ── Projection onto the canonical capability lifecycle ───────────────────────
# ConnectionState stays the connectors' fine-grained internal machine; the
# canonical cross-domain readiness truth is shared.certification.readiness.
# This TOTAL map (a test asserts coverage of every member) projects each
# connection state onto its honest CredentialReadiness rung so the persisted
# capability lifecycle can absorb connector health without a second vocabulary.


def _readiness():
    from shared.certification.readiness import CredentialReadiness

    return CredentialReadiness


def connection_state_to_readiness(state: ConnectionState):
    """Project a :class:`ConnectionState` onto the canonical
    ``CredentialReadiness`` token (total — raises on an unmapped member)."""
    R = _readiness()
    mapping = {
        # Readiness / pre-setup gates
        _S.CONTRACT_REQUIRED: R.CREDENTIAL_WAITING,
        _S.PROVIDER_APPROVAL_REQUIRED: R.CREDENTIAL_WAITING,
        _S.CREDENTIAL_WAITING: R.CREDENTIAL_WAITING,
        _S.PRODUCT_DEFERRED: R.DISABLED,
        _S.CERTIFIED: R.SANDBOX_VALIDATED,
        _S.UNSUPPORTED: R.DISABLED,
        _S.DEPRECATED: R.DISABLED,
        # Setup band
        _S.AVAILABLE: R.CREDENTIAL_WAITING,
        _S.AUTHORIZATION_PENDING: R.CREDENTIAL_WAITING,
        _S.CREDENTIALS_RECEIVED: R.CREDENTIAL_SUPPLIED,
        _S.VERIFYING: R.CREDENTIAL_SUPPLIED,
        _S.VERIFIED: R.CONNECTION_VALIDATED,
        _S.ACCOUNT_SELECTION_REQUIRED: R.CONNECTION_VALIDATED,
        _S.CONFIGURATION_REQUIRED: R.CONNECTION_VALIDATED,
        _S.WEBHOOK_REGISTRATION_PENDING: R.CONNECTION_VALIDATED,
        _S.INITIAL_SYNC_PENDING: R.CONNECTION_VALIDATED,
        _S.INITIAL_SYNC_RUNNING: R.CONNECTION_VALIDATED,
        # Operational band
        _S.CONNECTED: R.PARTNER_LIVE,
        _S.DEGRADED: R.DEGRADED,
        _S.RATE_LIMITED: R.DEGRADED,
        _S.PERMISSION_MISSING: R.DEGRADED,
        _S.TOKEN_EXPIRING: R.DEGRADED,
        _S.REAUTHORIZATION_REQUIRED: R.CREDENTIAL_WAITING,
        _S.WEBHOOK_INVALID: R.DEGRADED,
        _S.SYNC_FAILED: R.DEGRADED,
        _S.REVOKED: R.REVOKED,
        _S.DISABLED: R.DISABLED,
        _S.FAILED: R.DEGRADED,
    }
    try:
        return mapping[state]
    except KeyError as exc:
        raise ValueError(f"no readiness projection for connection state {state!r}") from exc


__all__ = [
    "TRANSITIONS",
    "ConnectionState",
    "can_transition",
    "connection_state_to_readiness",
    "from_connector_sync_status",
]
