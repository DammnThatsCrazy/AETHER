"""Conditioned facets with cohort-minimum suppression.

A facet is a value→count breakdown of the records currently in scope. The
filter-field registry declares a ``minimum_cohort_size`` for privacy-sensitive
fields (e.g. ``geography.city`` = 25). Any bucket whose count is below the
field's minimum is SUPPRESSED — dropped from the returned buckets and folded
into a ``suppressed_bucket_count`` with a reason recorded in the envelope — so
a small cohort can never be re-identified from a facet.

Facets are computed over plain record dicts, so this module has no dependency
on any read plane and is exercised directly by the suppression unit tests.
"""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field

from shared.exploration.generated_fields import FILTER_FIELDS


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class FacetBucket(_Model):
    value: str
    count: int


class SurfaceFacet(_Model):
    field: str
    buckets: list[FacetBucket] = Field(default_factory=list)
    suppressed_bucket_count: int = 0
    suppressed_record_count: int = 0
    minimum_cohort_size: Optional[int] = None
    suppression_reason: Optional[str] = None


class FacetResult(_Model):
    facets: list[SurfaceFacet] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


def minimum_cohort_size(field_id: str) -> Optional[int]:
    spec = FILTER_FIELDS.get(field_id)
    if spec is None:
        return None
    value = spec.get("minimum_cohort_size")
    return int(value) if value is not None else None


def _extract(record: dict[str, Any], field_id: str) -> Optional[str]:
    """Read a facet field from a record dict, honouring dotted paths.

    Records are surface-shaped dicts (e.g. graph node ``properties``). A field
    is looked up by its full dotted id, by its last segment, and inside a nested
    ``properties`` map — whichever resolves first.
    """
    if field_id in record and record[field_id] is not None:
        return str(record[field_id])
    leaf = field_id.split(".")[-1]
    if leaf in record and record[leaf] is not None:
        return str(record[leaf])
    props = record.get("properties")
    if isinstance(props, dict):
        for key in (field_id, leaf):
            if key in props and props[key] is not None:
                return str(props[key])
    return None


def compute_facets(records: list[dict[str, Any]], fields: list[str]) -> FacetResult:
    """Compute value→count facets for ``fields`` with cohort-minimum suppression."""
    result = FacetResult()
    for field_id in fields:
        minimum = minimum_cohort_size(field_id)
        counts: dict[str, int] = {}
        for record in records:
            value = _extract(record, field_id)
            if value is None:
                continue
            counts[value] = counts.get(value, 0) + 1

        kept: list[FacetBucket] = []
        suppressed_buckets = 0
        suppressed_records = 0
        for value, count in sorted(counts.items(), key=lambda x: (-x[1], x[0])):
            if minimum is not None and count < minimum:
                suppressed_buckets += 1
                suppressed_records += count
                continue
            kept.append(FacetBucket(value=value, count=count))

        facet = SurfaceFacet(
            field=field_id,
            buckets=kept,
            suppressed_bucket_count=suppressed_buckets,
            suppressed_record_count=suppressed_records,
            minimum_cohort_size=minimum,
            suppression_reason=(
                f"buckets_below_cohort_minimum_{minimum}"
                if suppressed_buckets
                else None
            ),
        )
        result.facets.append(facet)
        if suppressed_buckets:
            result.warnings.append(
                f"facet_{field_id}_suppressed_{suppressed_buckets}_small_cohorts"
            )
    return result


__all__ = [
    "FacetBucket",
    "SurfaceFacet",
    "FacetResult",
    "compute_facets",
    "minimum_cohort_size",
]
