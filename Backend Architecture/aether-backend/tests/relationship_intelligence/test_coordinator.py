"""Wave 2b coordinator tests — RelationshipSpineCoordinator.run_for_relationship.

Covers the run contract end to end against the real M7 engine + the real (flag
gated) incentive service where the behaviour under test is the coordinator's own
gating; a fake service injects deterministic incentive contexts where the
behaviour under test is enrichment stamping.

Honesty invariants asserted throughout:
* unknown is never 0 — independence-gated dims and counts stay None when
  grouping is declined;
* never fabricated — enrichment disabled/failed leaves observations untouched;
* the persist gate honors ``fidelity_mode()`` and the ``persist`` override.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from services.computation.repositories import get_computation_repository
from services.relationship_fidelity import engine as _fidelity_engine
from services.relationship_intelligence.coordinator import (
    INCENTIVE_PRESENT_STATUSES,
    RelationshipSpineCoordinator,
    SpineRunResult,
    materialize_observations,
    relationship_ref_for,
)
from shared.logger.logger import metrics
from shared.relationship_fidelity.definitions import INDEPENDENCE_GATED_DIMENSIONS

COORD = "services.relationship_intelligence.coordinator"
ENGINE = "services.relationship_fidelity.engine"


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def coordinator():
    return RelationshipSpineCoordinator()


class _FakeIncentiveService:
    """Deterministic incentive-context resolver for enrichment tests."""

    def __init__(self, ctx, *, enabled: bool = True, exc: Exception | None = None):
        self._ctx = ctx
        self._enabled = enabled
        self._exc = exc

    @property
    def enabled(self) -> bool:
        return self._enabled

    async def resolve(self, tenant_id: str, evidence=None):  # noqa: ARG002
        if self._exc is not None:
            raise self._exc
        return self._ctx


def _records() -> list[dict]:
    return [
        {
            "id": "o-1",
            "predicate": "FOLLOWS",
            "direction": "outgoing",
            "source_key": "src-a",
            "observed_at": "2026-08-01T00:00:00Z",
        },
        {
            "id": "o-2",
            "predicate": "FOLLOWS",
            "direction": "incoming",
            "source_key": "src-b",
            "observed_at": "2026-08-20T00:00:00Z",
        },
        {
            "id": "o-3",
            "predicate": "FOLLOWS",
            "direction": "outgoing",
            "source_key": "src-b",
            "observed_at": "2026-08-21T00:00:00Z",
        },
    ]


def _obs() -> list:
    return materialize_observations(_records())


def _set_mode(monkeypatch, mode: str) -> None:
    monkeypatch.setattr(_fidelity_engine, "fidelity_mode", lambda: mode)


# ---------------------------------------------------------------------------
# materialize_observations — pure helper
# ---------------------------------------------------------------------------


def test_materialize_observations_maps_aliases_and_defaults():
    records = [
        {
            "id": "x1",
            "predicate_ref": "FOLLOWS",
            "observed_at": "2026-08-01T00:00:00Z",
            "source": "  src-1 ",
            "intensity": "0.8",
            "source_reliability": "0.9",
            "context_tags": ["a", "b"],
            "incentive_context": "true",
            "incentive_assessed": True,
        },
        {"event_id": "x2", "predicate": "FOLLOWS", "at": "2026-08-02T00:00:00Z"},
    ]
    obs = materialize_observations(records, default_direction="outgoing")
    assert len(obs) == 2
    first, second = obs
    assert first.observation_id == "x1"
    assert first.predicate == "FOLLOWS"
    assert first.direction == "outgoing"  # default applied only when absent
    assert first.source_key == "src-1"
    assert first.intensity == 0.8
    assert first.source_reliability == 0.9
    assert first.context_tags == ("a", "b")
    assert first.incentive_context is True
    assert first.incentive_assessed is True
    assert second.observation_id == "x2"
    assert second.direction == "outgoing"  # default_direction applied


def test_materialize_observations_skips_unmappable_records():
    records = [
        {"id": "no-predicate"},
        {"predicate": "FOLLOWS", "id": "no-time"},
        {"id": "bad-direction", "predicate": "FOLLOWS", "observed_at": "2026-08-01T00:00:00Z", "direction": "sideways"},
        {"id": "bad-intensity", "predicate": "FOLLOWS", "observed_at": "2026-08-01T00:00:00Z", "direction": "outgoing", "intensity": 7},  # out of range
        {"id": "good", "predicate": "FOLLOWS", "observed_at": "2026-08-01T00:00:00Z", "direction": "outgoing", "intensity": 0.5},
        "not-a-dict",
        None,
    ]
    obs = materialize_observations(records)
    assert len(obs) == 2
    # out-of-range intensity is not coerced into a plausible one
    assert obs[0].intensity is None
    assert obs[0].observation_id == "bad-intensity"
    assert obs[1].observation_id == "good"
    assert obs[1].intensity == 0.5


def test_materialize_observations_source_key_empty_is_never_attributed():
    obs = materialize_observations(
        [{"id": "x", "predicate": "FOLLOWS", "observed_at": "2026-08-01T00:00:00Z", "direction": "outgoing"}]
    )
    assert obs[0].source_key == ""


def test_incentive_present_statuses_are_honest():
    # observed/declared/verified/suspected assert presence; none_observed is an
    # assessed absence and is NOT in the presence set.
    assert INCENTIVE_PRESENT_STATUSES == frozenset(
        {"verified", "declared", "observed", "suspected"}
    )
    assert "none_observed" not in INCENTIVE_PRESENT_STATUSES


# ---------------------------------------------------------------------------
# Persist gate
# ---------------------------------------------------------------------------


def test_mode_off_does_not_persist_and_emits_run_meters(coordinator, monkeypatch):
    _set_mode(monkeypatch, "off")
    tenant = "t-off-1"
    ref = relationship_ref_for("a", "b")

    async def _run():
        return await coordinator.run_for_relationship(
            tenant_id=tenant,
            relationship_ref=ref,
            source_entity_id="a",
            target_entity_id="b",
            observations=_obs(),
            enrich_incentives=False,
        )

    result = asyncio.run(_run())
    assert isinstance(result, SpineRunResult)
    assert result.mode == "off"
    assert result.persisted is False
    assert result.run_id is None
    assert result.vector is not None
    assert any("vector not persisted" in l for l in result.limitations)
    # meters incremented once per metric with {mode, tenant} labels
    assert metrics.get_counter("relationship_spine.run", {"mode": "off", "tenant": tenant}) == 1
    assert metrics.get_counter("relationship_spine.fidelity.computed", {"mode": "off", "tenant": tenant}) == 1
    assert metrics.get_counter("relationship_spine.fidelity.persisted", {"mode": "off", "tenant": tenant}) == 0

    async def _no_run():
        return await get_computation_repository().get_run(tenant, "run_fidelity_fid_x")

    assert asyncio.run(_no_run()) is None


def test_shadow_persists_observation_only(coordinator, monkeypatch):
    _set_mode(monkeypatch, "shadow")
    tenant = "t-shadow-1"

    async def _run():
        return await coordinator.run_for_relationship(
            tenant_id=tenant,
            relationship_ref="a::b",
            source_entity_id="a",
            target_entity_id="b",
            observations=_obs(),
            enrich_incentives=False,
        )

    result = asyncio.run(_run())
    assert result.persisted is True
    assert result.run_id
    assert any("observation/compare-only" in l for l in result.limitations)

    async def _read():
        return await get_computation_repository().get_run(tenant, result.run_id)

    run = asyncio.run(_read())
    assert run is not None
    assert run["data"]["kind"] == "fidelity_vector_surface"
    assert run["data"]["mode"] == "shadow"


def test_enforce_persists_and_records_run(coordinator, monkeypatch):
    _set_mode(monkeypatch, "enforce")
    tenant = "t-enforce-1"

    async def _run():
        return await coordinator.run_for_relationship(
            tenant_id=tenant,
            relationship_ref="a::b",
            source_entity_id="a",
            target_entity_id="b",
            observations=_obs(),
            enrich_incentives=False,
        )

    result = asyncio.run(_run())
    assert result.persisted is True
    assert result.mode == "enforce"
    assert result.incentive_assessed is False
    assert result.independence_known is True  # 2 independent sources resolve
    assert result.run_id

    async def _read():
        return await get_computation_repository().get_run(tenant, result.run_id)

    run = asyncio.run(_read())
    assert run["data"]["relationship_ref"] == "a::b"
    assert metrics.get_counter("relationship_spine.fidelity.persisted", {"mode": "enforce", "tenant": tenant}) == 1


def test_persist_false_suppresses_even_in_enforce(coordinator, monkeypatch):
    _set_mode(monkeypatch, "enforce")
    tenant = "t-suppress-1"

    async def _run():
        return await coordinator.run_for_relationship(
            tenant_id=tenant,
            relationship_ref="a::b",
            source_entity_id="a",
            target_entity_id="b",
            observations=_obs(),
            enrich_incentives=False,
            persist=False,
        )

    result = asyncio.run(_run())
    assert result.persisted is False
    assert result.run_id is None
    assert any("Persistence suppressed by caller" in l for l in result.limitations)


def test_mode_off_with_explicit_persist_true_overrides(coordinator, monkeypatch):
    _set_mode(monkeypatch, "off")
    tenant = "t-off-override"

    async def _run():
        return await coordinator.run_for_relationship(
            tenant_id=tenant,
            relationship_ref="a::b",
            source_entity_id="a",
            target_entity_id="b",
            observations=_obs(),
            enrich_incentives=False,
            persist=True,
        )

    result = asyncio.run(_run())
    assert result.persisted is True
    assert result.run_id
    assert any("explicit caller override" in l for l in result.limitations)


def test_no_observations_yields_unknown_not_zero(coordinator, monkeypatch):
    _set_mode(monkeypatch, "enforce")
    tenant = "t-empty-1"

    async def _run():
        return await coordinator.run_for_relationship(
            tenant_id=tenant,
            relationship_ref="a::b",
            source_entity_id="a",
            target_entity_id="b",
            observations=[],
            enrich_incentives=False,
        )

    result = asyncio.run(_run())
    assert result.vector is None
    assert result.persisted is False
    assert result.run_id is None
    assert any("fidelity unknown" in l for l in result.limitations)


# ---------------------------------------------------------------------------
# Independence
# ---------------------------------------------------------------------------


def test_resolve_independence_false_blocks_gated_dims_never_zero(coordinator, monkeypatch):
    _set_mode(monkeypatch, "off")
    tenant = "t-gate-1"

    async def _run():
        return await coordinator.run_for_relationship(
            tenant_id=tenant,
            relationship_ref="a::b",
            source_entity_id="a",
            target_entity_id="b",
            observations=_obs(),
            enrich_incentives=False,
            resolve_independence=False,
        )

    result = asyncio.run(_run())
    assert result.independence_known is False
    assert result.vector is not None
    vector = result.vector
    # Two independent-looking sources were NOT grouped -> counts stay None.
    assert vector.independent_evidence_count is None
    assert vector.independent_source_count is None
    for dim in INDEPENDENCE_GATED_DIMENSIONS:
        assert getattr(vector, dim) is None, f"{dim} must stay None (unknown), never 0"
    assert (vector.coverage or {}).get("independence_unknown") is True
    assert any("grouping declined" in l for l in result.limitations)
    # the seam is never fabricated: an explicit empty account is handed to M7
    assert any("UNKNOWN, not zero" in l for l in result.limitations)


def test_independence_known_with_two_independent_sources(coordinator, monkeypatch):
    _set_mode(monkeypatch, "off")
    tenant = "t-ind-1"

    async def _run():
        return await coordinator.run_for_relationship(
            tenant_id=tenant,
            relationship_ref="a::b",
            source_entity_id="a",
            target_entity_id="b",
            observations=_obs(),
            enrich_incentives=False,
        )

    result = asyncio.run(_run())
    assert result.independence_known is True
    assert result.vector is not None
    assert result.vector.independent_evidence_count == 2
    assert result.vector.independent_source_count == 2
    assert (result.vector.coverage or {}).get("independence_unknown") is False


# ---------------------------------------------------------------------------
# Incentive enrichment
# ---------------------------------------------------------------------------


def test_enrichment_disabled_leaves_observations_untouched_never_organic(coordinator, monkeypatch):
    _set_mode(monkeypatch, "off")
    tenant = "t-enr-off"

    async def _run():
        return await coordinator.run_for_relationship(
            tenant_id=tenant,
            relationship_ref="a::b",
            source_entity_id="a",
            target_entity_id="b",
            observations=_obs(),
        )

    result = asyncio.run(_run())
    assert result.incentive_assessed is False
    assert any("enrichment disabled" in l for l in result.limitations)
    vector = result.vector
    quality = (vector.quality or {}).get("dimensions") or {}
    assert quality.get("incentive_assessment_coverage") == "insufficient_data"
    # unassessed is never organic: incentive exposure stays unknown (None)
    assert vector.incentive_exposure is None


def test_enrichment_resolve_failure_is_a_limitation_not_an_abort(monkeypatch):
    _set_mode(monkeypatch, "enforce")
    tenant = "t-enr-fail"
    failing = _FakeIncentiveService(ctx=None, exc=RuntimeError("resolver down"))
    coord = RelationshipSpineCoordinator(incentive_service=failing)

    async def _run():
        return await coord.run_for_relationship(
            tenant_id=tenant,
            relationship_ref="a::b",
            source_entity_id="a",
            target_entity_id="b",
            observations=_obs(),
            enrich_incentives=True,
        )

    result = asyncio.run(_run())
    assert result.vector is not None  # run survives a resolver failure
    assert result.incentive_assessed is False
    assert any("enrichment failed" in l for l in result.limitations)
    quality = (result.vector.quality or {}).get("dimensions") or {}
    assert quality.get("incentive_assessment_coverage") == "insufficient_data"


def test_enrichment_assesses_and_flags_exposure_within_window(monkeypatch):
    _set_mode(monkeypatch, "off")
    tenant = "t-enr-in"
    ctx = SimpleNamespace(
        status="declared",
        direct_incentive=False,
        exposure_started_at="2026-08-01T00:00:00Z",
        exposure_ended_at="2026-08-31T00:00:00Z",
    )
    coord = RelationshipSpineCoordinator(incentive_service=_FakeIncentiveService(ctx))

    async def _run():
        return await coord.run_for_relationship(
            tenant_id=tenant,
            relationship_ref="a::b",
            source_entity_id="a",
            target_entity_id="b",
            observations=_obs(),
            enrich_incentives=True,
        )

    result = asyncio.run(_run())
    assert result.incentive_assessed is True
    quality = (result.vector.quality or {}).get("dimensions") or {}
    assert quality.get("incentive_assessment_coverage") == "ready"
    # both observations fall inside the declared exposure window
    assert result.vector.incentive_exposure == 1.0


def test_enrichment_exposure_is_a_measured_zero_when_no_incentive(monkeypatch):
    _set_mode(monkeypatch, "off")
    tenant = "t-enr-zero"
    ctx = SimpleNamespace(
        status="none_observed",
        direct_incentive=False,
        exposure_started_at=None,
        exposure_ended_at=None,
    )
    coord = RelationshipSpineCoordinator(incentive_service=_FakeIncentiveService(ctx))

    async def _run():
        return await coord.run_for_relationship(
            tenant_id=tenant,
            relationship_ref="a::b",
            source_entity_id="a",
            target_entity_id="b",
            observations=_obs(),
            enrich_incentives=True,
            resolve_independence=False,
        )

    result = asyncio.run(_run())
    assert result.incentive_assessed is True
    # assessed 0.0 is evidence-backed (every obs assessed, none incentive-present)
    assert result.vector.incentive_exposure == 0.0
    quality = (result.vector.quality or {}).get("dimensions") or {}
    assert quality.get("incentive_assessment_coverage") == "ready"
    # independence-gated dims stay None even though exposure was assessed
    assert result.vector.incentive_independence_support is None


def test_run_contract_fields(coordinator, monkeypatch):
    _set_mode(monkeypatch, "off")
    tenant = "t-contract"

    async def _run():
        return await coordinator.run_for_relationship(
            tenant_id=tenant,
            relationship_ref="a::b",
            source_entity_id="a",
            target_entity_id="b",
            observations=_obs(),
            enrich_incentives=False,
        )

    result = asyncio.run(_run())
    assert result.relationship_ref == "a::b"
    assert result.tenant_id == tenant
    assert result.mode == "off"
    assert isinstance(result.independence_known, bool)
    assert result.vector is not None
