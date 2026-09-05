"""M6 independence seam resolution tests (M7 — D-04 wave 1).

Proves the recorded D-04 seam is filled end-to-end: the M7 relationship-fidelity
engine now resolves independence through the REAL M6 evidence engine
(``services.relationship_promotion.evidence_independence.resolve_independent_groups``)
with NO explicit resolver injected — the defensive loader
(``load_m6_independence_resolver``) finds the module at the documented path and
independence-gated dimensions become computable instead of staying UNKNOWN.

Honesty invariants remain enforced: when independence genuinely cannot be
determined (no usable source identity / no observations / a raising resolver)
the engine still degrades to UNKNOWN — never a fabricated number, never 0.
"""

from __future__ import annotations

import inspect

from services.relationship_fidelity.engine import RelationshipFidelityEngine
from services.relationship_promotion.evidence_independence import (
    PROVIDED_BY,
    resolve_independent_groups,
)
from shared.relationship_fidelity.definitions import INDEPENDENCE_GATED_DIMENSIONS
from shared.relationship_fidelity.evidence import (
    IndependentEvidenceAccount,
    M6_EVIDENCE_INDEPENDENCE_MODULE,
    Observation,
    load_m6_independence_resolver,
)

engine = RelationshipFidelityEngine()


def _obs(
    oid: str,
    *,
    direction: str,
    source: str,
    ts: str,
    correlation_family: str | None = None,
    incentive_assessed: bool = False,
    incentive_context: bool = False,
) -> Observation:
    return Observation(
        observation_id=oid,
        predicate="FOLLOWS",
        direction=direction,
        source_key=source,
        observed_at=ts,
        correlation_family=correlation_family,
        incentive_assessed=incentive_assessed,
        incentive_context=incentive_context,
    )


# --------------------------------------------------------------------------- #
# The seam is live: no explicit resolver, engine resolves independence
# --------------------------------------------------------------------------- #
def test_loader_returns_the_real_resolver_factory():
    # The documented M6 module path now resolves to our factory (the D-04 seam).
    assert M6_EVIDENCE_INDEPENDENCE_MODULE == (
        "services.relationship_promotion.evidence_independence"
    )
    resolver = load_m6_independence_resolver()
    assert resolver is resolve_independent_groups


def test_engine_resolves_two_independent_source_lineages_end_to_end():
    # Two distinct source lineages (provider-a, provider-b), each observing the
    # same relationship across >=2 distinct calendar dates spread ~2 weeks apart,
    # with a direction mix (outgoing from provider-a, incoming from provider-b).
    observations = [
        _obs("o1", direction="outgoing", source="provider-a", ts="2026-08-01T00:00:00Z"),
        _obs("o2", direction="outgoing", source="provider-a", ts="2026-08-10T00:00:00Z"),
        _obs("o3", direction="incoming", source="provider-b", ts="2026-08-03T00:00:00Z"),
        _obs("o4", direction="incoming", source="provider-b", ts="2026-08-15T00:00:00Z"),
    ]
    vec = engine.compute_fidelity(relationship_ref="rel:alice-bob", observations=observations)
    # Independence is now a measurement, not UNKNOWN.
    assert vec.independent_evidence_count is not None
    assert vec.independent_source_count is not None
    assert vec.independent_evidence_count >= 2
    assert vec.independent_source_count >= 2
    # Independence-gated dimensions materialize (were UNKNOWN before the seam).
    assert vec.persistence is not None and 0.0 <= vec.persistence <= 1.0
    assert vec.reciprocity is not None and 0.0 <= vec.reciprocity <= 1.0
    # Provenance is honest and independence is no longer flagged unknown.
    assert vec.coverage["independent_account"] == PROVIDED_BY
    assert vec.coverage["independence_unknown"] is False
    # Only the two independent lineages are counted (not raw observation count).
    assert vec.observation_count == 4
    assert vec.status == "current"


