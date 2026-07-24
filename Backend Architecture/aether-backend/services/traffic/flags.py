"""Feature flags for the traffic-intelligence staged rollout (spec §19).

Mirrors :class:`services.noesis.flags.NoesisFlags`: every flag is read from an
environment variable so rollout can be staged per environment without a
deploy, and a canary-tenant allowlist gates tenant-scoped enablement.

Boolean flags default to the value that preserves the already-merged
traffic-intelligence v1 behaviour. ``is_enabled_for_tenant`` layers the canary
allowlist on top of a boolean flag: when a canary list is configured a flag is
only "on" for tenants in that list, letting an operator ship a capability to a
handful of tenants before a fleet-wide flip.
"""

from __future__ import annotations

import os

_TRUE = ("true", "1", "yes", "on")


def _flag(env_var: str, default: str) -> bool:
    return os.getenv(env_var, default).lower() in _TRUE


class TrafficFlags:
    """Reads traffic-intelligence feature flags from environment variables."""

    # ── Capability flags (spec §19 rollout surface) ─────────────────────────
    @property
    def canonical_classifier_version(self) -> str:
        """Target classifier version operators are rolling the fleet toward."""
        from .classifier import SOURCE_CLASSIFIER_VERSION

        return os.getenv("TRAFFIC_CANONICAL_CLASSIFIER_VERSION", SOURCE_CLASSIFIER_VERSION)

    @property
    def verified_source_link_redirect(self) -> bool:
        return _flag("TRAFFIC_VERIFIED_SOURCE_LINK_REDIRECT", "true")

    @property
    def web_navigation_correlation(self) -> bool:
        return _flag("TRAFFIC_WEB_NAVIGATION_CORRELATION", "true")

    @property
    def android_install_referrer(self) -> bool:
        return _flag("TRAFFIC_ANDROID_INSTALL_REFERRER", "true")

    @property
    def android_app_link_auto(self) -> bool:
        return _flag("TRAFFIC_ANDROID_APP_LINK_AUTO", "true")

    @property
    def ios_universal_link(self) -> bool:
        return _flag("TRAFFIC_IOS_UNIVERSAL_LINK", "true")

    @property
    def deferred_attribution(self) -> bool:
        return _flag("TRAFFIC_DEFERRED_ATTRIBUTION", "true")

    @property
    def native_interaction_tracking(self) -> bool:
        return _flag("TRAFFIC_NATIVE_INTERACTION_TRACKING", "true")

    @property
    def historical_reclassification(self) -> bool:
        return _flag("TRAFFIC_HISTORICAL_RECLASSIFICATION", "true")

    @property
    def new_ui_labels(self) -> bool:
        return _flag("TRAFFIC_NEW_UI_LABELS", "false")

    # ── Shadow / promotion controls ─────────────────────────────────────────
    @property
    def shadow_classification_enabled(self) -> bool:
        """When on, the dispatcher records legacy-vs-canonical divergences."""
        return _flag("TRAFFIC_SHADOW_CLASSIFICATION_ENABLED", "false")

    @property
    def canonical_labels_promoted(self) -> bool:
        """True once canonical labels are the customer-visible default."""
        return _flag("TRAFFIC_CANONICAL_LABELS_PROMOTED", "false")

    @property
    def canary_tenants(self) -> list[str]:
        raw = os.getenv("TRAFFIC_CANARY_TENANTS", "").strip()
        if not raw:
            return []
        return [t.strip() for t in raw.split(",") if t.strip()]

    # ── Tenant-scoped gate ──────────────────────────────────────────────────
    _BOOL_FLAGS = frozenset({
        "verified_source_link_redirect",
        "web_navigation_correlation",
        "android_install_referrer",
        "android_app_link_auto",
        "ios_universal_link",
        "deferred_attribution",
        "native_interaction_tracking",
        "historical_reclassification",
        "new_ui_labels",
        "shadow_classification_enabled",
        "canonical_labels_promoted",
    })

    def is_tenant_canary(self, tenant_id: str) -> bool:
        """True when no canary list is configured (fleet-wide) or tenant is listed."""
        canaries = self.canary_tenants
        if not canaries:
            return True
        return tenant_id in canaries

    def is_enabled_for_tenant(self, flag: str, tenant_id: str) -> bool:
        """Return whether ``flag`` is on for ``tenant_id``.

        A flag is enabled for a tenant only when its boolean value is on AND the
        tenant is inside the canary allowlist (an empty list means every tenant).
        Unknown flag names are treated as disabled rather than raising, so a
        caller typo can never silently enable a capability.
        """
        if flag not in self._BOOL_FLAGS:
            return False
        if not bool(getattr(self, flag)):
            return False
        return self.is_tenant_canary(tenant_id)


# Module-level singleton mirrors the NoesisFlags usage pattern.
traffic_flags = TrafficFlags()

__all__ = ["TrafficFlags", "traffic_flags"]
