"""Ad-platform account identity + live credential probe (additive, WS-2).

The measurement ad connectors all target *one* account per platform, but each
module reads that account from a differently-named config key (Google Ads calls
it ``customer_id``, Meta ``ad_account_id``, TikTok ``advertiser_id``, and the
rest ``account_id``). The unified catalog
(``shared/integration_contracts/catalog.py``) marks the same field as the
non-secret identifier in each family's credential schema, and each connector
module surfaces it as ``external_account_id`` on every spend record.

Ad platforms have **no account discovery** — their catalog manifests carry
``accounts=Accounts()`` with ``discovery_supported=False`` — so a connected
source represents exactly one manually-entered account. This module owns:

* the canonical set of measurement-backed ad families (the 7 catalog families
  that have a runtime connector module);
* the config key each family uses to identify its single account;
* lazy connector-class loading for live credential tests.

Import-cycle law: this module lives in the measurement ``connectors`` package,
so it never top-level imports ``shared/certification``/``readiness`` or
``integration_contracts.catalog``. Connector modules are loaded lazily, only
when a credential probe actually runs. The account-field map here is kept
consistent with the catalog schema and the connector modules by honesty tests
in the campaign ad-source orchestration suite (WS-2).
"""

from __future__ import annotations

import importlib
from typing import Any, Mapping, Optional

# Canonical ad families that have a measurement runtime behind them. Mirrors
# ``catalog.AD_FAMILIES`` order for a stable surface; a family named by the
# public vocabulary but with NO runtime (snapchat_ads / pinterest_ads) is
# deliberately absent so surfaces never claim capability behind it.
AD_ACCOUNT_FAMILIES: tuple[str, ...] = (
    "google_ads",
    "meta_ads",
    "tiktok_ads",
    "linkedin_ads",
    "x_ads",
    "reddit_ads",
    "microsoft_ads",
)

# The single config key each ad connector reads as its account identifier, and
# surfaces as ``external_account_id`` on spend records. Cross-checked against
# the catalog credential schema (identifier fields) and each connector module's
# account extraction by the WS-2 account-field honesty tests.
AD_FAMILY_ACCOUNT_FIELD: Mapping[str, str] = {
    # google_ads.py: account_id = config["customer_id"] (Google Ads customer ID)
    "google_ads": "customer_id",
    # meta_ads.py: account_id = config["ad_account_id"] (act_<id>)
    "meta_ads": "ad_account_id",
    # tiktok_ads.py: account_id = config["advertiser_id"]
    "tiktok_ads": "advertiser_id",
    # linkedin_ads.py: ad_account_id = config["ad_account_id"]
    "linkedin_ads": "ad_account_id",
    # x_ads.py: account_id = config["account_id"]
    "x_ads": "account_id",
    # reddit_ads.py: account_id = config["account_id"]
    "reddit_ads": "account_id",
    # microsoft_ads.py: account_id = config["account_id"]
    "microsoft_ads": "account_id",
}

# module basename + connector class per family, for lazy importlib loading.
_AD_FAMILY_MODULE: Mapping[str, str] = {
    "google_ads": "google_ads",
    "meta_ads": "meta_ads",
    "tiktok_ads": "tiktok_ads",
    "linkedin_ads": "linkedin_ads",
    "x_ads": "x_ads",
    "reddit_ads": "reddit_ads",
    "microsoft_ads": "microsoft_ads",
}

_AD_FAMILY_CLASS: Mapping[str, str] = {
    "google_ads": "GoogleAdsConnector",
    "meta_ads": "MetaAdsConnector",
    "tiktok_ads": "TikTokAdsConnector",
    "linkedin_ads": "LinkedInAdsConnector",
    "x_ads": "XAdsConnector",
    "reddit_ads": "RedditAdsConnector",
    "microsoft_ads": "MicrosoftAdsConnector",
}

# Deterministic placeholder identities for a credential probe. Probes never
# persist, so these never touch a tenant's id-space.
_PROBE_CONNECTOR_ID = "credential-probe"
_PROBE_TENANT_ID = "credential-probe"


def is_ad_account_family(family: Optional[str]) -> bool:
    """True when ``family`` is a measurement-backed ad platform family."""
    return bool(family) and family in AD_ACCOUNT_FAMILIES


def account_field_for(family: Optional[str]) -> Optional[str]:
    """Return the config key ``family`` uses for its single account.

    ``None`` for an unknown/unbacked family so callers never guess a field.
    """
    if not family:
        return None
    return AD_FAMILY_ACCOUNT_FIELD.get(family)


def account_value_for(family: Optional[str], config: Optional[Mapping[str, Any]]) -> Optional[str]:
    """Return the configured account identifier for ``family``, if present.

    The account id is a non-secret identifier; it may be surfaced to operators
    (it is what the connector writes as ``external_account_id``).
    """
    field = account_field_for(family)
    if not field or not config:
        return None
    value = config.get(field)
    if value is None or value == "":
        return None
    return str(value)


async def run_credential_test(family: str, config: Mapping[str, Any]) -> dict[str, Any]:
    """Run the family's own connector credential probe against ``config``.

    Returns the connector's *truth* — it never fabricates a pass and never
    persists anything. A family that has no runtime (snapchat_ads etc.) or an
    unknown id raises ``ValueError`` so the caller surfaces a clear rejection
    instead of silently probing nothing.

    Result keys:
      ``family``          — canonical family probed
      ``account_field``   — config key used as the account identifier
      ``account_value``   — the (non-secret) account identifier supplied
      ``valid``           — bool, from the connector's own validate_credentials
      ``status_message``  — connector health message (truncated, safe)
    """
    if not is_ad_account_family(family):
        raise ValueError(
            f"{family!r} is not a measurement-backed ad platform family; "
            "cannot run a credential probe"
        )

    module_name = _AD_FAMILY_MODULE[family]
    class_name = _AD_FAMILY_CLASS[family]
    module = importlib.import_module(f"services.measurement.connectors.{module_name}")
    connector_cls = getattr(module, class_name)

    connector = connector_cls(
        connector_id=_PROBE_CONNECTOR_ID,
        tenant_id=_PROBE_TENANT_ID,
        config=dict(config or {}),
        cursor_state={},
    )

    try:
        cred_valid = await connector.validate_credentials()
        health = await connector.health_check()
        message = health.status_message if health is not None else None
        valid = bool(cred_valid)
    except Exception as exc:  # connector probes must never 500 the caller
        valid = False
        message = f"Credential probe failed: {exc}"

    return {
        "family": family,
        "account_field": account_field_for(family),
        "account_value": account_value_for(family, config),
        "valid": valid,
        "status_message": (message or "")[:300],
    }


__all__ = [
    "AD_ACCOUNT_FAMILIES",
    "AD_FAMILY_ACCOUNT_FIELD",
    "account_field_for",
    "account_value_for",
    "is_ad_account_family",
    "run_credential_test",
]