def test_engine_resolves_reciprocity_across_independent_direction_groups():
    observations = [
        _obs("o1", direction="outgoing", source="provider-a", ts="2026-08-01T00:00:00Z"),
        _obs("o2", direction="outgoing", source="provider-a", ts="2026-08-10T00:00:00Z"),
        _obs("o3", direction="incoming", source="provider-b", ts="2026-08-03T00:00:00Z"),
        _obs("o4", direction="incoming", source="provider-b", ts="2026-08-15T00:00:00Z"),
    ]
    vec = engine.compute_fidelity(relationship_ref="rel:alice-bob2", observations=observations)
    # One outgoing group + one incoming group => harmonic 2*1/(1+1) = 1.0.
    assert vec.reciprocity is not None
    assert abs(vec.reciprocity - 1.0) < 1e-3


# --------------------------------------------------------------------------- #
# Coordination: >=2 groups sharing a correlation family
# --------------------------------------------------------------------------- #
def test_coordination_indicator_materializes_when_groups_share_family():
    # provider-a/provider-b are un-correlated; provider-c/provider-d share one
    # correlation family => a coordination structure is actually observed.
    observations = [
        _obs("o1", direction="outgoing", source="provider-a", ts="2026-08-01T00:00:00Z"),
        _obs("o2", direction="outgoing", source="provider-a", ts="2026-08-10T00:00:00Z"),
        _obs("o3", direction="incoming", source="provider-b", ts="2026-08-03T00:00:00Z"),
        _obs("o4", direction="incoming", source="provider-b", ts="2026-08-15T00:00:00Z"),
        _obs(
            "o5",
            direction="outgoing",
            source="provider-c",
            ts="2026-08-02T00:00:00Z",
            correlation_family="campaign-orch",
        ),
        _obs(
            "o6",
            direction="incoming",
            source="provider-c",
            ts="2026-08-11T00:00:00Z",
            correlation_family="campaign-orch",
        ),
        _obs(
            "o7",
            direction="incoming",
            source="provider-d",
            ts="2026-08-04T00:00:00Z",
            correlation_family="campaign-orch",
        ),
        _obs(
            "o8",
            direction="outgoing",
            source="provider-d",
            ts="2026-08-16T00:00:00Z",
            correlation_family="campaign-orch",
        ),
    ]
    vec = engine.compute_fidelity(
        relationship_ref="rel:coordination-1", observations=observations
    )
    assert vec.independent_evidence_count == 4
    # Two of four groups are correlated siblings => strength 0.5.
    assert vec.coordination_indicator_strength is not None
    assert 0.0 <= vec.coordination_indicator_strength <= 1.0
    assert abs(vec.coordination_indicator_strength - 0.5) < 1e-3


# --------------------------------------------------------------------------- #
# Incentive independence: assessed incentive-free vs assessed incentivized
# --------------------------------------------------------------------------- #
def test_incentive_independence_materializes_over_assessed_groups():
    observations = [
        # provider-a: assessed, incentive-free independent group.
        _obs(
            "o1",
            direction="outgoing",
            source="provider-a",
            ts="2026-08-01T00:00:00Z",
            incentive_assessed=True,
            incentive_context=False,
        ),
        _obs(
            "o2",
            direction="outgoing",
            source="provider-a",
            ts="2026-08-10T00:00:00Z",
            incentive_assessed=True,
            incentive_context=False,
        ),
        # provider-b: assessed and incentivized independent group.
        _obs(
            "o3",
            direction="incoming",
            source="provider-b",
            ts="2026-08-03T00:00:00Z",
            incentive_assessed=True,
            incentive_context=True,
        ),
        _obs(
            "o4",
            direction="incoming",
            source="provider-b",
            ts="2026-08-15T00:00:00Z",
            incentive_assessed=True,
            incentive_context=True,
        ),
        # provider-c: UNASSESSED observations are never read as incentive-free.
        _obs("o5", direction="outgoing", source="provider-c", ts="2026-08-02T00:00:00Z"),
        _obs("o6", direction="incoming", source="provider-c", ts="2026-08-11T00:00:00Z"),
    ]
    vec = engine.compute_fidelity(
        relationship_ref="rel:incentive-1", observations=observations
    )
    # 1 of 2 ASSESSED groups is incentive-free => 0.5.
    assert vec.incentive_independence_support is not None
    assert 0.0 <= vec.incentive_independence_support <= 1.0
    assert abs(vec.incentive_independence_support - 0.5) < 1e-3
    # 2 of 4 ASSESSED observations occurred under an incentive => exposure 0.5.
    assert vec.incentive_exposure is not None
    assert 0.0 <= vec.incentive_exposure <= 1.0
    assert abs(vec.incentive_exposure - 0.5) < 1e-3


