"""M3a unit tests — bounded, redacted mobile gateway projections (decision-log D12).

Covers the projection builders and ``MobileProjectionService`` in
``services/mobile/projections.py`` plus their routes on the existing mobile
gateway:

* composition — projections READ owning-service truth (stubbed profile / campaign
  / inbox / saved-views / noesis return their values through); nothing is
  re-calculated;
* redaction — amounts, emails, phones, and long digit runs collapse to
  ``[redacted]`` (via the reused D11 projection helper);
* bounding — lists and per-field lengths are truncated;
* snake_case wire fields only (decision-log D6);
* tenant scoping + the flag gate on the routes.

Owning services are injected as fakes — no real DB is touched.
"""
from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest

from shared.common.common import NotFoundError
from services.mobile import routes as mobile_routes
from services.mobile.projections import (
    BRIEFING_CONVERSATIONS_DEFAULT,
    BRIEFING_VIEWS_DEFAULT,
    ENTITY_NAME_MAX_CHARS,
    INBOX_DEFAULT_LIMIT,
    MobileProjectionService,
    project_alert,
    project_campaign_summary,
    project_conversation,
    project_profile_peek,
    project_profile_summary,
    project_view,
)

REDACTED = "[redacted]"


def _run(coro):
    return asyncio.run(coro)


def _async_value(value):
    """Build an async fn returning ``value`` and recording its kwargs."""
    async def _fn(**kwargs):
        _fn.calls.append(kwargs)
        return value

    _fn.calls = []
    return _fn


def _async_raise(exc):
    async def _fn(**kwargs):
        _fn.calls.append(kwargs)
        raise exc

    _fn.calls = []
    return _fn


class _Tenant:
    tenant_id = "tenant-a"
    user_id = "user-1"

    def require_permission(self, permission):
        return None


def _req():
    return SimpleNamespace(state=SimpleNamespace(tenant=_Tenant()))


@pytest.fixture(autouse=True)
def _enabled(monkeypatch):
    monkeypatch.setattr(mobile_routes, "_require_enabled", lambda: None)
    yield


# ── fixture data: owning-service truth (as returned by the real services) ─────

def _profile_summary():
    return {
        "canonical_entity_id": "ent-1",
        "entity": {
            "id": "ent-1",
            "type": "person",
            "displayLabel": "Alice alice@example.com",
            "parentEntityId": None,
            "known": True,
            "timestamps": {"createdAt": "2026-01-01T00:00:00Z", "updatedAt": None},
            "metadata": {"segment": "northwind"},
        },
        "counts": {
            "agents": 2,
            "wallets": 3,
            "transfers": 5,
            "delegations_granted": 0,
            "delegations_received": 1,
            "active_delegations_granted": 0,
            "active_delegations_received": 1,
            "journey_chains": 0,
            "agent_executions": 4,
        },
        "financials": {
            "inflow_total": 100.0,
            "outflow_total": 40.0,
            "net": 60.0,
            "inflow_usd": "100.00",
            "outflow_usd": "40.00",
            "net_usd": "60.00",
            "rollup_status": "single_currency",
        },
        "behavior": {
            "automation_ratio": 0.5,
            "decision_latency_ms": 12,
            "risk_score": 0.8,
            "anomaly_flags": ["large-transfer", "new-wallet"],
            "computed_at": "2026-01-01T00:00:00Z",
            "computed": True,
        },
    }


def _campaign_overview():
    return {
        "campaign_id": "c1",
        "campaign_name": "Q3 Launch $1,000,000.00",
        "status": "active",
        "channel": "paid_social",
        "period": {"start": "2026-07-01", "end": "2026-07-31", "tz": "UTC"},
        "spend_usd": 1000000.0,
        "impressions": 1000,
        "clicks": 100,
        "cpm": 50.0,
        "cpc": 1.5,
        "ctr": 0.1,
        "observed_count": 500,
        "resolved_count": 400,
        "engaged_count": 300,
        "converted_count": 50,
        "attributed_count": 45,
        "conversion_count": 10,
        "fractional_attributed_conversions": 10.5,
        "gross_attributed_revenue": 200000.0,
        "net_attributed_revenue": 150000.0,
        "roas": 0.2,
        "identity_resolution_rate": 0.8,
        "attribution_model": "last_touch",
        "attribution_run_id": None,
        "total_credit_weight": 10.5,
        "touchpoint_count": 20,
        "data_quality": {"reconciliation_status": "ok", "completeness_pct": None},
    }


