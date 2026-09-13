"""Demographic lens tests (population360 P3.4).

Pins the lens contract: demographics are a governed human lens over canonical
profile facts — no ``Demographic360`` backend exists; small-cell suppression is
configurable (and never labeled differential privacy); ``not_applicable`` /
``empty`` / ``unknown`` / ``missing`` / ``degraded`` stay distinct typed states;
a missing profile-fact source degrades honestly (never fabricates).
"""

from __future__ import annotations

import pytest

from services.population360.demographics import (
    DEFAULT_MINIMUM_CELL_SIZE,
    DemographicLens,
    HumanProfileFact,
    LENS_DIMENSIONS,
    SmallCellSuppression,
    UnavailableProfileFactsReader,
    aggregate_human_profile,
    derive_age_band,
    suppress_distribution,
)

TENANT = "tenant_pop360_demo"


# ── Small-cell suppression (pure) ─────────────────────────────────────────────


def test_suppression_withholds_cells_below_floor_and_reports_total():
    dist = suppress_distribution(
        "age_band",
        {"25-34": 12, "35-44": 3, "65+": 8},
        SmallCellSuppression(minimum_cell_size=5),
    )
    assert dist.buckets == {"25-34": 12, "65+": 8}
    assert dist.suppressed_cells == 1
    assert dist.suppressed_total == 3
    assert dist.total == 23  # aggregate honestly covers the withheld cells


def test_suppression_disabled_shows_every_cell():
    dist = suppress_distribution(
        "gender",
        {"female": 4, "male": 90},
        SmallCellSuppression(minimum_cell_size=5, enabled=False),
    )
    assert dist.buckets == {"female": 4, "male": 90}
    assert dist.suppressed_cells == 0


def test_suppression_default_floor_is_five():
    assert SmallCellSuppression().minimum_cell_size == DEFAULT_MINIMUM_CELL_SIZE == 5
    assert SmallCellSuppression().enabled is True


def test_suppression_does_not_mutate_input():
    counts = {"female": 4, "male": 90}
    suppress_distribution("gender", counts, SmallCellSuppression())
    assert counts == {"female": 4, "male": 90}


# ── Age-band derivation (pure) ────────────────────────────────────────────────


@pytest.mark.parametrize(
    "age,band",
    [(0, "0-17"), (17, "0-17"), (18, "18-24"), (24, "18-24"), (25, "25-34"),
     (34, "25-34"), (44, "35-44"), (54, "45-54"), (64, "55-64"), (65, "65+"),
     (99, "65+"), (None, None), (-1, None)],
)
def test_age_band_edges(age, band):
    assert derive_age_band({"age": age}, as_of_year=2026) == band


def test_age_band_from_birthdate_year():
    assert derive_age_band({"birthdate": "2000-04-01"}, as_of_year=2026) == "25-34"
    # A malformed birthdate yields no band (never a fabricated bucket).
    assert derive_age_band({"birthdate": "not-a-date"}, as_of_year=2026) is None
    # Raw age wins when both present.
    assert derive_age_band(
        {"age": 70, "birthdate": "2000-04-01"}, as_of_year=2026
    ) == "65+"


def test_unknown_categorical_buckets_to_other_not_dropped():
    dists = aggregate_human_profile(
        {
            "u1": {"gender": "genderfluid"},
            "u2": {"gender": "male"},
            "u3": {"gender": "non_binary"},
        },
        as_of_year=2026,
        suppression=SmallCellSuppression(minimum_cell_size=1, enabled=True),
    )
    assert dists["gender"].buckets["male"] == 1
    assert dists["gender"].buckets["non_binary"] == 1
    assert dists["gender"].buckets["other"] == 1


# ── Aggregation (pure) ────────────────────────────────────────────────────────


def test_aggregate_produces_all_lens_dimensions_only():
    dists = aggregate_human_profile(
        {
            "u1": {"age": 30, "gender": "female", "language": "en"},
            "u2": {"age": 40, "gender": "male"},
        },
        as_of_year=2026,
        suppression=SmallCellSuppression(minimum_cell_size=1),
    )
    assert set(dists) == set(LENS_DIMENSIONS)
    assert dists["age_band"].buckets == {"25-34": 1, "35-44": 1}
    assert dists["gender"].buckets == {"female": 1, "male": 1}
    assert dists["language"].buckets == {"en": 1}
    # u2 has no language fact — the language dimension totals only observed facts.
    assert dists["language"].total == 1


