"""Tests for identity split policy."""
from __future__ import annotations

import pytest

from services.identity.split_policy import SplitPolicyContext, evaluate_split


def _ctx(**kwargs) -> SplitPolicyContext:
    defaults = dict(
        tenant_id="tenant_a",
        original_entity_id="entity_1",
        actor_type="operator",
        actor_id="op_001",
        reason="incorrect_merge",
        source_merge_event_id=None,
    )
    defaults.update(kwargs)
    return SplitPolicyContext(**defaults)


def test_operator_can_split():
    result = evaluate_split(_ctx())
    assert result.allowed is True


def test_admin_can_split():
    result = evaluate_split(_ctx(actor_type="admin"))
    assert result.allowed is True


def test_system_cannot_split():
    result = evaluate_split(_ctx(actor_type="system"))
    assert result.allowed is False
    assert result.error is not None


def test_missing_entity_id_not_allowed():
    result = evaluate_split(_ctx(original_entity_id=""))
    assert result.allowed is False


def test_missing_reason_not_allowed():
    result = evaluate_split(_ctx(reason=""))
    assert result.allowed is False


def test_split_has_reason_codes():
    result = evaluate_split(_ctx())
    assert isinstance(result.reason_codes, list)


def test_failed_split_has_error():
    result = evaluate_split(_ctx(actor_type="system"))
    assert result.error is not None
    assert len(result.error) > 0