def _inbox_rows():
    return [
        {
            "id": "a1",
            "tenant_id": "tenant-a",
            "category": "alert",
            "severity": "P0",
            "title": "Escalation $9,999.00 for bob@example.com",
            "body": "card 4111111111111111",
            "link": "/investigation/abc",
            "read": False,
            "count": 1,
            "created_at": "2026-08-01T00:00:00Z",
        },
        {
            "id": "a2",
            "tenant_id": "tenant-a",
            "category": "alert",
            "severity": "P1",
            "title": "Secondary alert",
            "body": "review now",
            "link": "/investigation/def",
            "read": False,
            "count": 2,
            "created_at": "2026-08-01T00:01:00Z",
        },
        {
            "id": "a3",
            "tenant_id": "tenant-a",
            "category": "digest",
            "severity": "info",
            "title": "Daily digest",
            "body": "summary",
            "link": None,
            "read": True,
            "count": 1,
            "created_at": "2026-08-01T00:02:00Z",
        },
    ]


# ── profile projection builder ────────────────────────────────────────────────

def test_profile_projection_composes_owning_counts_and_redacts_amounts_pii():
    proj = project_profile_summary(_profile_summary())

    # Owning-service truth passes through (composed, never recomputed).
    assert proj["entity_id"] == "ent-1"
    assert proj["counts"]["agents"] == 2
    assert proj["counts"]["wallets"] == 3
    assert proj["counts"]["transfers"] == 5
    assert proj["behavior"]["risk_score"] == 0.8
    assert proj["behavior"]["anomaly_flags"] == ["large-transfer", "new-wallet"]

    # PII / amounts are redacted.
    assert proj["entity"]["display_label"] == f"Alice {REDACTED}"
    assert proj["financials"]["inflow_usd"] == REDACTED
    assert proj["financials"]["outflow_usd"] == REDACTED
    assert proj["financials"]["net_usd"] == REDACTED
    joined = json.dumps(proj)
    assert "alice@example.com" not in joined
    assert "100.00" not in joined

    # Non-amount values survive (status vocabulary is not an amount).
    assert proj["financials"]["rollup_status"] == "single_currency"

    # snake_case wire fields only (D6): camelCase owning-service keys are re-keyed.
    assert proj["entity"]["display_label"] == f"Alice {REDACTED}"
    assert "displayLabel" not in joined
    assert "parentEntityId" not in joined


def test_profile_projection_preserves_absent_amounts():
    summary = _profile_summary()
    summary["financials"] = {
        "inflow_total": None,
        "outflow_total": None,
        "net": None,
        "inflow_usd": None,
        "outflow_usd": None,
        "net_usd": None,
        "rollup_status": "mixed_currency",
    }
    proj = project_profile_summary(summary)
    assert proj["financials"]["inflow_usd"] is None
    assert proj["financials"]["net_usd"] is None
    assert proj["financials"]["rollup_status"] == "mixed_currency"


def test_profile_projection_bounds_anomaly_flags():
    summary = _profile_summary()
    summary["behavior"]["anomaly_flags"] = [f"flag-{i}" for i in range(50)]
    proj = project_profile_summary(summary)
    assert len(proj["behavior"]["anomaly_flags"]) <= 10


def test_profile_peek_is_bounded_subset():
    peek = project_profile_peek(_profile_summary())
    assert set(peek["counts"]) == {
        "agents",
        "wallets",
        "active_delegations_received",
        "journey_chains",
    }
    assert "transfers" not in peek["counts"]
    assert peek["risk_score"] == 0.8
    assert peek["financials"]["inflow_usd"] == REDACTED


# ── campaign projection builder ───────────────────────────────────────────────

def test_campaign_projection_composes_overview_counts_and_redacts_amounts():
    proj = project_campaign_summary(_campaign_overview())

    assert proj["campaign_id"] == "c1"
    assert proj["status"] == "active"
    assert proj["counts"]["impressions"] == 1000
    assert proj["counts"]["converted_count"] == 50
    assert proj["counts"]["touchpoint_count"] == 20
    assert proj["ratios"]["ctr"] == 0.1
    assert proj["ratios"]["identity_resolution_rate"] == 0.8

    # Amount-denominated fields are redacted regardless of the regex surface.
    for key in ("spend_usd", "cpm", "cpc", "gross_attributed_revenue",
                "net_attributed_revenue", "roas"):
        assert proj["amounts"][key] == REDACTED

    # The campaign name carried an amount — redacted.
    assert proj["name"] == f"Q3 Launch {REDACTED}"
    joined = json.dumps(proj)
    assert "1,000,000.00" not in joined
    assert "200000.0" not in joined


