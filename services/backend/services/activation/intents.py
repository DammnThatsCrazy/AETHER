"""Activation intents — the customer goal layer over the one catalog (WS-3).

Intent-driven activation lets a tenant say *what they are trying to do* (drive
sales, run ads, engage customers, ...) rather than *which connector to switch
on*. Each :class:`ActivationIntent` recommends an ordered set of
:class:`~shared.integration_contracts.experience.ExperienceCategory` values; the
recommended integrations under those categories are then derived from the one
derived catalog (:data:`ALL_MANIFESTS`) — never a hand-synced per-provider list
(ADR-C11 "derive, don't hardcode a cohort").

This module is a pure projection. It holds intent metadata and the catalog→plan
entry projection helpers only; the tenant-aware planner
(:mod:`services.activation.planner`) owns the connect-step derivation and the
mutations that reuse ``connector_service`` + the credential service.

The intent vocabulary is deliberately customer-facing (shared with the tenant
UI) and is separate from the engineering connector taxonomy, exactly like
:data:`~shared.integration_contracts.experience.ExperienceCategory`.
"""
from __future__ import annotations

import enum
from typing import Any

from shared.integration_contracts.catalog import ALL_MANIFESTS
from shared.integration_contracts.experience import (
    EXPERIENCE_CATEGORIES,
    ExperienceCategory,
    experience_category_for,
)
from shared.integration_contracts.manifest import ProviderManifest


class ActivationIntent(str, enum.Enum):
    """Customer goal the activation flow turns into connect steps.

    Member values are stable snake_case wire tokens shared with the tenant UI.
    They never change once shipped.
    """

    GROW_REVENUE = "grow_revenue"
    RUN_ADVERTISING = "run_advertising"
    KNOW_CUSTOMERS = "know_customers"
    ENGAGE_CUSTOMERS = "engage_customers"
    UNDERSTAND_BEHAVIOR = "understand_behavior"
    GROW_COMMUNITY = "grow_community"
    SUPPORT_CUSTOMERS = "support_customers"
    STREAMLINE_WORK = "streamline_work"


# Stable presentation order for the intent picker.
INTENT_ORDER: tuple[ActivationIntent, ...] = (
    ActivationIntent.GROW_REVENUE,
    ActivationIntent.RUN_ADVERTISING,
    ActivationIntent.KNOW_CUSTOMERS,
    ActivationIntent.ENGAGE_CUSTOMERS,
    ActivationIntent.UNDERSTAND_BEHAVIOR,
    ActivationIntent.GROW_COMMUNITY,
    ActivationIntent.SUPPORT_CUSTOMERS,
    ActivationIntent.STREAMLINE_WORK,
)


def _ordered_intent_tokens() -> list[str]:
    return [i.value for i in INTENT_ORDER]


# ── Intent copy (single-sourced here so the backend and tenant UI agree) ────

_INTENT_LABELS: dict[ActivationIntent, str] = {
    ActivationIntent.GROW_REVENUE: "Grow revenue",
    ActivationIntent.RUN_ADVERTISING: "Run ad campaigns",
    ActivationIntent.KNOW_CUSTOMERS: "Understand my customers",
    ActivationIntent.ENGAGE_CUSTOMERS: "Reach & engage customers",
    ActivationIntent.UNDERSTAND_BEHAVIOR: "Analyze product behavior",
    ActivationIntent.GROW_COMMUNITY: "Build my community",
    ActivationIntent.SUPPORT_CUSTOMERS: "Support customers",
    ActivationIntent.STREAMLINE_WORK: "Connect work tools",
}

