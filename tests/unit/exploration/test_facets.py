"""Conditioned facets — cohort-minimum suppression is mandatory."""
from __future__ import annotations

from services.exploration.facets import compute_facets, minimum_cohort_size


def test_registry_declares_city_minimum():
    assert minimum_cohort_size("geography.city") == 25
    # A field with no declared minimum is not suppressed.
    assert minimum_cohort_size("entity.type") is None


def test_small_cohorts_are_suppressed():
    records = (
        [{"properties": {"city": "Metropolis"}} for _ in range(40)]
        + [{"properties": {"city": "Bigtown"}} for _ in range(25)]  # exactly at minimum
        + [{"properties": {"city": "Smallville"}} for _ in range(5)]  # below minimum
        + [{"properties": {"city": "Tinyhamlet"}} for _ in range(1)]
    )
    result = compute_facets(records, ["geography.city"])
    facet = result.facets[0]
    kept = {b.value: b.count for b in facet.buckets}
    assert kept == {"Metropolis": 40, "Bigtown": 25}  # >= 25 kept
    assert facet.suppressed_bucket_count == 2  # Smallville + Tinyhamlet
    assert facet.suppressed_record_count == 6
    assert facet.minimum_cohort_size == 25
    assert facet.suppression_reason == "buckets_below_cohort_minimum_25"
    assert any("geography.city_suppressed" in w for w in result.warnings)


def test_no_minimum_means_no_suppression():
    records = [{"properties": {"type": "user"}}] + [
        {"properties": {"type": "agent"}} for _ in range(1)
    ]
    result = compute_facets(records, ["entity.type"])
    facet = result.facets[0]
    assert facet.suppressed_bucket_count == 0
    assert facet.suppression_reason is None
    assert {b.value for b in facet.buckets} == {"user", "agent"}


def test_missing_values_are_ignored_not_counted():
    records = [{"properties": {}}, {"properties": {"city": "OnlyOne"}}]
    result = compute_facets(records, ["geography.city"])
    facet = result.facets[0]
    # OnlyOne is below the 25 minimum → suppressed; empty record contributes nothing.
    assert facet.buckets == []
    assert facet.suppressed_record_count == 1