def test_campaign_projection_truncates_long_name():
    overview = {"campaign_id": "c1", "campaign_name": "x" * 500}
    proj = project_campaign_summary(overview)
    assert len(proj["name"]) <= ENTITY_NAME_MAX_CHARS
    assert proj["name"].endswith("…")


def test_campaign_projection_wire_fields_are_snake_case():
    joined = json.dumps(project_campaign_summary(_campaign_overview()))
    assert "campaign_name" not in joined
    assert "spend_usd" in joined  # present as a redacted-amount key


# ── alerts / briefing builders ────────────────────────────────────────────────

def test_alert_projection_redacts_via_d11_builder():
    proj = project_alert(_inbox_rows()[0])
    assert proj["id"] == "a1"
    assert proj["severity"] == "P0"
    assert proj["category"] == "alert"
    assert proj["deep_link_class"] == "investigation"
    assert proj["read"] is False
    joined = json.dumps(proj)
    assert "9,999.00" not in joined
    assert "bob@example.com" not in joined
    assert "4111111111111111" not in joined
    assert REDACTED in proj["title"]


def test_conversation_projection_redacts_message():
    conv = {
        "conversation_id": "c1",
        "last_message": "Call bob@example.com about $1,000.00",
        "last_intent": "investigate",
        "last_ts": "2026-08-01T00:00:00Z",
    }
    proj = project_conversation(conv)
    assert proj["conversation_id"] == "c1"
    assert "bob@example.com" not in proj["last_message"]
    assert REDACTED in proj["last_message"]


def test_view_projection_is_bounded():
    proj = project_view({"view_id": "v1", "name": "Northwind 2026", "saved_at": "x"})
    assert proj["view_id"] == "v1"
    assert proj["name"] == "Northwind 2026"


# ── MobileProjectionService: composition over owning services ────────────────

def test_today_digest_composes_owning_truth_and_redacts():
    rows = _inbox_rows()
    profile_summary = _profile_summary()
    svc = MobileProjectionService(
        inbox_list=_async_value(rows),
        inbox_unread=_async_value(3),
        profile_aggregator=SimpleNamespace(summary=_async_value(profile_summary)),
    )
    digest = _run(svc.today_digest(tenant_id="tenant-a", profile_user_id="ent-1"))

    # Alert counts come from the owning inbox listing (composed, not recomputed).
    assert digest["unread_alert_count"] == 3
    assert digest["top_severity_alert_count"] == 2  # P0 + P1

    # Recent redacted titles.
    titles = " ".join(a["title"] for a in digest["recent_alerts"])
    assert len(digest["recent_alerts"]) == 3
    assert "bob@example.com" not in titles
    assert "9,999.00" not in titles
    assert REDACTED in titles

    # Profile peek is bounded + redacted.
    peek = digest["profile_peek"]
    assert peek["entity_id"] == "ent-1"
    assert peek["financials"]["inflow_usd"] == REDACTED
    assert "alice@example.com" not in json.dumps(peek)


def test_today_digest_omits_profile_peek_when_not_requested():
    svc = MobileProjectionService(
        inbox_list=_async_value(_inbox_rows()),
        inbox_unread=_async_value(3),
    )
    digest = _run(svc.today_digest(tenant_id="tenant-a"))
    assert digest["profile_peek"] is None


def test_profile_summary_passes_through_stubbed_truth():
    fake = _async_value(_profile_summary())
    svc = MobileProjectionService(profile_aggregator=SimpleNamespace(summary=fake))
    result = _run(svc.profile_summary(tenant_id="tenant-a", user_id="ent-1"))

    # A stubbed owning profile returns its values through — composition, not
    # recalculation of Profile360 truth.
    assert result["counts"]["wallets"] == 3
    assert result["counts"]["agent_executions"] == 4
    assert result["financials"]["net_usd"] == REDACTED
    assert fake.calls == [{"entity_id": "ent-1", "tenant_id": "tenant-a"}]


