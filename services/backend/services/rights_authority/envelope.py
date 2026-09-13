"""Rights Authority → spine/graph propagation SEAM (no producer shipped).

This is a producer **seam**, not a fake producer. The Rights Authority already
produces a durable, immutable :class:`RightsDecision`; this module exposes the
narrow surface a future spine/graph producer calls so that resolved decision
can ride cross-spine artifacts:

- :func:`rights_envelope_fields` — returns the ``SpineEnvelope`` field values
  the Rights Authority would supply for one decision (``rights_decision_ref``
  plus an optional :class:`~services.operational_intelligence.models.EvidenceRef`
  describing the decision record), given the decision and the artifact/subject
  context of the governed material interaction.
- :func:`apply_rights_ref` — sets ``SpineEnvelope.rights_decision_ref`` on an
  envelope. A future producer calls it; this seam never calls it itself.

Architectural boundary (do NOT cross it here):
- ``SpineEnvelope.rights_decision_ref`` remains present-but-unpopulated: it is
  still listed in ``SPINE_ENVELOPE_UNPOPULATED_FIELDS``
  (``shared/spine/spine_envelope.py``), the hand-authored TS twin
  (``packages/shared/spine-envelope.ts``) keeps ``@unpopulated``, and
  ``tests/unit/test_spine_envelope_parity.py`` keeps asserting the no-producer
  set. Shipping a REAL producer — which moves ``rights_decision_ref`` OUT of
  ``SPINE_ENVELOPE_UNPOPULATED_FIELDS``, updates the TS twin, updates the
  parity test, and starts publishing populated envelopes — belongs to the spine
  producer program (``RIGHTS_AUTHORITY_BLUEPRINT.md`` §11 and §17 Phase 3).
  Until then, calling :func:`apply_rights_ref` in shipped production code would
  CLAIM a producer that does not exist, so nothing here is auto-wired.
- The graph-propagation companion seam (carrying ``rights_decision_ref`` on the
  gateway write path) lives in ``shared/graph/mutation_gateway.py``
  (``MutationIntent.rights_decision_ref`` → versioned fact-payload annotation);
  it also does not claim a SpineEnvelope producer.

Everything in this module is deterministic, env-safe, and additive.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Optional, Tuple

from services.operational_intelligence.models import EntityRef, EvidenceRef
from services.rights_authority.contracts import RightsDecision
from shared.spine.spine_envelope import SPINE_ENVELOPE_UNPOPULATED_FIELDS, SpineEnvelope

__all__ = [
    "RightsEnvelopeFields",
    "SPINE_EVIDENCE_SOURCE",
    "SPINE_EVIDENCE_TYPE",
    "SPINE_EVIDENCE_URI_PREFIX",
    "apply_rights_ref",
    "decision_evidence_ref",
    "rights_envelope_fields",
]

# Canonical EvidenceRef vocabulary the Rights Authority would use when it
# references its own durable decision as evidence on a spine envelope.
SPINE_EVIDENCE_SOURCE = "rights_authority.decision"
SPINE_EVIDENCE_TYPE = "document"
SPINE_EVIDENCE_URI_PREFIX = "rights://decisions/"


@dataclass(frozen=True)
class RightsEnvelopeFields:
    """The ``SpineEnvelope`` field values the Rights Authority contributes.

    ``rights_decision_ref`` is the one field the Rights Authority owns on the
    envelope. ``decision_evidence`` (when requested) is an :class:`EvidenceRef`
    a producer should *append* to ``SpineEnvelope.evidence_refs`` — the Rights
    Authority adds to evidence, it never replaces evidence other authorities
    supplied.

    ``artifact_ref`` / ``subject_refs`` are NOT envelope fields: they capture
    the governed material interaction the caller passed in, so the future
    producer (and audit) can correlate the ref with the write it governs.
    """

    rights_decision_ref: str
    decision_evidence: Optional[EvidenceRef] = None
    artifact_ref: Optional[str] = None
    subject_refs: Tuple[EntityRef, ...] = field(default_factory=tuple)


def decision_evidence_ref(decision: RightsDecision) -> EvidenceRef:
    """An :class:`EvidenceRef` pointing at the durable decision record itself.

    The decision id is a ``rdec_...`` durable ref; representing it back as an
    evidence ref (rather than inventing a parallel evidence system) lets a
    governed derivative's evidence lineage resolve to the decision that
    authorized it. ``source``/``type``/``uri`` are stable constants so the same
    decision always produces the identical ref.
    """
    return EvidenceRef(
        id=decision.decision_id,
        type=SPINE_EVIDENCE_TYPE,
        source=SPINE_EVIDENCE_SOURCE,
        observedAt=decision.evaluated_at,
        uri=f"{SPINE_EVIDENCE_URI_PREFIX}{decision.decision_id}",
    )


def rights_envelope_fields(
    decision: RightsDecision,
    *,
    include_decision_evidence: bool = True,
    artifact_ref: Optional[str] = None,
    subject_refs: Optional[Iterable[EntityRef]] = None,
) -> RightsEnvelopeFields:
    """Return the spine-envelope fields the Rights Authority WOULD supply.

    ``decision`` is the resolved/durable :class:`RightsDecision`. The optional
    ``artifact_ref`` / ``subject_refs`` describe the material interaction being
    governed (a graph mutation, export, projection, …) and are captured on the
    returned object for producer/audit correlation; they are not envelope
    fields the Rights Authority claims.

    ``include_decision_evidence=True`` (default) also returns a decision
    :class:`EvidenceRef` to append to the envelope's ``evidence_refs``. This is
    a pure function: identical inputs always return identical values.
    """
    subjects = tuple(subject_refs or ())
    return RightsEnvelopeFields(
        rights_decision_ref=decision.decision_id,
        decision_evidence=decision_evidence_ref(decision)
        if include_decision_evidence
        else None,
        artifact_ref=artifact_ref,
        subject_refs=subjects,
    )


def apply_rights_ref(envelope: SpineEnvelope, decision_id: str) -> SpineEnvelope:
    """Set ``envelope.rights_decision_ref = decision_id`` and return the envelope.

    Intended to be called by the future spine producer once it exists (see the
    module docstring and :data:`SPINE_ENVELOPE_UNPOPULATED_FIELDS` — shipping a
    producer that populates this field is the spine producer program's
    boundary, not this seam's). Fails closed on an empty/whitespace ref so a
    producer can never stamp an empty governance reference onto an envelope.
    """
    if not decision_id or not decision_id.strip():
        raise ValueError("rights_decision_ref must be a non-empty rdec_... identity")
    envelope.rights_decision_ref = decision_id
    return envelope