# --------------------------------------------------------------------------- #
# Honest degraded cases (UNKNOWN is never fabricated; never 0)
# --------------------------------------------------------------------------- #
def test_all_empty_source_keys_stay_unknown():
    observations = [
        Observation(
            observation_id="o1",
            predicate="FOLLOWS",
            direction="outgoing",
            source_key="",
            observed_at="2026-08-01T00:00:00Z",
        ),
        Observation(
            observation_id="o2",
            predicate="FOLLOWS",
            direction="incoming",
            source_key="   ",
            observed_at="2026-08-05T00:00:00Z",
        ),
    ]
    vec = engine.compute_fidelity(
        relationship_ref="rel:no-source", observations=observations
    )
    assert vec.coverage["independence_unknown"] is True
    assert vec.coverage["independent_account"] is None
    assert vec.independent_evidence_count is None
    assert vec.independent_source_count is None
    for dim in INDEPENDENCE_GATED_DIMENSIONS:
        assert vec.dimension_values()[dim] is None, (
            f"independence-gated dimension {dim} must stay null when no observation "
            "is attributable to an independent source (unknown, never 0)"
        )


def test_zero_observations_returns_all_null_unknown_vector():
    vec = engine.compute_fidelity(relationship_ref="rel:no-obs", observations=[])
    assert vec.observation_count == 0
    assert vec.status == "unknown"
    assert vec.materialized_dimension_count == 0
    assert vec.independent_evidence_count is None
    assert vec.independent_source_count is None
    assert all(v is None for v in vec.dimension_values().values())
    assert vec.to_contract_dict()["observation_count"] == 0


def test_raising_resolver_is_caught_and_degrades_to_unknown():
    observations = [
        _obs("o1", direction="outgoing", source="provider-a", ts="2026-08-01T00:00:00Z"),
        _obs("o2", direction="incoming", source="provider-b", ts="2026-08-05T00:00:00Z"),
    ]

    class _Exploding:
        def resolve(self, **kwargs):  # pragma: no cover - M6 must never break fidelity
            raise RuntimeError("M6 exploded")

    eng = RelationshipFidelityEngine(resolver=_Exploding().resolve)
    vec = eng.compute_fidelity(relationship_ref="rel:boom", observations=observations)
    assert vec.independent_evidence_count is None
    assert vec.independent_source_count is None
    assert vec.coverage["independence_unknown"] is True
    for dim in INDEPENDENCE_GATED_DIMENSIONS:
        assert vec.dimension_values()[dim] is None
    assert any("not present" in lim or "UNKNOWN" in lim for lim in vec.limitations)


# --------------------------------------------------------------------------- #
# Unit tests of resolve_independent_groups
# --------------------------------------------------------------------------- #
def test_resolver_signature_is_keyword_only_protocol():
    params = inspect.signature(resolve_independent_groups).parameters
    assert set(params) == {"relationship_ref", "tenant_id", "observations"}
    for name in params:
        assert params[name].kind is inspect.Parameter.KEYWORD_ONLY, name
    # matches the EvidenceIndependenceResolver protocol the engine consumes.
    try:
        resolve_independent_groups("rel:x", "tenant-x", [])  # type: ignore[call-arg]
    except TypeError:
        pass
    else:  # pragma: no cover - keyword-only contract must be enforced
        raise AssertionError("keyword-only signature was bypassed")


