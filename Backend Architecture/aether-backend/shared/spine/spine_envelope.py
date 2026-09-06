"""Common Spine Envelope — Python twin of the ADR-011 D3 authored contract.

TS twin: ``packages/shared/spine-envelope.ts`` (HAND-AUTHORED — never emitted by
``scripts/generate_platform_contracts.py``). Canonical field set and the
no-producer ``@unpopulated`` set are enforced by
``tests/unit/test_spine_envelope_parity.py``.

The SpineEnvelope composes canonical primitives and redefines nothing:
``subject_refs`` reuses :class:`~services.operational_intelligence.models.EntityRef`
and ``evidence_refs`` reuses
:class:`~services.operational_intelligence.models.EvidenceRef` — the canonical
Python mirrors of ``packages/shared/entities.ts`` and
``packages/shared/operational-intelligence.ts`` (single-monolith reuse, same as
``shared/intelligence_projections/contracts.py``).

Field parity invariant: ``SPINE_ENVELOPE_FIELDS`` is the ordered canonical field
set and MUST equal, field-for-field and in order, the ``SpineEnvelope``
interface body in the TS twin and the fields of :class:`SpineEnvelope` below.
Fields with no producer yet (``identity_watermark``, ``rights_decision_ref``)
are declared present-but-unpopulated and listed in
``SPINE_ENVELOPE_UNPOPULATED_FIELDS``; no producer is claimed until one ships
(ADR-011 D3; SPINE_P0_ARCHITECTURE.md §6).
"""

from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

# Reused canonical primitives (never redefined here) — mirrors the TS twin
# importing ``EntityRef`` from ``./entities`` and ``EvidenceRef`` from
# ``./operational-intelligence``.
from services.operational_intelligence.models import EntityRef, EvidenceRef

# ── Canonical field spec (order mirrors the TS interface body exactly) ──────

SPINE_ENVELOPE_FIELDS: tuple[str, ...] = (
    "tenant_id",
    "request_id",
    "scope_ref",
    "subject_refs",
    "as_of",
    "valid_time",
    "identity_watermark",
    "data_watermark",
    "policy_ref",
    "consent_decision_ref",
    "rights_decision_ref",
    "evidence_refs",
    "quality",
    "contract_versions",
    "model_refs",
    "lineage_refs",
)

# No-producer fields declared present-but-unpopulated (@unpopulated in the TS
# twin). Mirror of the ``spineEnvelopeUnpopulatedFields`` const.
SPINE_ENVELOPE_UNPOPULATED_FIELDS: frozenset[str] = frozenset({
    "identity_watermark",
    "rights_decision_ref",
})

# ── Quality / availability statement (ADR-011 D3; SPINE_P0_ARCHITECTURE §6) ──


class SpineEnvelopeQuality(BaseModel):
    """Availability/quality statement carried on every SpineEnvelope.

    Mirrors ``SpineEnvelopeQuality`` in the TS twin. The ``state`` values are
    the publish states the architecture names — a not-yet-complete spine
    publishes ``degraded``/``unavailable``/``unknown``/``not_applicable``
    through the same envelope instead of inventing behavior.
    """

    model_config = ConfigDict(extra="forbid")

    state: Literal["available", "degraded", "unavailable", "unknown", "not_applicable"]
    limitations: list[str] = Field(default_factory=list)


# ── SpineEnvelope model ──────────────────────────────────────────────────────


class SpineEnvelope(BaseModel):
    """The common spine envelope (ADR-011 D3).

    One governed envelope every cross-spine interaction resolves to. Every
    field is declared present; fields without a producer yet are present-but-
    ``None`` and listed in :data:`SPINE_ENVELOPE_UNPOPULATED_FIELDS`.
    """

    model_config = ConfigDict(extra="forbid")

    # ── Identity / scope ──
    tenant_id: str
    request_id: str
    scope_ref: str
    subject_refs: list[EntityRef]
    # ── Temporal context ──
    as_of: str  # canonical UTC instant (ISO-8601), point-in-time / replay
    # TS twin types valid_time as ``TemporalRange | null`` (temporal.ts). No
    # Python TemporalRange twin exists in shared/temporal yet, so the mirror
    # carries the canonical half-open instant interval shape as a dict
    # ({kind, start, endExclusive}); field presence is what parity asserts.
    valid_time: Optional[dict[str, Any]] = None
    identity_watermark: Optional[str] = None  # @unpopulated — no producer yet
    data_watermark: Optional[str] = None
    # ── Policy / consent / rights refs ──
    policy_ref: Optional[str] = None
    consent_decision_ref: Optional[str] = None
    rights_decision_ref: Optional[str] = None  # @unpopulated — no producer yet
    # ── Evidence / quality / versions / lineage ──
    evidence_refs: list[EvidenceRef]
    quality: SpineEnvelopeQuality
    contract_versions: dict[str, str]
    model_refs: list[str]
    lineage_refs: list[str]


__all__ = [
    "SPINE_ENVELOPE_FIELDS",
    "SPINE_ENVELOPE_UNPOPULATED_FIELDS",
    "SpineEnvelopeQuality",
    "SpineEnvelope",
]