def test_campaign_summary_reuses_owned_campaign_truth():
    owned = {"campaign_id": "c1", "tenant_id": "tenant-a", "name": "Q3 Launch"}
    overview = _campaign_overview()
    fake_find = _async_value(owned)
    fake_overview = _async_value(overview)
    svc = MobileProjectionService(
        campaign_repo=SimpleNamespace(find_by_id=fake_find),
        campaign_explorer=SimpleNamespace(get_overview=fake_overview),
    )
    result = _run(svc.campaign_summary(tenant_id="tenant-a", campaign_id="c1"))

    # The explorer (owning service) produced the overview; we compose it.
    assert result["campaign_id"] == "c1"
    assert result["counts"]["converted_count"] == 50
    assert result["amounts"]["spend_usd"] == REDACTED
    assert fake_find.calls == [{"campaign_id": "c1"}]
    assert fake_overview.calls == [{
        "tenant_id": "tenant-a",
        "campaign_id": "c1",
        "campaign": owned,
    }]


def test_campaign_summary_404_for_unowned_or_missing_campaign():
    # Missing campaign.
    svc = MobileProjectionService(campaign_repo=SimpleNamespace(find_by_id=_async_value(None)))
    with pytest.raises(NotFoundError):
        _run(svc.campaign_summary(tenant_id="tenant-a", campaign_id="nope"))

    # Campaign owned by another tenant — no cross-tenant leak.
    other = {"campaign_id": "c9", "tenant_id": "tenant-b"}
    svc = MobileProjectionService(
        campaign_repo=SimpleNamespace(find_by_id=_async_value(other)),
        campaign_explorer=SimpleNamespace(get_overview=_async_value(_campaign_overview())),
    )
    with pytest.raises(NotFoundError):
        _run(svc.campaign_summary(tenant_id="tenant-a", campaign_id="c9"))


def test_alerts_inbox_forwarded_limit_and_redacts_rows():
    rows = _inbox_rows()
    fake_list = _async_value(rows)
    svc = MobileProjectionService(
        inbox_list=fake_list, inbox_unread=_async_value(1)
    )
    result = _run(svc.alerts_inbox(tenant_id="tenant-a", unread_only=True, limit=INBOX_DEFAULT_LIMIT))

    assert result["count"] == len(rows)
    assert result["unread_count"] == 1
    assert fake_list.calls == [
        {"tenant_id": "tenant-a", "unread_only": True, "limit": INBOX_DEFAULT_LIMIT, "offset": 0}
    ]
    joined = json.dumps(result["alerts"])
    assert "4111111111111111" not in joined
    assert "bob@example.com" not in joined


def test_briefing_composes_views_and_conversations():
    views = [{"view_id": "v1", "name": "Northwind 2026", "saved_at": "2026-08-01T00:00:00Z"}]
    conversations = [{
        "conversation_id": "c1",
        "last_message": "Call bob@example.com about $1,000.00",
        "last_intent": "investigate",
        "last_ts": "2026-08-01T00:00:00Z",
    }]
    fake_views = _async_value(views)
    fake_convs = _async_value(conversations)
    svc = MobileProjectionService(
        views_repo=SimpleNamespace(list_scoped=fake_views),
        noesis_store=SimpleNamespace(list_for_tenant=fake_convs),
        noesis_status=lambda degraded, items: "available" if items else ("empty" if not degraded else "missing"),
    )
    result = _run(svc.explore_briefing(tenant_id="tenant-a"))

    assert result["saved_views"][0]["name"] == "Northwind 2026"
    assert result["conversations"][0]["conversation_id"] == "c1"
    assert "bob@example.com" not in result["conversations"][0]["last_message"]
    assert REDACTED in result["conversations"][0]["last_message"]
    assert result["conversations_source_status"] == "available"
    assert fake_views.calls == [{
        "tenant_id": "tenant-a", "limit": BRIEFING_VIEWS_DEFAULT, "offset": 0
    }]
    assert fake_convs.calls == [{
        "tenant_id": "tenant-a", "limit": BRIEFING_CONVERSATIONS_DEFAULT
    }]


