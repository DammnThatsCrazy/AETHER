"""M4 legacy social honesty tests (Social360 + Relationship Fidelity).

These tests pin the M4 honesty migration outcome for the legacy social surface:

* ``services/social/routes.py`` is a *compatibility wrapper* that delegates to the
  canonical Profile360 ``IntelligenceAggregator.social_intelligence`` and returns
  the aggregator envelope verbatim inside the standard ``APIResponse`` shape. It
  synthesizes NO metrics of its own.
* The fabricated legacy summary fields (``total_followers_deduped``,
  ``influence_level``, ``engagement_rate``, ``platforms_connected``) are gone.
* An empty / evidence-free result is an empty items list + an unpopulated summary
  — never ``followers = 0``, ``influence_level = "low"`` or ``engagement_rate =
  0.0`` for unknown data.
* The dead ``services/social/social_aggregator.py`` (fixed cross-platform overlap
  percentages + missing-data-as-zero fetchers) and the dead
  ``Data Lake Architecture/schemas/gold_social_intelligence.py`` ClickHouse DDL
  are removed and must not be importable / present.
"""

from __future__ import annotations

import asyncio
import importlib.util
import os
import sys
import types
from pathlib import Path

# ── path setup (mirrors tests/profile360/test_intelligence_endpoints.py) ──────
_BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
_REPO_ROOT = os.path.abspath(os.path.join(_BACKEND_ROOT, "..", ".."))
for _p in (_BACKEND_ROOT, _REPO_ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import pytest
from fastapi import HTTPException

from services.social.routes import get_social_intelligence

_TS = "2026-09-04T00:00:00+00:00"

_LEGACY_FABRICATED_SUMMARY_KEYS = {
    "total_followers_deduped",
    "influence_level",
    "engagement_rate",
    "platforms_connected",
}


def _run(coro):
    return asyncio.run(coro)


# ── doubles ──────────────────────────────────────────────────────────────


class _Tenant:
    """Minimal tenant double exposing the surface routes.py touches."""

    def __init__(self, tenant_id: str = "t-a", grants: tuple[str, ...] = ("read",)) -> None:
        self.tenant_id = tenant_id
        self._grants = set(grants)

    def require_permission(self, permission: str) -> None:
        if permission not in self._grants:
            raise PermissionError(f"missing required permission: {permission}")


def _request(tenant: _Tenant) -> types.SimpleNamespace:
    return types.SimpleNamespace(state=types.SimpleNamespace(tenant=tenant))


class _FakeAggregator:
    """Records the delegation and returns the caller-supplied canonical envelope."""

    def __init__(self, envelope: dict) -> None:
        self._envelope = envelope
        self.calls: list[tuple[str, str, str]] = []

    async def social_intelligence(self, entity_id: str, tenant_id: str, window: str = "30d") -> dict:
        self.calls.append((entity_id, tenant_id, window))
        return self._envelope


def _canonical_envelope(items: list | None = None) -> dict:
    items = list(items or [])
    return {
        "entity_id": "u-1",
        "tenant_id": "t-a",
        "kind": "social_intelligence",
        "window": "30d",
        "items": items,
        "summary": {
            "platform_count": len(items),
            "platforms": [i.get("platform") for i in items if i.get("platform")],
        },
        "computed_at": _TS,
        "provenance": {"sources": ["gold_social_intelligence"]},
    }


def _assert_no_legacy_fabricated_summary(payload: dict) -> None:
    summary = payload.get("summary") or {}
    leaked = _LEGACY_FABRICATED_SUMMARY_KEYS.intersection(summary.keys())
    assert not leaked, f"legacy fabricated summary keys still present: {sorted(leaked)}"


# ── wrapper behavior ─────────────────────────────────────────────────────


class TestWrapperDelegatesVerbatim:
    def test_returns_aggregator_envelope_verbatim(self):
        envelope = _canonical_envelope(items=[
            {
                "platform": "twitter",
                "handle": "@alice",
                "followers": 1000,
                "following": None,
                "post_count": 12,
                "engagement_rate": 0.04,
                "verified": True,
                "computed_at": _TS,
            },
        ])
        agg = _FakeAggregator(envelope)
        out = _run(get_social_intelligence("u-1", _request(_Tenant()), window="30d", intel=agg))

        assert out["status"] == "success"
        assert "timestamp" in out
        payload = out["data"]
        # Verbatim delegation: the wrapper injects NO extra or fabricated fields.
        assert payload == envelope
        assert agg.calls == [("u-1", "t-a", "30d")]
        _assert_no_legacy_fabricated_summary(payload)

    def test_evidence_backed_metrics_are_preserved(self):
        envelope = _canonical_envelope(items=[
            {
                "platform": "twitter",
                "handle": "@alice",
                "followers": 1_250_000,
                "following": 320,
                "post_count": 4210,
                "engagement_rate": 0.021,
                "verified": True,
                "computed_at": _TS,
            },
            {
                "platform": "farcaster",
                "handle": "alice.eth",
                "followers": 8500,
                "following": 1200,
                "post_count": None,
                "engagement_rate": None,
                "verified": None,
                "computed_at": _TS,
            },
        ])
        agg = _FakeAggregator(envelope)
        payload = _run(get_social_intelligence("u-1", _request(_Tenant()), window="30d", intel=agg))["data"]
        assert payload["summary"] == {
            "platform_count": 2,
            "platforms": ["twitter", "farcaster"],
        }
        _assert_no_legacy_fabricated_summary(payload)

    def test_null_metrics_are_never_coerced_to_zero(self):
        # A gold row observed a platform but no follower/engagement numbers:
        # the wrapper must pass the null through untouched — never coerce to 0.
        item = {
            "platform": "lens",
            "handle": None,
            "followers": None,
            "following": None,
            "post_count": None,
            "engagement_rate": None,
            "verified": None,
            "computed_at": _TS,
        }
        envelope = _canonical_envelope(items=[dict(item)])
        agg = _FakeAggregator(envelope)
        payload = _run(get_social_intelligence("u-1", _request(_Tenant()), window="30d", intel=agg))["data"]
        returned = payload["items"][0]
        assert returned["followers"] is None
        assert returned["engagement_rate"] is None
        assert returned == item  # bit-for-bit identical — no zero-coercion path

    def test_empty_result_is_evidence_free_not_zero_low(self):
        # No observed social facts: empty items, unpopulated summary, and NO
        # fabricated followers/influence/engagement claims anywhere.
        agg = _FakeAggregator(_canonical_envelope())
        payload = _run(get_social_intelligence("u-1", _request(_Tenant()), window="30d", intel=agg))["data"]
        assert payload["items"] == []
        assert payload["summary"] == {"platform_count": 0, "platforms": []}
        assert payload["computed_at"] == _TS
        _assert_no_legacy_fabricated_summary(payload)


class TestWrapperGuardRails:
    def test_invalid_window_raises_400_without_calling_aggregator(self):
        agg = _FakeAggregator(_canonical_envelope())
        with pytest.raises(HTTPException) as excinfo:
            _run(get_social_intelligence("u-1", _request(_Tenant()), window="bogus", intel=agg))
        assert excinfo.value.status_code == 400
        assert agg.calls == []  # rejected before delegation

    def test_valid_windows_pass_through(self):
        for window in ("30d", "60d", "90d", "lifetime"):
            agg = _FakeAggregator(_canonical_envelope())
            _run(get_social_intelligence("u-1", _request(_Tenant()), window=window, intel=agg))
            assert agg.calls == [("u-1", "t-a", window)]

    def test_read_permission_is_required(self):
        tenant = _Tenant(grants=())  # no permissions granted
        agg = _FakeAggregator(_canonical_envelope())
        with pytest.raises(PermissionError):
            _run(get_social_intelligence("u-1", _request(tenant), intel=agg))
        assert agg.calls == []  # denied before delegation


# ── dead-code removal guards ─────────────────────────────────────────────


class TestDeadCodeRemoved:
    def test_social_aggregator_module_is_gone(self):
        spec = importlib.util.find_spec("services.social.social_aggregator")
        assert spec is None, "dead social_aggregator module must not be importable"

    def test_social_aggregator_symbol_not_reexported(self):
        with pytest.raises(ImportError):
            from services.social import SocialAggregator  # noqa: F401

    def test_fixed_overlap_constants_absent_from_social_package(self):
        # The dead module was the sole carrier of the fabricated cross-platform
        # overlap percentages. Guard against reintroduction in the surviving
        # services/social package sources.
        social_dir = Path(_BACKEND_ROOT) / "services" / "social"
        forbidden = ("0.20", "0.15", "0.25", "x*0.85", "x * 0.85")
        found: list[str] = []
        for py in sorted(social_dir.glob("*.py")):
            text = py.read_text(encoding="utf-8")
            for token in forbidden:
                if token in text:
                    found.append(f"{py.name}: {token}")
        assert not found, f"fixed-overlap dishonesty reintroduced: {found}"

    def test_dead_gold_social_intelligence_ddl_is_gone(self):
        ddl = Path(_REPO_ROOT) / "Data Lake Architecture" / "schemas" / "gold_social_intelligence.py"
        assert not ddl.exists(), "dead non-bitemporal gold_social_intelligence DDL must be removed"

    def test_live_gold_social_intelligence_store_still_wired(self):
        # The live social gold is the metric-row GoldRepository("social_intelligence")
        # in repositories/lake.py; removing the dead DDL must not have removed it.
        spec = importlib.util.find_spec("repositories.lake")
        assert spec is not None
        from repositories.lake import gold_social_intelligence  # noqa: F401
