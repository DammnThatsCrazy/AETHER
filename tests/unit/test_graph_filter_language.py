"""Unit tests for the Phase 4 boolean filter language.

Covers FilterExpression evaluation, AND/OR/NOT FilterGroup logic,
budget truncation, cursor pagination, and operator validation.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest


def _add_backend() -> None:
    backend = str(Path(__file__).parents[2] / "Backend Architecture" / "aether-backend")
    if backend not in sys.path:
        sys.path.insert(0, backend)


_add_backend()

from services.operational_intelligence.models import (
    FilterExpression,
    FilterGroup,
    FilterOperator,
)
from services.operational_intelligence.routes import (
    _apply_boolean_filter,
    _cursor_decode,
    _cursor_encode,
    _evaluate_expression,
    _evaluate_filter_group,
)
from shared.graph.graph import Vertex


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _vertex(vertex_id: str, vertex_type: str = "Entity", **props) -> Vertex:
    return Vertex(
        vertex_type=vertex_type,
        vertex_id=vertex_id,
        properties={"tenantId": "t1", **props},
    )


# ── FilterExpression tests ─────────────────────────────────────────────────────

def test_eq_matches():
    v = _vertex("v1", label="alice")
    expr = FilterExpression(field="label", op=FilterOperator.EQ, value="alice")
    assert _evaluate_expression(expr, v)


def test_eq_no_match():
    v = _vertex("v1", label="bob")
    expr = FilterExpression(field="label", op=FilterOperator.EQ, value="alice")
    assert not _evaluate_expression(expr, v)


def test_neq_matches():
    v = _vertex("v1", label="bob")
    expr = FilterExpression(field="label", op=FilterOperator.NEQ, value="alice")
    assert _evaluate_expression(expr, v)


def test_gt_matches():
    v = _vertex("v1", risk_score="0.9")
    expr = FilterExpression(field="risk_score", op=FilterOperator.GT, value=0.5)
    assert _evaluate_expression(expr, v)


def test_gte_boundary():
    v = _vertex("v1", risk_score="0.5")
    expr = FilterExpression(field="risk_score", op=FilterOperator.GTE, value=0.5)
    assert _evaluate_expression(expr, v)


def test_lt_matches():
    v = _vertex("v1", score="0.2")
    expr = FilterExpression(field="score", op=FilterOperator.LT, value=0.5)
    assert _evaluate_expression(expr, v)


def test_lte_boundary():
    v = _vertex("v1", score="0.5")
    expr = FilterExpression(field="score", op=FilterOperator.LTE, value=0.5)
    assert _evaluate_expression(expr, v)


def test_in_operator():
    v = _vertex("v1", status="active")
    expr = FilterExpression(field="status", op=FilterOperator.IN, value=["active", "growing"])
    assert _evaluate_expression(expr, v)


def test_not_in_operator():
    v = _vertex("v1", status="dormant")
    expr = FilterExpression(field="status", op=FilterOperator.NOT_IN, value=["active", "growing"])
    assert _evaluate_expression(expr, v)


def test_exists_when_present():
    v = _vertex("v1", risk_score="0.7")
    expr = FilterExpression(field="risk_score", op=FilterOperator.EXISTS, value=None)
    assert _evaluate_expression(expr, v)


def test_not_exists_when_absent():
    v = _vertex("v1")
    expr = FilterExpression(field="risk_score", op=FilterOperator.NOT_EXISTS, value=None)
    assert _evaluate_expression(expr, v)


def test_exists_when_absent_returns_false():
    v = _vertex("v1")
    expr = FilterExpression(field="missing_field", op=FilterOperator.EXISTS, value=None)
    assert not _evaluate_expression(expr, v)


def test_contains_operator():
    v = _vertex("v1", label="alice_wonderland")
    expr = FilterExpression(field="label", op=FilterOperator.CONTAINS, value="alice")
    assert _evaluate_expression(expr, v)


def test_starts_with_operator():
    v = _vertex("v1", label="alice")
    expr = FilterExpression(field="label", op=FilterOperator.STARTS_WITH, value="ali")
    assert _evaluate_expression(expr, v)


def test_between_operator():
    v = _vertex("v1", score="0.6")
    expr = FilterExpression(field="score", op=FilterOperator.BETWEEN, value={"from": 0.5, "to": 0.8})
    assert _evaluate_expression(expr, v)


def test_between_excludes_outside_range():
    v = _vertex("v1", score="0.9")
    expr = FilterExpression(field="score", op=FilterOperator.BETWEEN, value={"from": 0.5, "to": 0.8})
    assert not _evaluate_expression(expr, v)


def test_threshold_operator():
    v = _vertex("v1", risk_score="0.75")
    expr = FilterExpression(field="risk_score", op=FilterOperator.THRESHOLD, value=0.5)
    assert _evaluate_expression(expr, v)


def test_null_value_fails_comparison():
    v = _vertex("v1")
    expr = FilterExpression(field="nonexistent", op=FilterOperator.GT, value=0.5)
    assert not _evaluate_expression(expr, v)


def test_node_type_field():
    v = _vertex("v1")  # default vertex_type="Entity"
    expr = FilterExpression(field="node_type", op=FilterOperator.EQ, value="Entity")
    assert _evaluate_expression(expr, v)


def test_type_error_returns_false():
    v = _vertex("v1", score="not_a_number")
    expr = FilterExpression(field="score", op=FilterOperator.GT, value=0.5)
    assert not _evaluate_expression(expr, v)


# ── FilterGroup tests ─────────────────────────────────────────────────────────

def test_and_group_all_true():
    v = _vertex("v1", status="active", score="0.8")
    fg = FilterGroup(
        logic="AND",
        expressions=[
            FilterExpression(field="status", op=FilterOperator.EQ, value="active"),
            FilterExpression(field="score", op=FilterOperator.GTE, value=0.5),
        ],
    )
    assert _evaluate_filter_group(fg, v)


def test_and_group_one_false():
    v = _vertex("v1", status="active", score="0.3")
    fg = FilterGroup(
        logic="AND",
        expressions=[
            FilterExpression(field="status", op=FilterOperator.EQ, value="active"),
            FilterExpression(field="score", op=FilterOperator.GTE, value=0.5),
        ],
    )
    assert not _evaluate_filter_group(fg, v)


def test_or_group_one_true():
    v = _vertex("v1", status="dormant")
    fg = FilterGroup(
        logic="OR",
        expressions=[
            FilterExpression(field="status", op=FilterOperator.EQ, value="active"),
            FilterExpression(field="status", op=FilterOperator.EQ, value="dormant"),
        ],
    )
    assert _evaluate_filter_group(fg, v)


def test_or_group_all_false():
    v = _vertex("v1", status="unknown")
    fg = FilterGroup(
        logic="OR",
        expressions=[
            FilterExpression(field="status", op=FilterOperator.EQ, value="active"),
            FilterExpression(field="status", op=FilterOperator.EQ, value="dormant"),
        ],
    )
    assert not _evaluate_filter_group(fg, v)


def test_not_group_inverts():
    v = _vertex("v1", status="active")
    fg = FilterGroup(
        logic="NOT",
        expressions=[
            FilterExpression(field="status", op=FilterOperator.EQ, value="active"),
        ],
    )
    assert not _evaluate_filter_group(fg, v)


def test_not_group_allows_non_matching():
    v = _vertex("v1", status="dormant")
    fg = FilterGroup(
        logic="NOT",
        expressions=[
            FilterExpression(field="status", op=FilterOperator.EQ, value="active"),
        ],
    )
    assert _evaluate_filter_group(fg, v)


def test_nested_and_or_group():
    v = _vertex("v1", status="active", risk="high", score="0.9")
    fg = FilterGroup(
        logic="AND",
        expressions=[
            FilterExpression(field="status", op=FilterOperator.EQ, value="active"),
            FilterGroup(
                logic="OR",
                expressions=[
                    FilterExpression(field="risk", op=FilterOperator.EQ, value="critical"),
                    FilterExpression(field="score", op=FilterOperator.GTE, value=0.8),
                ],
            ),
        ],
    )
    assert _evaluate_filter_group(fg, v)


def test_empty_and_group_returns_true():
    v = _vertex("v1")
    fg = FilterGroup(logic="AND", expressions=[])
    assert _evaluate_filter_group(fg, v)


def test_empty_or_group_returns_false():
    v = _vertex("v1")
    fg = FilterGroup(logic="OR", expressions=[])
    assert not _evaluate_filter_group(fg, v)


# ── _apply_boolean_filter ─────────────────────────────────────────────────────

def test_apply_filter_removes_non_matching_nodes():
    v1 = _vertex("v1", status="active")
    v2 = _vertex("v2", status="dormant")
    fg = FilterGroup(
        logic="AND",
        expressions=[FilterExpression(field="status", op=FilterOperator.EQ, value="active")],
    )
    nodes, edges = _apply_boolean_filter([v1, v2], [], fg)
    assert len(nodes) == 1
    assert nodes[0].vertex_id == "v1"


# ── Cursor pagination ─────────────────────────────────────────────────────────

def test_cursor_encode_decode_roundtrip():
    for offset in [0, 50, 100, 499]:
        cursor = _cursor_encode(offset)
        assert _cursor_decode(cursor) == offset, f"roundtrip failed for offset {offset}"


def test_invalid_cursor_returns_zero():
    assert _cursor_decode("not_valid_base64!!!") == 0


# ── FilterOperator valid values ────────────────────────────────────────────────

def test_all_operators_are_known():
    expected = {
        "eq", "neq", "gt", "gte", "lt", "lte",
        "in", "not_in", "exists", "not_exists",
        "contains", "starts_with", "between", "relative_time", "threshold",
    }
    assert FilterOperator.valid_values() == expected


def test_unknown_operator_rejected_by_pydantic():
    """Pydantic should reject an unknown op value."""
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        FilterExpression(field="x", op="unknown_op", value=None)  # type: ignore[arg-type]
