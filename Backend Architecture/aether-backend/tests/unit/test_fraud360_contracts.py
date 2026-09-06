"""Fraud360 contract tests (Phase 3): shape, fail-closed, and canonical reuse.

Fraud360 domain contracts are plain pydantic models with ``extra="forbid"``
(NOT ``ContractModel``). They must import — never re-declare — the canonical
primitives (``EvidenceRef``, ``GraphSnapshotRef``, ``MonetaryAmount``,
``EpistemicStatus``), and a ``confirmed`` hypothesis must never be constructed
under a suspicion claim state (no-silent-escalation).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

BACKEND_ROOT = Path(__file__).resolve().parents[2]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import services.economic.economic360_contracts as economic  # noqa: E402
import services.fraud360.contracts as fraud_contracts  # noqa: E402
from services.fraud360.contracts import (  # noqa: E402
    EpistemicStatus,
    EvidenceRef,
    FraudHypothesis,
    FraudHypothesisState,
    FraudPattern,
)
import services.operational_intelligence.models as oi_models  # noqa: E402
import shared.contracts_models.epistemic as epistemic  # noqa: E402


# Canonical primitive names that the fraud contracts may import but must NEVER
# declare a duplicate of.
_CANONICAL_PRIMITIVE_NAMES = frozenset(
    {"EvidenceRef", "EntityRef", "GraphSnapshotRef", "MonetaryAmount", "EpistemicStatus"}
)


def _sample_hypothesis(**overrides) -> FraudHypothesis:
    values = {
        "hypothesis_id": "hyp-1",
        "tenant_id": "tenant-a",
        "subject_kind": "entity",
        "subject_id": "ent_1",
    }
    values.update(overrides)
    return FraudHypothesis(**values)


def test_fraud360_contracts_reuse_canonical_primitives_by_identity():
    """The reused primitives ARE the canonical ones (no second copy)."""
    assert fraud_contracts.EvidenceRef is oi_models.EvidenceRef
    assert fraud_contracts.GraphSnapshotRef is oi_models.GraphSnapshotRef
    assert fraud_contracts.MonetaryAmount is economic.MonetaryAmount
    assert fraud_contracts.EpistemicStatus is epistemic.EpistemicStatus


def test_fraud360_contracts_declare_no_duplicate_primitive_classes():
    """No class in the module body shadows a canonical primitive name."""
    defined_here = {
        cls.__name__
        for cls in vars(fraud_contracts).values()
        if isinstance(cls, type) and cls.__module__ == "services.fraud360.contracts"
    }
    assert defined_here.isdisjoint(_CANONICAL_PRIMITIVE_NAMES), (
        f"fraud360/contracts.py re-declares a canonical primitive: "
        f"{sorted(defined_here & _CANONICAL_PRIMITIVE_NAMES)}"
    )


def test_fraud_hypothesis_uses_canonical_reference_types():
    h = _sample_hypothesis(
        exposure=None,
        evidence_refs=[EvidenceRef(id="ev1", type="transaction", source="src")],
        snapshot=None,
    )
    # Annotation identity (runtime) — fields hold canonical EvidenceRef rows.
    assert isinstance(h.evidence_refs[0], oi_models.EvidenceRef)


def test_fraud_pattern_extra_forbid():
    with pytest.raises(ValidationError):
        FraudPattern(
            pattern_id="p1",
            family="x",
            display_name="X",
            description="d",
            bogus_field="typo should raise",
        )


def test_fraud_hypothesis_extra_forbid():
    with pytest.raises(ValidationError):
        _sample_hypothesis(bogus_field="typo should raise")


def test_fraud_hypothesis_sensible_defaults():
    h = _sample_hypothesis()
    assert h.state is FraudHypothesisState.CANDIDATE
    assert h.claim_state is EpistemicStatus.DERIVED
    assert h.matched_pattern_ids == []
    assert h.evidence_refs == []
    assert h.contradictory_evidence_refs == []


def test_confirmed_hypothesis_requires_factual_claim_state():
    """A confirmed record may not be constructed under a suspicion claim."""
    for suspicion in (EpistemicStatus.DERIVED, EpistemicStatus.INFERRED,
                      EpistemicStatus.PREDICTED, EpistemicStatus.CORRELATED):
        with pytest.raises(ValidationError):
            _sample_hypothesis(
                state=FraudHypothesisState.CONFIRMED, claim_state=suspicion
            )


def test_confirmed_hypothesis_allows_factual_claim_state():
    for factual in (EpistemicStatus.OBSERVED, EpistemicStatus.VERIFIED,
                    EpistemicStatus.CAUSALLY_SUPPORTED):
        h = _sample_hypothesis(
            state=FraudHypothesisState.CONFIRMED, claim_state=factual
        )
        assert h.state is FraudHypothesisState.CONFIRMED


def test_fraud_hypothesis_run_reuses_canonical_run_substrate():
    from services.fraud360.contracts import FraudHypothesisRun
    from shared.computation.runtime import new_run_id

    run = FraudHypothesisRun(tenant_id="tenant-a")
    assert run.run_id.startswith("run_")  # minted by canonical new_run_id()
    assert FraudHypothesisRun(tenant_id="t", run_id=new_run_id()).run_id != run.run_id


def test_canonical_epistemic_home_has_consolidated_banding():
    """The fraud module reuses the single consolidated epistemic vocabulary."""
    values = epistemic.EpistemicStatus.valid_values()
    assert "derived" in values and "verified" in values and "causally_supported" in values
