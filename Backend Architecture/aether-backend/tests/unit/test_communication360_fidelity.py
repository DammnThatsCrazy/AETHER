"""Unit tests for Communication360 Phase-5 information fidelity (services.communication360.fidelity).

Pure-logic coverage of the SoT §67 / §71 fidelity metrics over the frozen Phase-3
information layer: metric bounds [0, 1], determinism, the
retention + semantic-drift + omission partition identity, honest-absence (NaN)
for unmeasured hops, epistemic capping (never verified/resolved/causally_supported),
and the binding-level contradiction helper.

Frozen contracts consumed directly: ``InformationTransformation``,
``MessageClaimBinding``, ``InformationRef``.
"""

from __future__ import annotations

import math
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]  # Backend Architecture/aether-backend
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("AETHER_ENV", "local")
os.environ.setdefault("JWT_SECRET", "test-secret")

from services.communication360.fidelity import (  # noqa: E402
    FidelityReport,
    assert_derived_status,
    citation_retention,
    claim_retention,
    compute_fidelity_report,
    contradiction_rate,
    evidence_retention,
    omission_rate,
    semantic_drift,
    unsupported_addition_rate,
)
from services.communication360.contracts import (  # noqa: E402
    InformationRef,
    InformationTransformation,
    MessageClaimBinding,
)
from shared.contracts_models.epistemic import EpistemicStatus  # noqa: E402


# ---------------------------------------------------------------------------
# Fixtures — deterministic, self-consistent hop chains
# ---------------------------------------------------------------------------

def _ref(information_id: str) -> dict:
    return {"information_id": information_id, "kind": "message_content", "tenant_id": "tenant-a"}


def degraded_chain() -> list[dict]:
    """A two-hop lineage with a nonzero value for every §67 metric.

    Hop 1 (request → agent context, summarization): c1/c2 retained, c3
    meaning-changed, c4 omitted, one citation lost, all evidence retained.
    Hop 2 (agent context → draft, paraphrase): c1 retained, c3 meaning-changed,
    c2 contradicted (negated), c5 introduced without support (c6 supported),
    remaining citations lost, one evidence ref retained.
    """
    return [
        {
            "transformation_id": "t1",
            "tenant_id": "tenant-a",
            "source_information_ref": _ref("info_request"),
            "derived_information_ref": _ref("info_agent_ctx"),
            "kind": "summarization",
            "agent_entity_id": "agent-1",
            "occurred_at": "2026-09-03T10:00:00Z",
            "drift_notes": ["price constraint and delivery date omitted"],
            "source_claims": ["c1", "c2", "c3", "c4"],
            "retained_claims": ["c1", "c2"],
            "meaning_changed_claims": ["c3"],
            "contradicted_claims": [],
            "added_claims": [],
            "unsupported_added_claims": [],
            "source_citations": ["cite1", "cite2"],
            "retained_citations": ["cite1"],
            "source_evidence_refs": ["ev1", "ev2"],
            "retained_evidence_refs": ["ev1", "ev2"],
        },
        {
            "transformation_id": "t2",
            "tenant_id": "tenant-a",
            "source_information_ref": _ref("info_agent_ctx"),
            "derived_information_ref": _ref("info_draft"),
            "kind": "paraphrase",
            "agent_entity_id": "agent-1",
            "occurred_at": "2026-09-03T10:05:00Z",
            "drift_notes": ["negated FedRAMP claim", "added unsupported SOC2 claim"],
            "source_claims": ["c1", "c2", "c3"],
            "retained_claims": ["c1"],
            "meaning_changed_claims": ["c3"],
            "contradicted_claims": ["c2"],
            "added_claims": ["c5", "c6"],
            "unsupported_added_claims": ["c5"],
            "source_citations": ["cite1", "cite3"],
            "retained_citations": [],
            "source_evidence_refs": ["ev1", "ev3"],
            "retained_evidence_refs": ["ev1"],
        },
    ]


