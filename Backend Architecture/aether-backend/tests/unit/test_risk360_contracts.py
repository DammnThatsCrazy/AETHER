"""Risk360 Phase-3 contract tests.

Verifies the risk domain contracts import ZERO duplicate canonical primitives,
fail closed on unknown fields (extra="forbid"), never fabricate a zero for a
missing dimension, and produce a deterministic ``context_hash`` on
:class:`RiskAssessmentRun` for equal computation contexts.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

BACKEND_ROOT = Path(__file__).resolve().parents[2]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

os.environ.setdefault("AETHER_ENV", "local")
os.environ.setdefault("JWT_SECRET", "test-secret")

import services.operational_intelligence.models as oi_models  # noqa: E402
from services.operational_intelligence.models import (  # noqa: E402
    EntityRef as _OI_EntityRef,
)
from services.operational_intelligence.models import EvidenceRef as _OI_EvidenceRef  # noqa: E402
from services.operational_intelligence.models import GraphSnapshotRef as _OI_GraphSnapshotRef  # noqa: E402
from services.risk360.contracts import (  # noqa: E402
    EpistemicStatus,
    EntityRef,
    EvidenceRef,
    ExposureAssessment,
    GraphSnapshotRef,
    MonetaryAmount,
    RiskAssessment,
    RiskAssessmentRun,
    RiskComponent,
    RiskSignal,
    RiskVector,
    ValueState,
    requires_value,
)
from shared.computation.context import ComputationContext  # noqa: E402
from shared.contracts_models import epistemic as _epistemic_module  # noqa: E402
from shared.contracts_models.epistemic import EpistemicStatus as _OI_EpistemicStatus  # noqa: E402


# ---------------------------------------------------------------------------
# Reuse, never redefine
# ---------------------------------------------------------------------------


def test_contracts_import_zero_duplicate_primitives() -> None:
    assert EvidenceRef is _OI_EvidenceRef
    assert EvidenceRef is oi_models.EvidenceRef
    assert EntityRef is _OI_EntityRef
    assert EntityRef is oi_models.EntityRef
    assert GraphSnapshotRef is _OI_GraphSnapshotRef
    assert GraphSnapshotRef is oi_models.GraphSnapshotRef
    assert EpistemicStatus is _OI_EpistemicStatus
    assert EpistemicStatus is _epistemic_module.EpistemicStatus
    # The re-export is a binding to the canonical home, not a second class.
    assert type(EvidenceRef) is type(oi_models.EvidenceRef)
    assert type(EpistemicStatus) is type(_epistemic_module.EpistemicStatus)


def test_contracts_fail_closed_on_unknown_fields() -> None:
    """extra="forbid": a misspelled field raises instead of silently passing."""
    with pytest.raises(ValidationError):
        RiskSignal(
            signal_id="s1",
            tenant_id="t1",
            subject_kind="entity",
            subject_id="u1",
            risk_dimension="payment",
            source="fraud.signals",
            bogus="extra",  # type: ignore[call-arg]
        )
    with pytest.raises(ValidationError):
        RiskVector(
            components=[],
            bogus="extra",  # type: ignore[call-arg]
        )
    with pytest.raises(ValidationError):
        RiskAssessment(
            assessment_id="a1",
            tenant_id="t1",
            subject_kind="entity",
            subject_id="u1",
            vector=RiskVector(),
            bogus="extra",  # type: ignore[call-arg]
        )


# ---------------------------------------------------------------------------
# RiskSignal
# ---------------------------------------------------------------------------


def test_risk_signal_builds_and_carries_claim_state_confidence_evidence() -> None:
    signal = RiskSignal(
        signal_id="s1",
        tenant_id="tenant-a",
        subject_kind="entity",
        subject_id="usr_1",
        risk_dimension="payment",
        claim_state=EpistemicStatus.INFERRED,
        confidence=0.7,
        evidence_refs=[EvidenceRef(id="ev1", type="transaction", source="ledger")],
        source="fraud.signals",
        detector_version="2.1.0",
        score=0.3,
    )
    assert signal.claim_state is EpistemicStatus.INFERRED
    assert signal.evidence_refs[0] is not None
    assert signal.evidence_refs[0].type == "transaction"
    assert signal.score == 0.3


def test_risk_signal_rejects_unregistered_dimension() -> None:
    with pytest.raises(ValidationError):
        RiskSignal(
            signal_id="s1",
            tenant_id="t1",
            subject_kind="entity",
            subject_id="u1",
            risk_dimension="not_a_real_dimension",
            source="detector",
        )


# ---------------------------------------------------------------------------
# RiskVector / RiskComponent — never a fabricated zero
# ---------------------------------------------------------------------------


def test_risk_component_invariant_forbids_fabricated_zero() -> None:
    # A missing dimension must never carry a score (including 0.0).
    with pytest.raises(ValidationError):
        RiskComponent(dimension="authentication", state=ValueState.MISSING_INPUTS, score=0.0)
    # An unobserved-but-scored component is also illegal.
    with pytest.raises(ValidationError):
        RiskComponent(dimension="authentication", state=ValueState.INSUFFICIENT_DATA, score=0.4)
    # A value-bearing state requires a real score.
    with pytest.raises(ValidationError):
        RiskComponent(dimension="authentication", state=ValueState.OBSERVED)
    # An *observed* zero is data-supported and therefore legal.
    ok = RiskComponent(dimension="authentication", state=ValueState.OBSERVED, score=0.0)
    assert ok.score == 0.0


def test_risk_vector_never_zeroes_a_missing_dimension() -> None:
    vec = RiskVector(
        components=[
            RiskComponent(
                dimension="economic",
                state=ValueState.OBSERVED,
                score=0.25,
                claim_state=EpistemicStatus.OBSERVED,
            )
        ]
    )
    # Economic is present.
    assert vec.has_component("economic")
    assert vec.component_for("economic").score == 0.25

    # Authentication has no recorded component — it must report an honest
    # absence (missing/unknown/not_applicable semantics), never a fabricated 0.
    absent = vec.component_for("authentication")
    assert not vec.has_component("authentication")
    assert absent.dimension == "authentication"
    assert absent.score is None
    assert not requires_value(absent.state)
    assert absent.state is ValueState.MISSING_INPUTS
    assert absent.claim_state is EpistemicStatus.UNKNOWN


def test_risk_vector_rejects_duplicate_dimensions() -> None:
    with pytest.raises(ValidationError):
        RiskVector(
            components=[
                RiskComponent(dimension="economic", state=ValueState.OBSERVED, score=0.2),
                RiskComponent(dimension="economic", state=ValueState.MISSING_INPUTS),
            ]
        )


def test_risk_component_uses_canonical_value_state() -> None:
    from shared.measurement import value_states as _vs

    component = RiskComponent(dimension="payment", state=ValueState.NOT_APPLICABLE, score=None)
    assert type(component.state) is type(_vs.ValueState.OBSERVED)
    assert component.state.value == "not_applicable"


# ---------------------------------------------------------------------------
# ExposureAssessment / RiskAssessment
# ---------------------------------------------------------------------------


def test_exposure_assessment_uses_canonical_monetary_amount() -> None:
    from decimal import Decimal

    from services.economic import economic360_contracts as _ec

    exposure = ExposureAssessment(
        tenant_id="tenant-a",
        subject_kind="entity",
        subject_id="usr_1",
        exposed_asset_labels=["wallet"],
        exposed_outcome_labels=["unauthorized_spend"],
        exposed_population_labels=[],
        economic_value=MonetaryAmount(
            amount=Decimal("120.00"), currency="USD", usd_value=Decimal("120.00")
        ),
        claim_state=EpistemicStatus.DERIVED,
        confidence=0.6,
    )
    assert exposure.economic_value is not None
    assert type(exposure.economic_value) is _ec.MonetaryAmount
    assert str(exposure.economic_value.amount) == "120.00"


def test_risk_assessment_builds_with_canonical_refs() -> None:
    assessment = RiskAssessment(
        assessment_id="a1",
        tenant_id="tenant-a",
        subject_kind="entity",
        subject_id="usr_1",
        subject_ref=EntityRef(kind="user", id="usr_1"),
        policy_id="policy_payment_authorization",
        policy_version="3",
        dimensions=["economic"],
        vector=RiskVector(
            components=[
                RiskComponent(
                    dimension="economic",
                    state=ValueState.OBSERVED,
                    score=0.4,
                    claim_state=EpistemicStatus.OBSERVED,
                )
            ]
        ),
        claim_state=EpistemicStatus.DERIVED,
        confidence=0.55,
        evidence_refs=[EvidenceRef(id="ev1", type="event", source="gateway")],
        snapshot=GraphSnapshotRef(graph_snapshot_id="gs1"),
        run_id="run_abc",
    )
    assert assessment.policy_id == "policy_payment_authorization"
    assert assessment.snapshot is not None  # type: ignore[union-attr]
    assert assessment.snapshot.graph_snapshot_id == "gs1"  # type: ignore[union-attr]
    assert assessment.subject_ref is not None  # type: ignore[union-attr]
    assert assessment.subject_ref.kind == "user"  # type: ignore[union-attr]
    # Sparse vector still answers honestly for an unevaluated dimension.
    assert assessment.vector.component_for("model_uncertainty").score is None


# ---------------------------------------------------------------------------
# RiskAssessmentRun — reproducibility over the computation substrate
# ---------------------------------------------------------------------------


def test_risk_assessment_run_context_hash_is_deterministic_for_equal_inputs() -> None:
    ctx_a = ComputationContext(
        tenant_id="tenant-a",
        subject_type="entity",
        subject_id="usr_1",
        as_of="2026-09-03T00:00:00Z",
        policy_version="3",
    )
    ctx_b = ComputationContext(
        tenant_id="tenant-a",
        subject_type="entity",
        subject_id="usr_1",
        as_of="2026-09-03T00:00:00Z",
        policy_version="3",
    )
    run_a = RiskAssessmentRun.from_context(tenant_id="tenant-a", assessment_id="a1", context=ctx_a)
    run_b = RiskAssessmentRun.from_context(tenant_id="tenant-a", assessment_id="a1", context=ctx_b)
    assert run_a.context_hash == run_b.context_hash
    assert run_a.context_hash == ctx_a.context_hash()
    assert run_a.context_hash == ctx_b.context_hash()
    assert len(run_a.context_hash) == 32
    # Equal context, fresh run id: a new run of the same computation is not a
    # fork, but the run id itself is unique.
    assert run_a.run_id != run_b.run_id
    assert run_a.run_id.startswith("run_")
    assert RiskAssessmentRun.make_run_id().startswith("run_")


def test_risk_assessment_run_context_hash_differs_on_input_change() -> None:
    base = ComputationContext(tenant_id="tenant-a", subject_type="entity", subject_id="usr_1")
    changed = ComputationContext(tenant_id="tenant-a", subject_type="entity", subject_id="usr_2")
    assert base.context_hash() != changed.context_hash()