_INTENT_DESCRIPTIONS: dict[ActivationIntent, str] = {
    ActivationIntent.GROW_REVENUE: (
        "Connect your store and payment rails, then reach buyers where they shop."
    ),
    ActivationIntent.RUN_ADVERTISING: (
        "Bring your ad accounts in so campaign performance lands in Aether."
    ),
    ActivationIntent.KNOW_CUSTOMERS: (
        "Sync your CRM so every profile carries its full customer record."
    ),
    ActivationIntent.ENGAGE_CUSTOMERS: (
        "Connect your email and messaging providers to reach your audience."
    ),
    ActivationIntent.UNDERSTAND_BEHAVIOR: (
        "Feed product analytics and events in to measure how users behave."
    ),
    ActivationIntent.GROW_COMMUNITY: (
        "Bring social and community activity into your customer view."
    ),
    ActivationIntent.SUPPORT_CUSTOMERS: (
        "Connect support channels so ticket context lives on every profile."
    ),
    ActivationIntent.STREAMLINE_WORK: (
        "Connect the work tools your team runs on every day."
    ),
}

# Intent → ordered recommended experience categories. A category a manifest
# cannot evidence today simply resolves to an honest empty/available list rather
# than a fabricated recommendation (experience_category_for returns None).
_INTENT_RECOMMENDATIONS: dict[ActivationIntent, tuple[ExperienceCategory, ...]] = {
    ActivationIntent.GROW_REVENUE: (
        ExperienceCategory.COMMERCE_REVENUE,
        ExperienceCategory.ADVERTISING_CAMPAIGNS,
    ),
    ActivationIntent.RUN_ADVERTISING: (
        ExperienceCategory.ADVERTISING_CAMPAIGNS,
        ExperienceCategory.ANALYTICS_BEHAVIOR,
    ),
    ActivationIntent.KNOW_CUSTOMERS: (
        ExperienceCategory.CRM_CUSTOMER,
        ExperienceCategory.COMMUNICATIONS_LIFECYCLE,
    ),
    ActivationIntent.ENGAGE_CUSTOMERS: (
        ExperienceCategory.COMMUNICATIONS_LIFECYCLE,
        ExperienceCategory.CRM_CUSTOMER,
    ),
    ActivationIntent.UNDERSTAND_BEHAVIOR: (
        ExperienceCategory.ANALYTICS_BEHAVIOR,
    ),
    ActivationIntent.GROW_COMMUNITY: (
        ExperienceCategory.SOCIAL_COMMUNITY,
        ExperienceCategory.COMMUNICATIONS_LIFECYCLE,
    ),
    ActivationIntent.SUPPORT_CUSTOMERS: (
        ExperienceCategory.CUSTOMER_SUPPORT,
        ExperienceCategory.WORK_OPERATIONS,
    ),
    ActivationIntent.STREAMLINE_WORK: (
        ExperienceCategory.WORK_OPERATIONS,
        ExperienceCategory.ANALYTICS_BEHAVIOR,
    ),
}


# ── Experience-category copy (single-sourced, §6 vocabulary) ────────────────

_EXPERIENCE_LABELS: dict[ExperienceCategory, str] = {
    ExperienceCategory.ADVERTISING_CAMPAIGNS: "Advertising",
    ExperienceCategory.COMMERCE_REVENUE: "Commerce & Revenue",
    ExperienceCategory.CRM_CUSTOMER: "Customer & CRM",
    ExperienceCategory.COMMUNICATIONS_LIFECYCLE: "Communications",
    ExperienceCategory.ANALYTICS_BEHAVIOR: "Analytics & Behavior",
    ExperienceCategory.SOCIAL_COMMUNITY: "Social & Community",
    ExperienceCategory.CUSTOMER_SUPPORT: "Customer Support",
    ExperienceCategory.WORK_OPERATIONS: "Work & Operations",
}


def experience_label(category: ExperienceCategory) -> str:
    """Customer-facing heading for an experience category (§6 vocabulary)."""
    return _EXPERIENCE_LABELS[category]


def intent_catalog() -> list[dict[str, Any]]:
    """The intent picker: every goal with its recommended experience categories.

    Pure projection — no tenant state. The tenant UI renders this as the "What
    are you trying to do?" step and the planner turns the selections into
    connect steps.
    """
    return [
        {
            "token": intent.value,
            "label": _INTENT_LABELS[intent],
            "description": _INTENT_DESCRIPTIONS[intent],
            "recommended_categories": [
                c.value for c in _INTENT_RECOMMENDATIONS[intent]
            ],
        }
        for intent in INTENT_ORDER
    ]