def _chain_transformations() -> list[InformationTransformation]:
    """The same lineage expressed purely as frozen contract objects (no partitions)."""
    chain = degraded_chain()
    return [
        InformationTransformation(
            transformation_id=hop["transformation_id"],
            tenant_id=hop["tenant_id"],
            source_information_ref=hop["source_information_ref"],
            derived_information_ref=hop["derived_information_ref"],
            kind=hop["kind"],
            agent_entity_id=hop["agent_entity_id"],
            occurred_at=hop["occurred_at"],
            drift_notes=list(hop["drift_notes"]),
        )
        for hop in chain
    ]


# ---------------------------------------------------------------------------
# Metric computation on a measured chain
# ---------------------------------------------------------------------------

def test_claim_metrics_are_computed_and_bounded() -> None:
    report = compute_fidelity_report(degraded_chain())
    # source totals: 4 + 3 = 7
    assert report.claim_retention_rate == pytest.approx(3 / 7)      # c1,c2 + c1
    assert report.semantic_drift == pytest.approx(3 / 7)            # c3 + (c3,c2)
    assert report.omission_rate == pytest.approx(1 / 7)             # c4
    assert report.contradiction_rate == pytest.approx(1 / 7)        # c2
    # partition identity: a claim is retained, drifted, or omitted
    assert (
        report.claim_retention_rate + report.semantic_drift + report.omission_rate
    ) == pytest.approx(1.0)
    for metric in (
        report.claim_retention_rate,
        report.semantic_drift,
        report.omission_rate,
        report.contradiction_rate,
    ):
        assert 0.0 <= metric <= 1.0


def test_citation_evidence_and_unsupported_addition_rates() -> None:
    report = compute_fidelity_report(degraded_chain())
    assert report.citation_retention_rate == pytest.approx(1 / 4)   # cite1 of 4
    assert report.evidence_retention_rate == pytest.approx(3 / 4)   # ev1,ev2 + ev1
    assert report.unsupported_addition_rate == pytest.approx(1 / 2)  # c5 of c5,c6
    for metric in (
        report.citation_retention_rate,
        report.evidence_retention_rate,
        report.unsupported_addition_rate,
    ):
        assert 0.0 <= metric <= 1.0


def test_helpers_agree_with_the_report() -> None:
    chain = degraded_chain()
    report = compute_fidelity_report(chain)
    assert claim_retention(chain) == pytest.approx(report.claim_retention_rate)
    assert citation_retention(chain) == pytest.approx(report.citation_retention_rate)
    assert evidence_retention(chain) == pytest.approx(report.evidence_retention_rate)
    assert semantic_drift(chain) == pytest.approx(report.semantic_drift)
    assert omission_rate(chain) == pytest.approx(report.omission_rate)
    assert unsupported_addition_rate(chain) == pytest.approx(
        report.unsupported_addition_rate
    )


def test_report_is_deterministic() -> None:
    chain = degraded_chain()
    first = compute_fidelity_report(chain)
    second = compute_fidelity_report(list(reversed(chain)))
    assert first.model_dump() == second.model_dump()


def test_confidence_reflects_measurement_coverage() -> None:
    report = compute_fidelity_report(degraded_chain())
    assert report.confidence == pytest.approx(1.0)
    assert report.transformation_count == 2


def test_measured_zero_unsupported_addition_is_honest_zero() -> None:
    # A hop that measured additions and observed none has unsupported rate 0.0,
    # not NaN and not fabricated.
    report = compute_fidelity_report([degraded_chain()[0]])
    assert report.unsupported_addition_rate == 0.0


# ---------------------------------------------------------------------------
# Window filtering by source_information_id
# ---------------------------------------------------------------------------

def test_source_information_window_restricts_to_one_hop() -> None:
    report = compute_fidelity_report(
        degraded_chain(), source_information_id="info_request"
    )
    assert report.transformation_count == 1
    # Hop 1 alone: source 4, retained 2, meaning-changed 1, omitted 1, cites 1/2.
    assert report.claim_retention_rate == pytest.approx(2 / 4)
    assert report.semantic_drift == pytest.approx(1 / 4)
    assert report.omission_rate == pytest.approx(1 / 4)
    assert report.contradiction_rate == 0.0
    assert report.citation_retention_rate == pytest.approx(1 / 2)
    assert report.evidence_retention_rate == 1.0


