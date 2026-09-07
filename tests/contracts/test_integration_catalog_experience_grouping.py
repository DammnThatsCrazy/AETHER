"""Experience-grouping contract over the unified catalog (ADR-0010).

`experience_category_for` projects each manifest's canonical engineering tokens
(product_id / category / data_outputs) onto exactly ONE customer-facing
experience category so Settings→Integrations and the public directory can group
integrations under the same headings the tenant sees. Invariants pinned here:

  - the eight experience categories and their presentation order are stable;
  - every connectable manifest derives to exactly one experience, and no
    manifest ever derives to two (deterministic single-bucket rule);
  - advertising membership is derived from product_id="ads" (never a
    hand-synced platform list);
  - communications membership is derived from the comms.* output cohort plus
    the category rule (never a per-provider hardcode);
  - deferred credit bureaus derive to None (never forced into a bucket the
    manifest does not evidence), and the customer-facing catalog therefore
    lists them in no experience group.

Namespaced (test_integration_catalog_*). Spec:
docs/source-of-truth/AETHER_END_USER_LIFECYCLE.md § experience categories.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND = REPO_ROOT / "Backend Architecture" / "aether-backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from shared.integration_contracts.catalog import ALL_MANIFESTS  # noqa: E402
from shared.integration_contracts.experience import (  # noqa: E402
    EXPERIENCE_CATEGORIES,
    ExperienceCategory,
    experience_category_for,
)
from services.integrations.connectors.catalog_endpoints import (  # noqa: E402
    _experience_value,
    _visible_catalog_entries,
)

_EXPECTED_GROUPING = {
    ExperienceCategory.ADVERTISING_CAMPAIGNS: {
        "google_ads",
        "meta_ads",
        "tiktok_ads",
        "linkedin_ads",
        "x_ads",
        "reddit_ads",
        "microsoft_ads",
    },
    ExperienceCategory.COMMERCE_REVENUE: {
        "shopify",
        "stripe",  # stripe.ingestion.connector
        "privy",
        "coinbase",
        "moonpay",
        "bridge",
    },
    ExperienceCategory.CRM_CUSTOMER: {"hubspot", "salesforce"},
    ExperienceCategory.COMMUNICATIONS_LIFECYCLE: {
        "klaviyo",
        "sendgrid",
        "customerio",
        "mailchimp",
        "postmark",
        "iterable",
        "braze",
    },
    ExperienceCategory.ANALYTICS_BEHAVIOR: {"webhook", "segment", "posthog", "ga4", "dune"},
    ExperienceCategory.CUSTOMER_SUPPORT: {"zendesk", "intercom"},
    ExperienceCategory.WORK_OPERATIONS: {"slack", "jira", "linear"},
}


def test_experience_categories_are_eight_and_stable():
    assert [c.value for c in EXPERIENCE_CATEGORIES] == [
        "advertising_campaigns",
        "commerce_revenue",
        "crm_customer",
        "communications_lifecycle",
        "analytics_behavior",
        "social_community",
        "customer_support",
        "work_operations",
    ]
    assert len(set(EXPERIENCE_CATEGORIES)) == 8


def test_every_connectable_manifest_maps_to_exactly_one_bucket():
    for manifest in ALL_MANIFESTS:
        if not manifest.availability.environments.any_enabled():
            continue
        exp = experience_category_for(manifest)
        assert exp is not None, (
            f"connectable manifest {manifest.identity_key} derives to no "
            "experience category"
        )
        # Determinism: same manifest, same bucket, every call.
        assert experience_category_for(manifest) == exp


def test_deferred_credit_bureaus_derive_to_none():
    for manifest in ALL_MANIFESTS:
        if manifest.product_id == "credit":
            assert experience_category_for(manifest) is None
            assert _experience_value(manifest) is None


def test_expected_grouping_is_exact():
    """The customer grouping over ALL_MANIFESTS matches the ADR-0010 design."""
    actual: dict[ExperienceCategory, set[str]] = {
        cat: set() for cat in ExperienceCategory
    }
    for manifest in ALL_MANIFESTS:
        exp = experience_category_for(manifest)
        if exp is not None:
            actual[exp].add(manifest.provider_family)

    # social_community has no connectable family today — it must stay empty.
    assert actual[ExperienceCategory.SOCIAL_COMMUNITY] == set()

    for cat, expected_families in _EXPECTED_GROUPING.items():
        assert actual[cat] == expected_families, (
            f"experience bucket {cat.value} drifted: "
            f"actual={sorted(actual[cat])} expected={sorted(expected_families)}"
        )


def test_advertising_is_derived_not_hand_synced():
    """Every ad-platform product family lands under advertising_campaigns."""
    ad_families = {
        m.provider_family
        for m in ALL_MANIFESTS
        if m.product_id == "ads" and m.capability_id == "metrics"
    }
    assert ad_families == _EXPECTED_GROUPING[ExperienceCategory.ADVERTISING_CAMPAIGNS]


def test_communications_membership_is_cohort_derived():
    """Comms membership follows experience.py precedence, never a platform list.

    Precedence (ADR-0010): product_id rule, then category rule, then the
    ADR-C11 comms.* data-output cohort. A manifest with a more specific rule
    (e.g. hubspot, category=crm) is NOT a communications provider even if its
    data outputs touch comms.* — at most one bucket per integration.
    """
    comms_families = _EXPECTED_GROUPING[ExperienceCategory.COMMUNICATIONS_LIFECYCLE]
    product_rules = {"ads": ExperienceCategory.ADVERTISING_CAMPAIGNS}
    category_rules = {
        "commerce": ExperienceCategory.COMMERCE_REVENUE,
        "billing": ExperienceCategory.COMMERCE_REVENUE,
        "payments": ExperienceCategory.COMMERCE_REVENUE,
        "crm": ExperienceCategory.CRM_CUSTOMER,
        "marketing": ExperienceCategory.COMMUNICATIONS_LIFECYCLE,
        "ad_platform": ExperienceCategory.ADVERTISING_CAMPAIGNS,
        "product_analytics": ExperienceCategory.ANALYTICS_BEHAVIOR,
        "webhook": ExperienceCategory.ANALYTICS_BEHAVIOR,
        "project": ExperienceCategory.WORK_OPERATIONS,
        "messaging": ExperienceCategory.WORK_OPERATIONS,
        "support": ExperienceCategory.CUSTOMER_SUPPORT,
    }
    for manifest in ALL_MANIFESTS:
        has_comms_output = any(
            output.startswith("comms.") for output in manifest.data_outputs
        )
        product_rule = product_rules.get(manifest.product_id)
        category_rule = category_rules.get(manifest.category)
        if product_rule is not None:
            derived = product_rule
        elif category_rule is not None:
            derived = category_rule
        elif has_comms_output:
            derived = ExperienceCategory.COMMUNICATIONS_LIFECYCLE
        else:
            derived = None

        actual = experience_category_for(manifest)
        assert actual == derived, (
            f"{manifest.identity_key} classification {actual} != precedence-derived "
            f"{derived} (product={manifest.product_id!r} category={manifest.category!r} "
            f"has_comms_output={has_comms_output})"
        )
        assert (
            manifest.provider_family in comms_families
        ) == (derived == ExperienceCategory.COMMUNICATIONS_LIFECYCLE), (
            f"{manifest.identity_key} comms membership inconsistent with precedence"
        )


def test_visible_catalog_entries_expose_experience_grouping():
    """The read model carries the experience token + canonical order."""
    visible = _visible_catalog_entries()
    experience_values = {e["experience_category"] for e in visible}
    # No None in the visible (connectable) catalog.
    assert None not in experience_values
    presented = {e["experience_category"] for e in visible}
    assert presented == {
        c.value for c in ExperienceCategory if c is not ExperienceCategory.SOCIAL_COMMUNITY
    }
    # Presentation sort key = experience order (unclassified would sort last).
    order = [c.value for c in EXPERIENCE_CATEGORIES]
    sorts = [order.index(e["experience_category"]) for e in visible]
    assert sorts == sorted(sorts)


def test_experience_category_tokens_are_lowercase_snake():
    for cat in ExperienceCategory:
        assert cat.value == cat.value.lower()
        assert "_" in cat.value and " " not in cat.value
