"""Customer-facing experience categories (additive, ADR-0010).

Aether's engineering taxonomy is per-surface: inbound connectors carry a
``ConnectorCategory`` value (``commerce``, ``crm``, ``marketing`` …), payment
rails and credit bureaus carry their own category strings, and provider
adapters carry ``ProviderCategory``. That vocabulary answers *what a system is*,
not *what a customer is trying to do*.

:data:`ExperienceCategory` is a small, additive, customer-facing projection of
that vocabulary into eight lifecycle experiences (``advertising_campaigns``,
``commerce_revenue``, …). It exists **beside** the engineering categories — it
never renames or removes them (ADR-0010). The derivation is a pure function of a
:class:`~shared.integration_contracts.manifest.ProviderManifest`'s canonical
engineering tokens, following the ADR-C11 "derive, never hardcode a cohort in one
place" rule: no per-provider list is duplicated here, and every rule keys off a
stable token the manifest already carries.

Mapping precedence (deterministic, at most one category per integration — a
Settings→Integrations grouping needs a single bucket):

1. ``product_id`` rule — e.g. measurement ad connectors (``product_id="ads"``).
2. ``category`` rule — BYOD connectors and rails carry an engineering category
   string (``commerce`` → ``commerce_revenue`` …).
3. ADR-C11 cohort — a manifest that declares ``comms.*`` data outputs but no
   category/product rule is a communications provider by derivation.

A manifest that matches none of these (e.g. a deferred credit bureau) yields
``None``; it is not forced into a bucket it does not evidence.
"""

from __future__ import annotations

import enum
from typing import Optional

from shared.integration_contracts.manifest import ProviderManifest


class ExperienceCategory(str, enum.Enum):
    """Customer-facing lifecycle experience (ADR-0010).

    Member values are the stable wire tokens shared with the tenant UI and the
    public site. They are lowercase snake_case and never change once shipped.
    """

    ADVERTISING_CAMPAIGNS = "advertising_campaigns"
    COMMERCE_REVENUE = "commerce_revenue"
    CRM_CUSTOMER = "crm_customer"
    COMMUNICATIONS_LIFECYCLE = "communications_lifecycle"
    ANALYTICS_BEHAVIOR = "analytics_behavior"
    SOCIAL_COMMUNITY = "social_community"
    CUSTOMER_SUPPORT = "customer_support"
    WORK_OPERATIONS = "work_operations"


# Stable presentation order for the customer-facing catalog / Settings groups.
EXPERIENCE_CATEGORIES: tuple[ExperienceCategory, ...] = (
    ExperienceCategory.ADVERTISING_CAMPAIGNS,
    ExperienceCategory.COMMERCE_REVENUE,
    ExperienceCategory.CRM_CUSTOMER,
    ExperienceCategory.COMMUNICATIONS_LIFECYCLE,
    ExperienceCategory.ANALYTICS_BEHAVIOR,
    ExperienceCategory.SOCIAL_COMMUNITY,
    ExperienceCategory.CUSTOMER_SUPPORT,
    ExperienceCategory.WORK_OPERATIONS,
)

# ── Derivation rule tables ───────────────────────────────────────────────────

# product_id → experience. The measurement ad connectors (google_ads, meta_ads,
# tiktok_ads, linkedin_ads, x_ads, reddit_ads, microsoft_ads) are exposed in the
# unified catalog with product_id="ads"; a single product rule covers all of
# them so advertising membership is never a hand-synced platform list.
_PRODUCT_TO_EXPERIENCE: dict[str, ExperienceCategory] = {
    "ads": ExperienceCategory.ADVERTISING_CAMPAIGNS,
}

# category string → experience. Keys are the canonical engineering category
# values a ProviderManifest may carry: the BYOD ConnectorCategory values
# (messaging … support), the payment-rail "payments" value, and the provider
# "ad_platform" value. Category values with no connectable customer surface
# today (onchain/cex/… layer-1 provider-catalog values, "credit_bureau") are
# intentionally absent: they derive to None rather than a fabricated bucket.
_CATEGORY_TO_EXPERIENCE: dict[str, ExperienceCategory] = {
    "commerce": ExperienceCategory.COMMERCE_REVENUE,
    "billing": ExperienceCategory.COMMERCE_REVENUE,
    "payments": ExperienceCategory.COMMERCE_REVENUE,
    "crm": ExperienceCategory.CRM_CUSTOMER,
    "marketing": ExperienceCategory.COMMUNICATIONS_LIFECYCLE,
    "ad_platform": ExperienceCategory.ADVERTISING_CAMPAIGNS,
    "product_analytics": ExperienceCategory.ANALYTICS_BEHAVIOR,
    # A generic signed webhook is an inbound ingestion channel; absent a more
    # specific category it lands under behavioral data.
    "webhook": ExperienceCategory.ANALYTICS_BEHAVIOR,
    "project": ExperienceCategory.WORK_OPERATIONS,
    "messaging": ExperienceCategory.WORK_OPERATIONS,
    "support": ExperienceCategory.CUSTOMER_SUPPORT,
}

# ADR-C11 cohort token. Communications membership is derived from manifest data
# outputs that feed the communications product destinations (comms.*). Kept as a
# single prefix constant so the classifier and any future consumer agree.
_COMMS_OUTPUT_PREFIX = "comms."


def experience_category_for(
    manifest: ProviderManifest,
) -> Optional[ExperienceCategory]:
    """Derive the single customer-facing experience for a manifest, or None.

    Pure function of the manifest's canonical engineering tokens (product_id,
    category, data_outputs). Returns at most one category so Settings→Integrations
    can group each integration under exactly one experience heading.
    """
    product_rule = _PRODUCT_TO_EXPERIENCE.get(manifest.product_id)
    if product_rule is not None:
        return product_rule

    category_rule = _CATEGORY_TO_EXPERIENCE.get(manifest.category)
    if category_rule is not None:
        return category_rule

    if any(
        output.startswith(_COMMS_OUTPUT_PREFIX)
        for output in manifest.data_outputs
    ):
        return ExperienceCategory.COMMUNICATIONS_LIFECYCLE

    return None


__all__ = [
    "EXPERIENCE_CATEGORIES",
    "ExperienceCategory",
    "experience_category_for",
]
