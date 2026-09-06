"""Correlation damping tests (M7).

Correlated evidence is not independent evidence: the M7 engine reuses the
platform's 0.4 correlation-damping discipline (first member of a family counts in
full; correlated siblings count at 0.4), so duplicated / structurally-correlated
evidence is never naively additive.
"""

from __future__ import annotations

from services.relationship_fidelity.engine import RelationshipFidelityEngine
from shared.relationship_fidelity.evidence import (
    CORRELATION_DAMPING,
    CORRELATION_DAMPING_REFERENCE,
    EvidenceGroup,
    IndependentEvidenceAccount,
    Observation,
    build_effective_evidence,
    damped_evidence_weight,
)

engine = RelationshipFidelityEngine()
WINDOW = 86400 * 30  # 30 days


def _obs(oid: str, direction: str = "outgoing", src: str = "src") -> Observation:
    return Observation(
        observation_id=oid,
        predicate="FOLLOWS",
        direction=direction,
        source_key=src,
        observed_at="2026-08-01T00:00:00Z",
    )


# --------------------------------------------------------------------------- #
# Pure damping math (0.4 discipline)
# --------------------------------------------------------------------------- #
def test_damping_constant_reuses_platform_0_4_discipline():
    assert CORRELATION_DAMPING == 0.4
    # provenance: the constant is documented as the platform 0.4 discipline
    assert (
        CORRELATION_DAMPING_REFERENCE.endswith("_CORRELATED_SIGNAL_DAMPING")
        or "0.4" in CORRELATION_DAMPING_REFERENCE
    )


def test_damped_weight_independent_families_full():
    # 3 families x 1 member => fully independent => full weight
    assert damped_evidence_weight([1, 1, 1]) == 3.0


def test_damped_weight_correlated_siblings_reduced():
    # 1 family of 3 correlated siblings => 1.0 + 0.4 * 2 = 1.8 (never 3.0)
    assert damped_evidence_weight([3]) == 1.8


def test_damped_weight_mixed():
    assert damped_evidence_weight([2, 1]) == 2.4  # (1 + 0.4) + 1


def test_correlated_never_beats_independent():
    independent = damped_evidence_weight([1, 1, 1])
    correlated = damped_evidence_weight([3])
    assert correlated < independent
    assert abs(correlated - 1.8) < 1e-9


# --------------------------------------------------------------------------- #
# Damping reflected in the fidelity computation
# --------------------------------------------------------------------------- #
def _account(*families) -> IndependentEvidenceAccount:
    groups = [
        EvidenceGroup(
            group_id=f"g{i}",
            observation_ids=(f"o{i}",),
            source_key=f"src{i}",
            correlation_family=family,
        )
        for i, family in enumerate(families)
    ]
    return IndependentEvidenceAccount(groups=tuple(groups), provided_by="test")


def test_independent_groups_yield_higher_frequency_than_correlated_groups():
    observations = [_obs(f"o{i}") for i in range(3)]
    independent = _account(None, None, None)  # three independent families
    correlated = _account("campaign-x", "campaign-x", "campaign-x")

    eff_ind = build_effective_evidence(observations, independent)
    eff_corr = build_effective_evidence(observations, correlated)
    assert eff_ind.damped_support == 3.0
    assert eff_corr.damped_support == 1.8

    vec_ind = engine.compute_fidelity(
        relationship_ref="rel:d1",
        observations=observations,
        independent_account=independent,
        window_seconds=WINDOW,
    )
    vec_corr = engine.compute_fidelity(
        relationship_ref="rel:d2",
        observations=observations,
        independent_account=correlated,
        window_seconds=WINDOW,
    )
    # Correlation damping must lower the strength-bearing frequency dimension.
    assert vec_ind.interaction_frequency is not None
    assert vec_corr.interaction_frequency is not None
    assert vec_corr.interaction_frequency < vec_ind.interaction_frequency
    # Both still carry the same raw observation count (never conflated).
    assert vec_ind.observation_count == vec_corr.observation_count == 3
    # Damped support is disclosed in coverage, not hidden.
    assert vec_ind.coverage["damped_support"] == 3.0
    assert vec_corr.coverage["damped_support"] == 1.8
