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

import httpx
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


# ── SSRF protection (tenant-controlled rpc_endpoint_pair url) ─────────────
#
# These mock credential_authority.get_active_secret directly (rather than
# routing through the real create_pending/activate + Postgres-backed
# repository, which requires DATABASE_URL outside AETHER_ENV=local) so the
# resolver's URL validation is exercised in isolation, independent of the
# credential storage backend.


def _mock_getaddrinfo(ip: str):
    """Minimal getaddrinfo() response resolving to a single IP."""
    return [(2, 1, 6, "", (ip, 443))]


def _mock_active_secret(monkeypatch, url: str):
    from unittest.mock import AsyncMock

    from services.providers.credentials.authority import credential_authority

    doc = json.dumps({"url": url, "api_key": "key-v1", "auth_mode": "header"})
    monkeypatch.setattr(credential_authority, "get_active_secret", AsyncMock(return_value=doc))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "bad_ip",
    [
        "127.0.0.1",       # loopback
        "169.254.169.254",  # cloud metadata (link-local)
        "10.0.0.5",         # RFC1918
        "172.16.0.5",       # RFC1918
        "192.168.1.5",      # RFC1918
    ],
)
async def test_rpc_ssrf_private_address_rejected_outside_local(monkeypatch, bad_ip):
    """A deployed-env tenant RPC whose hostname resolves to a private/loopback/
    link-local address must be rejected (fail-closed), never handed to the
    x402 verifier for an outbound POST."""
    from unittest.mock import patch

    from services.x402.rpc_resolver import RpcUnavailableError, resolve_rpc

    tenant = f"t-{uuid.uuid4().hex[:8]}"
    _mock_active_secret(monkeypatch, "https://tenant-rpc.example.com")
    monkeypatch.setenv("AETHER_ENV", "staging")

    with patch("socket.getaddrinfo", return_value=_mock_getaddrinfo(bad_ip)):
        with pytest.raises(RpcUnavailableError):
            await resolve_rpc(tenant, "live", "eip155:8453")


@pytest.mark.asyncio
async def test_rpc_ssrf_http_scheme_rejected_outside_local(monkeypatch):
    """Non-HTTPS tenant RPC urls are rejected outside local/test, regardless
    of what the hostname resolves to."""
    from services.x402.rpc_resolver import RpcUnavailableError, resolve_rpc

    tenant = f"t-{uuid.uuid4().hex[:8]}"
    _mock_active_secret(monkeypatch, "http://tenant-rpc.example.com")
    monkeypatch.setenv("AETHER_ENV", "staging")

    with pytest.raises(RpcUnavailableError):
        await resolve_rpc(tenant, "live", "eip155:8453")


@pytest.mark.asyncio
async def test_rpc_valid_public_https_accepted_outside_local(monkeypatch):
    """A valid public HTTPS tenant RPC endpoint is accepted outside local/test."""
    from unittest.mock import patch

    from services.x402.rpc_resolver import resolve_rpc

    tenant = f"t-{uuid.uuid4().hex[:8]}"
    _mock_active_secret(monkeypatch, "https://tenant-rpc.example.com")
    monkeypatch.setenv("AETHER_ENV", "staging")

    with patch("socket.getaddrinfo", return_value=_mock_getaddrinfo("93.184.216.34")):
        resolved = await resolve_rpc(tenant, "live", "eip155:8453")
    assert resolved.url == "https://tenant-rpc.example.com"
    assert resolved.api_key == "key-v1"


@pytest.mark.asyncio
async def test_rpc_localhost_allowed_in_local(monkeypatch):
    """Loopback tenant RPC endpoints stay usable in local/test (the platform
    default RPC there may itself be loopback), with no DNS resolution
    performed."""
    from unittest.mock import patch

    from services.x402.rpc_resolver import resolve_rpc

    tenant = f"t-{uuid.uuid4().hex[:8]}"
    _mock_active_secret(monkeypatch, "http://127.0.0.1:8545")
    monkeypatch.setenv("AETHER_ENV", "local")

    with patch("socket.getaddrinfo", side_effect=AssertionError("DNS should not be resolved in local")):
        resolved = await resolve_rpc(tenant, "sandbox", "eip155:84532")
    assert resolved.url == "http://127.0.0.1:8545"


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


def test_terminal_vs_retryable_verdict_classification():
    """Only ``not_finalized`` / ``verification_unavailable`` are retryable —
    the chain never actually adjudicated the payment. Every other verdict
    (success, or a definitive on-chain failure) is terminal and safe to
    cache/idempotency-lock on."""
    from services.x402.verification import is_terminal_verdict

    assert is_terminal_verdict("not_finalized") is False
    assert is_terminal_verdict("verification_unavailable") is False

    assert is_terminal_verdict("verified") is True
    assert is_terminal_verdict("reverted") is True
    assert is_terminal_verdict("payer_mismatch") is True
    assert is_terminal_verdict("amount_below_required") is True
    assert is_terminal_verdict("no_matching_transfer") is True
    assert is_terminal_verdict("malformed") is True
    assert is_terminal_verdict("verification_failed") is True


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