def test_resolver_groups_attributable_observations_by_source_lineage():
    observations = [
        _obs("o1", direction="outgoing", source="provider-a", ts="2026-08-01T00:00:00Z"),
        _obs("o2", direction="outgoing", source="provider-a", ts="2026-08-10T00:00:00Z"),
        _obs("o3", direction="incoming", source="provider-b", ts="2026-08-03T00:00:00Z"),
        # no usable source identity => excluded, no fabricated independent unit.
        Observation(
            observation_id="o4",
            predicate="FOLLOWS",
            direction="incoming",
            source_key="",
            observed_at="2026-08-15T00:00:00Z",
        ),
    ]
    account = resolve_independent_groups(
        relationship_ref="rel:unit-1", tenant_id="tenant-u", observations=observations
    )
    assert isinstance(account, IndependentEvidenceAccount)
    assert account is not None
    assert account.provided_by == PROVIDED_BY
    assert account.independent_evidence_count == 2
    assert account.independent_source_count == 2
    groups = account.groups
    assert [g.group_id for g in groups] == [
        "rel:unit-1::provider-a",
        "rel:unit-1::provider-b",
    ]
    by_id = {g.source_key: g for g in groups}
    assert by_id["provider-a"].observation_ids == ("o1", "o2")
    assert by_id["provider-b"].observation_ids == ("o3",)
    # the un-attributable observation must NOT appear in any group.
    all_ids = {oid for g in groups for oid in g.observation_ids}
    assert "o4" not in all_ids


def test_resolver_returns_none_when_no_observation_has_usable_source():
    for obs in (
        [],
        [
            Observation(
                observation_id="o1",
                predicate="FOLLOWS",
                direction="outgoing",
                source_key="",
                observed_at="2026-08-01T00:00:00Z",
            )
        ],
        [
            Observation(
                observation_id="o2",
                predicate="FOLLOWS",
                direction="outgoing",
                source_key="  \t",
                observed_at="2026-08-01T00:00:00Z",
            )
        ],
    ):
        account = resolve_independent_groups(
            relationship_ref="rel:unit-none", tenant_id="tenant-u", observations=obs
        )
        assert account is None  # independence UNKNOWN, never a fabricated 0


def test_resolver_correlation_family_only_when_all_members_share_it():
    def _family_obs(oid, family, source="src-x"):
        return _obs(
            oid, direction="outgoing", source=source, ts="2026-08-01T00:00:00Z",
            correlation_family=family,
        )

    # Uniform non-None family across the source => group carries that family.
    uniform = resolve_independent_groups(
        relationship_ref="rel:fam-1",
        tenant_id="tenant-u",
        observations=[_family_obs("o1", "campaign-q"), _family_obs("o2", "campaign-q")],
    )
    assert uniform is not None
    assert uniform.groups[0].correlation_family == "campaign-q"

    # Mixed with a None-labelled member => family unshared => None.
    mixed_none = resolve_independent_groups(
        relationship_ref="rel:fam-2",
        tenant_id="tenant-u",
        observations=[_family_obs("o3", "campaign-q"), _family_obs("o4", None)],
    )
    assert mixed_none is not None
    assert mixed_none.groups[0].correlation_family is None

    # Two distinct families within one source => family unshared => None.
    mixed_families = resolve_independent_groups(
        relationship_ref="rel:fam-3",
        tenant_id="tenant-u",
        observations=[_family_obs("o5", "campaign-q"), _family_obs("o6", "campaign-r")],
    )
    assert mixed_families is not None
    assert mixed_families.groups[0].correlation_family is None
