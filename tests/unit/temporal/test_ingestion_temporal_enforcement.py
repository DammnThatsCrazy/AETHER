"""Temporal enforcement at ingestion: mode ladder, reason codes, envelopes.

Covers the pure classifier (`enforce_temporal`) and the batch.py hook
(`_apply_temporal_enforcement`) across off/shadow/warn/enforce — including the
PR-1 invariant that mode=off changes NOTHING about event processing.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from shared.temporal.instant import parse_instant_strict

RECEIVED = parse_instant_strict("2026-07-15T12:00:00Z")


def _enforce(**overrides):
    from services.ingestion.temporal_enforcement import enforce_temporal

    kwargs = dict(
        event_timestamp="2026-07-15T11:59:59Z",
        event_family="core",
        context_timezone=None,
        context_offset_minutes=None,
        context_tz_source=None,
        context_clock_source=None,
        context_locale=None,
        sent_at="2026-07-15T12:00:00Z",
        received_at=RECEIVED,
    )
    kwargs.update(overrides)
    return enforce_temporal(**kwargs)


def test_valid_event_with_provenance_accepts_cleanly():
    decision = _enforce(
        context_timezone="America/New_York",
        context_offset_minutes=-240,
        context_tz_source="device",
        context_clock_source="device",
        context_locale="en-US",
    )
    assert decision.disposition == "accept"
    assert decision.reason_codes == []
    env = decision.envelope
    assert env is not None
    assert env.temporal_state == "valid"
    assert env.source_time_zone == "America/New_York"
    assert env.clock_skew_ms == -1000
    assert env.delivery_lag_ms == 0
    assert env.temporal_policy_version and env.tzdb_version


def test_naive_timestamp_maps_to_reject_disposition():
    decision = _enforce(event_timestamp="2026-07-15T11:59:59")
    assert decision.envelope is None
    assert decision.disposition == "reject"
    assert decision.reason_codes == ["timestamp_naive"]


def test_unparseable_timestamp_rejects():
    decision = _enforce(event_timestamp="garbage")
    assert decision.disposition == "reject"
    assert decision.reason_codes == ["timestamp_invalid"]


def test_future_beyond_family_tolerance_rejects():
    future = (RECEIVED + timedelta(minutes=10)).isoformat().replace("+00:00", "Z")
    decision = _enforce(event_timestamp=future)
    assert decision.disposition == "reject"
    assert "timestamp_future" in decision.reason_codes


def test_missing_timezone_is_warn_only():
    decision = _enforce()  # no timezone claimed
    assert decision.disposition == "accept_with_warning"
    assert decision.reason_codes == ["temporal_provenance_missing"]
    assert decision.envelope.temporal_state == "timezone_unknown"


def test_invalid_zone_and_offset_mismatch():
    bad_zone = _enforce(context_timezone="EST")
    assert "timezone_invalid" in bad_zone.reason_codes
    assert bad_zone.disposition == "reject"

    mismatch = _enforce(context_timezone="America/New_York", context_offset_minutes=-300)
    assert "timezone_offset_mismatch" in mismatch.reason_codes
    assert mismatch.disposition == "reject"


def test_too_old_quarantines():
    old = (RECEIVED - timedelta(days=30)).isoformat().replace("+00:00", "Z")
    decision = _enforce(event_timestamp=old, context_timezone="America/New_York",
                        context_offset_minutes=-240)
    assert "timestamp_too_old" in decision.reason_codes
    assert decision.disposition == "quarantine"
    assert decision.blocked


def test_web3_family_tolerates_month_old_events():
    old = (RECEIVED - timedelta(days=20)).isoformat().replace("+00:00", "Z")
    core = _enforce(event_timestamp=old)
    web3 = _enforce(event_timestamp=old, event_family="web3_lc")
    assert "timestamp_too_old" in core.reason_codes  # 7d default lateness
    assert "timestamp_too_old" not in web3.reason_codes  # 30d chain lateness


# ── batch.py hook: the mode ladder ────────────────────────────────────────────


def _hook(mode: str, *, timestamp: str = "2026-07-15T11:59:59Z", canary=()):
    import config.settings as settings_module
    from config.settings import TemporalIntegrityConfig
    from services.ingestion import batch

    original = settings_module.settings.temporal_integrity
    settings_module.settings.temporal_integrity = TemporalIntegrityConfig(
        enforcement_mode=mode, canary_tenants=list(canary)
    )
    try:
        event = batch.BaseEvent(
            id="evt-1",
            type="track",
            timestamp=timestamp,
            sessionId="s1",
            anonymousId="a1",
        )
        result = batch.EventResult(id="evt-1", status="accepted")
        normalized = {"event_id": "evt-1"}
        out = batch._apply_temporal_enforcement(
            sdk_event=event,
            result=result,
            normalized=normalized,
            tenant_id="tenant-1",
            sent_at="2026-07-15T12:00:00Z",
            received_at_dt=RECEIVED,
        )
        return out, normalized
    finally:
        settings_module.settings.temporal_integrity = original


def test_mode_off_changes_nothing():
    out, normalized = _hook("off", timestamp="2026-07-15T11:59:59")  # even naive
    assert out.status == "accepted" and out.reason is None
    assert "temporal" not in normalized


def test_mode_shadow_attaches_envelope_without_behavior_change():
    out, normalized = _hook("shadow")
    assert out.status == "accepted" and out.reason is None
    assert normalized["temporal"]["temporal_state"] == "timezone_unknown"
    assert normalized["temporal"]["temporal_policy_version"]


def test_mode_shadow_never_rejects_even_naive():
    out, normalized = _hook("shadow", timestamp="2026-07-15T11:59:59")
    assert out.status == "accepted"
    assert "temporal" not in normalized  # no envelope computable for naive


def test_mode_warn_surfaces_reasons_but_accepts():
    out, _ = _hook("warn")
    assert out.status == "accepted"
    assert out.reason.startswith("temporal_warning:")
    assert "temporal_provenance_missing" in out.reason


def test_mode_enforce_rejects_naive():
    out, _ = _hook("enforce", timestamp="2026-07-15T11:59:59")
    assert out.status == "rejected"
    assert out.reason.startswith("temporal_reject:")
    assert "timestamp_naive" in out.reason


def test_mode_enforce_accepts_valid_with_warning_reasons_intact():
    out, normalized = _hook("enforce")
    assert out.status == "accepted"
    assert normalized["temporal"]["reason_codes"] == ["temporal_provenance_missing"]


def test_canary_scoping_leaves_other_tenants_off():
    out, normalized = _hook("enforce", timestamp="2026-07-15T11:59:59",
                            canary=("someone-else",))
    assert out.status == "accepted"  # tenant-1 is not in the canary list
    assert "temporal" not in normalized
