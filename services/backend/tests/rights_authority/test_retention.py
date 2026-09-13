"""Rights Authority retention executor seam — expiry + fail-closed pending items.

A known window/expiry schedules a pending ``delete_at_expiry`` impact item; an
unknown retention signal NEVER implies retention and instead enqueues a pending
``retention_review`` item (fail closed). All timestamps are aware UTC.
"""
from __future__ import annotations

import types
from datetime import datetime, timedelta, timezone

import pytest

from repositories.repos import reset_in_memory_stores
from services.rights_authority import impact as impact_mod
from services.rights_authority import retention as retention_mod
from services.rights_authority.retention import (
    RETENTION_REVIEW_ACTION,
    RETENTION_SCHEDULED_DELETE_ACTION,
    RetentionWindow,
    evaluate_retention,
    parse_retention_window,
    schedule_retention,
)

_AWARE = timezone.utc
ANCHOR = datetime(2026, 1, 15, 12, 0, 0, tzinfo=_AWARE)
ANCHOR_ISO = "2026-01-15T12:00:00+00:00"


class _FakeImpactRepo:
    def __init__(self) -> None:
        self._store: dict[str, dict] = {}

    async def record(self, row: dict) -> dict:
        rid = row.get("impact_id") or row.get("decision_id") or row.get("id")
        assert rid, "record requires an id"
        self._store[rid] = dict(row)
        return dict(row)

    async def get(self, rid: str):
        return self._store.get(rid)

    async def list_for_tenant(self, tenant_id, limit=200, offset=0, extra=None):
        rows = [r for r in self._store.values() if r.get("tenant_id") == tenant_id]
        if extra:
            rows = [r for r in rows if all(r.get(k) == v for k, v in extra.items())]
        return rows[offset:offset + limit]

    async def list_pending(self, tenant_id=None, limit=200):
        rows = [r for r in self._store.values() if r.get("remediation_state") == "pending"]
        if tenant_id:
            rows = [r for r in rows if r.get("tenant_id") == tenant_id]
        return rows[:limit]


@pytest.fixture(autouse=True)
def _isolated(monkeypatch):
    reset_in_memory_stores()
    impact_repo = _FakeImpactRepo()
    repos = types.SimpleNamespace(
        rights_decision_repository=_FakeImpactRepo(),
        rights_lineage_repository=_FakeImpactRepo(),
        rights_impact_repository=impact_repo,
    )
    monkeypatch.setattr(impact_mod, "_pb1_repositories", lambda: repos)
    yield repos
    reset_in_memory_stores()


# ═══════════════════════════════════════════════════════════════════════════
# Window parsing
# ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("raw,years,months,days,hours", [
    ("90d", 0, 0, 90, 0),
    ("P90D", 0, 0, 90, 0),
    (90, 0, 0, 90, 0),
    ("P2W", 0, 0, 14, 0),
    ("P6M", 0, 6, 0, 0),
    ("P1Y", 1, 0, 0, 0),
    ("P1Y6M10D", 1, 6, 10, 0),
    ("PT24H", 0, 0, 0, 24),
])
def test_parse_retention_window_known_forms(raw, years, months, days, hours):
    window = parse_retention_window(raw)
    assert window is not None
    assert window == RetentionWindow(years=years, months=months, days=days, hours=hours)


@pytest.mark.parametrize("raw", [None, "", "bogus", "P0D", "0d", 0, -3, "PT", "90x", 1.5])
def test_parse_retention_window_rejects_unknown_or_zero(raw):
    assert parse_retention_window(raw) is None


def test_add_window_month_arithmetic_clamps_day():
    jan31 = datetime(2026, 1, 31, 0, 0, 0, tzinfo=_AWARE)
    result = retention_mod.add_retention_window(jan31, RetentionWindow(months=1))
    assert result.date().isoformat() == "2026-02-28"


# ═══════════════════════════════════════════════════════════════════════════
# Known window / explicit expiry → pending delete_at_expiry
# ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_schedule_retention_known_window_persists_pending_delete():
    resolution = await schedule_retention(
        tenant_id="t1",
        artifact_ref="artifact_a",
        retention_window="P90D",
        anchor=ANCHOR,
        component_type="raw_object",
    )
    expected = ANCHOR + timedelta(days=90)
    assert resolution.state == "known_window"
    assert resolution.expiry == expected.isoformat()
    assert resolution.action == RETENTION_SCHEDULED_DELETE_ACTION
    assert len(resolution.impact_items) == 1
    assert len(resolution.impact_ids) == 1
    item = resolution.impact_items[0]
    assert item.remediation_state == "pending"
    assert item.required_action == RETENTION_SCHEDULED_DELETE_ACTION
    assert item.component_type == "raw_object"
    # The deletion is durable + surfaced — nothing was executed.
    pending = await impact_mod.list_pending_impacts("t1")
    assert len(pending) == 1
    assert pending[0]["remediation_state"] == "pending"
    assert expected.isoformat() in pending[0]["reason"]


