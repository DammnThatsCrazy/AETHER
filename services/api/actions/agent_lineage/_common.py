"""Shared primitives for the principal <-> agent lineage engine.

Timestamps are normalised to epoch seconds internally so evidence arriving in
any order (and with mixed ISO spellings) folds to the same state; opaque cursors
are bound to the query scope that issued them so one cursor cannot be replayed
against a different tenant, principal or filter set.
"""
from __future__ import annotations

import base64
import hashlib
import json
from datetime import datetime, timezone
from functools import lru_cache
from typing import Any, Optional

from shared.agent_lineage import vocabulary as vocab

#: Reserved principal bucket for agents and clusters with no attributable
#: principal. Entity ids are namespaced, so this can never collide with one.
UNATTRIBUTED = "unattributed"

#: Materialized-path separator (ASCII unit separator; never part of an id).
PATH_SEP = "\x1f"

EVIDENCE_RANK: dict[str, int] = {c: i for i, c in enumerate(vocab.PRINCIPAL_EVIDENCE_CLASSES)}
PROOF_CLASSES = vocab.PRINCIPAL_PROOF_EVIDENCE_CLASSES
_UNKNOWN_RANK = EVIDENCE_RANK["UNKNOWN"]

_ATTRIBUTION_BY_CLASS = {
    "VERIFIED_AUTHORITY": "verified",
    "DETERMINISTIC_BINDING": "verified",
    "CRYPTOGRAPHICALLY_ATTESTED": "verified",
    "PROVIDER_ASSERTED": "inferred",
    "TENANT_DECLARED": "inferred",
    "BEHAVIORALLY_INFERRED": "inferred",
    "INFRASTRUCTURE_CORRELATED": "suspected_cluster",
    "TEMPORALLY_CORRELATED": "suspected_cluster",
    "UNKNOWN": "unresolved",
}

#: Principal-link confidence ceiling per evidence class. Weak classes can never
#: score at or above a proof class.
LINK_CONFIDENCE: dict[str, float] = {
    "VERIFIED_AUTHORITY": 0.99,
    "DETERMINISTIC_BINDING": 0.95,
    "CRYPTOGRAPHICALLY_ATTESTED": 0.97,
    "PROVIDER_ASSERTED": 0.55,
    "TENANT_DECLARED": 0.5,
    "BEHAVIORALLY_INFERRED": 0.35,
    "INFRASTRUCTURE_CORRELATED": 0.25,
    "TEMPORALLY_CORRELATED": 0.15,
    "UNKNOWN": 0.0,
}


def rank_of(evidence_class: Optional[str]) -> int:
    return EVIDENCE_RANK.get(evidence_class or "UNKNOWN", _UNKNOWN_RANK)


def class_of(rank: int) -> str:
    return vocab.PRINCIPAL_EVIDENCE_CLASSES[min(rank, _UNKNOWN_RANK)]


def is_proof_class(evidence_class: Optional[str]) -> bool:
    return evidence_class in PROOF_CLASSES


def attribution_for(evidence_class: Optional[str]) -> str:
    return _ATTRIBUTION_BY_CLASS.get(evidence_class or "UNKNOWN", "unresolved")


@lru_cache(maxsize=1 << 16)
def _epoch_str(value: str) -> Optional[float]:
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.timestamp()


def epoch(value: Any) -> Optional[float]:
    """Epoch seconds for an ISO string / datetime / number; ``None`` if unparseable."""
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.timestamp()
    if isinstance(value, str):
        return _epoch_str(value)
    return None


def iso(value: Optional[float]) -> Optional[str]:
    if value is None:
        return None
    return (
        datetime.fromtimestamp(value, timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


def ref(value: Any) -> Optional[str]:
    return value.strip() if isinstance(value, str) and value.strip() else None


def digest_int(text: str) -> int:
    return int.from_bytes(hashlib.blake2b(text.encode("utf-8"), digest_size=8).digest(), "big")


def stable_hash(*parts: Any) -> str:
    payload = json.dumps(parts, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


class LineageQueryError(ValueError):
    """A lineage query was malformed (bad cursor, filter, budget)."""


def encode_cursor(scope: str, key: list[Any]) -> str:
    body = json.dumps({"v": 1, "s": stable_hash(scope)[:8], "k": key}, separators=(",", ":"))
    return base64.urlsafe_b64encode(body.encode("utf-8")).decode("ascii").rstrip("=")


def decode_cursor(token: Optional[str], scope: str) -> Optional[list[Any]]:
    if not token:
        return None
    try:
        padded = token + "=" * (-len(token) % 4)
        body = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")))
        if body.get("v") != 1 or body.get("s") != stable_hash(scope)[:8]:
            raise ValueError("scope mismatch")
        key = body["k"]
        if not isinstance(key, list):
            raise ValueError("bad key")
        return key
    except (ValueError, KeyError, TypeError) as exc:
        raise LineageQueryError("invalid or mismatched cursor") from exc


def clamp_page_size(value: Optional[int]) -> int:
    if value is None:
        return vocab.DEFAULT_PAGE_SIZE
    if value < 1:
        raise LineageQueryError("page_size must be >= 1")
    return min(value, vocab.MAX_PAGE_SIZE)