def experience_categories_view() -> list[dict[str, str]]:
    """Ordered experience-category tokens + display labels (canonical order)."""
    return [
        {"token": cat.value, "label": _EXPERIENCE_LABELS[cat]}
        for cat in EXPERIENCE_CATEGORIES
    ]


def recommended_categories_for(intent: ActivationIntent) -> tuple[ExperienceCategory, ...]:
    """The experience categories one intent recommends (ordered)."""
    return _INTENT_RECOMMENDATIONS.get(intent, ())


def valid_intent_tokens() -> frozenset[str]:
    return frozenset(_ordered_intent_tokens())


def intent_label(intent: ActivationIntent) -> str:
    return _INTENT_LABELS.get(intent, intent.value)


def intent_description(intent: ActivationIntent) -> str:
    return _INTENT_DESCRIPTIONS.get(intent, "")


# ── Catalog → activation-entry projection ────────────────────────────────────
# Reuses the manifest classifier (experience_category_for) and the derived
# ALL_MANIFESTS union so every recommended integration is real catalog truth,
# never a hand-synced provider list.

def _manifest_connectable(m: ProviderManifest) -> bool:
    """True when this manifest is reachable through the Settings connect
    surface that ``connector_service`` manages (the BYOD ``ingestion``
    product). Advertising (``ads``) and payment-rail (``payment_rails``)
    manifests have their own connect flows and stay honest here."""
    return m.product_id == "ingestion"


def manifest_to_activation_entry(m: ProviderManifest) -> dict[str, Any]:
    """Project one manifest onto the activation plan-entry wire shape.

    ``connectable`` is a fact about the *connect surface*, never a readiness
    claim. ``manifest_readiness`` is the manifest's catalog baseline
    (credential-waiting material) so the UI never invents tenant readiness.
    """
    category = experience_category_for(m)
    connectable = _manifest_connectable(m)
    return {
        "key": m.identity_key,
        "family": m.provider_family,
        "product": m.product_id,
        "display_name": m.display_name,
        "experience_category": category.value if category is not None else None,
        "connectable": connectable,
        "connect_unavailable_reason": (
            None
            if connectable
            else (
                "managed_by_other_flow"
                if m.product_id in {"ads", "payment_rails"}
                else "catalog_baseline"
            )
        ),
        "credential_required": bool(m.authentication.credential_schema),
        "authentication": m.authentication.type,
        "accounts_discovery": m.accounts.discovery_supported,
        "accounts_selection_required": m.accounts.selection_required,
        "sync_initial_backfill": m.sync.initial_backfill,
        "manifest_readiness": {
            "state": m.readiness.state.value,
            "level": m.readiness.level,
        },
    }


def category_manifests(category: ExperienceCategory) -> list[ProviderManifest]:
    """Every self-service, environment-enabled manifest in one experience.

    Deferred/never-enabled manifests (credit bureaus) are excluded by the
    environment gate, keeping the activation surface honest about what can
    actually be connected today.
    """
    out = []
    for m in ALL_MANIFESTS:
        if not m.availability.environments.any_enabled():
            continue
        if not m.availability.tenant_self_service:
            continue
        if experience_category_for(m) is not category:
            continue
        out.append(m)
    # Deterministic order: connectable (connector_service surface) first, then
    # by display name. No readiness ordering is implied.
    out.sort(
        key=lambda m: (
            not _manifest_connectable(m),
            m.display_name.lower(),
            m.identity_key,
        )
    )
    return out


def connectable_manifests_for(category: ExperienceCategory) -> list[ProviderManifest]:
    """Only the manifests reachable through the shared connector_service
    connect surface under one experience category."""
    return [m for m in category_manifests(category) if _manifest_connectable(m)]


__all__ = [
    "ActivationIntent",
    "INTENT_ORDER",
    "category_manifests",
    "connectable_manifests_for",
    "experience_categories_view",
    "experience_label",
    "intent_catalog",
    "intent_description",
    "intent_label",
    "manifest_to_activation_entry",
    "recommended_categories_for",
    "valid_intent_tokens",
]
