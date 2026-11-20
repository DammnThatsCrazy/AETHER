"""Minimal CBOR (RFC 8949) decoder for App Attest attestation objects.

Supports the subset Apple uses: unsigned / negative integers, byte and text
strings (definite length), arrays, maps, simple values. Indefinite lengths,
tags beyond pass-through and floats are rejected. Bounded to defend against
hostile input.
"""

from __future__ import annotations

from typing import Any

MAX_DEPTH = 16
MAX_ITEMS = 4096


class CBORError(ValueError):
    pass


def _length(data: bytes, pos: int, info: int) -> tuple[int, int]:
    if info < 24:
        return info, pos
    sizes = {24: 1, 25: 2, 26: 4, 27: 8}
    if info not in sizes:
        raise CBORError("unsupported length encoding")
    n = sizes[info]
    if pos + n > len(data):
        raise CBORError("truncated length")
    return int.from_bytes(data[pos:pos + n], "big"), pos + n


def _decode(data: bytes, pos: int, depth: int) -> tuple[Any, int]:
    if depth > MAX_DEPTH:
        raise CBORError("nesting too deep")
    if pos >= len(data):
        raise CBORError("truncated item")
    head = data[pos]
    major, info = head >> 5, head & 0x1F
    pos += 1
    if major in (0, 1):
        value, pos = _length(data, pos, info)
        return (value if major == 0 else -1 - value), pos
    if major in (2, 3):
        n, pos = _length(data, pos, info)
        if pos + n > len(data):
            raise CBORError("truncated string")
        raw = data[pos:pos + n]
        pos += n
        if major == 2:
            return bytes(raw), pos
        try:
            return raw.decode("utf-8"), pos
        except UnicodeDecodeError as exc:
            raise CBORError("bad utf-8") from exc
    if major == 4:
        n, pos = _length(data, pos, info)
        if n > MAX_ITEMS:
            raise CBORError("array too large")
        items = []
        for _ in range(n):
            item, pos = _decode(data, pos, depth + 1)
            items.append(item)
        return items, pos
    if major == 5:
        n, pos = _length(data, pos, info)
        if n > MAX_ITEMS:
            raise CBORError("map too large")
        out: dict[Any, Any] = {}
        for _ in range(n):
            key, pos = _decode(data, pos, depth + 1)
            if isinstance(key, (list, dict)):
                raise CBORError("unhashable map key")
            value, pos = _decode(data, pos, depth + 1)
            out[key] = value
        return out, pos
    if major == 6:
        _tag, pos = _length(data, pos, info)
        return _decode(data, pos, depth + 1)
    if major == 7:
        simple = {20: False, 21: True, 22: None}
        if info in simple:
            return simple[info], pos
    raise CBORError("unsupported CBOR item")


def decode(data: bytes) -> Any:
    value, pos = _decode(bytes(data), 0, 0)
    if pos != len(data):
        raise CBORError("trailing bytes")
    return value


__all__ = ["CBORError", "decode"]
