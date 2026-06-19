"""
Aether Backend — Oracle Proof Signer (EVM)

Generates cryptographic proofs for reward eligibility that are verifiable
on-chain via keccak256 message signing with secp256k1 ECDSA.

Supports two proof formats:
- EIP-191: raw keccak256(abi.encodePacked(...)) — matches AnalyticsRewards.sol
- EIP-712: typed structured data with domain separator — for future contract upgrades

Uses eth_account for real cryptographic operations:
- keccak256 hashing (matching Solidity's abi.encodePacked)
- secp256k1 ECDSA signing via Account.signHash
- ecrecover-compatible signature verification
- Real Ethereum address derivation from private key

Requires: eth-account>=0.11.0 (included in backend extras)
"""

from __future__ import annotations

import hashlib
import os
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from shared.logger.logger import get_logger, metrics

logger = get_logger("aether.service.oracle.signer")

# eth_account for real secp256k1 ECDSA
try:
    from eth_account import Account
    from eth_hash.auto import keccak
    ETH_ACCOUNT_AVAILABLE = True
except ImportError:
    ETH_ACCOUNT_AVAILABLE = False
    Account = None  # type: ignore[misc, assignment]
    keccak = None  # type: ignore[assignment]


def _is_local_env() -> bool:
    return os.getenv("AETHER_ENV", "local").lower() == "local"


# ======================================================================
# ENUMS
# ======================================================================

class ProofFormat(str, Enum):
    EIP191 = "eip191"
    EIP712 = "eip712"


# ======================================================================
# DATA MODELS
# ======================================================================

@dataclass(frozen=True)
class ProofConfig:
    """Configuration for the oracle signer."""
    signer_private_key: str
    contract_address: str
    chain_id: int = 1
    proof_expiry_seconds: int = 3600


@dataclass(frozen=True)
class RewardProof:
    """A cryptographic proof verifiable on-chain."""
    user: str
    action_type: str
    amount_wei: int
    nonce: str
    expiry: int
    chain_id: int
    contract_address: str
    signature: str
    message_hash: str
    # Extended fields (A6: attribution-verified reward enablement)
    proof_format: str = "eip191"
    campaign_id: Optional[str] = None
    rule_id: Optional[str] = None
    decision_id: Optional[str] = None

    def to_dict(self) -> dict:
        d = {
            "user": self.user,
            "action_type": self.action_type,
            "amount_wei": str(self.amount_wei),
            "nonce": self.nonce,
            "expiry": self.expiry,
            "chain_id": self.chain_id,
            "contract_address": self.contract_address,
            "signature": self.signature,
            "message_hash": self.message_hash,
            "proof_format": self.proof_format,
        }
        if self.campaign_id:
            d["campaign_id"] = self.campaign_id
        if self.rule_id:
            d["rule_id"] = self.rule_id
        if self.decision_id:
            d["decision_id"] = self.decision_id
        return d


# ======================================================================
# ORACLE PROOF SIGNER
# ======================================================================

