"""
Aether Backend — Multi-Chain Oracle Signer

Generates cryptographic proofs for reward eligibility across all supported
blockchain virtual machines: EVM, SVM (Solana), Bitcoin, MoveVM (SUI),
NEAR, TVM (TRON), and Cosmos.

Each VM family uses its own message format and signing scheme:
    - EVM:     keccak256 + secp256k1 ECDSA (EIP-191 / EIP-712)
    - SVM:     SHA-256 + Ed25519 (Solana native)
    - Bitcoin: SHA-256d (double-hash) + secp256k1 ECDSA
    - MoveVM:  SHA3-256 + Ed25519 (SUI native)
    - NEAR:    SHA-256 + Ed25519 (NEAR native)
    - TVM:     keccak256 + secp256k1 ECDSA (TRON, EVM-compatible)
    - Cosmos:  SHA-256 + secp256k1 ECDSA (Amino signing)

Production: uses eth_account for secp256k1 ECDSA with chain-specific
hashing (keccak256, SHA3-256, SHA-256d). Local fallback uses HMAC-SHA256.
"""

from __future__ import annotations

import base64
import hashlib
import json
import struct
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from services.oracle.base_signer import BaseProofSigner
from services.oracle.signer import RewardProof
from shared.common.common import BadRequestError
from shared.logger.logger import get_logger, metrics

logger = get_logger("aether.service.oracle.multichain_signer")


# ======================================================================
# VM TYPE ENUM
# ======================================================================

class VMType(str, Enum):
    """Supported blockchain virtual machine families."""

    EVM = "evm"
    SVM = "svm"
    BITCOIN = "bitcoin"
    MOVEVM = "movevm"
    NEAR = "near"
    TVM = "tvm"
    COSMOS = "cosmos"

    @classmethod
    def from_string(cls, value: str) -> VMType:
        """Parse a VM type from a case-insensitive string."""
        normalised = value.strip().lower()
        for member in cls:
            if member.value == normalised:
                return member
        raise BadRequestError(
            f"Unsupported VM type: '{value}'. "
            f"Supported: {', '.join(m.value for m in cls)}"
        )


# ======================================================================
# CHAIN CONFIG
# ======================================================================

@dataclass(frozen=True)
class ChainConfig:
    """
    Per-chain configuration for the multi-chain signer.

    Attributes:
        chain_id:              Numeric chain identifier (EVM chain ID, Cosmos
                               chain numeric, Solana cluster enum, etc.).
        contract_address:      Primary contract/program address on this chain.
        proof_expiry_seconds:  Seconds until a generated proof expires.
    """

    chain_id: int
    contract_address: str
    proof_expiry_seconds: int = 3_600  # 1 h


@dataclass(frozen=True)
class MultiChainProofConfig:
    """
    Global configuration for the multi-chain oracle signer.

    Attributes:
        signer_private_key:  Hex-encoded private key shared across all chains.
        chain_configs:       Per-VM chain configurations.
    """

    signer_private_key: str
    chain_configs: dict[VMType, ChainConfig] = field(default_factory=dict)

    def get_chain_config(self, vm_type: VMType) -> ChainConfig:
        """Return the config for a VM type, or raise if unconfigured."""
        config = self.chain_configs.get(vm_type)
        if config is None:
            raise BadRequestError(
                f"No chain configuration registered for VM type: {vm_type.value}"
            )
        return config


# ======================================================================
# MULTI-CHAIN REWARD PROOF
# ======================================================================

