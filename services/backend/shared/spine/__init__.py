"""Common Spine Envelope shared contracts.

Owns the ADR-011 D3 :class:`~shared.spine.spine_envelope.SpineEnvelope` — the
governed envelope every cross-spine interaction resolves to — plus the ordered
canonical field set (:data:`~shared.spine.spine_envelope.SPINE_ENVELOPE_FIELDS`)
and the no-producer ``@unpopulated`` field set
(:data:`~shared.spine.spine_envelope.SPINE_ENVELOPE_UNPOPULATED_FIELDS`). TS
twin: ``packages/shared/spine-envelope.ts`` (hand-authored). It composes the
canonical ``EntityRef`` / ``EvidenceRef`` primitives — it never redefines them.
"""

from shared.spine.spine_envelope import (
    SPINE_ENVELOPE_FIELDS,
    SPINE_ENVELOPE_UNPOPULATED_FIELDS,
    SpineEnvelope,
    SpineEnvelopeQuality,
)

__all__ = [
    "SPINE_ENVELOPE_FIELDS",
    "SPINE_ENVELOPE_UNPOPULATED_FIELDS",
    "SpineEnvelope",
    "SpineEnvelopeQuality",
]
