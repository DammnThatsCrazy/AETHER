"""Exploration planner — the anti-silent-drop core of the fabric.

Every ``FilterExpression`` submitted in an ``ExplorationContextV1.population``
is validated against the canonical filter-field registry
(``shared.exploration.generated_fields.FILTER_FIELDS``) and the target surface's
declared capabilities (``shared.exploration.generated_surfaces``). The planner
emits EXACTLY ONE ``FilterApplicabilityEntry`` per submitted leaf filter — a
filter may be ``applied``, ``translated``, ``unsupported``, ``suppressed``, or
``not_applicable``, but it can never be silently dropped. That completeness is
asserted here (defensively) and by the planner golden corpus.

Only filters that resolve to ``applied``/``translated`` are routed to the
surface adapter; the rest are recorded, never executed.
"""

from __future__ import annotations

from dataclasses import dataclass, field as _dc_field
from typing import Iterable, Optional

from shared.contracts_models.filters import FilterExpression, FilterGroup
from shared.exploration.generated_fields import FILTER_FIELDS
from shared.exploration.generated_surfaces import SURFACE_CAPABILITIES
from shared.exploration.models import (
    ApplicabilityReport,
    ExplorationContextV1,
    FilterApplicabilityEntry,
)

# Dispositions that mean "this filter reaches the adapter".
_ROUTED_DISPOSITIONS = frozenset({"applied", "translated"})


def iter_leaf_expressions(group: Optional[FilterGroup]) -> Iterable[FilterExpression]:
    """Yield every leaf ``FilterExpression`` in a (possibly nested) group.

    Order is stable (depth-first, left-to-right) so the applicability report is
    deterministic for a given context.
    """
    if group is None:
        return
    for expr in group.expressions:
        if isinstance(expr, FilterGroup):
            yield from iter_leaf_expressions(expr)
        elif isinstance(expr, FilterExpression):
            yield expr
        else:  # pragma: no cover - pydantic guarantees one of the two above
            raise TypeError(f"Unexpected filter node: {type(expr)!r}")


def _op_value(expr: FilterExpression) -> str:
    op = expr.op
    return getattr(op, "value", str(op))


@dataclass
class PlannedFilter:
    """One submitted filter plus the decision the planner made about it."""

    expression: FilterExpression
    entry: FilterApplicabilityEntry

    @property
    def routed(self) -> bool:
        return self.entry.disposition in _ROUTED_DISPOSITIONS


@dataclass
class ExplorationPlan:
    """The validated plan for one exploration request against one surface."""

    surface: str
    surface_registered: bool
    planned: list[PlannedFilter] = _dc_field(default_factory=list)
    warnings: list[str] = _dc_field(default_factory=list)

    @property
    def applied_filters(self) -> list[FilterExpression]:
        return [p.expression for p in self.planned if p.routed]

    @property
    def applicability(self) -> ApplicabilityReport:
        return ApplicabilityReport(entries=[p.entry for p in self.planned])

    def assert_complete(self, submitted: int) -> None:
        """Guarantee one applicability entry per submitted filter."""
        produced = len(self.planned)
        if produced != submitted:  # pragma: no cover - defensive invariant
            raise AssertionError(
                "exploration planner dropped filters: "
                f"{submitted} submitted, {produced} accounted for"
            )


def plan_context(
    context: ExplorationContextV1,
    *,
    redacted_fields: Optional[frozenset[str]] = None,
) -> ExplorationPlan:
    """Validate ``context.population`` against the target surface.

    ``redacted_fields`` are governance-suppressed field ids (e.g. a restricted
    field the caller lacks scope for): they resolve to ``suppressed`` rather
    than being applied. Default empty — nothing is suppressed without an
    explicit, honest governance signal.
    """
    redacted = redacted_fields or frozenset()
    surface = context.scope.surface
    caps = SURFACE_CAPABILITIES.get(surface)
    plan = ExplorationPlan(surface=surface, surface_registered=caps is not None)

    if caps is None:
        plan.warnings.append(f"surface_not_registered:{surface}")

    supported_categories = (
        frozenset(caps["supported_field_categories"]) if caps else frozenset()
    )

    leaves = list(iter_leaf_expressions(context.population))
    for expr in leaves:
        plan.planned.append(
            PlannedFilter(
                expression=expr,
                entry=_dispose(expr, caps, supported_categories, redacted),
            )
        )

    plan.assert_complete(len(leaves))
    return plan


def _dispose(
    expr: FilterExpression,
    caps: Optional[dict],
    supported_categories: frozenset[str],
    redacted: frozenset[str],
) -> FilterApplicabilityEntry:
    field_id = expr.field

    if caps is None:
        return FilterApplicabilityEntry(
            field=field_id,
            disposition="not_applicable",
            reason="surface_not_registered",
        )

    spec = FILTER_FIELDS.get(field_id)
    if spec is None:
        return FilterApplicabilityEntry(
            field=field_id,
            disposition="unsupported",
            reason="field_not_registered",
        )

    op = _op_value(expr)
    if op not in spec["operators"]:
        return FilterApplicabilityEntry(
            field=field_id,
            disposition="unsupported",
            reason=f"operator_not_supported_for_field:{op}",
        )

    if field_id in redacted:
        return FilterApplicabilityEntry(
            field=field_id,
            disposition="suppressed",
            reason="field_redacted_by_governance",
        )

    category = spec["category"]
    if category not in supported_categories:
        return FilterApplicabilityEntry(
            field=field_id,
            disposition="not_applicable",
            reason=f"category_not_supported_by_surface:{category}",
        )

    return FilterApplicabilityEntry(field=field_id, disposition="applied", reason=None)


__all__ = [
    "ExplorationPlan",
    "PlannedFilter",
    "iter_leaf_expressions",
    "plan_context",
]
