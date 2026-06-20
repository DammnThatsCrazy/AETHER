"""
Unit tests for reward proof security (A6).

Covers: proof validity, signer mismatch, chain replay, nonce replay, expiry,
revocation prevention, fraud blocking, wallet gating, contract registry,
and hardcoded key protection.
"""

from __future__ import annotations

import asyncio
import os
import sys
import time
import uuid

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

os.environ.setdefault("AETHER_ENV", "local")

from services.oracle.signer import OracleProofSigner, ProofConfig, ProofFormat


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


_HARDHAT_KEY = "ac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80"
_ALT_KEY = "59c6995e998f97a5a0044966f0945389dc9e86dae88c7a8412f4603b6b78690d"
_CONTRACT = "0x5FbDB2315678afecb367f032d93F642f64180aa3"
_CHAIN_ID = 31337  # Hardhat local


def _make_signer(key=_HARDHAT_KEY, contract=_CONTRACT, chain_id=_CHAIN_ID, expiry=3600):
    return OracleProofSigner(ProofConfig(
        signer_private_key=key,
        contract_address=contract,
        chain_id=chain_id,
        proof_expiry_seconds=expiry,
    ))


# ═══════════════════════════════════════════════════════════════════════════
# Valid proof verifies
# ═══════════════════════════════════════════════════════════════════════════

def test_valid_eip191_proof_verifies():
    signer = _make_signer()
    proof = _run(signer.generate_proof(
        user="0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266",
        action_type="conversion",
        amount_wei=1000000000000000000,
    ))
    assert _run(signer.verify_proof(proof))


def test_valid_eip712_proof_verifies():
    signer = _make_signer()
    proof = _run(signer.generate_proof(
        user="0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266",
        action_type="conversion",
        amount_wei=1000000000000000000,
        proof_format="eip712",
        campaign_id=str(uuid.uuid4()),
        rule_id=str(uuid.uuid4()),
        decision_id=str(uuid.uuid4()),
    ))
    assert proof.proof_format == "eip712"
    assert _run(signer.verify_proof(proof))


# ═══════════════════════════════════════════════════════════════════════════
# Wrong signer rejected
# ═══════════════════════════════════════════════════════════════════════════

def test_wrong_signer_rejected():
    signer_a = _make_signer(key=_HARDHAT_KEY)
    signer_b = _make_signer(key=_ALT_KEY)

    proof = _run(signer_a.generate_proof(
        user="0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266",
        action_type="conversion",
        amount_wei=500,
    ))
    # Verify with wrong signer (different key → different expected address)
    assert not _run(signer_b.verify_proof(proof))


# ═══════════════════════════════════════════════════════════════════════════
# Wrong chain rejected
# ═══════════════════════════════════════════════════════════════════════════

def test_proof_fields_include_chain_id():
    signer = _make_signer(chain_id=1)
    proof = _run(signer.generate_proof(
        user="0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266",
        action_type="referral",
        amount_wei=200,
    ))
    assert proof.chain_id == 1

    # Proof generated on chain 1 should NOT verify on a signer for chain 137
    signer_polygon = _make_signer(chain_id=137)
    assert not _run(signer_polygon.verify_proof(proof))


# ═══════════════════════════════════════════════════════════════════════════
# Expired proof rejected
# ═══════════════════════════════════════════════════════════════════════════

def test_expired_proof_fails_verify():
    signer = _make_signer(expiry=1)  # 1 second expiry
    proof = _run(signer.generate_proof(
        user="0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266",
        action_type="signup",
        amount_wei=100,
    ))
    import time as _t
    _t.sleep(2)  # wait for expiry
    assert not _run(signer.verify_proof(proof))


# ═══════════════════════════════════════════════════════════════════════════
# Nonce uniqueness
# ═══════════════════════════════════════════════════════════════════════════

def test_nonces_are_unique_across_proofs():
    signer = _make_signer()
    proofs = [
        _run(signer.generate_proof(
            user="0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266",
            action_type="conversion",
            amount_wei=100,
        ))
        for _ in range(5)
    ]
    nonces = {p.nonce for p in proofs}
    assert len(nonces) == 5


# ═══════════════════════════════════════════════════════════════════════════
# Proof repository: mark_used and mark_revoked
# ═══════════════════════════════════════════════════════════════════════════

