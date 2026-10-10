"""Connection lifecycle: legal/illegal transitions and sync-status mapping."""

from __future__ import annotations

import pytest

from shared.integration_contracts.lifecycle import (
    TRANSITIONS,
    ConnectionState,
    can_transition,
    from_connector_sync_status,
)


def test_legal_setup_transitions() -> None:
    assert can_transition(ConnectionState.AVAILABLE, ConnectionState.AUTHORIZATION_PENDING)
    assert can_transition(
        ConnectionState.AUTHORIZATION_PENDING, ConnectionState.CREDENTIALS_RECEIVED
    )
    assert can_transition(ConnectionState.CREDENTIALS_RECEIVED, ConnectionState.VERIFYING)
    assert can_transition(ConnectionState.VERIFYING, ConnectionState.VERIFIED)
    assert can_transition(
        ConnectionState.INITIAL_SYNC_RUNNING, ConnectionState.CONNECTED
    )


def test_legal_operational_and_recovery_transitions() -> None:
    assert can_transition(ConnectionState.CONNECTED, ConnectionState.DEGRADED)
    assert can_transition(ConnectionState.DEGRADED, ConnectionState.CONNECTED)
    assert can_transition(
        ConnectionState.TOKEN_EXPIRING, ConnectionState.REAUTHORIZATION_REQUIRED
    )
    assert can_transition(ConnectionState.REVOKED, ConnectionState.AVAILABLE)


def test_illegal_transitions() -> None:
    # Cannot jump straight from AVAILABLE to CONNECTED (must be verified first).
    assert not can_transition(ConnectionState.AVAILABLE, ConnectionState.CONNECTED)
    # Cannot go back from CONNECTED to a raw setup state.
    assert not can_transition(ConnectionState.CONNECTED, ConnectionState.AVAILABLE)
    # DEPRECATED is terminal.
    assert not can_transition(ConnectionState.DEPRECATED, ConnectionState.AVAILABLE)
    assert TRANSITIONS[ConnectionState.DEPRECATED] == set()
    # Self-transition is not implicitly legal.
    assert not can_transition(ConnectionState.CONNECTED, ConnectionState.CONNECTED)


def test_transitions_table_targets_are_known_states() -> None:
    for src, targets in TRANSITIONS.items():
        assert isinstance(src, ConnectionState)
        for dst in targets:
            assert isinstance(dst, ConnectionState)


def test_from_connector_sync_status_mapping() -> None:
    assert from_connector_sync_status("never_synced") is ConnectionState.INITIAL_SYNC_PENDING
    assert from_connector_sync_status("syncing") is ConnectionState.INITIAL_SYNC_RUNNING
    assert from_connector_sync_status("healthy") is ConnectionState.CONNECTED
    assert from_connector_sync_status("degraded") is ConnectionState.DEGRADED
    assert from_connector_sync_status("failed") is ConnectionState.SYNC_FAILED
    assert from_connector_sync_status("disabled") is ConnectionState.DISABLED


def test_from_connector_sync_status_unknown_raises() -> None:
    with pytest.raises(ValueError):
        from_connector_sync_status("bogus")  # type: ignore[arg-type]