# ── Multi-candidate transfer scan (batched/multicall payments) ────────────
#
# The EVM Transfer-log scan and the Solana instruction scan must examine
# EVERY candidate transfer to the recipient, not just the first one — a
# batched/multicall tx can carry several transfers to the same recipient,
# and only one of them needs to satisfy every predicate (payer + recipient +
# amount). These configure a real per-tenant RPC credential (as
# test_rpc_pair_resolves_atomically_from_authority does) and mock only the
# outbound httpx call, so the real _resolve_rpc → _verify_evm/_verify_solana
# code path runs end to end with no live network.

# keccak256("Transfer(address,address,uint256)") — copied from
# VerificationEngine._verify_evm so the crafted logs match exactly.
_TRANSFER_TOPIC = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"


def _topic_addr(addr: str) -> str:
    """Left-pad an address into a 32-byte log topic the same way
    VerificationEngine._verify_evm does."""
    return "0x" + addr.lower().lstrip("0x").zfill(64)


async def _configure_evm_rpc(tenant: str) -> None:
    from services.providers.credentials.authority import credential_authority

    doc = json.dumps({"url": "https://rpc.example.com", "api_key": "", "auth_mode": "none"})
    pending = await credential_authority.create_pending(
        tenant, "rpc_evm_base_sepolia", "sandbox", "rpc_endpoint_pair", doc, created_by="admin"
    )
    await credential_authority.activate(
        tenant, "rpc_evm_base_sepolia", "sandbox", "rpc_endpoint_pair",
        credential_version=int(pending["credential_version"]), actor="admin",
    )