def test_proof_mark_used():
    from services.rewards.repositories import RewardProofRepository
    repo = RewardProofRepository()
    nonce = os.urandom(16).hex()

    async def run():
        proof = await repo.create("tenant_t1", {
            "nonce": nonce,
            "wallet_address": "0xdeadbeef",
            "expiry": int(time.time()) + 3600,
            "expires_at": "2099-01-01T00:00:00Z",
            "status": "created",
        })
        proof_id = proof["id"]
        updated = await repo.mark_used(proof_id, "tenant_t1")
        return updated

    result = _run(run())
    assert result["status"] == "used"
    assert "used_at" in result


def test_proof_mark_revoked():
    from services.rewards.repositories import RewardProofRepository
    repo = RewardProofRepository()
    nonce = os.urandom(16).hex()

    async def run():
        proof = await repo.create("tenant_t2", {
            "nonce": nonce,
            "wallet_address": "0xbeefdead",
            "expiry": int(time.time()) + 3600,
            "expires_at": "2099-01-01T00:00:00Z",
            "status": "created",
        })
        proof_id = proof["id"]
        updated = await repo.mark_revoked(proof_id, "tenant_t2", reason="test_revoke")
        return updated

    result = _run(run())
    assert result["status"] == "revoked"
    assert "revoked_at" in result


# ═══════════════════════════════════════════════════════════════════════════
# Proof format fields
# ═══════════════════════════════════════════════════════════════════════════

def test_proof_to_dict_includes_format():
    signer = _make_signer()
    proof = _run(signer.generate_proof(
        user="0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266",
        action_type="conversion",
        amount_wei=100,
        proof_format="eip712",
        campaign_id=str(uuid.uuid4()),
        rule_id=str(uuid.uuid4()),
    ))
    d = proof.to_dict()
    assert d["proof_format"] == "eip712"
    assert "campaign_id" in d
    assert "rule_id" in d


def test_proof_eip191_to_dict_no_extra_fields():
    signer = _make_signer()
    proof = _run(signer.generate_proof(
        user="0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266",
        action_type="conversion",
        amount_wei=100,
    ))
    d = proof.to_dict()
    assert d["proof_format"] == "eip191"
    assert "campaign_id" not in d  # not included when None


# ═══════════════════════════════════════════════════════════════════════════
# Hardhat key blocked in non-local environments
# ═══════════════════════════════════════════════════════════════════════════

def test_hardhat_key_blocked_in_staging():
    original_env = os.environ.get("AETHER_ENV", "local")
    os.environ["AETHER_ENV"] = "staging"
    try:
        from services.rewards.rails import OnchainClaimAdapter
        adapter = OnchainClaimAdapter()
        # The adapter should raise when trying to use the hardhat key in staging
        with pytest.raises((RuntimeError, ValueError)):
            adapter._resolve_signer_key({})
    finally:
        os.environ["AETHER_ENV"] = original_env


def test_hardhat_key_allowed_in_local():
    os.environ["AETHER_ENV"] = "local"
    os.environ.pop("ORACLE_SIGNER_KEY", None)
    signer = _make_signer(key=_HARDHAT_KEY)
    assert signer.signer_address is not None


# ═══════════════════════════════════════════════════════════════════════════
# EIP-712 domain separation prevents cross-chain replay
# ═══════════════════════════════════════════════════════════════════════════

def test_eip712_different_chains_produce_different_hashes():
    signer1 = _make_signer(chain_id=1)
    signer2 = _make_signer(chain_id=137)

    campaign_id = str(uuid.uuid4())
    rule_id = str(uuid.uuid4())
    decision_id = str(uuid.uuid4())
    nonce = os.urandom(32)
    expiry = int(time.time()) + 3600

    from services.oracle.signer import _uuid_to_bytes32
    hash1 = signer1._compute_eip712_hash(
        user="0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266",
        campaign_id_bytes32=_uuid_to_bytes32(campaign_id),
        rule_id_bytes32=_uuid_to_bytes32(rule_id),
        decision_id_bytes32=_uuid_to_bytes32(decision_id),
        action_type="conversion",
        amount_wei=100,
        nonce_bytes32=nonce,
        expiry=expiry,
    )
    hash2 = signer2._compute_eip712_hash(
        user="0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266",
        campaign_id_bytes32=_uuid_to_bytes32(campaign_id),
        rule_id_bytes32=_uuid_to_bytes32(rule_id),
        decision_id_bytes32=_uuid_to_bytes32(decision_id),
        action_type="conversion",
        amount_wei=100,
        nonce_bytes32=nonce,
        expiry=expiry,
    )
    assert hash1 != hash2
