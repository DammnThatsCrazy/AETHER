"""Aether Backend — Oracle proof verifier using secp256k1 verification."""

from __future__ import annotations

import hashlib
import time

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, utils

from services.oracle.signer import RewardProof
from shared.logger.logger import get_logger

logger = get_logger("aether.service.oracle.verifier")


def verify_reward_proof(proof: RewardProof, expected_signer: str) -> bool:
    if is_proof_expired(proof):
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
        return False
    try:
        public_key = _load_public_key(proof.signer_public_key)
        if _derive_address(public_key).lower() != expected_signer.lower():
            return False
        public_key.verify(
            _decode_signature(proof.signature.removeprefix("0x")),
            bytes.fromhex(actual_hash),
            ec.ECDSA(utils.Prehashed(hashes.SHA256())),
        )
        return True
    except (ValueError, InvalidSignature):
        return False


def is_proof_expired(proof: RewardProof) -> bool:
    return int(time.time()) > proof.expiry


def compute_message_hash(user: str, action_type: str, amount_wei: int, nonce: str, expiry: int, chain_id: int, contract_address: str) -> str:
    packed = b"".join([
        bytes.fromhex(user.removeprefix("0x").lower()),
        action_type.encode("utf-8"),
        amount_wei.to_bytes(32, "big"),
        bytes.fromhex(nonce),
        expiry.to_bytes(32, "big"),
        chain_id.to_bytes(32, "big"),
        bytes.fromhex(contract_address.removeprefix("0x").lower()),
    ])
    return hashlib.sha256(packed).hexdigest()


def _decode_signature(signature_hex: str) -> bytes:
    raw = bytes.fromhex(signature_hex)
    if len(raw) != 64:
        raise ValueError("Expected compact 64-byte secp256k1 signature")
    r = int.from_bytes(raw[:32], "big")
    s = int.from_bytes(raw[32:], "big")
    return utils.encode_dss_signature(r, s)


def _load_public_key(public_key_hex: str) -> ec.EllipticCurvePublicKey:
    data = bytes.fromhex(public_key_hex.removeprefix("0x"))
    return ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256K1(), data)


def _derive_address(public_key: ec.EllipticCurvePublicKey) -> str:
    encoded = public_key.public_bytes(
        encoding=serialization.Encoding.X962,
        format=serialization.PublicFormat.CompressedPoint,
    ).hex()
    digest = hashlib.sha256(encoded.encode("ascii")).hexdigest()
    return f"0x{digest[-40:]}"
