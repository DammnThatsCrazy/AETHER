"""
Unit tests for x402 on-chain payment verification (mocked RPC, no live network).

These drive the private ``_verify_evm`` / ``_verify_solana`` RPC verification
paths directly — NOT ``verify()`` — so the local-mode short-circuit
(``_verify_locally`` returning ``(True, None)`` when AETHER_ENV=local) is never
hit and the JSON-RPC decode/mapping logic is exercised end to end against fake
``eth_getTransactionReceipt`` / ``getTransaction`` payloads.

The fake RPC sender injects canned JSON-RPC responses by patching
``value.x402.verification.send_public_request``. Nothing touches the network.
"""

from __future__ import annotations

import asyncio
import os
import sys
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

os.environ.setdefault("AETHER_ENV", "local")

from value.x402.commerce_models import PaymentAuthorization
from value.x402.verification import VerificationEngine

TRANSFER_TOPIC = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
BASE_USDC = "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913"  # lowercase
SOLANA_USDC = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"

EVM_RECIPIENT = "0x1234567890abcdef1234567890abcdef12345678"
SOLANA_RECIPIENT = "RecipientSolanaWallet111111111111111111111111111"


def _run(coro):
    # These sync tests may run in the same process as pytest-asyncio async tests
    # (auto mode), which tears down its event loop between tests — so the
    # main-thread loop may not exist here. Create one rather than raising.
    try:
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            raise RuntimeError
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop.run_until_complete(coro)


def _evm_auth(amount_usd: float = 5.0) -> PaymentAuthorization:
    return PaymentAuthorization(
        tenant_id="tenant_test",
        challenge_id="chg_evm",
        approval_id="appr_evm",
        payment_identifier="pi_evm",
        amount_usd=amount_usd,
        asset_symbol="USDC",
        chain="eip155:8453",
        recipient=EVM_RECIPIENT,
        payer="0x1111111111111111111111111111111111111111",
        facilitator_id="fac_test",
    )


def _solana_auth(amount_usd: float = 5.0) -> PaymentAuthorization:
    return PaymentAuthorization(
        tenant_id="tenant_test",
        challenge_id="chg_svm",
        approval_id="appr_svm",
        payment_identifier="pi_svm",
        amount_usd=amount_usd,
        asset_symbol="USDC",
        chain="solana:mainnet",
        recipient=SOLANA_RECIPIENT,
        payer="PayerSolanaWallet111111111111111111111111111",
        facilitator_id="fac_test",
    )


def _engine() -> VerificationEngine:
    """Construct the engine without __init__ (no store/facilitator singletons)."""
    return VerificationEngine.__new__(VerificationEngine)


class _FakeResponse:
    def __init__(self, data):
        self._data = data

    def raise_for_status(self):
        return None

    def json(self):
        return self._data


def _fake_rpc(responder):
    """Patch the verifier's outbound sender to answer JSON-RPC calls from *responder*."""

    async def send(method, url, *, json=None, **_kwargs):
        # The EVM verifier makes a second JSON-RPC call for the current block
        # height to enforce finality. Answer a sufficiently confirmed head so
        # the receipt result drives the verdict.
        if json["method"] == "eth_blockNumber":
            return _FakeResponse({"result": "0x10"})
        return _FakeResponse(responder(json["method"], json["params"]))

    return patch("value.x402.verification.send_public_request", side_effect=send)


# ── EVM verification ────────────────────────────────────────────────────────

def test_verify_evm_success():
    auth = _evm_auth(5.0)
    recipient_padded = "0x" + EVM_RECIPIENT.lower().lstrip("0x").zfill(64)

    def responder(method, params):
        assert method == "eth_getTransactionReceipt"
        assert params == [params[0]] or params[0]
        # main's verifier binds the Transfer's `from` (topics[1]) to the
        # authorized payer — emit the correctly-padded payer topic.
        payer_padded = "0x" + auth.payer.lower().lstrip("0x").zfill(64)
        return {"result": {
            "status": "0x1",
            # main's verifier enforces finality vs the current head — give the
            # receipt a mined block so confirmations are satisfied.
            "blockNumber": "0x1",
            "logs": [{
                "address": BASE_USDC,
                "topics": [TRANSFER_TOPIC, payer_padded, recipient_padded],
                "data": hex(5_000_000),
            }],
        }}

    with _fake_rpc(responder):
        ok, error = _run(_engine()._verify_evm(auth, "0x" + "a" * 64))
    assert ok is True
    assert error is None


def test_verify_evm_tx_not_found():
    auth = _evm_auth(5.0)

    def responder(method, params):
        return {"result": None}

    with _fake_rpc(responder):
        ok, error = _run(_engine()._verify_evm(auth, "0x" + "b" * 64))
    assert ok is False
    assert "not found" in error


def test_verify_evm_reverted():
    auth = _evm_auth(5.0)

    def responder(method, params):
        return {"result": {"status": "0x0", "logs": []}}

    with _fake_rpc(responder):
        ok, error = _run(_engine()._verify_evm(auth, "0x" + "c" * 64))
    assert ok is False
    assert "reverted" in error


