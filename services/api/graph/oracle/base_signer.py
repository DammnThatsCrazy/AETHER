"""
Aether Backend — Base Proof Signer

Shared cryptographic signing infrastructure used by both the EVM-only
``OracleProofSigner`` and the ``MultiChainSigner``.

Production: uses eth_account for secp256k1 ECDSA (EVM/TVM/Bitcoin/Cosmos).
Local fallback: HMAC-SHA256 simulation when eth_account unavailable.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import time
from dataclasses import dataclass

from shared.common.common import BadRequestError

# Optional real crypto imports
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


# ======================================================================
# DATA MODELS
# ======================================================================

@dataclass(frozen=True)
class BaseProofConfig:
    """Shared configuration fields for all oracle signers."""
    signer_private_key: str
    contract_address: str
    chain_id: int = 1
    proof_expiry_seconds: int = 3_600


@dataclass
class BaseRewardProof:
    """Minimal set of fields shared by all reward proofs regardless of chain."""
    user: str
    action_type: str
    amount_wei: int
    nonce: str
    expiry: int
    chain_id: int
    contract_address: str
    signature: str
    message_hash: str


# ======================================================================
# BASE PROOF SIGNER
# ======================================================================

class BaseProofSigner:
    """
    Shared signing infrastructure for all oracle signers.

    Production: uses eth_account for secp256k1 ECDSA signing and
    chain-specific hashing (keccak256, SHA3-256, SHA-256d).
    Local: HMAC-SHA256 fallback for development without crypto deps.
    """

    def __init__(self, private_key: str) -> None:
        self._private_key = private_key.removeprefix("0x")
        self._use_real_crypto = REAL_CRYPTO_AVAILABLE

        if not _is_local_env() and not REAL_CRYPTO_AVAILABLE:
            raise RuntimeError(
                "eth-account required for production oracle signing. "
                "Install: pip install eth-account>=0.11.0"
            )

    # -- crypto primitives (real or fallback) ----------------------------

    def _sign(self, message_hash: str, domain: str = "") -> str:
        """Sign a message hash. Uses secp256k1 ECDSA when available."""
        if self._use_real_crypto:
            msg_bytes = bytes.fromhex(message_hash)
            signed = Account.signHash(msg_bytes, f"0x{self._private_key}")
            return signed.signature.hex()

        # Local-only HMAC fallback
        key_material = self._private_key + (":" + domain if domain else "")
        return hmac.new(
            key=key_material.encode("utf-8"),
            msg=bytes.fromhex(message_hash),
            digestmod=hashlib.sha256,
        ).hexdigest()

    def _recover_signer(
        self,
        message_hash: str,
        signature: str,
        domain: str = "",
        expected_address: str = "",
    ) -> str:
        """Recover the signer address. Uses ecrecover when available."""
        if self._use_real_crypto:
            try:
                msg_bytes = bytes.fromhex(message_hash)
                sig_bytes = bytes.fromhex(signature)
                return Account.recoverHash(msg_bytes, signature=sig_bytes)
            except Exception:
                return self._null_address()

        # Local-only HMAC fallback
        expected_sig = hmac.new(
            key=(self._private_key + (":" + domain if domain else "")).encode("utf-8"),
            msg=bytes.fromhex(message_hash),
            digestmod=hashlib.sha256,
        ).hexdigest()
        if hmac.compare_digest(expected_sig, signature):
            return expected_address
        return self._null_address()

    # -- chain-specific hash functions -----------------------------------

    def _hash_keccak256(self, data: bytes) -> str:
        """Compute keccak256 (EVM/TVM). Falls back to SHA-256 locally."""
        if self._use_real_crypto and keccak is not None:
            return keccak(data).hex()
        return hashlib.sha256(data).hexdigest()

    def _hash_sha256(self, data: bytes) -> str:
        """Compute SHA-256 (SVM/NEAR/Cosmos)."""
        return hashlib.sha256(data).hexdigest()

    def _hash_sha3_256(self, data: bytes) -> str:
        """Compute SHA3-256 (MoveVM/SUI)."""
        return hashlib.sha3_256(data).hexdigest()

    def _hash_sha256d(self, data: bytes) -> str:
        """Compute SHA-256d / double-SHA-256 (Bitcoin)."""
        return hashlib.sha256(hashlib.sha256(data).digest()).hexdigest()

    def _derive_address(self, private_key_hex: str) -> str:
        """Derive Ethereum address from private key."""
        if self._use_real_crypto:
            return Account.from_key(f"0x{private_key_hex}").address
        addr_hash = hashlib.sha256(bytes.fromhex(private_key_hex)).hexdigest()[:40]
        return f"0x{addr_hash}"

    # -- backward compatibility aliases ----------------------------------

    def _simulate_sign(self, message_hash: str, domain: str = "") -> str:
        """Backward compatibility: delegates to _sign()."""
        return self._sign(message_hash, domain)

    def _simulate_recover(
        self, message_hash: str, signature: str,
        domain: str = "", expected_address: str = "",
    ) -> str:
        """Backward compatibility: delegates to _recover_signer()."""
        return self._recover_signer(message_hash, signature, domain, expected_address)

    # -- input validation -----------------------------------------------

    @staticmethod
    def _validate_proof_inputs(user: str, amount: int) -> None:
        if not user:
            raise BadRequestError("user address is required")
        if amount <= 0:
            raise BadRequestError("amount must be positive")

    @staticmethod
    def _generate_nonce_and_expiry(expiry_seconds: int = 3_600) -> tuple[str, int]:
        nonce = os.urandom(32).hex()
        expiry = int(time.time()) + expiry_seconds
        return nonce, expiry

    @staticmethod
    def _format_hex_value(hex_str: str, prefix: str = "0x") -> str:
        return f"{prefix}{hex_str}"

    @staticmethod
    def _strip_hex_prefix(formatted: str, prefix: str = "0x") -> str:
        return formatted[len(prefix):] if formatted.startswith(prefix) else formatted

    @staticmethod
    def _null_address() -> str:
        return "0x" + "0" * 40
