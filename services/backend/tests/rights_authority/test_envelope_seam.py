"""Rights Authority → spine/graph envelope SEAM (called by the producer).

Exercises ``services/rights_authority/envelope.py``: the field surface the
propagation producer (``services/rights_authority/propagation.py``) calls so a
resolved ``RightsDecision`` can ride a ``SpineEnvelope``. These tests
deliberately construct a ``SpineEnvelope`` directly and call the seam — they do
NOT claim the seam itself populates anything; the producer round trip is covered
by ``test_propagation_producer.py``.
"""

from __future__ import annotations

import pytest

from services.integrations.data_rights.models import RightsDecisionDisposition
from services.operational_intelligence.models import EntityRef, EvidenceRef
from services.rights_authority.contracts import RightsDecision
from services.rights_authority.envelope import (
    SPINE_EVIDENCE_SOURCE,
    SPINE_EVIDENCE_TYPE,
    apply_rights_ref,
    decision_evidence_ref,
    rights_envelope_fields,
)
from shared.spine.spine_envelope import (
    SPINE_ENVELOPE_UNPOPULATED_FIELDS,
    SpineEnvelope,
    SpineEnvelopeQuality,
)

_TENANT = "tenant_seam"


def _decision(
    *,
    decision_id: str = "rdec_seam_1",
    tenant_id: str = _TENANT,
    evaluated_at: str = "2026-09-07T00:00:00+00:00",
) -> RightsDecision:
    return RightsDecision(
        decision_id=decision_id,
        tenant_id=tenant_id,
        allowed=True,
        disposition=RightsDecisionDisposition.ALLOWED,
        reason_codes=[],
        source_grant_refs=["drg_seam_001"],
        ownership_class="contributed_source",
        permitted_uses=["export"],
        evaluated_at=evaluated_at,
        effective_as_of="2026-09-07T00:00:00+00:00",
    )


def _bare_envelope(*, as_of: str = "2026-09-07T00:00:00+00:00") -> SpineEnvelope:
    """A minimal, valid SpineEnvelope with no rights/evidence populated."""
    return SpineEnvelope(
        tenant_id=_TENANT,
        request_id="req_seam_1",
        scope_ref="scope_seam",
        subject_refs=[],
        as_of=as_of,
        evidence_refs=[],
        quality=SpineEnvelopeQuality(state="available"),
        contract_versions={},
        model_refs=[],
        lineage_refs=[],
    )


# ── Seam function: rights_envelope_fields ─────────────────────────────────────


def test_rights_envelope_fields_returns_decision_id_and_evidence() -> None:
    decision = _decision(decision_id="rdec_alpha")
    fields = rights_envelope_fields(decision)

    # The one spine field the Rights Authority owns is the durable decision ref.
    assert fields.rights_decision_ref == "rdec_alpha"

    # Optionally an EvidenceRef describing the decision record itself.
    assert fields.decision_evidence is not None
    assert isinstance(fields.decision_evidence, EvidenceRef)
    assert fields.decision_evidence.id == "rdec_alpha"
    assert fields.decision_evidence.type == SPINE_EVIDENCE_TYPE == "document"
    assert fields.decision_evidence.source == SPINE_EVIDENCE_SOURCE
    assert fields.decision_evidence.observedAt == decision.evaluated_at


def test_rights_envelope_fields_captures_artifact_and_subject_context() -> None:
    decision = _decision()
    subject = EntityRef(kind="user", id="user_seam_1")
    fields = rights_envelope_fields(
        decision, artifact_ref="art_seam_1", subject_refs=[subject]
    )

    # Context is captured for producer/audit correlation; it is not a spine
    # field claim, so the decision ref stays the decision's own identity.
    assert fields.artifact_ref == "art_seam_1"
    assert fields.subject_refs == (subject,)
    assert fields.rights_decision_ref == decision.decision_id


def test_rights_envelope_fields_can_omit_decision_evidence() -> None:
    fields = rights_envelope_fields(_decision(), include_decision_evidence=False)
    assert fields.rights_decision_ref == "rdec_seam_1"
    assert fields.decision_evidence is None


def test_rights_envelope_fields_is_pure_and_deterministic() -> None:
    decision = _decision()
    subject = EntityRef(kind="user", id="user_seam_1")
    first = rights_envelope_fields(
        decision, artifact_ref="art_seam_1", subject_refs=[subject]
    )
    second = rights_envelope_fields(
        decision, artifact_ref="art_seam_1", subject_refs=[subject]
    )
    assert first == second  # frozen dataclass equality; no env/credentials


def test_decision_evidence_ref_vocabulary_is_stable() -> None:
    decision = _decision(decision_id="rdec_beta")
    ref = decision_evidence_ref(decision)
    assert ref.id == "rdec_beta"
    assert ref.source == SPINE_EVIDENCE_SOURCE
    assert ref.uri == f"rights://decisions/rdec_beta"
    # Same decision → byte-identical evidence ref every call.
    assert decision_evidence_ref(decision) == ref


# ── Seam function: apply_rights_ref ───────────────────────────────────────────


def test_apply_rights_ref_populates_envelope_and_returns_it() -> None:
    envelope = _bare_envelope()
    assert envelope.rights_decision_ref is None

    returned = apply_rights_ref(envelope, "rdec_gamma")

    assert envelope.rights_decision_ref == "rdec_gamma"
    assert returned is envelope  # in-place, chainable


def test_apply_rights_ref_fails_closed_on_empty_ref() -> None:
    envelope = _bare_envelope()
    for empty in ("", "   "):
        with pytest.raises(ValueError):
            apply_rights_ref(envelope, empty)
        assert envelope.rights_decision_ref is None  # never partially stamped


def test_envelope_carries_both_ref_and_decision_evidence() -> None:
    """The propagation producer merges the seam's outputs into a real envelope."""
    decision = _decision(decision_id="rdec_delta")
    envelope = _bare_envelope()

    apply_rights_ref(envelope, decision.decision_id)
    evidence = rights_envelope_fields(decision).decision_evidence
    assert evidence is not None
    envelope.evidence_refs.append(evidence)

    assert envelope.rights_decision_ref == "rdec_delta"
    assert [e.id for e in envelope.evidence_refs] == ["rdec_delta"]


# ── Parity surface: the producer now ships, so the field left the no-producer set


def test_producer_shipped_so_field_is_out_of_the_unpopulated_set() -> None:
    """The propagation producer exists, so ``rights_decision_ref`` is no longer
    ``@unpopulated``: it is out of the Python no-producer set and the TS twin
    (``packages/shared/spine-envelope.ts``) carries a producer reference instead
    of the ``@unpopulated`` tag. The seam itself still populates nothing on its
    own — a fresh ``SpineEnvelope`` has no rights ref until a producer stamps
    one (see ``test_propagation_producer.py``)."""
    assert "rights_decision_ref" not in SPINE_ENVELOPE_UNPOPULATED_FIELDS
    # At least one field is still honestly declared no-producer, so the set's
    # purpose survives (identity_watermark has no producer yet).
    assert SPINE_ENVELOPE_UNPOPULATED_FIELDS
    envelope = _bare_envelope()
    assert envelope.rights_decision_ref is None
    # No seam entry point populates the field by itself; only a real decision
    # ref passed in by a caller does.
    rights_envelope_fields(_decision())
    assert envelope.rights_decision_ref is None
    apply_rights_ref(envelope, "rdec_epsilon")
    assert envelope.rights_decision_ref == "rdec_epsilon"
    assert "rights_decision_ref" not in SPINE_ENVELOPE_UNPOPULATED_FIELDS
