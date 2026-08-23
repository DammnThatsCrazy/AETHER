"""
Unit tests for the SVM (Solana) onchain_claim rail wiring.

Covers the SVM branch of ``OnchainClaimAdapter``:
    - validate_config accepts svm with a program_id and rejects unsupported VMs
    - build_action_payload emits a proof_format="svm" payload with a base58
      program_id, base58 signer address, SHA-256 message hash, and the
      Anchor-program instruction copy
    - asset conversion still uses EXPLICIT decimals (never 18) for svm

NOTE: the real-crypto signing path of ``MultiChainSigner`` currently breaks on
eth-account 0.13 (``BaseProofSigner._sign`` still calls the removed
``Account.signHash`` — the canonical ``OracleProofSigner`` already uses
``Account.unsafe_sign_hash``). That regression lives in services/oracle/ and is
out of scope here. To exercise the SVM wiring end to end without the network or
the broken primitive, these tests force the local HMAC fallback
(``REAL_CRYPTO_AVAILABLE = False``), which is exactly the signing path local dev
uses when eth-account is absent.
"""

from __future__ import annotations

import asyncio
import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

os.environ.setdefault("AETHER_ENV", "local")

from services.rewards.policy_engine import PolicyDecision
from services.rewards.rails import OnchainClaimAdapter

SVM_PROGRAM = "AetherRwd1111111111111111111111111111111111"
SVM_RECIPIENT = "SolanaRecipientPubkey111111111111111111111111111"


def _run(coro):
    # Same-process coexistence with pytest-asyncio auto-mode async tests: its loop
    # is torn down between tests, so the main-thread loop may not exist here.
    try:
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            raise RuntimeError
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop.run_until_complete(coro)


def _svm_decision() -> PolicyDecision:
    return PolicyDecision(
        eligible=True,
        decision="eligible",
        campaign_id="camp-svm",
        rule_id="rule-svm",
        rail="onchain_claim",
        reward={"amount": "10.0", "unit": "USD", "currency": "USD"},
        identity={"user_id": "user_svm", "wallet_address": SVM_RECIPIENT},
    )


def _svm_rule() -> dict:
    return {"id": "rule-svm", "name": "Test Rule", "reward_amount": 10.0, "asset_decimals": 6}


def _svm_campaign() -> dict:
    return {
        "id": "camp-svm",
        "name": "Test Campaign",
        "vm_type": "svm",
        "program_id": SVM_PROGRAM,
        "chain_id": 101,
    }


@pytest.fixture()
def _hmac_fallback(monkeypatch):
    """Force the HMAC signing fallback (bypasses the pre-existing eth-account
    0.13 signHash regression in services/oracle/base_signer.py)."""
    import services.oracle.base_signer as bs
    monkeypatch.setattr(bs, "REAL_CRYPTO_AVAILABLE", False)


def test_svm_validate_config_accepts_program_id(_hmac_fallback):
    adapter = OnchainClaimAdapter()
    errors = adapter.validate_config({
        "vm_type": "svm",
        "chain_id": 101,
        "program_id": SVM_PROGRAM,
        "oracle_signer_key": "x",
    })
    assert errors == []


def test_svm_validate_config_requires_program_id(_hmac_fallback):
    adapter = OnchainClaimAdapter()
    errors = adapter.validate_config({
        "vm_type": "svm",
        "chain_id": 101,
        "oracle_signer_key": "x",
    })
    assert any("program_id" in e for e in errors)


def test_svm_validate_config_rejects_unsupported_vm(_hmac_fallback):
    adapter = OnchainClaimAdapter()
    errors = adapter.validate_config({
        "vm_type": "bitcoin",
        "chain_id": 0,
        "oracle_signer_key": "x",
    })
    assert any("not wired" in e for e in errors)


def test_svm_build_action_payload_shapes_svm_proof(_hmac_fallback):
    adapter = OnchainClaimAdapter()
    payload = _run(adapter.build_action_payload(
        _svm_decision(), _svm_rule(), _svm_campaign(), "tenant_svm_test"
    ))
    assert payload["vm_type"] == "svm"
    assert payload["execution_mode"] == "onchain_claim"
    assert payload["status"] == "ready"

    proof = payload["proof"]
    assert proof["proof_format"] == "svm"
    assert proof["program_id"] == SVM_PROGRAM
    assert proof["contract_address"] == SVM_PROGRAM
    assert proof["vm_type"] == "svm"
    assert proof["user"] == SVM_RECIPIENT
    # SVM signer address is base58 (not 0x-prefixed).
    assert proof["signer_address"].startswith("0x") is False
    assert proof["nonce"] and proof["signature"] and proof["message_hash"]

    assert payload["payload"]["type"] == "onchain_claim_proof"
    assert payload["payload"]["vm_type"] == "svm"
    assert payload["payload"]["program_id"] == SVM_PROGRAM
    assert "Anchor reward program" in payload["payload"]["instruction"]


def test_svm_proof_data_and_canonical_proof_agree(_hmac_fallback):
    adapter = OnchainClaimAdapter()
    payload = _run(adapter.build_action_payload(
        _svm_decision(), _svm_rule(), _svm_campaign(), "tenant_svm_test"
    ))
    pd = payload["proof_data"]
    assert pd["proof_format"] == "svm"
    assert pd["nonce"] == payload["proof"]["nonce"]
    assert pd["signature"] == payload["proof"]["signature"]
    assert pd["amount"] == payload["proof"]["amount_wei"]


def test_svm_build_action_payload_rejects_unsupported_vm(_hmac_fallback):
    adapter = OnchainClaimAdapter()
    campaign = {**_svm_campaign(), "vm_type": "bitcoin"}
    with pytest.raises(ValueError, match="not wired"):
        _run(adapter.build_action_payload(
            _svm_decision(), _svm_rule(), campaign, "tenant_svm_test"
        ))
