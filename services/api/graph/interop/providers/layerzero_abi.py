"""LayerZero V2 EndpointV2 event decoding — pure-Python ABI byte slicing.

No web3py dependency (matches the x402 verification precedent): topic
constants are keccak hashes of the canonical event signatures, and packet
payloads are decoded with explicit offsets. Provider-native names (GUID,
EID, nonce) appear ONLY here and in the adapter — the canonical model
receives protocol-neutral observations with alias references.

Packet header layout inside PacketSent.encodedPayload (LayerZero V2):
    version   uint8    1 byte
    nonce     uint64   8 bytes
    srcEid    uint32   4 bytes
    sender    bytes32 32 bytes
    dstEid    uint32   4 bytes
    receiver  bytes32 32 bytes
    guid      bytes32 32 bytes   = keccak(nonce ‖ srcEid ‖ sender ‖ dstEid ‖ receiver)
    message   bytes    remainder
"""

from __future__ import annotations

from typing import Any, Optional

from eth_utils import keccak

# Event signatures (LayerZero V2 EndpointV2)
SIG_PACKET_SENT = "PacketSent(bytes,bytes,address)"
SIG_PACKET_VERIFIED = "PacketVerified((uint32,bytes32,uint64),address,bytes32)"
SIG_PACKET_DELIVERED = "PacketDelivered((uint32,bytes32,uint64),address)"

TOPIC_PACKET_SENT = "0x" + keccak(text=SIG_PACKET_SENT).hex()
TOPIC_PACKET_VERIFIED = "0x" + keccak(text=SIG_PACKET_VERIFIED).hex()
TOPIC_PACKET_DELIVERED = "0x" + keccak(text=SIG_PACKET_DELIVERED).hex()


def compute_guid(
    nonce: int, src_eid: int, sender32: bytes, dst_eid: int, receiver32: bytes,
) -> str:
    """GUID = keccak(nonce u64 BE ‖ srcEid u32 BE ‖ sender ‖ dstEid u32 BE ‖ receiver)."""
    if len(sender32) != 32 or len(receiver32) != 32:
        raise ValueError("sender and receiver must be 32-byte values")
    packed = (
        nonce.to_bytes(8, "big")
        + src_eid.to_bytes(4, "big")
        + sender32
        + dst_eid.to_bytes(4, "big")
        + receiver32
    )
    return "0x" + keccak(packed).hex()


def _strip0x(value: str) -> bytes:
    return bytes.fromhex(value[2:] if value.startswith("0x") else value)


def encode_packet(
    nonce: int, src_eid: int, sender32: bytes, dst_eid: int, receiver32: bytes,
    message: bytes, version: int = 1,
) -> bytes:
    """Build a V2 packet payload (used by the fixture generator so the
    decoder and fixtures can never drift)."""
    guid = _strip0x(compute_guid(nonce, src_eid, sender32, dst_eid, receiver32))
    return (
        version.to_bytes(1, "big")
        + nonce.to_bytes(8, "big")
        + src_eid.to_bytes(4, "big")
        + sender32
        + dst_eid.to_bytes(4, "big")
        + receiver32
        + guid
        + message
    )


def decode_packet(payload: bytes) -> dict[str, Any]:
    """Decode a V2 packet header. Raises ValueError on short payloads."""
    if len(payload) < 1 + 8 + 4 + 32 + 4 + 32 + 32:
        raise ValueError(f"packet payload too short: {len(payload)} bytes")
    offset = 0
    version = payload[offset]
    offset += 1
    nonce = int.from_bytes(payload[offset:offset + 8], "big")
    offset += 8
    src_eid = int.from_bytes(payload[offset:offset + 4], "big")
    offset += 4
    sender = payload[offset:offset + 32]
    offset += 32
    dst_eid = int.from_bytes(payload[offset:offset + 4], "big")
    offset += 4
    receiver = payload[offset:offset + 32]
    offset += 32
    guid = payload[offset:offset + 32]
    offset += 32
    message = payload[offset:]
    return {
        "version": version,
        "nonce": nonce,
        "src_eid": src_eid,
        "sender": "0x" + sender.hex(),
        "dst_eid": dst_eid,
        "receiver": "0x" + receiver.hex(),
        "guid": "0x" + guid.hex(),
        "message_hash": "0x" + keccak(message).hex(),
        "message_length": len(message),
    }


