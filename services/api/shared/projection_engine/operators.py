"""Projection operators (A8 projection engine).

An operator is a declared shaping verb a lens set applies to a projection —
SELECT (which sections), TRAVERSE (graph hops), MEASURE (metrics), AGGREGATE
(rollups), RANK (ordering), FINDING (synthesized claims). Operators are carried
by the compiled IR and applied by the executor to the composed result.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field as dataclass_field
from typing import Optional


class Operator(enum.Enum):
    """The operator vocabulary of the projection engine."""

    SELECT = "select"  # restrict rendered sections
    TRAVERSE = "traverse"  # expand along graph relationships
    MEASURE = "measure"  # attach metric content
    AGGREGATE = "aggregate"  # roll up to a coarser grain
    RANK = "rank"  # order sections / findings
    FINDING = "finding"  # synthesize evidence-backed claims


_OPERATOR_REQUIRED_KIND = frozenset(
    {"entity_360", "relationship_360", "sequence_360", "context_360"}
)
_OPERATOR_SELECTION_KINDS = frozenset(
    {"measurement_360", "risk_360", "operational_workbench"}
)


@dataclass(frozen=True)
class OperatorSpec:
    """One applied operator."""

    operator: Operator
    field: Optional[str] = None  # the section / metric / relationship the operator acts on
    params: dict = dataclass_field(default_factory=dict)  # operator-specific parameters


def validate_operators(
    operators: list[OperatorSpec],
    *,
    projection_kind: Optional[str] = None,
) -> list[str]:
    """Validate operator legality for a projection kind.

    Returns a list of violation messages (empty when legal). The engine refuses
    to apply a FINDING / AGGREGATE operator to a measurement workbench or to
    ask a non-graph projection to TRAVERSE — an illegal operator request is a
    request bug, surfaced at compile time (``PARAMETER_CONFLICT``).
    """
    violations: list[str] = []
    if not projection_kind:
        return violations
    for spec in operators:
        if (
            spec.operator in (Operator.TRAVERSE, Operator.AGGREGATE)
            and projection_kind not in _OPERATOR_REQUIRED_KIND
        ):
            violations.append(
                f"operator {spec.operator.value!r} is not legal for projection "
                f"kind {projection_kind!r}"
            )
        if (
            spec.operator is Operator.FINDING
            and projection_kind not in _OPERATOR_SELECTION_KINDS
        ):
            violations.append(
                f"operator {spec.operator.value!r} is not legal for projection "
                f"kind {projection_kind!r}"
            )
    return violations


__all__ = ["Operator", "OperatorSpec", "validate_operators"]
