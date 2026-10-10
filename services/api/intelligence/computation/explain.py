"""Explainability for canonical results.

Turns a stored :class:`CanonicalResult` + its definition into a plain-language
answer to "what is this number?" — definition version, formula/kind, inputs,
window, dimensions, whether it is observed / allocated / estimated / predicted /
reconciled, completeness, staleness, uncertainty, and its supersession state.
"""

from __future__ import annotations

from typing import Any, Optional

from shared.computation.definition import ComputationDefinition
from shared.computation.registry import get_definition

_KIND_NATURE = {
    "observed_fact": "observed",
    "deterministic_metric": "deterministic",
    "allocated_value": "allocated (estimated, not observed)",
    "heuristic_score": "heuristic (uncalibrated)",
    "statistical_estimate": "estimated",
    "calibrated_probability": "calibrated probability",
    "forecast": "forecast",
    "reconciled_value": "reconciled",
    "policy_decision": "policy decision",
    "counterfactual_estimate": "counterfactual estimate",
    "simulation": "simulation",
    "rank": "rank",
    "percentile": "percentile",
    "graph_metric": "graph metric",
}


def _definition_for(result: dict) -> Optional[ComputationDefinition]:
    return get_definition(
        result.get("definition_id", ""), result.get("definition_version", "1")
    )


def build_explain(result: dict, chain: Optional[list[dict]] = None) -> dict[str, Any]:
    """Build the explain payload for a stored result dict."""
    definition = _definition_for(result)
    status = result.get("status")
    kind = definition.computation_kind.value if definition else None
    nature = _KIND_NATURE.get(kind or "", "unknown")
    is_allocated = bool(result.get("allocation"))

    return {
        "what": (
            f"{definition.display_name} — {definition.description}"
            if definition
            else result.get("definition_id")
        ),
        "definition_id": result.get("definition_id"),
        "definition_version": result.get("definition_version"),
        "value": result.get("value"),
        "value_type": result.get("value_type"),
        "unit": result.get("unit"),
        "currency": result.get("currency"),
        "status": status,
        "nature": "allocated (estimated, not observed)" if is_allocated else nature,
        "formula": {
            "numerator": result.get("numerator"),
            "denominator": result.get("denominator"),
            "aggregation": definition.aggregation_type.value if definition else None,
        },
        "inputs": (definition.required_inputs if definition else [])
        + (definition.dependency_definitions if definition else []),
        "window": result.get("window"),
        "as_of": result.get("as_of"),
        "dimensions": result.get("dimensions"),
        "is_observed": kind == "observed_fact" and not is_allocated,
        "is_allocated": is_allocated or kind == "allocated_value",
        "is_estimated": status in {"estimated", "partial"},
        "is_predicted": kind in {"forecast", "calibrated_probability"},
        "is_reconciled": bool(result.get("reconciliation")),
        "population_complete": status not in {"partial", "truncated", "insufficient_data"},
        "is_stale": status == "stale",
        "uncertainty": result.get("uncertainty"),
        "quality": result.get("quality"),
        "lineage": result.get("lineage"),
        "superseded_by": result.get("superseded_by"),
        "supersedes_result_id": result.get("supersedes_result_id"),
        "restatement_reason": result.get("restatement_reason"),
        "restatement_chain": chain or [],
        "decision_impact_class": (
            definition.decision_impact_class.value if definition else None
        ),
        "permitted_consumers": definition.permitted_consumers if definition else [],
    }


__all__ = ["build_explain"]
