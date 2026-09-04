"""Golden corpus for the pure exploration-operation semantics (apply_operation).

Every test exercises the PURE layer: ``apply_operation(context, ...)`` returns
``(new_context, rejection_reason, warnings)`` — the input context is NEVER
mutated, a field the operation does not target is byte-identical in the output
(context-inheritance invariant), and every rejection returns the input context
untouched with a content-free, reason-coded rejection. No I/O, no session state.
"""
from __future__ import annotations

from exploration_fakes import context

from shared.contracts_models.filters import FilterExpression, FilterGroup
from shared.exploration.models import (
    ExplorationAnchor,
    GraphConstraints,
    PivotSpec,
    TemporalSelection,
)
from services.exploration.operations import apply_operation
from services.exploration.planner import iter_leaf_expressions


def _eq(field: str, value: str) -> FilterExpression:
    return FilterExpression(field=field, op="eq", value=value)


def _group(*expressions: FilterExpression, logic: str = "AND") -> FilterGroup:
    return FilterGroup(logic=logic, expressions=list(expressions))


class TestPivot:
    def test_retargets_surface_and_preserves_state(self):
        ctx = context("graph", [{"field": "entity.type", "op": "eq", "value": "human"}])
        new, rejection, warnings = apply_operation(
            ctx, "PIVOT", pivot=PivotSpec(target_surface="table")
        )
        assert rejection is None
        assert warnings == []
        assert new.scope.surface == "table"
        # Filters + fabric temporal carry over unchanged.
        assert new.population == ctx.population
        assert new.temporal == ctx.temporal

    def test_pivot_preserves_engine_frame(self):
        ctx = context("profile360").model_copy(
            update={"lens_set": ["standard", "fraud"], "temporal_mode": "live"}
        )
        new, rejection, _ = apply_operation(
            ctx, "PIVOT", pivot=PivotSpec(target_surface="graph")
        )
        assert rejection is None
        assert new.lens_set == ["standard", "fraud"]
        assert new.temporal_mode == "live"

    def test_pivot_clear_selection_and_focus(self):
        ctx = context("graph")
        new, rejection, _ = apply_operation(
            ctx,
            "PIVOT",
            pivot=PivotSpec(
                target_surface="graph",
                focus=ExplorationAnchor(kind="entity", id="e1"),
                clear_selection=True,
            ),
        )
        assert rejection is None
        assert new.selection is not None
        assert new.selection.focused.id == "e1"

    def test_pivot_without_spec_rejects(self):
        ctx = context("graph")
        new, rejection, _ = apply_operation(ctx, "PIVOT")
        assert rejection == "pivot_requires_spec"
        assert new is ctx  # untouched

    def test_input_never_mutated(self):
        ctx = context("graph", [{"field": "entity.type", "op": "eq", "value": "human"}])
        before = ctx.model_dump(mode="json")
        apply_operation(ctx, "PIVOT", pivot=PivotSpec(target_surface="map"))
        apply_operation(ctx, "EXPAND")
        apply_operation(
            ctx, "FILTER_ADD", filter_group=_group(_eq("geography.city", "NYC"))
        )
        apply_operation(
            ctx, "FILTER_REMOVE", filter_group=_group(_eq("entity.type", "human"))
        )
        apply_operation(ctx, "LENS_ADD", lens_ids=["standard", "fraud"])
        assert ctx.model_dump(mode="json") == before


class TestDepth:
    def test_expand_initializes_depth(self):
        ctx = context("graph")  # no graph constraints → default depth 1
        new, rejection, _ = apply_operation(ctx, "EXPAND")
        assert rejection is None
        assert new.graph is not None
        assert new.graph.depth == 2

    def test_collapse_clamps_at_min(self):
        ctx = context("graph")
        new, rejection, _ = apply_operation(ctx, "COLLAPSE")
        assert rejection is None
        assert new.graph is not None
        assert new.graph.depth == 1

    def test_expand_never_exceeds_max(self):
        ctx = context("graph").model_copy(update={"graph": GraphConstraints(depth=10)})
        new, _, _ = apply_operation(ctx, "EXPAND")
        assert new.graph.depth == 10


