"""Fraud-decision evidence helpers (canonical EvidenceRef convergence).

The fraud package previously declared a divergent, fraud-local
``EvidenceRef`` (``ref_id`` / ``ref_type`` / ``ref_source`` / ``description`` /
``metadata``) in ``services/fraud/models.py``. That class is removed; every
fraud evidence ref now uses the canonical
``services.operational_intelligence.models.EvidenceRef``
(``id`` / ``type`` / ``source`` / ``observedAt`` / ``confidence`` / ``uri``,
with ``type`` validated against the canonical ``EvidenceType``).

Because ``FraudDecision.evidence_refs`` is persisted JSONB, rows written before
the convergence may still hold the OLD shape. This module provides the ONE-WAY
legacy compat loader: old-shape JSONB reads are mapped to canonical-shaped
dicts. New code always writes canonical shape; nothing here converts canonical
back to legacy.

Mapping policy for legacy values with no canonical home:

* ``ref_id``      → ``id`` (kept verbatim; a UUID fallback is generated only if
  absent — legacy writes always persisted a generated ``ref_id``).
* ``ref_type``    → ``type`` via ``LEGACY_REF_TYPE_TO_EVIDENCE_TYPE``. The
  canonical ``EvidenceRef.type`` is validated against ``EvidenceType``, so a
  legacy ``ref_type`` with no honest canonical rendering would be rejected by
  the model. Such rows are DROPPED (never fabricated as ``model_output`` — that
  would assert provenance the legacy row did not record).
* ``ref_source``  → ``source``.
* ``description`` → ``uri`` only when it already looks like a URI; otherwise
  dropped (the canonical shape has no free-form description slot).
* ``metadata``    → dropped (no canonical slot; nothing downstream reads it).
"""

from __future__ import annotations

import uuid
from typing import Any, Optional, get_args

from services.operational_intelligence.models import EvidenceType

# Detector signal names → canonical EvidenceType. Mirrors the per-signal
# rendering in services/fraud_networks/evidence.py (the same detector outputs
# land on fraud-network members and on fraud decisions), so one signal renders
# one way across both surfaces.
SIGNAL_TO_EVIDENCE_TYPE: dict[str, str] = {
    "shared_device": "relationship",
    "shared_ip": "relationship",
    "shared_wallet": "relationship",
    "circular_transfer": "transaction",
    "split_merge": "transaction",
    "reward_farming": "transaction",
    "agentic_delegation_abuse": "relationship",
    "commerce_abuse": "transaction",
}

# Legacy ``ref_type`` string values (the fraud-local EvidenceRef documented
# "session", "transfer", "wallet_link", "reward_event", "delegation", "order";
# the fraud evaluator also persisted raw detector signal names) → canonical
# EvidenceType. Unmappable values are intentionally absent so the loader DROPS
# those rows (see module docstring).
LEGACY_REF_TYPE_TO_EVIDENCE_TYPE: dict[str, str] = {
    "session": "event",
    "transfer": "transaction",
    "wallet_link": "relationship",
    "reward_event": "event",
    "delegation": "relationship",
    "order": "transaction",
    **SIGNAL_TO_EVIDENCE_TYPE,
}

_CANONICAL_EVIDENCE_TYPES: frozenset[str] = frozenset(get_args(EvidenceType))
_LEGACY_KEYS: frozenset[str] = frozenset(
    {"ref_id", "ref_type", "ref_source", "description", "metadata"}
)
_CANONICAL_KEYS: frozenset[str] = frozenset({"id", "type", "source"})

_URI_SCHEMES: tuple[str, ...] = ("http://", "https://", "aether://", "evidence://", "file://")


def _is_canonical(raw: dict[str, Any]) -> bool:
    return _CANONICAL_KEYS.issubset(raw.keys()) and not _LEGACY_KEYS.intersection(raw.keys())


def _looks_like_uri(value: object) -> bool:
    return isinstance(value, str) and value.startswith(_URI_SCHEMES)


def normalize_legacy_evidence_ref(raw: Any) -> Optional[dict[str, Any]]:
    """Convert one persisted evidence-ref dict to canonical shape.

    Returns a canonical-shaped dict (safe to hand to ``EvidenceRef(**dict)``),
    the same dict unchanged when it is already canonical (new-shape
    round-trip), or ``None`` when the row is unrepresentable under the
    canonical vocabulary and must be dropped.
    """
    if not isinstance(raw, dict):
        return None
    if _is_canonical(raw):
        # New-shape row (or an already-converted one): pass through unchanged.
        return dict(raw)
    if not _LEGACY_KEYS.intersection(raw.keys()):
        # Neither canonical nor legacy-shaped — do not guess.
        return None

    out: dict[str, Any] = {}

    ref_id = raw.get("ref_id")
    out["id"] = ref_id if isinstance(ref_id, str) and ref_id else str(uuid.uuid4())

    ref_type = raw.get("ref_type")
    canonical_type = (
        LEGACY_REF_TYPE_TO_EVIDENCE_TYPE.get(ref_type)
        if isinstance(ref_type, str)
        else None
    )
    if canonical_type is None or canonical_type not in _CANONICAL_EVIDENCE_TYPES:
        # No honest rendering under the canonical EvidenceType vocabulary.
        return None
    out["type"] = canonical_type

    ref_source = raw.get("ref_source")
    out["source"] = (
        ref_source if isinstance(ref_source, str) and ref_source else "fraud_evaluator"
    )

    # description → uri only when it is already a URI; the free-form legacy
    # description is otherwise dropped (canonical EvidenceRef has no slot).
    description = raw.get("description")
    if _looks_like_uri(description):
        out["uri"] = description

    # metadata has no canonical slot and nothing downstream reads it → dropped.
    return out


def normalize_persisted_evidence_refs(raw: Any) -> list[dict[str, Any]]:
    """Normalize a persisted ``evidence_refs`` JSONB value to canonical shape.

    Accepts a list of per-ref dicts, a single dict, ``None``, or ``[]`` (all
    shapes a JSONB column may hold) and returns a list of canonical-shaped
    dicts — legacy rows converted, canonical rows passed through, unrepresentable
    rows dropped.
    """
    if raw is None:
        return []
    items = raw if isinstance(raw, list) else [raw]
    normalized: list[dict[str, Any]] = []
    for item in items:
        converted = normalize_legacy_evidence_ref(item)
        if converted is not None:
            normalized.append(converted)
    return normalized


__all__ = [
    "SIGNAL_TO_EVIDENCE_TYPE",
    "LEGACY_REF_TYPE_TO_EVIDENCE_TYPE",
    "normalize_legacy_evidence_ref",
    "normalize_persisted_evidence_refs",
]