def test_briefing_degrades_conversations_with_honest_source_status():
    svc = MobileProjectionService(
        views_repo=SimpleNamespace(list_scoped=_async_value([])),
        noesis_store=SimpleNamespace(list_for_tenant=_async_raise(RuntimeError("cache down"))),
        noesis_status=lambda degraded, items: "missing" if degraded else "available",
    )
    result = _run(svc.explore_briefing(tenant_id="tenant-a"))
    assert result["conversations"] == []
    assert result["conversations_source_status"] == "missing"


# ── route wiring ──────────────────────────────────────────────────────────────

def test_projection_routes_are_flag_gated(monkeypatch):
    def _disabled():
        raise NotFoundError("mobile gateway (feature not enabled)")

    monkeypatch.setattr(mobile_routes, "_require_enabled", _disabled)
    for call in (
        mobile_routes.get_today_projection,
        mobile_routes.get_profile_projection,
        mobile_routes.get_campaign_projection,
        mobile_routes.get_alerts_projection,
        mobile_routes.get_explore_briefing,
    ):
        with pytest.raises(NotFoundError):
            _run(call(_req()))


def _fake_projection_service():
    return SimpleNamespace(
        today_digest=_async_value({
            "unread_alert_count": 3,
            "top_severity_alert_count": 2,
            "recent_alerts": [{"id": "a1", "title": f"Escalation {REDACTED}"}],
            "profile_peek": None,
        }),
        profile_summary=_async_value(project_profile_summary(_profile_summary())),
        campaign_summary=_async_value(project_campaign_summary(_campaign_overview())),
        alerts_inbox=_async_value({"alerts": [], "unread_count": 0, "count": 0}),
        explore_briefing=_async_value({"saved_views": [], "conversations": [],
                                       "conversations_source_status": "empty"}),
    )


def test_today_route_returns_redacted_digest(monkeypatch):
    fake = _fake_projection_service()
    monkeypatch.setattr(mobile_routes, "_projection_service", fake)
    resp = _run(mobile_routes.get_today_projection(_req(), profile_user_id="ent-1"))
    assert resp.data["unread_alert_count"] == 3
    assert resp.data["top_severity_alert_count"] == 2
    assert resp.data["recent_alerts"][0]["title"] == f"Escalation {REDACTED}"
    # tenant id flows from the authenticated context, not the client.
    assert fake.today_digest.calls == [{
        "tenant_id": "tenant-a", "profile_user_id": "ent-1"
    }]


def test_projection_routes_are_tenant_scoped(monkeypatch):
    fake = _fake_projection_service()
    monkeypatch.setattr(mobile_routes, "_projection_service", fake)

    _run(mobile_routes.get_profile_projection(_req(), user_id="ent-1"))
    _run(mobile_routes.get_campaign_projection(_req(), campaign_id="c1"))
    _run(mobile_routes.get_alerts_projection(_req(), unread=True, limit=10, offset=0))
    # Route handlers are invoked directly (no FastAPI DI), so query defaults must
    # be passed explicitly — the same convention test_mobile_config.py uses.
    _run(mobile_routes.get_explore_briefing(
        _req(),
        views_limit=BRIEFING_VIEWS_DEFAULT,
        conversations_limit=BRIEFING_CONVERSATIONS_DEFAULT,
    ))

    assert fake.profile_summary.calls == [{"tenant_id": "tenant-a", "user_id": "ent-1"}]
    assert fake.campaign_summary.calls == [{"tenant_id": "tenant-a", "campaign_id": "c1"}]
    assert fake.alerts_inbox.calls == [{
        "tenant_id": "tenant-a", "unread_only": True, "limit": 10, "offset": 0
    }]
    assert fake.explore_briefing.calls == [{
        "tenant_id": "tenant-a",
        "views_limit": BRIEFING_VIEWS_DEFAULT,
        "conversations_limit": BRIEFING_CONVERSATIONS_DEFAULT,
    }]


def test_profile_route_404_when_no_summary(monkeypatch):
    fake = SimpleNamespace(
        profile_summary=_async_value(None),
        today_digest=_async_value({}),
        campaign_summary=_async_value({}),
        alerts_inbox=_async_value({}),
        explore_briefing=_async_value({}),
    )
    monkeypatch.setattr(mobile_routes, "_projection_service", fake)
    with pytest.raises(NotFoundError):
        _run(mobile_routes.get_profile_projection(_req(), user_id="ent-1"))