class TestFilterAddRemove:
    def test_add_composes_fresh_and_node(self):
        base = context("graph", [{"field": "entity.type", "op": "eq", "value": "human"}])
        new, rejection, _ = apply_operation(
            base, "FILTER_ADD", filter_group=_group(_eq("geography.city", "NYC"))
        )
        assert rejection is None
        assert new.population.logic == "AND"
        assert len(new.population.expressions) == 2
        # The existing group is preserved structurally intact — never dropped.
        assert new.population.expressions[0] == base.population
        assert new.population.expressions[1].expressions[0].field == "geography.city"

    def test_add_to_empty_population(self):
        ctx = context("graph")
        new, _, _ = apply_operation(
            ctx, "FILTER_ADD", filter_group=_group(_eq("entity.type", "human"))
        )
        assert new.population.logic == "AND"
        assert len(new.population.expressions) == 1

    def test_add_requires_group(self):
        ctx = context("graph")
        new, rejection, _ = apply_operation(ctx, "FILTER_ADD")
        assert rejection == "filter_add_requires_group"
        assert new is ctx

    def test_remove_deep_removes_only_target_fields(self):
        ctx = context(
            "graph",
            [
                {"field": "entity.type", "op": "eq", "value": "human"},
                {"field": "geography.city", "op": "eq", "value": "NYC"},
            ],
        )
        new, rejection, _ = apply_operation(
            ctx, "FILTER_REMOVE", filter_group=_group(_eq("geography.city", "NYC"))
        )
        assert rejection is None
        fields = [e.field for e in iter_leaf_expressions(new.population)]
        assert fields == ["entity.type"]

    def test_remove_empties_to_none(self):
        ctx = context("graph", [{"field": "entity.type", "op": "eq", "value": "human"}])
        new, rejection, _ = apply_operation(
            ctx, "FILTER_REMOVE", filter_group=_group(_eq("entity.type", "human"))
        )
        assert rejection is None
        assert new.population is None  # honest: no filters → None, never empty group

    def test_remove_requires_fields(self):
        ctx = context("graph")
        new, rejection, _ = apply_operation(ctx, "FILTER_REMOVE")
        assert rejection == "filter_remove_requires_fields"
        assert new is ctx

    def test_remove_nested_group(self):
        inner = _group(_eq("a.b", "x"))
        outer = _group(_eq("entity.type", "human"), inner)
        ctx = context("graph").model_copy(update={"population": outer})
        new, _, _ = apply_operation(
            ctx, "FILTER_REMOVE", filter_group=_group(_eq("a.b", "x"))
        )
        fields = [e.field for e in iter_leaf_expressions(new.population)]
        assert fields == ["entity.type"]


class TestLensAdd:
    def test_accepts_valid_frame_and_defaults_temporal_mode(self):
        ctx = context("profile360")
        assert ctx.temporal_mode is None
        new, rejection, _ = apply_operation(ctx, "LENS_ADD", lens_ids=["standard", "fraud"])
        assert rejection is None
        assert new.lens_set == ["standard", "fraud"]
        assert new.temporal_mode == "live"

    def test_keeps_existing_temporal_mode(self):
        ctx = context("profile360").model_copy(update={"temporal_mode": "as_of"})
        new, _, _ = apply_operation(ctx, "LENS_ADD", lens_ids=["standard", "fraud"])
        assert new.temporal_mode == "as_of"

    def test_requires_ids(self):
        ctx = context("profile360")
        new, rejection, _ = apply_operation(ctx, "LENS_ADD", lens_ids=[])
        assert rejection == "lens_add_requires_ids"
        assert new is ctx

    def test_unknown_lens_rejected(self):
        ctx = context("profile360")
        new, rejection, _ = apply_operation(ctx, "LENS_ADD", lens_ids=["bogus_lens"])
        assert rejection == "unknown_lens_id:bogus_lens"
        assert new is ctx

    def test_base_lens_as_overlay_rejected(self):
        ctx = context("profile360")
        new, rejection, _ = apply_operation(
            ctx, "LENS_ADD", lens_ids=["standard", "standard"]
        )
        assert rejection == "self_base_lens:standard"
        assert new is ctx

    def test_base_mismatch_rejected_with_custom_registry(self):
        from shared.projection_engine.lens_registry import LensRegistry

        def _def(lid, kind, base_lens, default=False):
            return {
                "id": lid,
                "displayName": lid,
                "kind": kind,
                "baseLens": base_lens,
                "description": "test lens",
                "domain": "test",
                "applicableSubjectKinds": [],
                "temporalModes": [],
                "default": default,
            }

        reg = LensRegistry(
            {
                "standard": _def("standard", "base", None, default=True),
                "alpha": _def("alpha", "base", None),
                "beta": _def("beta", "overlay", "alpha"),
            }
        )
        ctx = context("profile360")
        new, rejection, _ = apply_operation(
            ctx, "LENS_ADD", lens_ids=["standard", "beta"], lens_registry=reg
        )
        assert rejection == "lens_base_mismatch:beta"
        assert new is ctx


