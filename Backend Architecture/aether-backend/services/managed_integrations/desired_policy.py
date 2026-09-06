"""Desired-state assembly for managed integrations (Phase 0).

The desired state declares *what should exist* (blueprint §12.1) so the
reconciler can diff it against an observed snapshot. Phase 0 assembles desired
state from two existing authorities and nothing new:

* release-channel policy (blueprint §28) — the tenant update channel maps to an
  inclusive runtime-version floor inside the canonical SDK version bands
  (``services/ingestion/sdk_version_tiers.py``). ``managed_stable`` is the
  Phase-0 default: "keep the runtime inside the served band (supported or
  deprecated)" — NOT "uncontrolled latest".
* capability requirements the caller asserts explicitly (a Phase-0 caller never
  has a capability set auto-derived; that would invent policy).

No authority is queried here — ``build_desired_state`` is a pure policy
function over the arguments the caller (or a later admission authority) passes.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable, Optional

from services.managed_integrations.contracts import (
    DEFAULT_MANAGED_RELEASE_CHANNEL,
    DesiredStateSpec,
    MinimumCapabilityRequirement,
)

# Release channel -> inclusive floor SDK band (blueprint §28 tenant channels).
# `pinned` pins the version (no auto floor → the version dimension is not
# reconciled). Every other managed channel keeps the runtime inside a *served*
# band:
#   managed_stable  -> deprecated floor (supported 8.x + deprecated 7.x served)
#   security_auto   -> deprecated floor (security patches still delivered to 7.x)
#   compatible_auto -> deprecated floor (auto-apply compatible upgrades within 7.x+)
#   patch_auto      -> supported floor (auto-apply patch releases within 8.x)
# These floors are advisory Phase-0 policy data; the *only* contracted default is
# managed_stable, which does NOT equate to following the newest published build.
_FLOOR_BAND_BY_CHANNEL: dict[str, Optional[str]] = {
    "managed_stable": "deprecated",
    "security_auto": "deprecated",
    "compatible_auto": "deprecated",
    "patch_auto": "supported",
    "pinned": None,
}

# Band ordering oldest-aware: supported is the newest band; the floor is the
# lowest band still acceptable for the channel.
_BAND_RANK: dict[str, int] = {
    "supported": 0,
    "deprecated": 1,
    "read_compatible": 2,
    "blocked": 3,
    "unsupported": 4,
    "unclassified": 5,
}


def floor_band_for_channel(release_channel: str) -> Optional[str]:
    """Inclusive floor SDK band id for a release channel (None = pinned)."""
    return _FLOOR_BAND_BY_CHANNEL.get(release_channel)


def channel_pins_version(release_channel: str) -> bool:
    """True when the channel pins the runtime version (no auto floor)."""
    return floor_band_for_channel(release_channel) is None


def minimum_runtime_version_for_channel(release_channel: str) -> Optional[str]:
    """Resolve the channel's minimum runtime version from the SDK band floor."""
    floor = floor_band_for_channel(release_channel)
    if floor is None:
        return None
    from services.ingestion.sdk_version_tiers import SDK_VERSION_BANDS

    band = next((b for b in SDK_VERSION_BANDS if b.id == floor), None)
    return band.min_version if band is not None else None


def classify_observed_runtime(version: Optional[str]) -> Optional[str]:
    """Return the SDK band id for an observed runtime version (None unclassifiable).

    Wraps ``sdk_version_tiers.classify_sdk_version``; a missing/unparseable
    version or unknown SDK name resolves to ``None`` so the reconciler never
    fabricates a version or release-support drift from a silent runtime.
    """
    if not version:
        return None
    from services.ingestion.sdk_version_tiers import classify_sdk_version

    band = classify_sdk_version(version)
    if band is None or getattr(band, "id", None) == "unclassified":
        return None
    return band.id


def is_below_channel_floor(release_channel: str, observed_band_id: Optional[str]) -> bool:
    """True when the observed band sits below the channel's inclusive floor.

    ``managed_stable`` floor = ``deprecated``: a ``deprecated`` (7.x) runtime is
    at the floor (served, acceptable); a ``read_compatible``/older runtime is
    below it (actionable version drift).
    """
    if observed_band_id is None or observed_band_id not in _BAND_RANK:
        return False
    floor = floor_band_for_channel(release_channel)
    if floor is None or floor not in _BAND_RANK:
        return False
    return _BAND_RANK[observed_band_id] > _BAND_RANK[floor]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def build_desired_state(
    *,
    managed_integration_id: str,
    tenant_id: str,
    environment_id: str,
    desired_state_id: Optional[str] = None,
    revision: str = "1",
    release_channel: str = DEFAULT_MANAGED_RELEASE_CHANNEL,
    minimum_capabilities: Optional[Iterable[tuple[str, str]]] = None,
    schema_fingerprint: Optional[str] = None,
    health_policy_ref: Optional[str] = None,
    integration_contract_ref: Optional[str] = None,
) -> DesiredStateSpec:
    """Build a Phase-0 ``DesiredStateSpec`` from explicit policy arguments.

    ``minimum_capabilities`` is an iterable of ``(capability, availability)`` —
    the caller asserts the requirement; nothing here auto-derives a capability
    set (that would invent policy).
    """
    caps: list[MinimumCapabilityRequirement] = []
    for capability, availability in minimum_capabilities or []:
        if availability not in ("available", "degraded", "empty", "missing"):
            raise ValueError(
                f"unsupported required availability {availability!r} for {capability!r}"
            )
        caps.append(
            MinimumCapabilityRequirement(
                capability=capability, required_availability=availability  # type: ignore[arg-type]
            )
        )
    return DesiredStateSpec(
        desired_state_id=desired_state_id or f"rcds_{managed_integration_id[:12]}",
        managed_integration_ref=managed_integration_id,
        tenant_id=tenant_id,
        environment_id=environment_id,
        revision=revision,
        release_channel=release_channel,  # type: ignore[arg-type]
        minimum_runtime_version=minimum_runtime_version_for_channel(release_channel),
        minimum_capabilities=caps,
        schema_fingerprint=schema_fingerprint,
        health_policy_ref=health_policy_ref,
        integration_contract_ref=integration_contract_ref,
        created_at=_utc_now(),
    )
