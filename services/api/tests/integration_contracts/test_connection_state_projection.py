"""ConnectionState → CredentialReadiness projection — total-coverage contract.

The connectors' fine-grained ConnectionState machine projects onto the
canonical CredentialReadiness lifecycle via
``connection_state_to_readiness``. The map must be TOTAL (every member) and
honest: operational-band failure states may never project onto a progression
rung above the capability's actual evidence.
"""

from __future__ import annotations

import os
import sys

os.environ.setdefault("AETHER_ENV", "local")
os.environ.setdefault("JWT_SECRET", "test-secret")
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

import pytest

from shared.certification.readiness import CredentialReadiness as R
from shared.certification.readiness import readiness_rank
from shared.integration_contracts.lifecycle import (
    ConnectionState,
    connection_state_to_readiness,
)


def test_projection_is_total():
    for state in ConnectionState:
        result = connection_state_to_readiness(state)
        assert isinstance(result, R), f"{state} projected to non-readiness {result!r}"


def test_projection_key_semantics():
    assert connection_state_to_readiness(ConnectionState.CONNECTED) == R.PARTNER_LIVE
    assert connection_state_to_readiness(ConnectionState.CERTIFIED) == R.SANDBOX_VALIDATED
    assert connection_state_to_readiness(ConnectionState.VERIFIED) == R.CONNECTION_VALIDATED
    assert (
        connection_state_to_readiness(ConnectionState.CREDENTIALS_RECEIVED)
        == R.CREDENTIAL_SUPPLIED
    )
    assert (
        connection_state_to_readiness(ConnectionState.CREDENTIAL_WAITING)
        == R.CREDENTIAL_WAITING
    )
    assert connection_state_to_readiness(ConnectionState.REVOKED) == R.REVOKED
    assert connection_state_to_readiness(ConnectionState.DISABLED) == R.DISABLED
    assert connection_state_to_readiness(ConnectionState.DEGRADED) == R.DEGRADED


def test_failure_states_never_project_into_progression():
    threshold = readiness_rank(R.CREDENTIAL_WAITING)
    for state in (
        ConnectionState.DEGRADED,
        ConnectionState.RATE_LIMITED,
        ConnectionState.PERMISSION_MISSING,
        ConnectionState.WEBHOOK_INVALID,
        ConnectionState.SYNC_FAILED,
        ConnectionState.FAILED,
        ConnectionState.REVOKED,
        ConnectionState.DISABLED,
        ConnectionState.TOKEN_EXPIRING,
    ):
        assert readiness_rank(connection_state_to_readiness(state)) < threshold


def test_reauthorization_required_demotes_to_credential_waiting():
    assert (
        connection_state_to_readiness(ConnectionState.REAUTHORIZATION_REQUIRED)
        == R.CREDENTIAL_WAITING
    )


def test_unmapped_member_raises():
    with pytest.raises(ValueError):
        connection_state_to_readiness("not_a_state")  # type: ignore[arg-type]
