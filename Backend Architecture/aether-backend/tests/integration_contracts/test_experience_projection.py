"""Experience-category projection (ADR-0010): derived, never hardcoded.

Every manifest in the catalog maps to at most one customer-facing experience
category, and the mapping is a pure function of the manifest's canonical
engineering tokens — no per-provider list is duplicated in the classifier.
"""

from __future__ import annotations

from shared.integration_contracts.catalog import (
    ALL_MANIFESTS,
    CONNECTOR_MANIFESTS,
    DEFERRED_CREDIT_BUREAU_MANIFESTS,
    PAYMENT_RAIL_MANIFESTS,
    manifest_by_family,
)
from shared.integration_contracts.experience import (
    EXPERIENCE_CATEGORIES,
    ExperienceCategory,
    experience_category_for,
)

# The eight lifecycle experiences, in stable presentation order (ADR-0010).
_EXPECTED = (
    ExperienceCategory.ADVERTISING_CAMPAIGNS,
    ExperienceCategory.COMMERCE_REVENUE,
    ExperienceCategory.CRM_CUSTOMER,
    ExperienceCategory.COMMUNICATIONS_LIFECYCLE,
    ExperienceCategory.ANALYTICS_BEHAVIOR,
    ExperienceCategory.SOCIAL_COMMUNITY,
    ExperienceCategory.CUSTOMER_SUPPORT,
    ExperienceCategory.WORK_OPERATIONS,
)


def test_experience_categories_are_the_fixed_eight() -> None:
    assert EXPERIENCE_CATEGORIES == _EXPECTED
    assert len(set(ExperienceCategory)) == 8
    values = [c.value for c in ExperienceCategory]
    assert len(values) == len(set(values)), "experience category values must be unique"


# ── Category-rule classifications over the real connector catalog ────────────


def _category_of(family: str) -> ExperienceCategory | None:
    return experience_category_for(manifest_by_family[family])


def test_commerce_families_map_to_commerce_revenue() -> None:
    assert _category_of("shopify") == ExperienceCategory.COMMERCE_REVENUE
    assert _category_of("stripe") == ExperienceCategory.COMMERCE_REVENUE


def test_crm_families_map_to_crm_customer() -> None:
    assert _category_of("hubspot") == ExperienceCategory.CRM_CUSTOMER
    assert _category_of("salesforce") == ExperienceCategory.CRM_CUSTOMER


def test_marketing_families_map_to_communications_lifecycle() -> None:
    for family in (
        "klaviyo",
        "sendgrid",
        "customerio",
        "mailchimp",
        "postmark",
        "iterable",
        "braze",
    ):
        assert _category_of(family) == ExperienceCategory.COMMUNICATIONS_LIFECYCLE


def test_product_analytics_families_map_to_analytics_behavior() -> None:
    for family in ("segment", "posthog", "ga4", "dune"):
        assert _category_of(family) == ExperienceCategory.ANALYTICS_BEHAVIOR


def test_work_operations_families_map_to_work_operations() -> None:
    for family in ("jira", "linear", "slack"):
        assert _category_of(family) == ExperienceCategory.WORK_OPERATIONS


def test_support_families_map_to_customer_support() -> None:
    for family in ("zendesk", "intercom"):
        assert _category_of(family) == ExperienceCategory.CUSTOMER_SUPPORT


def test_generic_webhook_maps_to_analytics_behavior() -> None:
    assert _category_of("webhook") == ExperienceCategory.ANALYTICS_BEHAVIOR


def test_every_connector_classifies_or_is_none() -> None:
    for manifest in CONNECTOR_MANIFESTS:
        category = experience_category_for(manifest)
        assert category is None or isinstance(category, ExperienceCategory)


# ── Payment rails + deferred bureaus ──────────────────────────────────────────


def test_payment_rails_map_to_commerce_revenue() -> None:
    # Rails are observe-only financial connectors → Commerce & Revenue.
    for manifest in PAYMENT_RAIL_MANIFESTS:
        assert experience_category_for(manifest) == ExperienceCategory.COMMERCE_REVENUE


def test_deferred_bureaus_derive_to_none() -> None:
    # Deferred credit bureaus are tenant-hidden and scaffolded; they must not be
    # forced into a customer experience bucket.
    for manifest in DEFERRED_CREDIT_BUREAU_MANIFESTS:
        assert experience_category_for(manifest) is None


# ── Pure-function rules (product / ADR-C11 comms cohort) ─────────────────────


def test_product_ads_rule_maps_to_advertising_campaigns() -> None:
    # Any manifest with product_id="ads" (the measurement ad connectors added to
    # the unified catalog) is an advertising campaign — a product rule, not a
    # hand-synced platform list.
    sample = manifest_by_family["slack"].model_copy(
        update={"product_id": "ads", "capability_id": "metrics"}
    )
    assert experience_category_for(sample) == ExperienceCategory.ADVERTISING_CAMPAIGNS


def test_comms_output_cohort_is_the_adr_c11_derivation() -> None:
    # A manifest whose category is not itself mapped, but which declares comms.*
    # data outputs, derives to communications_lifecycle (ADR-C11 rule).
    sample = manifest_by_family["dune"].model_copy(
        update={
            "category": "custom",
            "data_outputs": ["comms.email.campaign_status"],
            "product_destinations": ["campaigns", "profile360"],
        }
    )
    assert experience_category_for(sample) == ExperienceCategory.COMMUNICATIONS_LIFECYCLE


def test_unmapped_category_derives_to_none() -> None:
    sample = manifest_by_family["dune"].model_copy(update={"category": "onchain"})
    assert experience_category_for(sample) is None


# ── Whole-catalog sweep ───────────────────────────────────────────────────────


def test_full_catalog_derives_at_most_one_category() -> None:
    for manifest in ALL_MANIFESTS:
        category = experience_category_for(manifest)
        if category is not None:
            assert isinstance(category, ExperienceCategory)
