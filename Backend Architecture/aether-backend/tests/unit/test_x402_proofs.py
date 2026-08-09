"""
Unit tests for x402 on-chain payment verification (mocked RPC, no live network).

These drive the private ``_verify_evm`` / ``_verify_solana`` RPC verification
paths directly — NOT ``verify()`` — so the local-mode short-circuit
(``_verify_locally`` returning ``(True, None)`` when AETHER_ENV=local) is never
hit and the JSON-RPC decode/mapping logic is exercised end to end against fake
``eth_getTransactionReceipt`` / ``getTransaction`` payloads.

The fake RPC client injects canned JSON-RPC responses by patching
``services.x402.verification.httpx.AsyncClient``. Nothing touches the network.
"""

from __future__ import annotations

import asyncio
import os
import sys
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

os.environ.setdefault("AETHER_ENV", "local")

from services.x402.commerce_models import PaymentAuthorization
from services.x402.verification import VerificationEngine

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


class _FakeRPCClient:
    """AsyncClient stand-in that answers JSON-RPC calls from a canned map."""

    def __init__(self, responder):
        self._responder = responder  # callable(method, params) -> jsonrpc result dict
        self.calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, url, json=None):
        self.calls.append(json)
        method = json["method"]
        params = json["params"]
        return _FakeResponse(self._responder(method, params))


def _fake_rpc(responder):
    """Context manager patching httpx.AsyncClient inside the verification module."""
    return patch("services.x402.verification.httpx.AsyncClient",
                 return_value=_FakeRPCClient(responder))


# ── EVM verification ────────────────────────────────────────────────────────

def test_verify_evm_success():
    auth = _evm_auth(5.0)
    recipient_padded = "0x" + EVM_RECIPIENT.lower().lstrip("0x").zfill(64)

    def responder(method, params):
        assert method == "eth_getTransactionReceipt"
        assert params == [params[0]] or params[0]
        return {"result": {
            "status": "0x1",
            "logs": [{
                "address": BASE_USDC,
                "topics": [TRANSFER_TOPIC, "0x" + "1" * 64, recipient_padded],
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
        return {"result": {
            "status": "0x1",
            "logs": [{
                "address": BASE_USDC,
                "topics": [TRANSFER_TOPIC, "0x" + "1" * 64, recipient_padded],
                "data": hex(100),  # $0.0001 — well below the $5.00 required
            }],
        }}

    with _fake_rpc(responder):
        ok, error = _run(_engine()._verify_evm(auth, "0x" + "d" * 64))
    assert ok is False
    assert "below required" in error


def test_verify_evm_no_matching_log():
    auth = _evm_auth(5.0)

    def responder(method, params):
        return {"result": {"status": "0x1", "logs": []}}

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

    def responder(method, params):
        raise AssertionError("network call attempted")  # pragma: no cover

    class _TimeoutClient(_FakeRPCClient):
        async def post(self, url, json=None):
            import httpx
            raise httpx.TimeoutException("timeout")

    with patch("services.x402.verification.httpx.AsyncClient", return_value=_TimeoutClient(responder)):
        ok, error = _run(_engine()._verify_solana(auth, "5FakeBase58TxHash1" * 3))
    assert ok is False
    assert "timeout" in error