def test_verify_evm_amount_below_required():
    auth = _evm_auth(5.0)
    recipient_padded = "0x" + EVM_RECIPIENT.lower().lstrip("0x").zfill(64)

    def responder(method, params):
        # main's verifier binds the Transfer's `from` (topics[1]) to the
        # authorized payer — emit the correctly-padded payer topic.
        payer_padded = "0x" + auth.payer.lower().lstrip("0x").zfill(64)
        return {"result": {
            "status": "0x1",
            "blockNumber": "0x1",
            "logs": [{
                "address": BASE_USDC,
                "topics": [TRANSFER_TOPIC, payer_padded, recipient_padded],
                "data": hex(100),  # $0.0001 — well below the $5.00 required
            }],
        }}

    with _fake_rpc(responder):
        ok, error = _run(_engine()._verify_evm(auth, "0x" + "d" * 64))
    assert ok is False
    # main's canonical semantic verdict token is amount_below_required.
    assert "amount_below_required" in error


def test_verify_evm_no_matching_log():
    auth = _evm_auth(5.0)

    def responder(method, params):
        return {"result": {"status": "0x1", "blockNumber": "0x1", "logs": []}}

    with _fake_rpc(responder):
        ok, error = _run(_engine()._verify_evm(auth, "0x" + "e" * 64))
    assert ok is False
    assert "no matching" in error


def test_verify_evm_unknown_asset_contract():
    auth = _evm_auth(5.0)
    auth = auth.model_copy(update={"asset_symbol": "FOO"})
    ok, error = _run(_engine()._verify_evm(auth, "0x" + "f" * 64))
    assert ok is False
    assert "no contract" in error


# ── Solana verification ─────────────────────────────────────────────────────

def test_verify_solana_success():
    auth = _solana_auth(5.0)

    def responder(method, params):
        assert method == "getTransaction"
        return {"result": {
            "meta": {"err": None, "innerInstructions": []},
            "transaction": {"message": {"instructions": [
                {
                    "program": "spl-token",
                    "parsed": {
                        "type": "transfer",
                        "info": {
                            "destination": SOLANA_RECIPIENT,
                            "mint": SOLANA_USDC,
                            "amount": "5000000",
                        },
                    },
                },
            ]}},
        }}

    with _fake_rpc(responder):
        ok, error = _run(_engine()._verify_solana(auth, "5FakeBase58TxHash1" * 3))
    assert ok is True
    assert error is None


def test_verify_solana_tx_failed_on_chain():
    auth = _solana_auth(5.0)

    def responder(method, params):
        return {"result": {"meta": {"err": {"InstructionError": [0, 1]}}, "transaction": {"message": {"instructions": []}}}}

    with _fake_rpc(responder):
        ok, error = _run(_engine()._verify_solana(auth, "5FakeBase58TxHash1" * 3))
    assert ok is False
    assert "failed on-chain" in error


def test_verify_solana_no_matching_transfer():
    auth = _solana_auth(5.0)

    def responder(method, params):
        return {"result": {
            "meta": {"err": None, "innerInstructions": []},
            "transaction": {"message": {"instructions": [
                {"program": "system", "parsed": {"type": "transfer", "info": {}}},
            ]}},
        }}

    with _fake_rpc(responder):
        ok, error = _run(_engine()._verify_solana(auth, "5FakeBase58TxHash1" * 3))
    assert ok is False
    assert "no matching" in error


def test_verify_solana_wrong_mint():
    auth = _solana_auth(5.0)

    def responder(method, params):
        return {"result": {
            "meta": {"err": None, "innerInstructions": []},
            "transaction": {"message": {"instructions": [
                {
                    "program": "spl-token",
                    "parsed": {
                        "type": "transfer",
                        "info": {
                            "destination": SOLANA_RECIPIENT,
                            "mint": "So11111111111111111111111111111111111111112",  # wSOL
                            "amount": "5000000",
                        },
                    },
                },
            ]}},
        }}

    with _fake_rpc(responder):
        ok, error = _run(_engine()._verify_solana(auth, "5FakeBase58TxHash1" * 3))
    assert ok is False
    assert "no matching" in error


def test_verify_solana_transfer_in_inner_instructions():
    """An spl-token transfer nested in innerInstructions is still a match."""
    auth = _solana_auth(5.0)

    def responder(method, params):
        return {"result": {
            "meta": {
                "err": None,
                "innerInstructions": [{
                    "instructions": [{
                        "program": "spl-token",
                        "parsed": {
                            "type": "transferChecked",
                            "info": {
                                "destination": SOLANA_RECIPIENT,
                                "mint": SOLANA_USDC,
                                "tokenAmount": {"amount": "5000000"},
                            },
                        },
                    }],
                }],
            },
            "transaction": {"message": {"instructions": [
                {"program": "system", "parsed": {}},
            ]}},
        }}

    with _fake_rpc(responder):
        ok, error = _run(_engine()._verify_solana(auth, "5FakeBase58TxHash1" * 3))
    assert ok is True
    assert error is None


def test_verify_solana_rpc_timeout_is_honest_failure():
    auth = _solana_auth(5.0)

    import httpx

    with patch("value.x402.verification.send_public_request", side_effect=httpx.TimeoutException("timeout")):
        ok, error = _run(_engine()._verify_solana(auth, "5FakeBase58TxHash1" * 3))
    assert ok is False
    assert "timeout" in error


@pytest.mark.parametrize("verify, auth", [("_verify_evm", _evm_auth), ("_verify_solana", _solana_auth)])
def test_verify_rpc_resolution_failure_is_unavailable_not_refused(verify, auth):
    from shared.security.ssrf import DestinationResolutionError

    failure = DestinationResolutionError("DNS resolution failed for 'rpc.example'")
    with patch("value.x402.verification.send_public_request", side_effect=failure):
        ok, error = _run(getattr(_engine(), verify)(auth(5.0), "5FakeBase58TxHash1" * 3))
    assert ok is False
    assert error.startswith("verification_unavailable:")
    assert "could not be resolved" in error
    assert "not a public address" not in error
