"""Social360SurfaceAdapter honest-state tests (M9).

The social360 intelligence-projection row is ``in_flight`` and has no registered
provider on this branch, so the adapter must report an honest degraded state —
``feature_disabled`` while the ``AETHER_SOCIAL_LENSES_ENABLED`` gate is off,
``provider_unavailable`` with no fabricated metrics once enabled — never
synthesised followers / engagement / relationship-strength numbers.
"""
from __future__ import annotations

import builtins

import pytest

from shared.exploration.generated_fields import FILTER_FIELD_CATEGORIES
from shared.exploration.models import ExplorationContextV1

from services.exploration.adapters.base import AdapterContext
from services.exploration.adapters.social360 import (
    Social360SurfaceAdapter,
    social_lenses_enabled,
)

# Metric-ish keys the social lens plane must NEVER fabricate when providers are
# unavailable (unknown is a state; zero is a measurement).
_FABRICATED_METRIC_MARKERS = (
    "followers",
    "engagement_rate",
    "relationship_strength",
    "influence",
    "audience_overlap",
)


def _adapter_ctx(lens_set: list[str] | None = None) -> AdapterContext:
    payload: dict = {
        "scope": {"tenant_id": "t1", "surface": "social360"},
        "temporal": {"mode": "window", "field": "occurred_at", "timezone": "UTC"},
    }
    if lens_set is not None:
        payload["lens_set"] = lens_set
    return AdapterContext(
        tenant_id="t1",
        context=ExplorationContextV1(**payload),
        applied_filters=[],
    )


def _result_payload_lower(result) -> str:
    return str(result.data).lower()


# ── Registry binding ────────────────────────────────────────────────────────

def test_adapter_bound_to_social360_surface_and_projection():
    adapter = Social360SurfaceAdapter(enabled=True)
    assert adapter.surface_id == "social360"
    assert adapter.resolved_projection_id == "social360"


def test_adapter_availability_is_honest_in_flight():
    adapter = Social360SurfaceAdapter(enabled=True)
    availability = adapter.availability()
    # The social360 projection row is in_flight on this branch and has no
    # registered provider — availability must say so, never implying readiness.
    assert availability.get("registryState") == "in_flight"
    assert availability.get("registered") is False


def test_adapter_capabilities_never_over_claim():
    adapter = Social360SurfaceAdapter(enabled=True)
    categories = adapter.capabilities["supported_field_categories"]
    # Pre-regeneration the generated twin lacks the social360 row and the
    # adapter honestly claims nothing; post-regeneration every declared category
    # must be a real filter-field category.
    allowed = set(FILTER_FIELD_CATEGORIES)
    assert set(categories) <= allowed


# ── Honest states ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_disabled_flag_reports_feature_disabled():
    adapter = Social360SurfaceAdapter(enabled=False)
    result = await adapter.execute(_adapter_ctx())
    assert result.surface == "social360"
    assert result.populated is False
    assert result.data["available"] is False
    assert result.data["reason"] == "feature_disabled"
    assert result.data["sections"] == []
    assert "feature_disabled" in result.warnings
    payload = _result_payload_lower(result)
    for marker in _FABRICATED_METRIC_MARKERS:
        assert marker not in payload


@pytest.mark.asyncio
async def test_enabled_in_flight_reports_provider_unavailable():
    adapter = Social360SurfaceAdapter(enabled=True)
    result = await adapter.execute(_adapter_ctx())
    assert result.surface == "social360"
    assert result.backend == "intelligence_projection"
    assert result.populated is False
    assert result.data["available"] is False
    assert result.data["reason"] == "provider_unavailable"
    assert result.data["sections"] == []
    assert "provider_unavailable" in result.warnings
    # No fabricated metrics and no no-evidence-as-zero conversion.
    payload = _result_payload_lower(result)
    for marker in _FABRICATED_METRIC_MARKERS:
        assert marker not in payload


@pytest.mark.asyncio
async def test_enabled_invalid_lens_frame_is_lens_frame_invalid():
    adapter = Social360SurfaceAdapter(enabled=True)
    result = await adapter.execute(_adapter_ctx(lens_set=["no_such_lens"]))
    assert result.populated is False
    assert result.data["available"] is False
    assert result.data["reason"] == "lens_frame_invalid"


# ── Flag-gate semantics (default OFF) ───────────────────────────────────────

def test_flag_gate_defaults_off_and_parses_env(monkeypatch):
    monkeypatch.setenv("AETHER_SOCIAL_LENSES_ENABLED", "")
    assert social_lenses_enabled() is False
    monkeypatch.setenv("AETHER_SOCIAL_LENSES_ENABLED", "0")
    assert social_lenses_enabled() is False
    monkeypatch.setenv("AETHER_SOCIAL_LENSES_ENABLED", "false")
    assert social_lenses_enabled() is False
    for truthy in ("1", "true", "on", "yes"):
        monkeypatch.setenv("AETHER_SOCIAL_LENSES_ENABLED", truthy)
        assert social_lenses_enabled() is True


def test_flag_gate_missing_config_defaults_off(monkeypatch):
    # When the env var is unset the gate attempts a defensive read of the app
    # settings object; a config that cannot be imported must fail CLOSED (OFF),
    # never raising and never enabling by accident.
    monkeypatch.delenv("AETHER_SOCIAL_LENSES_ENABLED", raising=False)
    real_import = builtins.__import__

    def _no_config(name, *args, **kwargs):
        if name in ("config", "config.settings"):
            raise ImportError("config.settings unavailable in M9 unit test")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _no_config)
    assert social_lenses_enabled() is False


def test_adapter_gate_respects_env_and_override(monkeypatch):
    monkeypatch.delenv("AETHER_SOCIAL_LENSES_ENABLED", raising=False)
    # With no override and no env, is_enabled() stays OFF.
    adapter = Social360SurfaceAdapter()
    # Patch the module gate function to avoid importing config.settings here;
    # the env parsing itself is covered by test_flag_gate_defaults_off_and_parses_env.
    import services.exploration.adapters.social360 as social360_module

    monkeypatch.setattr(social360_module, "social_lenses_enabled", lambda: False)
    assert adapter.is_enabled() is False
    monkeypatch.setattr(social360_module, "social_lenses_enabled", lambda: True)
    assert adapter.is_enabled() is True
    # An explicit constructor override always wins over the gate.
    assert Social360SurfaceAdapter(enabled=True).is_enabled() is True
    assert Social360SurfaceAdapter(enabled=False).is_enabled() is False