def encode_packet_sent_data(
    encoded_payload: bytes, options: bytes, send_library: str,
) -> str:
    """ABI-encode PacketSent event data: (bytes encodedPayload, bytes options,
    address sendLibrary) — two dynamic heads + one static address."""
    def word(value: int) -> bytes:
        return value.to_bytes(32, "big")

    def dyn(value: bytes) -> bytes:
        padded_len = (len(value) + 31) // 32 * 32
        return word(len(value)) + value.ljust(padded_len, b"\x00")

    head_size = 3 * 32
    payload_offset = head_size
    options_offset = payload_offset + 32 + (len(encoded_payload) + 31) // 32 * 32
    library_word = word(int(send_library, 16))
    data = (
        word(payload_offset)
        + word(options_offset)
        + library_word
        + dyn(encoded_payload)
        + dyn(options)
    )
    return "0x" + data.hex()


def decode_packet_sent_data(data_hex: str) -> dict[str, Any]:
    """Decode PacketSent data: dynamic-bytes heads for encodedPayload and
    options, then the send library address."""
    data = _strip0x(data_hex)
    if len(data) < 96:
        raise ValueError("PacketSent data too short")
    payload_offset = int.from_bytes(data[0:32], "big")
    options_offset = int.from_bytes(data[32:64], "big")
    send_library = "0x" + data[64:96][-20:].hex()

    payload_len = int.from_bytes(data[payload_offset:payload_offset + 32], "big")
    encoded_payload = data[payload_offset + 32: payload_offset + 32 + payload_len]
    options_len = int.from_bytes(data[options_offset:options_offset + 32], "big")
    options = data[options_offset + 32: options_offset + 32 + options_len]

    packet = decode_packet(encoded_payload)
    return {"packet": packet, "options": "0x" + options.hex(), "send_library": send_library}


def encode_origin_data(
    src_eid: int, sender32: bytes, nonce: int, receiver: str,
    payload_hash: Optional[bytes] = None,
) -> str:
    """ABI-encode PacketVerified/PacketDelivered data: the Origin tuple
    (uint32,bytes32,uint64) is static, followed by the receiver address and,
    for Verified, the payload hash."""
    def word(value: int) -> bytes:
        return value.to_bytes(32, "big")

    data = (
        word(src_eid)
        + sender32
        + word(nonce)
        + word(int(receiver, 16))
    )
    if payload_hash is not None:
        data += payload_hash
    return "0x" + data.hex()


def decode_origin_data(data_hex: str, expect_payload_hash: bool) -> dict[str, Any]:
    """Decode PacketVerified (with payloadHash) / PacketDelivered data."""
    data = _strip0x(data_hex)
    # Origin tuple (3 words) + receiver (1 word) [+ payloadHash (1 word)]
    minimum = 160 if expect_payload_hash else 128
    if len(data) < minimum:
        raise ValueError(f"origin data too short: {len(data)} bytes")
    src_eid = int.from_bytes(data[0:32], "big")
    sender = data[32:64]
    nonce = int.from_bytes(data[64:96], "big")
    receiver = "0x" + data[96:128][-20:].hex()
    result: dict[str, Any] = {
        "src_eid": src_eid,
        "sender": "0x" + sender.hex(),
        "nonce": nonce,
        "receiver": receiver,
    }
    if expect_payload_hash:
        if len(data) < 160:
            raise ValueError("PacketVerified data missing payload hash")
        result["payload_hash"] = "0x" + data[128:160].hex()
    return result
