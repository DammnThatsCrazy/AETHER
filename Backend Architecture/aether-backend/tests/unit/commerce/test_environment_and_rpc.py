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


def test_rpc_provider_resolved_by_chain_not_environment():
    """r812: the RPC provider is chosen from the explicit chain identifier, not
    the credential environment. A sandbox authorization that still names Base
    *mainnet* must resolve the mainnet provider (so verification hits mainnet
    USDC on a mainnet RPC), never Base Sepolia."""
    from services.x402.credential_slots import rpc_provider_for_chain

    # Chain string wins regardless of environment.
    assert rpc_provider_for_chain("eip155:8453", "sandbox") == "rpc_evm_base"
    assert rpc_provider_for_chain("eip155:8453", "live") == "rpc_evm_base"
    assert rpc_provider_for_chain("eip155:84532", "live") == "rpc_evm_base_sepolia"
    assert rpc_provider_for_chain("eip155:84532", "sandbox") == "rpc_evm_base_sepolia"
    assert rpc_provider_for_chain("solana:mainnet", "sandbox") == "rpc_svm_mainnet"
    assert rpc_provider_for_chain("solana:devnet", "live") == "rpc_svm_devnet"
    # Unknown chain → fail-closed None.
    assert rpc_provider_for_chain("eip155:999999", "live") is None
    # environment is optional.
    assert rpc_provider_for_chain("eip155:8453") == "rpc_evm_base"


@pytest.mark.asyncio
async def test_reconciliation_per_env_skip_and_terminal_verdict_fail(monkeypatch):
    """r795 + N12: the reconciliation kill switch is per settlement environment
    (suspending sandbox must not halt live), and a terminal verdict fails the
    settlement instead of leaving it PENDING forever."""
    from services.x402.reconciliation import X402ReconciliationWorker

    class _S:  # minimal settlement stub
        def __init__(self, sid, env, tx):
            self.settlement_id = sid
            self.environment = env
            self.receipt_id = f"rc-{sid}"
            self.tx_hash = tx

    class _Auth:
        authorization_id = "a1"

    sandbox_s = _S("s-sandbox", "sandbox", "0x1")
    live_terminal = _S("s-live-term", "live", "0x2")
    live_retryable = _S("s-live-retry", "live", "0x3")

    worker = X402ReconciliationWorker()

    class _Store:
        async def list_settlements(self, tenant_id, state=None):
            return [sandbox_s, live_terminal, live_retryable]

        async def get_receipt(self, tenant_id, rid):
            return type("R", (), {"authorization_id": "a1"})()

        async def get_authorization(self, tenant_id, aid):
            return _Auth()

    verdicts = {
        "0x2": (False, "no_matching_transfer: no transfer to recipient"),  # terminal
        "0x3": (False, "not_finalized: 1/2 confirmations"),                # retryable
    }

    class _Verify:
        async def _verify_locally(self, auth, tx):
            return verdicts[tx]

    failed_ids = []
    settled_ids = []

    class _Tracker:
        async def fail(self, tenant_id, sid, err):
            failed_ids.append(sid)

        async def mark_settled_reconciled(self, tenant_id, sid):
            settled_ids.append(sid)

    worker._store = _Store()
    worker._verify = _Verify()
    worker._tracker = _Tracker()

    async def _susp(tenant_id, environment):
        return environment == "sandbox"  # only sandbox suspended

    monkeypatch.setattr(worker, "_capability_suspended", _susp)
    monkeypatch.setattr(worker, "_write_cursor", lambda *a, **k: _noop())

    result = await worker.reconcile_tenant("t_recon")

    assert result["skipped"] == 1          # sandbox settlement skipped
    assert live_terminal.settlement_id in failed_ids  # terminal verdict → failed
    assert result["failed"] == 1
    assert result["still_pending"] == 1    # retryable live settlement stays pending


async def _noop():
    return None


@pytest.mark.asyncio
async def test_facilitator_missing_credential_falls_through_to_rpc():
    """r791: a facilitator that declares a credential slot but has no configured
    key must hand off to on-chain RPC verification (return False, None) instead
    of firing an unauthenticated request that fails terminally."""
    from services.x402.verification import get_verification_engine
    from services.x402.commerce_models import (
        Facilitator, FacilitatorMode, PaymentAuthorization,
    )

    engine = get_verification_engine()
    fac = Facilitator(
        facilitator_id="fac_circle_v2", name="Circle",
        endpoint_url="https://facilitator.example/v2", mode=FacilitatorMode.FACILITATOR,
        supported_assets=["USDC"], supported_chains=["eip155:8453"],
        credential_slot="facilitator_api_key",
    )
    auth = PaymentAuthorization(
        tenant_id="t_fac", challenge_id="c", approval_id="a", payment_identifier="p",
        amount_usd=1.0, asset_symbol="USDC", chain="eip155:8453", recipient="0xrecipient",
        payer="0xpayer", facilitator_id="fac_circle_v2", environment="sandbox",
    )
    verified, error = await engine._verify_via_facilitator("t_fac", fac, auth, "0x" + "a" * 64)
    assert verified is False and error is None  # → verify() falls through to RPC


