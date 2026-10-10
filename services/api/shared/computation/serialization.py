"""Serialization helpers for canonical results.

Canonical values serialize as JSON-safe dicts with their type, unit, status, and
presentation metadata attached — so a frontend can FORMAT a value but never has
to (or gets to) reinterpret it.
"""

from __future__ import annotations

from typing import Any

from shared.computation.result import CanonicalResult


def presentation_metadata(result: CanonicalResult) -> dict[str, Any]:
    """The display contract for a result: what to show and how, plus warnings.

    The substrate does not format numbers for a locale, but it does tell the
    presentation layer the unit, currency, status, and any warning it must
    surface (stale/partial/estimated/allocated/truncated) so those states are
    never hidden.
    """
    warnings: list[str] = []
    status = result.status.value
    if status in {"stale", "partial", "estimated", "truncated", "conflicted", "unreconciled"}:
        warnings.append(status)
    if result.allocation:
        warnings.append("allocated")
    return {
        "display_value": result.value,
        "display_unit": result.unit,
        "display_currency": result.currency,
        "display_status": status,
        "value_type": result.value_type.value,
        "warnings": warnings,
        "explain_ref": f"/v1/computations/results/{result.result_id}/explain",
        "definition_ref": f"/v1/computations/definitions/{result.definition_id}",
    }


def result_to_wire(result: CanonicalResult) -> dict[str, Any]:
    """A JSON-safe wire representation of a result with presentation metadata."""
    payload = result.model_dump(mode="json")
    payload["presentation"] = presentation_metadata(result)
    return payload


__all__ = ["presentation_metadata", "result_to_wire"]