# ---------------------------------------------------------------------------
# Honest absence + epistemic discipline
# ---------------------------------------------------------------------------

def test_contract_only_transformations_report_unmeasured_nan() -> None:
    # Frozen InformationTransformation objects carry identity but no claim
    # partition: every rate is NaN (honest absence), confidence 0.0.
    report = compute_fidelity_report(_chain_transformations())
    assert report.transformation_count == 2
    assert report.confidence == 0.0
    for metric in (
        report.claim_retention_rate,
        report.citation_retention_rate,
        report.evidence_retention_rate,
        report.semantic_drift,
        report.omission_rate,
        report.unsupported_addition_rate,
        report.contradiction_rate,
    ):
        assert math.isnan(metric)


def test_empty_transformations_report_nan() -> None:
    report = compute_fidelity_report([])
    assert report.transformation_count == 0
    assert report.confidence == 0.0
    assert math.isnan(report.claim_retention_rate)
    assert math.isnan(report.semantic_drift)


def test_report_defaults_to_inferred_claim_state() -> None:
    report = compute_fidelity_report(degraded_chain())
    assert report.claim_state is EpistemicStatus.INFERRED


def test_report_rejects_factual_claim_state() -> None:
    for status in (
        EpistemicStatus.VERIFIED,
        EpistemicStatus.RESOLVED,
        EpistemicStatus.CAUSALLY_SUPPORTED,
    ):
        with pytest.raises(ValueError):
            FidelityReport(claim_state=status)


def test_assert_derived_status_rejects_factual_band() -> None:
    assert assert_derived_status(EpistemicStatus.INFERRED) is EpistemicStatus.INFERRED
    assert assert_derived_status(EpistemicStatus.OBSERVED) is EpistemicStatus.OBSERVED
    with pytest.raises(ValueError):
        assert_derived_status(EpistemicStatus.VERIFIED)


# ---------------------------------------------------------------------------
# Binding-level contradiction helper (consumes the frozen MessageClaimBinding)
# ---------------------------------------------------------------------------

def _real_binding(binding_id: str, claim_text: str = "c1") -> MessageClaimBinding:
    return MessageClaimBinding(
        binding_id=binding_id,
        tenant_id="tenant-a",
        message_id="m1",
        information_ref=InformationRef(
            information_id="info_draft", kind="message_content", tenant_id="tenant-a"
        ),
        claim_text=claim_text,
    )


def test_contradiction_rate_is_nan_without_a_marked_relation() -> None:
    # A bare frozen MessageClaimBinding models the claim, not the contradiction
    # relation, so no contradiction is measured (never a fabricated zero).
    assert math.isnan(
        contradiction_rate(
            [
                _real_binding("b1", "FedRAMP required"),
                _real_binding("b2", "FedRAMP required"),
            ]
        )
    )


def test_contradiction_rate_computes_over_marked_dict_bindings() -> None:
    bindings = [
        {"binding_id": "b1", "tenant_id": "tenant-a", "contradicts_claim_id": "c2"},
        # marker present but empty → measured as NOT a contradiction
        {"binding_id": "b2", "tenant_id": "tenant-a", "contradicts_information_id": None},
        {"binding_id": "b3", "tenant_id": "tenant-a", "contradiction_of": "c1"},
    ]
    assert contradiction_rate(bindings) == pytest.approx(2 / 3)


def test_contradiction_rate_accepts_real_and_marked_mixed() -> None:
    # Real (unmeasured) bindings are excluded from the measured denominator.
    bindings = [
        _real_binding("b0"),
        {"binding_id": "b1", "tenant_id": "tenant-a", "contradicts_claim_id": "c2"},
    ]
    assert contradiction_rate(bindings) == pytest.approx(1.0)
