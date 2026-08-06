"""Input lineage for a computation run.

Records what a result was actually computed from: the source aggregates or record
references, their provenance and freshness, whether the population was complete
or truncated, and the scan/cursor facts of any bounded read. This is what lets a
bounded query honestly disclose that a page total is not a population total.
"""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


class BoundedReadDisclosure(BaseModel):
    """The truncation facts of a bounded read feeding an aggregation."""

    scan_limit: Optional[int] = None
    records_scanned: Optional[int] = None
    records_matched: Optional[int] = None
    population_complete: Optional[bool] = None
    truncated: Optional[bool] = None
    next_cursor: Optional[str] = None
    coverage_estimate: Optional[float] = None


class InputLineage(BaseModel):
    """One input to a computation, with provenance and freshness."""

    input_name: str
    source: Optional[str] = None
    source_ref: Optional[str] = None
    definition_id: Optional[str] = None
    result_id: Optional[str] = None
    as_of: Optional[str] = None
    freshness: Optional[str] = None
    record_count: Optional[int] = None
    bounded_read: Optional[BoundedReadDisclosure] = None
    detail: dict[str, Any] = Field(default_factory=dict)


class ComputationLineage(BaseModel):
    """The full set of inputs behind one result."""

    inputs: list[InputLineage] = Field(default_factory=list)

    def is_truncated(self) -> bool:
        return any(
            i.bounded_read is not None and bool(i.bounded_read.truncated)
            for i in self.inputs
        )


__all__ = ["BoundedReadDisclosure", "InputLineage", "ComputationLineage"]