class OracleProofSigner:
    """
    Generates and verifies cryptographic proofs for on-chain reward claims.

    Production: uses eth_account for real secp256k1 ECDSA signing.
    Local fallback: uses SHA-256 + HMAC simulation (NOT valid on-chain).
    """

    # EIP-712 domain name; must match AetherRewardEnabler.sol when deployed
    _EIP712_DOMAIN_NAME = b"AetherRewardEnabler"
    _EIP712_DOMAIN_VERSION = b"1"

    def __init__(self, config: ProofConfig) -> None:
        self._config = config
        self._use_real_crypto = ETH_ACCOUNT_AVAILABLE

        if not _is_local_env() and not ETH_ACCOUNT_AVAILABLE:
            raise RuntimeError(
                "eth-account required for production oracle signing. "
                "Install with: pip install eth-account>=0.11.0"
            )

        if self._use_real_crypto:
            acct = Account.from_key(config.signer_private_key)
            self._signer_address = acct.address
            logger.info(f"Oracle signer initialized (secp256k1, address={self._signer_address})")
        else:
            key_bytes = bytes.fromhex(config.signer_private_key.removeprefix("0x"))
            self._signer_address = f"0x{hashlib.sha256(key_bytes).hexdigest()[:40]}"
            logger.warning("Oracle signer using SHA-256 simulation (LOCAL mode only)")

    @property
    def signer_address(self) -> str:
        return self._signer_address

    # -- proof generation ------------------------------------------------

    async def generate_proof(
        self,
        user: str,
        action_type: str,
        amount_wei: int,
        *,
        proof_format: str = "eip191",
        campaign_id: Optional[str] = None,
        rule_id: Optional[str] = None,
        decision_id: Optional[str] = None,
    ) -> RewardProof:
        """Generate a cryptographic proof for a reward claim.

        Args:
            user: Recipient wallet address (0x...).
            action_type: Qualifying event type string.
            amount_wei: Reward amount in wei (uint256).
            proof_format: "eip191" (default, current contract) or "eip712" (typed data).
            campaign_id: Optional campaign UUID for EIP-712 struct.
            rule_id: Optional rule UUID for EIP-712 struct.
            decision_id: Optional decision UUID for EIP-712 struct.
        """
        nonce = os.urandom(32).hex()
        expiry = int(time.time()) + self._config.proof_expiry_seconds

        fmt = ProofFormat(proof_format)
        if fmt == ProofFormat.EIP712:
            message_hash = self._compute_eip712_hash(
                user=user,
                campaign_id_bytes32=_uuid_to_bytes32(campaign_id),
                rule_id_bytes32=_uuid_to_bytes32(rule_id),
                decision_id_bytes32=_uuid_to_bytes32(decision_id),
                action_type=action_type,
                amount_wei=amount_wei,
                nonce_bytes32=bytes.fromhex(nonce),
                expiry=expiry,
            )
        else:
            message_hash = self._build_message_hash(
                user, action_type, amount_wei, nonce, expiry,
            )

        signature = self._sign(message_hash)

        proof = RewardProof(
            user=user,
            action_type=action_type,
            amount_wei=amount_wei,
            nonce=nonce,
            expiry=expiry,
            chain_id=self._config.chain_id,
            contract_address=self._config.contract_address,
            signature=f"0x{signature}",
            message_hash=f"0x{message_hash}",
            proof_format=proof_format,
            campaign_id=campaign_id,
            rule_id=rule_id,
            decision_id=decision_id,
        )

        logger.info(
            f"Proof generated: user={user} action={action_type} "
            f"amount={amount_wei} expiry={expiry} format={proof_format}"
        )
        metrics.increment("oracle_proofs_generated", labels={"chain_id": str(self._config.chain_id), "format": proof_format})
        return proof

    async def verify_proof(self, proof: RewardProof) -> bool:
        """Verify a proof by recovering the signer from the signature."""
        if int(time.time()) > proof.expiry:
            logger.warning(f"Proof expired: user={proof.user} expiry={proof.expiry}")
            return False

        msg_hash = proof.message_hash.removeprefix("0x")
        sig = proof.signature.removeprefix("0x")

        recovered = self._recover_signer(msg_hash, sig)
        valid = recovered.lower() == self._signer_address.lower()

        if not valid:
            logger.warning(
                f"Proof verification failed: recovered={recovered} "
                f"expected={self._signer_address}"
            )

        metrics.increment(
            "oracle_proofs_verified",
            labels={"valid": str(valid), "chain_id": str(proof.chain_id)},
        )
        return valid

    # -- EIP-712 hash computation ----------------------------------------

    def _compute_eip712_hash(
        self,
        user: str,
        campaign_id_bytes32: bytes,
        rule_id_bytes32: bytes,
        decision_id_bytes32: bytes,
        action_type: str,
        amount_wei: int,
        nonce_bytes32: bytes,
        expiry: int,
    ) -> str:
        """Compute EIP-712 typed data hash.

        Matches the TypedData structure expected by an AetherRewardEnabler.sol
        upgrade. The domain separator includes chainId and verifyingContract for
        replay protection across chains and contracts.

        Type string (for reference):
            EIP712Domain(string name,string version,uint256 chainId,address verifyingContract)
            RewardClaim(address user,bytes32 campaignId,bytes32 ruleId,bytes32 decisionId,string actionType,uint256 amount,bytes32 nonce,uint256 expiry)
        """
        if not self._use_real_crypto:
            # Local fallback: use SHA-256 to simulate (not valid on-chain)
            import hashlib as _hl
            raw = (
                user
                + campaign_id_bytes32.hex()
                + action_type
                + str(amount_wei)
                + nonce_bytes32.hex()
                + str(expiry)
                + str(self._config.chain_id)
                + self._config.contract_address
            )
            return _hl.sha256(raw.encode()).hexdigest()

        # DOMAIN TYPEHASH
        domain_type_hash = keccak(
            b"EIP712Domain(string name,string version,uint256 chainId,address verifyingContract)"
        )
        name_hash = keccak(self._EIP712_DOMAIN_NAME)
        version_hash = keccak(self._EIP712_DOMAIN_VERSION)
        contract_bytes = bytes.fromhex(
            self._config.contract_address.removeprefix("0x").lower()
        ).rjust(32, b"\x00")

        domain_separator = keccak(
            domain_type_hash
            + name_hash
            + version_hash
            + self._config.chain_id.to_bytes(32, "big")
            + contract_bytes
        )

        # STRUCT TYPEHASH
        struct_type_hash = keccak(
            b"RewardClaim(address user,bytes32 campaignId,bytes32 ruleId,"
            b"bytes32 decisionId,string actionType,uint256 amount,bytes32 nonce,uint256 expiry)"
        )
        action_type_hash = keccak(action_type.encode("utf-8"))
        user_bytes = bytes.fromhex(user.removeprefix("0x").lower()).rjust(32, b"\x00")

        struct_hash = keccak(
            struct_type_hash
            + user_bytes
            + campaign_id_bytes32
            + rule_id_bytes32
            + decision_id_bytes32
            + action_type_hash
            + amount_wei.to_bytes(32, "big")
            + nonce_bytes32
            + expiry.to_bytes(32, "big")
        )

        return keccak(b"\x19\x01" + domain_separator + struct_hash).hex()

    # -- EIP-191 hash computation ----------------------------------------

    def _build_message_hash(
        self,
        user: str,
        action_type: str,
        amount_wei: int,
        nonce: str,
        expiry: int,
    ) -> str:
        """Compute keccak256(abi.encodePacked(...)) matching AnalyticsRewards.sol."""
        packed = b"".join([
            bytes.fromhex(user.removeprefix("0x").lower()),
            action_type.encode("utf-8"),
            amount_wei.to_bytes(32, "big"),
            bytes.fromhex(nonce),
            expiry.to_bytes(32, "big"),
            self._config.chain_id.to_bytes(32, "big"),
            bytes.fromhex(self._config.contract_address.removeprefix("0x").lower()),
        ])

        if self._use_real_crypto:
            return keccak(packed).hex()

        return hashlib.sha256(packed).hexdigest()

    # -- crypto primitives -----------------------------------------------

    def _sign(self, message_hash: str) -> str:
        """Sign a 32-byte message hash with secp256k1 ECDSA."""
        if self._use_real_crypto:
            msg_bytes = bytes.fromhex(message_hash)
            signed = Account.signHash(msg_bytes, self._config.signer_private_key)
            return signed.signature.hex()

        import hmac as _hmac
        return _hmac.new(
            key=self._config.signer_private_key.encode(),
            msg=bytes.fromhex(message_hash),
            digestmod=hashlib.sha256,
        ).hexdigest()

    def _recover_signer(self, message_hash: str, signature: str) -> str:
        """Recover the signer address from a signature (ecrecover)."""
        if self._use_real_crypto:
            msg_bytes = bytes.fromhex(message_hash)
            sig_bytes = bytes.fromhex(signature)
            recovered = Account.recoverHash(msg_bytes, signature=sig_bytes)
            return recovered

        import hmac as _hmac
        expected = _hmac.new(
            key=self._config.signer_private_key.encode(),
            msg=bytes.fromhex(message_hash),
            digestmod=hashlib.sha256,
        ).hexdigest()
        if _hmac.compare_digest(expected, signature):
            return self._signer_address
        return "0x0000000000000000000000000000000000000000"


# ======================================================================
# HELPERS
# ======================================================================

def _uuid_to_bytes32(uuid_str: Optional[str]) -> bytes:
    """Convert a UUID string (or None) to a 32-byte value for EIP-712 structs.

    UUID is 16 bytes; right-justified into 32 bytes (zeros on the left).
    This matches Solidity's implicit zero-padding for bytes32 assignments.
    """
    if not uuid_str:
        return b"\x00" * 32
    clean = uuid_str.replace("-", "")
    val = bytes.fromhex(clean)  # 16 bytes
    return val.rjust(32, b"\x00")


# Backward compatibility alias
OracleSigner = OracleProofSigner
