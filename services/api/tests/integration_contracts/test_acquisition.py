"""Acquisition context and provider account contracts."""

from __future__ import annotations

import pytest

from shared.credentials.types import ApiKeyCredential, SecretStr
from shared.integration_contracts.acquisition import AcquisitionContext, ProviderAccount


# ── AcquisitionContext ──────────────────────────────────────────────────────


def test_acquisition_context_requires_core_fields() -> None:
    ctx = AcquisitionContext(tenant_id="t1", provider_identity="shopify.admin.orders_read")
    assert ctx.tenant_id == "t1"
    assert ctx.provider_identity == "shopify.admin.orders_read"
    assert ctx.connection_id == ""
    assert ctx.account_id == ""
    assert ctx.config == {}
    assert ctx.credential is None


def test_acquisition_context_carries_config_and_credential() -> None:
    cred = ApiKeyCredential(api_key=SecretStr("secret"))
    ctx = AcquisitionContext(
        tenant_id="t1",
        provider_identity="shopify.admin.orders_read",
        connection_id="c1",
        account_id="a1",
        config={"shop_domain": "acme.myshopify.com"},
        credential=cred,
    )
    assert ctx.config["shop_domain"] == "acme.myshopify.com"
    assert ctx.credential == cred


def test_acquisition_context_forbids_unknown_fields() -> None:
    with pytest.raises(Exception):
        AcquisitionContext(  # type: ignore[call-arg]
            tenant_id="t1",
            provider_identity="shopify.admin.orders_read",
            unexpected_field="boom",
        )


def test_acquisition_context_accepts_structured_credential_dict() -> None:
    # The discriminated union is validated: a malformed credential is rejected.
    ctx = AcquisitionContext(
        tenant_id="t1",
        provider_identity="shopify.admin.orders_read",
        credential={"type": "api_key", "api_key": "inert-test-value"},
    )
    assert ctx.credential is not None
    assert ctx.credential.type == "api_key"


def test_acquisition_context_rejects_malformed_credential() -> None:
    with pytest.raises(Exception):
        AcquisitionContext(
            tenant_id="t1",
            provider_identity="shopify.admin.orders_read",
            credential={"type": "api_key"},  # missing api_key
        )


# ── ProviderAccount ─────────────────────────────────────────────────────────


def test_provider_account_defaults() -> None:
    a = ProviderAccount(account_id="a1")
    assert a.display_name == ""
    assert a.external_id is None
    assert a.currency is None
    assert a.region is None
    assert a.metadata == {}


def test_provider_account_allows_unknown_fields() -> None:
    # extra="allow" is deliberate: provider-specific fields are preserved.
    a = ProviderAccount(account_id="a1", display_name="Main", timezone="UTC", owner="team")
    assert a.timezone == "UTC"
    assert a.owner == "team"


def test_provider_account_requires_account_id() -> None:
    with pytest.raises(Exception):
        ProviderAccount()  # type: ignore[call-arg]


def test_provider_accounts_preserve_distinct_currencies() -> None:
    # A multi-currency provider: each account keeps its own currency; no cross
    # or defaulted currency can collapse two distinct accounts together.
    usd = ProviderAccount(account_id="a1", currency="USD")
    eur = ProviderAccount(account_id="a2", currency="EUR")
    none_ccy = ProviderAccount(account_id="a3")
    assert usd.currency == "USD"
    assert eur.currency == "EUR"
    assert none_ccy.currency is None
    assert usd != eur
    assert usd != none_ccy
    assert {usd.currency, eur.currency} == {"USD", "EUR"}
