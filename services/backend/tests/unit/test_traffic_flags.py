"""Staged-rollout feature flags for traffic intelligence (spec §19)."""

from __future__ import annotations

import pytest

from services.traffic.flags import TrafficFlags


def test_boolean_flags_default_to_v1_behaviour(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in (
        "TRAFFIC_VERIFIED_SOURCE_LINK_REDIRECT",
        "TRAFFIC_WEB_NAVIGATION_CORRELATION",
        "TRAFFIC_ANDROID_INSTALL_REFERRER",
        "TRAFFIC_IOS_UNIVERSAL_LINK",
        "TRAFFIC_DEFERRED_ATTRIBUTION",
        "TRAFFIC_NATIVE_INTERACTION_TRACKING",
        "TRAFFIC_HISTORICAL_RECLASSIFICATION",
        "TRAFFIC_NEW_UI_LABELS",
        "TRAFFIC_SHADOW_CLASSIFICATION_ENABLED",
        "TRAFFIC_CANONICAL_LABELS_PROMOTED",
        "TRAFFIC_CANARY_TENANTS",
    ):
        monkeypatch.delenv(var, raising=False)

    flags = TrafficFlags()
    # Already-merged capabilities stay on; not-yet-promoted surfaces stay off.
    assert flags.verified_source_link_redirect is True
    assert flags.deferred_attribution is True
    assert flags.new_ui_labels is False
    assert flags.shadow_classification_enabled is False
    assert flags.canonical_labels_promoted is False
    assert flags.canary_tenants == []


def test_env_var_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TRAFFIC_SHADOW_CLASSIFICATION_ENABLED", "true")
    monkeypatch.setenv("TRAFFIC_NEW_UI_LABELS", "yes")
    monkeypatch.setenv("TRAFFIC_DEFERRED_ATTRIBUTION", "false")
    flags = TrafficFlags()
    assert flags.shadow_classification_enabled is True
    assert flags.new_ui_labels is True
    assert flags.deferred_attribution is False


def test_canary_gate(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TRAFFIC_SHADOW_CLASSIFICATION_ENABLED", "true")
    monkeypatch.setenv("TRAFFIC_CANARY_TENANTS", "tenant-a, tenant-b")
    flags = TrafficFlags()

    assert flags.canary_tenants == ["tenant-a", "tenant-b"]
    assert flags.is_enabled_for_tenant("shadow_classification_enabled", "tenant-a") is True
    assert flags.is_enabled_for_tenant("shadow_classification_enabled", "tenant-z") is False


def test_canary_empty_means_fleet_wide(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TRAFFIC_SHADOW_CLASSIFICATION_ENABLED", "true")
    monkeypatch.delenv("TRAFFIC_CANARY_TENANTS", raising=False)
    flags = TrafficFlags()
    assert flags.is_enabled_for_tenant("shadow_classification_enabled", "any-tenant") is True


def test_disabled_flag_is_off_for_every_tenant(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TRAFFIC_SHADOW_CLASSIFICATION_ENABLED", "false")
    monkeypatch.setenv("TRAFFIC_CANARY_TENANTS", "tenant-a")
    flags = TrafficFlags()
    assert flags.is_enabled_for_tenant("shadow_classification_enabled", "tenant-a") is False


def test_unknown_flag_is_disabled() -> None:
    assert TrafficFlags().is_enabled_for_tenant("no_such_flag", "tenant-a") is False
