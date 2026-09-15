"""Rights Authority → spine/graph propagation SEAM (called by the producer).

The Rights Authority produces a durable, immutable :class:`RightsDecision`; this
module exposes the narrow surface the spine/graph PROPAGATION PRODUCER
(``services/rights_authority/propagation.py``) calls so that resolved decision
can ride cross-spine artifacts:

- :func:`rights_envelope_fields` — returns the ``SpineEnvelope`` field values
  the Rights Authority supplies for one decision (``rights_decision_ref`` plus
  an optional :class:`~services.operational_intelligence.models.EvidenceRef`
  describing the decision record), given the decision and the artifact/subject
  context of the governed material interaction.
- :func:`apply_rights_ref` — sets ``SpineEnvelope.rights_decision_ref`` on an
  envelope. This seam never calls it itself; the producer does.

Architectural boundary:
- ``SpineEnvelope.rights_decision_ref`` is no longer present-but-unpopulated: it
  LEFT ``SPINE_ENVELOPE_UNPOPULATED_FIELDS`` (``shared/spine/spine_envelope.py``)
  and lost its ``@unpopulated`` tag in the hand-authored TS twin
  (``packages/shared/spine-envelope.ts``) when the propagation producer shipped
  (blueprint §11 and §17 Phase 3). The field is still ``null`` on every
  interaction no rights gate ran for — the seam does not populate it by itself,
  and neither does anything here get auto-wired.
- The graph companion is ``Propagation→MutationIntent.rights_decision_ref`` →
  ``MutationRecord.rights_decision_ref`` → ``graph_mutation_ledger``, via the
  same producer.

Everything in this module is deterministic, env-safe, and additive.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Optional, Tuple

from services.operational_intelligence.models import EntityRef, EvidenceRef
from services.rights_authority.contracts import RightsDecision
from shared.spine.spine_envelope import SpineEnvelope

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

    Intended to be called by the spine producer
    (:mod:`services.rights_authority.propagation`) once it has resolved a
    decision. Fails closed on an empty/whitespace ref so a producer can never
    stamp an empty governance reference onto an envelope.
    """
    if not decision_id or not decision_id.strip():
        raise ValueError("rights_decision_ref must be a non-empty rdec_... identity")
    envelope.rights_decision_ref = decision_id
    return envelope
