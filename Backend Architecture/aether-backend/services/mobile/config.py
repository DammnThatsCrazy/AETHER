"""Mobile config assembly — GET /v1/mobile/config (M2, plan M2).

Owns the distribution-profile vocabulary (``DistributionProfile`` values +
family discriminator), the version-support policy (min/latest), the
upgrade-policy derivation, and the typed ``MobileConfig`` response.

Boundaries (reuse-before-build):
- ``service_capabilities`` is a READ-ONLY projection of the existing
  ``config/settings.py`` flags — no second backend flag system is created.
- ``feature_flags`` are the mobile-version client feature surface (all default
  OFF; version-gated rollout is staged behind future gates). No fabricated
  capability is ever surfaced.
- ``externally_blocked_providers`` is the honest static mirror of
  reports/mobile-productization/external-blockers.json ids.
- ``latest_version`` must track the platform version (pyproject.toml /
  app package.json / scripts/mobile_build_check.py PLATFORM_VERSION, pinned by
  scripts/check_version_consistency.py). This module declares the version
  SUPPORT policy; it never re-defines the build version.

Wire fields are snake_case (decision-log D6). Parity-tested by
tests/contracts/test_mobile_config_parity.py.
"""
from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, field_validator

from config.settings import settings

# ── Distribution profiles ───────────────────────────────────────────────────
#
# Two families. `dev` is family-agnostic (valid for both platforms); the rest
# are single-family. Values are snake_case.
IOS_DISTRIBUTION_PROFILES: tuple[str, ...] = ("dev", "testflight", "app_store")
ANDROID_DISTRIBUTION_PROFILES: tuple[str, ...] = ("dev", "play_internal", "managed")
DISTRIBUTION_PROFILES: tuple[str, ...] = (
    "dev",
    "testflight",
    "app_store",
    "play_internal",
    "managed",
)


class DistributionProfile(str, Enum):
    """Distribution-profile values (snake_case). Two families.

    - iOS:      dev, testflight, app_store
    - Android:  dev, play_internal, managed
    ``dev`` is family-agnostic; the family discriminator is
    :func:`profile_family` (falls back to the install platform for ``dev``).
    """

    dev = "dev"
    testflight = "testflight"
    app_store = "app_store"
    play_internal = "play_internal"
    managed = "managed"


def profile_family(profile: Optional[str], platform: Optional[str] = None) -> Optional[str]:
    """Effective distribution family (ios | android) for a profile.

    Unambiguous profiles return their family directly; ``dev`` is
    family-agnostic and falls back to the install platform when known
    (None when unknown)."""
    if profile in ("testflight", "app_store"):
        return "ios"
    if profile in ("play_internal", "managed"):
        return "android"
    if profile == "dev" and platform in ("ios", "android"):
        return platform
    return None


def validate_distribution_profile(profile: Optional[str]) -> Optional[str]:
    """Reject unknown distribution-profile values (case-sensitive snake_case)."""
    if profile is None:
        return None
    if profile not in DISTRIBUTION_PROFILES:
        raise ValueError(
            f"distribution_profile must be one of {', '.join(DISTRIBUTION_PROFILES)}"
        )
    return profile


# ── Version-support policy ───────────────────────────────────────────────────
#
# Deliberately declared, not parsed at runtime. `latest` must track the
# platform version (pinned by scripts/check_version_consistency.py); `min` is
# the declared support floor.
MIN_SUPPORTED_MOBILE_VERSION = "8.10.0"
LATEST_MOBILE_VERSION = "8.12.0"

UPGRADE_POLICIES: tuple[str, ...] = ("required", "suggested", "none")


class UpgradePolicy(str, Enum):
    required = "required"
    suggested = "suggested"
    none = "none"


def _version_parts(v: str) -> list[int]:
    parts: list[int] = []
    for p in v.split("."):
        try:
            parts.append(int(p))
        except ValueError:
            parts.append(0)
    return parts


def compare_versions(a: str, b: str) -> int:
    """Compare dotted-numeric versions: -1 (a<b), 0 (a==b), 1 (a>b)."""
    pa, pb = _version_parts(a), _version_parts(b)
    for x, y in zip(pa, pb):
        if x < y:
            return -1
        if x > y:
            return 1
    return (len(pa) > len(pb)) - (len(pa) < len(pb))