class TestTimeTravel:
    def test_applies_temporal_and_engine_mode(self):
        ctx = context("graph")
        temporal = TemporalSelection(
            mode="as_of",
            field="observed_at",
            timezone="UTC",
            as_of="2026-01-01T00:00:00Z",
        )
        new, rejection, _ = apply_operation(
            ctx, "TIME_TRAVEL", temporal=temporal, temporal_mode="as_of"
        )
        assert rejection is None
        assert new.temporal == temporal
        assert new.temporal_mode == "as_of"

    def test_rejects_invalid_engine_mode(self):
        ctx = context("graph")
        temporal = TemporalSelection(mode="window", field="occurred_at", timezone="UTC")
        new, rejection, _ = apply_operation(
            ctx, "TIME_TRAVEL", temporal=temporal, temporal_mode="nonsense"
        )
        assert rejection == "invalid_temporal_mode:nonsense"
        assert new is ctx

    def test_requires_temporal(self):
        ctx = context("graph")
        new, rejection, _ = apply_operation(ctx, "TIME_TRAVEL")
        assert rejection == "time_travel_requires_temporal"
        assert new is ctx


class TestDrillDown:
    def test_sets_focus_and_narrows_depth(self):
        ctx = context("graph").model_copy(update={"graph": GraphConstraints(depth=5)})
        new, rejection, _ = apply_operation(
            ctx, "DRILL_DOWN", focus=ExplorationAnchor(kind="entity", id="e1")
        )
        assert rejection is None
        assert new.selection.focused.id == "e1"
        assert new.graph.depth == 1

    def test_invents_selection_when_absent(self):
        ctx = context("graph")
        new, rejection, _ = apply_operation(
            ctx, "DRILL_DOWN", focus=ExplorationAnchor(kind="entity", id="e1")
        )
        assert rejection is None
        assert new.selection is not None
        assert new.selection.focused.id == "e1"
        assert new.graph is None  # does not invent graph constraints when absent

    def test_requires_focus(self):
        ctx = context("graph")
        new, rejection, _ = apply_operation(ctx, "DRILL_DOWN")
        assert rejection == "drill_down_requires_focus"
        assert new is ctx


class TestResetOpen:
    def test_reset_restores_seed(self):
        seed = context("graph", [{"field": "entity.type", "op": "eq", "value": "human"}])
        ctx = seed.model_copy(
            update={"scope": seed.scope.model_copy(update={"surface": "map"})}
        )
        new, rejection, _ = apply_operation(ctx, "RESET", seed=seed)
        assert rejection is None
        assert new.scope.surface == "graph"
        assert new.population == seed.population

    def test_open_uses_seed(self):
        seed = context("graph")
        ctx = context("table")
        new, rejection, _ = apply_operation(ctx, "OPEN", seed=seed)
        assert rejection is None
        assert new is seed

    def test_open_without_seed_is_identity(self):
        ctx = context("graph")
        new, _, _ = apply_operation(ctx, "OPEN")
        assert new is ctx


class TestSessionOpsAndUnknown:
    def test_save_is_session_operation(self):
        ctx = context("graph")
        new, rejection, _ = apply_operation(ctx, "SAVE")
        assert rejection == "save_is_a_session_operation"
        assert new is ctx

    def test_load_is_session_operation(self):
        ctx = context("graph")
        new, rejection, _ = apply_operation(ctx, "LOAD")
        assert rejection == "save_is_a_session_operation"
        assert new is ctx

    def test_unknown_operation_rejected(self):
        ctx = context("graph")
        new, rejection, _ = apply_operation(ctx, "SHRED")
        assert rejection == "unknown_operation:SHRED"
        assert new is ctx
