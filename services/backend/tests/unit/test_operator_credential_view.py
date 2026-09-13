"""Operator cross-tenant credential view — secrets never leak (sec26/sec27).

The ported :mod:`services.providers.credentials.operator_view` is the only
surface that reads credential state across tenants for the Kyber operator
plane. Every view is built from :data:`CredentialAuthority._SAFE_FIELDS` via
:meth:`CredentialAuthority._safe_view`, so a regular Aether tenant — even an
admin — can never receive a secret (no plaintext, no ciphertext, no data key).

These tests cover the three operator-view helpers end-to-end against the
canonical credential authority: the cross-tenant roll-up, tombstone
exclusion, and the per-tenant grouped view.
"""

from __future__ import annotations

import json
import os

import pytest

os.environ.setdefault("AETHER_ENV", "local")

from repositories.repos import reset_in_memory_stores  # noqa: E402
from repositories.typed_repo import reset_typed_in_memory_stores  # noqa: E402
from shared.store import reset_in_memory_stores as reset_shared_stores  # noqa: E402

SECRET_A = "whsec_opaque_secret_value_alpha_123"
SECRET_B = "ak_live_probe_secret_beta_456"
T1, T2 = "tenant-op-alpha", "tenant-op-beta"
P, E, S = "coinbase", "sandbox", "webhook_signing_secret"
APIKEY = "onramp_api_key"


def _reset() -> None:
    reset_in_memory_stores()
    reset_typed_in_memory_stores()
    reset_shared_stores()


@pytest.fixture(autouse=True)
def _autoreset():
    _reset()
    yield
    _reset()


def _secret_fields() -> tuple[str, ...]:
    return ("value", "encrypted_value", "encrypted_data_key", "secret", "plaintext")


# ── cross-tenant operator credential view: secrets never leak ──────────────

@pytest.mark.asyncio
async def test_collect_credential_slot_states_never_leaks_secrets():
    from services.providers.credentials.authority import CredentialAuthority
    from services.providers.credentials.operator_view import collect_credential_slot_states

    authority = CredentialAuthority()
    await authority.create_pending(T1, P, E, S, SECRET_A, created_by="operator")
    await authority.activate(T1, P, E, S, credential_version=1, actor="operator")
    await authority.create_pending(T2, P, E, APIKEY, SECRET_B, created_by="operator")

    result = await collect_credential_slot_states()
    assert result["tenant_count"] == 2
    assert result["slot_count"] == 2
    assert result["by_state"].get("active") == 1
    assert result["by_state"].get("pending") == 1

    blob = json.dumps(result)
    assert SECRET_A not in blob
    assert SECRET_B not in blob

    for item in result["items"]:
        assert item["tenant_id"] in (T1, T2)
        for view in item["slot_states"]:
            for forbidden in _secret_fields():
                assert forbidden not in view, f"secret field {forbidden!r} leaked in operator view"
            assert view["slot_name"] in (S, APIKEY)
            assert view["state"] in ("active", "pending")
            assert view["credential_version"] >= 1
            assert view["environment"] == "sandbox"
            assert "provider" in view


@pytest.mark.asyncio
async def test_collect_excludes_tombstoned_slots():
    from services.providers.credentials.authority import CredentialAuthority
    from services.providers.credentials.operator_view import collect_credential_slot_states

    authority = CredentialAuthority()
    await authority.create_pending(T1, P, E, S, SECRET_A, created_by="admin")
    await authority.activate(T1, P, E, S, credential_version=1, actor="admin")
    await authority.delete(T1, P, E, S, actor="admin")

    result = await collect_credential_slot_states()
    assert result["slot_count"] == 0
    assert result["tenant_count"] == 0
    assert result["by_state"] == {}


@pytest.mark.asyncio
async def test_tenant_credential_slot_states_groups_by_environment_and_state():
    from services.providers.credentials.authority import CredentialAuthority
    from services.providers.credentials.operator_view import tenant_credential_slot_states

    authority = CredentialAuthority()
    await authority.create_pending(T1, P, E, S, SECRET_A, created_by="admin")

    view = await tenant_credential_slot_states(T1)
    assert view["tenant_id"] == T1
    assert view["slot_count"] == 1
    assert view["by_state"].get("pending") == 1
    assert view["by_environment"]["sandbox"][0]["slot_name"] == S

    empty = await tenant_credential_slot_states("no-such-tenant")
    assert empty["slot_count"] == 0
    assert empty["by_state"] == {}
    assert empty["by_environment"] == {}