@dataclass
class MultiChainRewardProof:
    """
    A signed proof that a user is entitled to claim a specific reward
    on any supported chain.

    Extends the base ``RewardProof`` concept with VM-specific addressing
    fields so the consumer knows which on-chain entry-point to target.

    Attributes:
        user:              Address/account identifier of the claimant.
        action_type:       The qualifying event type (e.g. ``conversion``).
        amount_wei:        Reward amount (wei for EVM, lamports for SVM, etc.).
        nonce:             Random 32-byte hex nonce (replay protection).
        expiry:            Unix timestamp after which the proof is invalid.
        chain_id:          Target chain identifier.
        contract_address:  The reward contract/program this proof targets.
        signature:         Hex-encoded signature over the message hash.
        message_hash:      Hex-encoded hash of the canonical message.
        vm_type:           The VM family this proof was generated for.
        program_id:        Solana program ID (SVM only).
        module_address:    SUI Move module address (MoveVM only).
        account_id:        NEAR account ID (NEAR only).
        base_denom:        Cosmos base denomination (Cosmos only).
    """

    user: str
    action_type: str
    amount_wei: int
    nonce: str
    expiry: int
    chain_id: int
    contract_address: str
    signature: str
    message_hash: str
    vm_type: VMType
    program_id: Optional[str] = None
    module_address: Optional[str] = None
    account_id: Optional[str] = None
    base_denom: Optional[str] = None

    def to_dict(self) -> dict:
        result = {
            "user": self.user,
            "action_type": self.action_type,
            "amount_wei": self.amount_wei,
            "nonce": self.nonce,
            "expiry": self.expiry,
            "chain_id": self.chain_id,
            "contract_address": self.contract_address,
            "signature": self.signature,
            "message_hash": self.message_hash,
            "vm_type": self.vm_type.value,
        }
        if self.program_id is not None:
            result["program_id"] = self.program_id
        if self.module_address is not None:
            result["module_address"] = self.module_address
        if self.account_id is not None:
            result["account_id"] = self.account_id
        if self.base_denom is not None:
            result["base_denom"] = self.base_denom
        return result

    @classmethod
    def from_dict(cls, data: dict) -> MultiChainRewardProof:
        return cls(
            user=data["user"],
            action_type=data["action_type"],
            amount_wei=data["amount_wei"],
            nonce=data["nonce"],
            expiry=data["expiry"],
            chain_id=data["chain_id"],
            contract_address=data["contract_address"],
            signature=data["signature"],
            message_hash=data["message_hash"],
            vm_type=VMType.from_string(data["vm_type"]),
            program_id=data.get("program_id"),
            module_address=data.get("module_address"),
            account_id=data.get("account_id"),
            base_denom=data.get("base_denom"),
        )

    def to_reward_proof(self) -> RewardProof:
        """Downcast to a base ``RewardProof`` for backward compatibility."""
        return RewardProof(
            user=self.user,
            action_type=self.action_type,
            amount_wei=self.amount_wei,
            nonce=self.nonce,
            expiry=self.expiry,
            chain_id=self.chain_id,
            contract_address=self.contract_address,
            signature=self.signature,
            message_hash=self.message_hash,
        )


# ======================================================================
# BASE58 ENCODING UTILITY
# ======================================================================

_BASE58_ALPHABET = b"123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


def _base58_encode(data: bytes) -> str:
    """Encode raw bytes into a Base58 string (Bitcoin/Solana style)."""
    # Count leading zero bytes
    num_leading_zeros = 0
    for byte in data:
        if byte == 0:
            num_leading_zeros += 1
        else:
            break

    # Convert bytes to a big integer
    num = int.from_bytes(data, "big")

    # Encode the integer as base58
    result = bytearray()
    while num > 0:
        num, remainder = divmod(num, 58)
        result.append(_BASE58_ALPHABET[remainder])

    # Reverse to get most-significant digit first
    result.reverse()

    # Prepend '1' characters for each leading zero byte
    return ("1" * num_leading_zeros) + result.decode("ascii")


# ======================================================================
# MULTI-CHAIN SIGNER
# ======================================================================

