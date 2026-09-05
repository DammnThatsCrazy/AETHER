"""Independence handling tests (M7).

The M6 evidence engine (``services.relationship_promotion.evidence_independence``)
is NOW present in this tree (D-04 filled), so the honest UNKNOWN fallback is
exercised through explicit resolver-ABSENT simulations: independent-observation
grouping is UNKNOWN and independence-gated fidelity dimensions degrade honestly
to null — never a fabricated number and never 0. The declared M6 interface
(``EvidenceIndependenceResolver``) is consumed defensively: a resolver may be
supplied by the caller or imported from the M6 module; any failure degrades to
UNKNOWN. The end-to-end proof that the real seam now resolves independence lives
in ``test_m6_independence_resolver.py``.
"""

from __future__ import annotations

from services.relationship_fidelity.engine import RelationshipFidelityEngine
from shared.relationship_fidelity.definitions import INDEPENDENCE_GATED_DIMENSIONS
from shared.relationship_fidelity.evidence import (
    EvidenceGroup,
    IndependentEvidenceAccount,
    M6_EVIDENCE_INDEPENDENCE_MODULE,
    Observation,
    load_m6_independence_resolver,
)

engine = RelationshipFidelityEngine()


def _obs(oid: str, direction: str, src: str, ts: str) -> Observation:
    return Observation(
        observation_id=oid,
        predicate="FOLLOWS",
        direction=direction,
        source_key=src,
        observed_at=ts,
    )


def test_m6_module_absent_resolver_is_none(monkeypatch):
    # The M6 (relationship_promotion) module is present in this tree, so simulate
    # it ABSENT by pointing the documented module path at a module that does not
    # exist: the defensive import must degrade to None, never raise, never
    # fabricate grouping.
    assert "relationship_promotion" in M6_EVIDENCE_INDEPENDENCE_MODULE
    monkeypatch.setattr(
        "shared.relationship_fidelity.evidence.M6_EVIDENCE_INDEPENDENCE_MODULE",
        "services.relationship_promotion._no_such_m6_evidence_module",
    )
    assert load_m6_independence_resolver() is None


def test_resolver_absent_independence_is_unknown_not_zero(monkeypatch):
    observations = [
        _obs("o1", "outgoing", "src-a", "2026-08-01T00:00:00Z"),
        _obs("o2", "incoming", "src-b", "2026-08-05T00:00:00Z"),
    ]
    # No resolver available and no explicit account => independence UNKNOWN.
    # The M6 module IS present, so simulate resolver ABSENCE at the engine's
    # defensive loader and assert the same honest degraded outcomes.
    monkeypatch.setattr(
        "services.relationship_fidelity.engine.load_m6_independence_resolver",
        lambda: None,
    )
    vec = engine.compute_fidelity(relationship_ref="rel:i1", observations=observations)
    assert vec.independent_evidence_count is None
    assert vec.independent_source_count is None
    for dim in INDEPENDENCE_GATED_DIMENSIONS:
        assert vec.dimension_values()[dim] is None, (
            f"independence-gated dimension {dim} must stay null when independence "
            "is unknown (never a fabricated number)"
        )


def test_explicit_m6_account_materializes_independence():
    observations = [
        _obs("o1", "outgoing", "src-a", "2026-08-01T00:00:00Z"),
        _obs("o2", "incoming", "src-b", "2026-08-05T00:00:00Z"),
        _obs("o3", "outgoing", "src-c", "2026-09-01T00:00:00Z"),
    ]
    groups = (
        EvidenceGroup(group_id="g1", observation_ids=("o1",), source_key="src-a"),
        EvidenceGroup(group_id="g2", observation_ids=("o2",), source_key="src-b"),
        EvidenceGroup(group_id="g3", observation_ids=("o3",), source_key="src-c"),
    )
    account = IndependentEvidenceAccount(groups=groups, provided_by="m6.evidence_independence")
    vec = engine.compute_fidelity(
        relationship_ref="rel:i2",
        observations=observations,
        independent_account=account,
    )
    assert vec.independent_evidence_count == 3
    assert vec.independent_source_count == 3
    # reciprocity materializes only because BOTH directions are independently
    # observed (2 outgoing groups vs 1 incoming group => harmonic 2/3).
    assert vec.reciprocity is not None
    assert abs(vec.reciprocity - 2.0 / 3.0) < 1e-3  # rounded to 4 decimals
    # persistence materializes because >=2 independent groups span time.
    assert vec.persistence is not None
    assert vec.coverage["independent_account"] == "m6.evidence_independence"


def test_resolver_interface_is_consumed_defensively():
    observations = [
        _obs("o1", "outgoing", "src-a", "2026-08-01T00:00:00Z"),
        _obs("o2", "outgoing", "src-b", "2026-08-05T00:00:00Z"),
    ]
    group = EvidenceGroup(group_id="g1", observation_ids=("o1", "o2"), source_key="src-a")
    account = IndependentEvidenceAccount(groups=(group,), provided_by="test-resolver")

    class _Resolver:
        def resolve(self, *, relationship_ref, tenant_id, observations):
            assert tenant_id == "tenant-9"
            return account

    with_account = RelationshipFidelityEngine(resolver=_Resolver().resolve)
    vec = with_account.compute_fidelity(
        relationship_ref="rel:i3",
        tenant_id="tenant-9",
        observations=observations,
    )
    assert vec.independent_evidence_count == 1


def test_resolver_failure_degrades_to_unknown():
    observations = [_obs("o1", "outgoing", "src-a", "2026-08-01T00:00:00Z")]

    class _Failing:
        def resolve(self, **kwargs):  # M6 must never break fidelity
            raise RuntimeError("M6 exploded")

    eng = RelationshipFidelityEngine(resolver=_Failing().resolve)
    vec = eng.compute_fidelity(relationship_ref="rel:i4", observations=observations)
    assert vec.independent_evidence_count is None
    for dim in INDEPENDENCE_GATED_DIMENSIONS:
        assert vec.dimension_values()[dim] is None
    assert any("not present" in lim or "UNKNOWN" in lim for lim in vec.limitations)


def test_unidirectional_evidence_never_low_reciprocity():
    observations = [
        _obs("o1", "outgoing", "src-a", "2026-08-01T00:00:00Z"),
        _obs("o2", "outgoing", "src-b", "2026-08-05T00:00:00Z"),
    ]
    groups = (
        EvidenceGroup(group_id="g1", observation_ids=("o1",), source_key="src-a"),
        EvidenceGroup(group_id="g2", observation_ids=("o2",), source_key="src-b"),
    )
    account = IndependentEvidenceAccount(groups=groups, provided_by="test")
    vec = engine.compute_fidelity(
        relationship_ref="rel:i5",
        observations=observations,
        independent_account=account,
    )
    # Unidirectional evidence is UNKNOWN reciprocity, never a low value / 0.
    assert vec.reciprocity is None
    assert vec.reciprocity != 0
