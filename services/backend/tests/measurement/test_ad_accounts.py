"""WS-2 ad-platform account-identity honesty tests (measurement layer).

The account-field map in ``services/measurement/connectors/ad_accounts.py`` is
the campaign-side truth for which config key each ad family uses as its single
account. These tests keep it honest against the unified catalog: every backed
family's account field must exist in its catalog credential schema as a
non-secret identifier, the backed family set must not drift from
``catalog.AD_FAMILIES``, and unbacked / alias-only families must never resolve
to an account field or a credential probe.
"""
from __future__ import annotations

import pytest

from services.measurement.connectors.ad_accounts import (
    AD_ACCOUNT_FAMILIES,
    AD_FAMILY_ACCOUNT_FIELD,
    account_field_for,
    account_value_for,
    is_ad_account_family,
    run_credential_test,
)


def test_backed_family_set_matches_catalog_ad_families() -> None:
    """The 7 measurement-backed families must equal the catalog AD_FAMILIES.

    A family added to the catalog without a runtime (or vice versa) would let a
    connect surface claim a platform that cannot actually sync spend — the exact
    drift this map exists to catch.
    """
    from shared.integration_contracts.catalog import AD_FAMILIES

    assert AD_ACCOUNT_FAMILIES == AD_FAMILIES
    assert len(AD_ACCOUNT_FAMILIES) == 7
    assert len(AD_FAMILY_ACCOUNT_FIELD) == len(AD_ACCOUNT_FAMILIES)


@pytest.mark.parametrize("family", AD_ACCOUNT_FAMILIES)
def test_account_field_is_catalog_non_secret_identifier(family: str) -> None:
    """Each family's account field must be a field in its catalog schema.

    The account id is written to every spend record as ``external_account_id``,
    so the map must agree with the catalog schema (the platform's identity
    vocabulary) — never a private guess.
    """
    from shared.integration_contracts.catalog import manifest_from_ad_platform

    field = account_field_for(family)
    assert field, f"{family} is missing an account field mapping"
    assert is_ad_account_family(family) is True

    schema = manifest_from_ad_platform(family).authentication.credential_schema
    by_name = {spec.name: spec for spec in schema}
    assert field in by_name, (
        f"{family} account field {field!r} is not in its catalog credential schema"
    )
    assert by_name[field].secret is False, (
        f"{family} account field {field!r} is marked secret in the catalog — "
        "account ids are non-secret identifiers"
    )


def test_unbacked_and_unknown_families_never_resolve_to_an_account() -> None:
    """Alias-only (snapchat/pinterest) and unknown ids must not map to a field."""
    from shared.integration_contracts.aliases import ALIAS_ONLY_FAMILIES

    for raw in ("snapchat_ads", "pinterest_ads", "nonsense", "google_analytics"):
        assert is_ad_account_family(raw) is False, raw
        assert account_field_for(raw) is None, raw

    assert ALIAS_ONLY_FAMILIES.isdisjoint(set(AD_ACCOUNT_FAMILIES))


@pytest.mark.asyncio
async def test_credential_probe_rejects_unbacked_family_without_loading_connector() -> None:
    """A probe for a platform with no runtime must raise, not probe nothing."""
    for raw in ("snapchat_ads", "pinterest_ads", "definitely-not-a-family"):
        with pytest.raises(ValueError, match="not a measurement-backed ad platform"):
            await run_credential_test(raw, {})


def test_account_value_extraction() -> None:
    """account_value_for reads the family's single account id from config."""
    assert account_value_for("x_ads", {"account_id": "user-x-1"}) == "user-x-1"
    assert account_value_for("google_ads", {"customer_id": "123-456"}) == "123-456"
    assert account_value_for("meta_ads", {"ad_account_id": "act_1"}) == "act_1"
    # Blank / missing / unknown family → None (never a fabricated account).
    assert account_value_for("meta_ads", {"ad_account_id": ""}) is None
    assert account_value_for("meta_ads", {}) is None
    assert account_value_for("snapchat_ads", {"account_id": "x"}) is None
