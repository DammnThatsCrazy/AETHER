"""Boundary family alias map (ADR-0009): resolves collisions, renames nothing.

The alias map is the single place boundary id collisions are reconciled into
canonical catalog families. These tests pin that it is total over its own
entries, idempotent, chain-free, and never resolves into an alias-only family.
"""

from __future__ import annotations

from shared.integration_contracts.aliases import (
    ALIAS_ONLY_FAMILIES,
    FAMILY_ALIASES,
    canonical_family_id,
)


def test_twitter_ads_aliases_to_x_ads() -> None:
    # shared/providers/categories + recommendations emit twitter_ads; the
    # measurement runtime and campaign normalization canonical is x_ads.
    assert canonical_family_id("twitter_ads") == "x_ads"


def test_google_analytics_aliases_to_ga4() -> None:
    assert canonical_family_id("google_analytics") == "ga4"


def test_facebook_and_bing_aliases_resolve() -> None:
    assert canonical_family_id("facebook_ads") == "meta_ads"
    assert canonical_family_id("bing_ads") == "microsoft_ads"


def test_resolution_is_case_and_whitespace_tolerant() -> None:
    assert canonical_family_id("  Twitter_Ads ") == "x_ads"
    assert canonical_family_id("GOOGLE_ANALYTICS") == "ga4"


def test_unaliased_ids_pass_through() -> None:
    # Canonical runtime ids are their own canonical families.
    for token in ("google_ads", "meta_ads", "tiktok_ads", "linkedin_ads", "x_ads",
                  "reddit_ads", "microsoft_ads", "slack", "ga4"):
        assert canonical_family_id(token) == token


def test_alias_only_families_are_recognized_names() -> None:
    # snapchat_ads/pinterest_ads are canonical public names today but have no
    # backed runtime; resolution must not invent a target for them.
    for family in ALIAS_ONLY_FAMILIES:
        assert canonical_family_id(family) == family


def test_alias_targets_are_canonical_and_chain_free() -> None:
    # No alias may resolve onto another alias (no chains) or onto an alias-only
    # family (which would fabricate capability behind an unbacked name).
    for alias, target in FAMILY_ALIASES.items():
        assert canonical_family_id(target) == target, f"alias chain at {alias!r}"
        assert target not in ALIAS_ONLY_FAMILIES, (
            f"{alias!r} resolves to unbacked {target!r}"
        )


def test_alias_space_is_disjoint_from_alias_only_families() -> None:
    keys = set(FAMILY_ALIASES)
    values = set(FAMILY_ALIASES.values())
    assert keys.isdisjoint(ALIAS_ONLY_FAMILIES)
    assert values.isdisjoint(ALIAS_ONLY_FAMILIES)


def test_resolution_is_idempotent() -> None:
    for token in ("twitter_ads", "google_analytics", "facebook_ads", "bing_ads",
                  "x_ads", "slack", "snapchat_ads", ""):
        once = canonical_family_id(token)
        assert canonical_family_id(once) == once
