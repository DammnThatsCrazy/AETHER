"""Unit tests for the Profile 360 delegation engine."""

from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))

from services.delegation.engine import DelegationEngine


class _FakeRepo:
    def __init__(self, rows):
        self._rows = rows

    async def active_for(self, _grantee, _tenant_id):
        # Signature mirrors DelegationRepository.active_for(grantee_entity_id,
        # tenant_id): delegation lookups are tenant-scoped, and a fake accepting
        # fewer arguments than production would fail every caller.
        return self._rows


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def test_allows_within_scope():
    engine = DelegationEngine(_FakeRepo([{
        "delegation_id": "d1",
        "scope": {
            "actions": ["transfer"],
            "resources": ["wallet:*"],
            "max_amount": "100",
        },
    }]))
    decision = _run(engine.evaluate("agent", "transfer", "wallet:abc", "50"))
    assert decision.allowed
    assert decision.delegation_id == "d1"


def test_rejects_over_amount():
    engine = DelegationEngine(_FakeRepo([{
        "delegation_id": "d1",
        "scope": {"actions": ["transfer"], "resources": ["wallet:*"], "max_amount": "100"},
    }]))
    decision = _run(engine.evaluate("agent", "transfer", "wallet:abc", "500"))
    assert not decision.allowed
    assert decision.reason == "scope_mismatch"


def test_rejects_unknown_action():
    engine = DelegationEngine(_FakeRepo([{
        "delegation_id": "d1",
        "scope": {"actions": ["transfer"], "resources": ["wallet:*"]},
    }]))
    decision = _run(engine.evaluate("agent", "sell", "wallet:abc"))
    assert not decision.allowed


def test_wildcards():
    engine = DelegationEngine(_FakeRepo([{
        "delegation_id": "d2",
        "scope": {"actions": ["*"], "resources": ["*"]},
    }]))
    decision = _run(engine.evaluate("agent", "anything", "foo:bar"))
    assert decision.allowed


def test_no_delegations_means_deny():
    engine = DelegationEngine(_FakeRepo([]))
    decision = _run(engine.evaluate("agent", "transfer", "wallet:abc"))
    assert not decision.allowed
    assert decision.reason == "no_active_delegation"


def test_resource_glob():
    engine = DelegationEngine(_FakeRepo([{
        "delegation_id": "d3",
        "scope": {"actions": ["read"], "resources": ["wallet:0xabc:*"]},
    }]))
    ok = _run(engine.evaluate("agent", "read", "wallet:0xabc:balance"))
    miss = _run(engine.evaluate("agent", "read", "wallet:0xdef:balance"))
    assert ok.allowed and not miss.allowed


def test_amount_string_decimal_compare():
    engine = DelegationEngine(_FakeRepo([{
        "delegation_id": "d1",
        "scope": {"actions": ["transfer"], "resources": ["*"], "max_amount": "100.50"},
    }]))
    boundary = _run(engine.evaluate("agent", "transfer", "wallet:x", "100.50"))
    over = _run(engine.evaluate("agent", "transfer", "wallet:x", "100.51"))
    assert boundary.allowed and not over.allowed
