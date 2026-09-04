"""Pure exploration operation semantics — no I/O, no session state.

``apply_operation`` transforms ONE :class:`ExplorationContextV1` into another
via ``model_copy(update=...)``: a field the operation does NOT target is
byte-identical in the output (the context-inheritance invariant), and the
input object is never mutated. Every rejection returns the input context
untouched with a content-free, reason-coded rejection.

``SAVE`` / ``LOAD`` are session-repository operations — the pure layer returns
the ``save_is_a_session_operation`` rejection and the service intercepts them
BEFORE calling this module (a second primitive would silently split the
session state).
"""

from __future__ import annotations

from typing import Optional

from shared.contracts_models.filters import FilterGroup
from shared.exploration.models import (
    ExplorationContextV1,
    GraphConstraints,
    PivotSpec,
    SelectionSet,
)
from shared.projection_engine.conflict import LensConflict, LensNotFound
from shared.projection_engine.lens_registry import (
    LensRegistry,
    lens_registry as _default_lens_registry,
)
from shared.projection_engine.lens_set import LensSet
from shared.projection_engine.temporal_modes import parse_temporal_mode
from services.exploration.planner import iter_leaf_expressions

_MIN_DEPTH = 1
_MAX_DEPTH = 10

_REASON_SAVE_IS_SESSION = "save_is_a_session_operation"


def _lens_rejection_reason(exc: Exception, lens_ids: Optional[list[str]]) -> str:
    """Map a lens-composition conflict to a stable, content-free reason code."""
    lens_id = getattr(exc, "lens_id", None)
    if isinstance(exc, LensNotFound):
        return f"unknown_lens_id:{lens_id or 'unknown'}"
    message = str(exc)
    if "must not be composed as an overlay" in message:
        return f"self_base_lens:{lens_id or 'unknown'}"
    if "not the lens set base" in message:
        return f"lens_base_mismatch:{lens_id or 'unknown'}"
    if "not a base-kind lens" in message:
        return f"lens_base_mismatch:{lens_id or 'unknown'}"
    return f"lens_conflict:{lens_id or 'unknown'}"


def _pivot(
    context: ExplorationContextV1, pivot: Optional[PivotSpec]
) -> tuple[ExplorationContextV1, Optional[str], list[str]]:
    if pivot is None:
        return context, "pivot_requires_spec", []
    update = {
        "scope": context.scope.model_copy(update={"surface": pivot.target_surface})
    }
    selection = context.selection
    if pivot.clear_selection:
        selection = None
    if pivot.focus is not None:
        if selection is None:
            selection = SelectionSet()
        selection = selection.model_copy(update={"focused": pivot.focus})
    if pivot.clear_selection or pivot.focus is not None:
        update["selection"] = selection
    return context.model_copy(update=update), None, []


def _depth(
    context: ExplorationContextV1, operation: str
) -> tuple[ExplorationContextV1, Optional[str], list[str]]:
    graph = context.graph
    current = graph.depth if graph is not None and graph.depth is not None else _MIN_DEPTH
    if graph is None:
        graph = GraphConstraints()
    delta = 1 if operation == "EXPAND" else -1
    new_depth = min(_MAX_DEPTH, max(_MIN_DEPTH, current + delta))
    return (
        context.model_copy(update={"graph": graph.model_copy(update={"depth": new_depth})}),
        None,
        [],
    )


def _filter_add(
    context: ExplorationContextV1, filter_group: Optional[FilterGroup]
) -> tuple[ExplorationContextV1, Optional[str], list[str]]:
    if filter_group is None:
        return context, "filter_add_requires_group", []
    existing = context.population
    if existing is None:
        new_pop = filter_group
    else:
        # Compose additively: a fresh AND node keeps the existing group
        # structurally intact (never drops an existing expression).
        new_pop = FilterGroup(logic="AND", expressions=[existing, filter_group])
    return context.model_copy(update={"population": new_pop}), None, []


def _remove_fields(group: FilterGroup, fields_to_remove: set[str]) -> Optional[FilterGroup]:
    """Deep-remove every expression whose field is in ``fields_to_remove``.

    An emptied nested group is dropped (honest: no filters = ``None`` at the
    top level, never an empty group).
    """
    kept = []
    for expr in group.expressions:
        if isinstance(expr, FilterGroup):
            inner = _remove_fields(expr, fields_to_remove)
            if inner is not None:
                kept.append(inner)
        elif expr.field not in fields_to_remove:
            kept.append(expr)
    if not kept:
        return None
    return group.model_copy(update={"expressions": kept})