@pytest.mark.asyncio
async def test_facilitator_credential_attached_as_bearer(monkeypatch):
    """r791: a configured facilitator credential is attached as a bearer token
    on the verification request."""
    import httpx

    from services.x402.verification import get_verification_engine
    from services.x402.commerce_models import (
        Facilitator, FacilitatorMode, PaymentAuthorization,
    )

    async def _key(tenant_id, provider, environment, slot):
        assert provider == "fac_circle_v2" and slot == "facilitator_api_key"
        return "sk_fac_test_123"

    monkeypatch.setattr(
        "services.providers.credentials.authority.credential_authority.get_active_secret",
        _key,
    )

    seen = {}

    class _Resp:
        status_code = 200

        def json(self):
            return {"isValid": True}

    class _Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, json=None, headers=None):
            seen["headers"] = headers or {}
            return _Resp()

    monkeypatch.setattr(httpx, "AsyncClient", _Client)

    engine = get_verification_engine()
    fac = Facilitator(
        facilitator_id="fac_circle_v2", name="Circle",
        endpoint_url="https://facilitator.example/v2", mode=FacilitatorMode.FACILITATOR,
        supported_assets=["USDC"], supported_chains=["eip155:8453"],
        credential_slot="facilitator_api_key",
    )
    auth = PaymentAuthorization(
        tenant_id="t_fac2", challenge_id="c", approval_id="a", payment_identifier="p2",
        amount_usd=1.0, asset_symbol="USDC", chain="eip155:8453", recipient="0xrecipient",
        payer="0xpayer", facilitator_id="fac_circle_v2", environment="sandbox",
    )
    verified, error = await engine._verify_via_facilitator("t_fac2", fac, auth, "0x" + "a" * 64)
    assert verified is True
    assert seen["headers"].get("Authorization") == "Bearer sk_fac_test_123"


def test_facilitator_transport_failures_map_to_retryable_verdict():
    """N22: facilitator 5xx / timeout / unreachable must yield a
    verification_unavailable (retryable) verdict, not a terminal
    verification_failed that verify_and_settle caches for 24h."""
    from services.x402.verification import _verdict_token, is_terminal_verdict

    for msg in (
        "verification_unavailable: facilitator returned HTTP 503",
        "verification_unavailable: facilitator fac_x timed out",
        "verification_unavailable: facilitator unreachable: conn refused",
    ):
        assert _verdict_token(msg) == "verification_unavailable"
        assert is_terminal_verdict(_verdict_token(msg)) is False
    # A definitive 4xx stays terminal.
    assert is_terminal_verdict(_verdict_token("facilitator returned HTTP 400")) is True


def test_receipt_id_is_deterministic_per_authorization():
    """N16: the receipt id is derived from (tenant, authorization) so a
    re-verification upserts the same receipt row instead of colliding on the
    commerce_receipts (tenant_id, authorization_id) unique index."""
    from services.x402.verification import _receipt_id_for

    a = _receipt_id_for("t1", "auth-1")
    assert a == _receipt_id_for("t1", "auth-1")            # stable
    assert a != _receipt_id_for("t1", "auth-2")            # per-authorization
    assert a != _receipt_id_for("t2", "auth-1")            # per-tenant
    assert a.startswith("rcpt_")


@pytest.mark.asyncio
async def test_reconciliation_keeps_settlement_pending_when_mint_fails(monkeypatch):
    """N17: if the entitlement mint fails after verification, the settlement
    must stay PENDING (retried next tick), never SETTLED-without-entitlement."""
    import services.x402.control_plane as cp_mod
    from services.x402.reconciliation import X402ReconciliationWorker

    class _S:
        settlement_id = "s-mintfail"
        environment = "sandbox"
        receipt_id = "rc"
        tx_hash = "0x9"

    class _Store:
        async def list_settlements(self, tenant_id, state=None):
            return [_S()]

        async def get_receipt(self, tenant_id, rid):
            return type("R", (), {"authorization_id": "a1"})()

        async def get_authorization(self, tenant_id, aid):
            return type("A", (), {"authorization_id": "a1"})()

    class _Verify:
        async def _verify_locally(self, auth, tx):
            return True, None  # verified

    marked = {"settled": False}

    class _Tracker:
        async def mark_settled_reconciled(self, tenant_id, sid):
            marked["settled"] = True

    class _FailingPlane:
        async def mint_entitlement_for_reconciled_settlement(self, tenant_id, settlement):
            raise RuntimeError("transient mint outage")

    monkeypatch.setattr(cp_mod, "get_control_plane", lambda: _FailingPlane())

    worker = X402ReconciliationWorker()
    worker._store = _Store()
    worker._verify = _Verify()
    worker._tracker = _Tracker()
    monkeypatch.setattr(worker, "_capability_suspended", lambda t, e: _false())
    monkeypatch.setattr(worker, "_write_cursor", lambda *a, **k: _none())

    result = await worker.reconcile_tenant("t-mintfail")
    assert result["settled"] == 0
    assert result["still_pending"] == 1
    assert marked["settled"] is False  # settlement never flipped to SETTLED


async def _false():
    return False


async def _none():
    return None
