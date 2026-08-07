"""TS <-> Python parity for the mobile gateway projection contracts (M3a).

`packages/shared/mobile-projection.ts` is the TS twin of the Python-authoritative
mobile projection builders (`services/mobile/projections.py`). Every surface is
bounded/redacted on the backend; this test asserts the wire key sets stay in
lockstep so an app screen can never render against a key the backend does not
emit (M8 architecture-1 remediation).
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND = REPO_ROOT / "Backend Architecture" / "aether-backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from services.mobile.projections import (  # noqa: E402
    MobileProjectionService,
    project_alert,
    project_conversation,
    project_profile_peek,
    project_profile_summary,
    project_view,
)
from services.mobile.projections import (  # noqa: E402
    _project_profile_behavior,
    _project_profile_entity,
    _project_profile_financials,
)

TS_PATH = REPO_ROOT / "packages" / "shared" / "mobile-projection.ts"


def _interface_fields(interface: str) -> set[str]:
    text = TS_PATH.read_text(encoding="utf-8")
    m = re.search(rf"export interface {interface}(?:<[^>]+>)?\s*\{{(.*?)\n\}}", text, re.S)
    assert m, f"interface {interface} not found in mobile-projection.ts"
    return set(re.findall(r"^\s{2}([a-z_][a-z0-9_]*)\??:", m.group(1), re.M))


def _const_array(name: str) -> set[str]:
    text = TS_PATH.read_text(encoding="utf-8")
    m = re.search(rf"{name}[^\[]*\[(.*?)\]\s*as const", text, re.S)
    assert m, f"const array {name!r} not found in mobile-projection.ts"
    return set(re.findall(r"'([^']+)'", m.group(1)))


# ── minimal owning-service fakes (no DB) ─────────────────────────────────────

class _FakeProfile:
    async def summary(self, **kwargs):
        return {
            "snapshot": {
                "canonical_entity_id": "ent_1",
                "entity": {"id": "ent_1", "type": "wallet", "displayLabel": "Alice"},
                "counts": {"agents": 2, "wallets": 1},
                "financials": {"inflow_total": 1, "rollup_status": "ok"},
                "behavior": {"risk_score": 0.3, "anomaly_flags": ["flag"], "computed": True},
            }
        }


class _FakeRows:
    def __init__(self, rows):
        self._rows = rows

    async def __call__(self, **kwargs):
        return self._rows


class _FakeCount:
    def __init__(self, n):
        self._n = n

    async def __call__(self, **kwargs):
        return self._n


class _FakeSnapshot:
    """M8-B5: the projection service reads rows AND unread count from ONE
    single-snapshot call — the fakes must provide that, not separate calls."""

    def __init__(self, rows, unread=0):
        self._rows = rows
        self._unread = unread

    async def __call__(self, **kwargs):
        return {"rows": self._rows, "unread_count": self._unread}


class _FakeViews:
    def __init__(self, rows):
        self._rows = rows

    async def list_scoped(self, **kwargs):
        return self._rows


class _FakeConversations:
    def __init__(self, rows):
        self._rows = rows

    async def list_for_tenant(self, **kwargs):
        return self._rows


def _service(rows=None, views=None, conversations=None):
    return MobileProjectionService(
        profile_aggregator=_FakeProfile(),
        # M8-B5: single-snapshot injection (rows + unread count from one read).
        inbox_snapshot=_FakeSnapshot(rows or []),
        views_repo=_FakeViews(views or []),
        noesis_store=_FakeConversations(conversations or []),
        noesis_status=lambda degraded, items: "available",
    )


# ── surface parity ───────────────────────────────────────────────────────────

async def test_today_digest_parity():
    result = await _service().today_digest(tenant_id="t1")
    assert set(result.keys()) == _interface_fields("MobileTodayProjection")


async def test_recent_alert_parity():
    svc = _service(rows=[{"id": "a1", "title": "T", "category": "alert", "severity": "P1", "created_at": "now"}])
    result = await svc.today_digest(tenant_id="t1")
    assert len(result["recent_alerts"]) == 1
    assert set(result["recent_alerts"][0].keys()) == _interface_fields("MobileRecentAlert")


def test_profile_summary_parity():
    result = project_profile_summary({"snapshot": {}})
    assert set(result.keys()) == _interface_fields("MobileProfileSummary")


def test_profile_peek_parity():
    result = project_profile_peek({"snapshot": {}})
    assert set(result.keys()) == _interface_fields("MobileProfilePeek")


def test_profile_entity_parity():
    result = _project_profile_entity({"id": "e", "type": "w", "displayLabel": "x", "timestamps": {}})
    assert set(result.keys()) == _interface_fields("MobileProfileEntity")


def test_profile_financials_parity():
    result = _project_profile_financials({"inflow_total": 1})
    assert set(result.keys()) == _interface_fields("MobileProfileFinancials")


def test_profile_behavior_parity():
    result = _project_profile_behavior({"anomaly_flags": []})
    assert set(result.keys()) == _interface_fields("MobileProfileBehavior")


def test_alert_item_parity():
    result = project_alert({"id": "a1", "title": "t", "body": "b"})
    assert set(result.keys()) == _interface_fields("MobileAlertItem")


async def test_alerts_inbox_parity():
    result = await _service().alerts_inbox(tenant_id="t1")
    assert set(result.keys()) == _interface_fields("MobileAlertsProjection")


def test_saved_view_parity():
    result = project_view({"view_id": "v1", "name": "n", "saved_at": "now"})
    assert set(result.keys()) == _interface_fields("MobileSavedView")


def test_conversation_parity():
    result = project_conversation(
        {"conversation_id": "c1", "last_message": "m", "last_intent": "i", "last_ts": "now"}
    )
    assert set(result.keys()) == _interface_fields("MobileConversation")


async def test_explore_briefing_parity():
    result = await _service().explore_briefing(tenant_id="t1")
    assert set(result.keys()) == _interface_fields("MobileBriefingProjection")


def test_conversation_source_status_vocabulary():
    assert _const_array("conversationSourceStatuses") == {"missing", "empty", "available"}


def test_barrel_exports_projection():
    index = (REPO_ROOT / "packages" / "shared" / "index.ts").read_text(encoding="utf-8")
    assert "export * from './mobile-projection';" in index
