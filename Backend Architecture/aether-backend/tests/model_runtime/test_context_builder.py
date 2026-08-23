"""Context-builder tests for ADR-008 D6 grounded synthesis (Commit 8, Agent B).

Exercises ``ContextBuilder.build`` ordering and semantics against the landed
evidence models (Agent A): tenant scope rejection (fail-closed), freshness
bound, deduplication by ``reference_id`` (first occurrence wins), item/content
bounds (``EvidenceBounds``), future-dated retention, and the default budget.

All timestamps use aware UTC datetimes via ``datetime.now(timezone.utc)`` plus
``timedelta`` so the builder's subtraction is deterministic. Plain asserts with
a tiny ``_raises`` helper — no pytest fixtures required.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from services.model_runtime.context.builder import (
    ContextBuilder,
    ContextScopeViolation,
    RetrievalItem,
)
from services.model_runtime.context.evidence import (
    EvidenceBounds,
    EvidenceBudget,
)


def _raises(exc_type, fn) -> None:
    """Assert that ``fn()`` raises ``exc_type`` (plain-assert style)."""
    try:
        fn()
    except exc_type:
        return
    raise AssertionError(f"expected {exc_type.__name__} to be raised")


def _item(
    reference_id: str,
    *,
    tenant_id: str = "tenant-a",
    content: str = "grounding evidence",
    age_seconds: int = 0,
    now: datetime | None = None,
) -> RetrievalItem:
    """Build a fresh retrieval item with an optional age relative to ``now``."""
    base = now if now is not None else datetime.now(timezone.utc)
    return RetrievalItem(
        reference_id=reference_id,
        source="aether.records.transactions",
        tenant_id=tenant_id,
        content=content,
        collected_at=base - timedelta(seconds=age_seconds),
    )


def test_happy_path_assembles_tenant_scoped_bundle() -> None:
    now = datetime.now(timezone.utc)
    items = [
        _item("r-1", now=now),
        _item("r-2", content="second grounding evidence", now=now),
    ]
    bundle = ContextBuilder().build(
        tenant_id="tenant-a",
        profile_id="profile-1",
        query="What is the running balance?",
        items=items,
        now=now,
    )
    assert bundle.tenant_id == "tenant-a"
    assert bundle.profile_id == "profile-1"
    assert bundle.query == "What is the running balance?"
    assert bundle.created_at == now
    assert [i.reference_id for i in bundle.evidence.items] == ["r-1", "r-2"]
    for item in bundle.evidence.items:
        assert item.tenant_id == "tenant-a"


def test_foreign_tenant_item_raises_scope_violation() -> None:
    now = datetime.now(timezone.utc)
    items = [_item("r-1", now=now), _item("r-foreign", tenant_id="tenant-b", now=now)]
    _raises(
        ContextScopeViolation,
        lambda: ContextBuilder().build(
            tenant_id="tenant-a",
            profile_id="profile-1",
            query="scope check",
            items=items,
            now=now,
        ),
    )


def test_stale_item_dropped_by_freshness_bound() -> None:
    now = datetime.now(timezone.utc)
    budget = EvidenceBudget(freshness_seconds=60)
    items = [
        _item("r-now", now=now),
        _item("r-30s", age_seconds=30, now=now),
        _item("r-120s", age_seconds=120, now=now),
    ]
    bundle = ContextBuilder(budget=budget).build(
        tenant_id="tenant-a",
        profile_id="profile-1",
        query="freshness bound",
        items=items,
        now=now,
    )
    # 120s is stale (>60s) and dropped; 0s and 30s are kept.
    assert [i.reference_id for i in bundle.evidence.items] == ["r-now", "r-30s"]


def test_dedup_keeps_first_reference_id() -> None:
    now = datetime.now(timezone.utc)
    items = [
        _item("dup-1", content="first content", now=now),
        _item("dup-1", content="second content", now=now),
        _item("r-2", content="third content", now=now),
    ]
    bundle = ContextBuilder().build(
        tenant_id="tenant-a",
        profile_id="profile-1",
        query="dedupe check",
        items=items,
        now=now,
    )
    assert [i.reference_id for i in bundle.evidence.items] == ["dup-1", "r-2"]
    assert bundle.evidence.items[0].content == "first content"


def test_item_count_over_budget_raises_evidence_bounds() -> None:
    now = datetime.now(timezone.utc)
    items = [
        _item(f"r-{i}", now=now, content=f"grounding evidence item {i}")
        for i in range(65)
    ]
    _raises(
        EvidenceBounds,
        lambda: ContextBuilder().build(
            tenant_id="tenant-a",
            profile_id="profile-1",
            query="count bound",
            items=items,
            now=now,
        ),
    )


def test_content_over_budget_raises_evidence_bounds() -> None:
    now = datetime.now(timezone.utc)
    long_content = "x" * 4097  # exceeds default max_content_chars=4096
    items = [_item("r-long", content=long_content, now=now)]
    _raises(
        EvidenceBounds,
        lambda: ContextBuilder().build(
            tenant_id="tenant-a",
            profile_id="profile-1",
            query="content bound",
            items=items,
            now=now,
        ),
    )


def test_future_dated_item_is_kept() -> None:
    now = datetime.now(timezone.utc)
    future = now + timedelta(seconds=3600)
    items = [RetrievalItem(
        reference_id="r-future",
        source="aether.records.transactions",
        tenant_id="tenant-a",
        content="future-dated evidence",
        collected_at=future,
    )]
    bundle = ContextBuilder().build(
        tenant_id="tenant-a",
        profile_id="profile-1",
        query="future dated",
        items=items,
        now=now,
    )
    assert [i.reference_id for i in bundle.evidence.items] == ["r-future"]


def test_default_budget_applies() -> None:
    now = datetime.now(timezone.utc)
    items = [_item("r-1", now=now), _item("r-2", content="more evidence", now=now)]
    bundle = ContextBuilder().build(
        tenant_id="tenant-a",
        profile_id="profile-1",
        query="default budget",
        items=items,
        now=now,
    )
    # No budget supplied → EvidenceBudget() defaults are used; fresh items pass.
    assert len(bundle.evidence.items) == 2
    assert bundle.evidence.items[0].reference_id == "r-1"
    assert bundle.evidence.items[1].reference_id == "r-2"
