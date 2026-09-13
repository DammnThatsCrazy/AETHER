"""Desired-state assembly from release-channel policy (Phase 0).

``desired_policy.build_desired_state`` is a pure policy function: the channel
(§28, default ``managed_stable``) resolves to an inclusive floor inside the
canonical SDK version bands, and capabilities are only ever what a caller
asserts explicitly — nothing is auto-derived (that would invent policy).
"""

from __future__ import annotations

import pytest

from services.ingestion.sdk_version_tiers import (
    SDK_VERSION_BANDS,
    classify_sdk_version,
)
from services.managed_integrations.desired_policy import (
    build_desired_state,
    channel_pins_version,
    classify_observed_runtime,
    floor_band_for_channel,
    is_below_channel_floor,
    minimum_runtime_version_for_channel,
)


def test_managed_stable_is_the_default_and_floor_is_supported() -> None:
    desired = build_desired_state(
        managed_integration_id="mi-1",
        tenant_id="tenant-a",
        environment_id="env-1",
    )
    assert desired.release_channel == "managed_stable"
    assert desired.minimum_runtime_version == "0.1.0"  # supported band floor
    assert desired.revision == "1"


def test_channel_floor_band_policy_table() -> None:
    # All managed channels floor at supported (only active band); pinned pins.
    assert floor_band_for_channel("managed_stable") == "supported"
    assert floor_band_for_channel("security_auto") == "supported"
    assert floor_band_for_channel("compatible_auto") == "supported"
    assert floor_band_for_channel("patch_auto") == "supported"
    assert floor_band_for_channel("pinned") is None
    assert channel_pins_version("pinned") is True
    assert channel_pins_version("managed_stable") is False


def test_minimum_runtime_version_resolves_from_the_band_floor() -> None:
    # All managed channels resolve to the supported band floor (0.1.0).
    assert minimum_runtime_version_for_channel("patch_auto") == "0.1.0"
    assert minimum_runtime_version_for_channel("managed_stable") == "0.1.0"
    assert minimum_runtime_version_for_channel("pinned") is None


def test_build_desired_state_carries_explicit_capabilities() -> None:
    desired = build_desired_state(
        managed_integration_id="mi-2",
        tenant_id="tenant-a",
        environment_id="env-1",
        minimum_capabilities=[("batch_ingestion", "available")],
        schema_fingerprint="fp-1",
    )
    assert len(desired.minimum_capabilities) == 1
    assert desired.minimum_capabilities[0].capability == "batch_ingestion"
    assert desired.minimum_capabilities[0].required_availability == "available"
    assert desired.schema_fingerprint == "fp-1"


def test_build_desired_state_never_auto_derives_capabilities() -> None:
    desired = build_desired_state(
        managed_integration_id="mi-3",
        tenant_id="tenant-a",
        environment_id="env-1",
    )
    assert desired.minimum_capabilities == []


def test_build_desired_state_rejects_invalid_required_availability() -> None:
    with pytest.raises(ValueError):
        build_desired_state(
            managed_integration_id="mi-4",
            tenant_id="tenant-a",
            environment_id="env-1",
            minimum_capabilities=[("batch_ingestion", "not_a_label")],
        )


def test_build_desired_state_mints_desired_state_id() -> None:
    desired = build_desired_state(
        managed_integration_id="mi-abc",
        tenant_id="tenant-a",
        environment_id="env-1",
    )
    assert desired.desired_state_id == "rcds_mi-abc"
    assert desired.created_at.tzinfo is not None


def test_classify_observed_runtime_maps_to_sdk_bands() -> None:
    assert classify_observed_runtime("0.1.3") == "supported"
    assert classify_observed_runtime("0.2.0") == "supported"
    assert classify_observed_runtime("0.0.9") == "unsupported"
    # Missing / unparseable -> None (never a fabricated drift dimension).
    assert classify_observed_runtime(None) is None
    assert classify_observed_runtime("not.a.version") is None


def test_classify_observed_runtime_agrees_with_tier_classifier() -> None:
    assert classify_sdk_version("0.1.3").id == "supported"
    assert classify_sdk_version("0.2.0").id == "supported"
    assert classify_sdk_version("0.0.9").id == "unsupported"


def test_is_below_channel_floor_semantics() -> None:
    # managed_stable floor = supported: supported is at-or-above (no drift);
    # unsupported is below it (actionable).
    assert is_below_channel_floor("managed_stable", "supported") is False
    assert is_below_channel_floor("managed_stable", "unsupported") is True
    # pinned has no floor -> nothing is below it.
    assert is_below_channel_floor("pinned", "unsupported") is False
    # Unknown bands resolve to False (never invent drift from an unclassified id).
    assert is_below_channel_floor("managed_stable", None) is False


def test_managed_stable_floor_is_supported() -> None:
    # With the pre-1.0 scheme, supported (>=0.1.0) is the only active band.
    assert minimum_runtime_version_for_channel("managed_stable") == "0.1.0"
    supported_min = next(b.min_version for b in SDK_VERSION_BANDS if b.id == "supported")
    assert supported_min == "0.1.0"


def test_desired_state_timestamps_are_aware_utc() -> None:
    desired = build_desired_state(
        managed_integration_id="mi-5",
        tenant_id="tenant-a",
        environment_id="env-1",
    )
    assert desired.created_at.tzinfo is not None
    assert desired.created_at.utcoffset() is not None


def test_channel_floor_is_backed_by_a_real_served_band() -> None:
    band_ids = {b.id for b in SDK_VERSION_BANDS}
    for channel in ("managed_stable", "security_auto", "compatible_auto", "patch_auto"):
        floor = floor_band_for_channel(channel)
        assert floor in band_ids, f"{channel} floor {floor!r} not a real band"