def _patch_async_client(monkeypatch, transport: httpx.MockTransport) -> None:
    real_async_client = httpx.AsyncClient

    def _factory(*args, **kwargs):
        kwargs["transport"] = transport
        return real_async_client(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", _factory)


@pytest.mark.asyncio
async def test_verify_evm_scans_all_candidate_transfers_for_batched_payment(monkeypatch):
    """BUG FIX regression: a receipt whose FIRST candidate Transfer log is
    from an unauthorized wallet, followed by a SECOND Transfer log from the
    authorized payer with sufficient value, must verify successfully — the
    scan must not return on the first (bad) candidate."""
    from services.x402.commerce_models import PaymentAuthorization
    from services.x402.verification import _ASSET_CONTRACT, _expected_atomic, get_verification_engine

    tenant = f"t-{uuid.uuid4().hex[:8]}"
    await _configure_evm_rpc(tenant)

    recipient = "0x1111111111111111111111111111111111111111"
    authorized_payer = "0x2222222222222222222222222222222222222222"
    unauthorized_payer = "0x3333333333333333333333333333333333333333"
    contract = _ASSET_CONTRACT[("USDC", "eip155:84532")]
    expected_min = _expected_atomic(1.0, "USDC")

    bad_log = {
        "address": contract,
        "topics": [_TRANSFER_TOPIC, _topic_addr(unauthorized_payer), _topic_addr(recipient)],
        "data": hex(expected_min * 2),  # plenty of value, but from the wrong wallet
    }
    good_log = {
        "address": contract,
        "topics": [_TRANSFER_TOPIC, _topic_addr(authorized_payer), _topic_addr(recipient)],
        "data": hex(expected_min),
    }
    receipt_result = {"status": "0x1", "blockNumber": hex(98), "logs": [bad_log, good_log]}

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        method = body.get("method")
        if method == "eth_getTransactionReceipt":
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": receipt_result})
        if method == "eth_blockNumber":
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": 2, "result": hex(100)})
        raise AssertionError(f"unexpected RPC method {method!r}")

    _patch_async_client(monkeypatch, httpx.MockTransport(handler))

    engine = get_verification_engine()
    auth = PaymentAuthorization(
        tenant_id=tenant, challenge_id="c", approval_id="a", payment_identifier="p",
        amount_usd=1.0, asset_symbol="USDC", chain="eip155:84532", environment="sandbox",
        recipient=recipient, payer=authorized_payer, facilitator_id="f",
    )
    verified, error = await engine._verify_evm(auth, "0x" + "e" * 64)
    assert verified is True
    assert error is None


@pytest.mark.asyncio
async def test_verify_evm_reports_first_failure_when_no_candidate_matches(monkeypatch):
    """All-fail case: when NO candidate transfer satisfies every predicate,
    the original failure-reason semantics are preserved (the first
    non-matching candidate's reason is reported)."""
    from services.x402.commerce_models import PaymentAuthorization
    from services.x402.verification import _ASSET_CONTRACT, _expected_atomic, get_verification_engine

    tenant = f"t-{uuid.uuid4().hex[:8]}"
    await _configure_evm_rpc(tenant)

    recipient = "0x1111111111111111111111111111111111111111"
    authorized_payer = "0x2222222222222222222222222222222222222222"
    unauthorized_payer = "0x3333333333333333333333333333333333333333"
    contract = _ASSET_CONTRACT[("USDC", "eip155:84532")]
    expected_min = _expected_atomic(1.0, "USDC")

    bad_payer_log = {
        "address": contract,
        "topics": [_TRANSFER_TOPIC, _topic_addr(unauthorized_payer), _topic_addr(recipient)],
        "data": hex(expected_min * 2),
    }
    short_amount_log = {
        "address": contract,
        "topics": [_TRANSFER_TOPIC, _topic_addr(authorized_payer), _topic_addr(recipient)],
        "data": hex(expected_min - 1),
    }
    receipt_result = {
        "status": "0x1", "blockNumber": hex(98),
        "logs": [bad_payer_log, short_amount_log],
    }

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        method = body.get("method")
        if method == "eth_getTransactionReceipt":
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": receipt_result})
        if method == "eth_blockNumber":
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": 2, "result": hex(100)})
        raise AssertionError(f"unexpected RPC method {method!r}")

    _patch_async_client(monkeypatch, httpx.MockTransport(handler))

    engine = get_verification_engine()
    auth = PaymentAuthorization(
        tenant_id=tenant, challenge_id="c", approval_id="a", payment_identifier="p",
        amount_usd=1.0, asset_symbol="USDC", chain="eip155:84532", environment="sandbox",
        recipient=recipient, payer=authorized_payer, facilitator_id="f",
    )
    verified, error = await engine._verify_evm(auth, "0x" + "e" * 64)
    assert verified is False
    assert error.startswith("payer_mismatch")  # first candidate's failure reason


async def _configure_solana_rpc(tenant: str) -> None:
    from services.providers.credentials.authority import credential_authority

    doc = json.dumps({"url": "https://solana-rpc.example.com", "api_key": "", "auth_mode": "none"})
    pending = await credential_authority.create_pending(
        tenant, "rpc_svm_devnet", "sandbox", "rpc_endpoint_pair", doc, created_by="admin"
    )
    await credential_authority.activate(
        tenant, "rpc_svm_devnet", "sandbox", "rpc_endpoint_pair",
        credential_version=int(pending["credential_version"]), actor="admin",
    )


@pytest.mark.asyncio
async def test_verify_solana_scans_all_candidate_instructions_for_batched_payment(monkeypatch):
    """Same regression as the EVM case, for the Solana spl-token instruction
    scan: a first instruction from the wrong authority must not short-circuit
    a later instruction from the authorized payer."""
    from services.x402.commerce_models import PaymentAuthorization
    from services.x402.verification import _expected_atomic, get_verification_engine

    tenant = f"t-{uuid.uuid4().hex[:8]}"
    await _configure_solana_rpc(tenant)

    recipient = "RecipientTokenAccount1111111111111111111111"
    authorized_payer = "AuthorizedPayerAuthority111111111111111111"
    wrong_authority = "WrongAuthority111111111111111111111111111111"
    expected_min = _expected_atomic(1.0, "USDC")

    bad_ix = {
        "program": "spl-token",
        "parsed": {
            "type": "transfer",
            "info": {
                "destination": recipient,
                "authority": wrong_authority,
                "amount": str(expected_min * 2),
            },
        },
    }
    good_ix = {
        "program": "spl-token",
        "parsed": {
            "type": "transferChecked",
            "info": {
                "destination": recipient,
                "authority": authorized_payer,
                "tokenAmount": {"amount": str(expected_min)},
            },
        },
    }
    tx_result = {
        "meta": {"err": None, "innerInstructions": []},
        "transaction": {"message": {"instructions": [bad_ix, good_ix]}},
    }

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body.get("method") == "getTransaction"
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": tx_result})

    _patch_async_client(monkeypatch, httpx.MockTransport(handler))

    engine = get_verification_engine()
    auth = PaymentAuthorization(
        tenant_id=tenant, challenge_id="c", approval_id="a", payment_identifier="p",
        amount_usd=1.0, asset_symbol="USDC", chain="solana:devnet", environment="sandbox",
        recipient=recipient, payer=authorized_payer, facilitator_id="f",
    )
    verified, error = await engine._verify_solana(auth, "5" + "1" * 60)
    assert verified is True
    assert error is None
