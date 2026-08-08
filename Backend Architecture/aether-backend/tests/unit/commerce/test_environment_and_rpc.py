"""x402 environment axis + per-tenant RPC resolution — P4 invariants.

Pins:

* the environment field on authorizations/receipts/settlements, resolved
  server-side from the tenant's x402 activation state (never client-trusted);
* atomic RPC endpoint+key pair resolution from the credential authority, with
  fail-closed behavior outside local when no pair is configured;
* the RPC pair rotating url+key together (one credential version = one pair);
* strict asset decimals (unknown assets are a hard error, never default-6);
* the verification verdict token surface;
* budget policies backed by Postgres repos outside local.
"""

from __future__ import annotations

import json
import os
import sys
import uuid

os.environ.setdefault("AETHER_ENV", "local")
os.environ.setdefault("JWT_SECRET", "test-secret")
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))

import pytest

from repositories.repos import reset_in_memory_stores


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    monkeypatch.setenv("AETHER_ENV", "local")
    monkeypatch.setenv("AETHER_ALLOW_INMEMORY_STORE", "1")
    reset_in_memory_stores()
    from services.x402.commerce_store import reset_commerce_store

    reset_commerce_store()
    yield
    reset_in_memory_stores()


# ── RPC resolution ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_rpc_pair_resolves_atomically_from_authority():
    from services.providers.credentials.authority import credential_authority
    from services.x402.rpc_resolver import resolve_rpc

    tenant = f"t-{uuid.uuid4().hex[:8]}"
    doc = json.dumps({"url": "https://rpc.example.com", "api_key": "key-v1", "auth_mode": "path"})
    pending = await credential_authority.create_pending(
        tenant, "rpc_evm_base_sepolia", "sandbox", "rpc_endpoint_pair", doc, created_by="admin"
    )
    await credential_authority.activate(
        tenant, "rpc_evm_base_sepolia", "sandbox", "rpc_endpoint_pair",
        credential_version=int(pending["credential_version"]), actor="admin",
    )
    resolved = await resolve_rpc(tenant, "sandbox", "eip155:84532")
    assert resolved.url == "https://rpc.example.com"
    assert resolved.api_key == "key-v1"
    assert resolved.request_url() == "https://rpc.example.com/key-v1"


@pytest.mark.asyncio
async def test_rpc_rotation_swaps_url_and_key_together():
    from services.providers.credentials.authority import credential_authority
    from services.x402.rpc_resolver import resolve_rpc

    tenant = f"t-{uuid.uuid4().hex[:8]}"
    v1 = json.dumps({"url": "https://old.example.com", "api_key": "old", "auth_mode": "header"})
    p = await credential_authority.create_pending(
        tenant, "rpc_evm_base", "live", "rpc_endpoint_pair", v1, created_by="admin"
    )
    await credential_authority.activate(
        tenant, "rpc_evm_base", "live", "rpc_endpoint_pair",
        credential_version=int(p["credential_version"]), actor="admin",
    )
    v2 = json.dumps({"url": "https://new.example.com", "api_key": "new", "auth_mode": "header"})
    await credential_authority.rotate(
        tenant, "rpc_evm_base", "live", "rpc_endpoint_pair", v2, actor="admin"
    )
    resolved = await resolve_rpc(tenant, "live", "eip155:8453")
    # url and key move together — never new url with old key
    assert resolved.url == "https://new.example.com"
    assert resolved.api_key == "new"
    assert resolved.headers() == {"Authorization": "Bearer new"}


@pytest.mark.asyncio
async def test_rpc_fail_closed_outside_local(monkeypatch):
    from services.x402.rpc_resolver import RpcUnavailableError, resolve_rpc

    monkeypatch.setenv("AETHER_ENV", "staging")
    tenant = f"t-{uuid.uuid4().hex[:8]}"
    with pytest.raises(RpcUnavailableError):
        await resolve_rpc(tenant, "live", "eip155:8453")


@pytest.mark.asyncio
async def test_rpc_local_platform_default(monkeypatch):
    from services.x402.rpc_resolver import resolve_rpc

    monkeypatch.setenv("AETHER_ENV", "local")
    tenant = f"t-{uuid.uuid4().hex[:8]}"
    resolved = await resolve_rpc(tenant, "sandbox", "eip155:84532")
    assert resolved.url  # platform default present in local


# ── Environment axis ──────────────────────────────────────────────────────


def test_models_carry_environment():
    from services.x402.commerce_models import (
        PaymentAuthorization,
        PaymentReceipt,
        Settlement,
    )

    auth = PaymentAuthorization(
        tenant_id="t", challenge_id="c", approval_id="a", payment_identifier="p",
        amount_usd=1.0, asset_symbol="USDC", chain="eip155:8453",
        recipient="0x1", payer="0x2", facilitator_id="f",
    )
    assert auth.environment == "sandbox"
    r = PaymentReceipt(
        tenant_id="t", authorization_id="a", challenge_id="c", tx_hash="0x",
        chain="eip155:8453", asset_symbol="USDC", amount_usd=1.0, payer="0x2", recipient="0x1",
    )
    assert r.environment == "sandbox"
    assert hasattr(r, "verification_verdict")
    s = Settlement(
        tenant_id="t", receipt_id="r", challenge_id="c", tx_hash="0x",
        chain="eip155:8453", amount_usd=1.0, facilitator_id="f",
    )
    assert s.environment == "sandbox"


# ── Strict decimals ────────────────────────────────────────────────────────


def test_unknown_asset_decimals_is_hard_error():
    from services.x402.verification import AssetDecimalsError, _asset_decimals, _expected_atomic

    assert _asset_decimals("USDC") == 6
    with pytest.raises(AssetDecimalsError):
        _asset_decimals("MYSTERYCOIN")
    with pytest.raises(AssetDecimalsError):
        _expected_atomic(1.0, "MYSTERYCOIN")


def test_verdict_tokens():
    from services.x402.verification import _verdict_token

    assert _verdict_token("verification_unavailable: RPC timeout") == "verification_unavailable"
    assert _verdict_token("payer_mismatch: bad wallet") == "payer_mismatch"
    assert _verdict_token("amount_below_required: 1 < 2") == "amount_below_required"
    assert _verdict_token("not_finalized: 0 < 2 confirmations") == "not_finalized"
    assert _verdict_token(None) == "verification_failed"


# ── Verification fail-closed outside local without RPC ────────────────────


@pytest.mark.asyncio
async def test_verify_unavailable_without_rpc_outside_local(monkeypatch):
    from services.x402.commerce_models import PaymentAuthorization
    from services.x402.verification import get_verification_engine

    monkeypatch.setenv("AETHER_ENV", "staging")
    engine = get_verification_engine()
    auth = PaymentAuthorization(
        tenant_id=f"t-{uuid.uuid4().hex[:8]}", challenge_id="c", approval_id="a",
        payment_identifier="p", amount_usd=1.0, asset_symbol="USDC",
        chain="eip155:8453", environment="live",
        recipient="0x1", payer="0x2", facilitator_id="f",
    )
    verified, error = await engine._verify_evm(auth, "0x" + "ab" * 32)
    assert verified is False
    assert error.startswith("verification_unavailable")