@pytest.mark.asyncio
async def test_evaluate_retention_explicit_expiry():
    expiry = datetime(2027, 1, 1, 0, 0, 0, tzinfo=_AWARE)
    resolution = evaluate_retention(
        tenant_id="t1",
        artifact_ref="artifact_a",
        expires_at=expiry,
        anchor=ANCHOR,
    )
    assert resolution.state == "explicit_expiry"
    assert resolution.expiry == expiry.isoformat()
    assert len(resolution.impact_items) == 1


@pytest.mark.asyncio
async def test_retention_decision_effective_as_of_is_anchor():
    decision = types.SimpleNamespace(
        decision_id="rdec_1", tenant_id="t1", retention="per_policy", effective_as_of=ANCHOR_ISO,
    )
    resolution = evaluate_retention(
        tenant_id="t1",
        artifact_ref="artifact_a",
        decision=decision,
        retention_window="P10D",
    )
    expected = ANCHOR + timedelta(days=10)
    assert resolution.state == "known_window"
    assert resolution.expiry == expected.isoformat()
    assert resolution.decision_ref == "rdec_1"


# ═══════════════════════════════════════════════════════════════════════════
# Unknown retention → pending review (never silent retention)
# ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_unknown_retention_fail_closed_pending_review():
    resolution = await schedule_retention(tenant_id="t1", artifact_ref="artifact_a")
    assert resolution.state == "unknown_retention"
    assert resolution.expiry is None
    assert resolution.action == RETENTION_REVIEW_ACTION
    assert len(resolution.impact_ids) == 1
    assert "never implies retention" in resolution.notes[0]
    pending = await impact_mod.list_pending_impacts("t1")
    assert len(pending) == 1
    assert pending[0]["remediation_state"] == "pending"
    assert "retention_review" in pending[0]["required_action"]


@pytest.mark.asyncio
async def test_unknown_window_label_fail_closed():
    # resolver-style per_policy/delete_by_policy hint without a real window.
    decision = types.SimpleNamespace(
        decision_id="rdec_1", tenant_id="t1", retention="per_policy",
        deletion="delete_by_policy",
    )
    resolution = evaluate_retention(tenant_id="t1", artifact_ref="artifact_a", decision=decision)
    assert resolution.state == "unknown_retention"
    assert len(resolution.impact_items) == 1
    assert resolution.impact_items[0].required_action == RETENTION_REVIEW_ACTION


@pytest.mark.asyncio
async def test_governed_label_without_window_does_not_imply_retention():
    decision = types.SimpleNamespace(
        decision_id="rdec_1", tenant_id="t1", retention="governed",
        deletion="recompute_or_delete",
    )
    resolution = evaluate_retention(tenant_id="t1", artifact_ref="artifact_a", decision=decision)
    assert resolution.state == "unknown_retention"
    assert len(resolution.impact_items) == 1


@pytest.mark.asyncio
async def test_unparseable_window_fail_closed():
    resolution = await schedule_retention(
        tenant_id="t1", artifact_ref="artifact_a", retention_window="not-a-window",
        anchor=ANCHOR,
    )
    assert resolution.state == "unknown_retention"
    assert resolution.expiry is None
    assert len(resolution.impact_ids) == 1


@pytest.mark.asyncio
async def test_unparseable_expires_at_fail_closed():
    resolution = evaluate_retention(
        tenant_id="t1", artifact_ref="artifact_a", expires_at="not-a-date", anchor=ANCHOR,
    )
    assert resolution.state == "unknown_retention"
    assert len(resolution.impact_items) == 1


# ═══════════════════════════════════════════════════════════════════════════
# Explicit preserve → nothing scheduled; delete-now → pending delete
# ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_preserve_decision_schedules_nothing():
    lifecycle = types.SimpleNamespace(decision_ref="lr_1", action="legal_hold")
    resolution = await schedule_retention(
        tenant_id="t1", artifact_ref="artifact_a", lifecycle=lifecycle,
    )
    assert resolution.state == "preserve"
    assert resolution.remediates is False
    assert resolution.impact_ids == []
    assert await impact_mod.list_pending_impacts("t1") == []


@pytest.mark.asyncio
async def test_delete_now_decision_persists_pending_delete():
    decision = types.SimpleNamespace(
        decision_id="rdec_1", tenant_id="t1", retention="", deletion="hard_delete",
    )
    resolution = await schedule_retention(
        tenant_id="t1", artifact_ref="artifact_a", decision=decision,
        component_type="raw_object",
    )
    assert resolution.state == "delete_immediate"
    assert resolution.action == "hard_delete"
    assert len(resolution.impact_ids) == 1
    pending = await impact_mod.list_pending_impacts("t1")
    assert len(pending) == 1
    assert pending[0]["required_action"] == "hard_delete"


# ═══════════════════════════════════════════════════════════════════════════
# Time-safety
# ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_expiry_is_aware_utc_even_when_anchor_omitted():
    resolution = await schedule_retention(
        tenant_id="t1", artifact_ref="artifact_a", retention_window="P90D",
    )
    assert resolution.expiry is not None
    parsed = datetime.fromisoformat(resolution.expiry.replace("Z", "+00:00"))
    assert parsed.tzinfo is not None
    assert parsed.tzinfo.utcoffset(parsed) is not None