def test_aggregate_applies_suppression_per_dimension():
    dists = aggregate_human_profile(
        {
            f"u{i}": {"age": 30} for i in range(6)  # six 25-34s
        }
        | {"u6": {"age": 70}},
        as_of_year=2026,
        suppression=SmallCellSuppression(minimum_cell_size=5),
    )
    age = dists["age_band"]
    assert age.buckets == {"25-34": 6}  # the single 65+ cell is withheld
    assert age.suppressed_cells == 1
    assert age.suppressed_total == 1
    assert age.total == 7


# ── The lens (seams + typed states) ───────────────────────────────────────────


class _FakeProfileFactsReader:
    def __init__(self, facts: dict[str, HumanProfileFact],
                 *, fail: bool = False) -> None:
        self._facts = facts
        self._fail = fail

    async def facts_for(self, *, tenant_id: str, entity_ids: list[str]):
        if self._fail:
            raise RuntimeError("profile store down")
        return {eid: self._facts[eid] for eid in entity_ids if eid in self._facts}


@pytest.mark.asyncio
async def test_entity_subject_is_not_applicable():
    lens = DemographicLens(facts_reader=_FakeProfileFactsReader({}))
    result = await lens.lens_for_population(
        tenant_id=TENANT, subject_kind="entity", entity_ids=["u1"]
    )
    assert result.applicable is False
    assert result.state == "not_applicable"
    assert result.dimensions == {}


@pytest.mark.asyncio
async def test_population_with_no_active_members_is_empty_not_fabricated_zero():
    lens = DemographicLens(facts_reader=_FakeProfileFactsReader({}))
    result = await lens.lens_for_population(
        tenant_id=TENANT, subject_kind="population", entity_ids=[]
    )
    assert result.applicable is True
    assert result.state == "empty"
    assert result.total_members == 0


@pytest.mark.asyncio
async def test_default_reader_degrades_to_missing_while_profile360_in_flight():
    # UnavailableProfileFactsReader is the default when no reader is injected.
    lens = DemographicLens()
    assert isinstance(lens._reader, UnavailableProfileFactsReader)
    result = await lens.lens_for_population(
        tenant_id=TENANT, subject_kind="population", entity_ids=["u1"]
    )
    assert result.applicable is True
    assert result.state == "missing"  # profile360 is in_flight — honest, not fake
    assert result.total_members == 1


@pytest.mark.asyncio
async def test_members_without_canonical_facts_render_unknown():
    lens = DemographicLens(facts_reader=_FakeProfileFactsReader({}))
    result = await lens.lens_for_population(
        tenant_id=TENANT, subject_kind="cluster", entity_ids=["u1", "u2"]
    )
    assert result.applicable is True
    assert result.state == "unknown"
    assert result.profiled_members == 0


@pytest.mark.asyncio
async def test_lens_reads_canonical_profile_facts_and_applies_suppression():
    facts = {
        **{f"u{i}": {"age": 30, "gender": "female"} for i in range(6)},
        "u6": {"age": 70, "gender": "male"},
    }
    lens = DemographicLens(facts_reader=_FakeProfileFactsReader(facts))
    result = await lens.lens_for_population(
        tenant_id=TENANT,
        subject_kind="population",
        entity_ids=list(facts),
        suppression=SmallCellSuppression(minimum_cell_size=5),
    )
    assert result.state == "available"
    assert result.total_members == 7
    assert result.profiled_members == 7
    # The sparse male cell is withheld; the visible aggregate is honest.
    assert result.dimensions["gender"].buckets == {"female": 6}
    assert result.dimensions["gender"].suppressed_cells == 1
    assert result.dimensions["age_band"].buckets == {"25-34": 6}


@pytest.mark.asyncio
async def test_reader_failure_degrades_not_raises():
    lens = DemographicLens(facts_reader=_FakeProfileFactsReader({}, fail=True))
    result = await lens.lens_for_population(
        tenant_id=TENANT, subject_kind="population", entity_ids=["u1"]
    )
    assert result.state == "degraded"
    assert result.warnings