class MultiChainSigner(BaseProofSigner):
    """
    Generates and verifies reward proofs across all supported VM families.

    Inherits shared HMAC signing, input validation, and nonce generation
    from ``BaseProofSigner``. Adds VM-specific message hashing, address
    derivation, and formatting.

    Production notes:
        - EVM/TVM: replace hashing with ``Web3.keccak``, signing with
          ``Account.sign_message``.
        - SVM: replace with ``nacl.signing.SigningKey`` (Ed25519).
        - Bitcoin: replace with ``ecdsa`` or ``bitcoinlib`` for secp256k1.
        - MoveVM: replace with ``pynacl`` Ed25519 + SHA3-256.
        - NEAR: replace with ``pynacl`` Ed25519.
        - Cosmos: replace with ``ecdsa`` secp256k1 + Amino encoding.
    """

    def __init__(self, config: MultiChainProofConfig) -> None:
        super().__init__(config.signer_private_key)
        self._config = config
        self._signer_addresses: dict[VMType, str] = {}

        # Derive a pseudo-address for every configured VM type
        for vm_type in VMType:
            self._signer_addresses[vm_type] = self._derive_address(
                config.signer_private_key, vm_type
            )

        # Log initialization summary
        configured_chains = [
            vm.value for vm in config.chain_configs.keys()
        ]
        logger.info(
            f"MultiChainSigner initialised: configured_chains={configured_chains} "
            f"total_vm_types={len(VMType)}"
        )
        for vm_type, address in self._signer_addresses.items():
            logger.debug(f"  {vm_type.value}: signer={address}")

    # -- public API --------------------------------------------------------

    def get_signer_address(self, vm_type: VMType) -> str:
        """Return the oracle signer address for a given VM type."""
        return self._signer_addresses[vm_type]

    def get_signer_info(self) -> dict[str, dict]:
        """
        Return all VM addresses and their chain configs.

        Example return value::

            {
                "evm": {
                    "signer_address": "0xabc...",
                    "chain_id": 1,
                    "contract_address": "0x..."
                },
                ...
            }
        """
        info: dict[str, dict] = {}
        for vm_type in VMType:
            entry: dict = {
                "signer_address": self._signer_addresses[vm_type],
            }
            chain_cfg = self._config.chain_configs.get(vm_type)
            if chain_cfg is not None:
                entry["chain_id"] = chain_cfg.chain_id
                entry["contract_address"] = chain_cfg.contract_address
                entry["proof_expiry_seconds"] = chain_cfg.proof_expiry_seconds
            info[vm_type.value] = entry
        return info

    async def generate_proof(
        self,
        user: str,
        action_type: str,
        amount: int,
        vm_type: VMType,
        chain_id: Optional[int] = None,
    ) -> MultiChainRewardProof:
        """
        Build a signed proof authorising ``user`` to claim ``amount`` on the
        specified VM chain.

        Args:
            user:        Address/account of the reward recipient.
            action_type: The qualifying event type.
            amount:      Reward amount (wei, lamports, satoshis, etc.).
            vm_type:     Target VM family.
            chain_id:    Override the configured chain ID (optional).

        Returns:
            A fully signed ``MultiChainRewardProof``.
        """
        self._validate_proof_inputs(user, amount)

        chain_cfg = self._config.get_chain_config(vm_type)
        resolved_chain_id = chain_id if chain_id is not None else chain_cfg.chain_id

        nonce, expiry = self._generate_nonce_and_expiry(
            chain_cfg.proof_expiry_seconds,
        )

        # Dispatch to VM-specific message builder
        message_hash = self._build_message_hash(
            vm_type=vm_type,
            user=user,
            action_type=action_type,
            amount=amount,
            nonce=nonce,
            expiry=expiry,
            chain_id=resolved_chain_id,
            contract_address=chain_cfg.contract_address,
        )

        # Sign the hash (domain-separated by VM type)
        signature = self._simulate_sign(message_hash, domain=vm_type.value)

        # Determine VM-specific optional fields
        program_id: Optional[str] = None
        module_address: Optional[str] = None
        account_id: Optional[str] = None
        base_denom: Optional[str] = None

        if vm_type == VMType.SVM:
            program_id = chain_cfg.contract_address
        elif vm_type == VMType.MOVEVM:
            module_address = chain_cfg.contract_address
        elif vm_type == VMType.NEAR:
            account_id = chain_cfg.contract_address
        elif vm_type == VMType.COSMOS:
            base_denom = "uatom"

        # Format nonce/signature/hash prefixes per VM convention
        nonce_formatted = self._format_hex_for_vm(nonce, vm_type, "nonce")
        signature_formatted = self._format_hex_for_vm(signature, vm_type, "signature")
        hash_formatted = self._format_hex_for_vm(message_hash, vm_type, "hash")

        proof = MultiChainRewardProof(
            user=user,
            action_type=action_type,
            amount_wei=amount,
            nonce=nonce_formatted,
            expiry=expiry,
            chain_id=resolved_chain_id,
            contract_address=chain_cfg.contract_address,
            signature=signature_formatted,
            message_hash=hash_formatted,
            vm_type=vm_type,
            program_id=program_id,
            module_address=module_address,
            account_id=account_id,
            base_denom=base_denom,
        )

        logger.info(
            f"Multi-chain proof generated: vm={vm_type.value} user={user} "
            f"action={action_type} amount={amount} chain_id={resolved_chain_id} "
            f"expiry={expiry}"
        )
        metrics.increment(
            "oracle_multichain_proofs_generated",
            labels={"vm_type": vm_type.value, "chain_id": str(resolved_chain_id)},
        )
        return proof

    async def verify_proof(self, proof: MultiChainRewardProof) -> bool:
        """
        Verify a multi-chain proof by:
            1. Checking the expiry timestamp.
            2. Recovering the signer and comparing to the expected address.

        Args:
            proof: The proof to verify.

        Returns:
            ``True`` when all checks pass.
        """
        # Check expiry
        if int(time.time()) > proof.expiry:
            logger.warning(
                f"Multi-chain proof expired: vm={proof.vm_type.value} "
                f"user={proof.user} expiry={proof.expiry}"
            )
            return False

        # Strip formatting prefixes for internal operations
        msg_hash = self._strip_hex_for_vm(proof.message_hash, proof.vm_type, "hash")
        sig = self._strip_hex_for_vm(proof.signature, proof.vm_type, "signature")

        # Verify via HMAC recovery (domain-separated by VM type)
        expected = self._signer_addresses[proof.vm_type]
        recovered = self._simulate_recover(
            msg_hash, sig,
            domain=proof.vm_type.value,
            expected_address=expected,
        )
        valid = recovered.lower() == expected.lower()

        if not valid:
            logger.warning(
                f"Multi-chain proof verification failed: vm={proof.vm_type.value} "
                f"recovered={recovered} expected={expected}"
            )

        metrics.increment(
            "oracle_multichain_proofs_verified",
            labels={
                "valid": str(valid),
                "vm_type": proof.vm_type.value,
                "chain_id": str(proof.chain_id),
            },
        )
        return valid

    # -- VM-specific formatting -----------------------------------------

    @staticmethod
    def _format_hex_for_vm(
        hex_str: str, vm_type: VMType, format_type: str,
    ) -> str:
        """
        Apply VM-specific formatting to a raw hex string.

        Args:
            hex_str:     Raw hex string (no prefix).
            vm_type:     Target VM family.
            format_type: One of ``"nonce"``, ``"signature"``, or ``"hash"``.

        Returns:
            Formatted string in the VM's native convention.
        """
        if vm_type in (VMType.EVM, VMType.TVM, VMType.MOVEVM):
            return f"0x{hex_str}"

        elif vm_type == VMType.SVM:
            return _base58_encode(bytes.fromhex(hex_str))

        elif vm_type == VMType.BITCOIN:
            return hex_str  # raw hex for Bitcoin

        elif vm_type == VMType.NEAR:
            return base64.b64encode(bytes.fromhex(hex_str)).decode("ascii")

        elif vm_type == VMType.COSMOS:
            if format_type == "signature":
                return base64.b64encode(bytes.fromhex(hex_str)).decode("ascii")
            return hex_str  # nonce and hash stay as raw hex

        else:
            return f"0x{hex_str}"

    @staticmethod
    def _strip_hex_for_vm(
        formatted: str, vm_type: VMType, format_type: str,
    ) -> str:
        """
        Strip VM-specific formatting from a formatted string to get raw hex.

        Args:
            formatted:   The formatted string.
            vm_type:     The VM family.
            format_type: One of ``"hash"`` or ``"signature"``.

        Returns:
            Raw hex string.
        """
        if vm_type in (VMType.EVM, VMType.TVM, VMType.MOVEVM):
            return formatted.removeprefix("0x")

        elif vm_type == VMType.SVM:
            return formatted  # simplified; in production decode base58

        elif vm_type == VMType.BITCOIN:
            return formatted

        elif vm_type == VMType.NEAR:
            return base64.b64decode(formatted).hex()

        elif vm_type == VMType.COSMOS:
            if format_type == "signature":
                return base64.b64decode(formatted).hex()
            return formatted

        else:
            return formatted.removeprefix("0x")

    # -- message construction dispatching ----------------------------------

    def _build_message_hash(
        self,
        vm_type: VMType,
        user: str,
        action_type: str,
        amount: int,
        nonce: str,
        expiry: int,
        chain_id: int,
        contract_address: str,
    ) -> str:
        """Dispatch to the correct VM-specific message hash builder."""
        builders = {
            VMType.EVM: self._build_evm_message_hash,
            VMType.SVM: self._build_svm_message_hash,
            VMType.BITCOIN: self._build_bitcoin_message_hash,
            VMType.MOVEVM: self._build_movevm_message_hash,
            VMType.NEAR: self._build_near_message_hash,
            VMType.TVM: self._build_tvm_message_hash,
            VMType.COSMOS: self._build_cosmos_message_hash,
        }
        builder = builders[vm_type]
        return builder(
            user=user,
            action_type=action_type,
            amount=amount,
            nonce=nonce,
            expiry=expiry,
            chain_id=chain_id,
            contract_address=contract_address,
        )

    # -- EVM message hash --------------------------------------------------

    def _build_evm_message_hash(
        self,
        user: str,
        action_type: str,
        amount: int,
        nonce: str,
        expiry: int,
        chain_id: int,
        contract_address: str,
    ) -> str:
        """Compute keccak256(abi.encodePacked(...)) for EVM chains."""
        packed = b"".join([
            bytes.fromhex(user.removeprefix("0x").lower().zfill(40)),
            action_type.encode("utf-8"),
            struct.pack(">Q", amount),
            bytes.fromhex(nonce),
            struct.pack(">Q", expiry),
            struct.pack(">Q", chain_id),
            bytes.fromhex(contract_address.removeprefix("0x").lower().zfill(40)),
        ])
        return self._hash_keccak256(packed)

    # -- SVM (Solana) message hash -----------------------------------------

    def _build_svm_message_hash(
        self,
        user: str,
        action_type: str,
        amount: int,
        nonce: str,
        expiry: int,
        chain_id: int,
        contract_address: str,
    ) -> str:
        """
        Simulate Borsh-serialized message hashing for Solana (SHA-256).

        Production: use ``borsh`` serialization library with proper schema.
        """
        discriminator = hashlib.sha256(b"aether:claim_reward").digest()[:8]
        user_bytes = self._normalize_solana_pubkey(user)

        action_bytes = action_type.encode("utf-8")
        action_len = struct.pack("<I", len(action_bytes))

        program_bytes = self._normalize_solana_pubkey(contract_address)

        packed = b"".join([
            discriminator,
            user_bytes,
            action_len,
            action_bytes,
            struct.pack("<Q", amount),
            bytes.fromhex(nonce),
            struct.pack("<Q", expiry),
            program_bytes,
        ])
        return self._hash_sha256(packed)

    # -- Bitcoin message hash ----------------------------------------------

    def _build_bitcoin_message_hash(
        self,
        user: str,
        action_type: str,
        amount: int,
        nonce: str,
        expiry: int,
        chain_id: int,
        contract_address: str,
    ) -> str:
        """
        Simulate Bitcoin signed message format (SHA-256d = double SHA-256).

        Production: use ``bitcoinlib`` or ``python-bitcoinlib`` for proper
        message signing with secp256k1.
        """
        payload = (
            f"aether:claim|{user}|{action_type}|{amount}|{nonce}|"
            f"{expiry}|{chain_id}|{contract_address}"
        )
        payload_bytes = payload.encode("utf-8")

        prefix = b"\x18Bitcoin Signed Message:\n"
        msg_len = self._bitcoin_varint(len(payload_bytes))

        full_message = prefix + msg_len + payload_bytes

        return self._hash_sha256d(full_message)

    # -- MoveVM (SUI) message hash -----------------------------------------

    def _build_movevm_message_hash(
        self,
        user: str,
        action_type: str,
        amount: int,
        nonce: str,
        expiry: int,
        chain_id: int,
        contract_address: str,
    ) -> str:
        """
        Simulate BCS-serialized message hashing for SUI (SHA3-256).

        Production: use ``pysui`` or custom BCS serializer with SHA3-256.
        """
        type_tag = b"aether::rewards::ClaimProof"
        type_tag_len = self._uleb128_encode(len(type_tag))

        user_bytes = bytes.fromhex(user.removeprefix("0x").lower().zfill(64))

        action_bytes = action_type.encode("utf-8")
        action_len = self._uleb128_encode(len(action_bytes))

        module_bytes = bytes.fromhex(
            contract_address.removeprefix("0x").lower().zfill(64)
        )

        packed = b"".join([
            type_tag_len,
            type_tag,
            user_bytes,
            action_len,
            action_bytes,
            struct.pack("<Q", amount),
            bytes.fromhex(nonce),
            struct.pack("<Q", expiry),
            module_bytes,
        ])
        return self._hash_sha3_256(packed)

    # -- NEAR message hash -------------------------------------------------

    def _build_near_message_hash(
        self,
        user: str,
        action_type: str,
        amount: int,
        nonce: str,
        expiry: int,
        chain_id: int,
        contract_address: str,
    ) -> str:
        """
        Simulate Borsh-serialized message hashing for NEAR (SHA-256).

        Production: use ``borsh-python`` or ``near-api-py`` for proper
        serialization.
        """
        method_name = b"claim_reward"
        account_id = user.encode("utf-8")
        action_bytes = action_type.encode("utf-8")
        contract_id = contract_address.encode("utf-8")

        packed = b"".join([
            struct.pack("<I", len(method_name)),
            method_name,
            struct.pack("<I", len(account_id)),
            account_id,
            struct.pack("<I", len(action_bytes)),
            action_bytes,
            struct.pack("<QQ", amount, 0),
            bytes.fromhex(nonce),
            struct.pack("<Q", expiry),
            struct.pack("<I", len(contract_id)),
            contract_id,
        ])
        return self._hash_sha256(packed)

    # -- TVM (TRON) message hash -------------------------------------------

    def _build_tvm_message_hash(
        self,
        user: str,
        action_type: str,
        amount: int,
        nonce: str,
        expiry: int,
        chain_id: int,
        contract_address: str,
    ) -> str:
        """
        TRON uses keccak256 + secp256k1 ECDSA, same as EVM.

        Production: use ``tronpy`` for proper keccak256 hashing and signing.
        """
        user_hex = self._normalize_tron_address(user)
        contract_hex = self._normalize_tron_address(contract_address)

        packed = b"".join([
            bytes.fromhex(user_hex.zfill(40)),
            action_type.encode("utf-8"),
            struct.pack(">Q", amount),
            bytes.fromhex(nonce),
            struct.pack(">Q", expiry),
            struct.pack(">Q", chain_id),
            bytes.fromhex(contract_hex.zfill(40)),
        ])
        return self._hash_keccak256(packed)  # TVM is EVM-compatible

    # -- Cosmos message hash -----------------------------------------------

    def _build_cosmos_message_hash(
        self,
        user: str,
        action_type: str,
        amount: int,
        nonce: str,
        expiry: int,
        chain_id: int,
        contract_address: str,
    ) -> str:
        """
        Simulate Amino JSON canonical message hashing for Cosmos (SHA-256).

        Production: use ``cosmpy`` or ``cosmos-sdk-python`` for proper
        Amino/Protobuf serialization.
        """
        sign_doc = {
            "account_number": "0",
            "chain_id": str(chain_id),
            "fee": {
                "amount": [{"amount": "0", "denom": "uatom"}],
                "gas": "200000",
            },
            "memo": "",
            "msgs": [
                {
                    "type": "aether/ClaimReward",
                    "value": {
                        "action_type": action_type,
                        "amount": str(amount),
                        "claimant": user,
                        "contract": contract_address,
                        "expiry": str(expiry),
                        "nonce": nonce,
                    },
                }
            ],
            "sequence": "0",
        }
        canonical = json.dumps(sign_doc, sort_keys=True, separators=(",", ":"))
        return self._hash_sha256(canonical.encode("utf-8"))

    # -- address derivation ------------------------------------------------

    @staticmethod
    def _derive_address(private_key_hex: str, vm_type: VMType) -> str:
        """
        Derive a pseudo-address from the private key for each VM type.

        Production: derive the actual public key using the chain's curve
        (secp256k1 for EVM/BTC/TRON/Cosmos, Ed25519 for SVM/MoveVM/NEAR).
        """
        key_bytes = bytes.fromhex(private_key_hex.removeprefix("0x"))
        domain = f"{private_key_hex}:{vm_type.value}".encode("utf-8")
        addr_hash = hashlib.sha256(domain).hexdigest()

        if vm_type == VMType.EVM:
            return f"0x{addr_hash[:40]}"
        elif vm_type == VMType.TVM:
            return f"0x{addr_hash[:40]}"
        elif vm_type == VMType.SVM:
            raw_bytes = bytes.fromhex(addr_hash[:64])
            return _base58_encode(raw_bytes)
        elif vm_type == VMType.BITCOIN:
            return f"1{addr_hash[:33]}"
        elif vm_type == VMType.MOVEVM:
            return f"0x{addr_hash[:64]}"
        elif vm_type == VMType.NEAR:
            return f"{addr_hash[:20]}.near"
        elif vm_type == VMType.COSMOS:
            return f"cosmos1{addr_hash[:38]}"
        else:
            return f"0x{addr_hash[:40]}"

    @staticmethod
    def _null_address(vm_type: VMType = None) -> str:
        """Return a null/zero address in the format expected by the VM."""
        if vm_type is None or vm_type == VMType.EVM:
            return "0x" + "0" * 40
        elif vm_type == VMType.TVM:
            return "0x" + "0" * 40
        elif vm_type == VMType.SVM:
            return "1" * 32
        elif vm_type == VMType.BITCOIN:
            return "1" + "0" * 33
        elif vm_type == VMType.MOVEVM:
            return "0x" + "0" * 64
        elif vm_type == VMType.NEAR:
            return "0" * 20 + ".near"
        elif vm_type == VMType.COSMOS:
            return "cosmos1" + "0" * 38
        else:
            return "0x" + "0" * 40

    # -- chain-specific normalization helpers -------------------------------

    @staticmethod
    def _normalize_solana_pubkey(address: str) -> bytes:
        """
        Normalize a Solana public key to 32 bytes.

        Accepts hex-encoded (with or without 0x prefix) or base58-encoded
        public keys.
        """
        clean = address.removeprefix("0x")
        try:
            raw = bytes.fromhex(clean)
            if len(raw) == 32:
                return raw
            return hashlib.sha256(raw).digest()
        except ValueError:
            return hashlib.sha256(address.encode("utf-8")).digest()

    @staticmethod
    def _normalize_tron_address(address: str) -> str:
        """
        Normalize a TRON address to a 40-char hex string.

        Handles 0x-prefixed hex, 41-prefixed hex (TRON convention), and
        T-prefixed Base58Check (wire format).
        """
        clean = address.strip()

        if clean.startswith("0x") or clean.startswith("0X"):
            return clean[2:].lower()
        if clean.startswith("41") and len(clean) == 42:
            return clean[2:].lower()
        if clean.startswith("T"):
            return hashlib.sha256(clean.encode("utf-8")).hexdigest()[:40]

        return clean.lower()

    @staticmethod
    def _bitcoin_varint(n: int) -> bytes:
        """Encode an integer as a Bitcoin variable-length integer."""
        if n < 0xFD:
            return struct.pack("<B", n)
        elif n <= 0xFFFF:
            return b"\xfd" + struct.pack("<H", n)
        elif n <= 0xFFFFFFFF:
            return b"\xfe" + struct.pack("<I", n)
        else:
            return b"\xff" + struct.pack("<Q", n)

    @staticmethod
    def _uleb128_encode(value: int) -> bytes:
        """Encode an unsigned integer as ULEB128 (used in BCS serialization)."""
        result = bytearray()
        while value >= 0x80:
            result.append((value & 0x7F) | 0x80)
            value >>= 7
        result.append(value & 0x7F)
        return bytes(result)
