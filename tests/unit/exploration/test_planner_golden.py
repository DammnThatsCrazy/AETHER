"""Planner golden corpus — zero silent filter drops, ever.

The load-bearing invariant of the exploration fabric: for EVERY submitted
context, the number of leaf filters equals the number of applicability entries,
and every disposition is one of the registry's declared dispositions. A silent
drop is structurally impossible.
"""
from __future__ import annotations

import pytest

from exploration_fakes import context

from shared.exploration.generated_fields import FILTER_FIELDS
from shared.exploration.generated_surfaces import (
    EXPLORATION_SURFACE_IDS,
    SURFACE_CAPABILITIES,
)
from shared.exploration.models import FILTER_DISPOSITIONS
from services.exploration.planner import iter_leaf_expressions, plan_context


def _one_op(field_id: str) -> str:
    return FILTER_FIELDS[field_id]["operators"][0]


# ── Golden corpus ─────────────────────────────────────────────────────────────

def _corpus():
    cases = []

    # 1. No population at all → zero filters, zero entries.
    cases.append(("graph_no_filters", context("graph")))

    # 2. Empty flat group.
    cases.append(("graph_empty_group", context("graph", [])))

    # 3. Every registry field, one filter each, against the broad graph surface.
    all_fields_exprs = [
        {"field": fid, "op": _one_op(fid), "value": "x"} for fid in sorted(FILTER_FIELDS)
    ]
    cases.append(("graph_every_field", context("graph", all_fields_exprs)))

    # 4. Every surface with a filter from every category it should NOT support
    #    (forces not_applicable) mixed with one it does support.
    for surface in EXPLORATION_SURFACE_IDS:
        exprs = [
            {"field": fid, "op": _one_op(fid), "value": "x"}
            for fid in sorted(FILTER_FIELDS)
        ]
        cases.append((f"{surface}_all_fields", context(surface, exprs)))

    # 5. Unregistered field + bad operator + nested groups.
    nested = context(
        "graph",
        [
            {"field": "entity.id", "op": "eq", "value": "e1"},
            {"field": "does.not.exist", "op": "eq", "value": "x"},
            {"field": "entity.id", "op": "contains", "value": "z"},  # bad op
            {
                "logic": "OR",
                "expressions": [
                    {"field": "geography.city", "op": "eq", "value": "NYC"},
                    {"field": "risk.score", "op": "gt", "value": 0.5},
                    {
                        "logic": "NOT",
                        "expressions": [
                            {"field": "device.os", "op": "eq", "value": "ios"},
                        ],
                    },
                ],
            },
        ],
    )
    cases.append(("graph_nested_mixed", nested))

    # 6. Unregistered surface — still one entry per filter.
    cases.append(
        ("unknown_surface", context("not_a_surface", [
            {"field": "entity.id", "op": "eq", "value": "e1"},
        ]))
    )
    return cases


CORPUS = _corpus()


@pytest.mark.parametrize("name,ctx", CORPUS, ids=[c[0] for c in CORPUS])
def test_zero_silent_drops(name, ctx):
    plan = plan_context(ctx)
    leaves = list(iter_leaf_expressions(ctx.population))
    entries = plan.applicability.entries
    assert len(entries) == len(leaves), (
        f"{name}: {len(leaves)} filters submitted but {len(entries)} accounted for"
    )
    # Field identity preserved, one entry per submitted leaf, in order.
    assert [e.field for e in entries] == [x.field for x in leaves]
    for entry in entries:
        assert entry.disposition in FILTER_DISPOSITIONS


@pytest.mark.parametrize("name,ctx", CORPUS, ids=[c[0] for c in CORPUS])
def test_routed_filters_are_a_subset(name, ctx):
    plan = plan_context(ctx)
    routed = {id(f) for f in plan.applied_filters}
    leaves = list(iter_leaf_expressions(ctx.population))
    assert routed.issubset({id(f) for f in leaves})
    # Only applied/translated dispositions are routed.
    routed_fields = [f.field for f in plan.applied_filters]
    applied_entries = [
        e.field for e in plan.applicability.entries
        if e.disposition in ("applied", "translated")
    ]
    assert sorted(routed_fields) == sorted(applied_entries)


def test_disposition_semantics_on_graph():
    ctx = context("graph", [
        {"field": "entity.id", "op": "eq", "value": "e1"},       # applied
        {"field": "made.up", "op": "eq", "value": "x"},          # unsupported: field
        {"field": "entity.id", "op": "contains", "value": "z"},  # unsupported: operator
    ])
    plan = plan_context(ctx)
    by_reason = [(e.disposition, e.reason) for e in plan.applicability.entries]
    assert by_reason[0] == ("applied", None)
    assert by_reason[1] == ("unsupported", "field_not_registered")
    assert by_reason[2][0] == "unsupported"
    assert by_reason[2][1].startswith("operator_not_supported_for_field")


def test_category_not_supported_is_not_applicable():
    # temporal_observatory supports only entity/time/truth categories.
    caps = SURFACE_CAPABILITIES["temporal_observatory"]
    assert "device" not in caps["supported_field_categories"]
    ctx = context("temporal_observatory", [
        {"field": "device.os", "op": "eq", "value": "ios"},
    ])
    entry = plan_context(ctx).applicability.entries[0]
    assert entry.disposition == "not_applicable"
    assert entry.reason.startswith("category_not_supported_by_surface")


def test_unregistered_surface_marks_every_filter_not_applicable():
    ctx = context("not_a_surface", [
        {"field": "entity.id", "op": "eq", "value": "e1"},
        {"field": "risk.score", "op": "gt", "value": 0.5},
    ])
    plan = plan_context(ctx)
    assert plan.surface_registered is False
    assert [e.disposition for e in plan.applicability.entries] == [
        "not_applicable", "not_applicable",
    ]
    assert plan.applied_filters == []


def test_governance_redaction_suppresses():
    ctx = context("graph", [
        {"field": "risk.fraud_network_member", "op": "eq", "value": True},
    ])
    plan = plan_context(ctx, redacted_fields=frozenset({"risk.fraud_network_member"}))
    entry = plan.applicability.entries[0]
    assert entry.disposition == "suppressed"
    assert entry.reason == "field_redacted_by_governance"
    assert plan.applied_filters == []
