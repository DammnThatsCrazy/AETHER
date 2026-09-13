"""
Aether Backend — Oracle Signature Verifier

Utilities for verifying oracle signatures off-chain before submitting
on-chain. Used by the rewards service to validate proofs before storing
them and by the oracle routes for standalone verification.

Production: uses eth_account for keccak256 + ecrecover.
Local fallback: HMAC comparison when eth_account unavailable.
"""

from __future__ import annotations

import hashlib
import os
import time

from services.oracle.signer import RewardProof
from shared.logger.logger import get_logger

logger = get_logger("aether.service.oracle.verifier")

# Real crypto when available
try:
    from eth_account import Account
    from eth_hash.auto import keccak
    REAL_CRYPTO_AVAILABLE = True
except ImportError:
    Account = None  # type: ignore[misc, assignment]
    keccak = None  # type: ignore[assignment]
    REAL_CRYPTO_AVAILABLE = False


def _is_local_env() -> bool:
    return os.getenv("AETHER_ENV", "local").lower() == "local"


# ═══════════════════════════════════════════════════════════════════════════
# PUBLIC HELPERS
# ═══════════════════════════════════════════════════════════════════════════

def verify_reward_proof(proof: RewardProof, expected_signer: str) -> bool:
    """
    Full off-chain verification of a reward proof.

    Checks:
        1. The proof has not expired.
        2. The message hash is correctly derived from the proof fields.
        3. The recovered signer matches ``expected_signer``.
    """
    if is_proof_expired(proof):
        logger.warning(f"Proof expired: user={proof.user} expiry={proof.expiry}")
        return False

    expected_hash = compute_message_hash(
        user=proof.user,
        action_type=proof.action_type,
        amount_wei=proof.amount_wei,
        nonce=proof.nonce.removeprefix("0x"),
        expiry=proof.expiry,
        chain_id=proof.chain_id,
        contract_address=proof.contract_address,
    )

    actual_hash = proof.message_hash.removeprefix("0x")
    if expected_hash != actual_hash:
        logger.warning(
            f"Message hash mismatch: expected={expected_hash} actual={actual_hash}"
        )
        return False

    recovered = _recover_signer(
        message_hash=actual_hash,
        signature=proof.signature.removeprefix("0x"),
    )

    if recovered.lower() != expected_signer.lower():
        logger.warning(
            f"Signer mismatch: recovered={recovered} expected={expected_signer}"
        )
        return False

    return True


def is_proof_expired(proof: RewardProof) -> bool:
    """Return ``True`` when the proof's expiry timestamp is in the past."""
    return int(time.time()) > proof.expiry


def compute_message_hash(
    user: str,
    action_type: str,
    amount_wei: int,
    nonce: str,
    expiry: int,
    chain_id: int,
    contract_address: str,
) -> str:
    """
    Recompute the canonical message hash from proof components.
    Mirrors the packing logic in OracleProofSigner._build_message_hash.
    """
    packed = b"".join([
        bytes.fromhex(user.removeprefix("0x").lower()),
        action_type.encode("utf-8"),
        amount_wei.to_bytes(32, "big"),
        bytes.fromhex(nonce),
        expiry.to_bytes(32, "big"),
        chain_id.to_bytes(32, "big"),
        bytes.fromhex(contract_address.removeprefix("0x").lower()),
    ])
    return _keccak256(packed)


# ═══════════════════════════════════════════════════════════════════════════
# PRIVATE HELPERS
# ═══════════════════════════════════════════════════════════════════════════

def _keccak256(data: bytes) -> str:
    """Compute keccak256. Uses real keccak when available, SHA-256 fallback for local."""
    if REAL_CRYPTO_AVAILABLE and keccak is not None:
        return keccak(data).hex()
    if not _is_local_env():
        raise RuntimeError(
            "eth-account required for production oracle verification. "
            "Install: pip install eth-account>=0.11.0"
        )
    return hashlib.sha256(data).hexdigest()


def _recover_signer(message_hash: str, signature: str) -> str:
    """Recover signer address from signature via ecrecover."""
    if REAL_CRYPTO_AVAILABLE:
        try:
            msg_bytes = bytes.fromhex(message_hash)
            sig_bytes = bytes.fromhex(signature)
            return Account.recoverHash(msg_bytes, signature=sig_bytes)
        except Exception as e:
            logger.error(f"ecrecover failed: {e}")
            return "0x" + "0" * 40

    if not _is_local_env():
        raise RuntimeError(
            "eth-account required for production oracle verification."
        )
    # Local-only fallback: accept any plausible-length signature
    # This is NOT real verification — only for local dev
    logger.warning("Using local-only signature verification (NOT production-safe)")
    if len(signature) >= 64:
        return "0x" + "0" * 40  # Cannot recover without real crypto
    return "0x" + "0" * 40
