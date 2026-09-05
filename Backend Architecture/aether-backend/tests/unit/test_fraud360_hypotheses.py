"""Fraud360 Phase-6 synthesis generator tests.

Covers the honest deterministic producer: a real Day-1 pattern alignment yields
EXACTLY that suspicion-state hypothesis (deterministic content-derived id), an
unrelated subject yields zero hypotheses, claim state never escalates to factual
for generated candidates, materiality is evidence-backed (None when nothing backs
it), the persist path writes hypotheses + one ``computation_runs`` row with no
duplicates, the lifecycle wrappers reach the store (and illegal transitions
raise), and the repository evidence reader returns real authorities while
missing authorities degrade to empty without raising.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[2]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

os.environ.setdefault("AETHER_ENV", "local")
os.environ.setdefault("JWT_SECRET", "test-secret")

from repositories.repos import (  # noqa: E402
    FlowTraceRepository,
    FraudDecisionRepository,
    FraudNetworkMemberRepository,
    FraudNetworkRepository,
    reset_in_memory_stores,
)
from services.fraud360.contracts import (  # noqa: E402
    ConfirmationRequiresFactualClaimError,
    EpistemicStatus,
    FraudHypothesis,
    FraudHypothesisState,
    SUSPICION_CLAIM_STATES,
)
from services.fraud360.hypotheses import (  # noqa: E402
    FraudHypothesisEvidence,
    HypothesisGenerationResult,
    RepositoryFraudEvidenceReader,
    correct_hypothesis,
    dispute_hypothesis,
    evaluate_pattern,
    generate_hypotheses,
    hypothesis_materiality,
    mark_stale,
    persist_hypotheses,
    supersede_hypothesis,
)
from services.fraud360.patterns import fraud_pattern  # noqa: E402
from services.fraud360.store import FraudHypothesisRepository  # noqa: E402
from services.risk360.contracts import (  # noqa: E402
    RiskAssessment,
    RiskComponent,
    RiskVector,
)
from services.risk360.store import RiskAssessmentRepository  # noqa: E402
from shared.measurement.value_states import ValueState  # noqa: E402

TENANT = "tenant-a"


@pytest.fixture(autouse=True)
def _reset_stores():
    reset_in_memory_stores()
    yield
    reset_in_memory_stores()


def _circular_evidence(entity_id: str = "ent_1") -> FraudHypothesisEvidence:
    """Entity aligned to the circular_value_flow Day-1 pattern ONLY.

    Fraud-network taxonomy layering_network + role ``relay`` (a role wallet_abuse
    does NOT carry) plus a ``round_trip`` decision signal — no other Day-1
    pattern shares that type+role pair or that family keyword.
    """
    return FraudHypothesisEvidence(
        tenant_id=TENANT,
        subject_kind="entity",
        subject_id=entity_id,
        network_ids=["net_1"],
        network_types=["layering_network"],
        network_member_roles=["relay"],
        flow_trace_ids=["ft_1"],
        flow_pattern_tags=["round_trip"],
        decision_ids=["dec_1"],
        decision_signals=["round_trip"],
    )


def _risk_assessment(
    assessment_id: str = "ras_1", score: float = 0.9, subject_id: str = "ent_1"
) -> RiskAssessment:
    return RiskAssessment(
        assessment_id=assessment_id,
        tenant_id=TENANT,
        subject_kind="entity",
        subject_id=subject_id,
        dimensions=["fraud"],
        vector=RiskVector(
            components=[
                RiskComponent(
                    dimension="fraud",
                    state=ValueState.OBSERVED,
                    score=score,
                    claim_state=EpistemicStatus.OBSERVED,
                )
            ]
        ),
        claim_state=EpistemicStatus.DERIVED,
    )


# ── evaluation + generation ─────────────────────────────────────────────────

def test_aligned_evidence_generates_exactly_circular_value_flow():
    res = generate_hypotheses(evidence=_circular_evidence())
    assert len(res.hypotheses) == 1
    hypothesis = res.hypotheses[0]
    assert hypothesis.matched_pattern_ids == ["circular_value_flow"]
    assert hypothesis.state is FraudHypothesisState.CANDIDATE
    assert hypothesis.claim_state in SUSPICION_CLAIM_STATES
    assert hypothesis.hypothesis_id.startswith("fh_")
    # evidence refs are content-derived from the real authority ids (never invented)
    ref_ids = [r.id for r in hypothesis.evidence_refs]
    assert any(rid.endswith(":ft_1") for rid in ref_ids)
    assert any(rid.endswith(":net_1") for rid in ref_ids)
    assert any(rid.endswith(":dec_1") for rid in ref_ids)
    # evaluate_pattern reports the honest channel, never a numeric probability
    match = evaluate_pattern(_circular_evidence(), fraud_pattern("circular_value_flow"))
    assert match.matched is True
    assert "layering_network" in match.signal_names


def test_unrelated_subject_generates_zero_hypotheses():
    unrelated = FraudHypothesisEvidence(
        tenant_id=TENANT, subject_kind="entity", subject_id="ent_other"
    )
    res = generate_hypotheses(evidence=unrelated)
    assert res.hypotheses == ()
    assert all(not m.matched for m in res.matches)


def test_generation_is_deterministic_content_only():
    first = generate_hypotheses(evidence=_circular_evidence())
    second = generate_hypotheses(evidence=_circular_evidence())
    assert first.run.context_hash == second.run.context_hash
    assert first.hypotheses[0].hypothesis_id == second.hypotheses[0].hypothesis_id
    # run ids differ — each run is its own substrate row
    assert first.run.run_id != second.run.run_id


def test_changed_evidence_changes_identity():
    base = _circular_evidence()
    changed = _circular_evidence()
    changed.decision_ids.append("dec_2")
    a = generate_hypotheses(evidence=base)
    b = generate_hypotheses(evidence=changed)
    assert a.run.context_hash != b.run.context_hash
    assert a.hypotheses[0].hypothesis_id != b.hypotheses[0].hypothesis_id


def test_generated_claim_state_is_never_factual():
    correlated = generate_hypotheses(
        evidence=_circular_evidence(), claim_state=EpistemicStatus.CORRELATED
    )
    assert correlated.hypotheses[0].claim_state is EpistemicStatus.CORRELATED
    with pytest.raises(ValueError):
        generate_hypotheses(
            evidence=_circular_evidence(), claim_state=EpistemicStatus.OBSERVED
        )


def test_evaluate_pattern_returns_zero_for_nonpattern_and_disabled():
    from services.fraud360.contracts import FraudPattern

    bogus = FraudPattern(
        pattern_id="not_real", family="?", display_name="?", description="?"
    )
    bogus.enabled = False
    match = evaluate_pattern(_circular_evidence(), bogus)
    assert match.matched is False


# ── materiality (evidence-backed only) ──────────────────────────────────────

def _material_hypothesis(evidence: FraudHypothesisEvidence) -> FraudHypothesis:
    result = generate_hypotheses(evidence=evidence)
    assert len(result.hypotheses) == 1
    return result.hypotheses[0]


def test_materiality_none_when_nothing_backs_it():
    bare = _candidate("h-bare")  # no matched patterns, no risk, no exposure
    assert bare.matched_pattern_ids == []
    assert hypothesis_materiality(bare) is None
    assert hypothesis_materiality(bare, risk_assessment=_risk_assessment()) is not None


def test_materiality_rubric_is_evidence_backed():
    h = _material_hypothesis(_circular_evidence())
    scored = hypothesis_materiality(
        h, risk_assessment=_risk_assessment(score=0.9), exposure_usd=1000.0
    )
    assert scored is not None
    # 0.15 (one matched pattern) + 0.25*0.9 (strongest component) + 0.15 (>= $1k)
    assert scored == pytest.approx(round(0.15 + 0.225 + 0.15, 4))
    # exposure-only contributes monotonically when a hypothesis backs it
    assert hypothesis_materiality(h, exposure_usd=10_000.0) == pytest.approx(0.15 + 0.20)


# ── persistence (the fraud360 write path) ───────────────────────────────────

async def test_persist_writes_hypothesis_and_one_run_no_duplicates():
    from services.computation.repositories import ComputedResultsRepository

    runs_repo = ComputedResultsRepository()
    repo = FraudHypothesisRepository()
    result = generate_hypotheses(evidence=_circular_evidence())

    persisted = await persist_hypotheses(
        result, tenant_id=TENANT, repo=repo, runs_repo=runs_repo
    )
    assert len(persisted.hypotheses) == 1

    row = await runs_repo.get_run(TENANT, persisted.run.run_id)
    assert row is not None
    assert row["definition_id"] == "fraud360.hypothesis"
    assert row["context_hash"] == result.run.context_hash
    assert row["data"]["hypothesis_ids"] == [persisted.hypotheses[0].hypothesis_id]

    stored = await repo.list(TENANT)
    assert len(stored) == 1
    assert stored[0].run_id == persisted.run.run_id

    # identical evidence again → a FRESH superseding run, never a duplicate row
    second = generate_hypotheses(evidence=_circular_evidence())
    persisted2 = await persist_hypotheses(
        second, tenant_id=TENANT, repo=repo, runs_repo=runs_repo
    )
    assert persisted2.run.run_id != persisted.run.run_id
    assert len(await repo.list(TENANT)) == 1
    row2 = await runs_repo.get_run(TENANT, persisted2.run.run_id)
    assert row2["data"]["supersedes_run_id"] == persisted.run.run_id


async def test_persist_confirmed_transition_guard_and_materialization_walk():
    """A generated suspicion hypothesis cannot jump to confirmed (state-machine).

    It must walk the funnel to ``investigating``; even there a suspicion claim
    is refused for ``confirmed`` until a factual claim state is supplied.
    """
    repo = FraudHypothesisRepository()
    result = generate_hypotheses(evidence=_circular_evidence())
    hypothesis = result.hypotheses[0]
    await repo.create(TENANT, hypothesis)

    for state in (
        FraudHypothesisState.UNDER_EVALUATION,
        FraudHypothesisState.SUPPORTED,
        FraudHypothesisState.MATERIAL,
        FraudHypothesisState.INVESTIGATING,
    ):
        await repo.update_state(TENANT, hypothesis.hypothesis_id, state)

    with pytest.raises(ConfirmationRequiresFactualClaimError):
        await repo.update_state(
            TENANT,
            hypothesis.hypothesis_id,
            FraudHypothesisState.CONFIRMED,
            claim_state=EpistemicStatus.DERIVED,
            evidence_refs=[{"id": "ev"}],
        )

    confirmed = await repo.update_state(
        TENANT,
        hypothesis.hypothesis_id,
        FraudHypothesisState.CONFIRMED,
        claim_state=EpistemicStatus.OBSERVED,
        evidence_refs=[{"id": "ev"}],
    )
    assert confirmed.state is FraudHypothesisState.CONFIRMED


# ── lifecycle wrappers reach the repo; illegal transitions raise ───────────

def _candidate(hypothesis_id: str) -> FraudHypothesis:
    return FraudHypothesis(
        hypothesis_id=hypothesis_id,
        tenant_id=TENANT,
        subject_kind="entity",
        subject_id="ent_1",
        claim_state=EpistemicStatus.DERIVED,
    )


async def test_lifecycle_wrappers_reach_the_store():
    repo = FraudHypothesisRepository()
    for hyp_id in ("h-super", "h-dispute", "h-stale", "h-correct"):
        await repo.create(TENANT, _candidate(hyp_id))

    assert (await supersede_hypothesis(TENANT, "h-super", repo=repo)).state is (
        FraudHypothesisState.SUPERSEDED
    )
    assert (await dispute_hypothesis(TENANT, "h-dispute", repo=repo)).state is (
        FraudHypothesisState.DISPUTED
    )
    assert (await mark_stale(TENANT, "h-stale", repo=repo)).state is (
        FraudHypothesisState.STALE
    )
    assert (await correct_hypothesis(TENANT, "h-correct", repo=repo)).state is (
        FraudHypothesisState.CORRECTED
    )
    for hyp_id, expected in (
        ("h-super", FraudHypothesisState.SUPERSEDED),
        ("h-dispute", FraudHypothesisState.DISPUTED),
        ("h-stale", FraudHypothesisState.STALE),
        ("h-correct", FraudHypothesisState.CORRECTED),
    ):
        assert (await repo.get(TENANT, hyp_id)).state is expected


async def test_illegal_transition_from_closed_raises():
    from services.fraud360.contracts import IllegalTransitionError

    repo = FraudHypothesisRepository()
    closed = _candidate("h-closed")
    closed.state = FraudHypothesisState.CLOSED
    await repo.create(TENANT, closed)
    with pytest.raises(IllegalTransitionError):
        await dispute_hypothesis(TENANT, "h-closed", repo=repo)


# ── repository evidence reader ──────────────────────────────────────────────

async def _seed_entity_authorities() -> None:
    await RiskAssessmentRepository().upsert_scoped(
        TENANT, "ras_1", _risk_assessment("ras_1").model_dump(mode="json")
    )
    await FraudNetworkRepository().create(
        {"id": "net_1", "tenant_id": TENANT, "network_type": "layering_network"}
    )
    await FraudNetworkMemberRepository().create(
        {
            "id": "mem_1",
            "tenant_id": TENANT,
            "network_id": "net_1",
            "entity_id": "ent_1",
            "role": "relay",
        }
    )
    await FlowTraceRepository().create(
        {
            "id": "ft_1",
            "tenant_id": TENANT,
            "anchor_entity_id": "ent_1",
            "pattern_tags": ["round_trip"],
        }
    )
    await FraudDecisionRepository().create(
        {
            "decision_id": "dec_1",
            "tenant_id": TENANT,
            "subject_type": "entity",
            "subject_id": "ent_1",
            "entity_id": "ent_1",
            "signal_types": ["round_trip"],
        }
    )


async def test_reader_returns_expected_authority_evidence():
    await _seed_entity_authorities()
    reader = RepositoryFraudEvidenceReader()
    evidence = await reader.read_evidence(
        tenant_id=TENANT, subject_kind="entity", subject_id="ent_1"
    )
    assert [a.assessment_id for a in evidence.risk_assessments] == ["ras_1"]
    assert evidence.network_ids == ["net_1"]
    assert evidence.network_types == ["layering_network"]
    assert evidence.network_member_roles == ["relay"]
    assert evidence.flow_trace_ids == ["ft_1"]
    assert evidence.flow_pattern_tags == ["round_trip"]
    assert evidence.decision_ids == ["dec_1"]
    assert evidence.decision_signals == ["round_trip"]

    # folding the read authority evidence back through the generator grounds the
    # SAME content-derived circular hypothesis.
    result = generate_hypotheses(evidence=evidence)
    assert result.hypotheses[0].matched_pattern_ids == ["circular_value_flow"]


async def test_reader_degrades_missing_authorities_empty_without_raising():
    await _seed_entity_authorities()
    reader = RepositoryFraudEvidenceReader()
    # relationship-kind subject has no network/flow membership facts: honest empty
    rel = await reader.read_evidence(
        tenant_id=TENANT, subject_kind="relationship", subject_id="rel_1"
    )
    assert rel.network_ids == []
    assert rel.flow_trace_ids == []
    assert rel.decision_ids == []
    assert rel.risk_assessments == []

    # an entity with no seeded authorities is read as an empty bundle, no raise
    empty = await reader.read_evidence(
        tenant_id=TENANT, subject_kind="entity", subject_id="ent_nobody"
    )
    assert empty.network_ids == []
    assert empty.flow_trace_ids == []
    assert empty.decision_ids == []
    assert HypothesisGenerationResult(  # smoke: the empty bundle stays honest
        run=generate_hypotheses(evidence=empty).run, hypotheses=()
    ).hypotheses == ()