def _filter_remove(
    context: ExplorationContextV1, filter_group: Optional[FilterGroup]
) -> tuple[ExplorationContextV1, Optional[str], list[str]]:
    if filter_group is None:
        return context, "filter_remove_requires_fields", []
    fields_to_remove = {expr.field for expr in iter_leaf_expressions(filter_group)}
    if not fields_to_remove:
        return context, "filter_remove_requires_fields", []
    if context.population is None:
        return context, None, []
    new_pop = _remove_fields(context.population, fields_to_remove)
    return context.model_copy(update={"population": new_pop}), None, []


def _lens_add(
    context: ExplorationContextV1,
    lens_ids: Optional[list[str]],
    lens_registry: Optional[LensRegistry],
) -> tuple[ExplorationContextV1, Optional[str], list[str]]:
    if not lens_ids:
        return context, "lens_add_requires_ids", []
    registry = lens_registry or _default_lens_registry
    try:
        frame = LensSet.from_request(list(lens_ids), registry=registry)
        frame.validate(registry)
    except (LensConflict, LensNotFound) as exc:
        return context, _lens_rejection_reason(exc, lens_ids), []
    update = {"lens_set": list(lens_ids)}
    if context.temporal_mode is None:
        # A lens frame implies the engine frame exists — honest default.
        update["temporal_mode"] = "live"
    return context.model_copy(update=update), None, []


def _time_travel(
    context: ExplorationContextV1,
    temporal,
    temporal_mode: Optional[str],
) -> tuple[ExplorationContextV1, Optional[str], list[str]]:
    if temporal is None:
        return context, "time_travel_requires_temporal", []
    update = {"temporal": temporal}
    if temporal_mode is not None:
        if parse_temporal_mode(temporal_mode) is None:
            return context, f"invalid_temporal_mode:{temporal_mode}", []
        update["temporal_mode"] = temporal_mode
    return context.model_copy(update=update), None, []


def _drill_down(
    context: ExplorationContextV1, focus
) -> tuple[ExplorationContextV1, Optional[str], list[str]]:
    if focus is None:
        return context, "drill_down_requires_focus", []
    selection = context.selection
    if selection is None:
        selection = SelectionSet()
    selection = selection.model_copy(update={"focused": focus})
    update = {"selection": selection}
    if context.graph is not None:
        # Narrow the lens; do NOT invent a graph when absent.
        update["graph"] = context.graph.model_copy(update={"depth": _MIN_DEPTH})
    return context.model_copy(update=update), None, []


def apply_operation(
    context: ExplorationContextV1,
    operation: str,
    *,
    pivot: Optional[PivotSpec] = None,
    lens_ids: Optional[list[str]] = None,
    temporal=None,
    filter_group: Optional[FilterGroup] = None,
    focus=None,
    seed: Optional[ExplorationContextV1] = None,
    lens_registry: Optional[LensRegistry] = None,
    temporal_mode: Optional[str] = None,
) -> tuple[ExplorationContextV1, Optional[str], list[str]]:
    """Apply one pure operation to ``context``.

    Returns ``(new_context, rejection_reason_or_None, warnings)``. On rejection
    ``new_context`` is the INPUT context untouched and ``rejection_reason`` is
    a content-free, reason-coded string.
    """
    if operation in ("SAVE", "LOAD"):
        return context, _REASON_SAVE_IS_SESSION, []
    if operation in ("OPEN", "RESET"):
        return (seed if seed is not None else context), None, []
    if operation == "PIVOT":
        return _pivot(context, pivot)
    if operation in ("EXPAND", "COLLAPSE"):
        return _depth(context, operation)
    if operation == "FILTER_ADD":
        return _filter_add(context, filter_group)
    if operation == "FILTER_REMOVE":
        return _filter_remove(context, filter_group)
    if operation == "LENS_ADD":
        return _lens_add(context, lens_ids, lens_registry)
    if operation == "TIME_TRAVEL":
        return _time_travel(context, temporal, temporal_mode)
    if operation == "DRILL_DOWN":
        return _drill_down(context, focus)
    return context, f"unknown_operation:{operation}", []


__all__ = ["apply_operation"]