def upgrade_policy_for(app_version: Optional[str]) -> str:
    """Derive the upgrade policy from the version comparison.

    - app_version <  min_supported        → "required"
    - min_supported <= app_version < latest → "suggested"
    - app_version >= latest               → "none"
    - unknown app_version                 → "required" (fail-safe floor)
    """
    if not app_version:
        return UpgradePolicy.required.value
    if compare_versions(app_version, MIN_SUPPORTED_MOBILE_VERSION) < 0:
        return UpgradePolicy.required.value
    if compare_versions(app_version, LATEST_MOBILE_VERSION) < 0:
        return UpgradePolicy.suggested.value
    return UpgradePolicy.none.value


# ── Per-version client feature flags ────────────────────────────────────────
#
# All default OFF. `app_version` is accepted so future per-version policy has a
# seam here without changing the contract.
VERSION_FEATURE_FLAG_KEYS: tuple[str, ...] = (
    "today_screen",
    "copilot_screen",
    "explore_screen",
    "alerts_screen",
    "account_screen",
    "offline_cache",
    "biometric_unlock",
)


def feature_flags_for(app_version: Optional[str]) -> dict[str, bool]:
    return {key: False for key in VERSION_FEATURE_FLAG_KEYS}


# ── Service capabilities (read-only settings projection) ─────────────────────
def service_capabilities() -> dict[str, bool]:
    """Which backend services are enabled, per config/settings.py flags."""
    return {
        "mobile_gateway": bool(settings.mobile.enabled),
        "continuation": bool(settings.continuation.enabled),
        "client_sync": bool(settings.client_sync.enabled),
        "exploration": bool(settings.exploration.enabled),
        "delivery": bool(settings.delivery.enabled),
        "command_center": bool(settings.command_center.command_center_enabled),
        "data_quality": bool(settings.data_quality.enabled),
    }


# ── Honest externally-blocked providers ─────────────────────────────────────
# Static mirror of the ids in reports/mobile-productization/external-blockers.json
# (the human-maintained source of truth). Kept honest: a provider listed here is
# NOT live, and no config claim flips that.
EXTERNALLY_BLOCKED_PROVIDERS: tuple[str, ...] = (
    "apns",
    "fcm",
    "web_push_vapid",
    "email_ses",
    "apple_signing",
    "google_play_signing",
    "aws_infra",
    "physical_device_matrix",
    "native_mobile_build",
    "store_distribution",
)


# ── Typed response ───────────────────────────────────────────────────────────
class _Base(BaseModel):
    model_config = ConfigDict(extra="forbid")


class MobileConfig(_Base):
    app_kind: str
    environment: str
    min_version: str
    latest_version: str
    upgrade_policy: str
    distribution_profile: str
    feature_flags: dict[str, bool]
    service_capabilities: dict[str, bool]
    externally_blocked_providers: list[str]

    @field_validator("upgrade_policy")
    @classmethod
    def _upgrade(cls, v: str) -> str:
        if v not in UPGRADE_POLICIES:
            raise ValueError(f"upgrade_policy must be one of {UPGRADE_POLICIES}")
        return v

    @field_validator("distribution_profile")
    @classmethod
    def _profile(cls, v: str) -> str:
        if v not in DISTRIBUTION_PROFILES:
            raise ValueError(
                f"distribution_profile must be one of {', '.join(DISTRIBUTION_PROFILES)}"
            )
        return v


def build_mobile_config(
    *,
    app_kind: str,
    environment: str,
    app_version: Optional[str],
    distribution_profile: Optional[str],
) -> dict:
    """Assemble the typed MobileConfig response (snake_case wire fields)."""
    cfg = MobileConfig(
        app_kind=app_kind,
        environment=environment,
        min_version=MIN_SUPPORTED_MOBILE_VERSION,
        latest_version=LATEST_MOBILE_VERSION,
        upgrade_policy=upgrade_policy_for(app_version),
        distribution_profile=distribution_profile or "dev",
        feature_flags=feature_flags_for(app_version),
        service_capabilities=service_capabilities(),
        externally_blocked_providers=list(EXTERNALLY_BLOCKED_PROVIDERS),
    )
    return cfg.model_dump(mode="json")
