"""Aether Backend — Oracle Proof Signer using secp256k1 signatures."""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, utils

from services.oracle.base_signer import BaseProofSigner
from shared.logger.logger import get_logger, metrics

logger = get_logger("aether.service.oracle.signer")


@dataclass(frozen=True)
class ProofConfig:
    signer_private_key: str
    contract_address: str
    chain_id: int = 1
    proof_expiry_seconds: int = 3600


@dataclass
class RewardProof:
    user: str
    action_type: str
    amount_wei: int
    nonce: str
    expiry: int
    chain_id: int
    contract_address: str
    signature: str
    message_hash: str
    signer_public_key: str = ""

    def to_dict(self) -> dict:
        return self.__dict__.copy()

    @classmethod
    def from_dict(cls, data: dict) -> "RewardProof":
        return cls(**data)


class OracleSigner(BaseProofSigner):
    def __init__(self, config: ProofConfig) -> None:
        super().__init__(config.signer_private_key)
        self._config = config
        self._private_key = self._load_private_key(config.signer_private_key)
        self._public_key = self._private_key.public_key()
        self._signer_public_key = self._public_bytes(self._public_key)
        self._signer_address = self._derive_address(self._public_key)
        logger.info(
            "OracleSigner initialised: chain_id=%s contract=%s signer=%s",
            config.chain_id,
            config.contract_address,
            self._signer_address,
        )

    @property
    def signer_address(self) -> str:
        return self._signer_address

    @property
    def signer_public_key(self) -> str:
        return self._signer_public_key

    async def generate_proof(self, user: str, action_type: str, amount_wei: int) -> RewardProof:
        self._validate_proof_inputs(user, amount_wei)
        nonce, expiry = self._generate_nonce_and_expiry(self._config.proof_expiry_seconds)
        message_hash = self._build_message_hash(user, action_type, amount_wei, nonce, expiry)
        signature = self._sign_digest(message_hash)
        proof = RewardProof(
            user=user,
            action_type=action_type,
            amount_wei=amount_wei,
            nonce=f"0x{nonce}",
            expiry=expiry,
            chain_id=self._config.chain_id,
            contract_address=self._config.contract_address,
            signature=f"0x{signature}",
            message_hash=f"0x{message_hash}",
            signer_public_key=f"0x{self._signer_public_key}",
        )
        metrics.increment("oracle_proofs_generated", labels={"chain_id": str(self._config.chain_id)})
        return proof

    async def verify_proof(self, proof: RewardProof) -> bool:
        if int(time.time()) > proof.expiry:
            return False
        try:
            public_key = self._load_public_key(proof.signer_public_key)
            if self._derive_address(public_key).lower() != self._signer_address.lower():
                return False
            digest = bytes.fromhex(proof.message_hash.removeprefix("0x"))
            raw_signature = bytes.fromhex(proof.signature.removeprefix("0x"))
            if len(raw_signature) != 64:
                return False
            r = int.from_bytes(raw_signature[:32], "big")
            s = int.from_bytes(raw_signature[32:], "big")
            signature = utils.encode_dss_signature(r, s)
            public_key.verify(signature, digest, ec.ECDSA(utils.Prehashed(hashes.SHA256())))
            return True
        except (ValueError, InvalidSignature):
            return False
        finally:
            metrics.increment("oracle_proofs_verified", labels={"chain_id": str(proof.chain_id)})

    def _build_message_hash(self, user: str, action_type: str, amount_wei: int, nonce: str, expiry: int) -> str:
        packed = b"".join([
            bytes.fromhex(user.removeprefix("0x").lower()),
            action_type.encode("utf-8"),
            amount_wei.to_bytes(32, "big"),
            bytes.fromhex(nonce),
            expiry.to_bytes(32, "big"),
            self._config.chain_id.to_bytes(32, "big"),
            bytes.fromhex(self._config.contract_address.removeprefix("0x").lower()),
        ])
        return hashlib.sha256(packed).hexdigest()

    def _sign_digest(self, digest_hex: str) -> str:
        digest = bytes.fromhex(digest_hex)
        signature_der = self._private_key.sign(digest, ec.ECDSA(utils.Prehashed(hashes.SHA256())))
        r, s = utils.decode_dss_signature(signature_der)
        return (r.to_bytes(32, "big") + s.to_bytes(32, "big")).hex()

    @staticmethod
    def _load_private_key(private_key_hex: str) -> ec.EllipticCurvePrivateKey:
        value = int(private_key_hex.removeprefix("0x"), 16)
        return ec.derive_private_key(value, ec.SECP256K1())

    @staticmethod
    def _load_public_key(public_key_hex: str) -> ec.EllipticCurvePublicKey:
        data = bytes.fromhex(public_key_hex.removeprefix("0x"))
        return ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256K1(), data)

    @staticmethod
    def _public_bytes(public_key: ec.EllipticCurvePublicKey) -> str:
        return public_key.public_bytes(
            encoding=serialization.Encoding.X962,
            format=serialization.PublicFormat.CompressedPoint,
        ).hex()

    @classmethod
    def _derive_address(cls, public_key: ec.EllipticCurvePublicKey) -> str:
        digest = hashlib.sha256(cls._public_bytes(public_key).encode("ascii")).hexdigest()
        return f"0x{digest[-40:]}"
