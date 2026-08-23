"""Legacy SSRF hardening tests (WS8) — Team F.

The pre-existing inbound connector adapters built tenant-supplied URLs directly
and handed them to ``_http_get`` / ``_http_post`` with no validation. This
suite verifies that every legacy site now validates the tenant-supplied host
against an allowlist suffix contract (via ``validated_https_host``) BEFORE any
URL is built:

* (a) a denied host returns the connector's existing failure shape and NEVER
  reaches the HTTP helper;
* (b) a valid allowlisted host still works and reaches the HTTP helper with a
  URL whose host equals the allowlisted host.

Error text is ``safe_message`` only — the raw host/domain value and any
credential are never echoed back.
"""
from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock
from urllib.parse import urlparse

import pytest

from services.integrations.connectors import adapters
from services.integrations.connectors import registry as registry_mod
from services.integrations.connectors.adapters import (
    ALL_CONNECTORS,
    ConnectorPullDeniedError,
    DuneConnector,
    JiraConnector,
    PostHogConnector,
    SalesforceConnector,
    ShopifyConnector,
    ZendeskConnector,
)
from services.integrations.connectors.base import ConnectorConfig
from services.integrations.connectors.braze import BrazeConnector
from services.integrations.connectors.registry import (
    get_connector,
    is_retired,
    list_descriptors,
    retire_connector_type,
)


def _cfg(connector_type: str, config: dict[str, Any]) -> ConnectorConfig:
    return ConnectorConfig(
        tenant_id="t1",
        connector_type=connector_type,  # type: ignore[arg-type]
        enabled=True,
        secret_configured=True,
        config=config,
    )


def _host_of(url: str) -> str:
    return urlparse(url).hostname or ""


@pytest.fixture(autouse=True)
def _reset_retirement_ledger():
    """The retirement ledger is module-global; clear it before AND after each
    test so registry-resolution tests (F-3) are deterministic and never leak a
    retirement into another test module's registry assertions."""
    registry_mod._RETIRED_AT.clear()
    yield
    registry_mod._RETIRED_AT.clear()


def _fresh_registry_state() -> dict[str, Any]:
    """A fresh registry state (never the shared module global) for the F-3
    retire-consumption tests."""
    return {c.connector_type: c() for c in ALL_CONNECTORS}


# ── Shopify — shop_domain is a bare `*.myshopify.com` hostname ─────────────

SHOPIFY_MALICIOUS_SHOP = [
    "127.0.0.1",
    "169.254.169.254",
    "10.0.0.1",
    "192.168.1.1",
    "172.16.0.1",
    "::1",
    "http://shop.example.com",   # wrong scheme (only https is accepted)
    "attacker.com",              # not on the allowlist
    "evilmyshopify.com",         # label boundary: sibling, not a subdomain
    "myshopify.com.evil.com",    # trailing labels are not on the allowlist
]
SHOPIFY_VALID_SHOP = "testshop.myshopify.com"


@pytest.mark.asyncio
@pytest.mark.parametrize("shop", SHOPIFY_MALICIOUS_SHOP)
async def test_shopify_test_connection_rejects_malicious_shop(monkeypatch, shop: str) -> None:
    get = AsyncMock(return_value=(200, {"shop": {"name": "x"}}))
    monkeypatch.setattr(adapters, "_http_get", get)
    conn = ShopifyConnector()
    result = await conn.test_connection(_cfg("shopify", {"shop_domain": shop}), secret="secret")
    assert not result.ok
    assert result.status == "error"
    assert "shopify" in result.detail
    assert "invalid shop URL" in result.detail
    assert shop not in result.detail  # safe_message only, never the raw host
    assert get.await_count == 0


@pytest.mark.asyncio
async def test_shopify_test_connection_accepts_valid_shop(monkeypatch) -> None:
    get = AsyncMock(return_value=(200, {"shop": {"name": "Test Shop"}}))
    monkeypatch.setattr(adapters, "_http_get", get)
    conn = ShopifyConnector()
    result = await conn.test_connection(_cfg("shopify", {"shop_domain": SHOPIFY_VALID_SHOP}), secret="secret")
    assert result.ok
    get.assert_awaited_once()
    assert _host_of(get.await_args.args[0]) == SHOPIFY_VALID_SHOP


@pytest.mark.asyncio
@pytest.mark.parametrize("shop", SHOPIFY_MALICIOUS_SHOP)
async def test_shopify_pull_rejects_malicious_shop(monkeypatch, shop: str) -> None:
    get = AsyncMock(return_value=(200, {"orders": []}))
    monkeypatch.setattr(adapters, "_http_get", get)
    conn = ShopifyConnector()
    # F-4: a denied host in a pull path is a TYPED failure (never a silent []).
    with pytest.raises(ConnectorPullDeniedError) as excinfo:
        await conn.pull(_cfg("shopify", {"shop_domain": shop}), secret="secret")
    assert "shopify" in excinfo.value.safe_message
    assert shop not in excinfo.value.safe_message  # safe_message only, never raw host
    assert shop not in str(excinfo.value)
    assert get.await_count == 0


@pytest.mark.asyncio
async def test_shopify_pull_accepts_valid_shop(monkeypatch) -> None:
    get = AsyncMock(return_value=(200, {"orders": [
        {"id": 1, "updated_at": "2024-01-01T00:00:00Z", "email": "a@b.com",
         "total_price": "9.99", "financial_status": "paid"},
    ]}))
    monkeypatch.setattr(adapters, "_http_get", get)
    conn = ShopifyConnector()
    events = await conn.pull(_cfg("shopify", {"shop_domain": SHOPIFY_VALID_SHOP}), secret="secret")
    assert len(events) == 1
    assert events[0].source == "shopify"
    get.assert_awaited_once()
    assert _host_of(get.await_args.args[0]) == SHOPIFY_VALID_SHOP


# ── Salesforce — instance_url must resolve to *.salesforce.com / *.force.com ─

SALESFORCE_MALICIOUS_INSTANCE = [
    "http://127.0.0.1",
    "http://169.254.169.254",
    "http://10.0.0.1",
    "http://192.168.1.1",
    "http://172.16.0.1",
    "https://[::1]",
    "127.0.0.1",
    "https://acme.salesforce.com.evil.com",
    "https://attacker.com",
]
SALESFORCE_VALID_INSTANCE = "https://acme.my.salesforce.com"
SALESFORCE_VALID_HOST = "acme.my.salesforce.com"


@pytest.mark.asyncio
@pytest.mark.parametrize("instance", SALESFORCE_MALICIOUS_INSTANCE)
async def test_salesforce_test_connection_rejects_malicious_instance(monkeypatch, instance: str) -> None:
    get = AsyncMock(return_value=(200, {}))
    monkeypatch.setattr(adapters, "_http_get", get)
    conn = SalesforceConnector()
    result = await conn.test_connection(_cfg("salesforce", {"instance_url": instance}), secret="secret")
    assert not result.ok
    assert result.status == "error"
    assert "salesforce" in result.detail
    assert "invalid instance_url URL" in result.detail
    assert instance not in result.detail
    assert get.await_count == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("instance", [SALESFORCE_VALID_INSTANCE, SALESFORCE_VALID_HOST])
async def test_salesforce_test_connection_accepts_valid_instance(monkeypatch, instance: str) -> None:
    get = AsyncMock(return_value=(200, {}))
    monkeypatch.setattr(adapters, "_http_get", get)
    conn = SalesforceConnector()
    result = await conn.test_connection(_cfg("salesforce", {"instance_url": instance}), secret="secret")
    assert result.ok
    get.assert_awaited_once()
    assert _host_of(get.await_args.args[0]) == SALESFORCE_VALID_HOST


@pytest.mark.asyncio
async def test_salesforce_test_connection_preserves_missing_instance_url_path(monkeypatch) -> None:
    get = AsyncMock(return_value=(200, {}))
    monkeypatch.setattr(adapters, "_http_get", get)
    conn = SalesforceConnector()
    result = await conn.test_connection(_cfg("salesforce", {}), secret="secret")
    assert not result.ok
    assert result.status == "error"
    assert result.detail == "instance_url missing from config"
    assert get.await_count == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("instance", SALESFORCE_MALICIOUS_INSTANCE)
async def test_salesforce_pull_rejects_malicious_instance(monkeypatch, instance: str) -> None:
    get = AsyncMock(return_value=(200, {"records": []}))
    monkeypatch.setattr(adapters, "_http_get", get)
    conn = SalesforceConnector()
    # F-4: a denied host in a pull path is a TYPED failure (never a silent []).
    with pytest.raises(ConnectorPullDeniedError) as excinfo:
        await conn.pull(_cfg("salesforce", {"instance_url": instance}), secret="secret")
    assert "salesforce" in excinfo.value.safe_message
    assert instance not in excinfo.value.safe_message
    assert instance not in str(excinfo.value)
    assert get.await_count == 0


@pytest.mark.asyncio
async def test_salesforce_pull_accepts_valid_instance(monkeypatch) -> None:
    get = AsyncMock(return_value=(200, {"records": [
        {"Id": "1", "Email": "a@b.com", "Company": "ACME"},
    ]}))
    monkeypatch.setattr(adapters, "_http_get", get)
    conn = SalesforceConnector()
    events = await conn.pull(_cfg("salesforce", {"instance_url": SALESFORCE_VALID_INSTANCE}), secret="secret")
    assert len(events) == 1
    assert events[0].source == "salesforce"
    get.assert_awaited_once()
    assert _host_of(get.await_args.args[0]) == SALESFORCE_VALID_HOST


# ── PostHog — host must be *.posthog.com (default https://app.posthog.com) ──

POSTHOG_MALICIOUS_HOST = [
    "127.0.0.1",
    "169.254.169.254",
    "http://app.posthog.com",          # wrong scheme
    "https://app.posthog.com.evil.com",
    "https://attacker.com",
]
POSTHOG_VALID_HOST = "app.posthog.com"


@pytest.mark.asyncio
@pytest.mark.parametrize("host", POSTHOG_MALICIOUS_HOST)
async def test_posthog_test_connection_rejects_malicious_host(monkeypatch, host: str) -> None:
    get = AsyncMock(return_value=(200, {}))
    monkeypatch.setattr(adapters, "_http_get", get)
    conn = PostHogConnector()
    result = await conn.test_connection(_cfg("posthog", {"host": host}), secret="secret")
    assert not result.ok
    assert result.status == "error"
    assert "posthog" in result.detail
    assert "invalid host URL" in result.detail
    assert host not in result.detail
    assert get.await_count == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("host", ["https://app.posthog.com", POSTHOG_VALID_HOST])
async def test_posthog_test_connection_accepts_valid_host(monkeypatch, host: str) -> None:
    get = AsyncMock(return_value=(200, {}))
    monkeypatch.setattr(adapters, "_http_get", get)
    conn = PostHogConnector()
    result = await conn.test_connection(_cfg("posthog", {"host": host}), secret="secret")
    assert result.ok
    get.assert_awaited_once()
    assert _host_of(get.await_args.args[0]) == POSTHOG_VALID_HOST


@pytest.mark.asyncio
async def test_posthog_default_host_is_validated_and_hits_app_posthog(monkeypatch) -> None:
    get = AsyncMock(return_value=(200, {}))
    monkeypatch.setattr(adapters, "_http_get", get)
    conn = PostHogConnector()
    # No `host` key: the connector falls back to its default and must still
    # pass the allowlist gate.
    result = await conn.test_connection(_cfg("posthog", {}), secret="secret")
    assert result.ok
    get.assert_awaited_once()
    assert _host_of(get.await_args.args[0]) == POSTHOG_VALID_HOST


@pytest.mark.asyncio
@pytest.mark.parametrize("host", POSTHOG_MALICIOUS_HOST)
async def test_posthog_pull_rejects_malicious_host(monkeypatch, host: str) -> None:
    get = AsyncMock(return_value=(200, {"results": []}))
    monkeypatch.setattr(adapters, "_http_get", get)
    conn = PostHogConnector()
    # F-4: a denied host in a pull path is a TYPED failure (never a silent []).
    with pytest.raises(ConnectorPullDeniedError) as excinfo:
        await conn.pull(
            _cfg("posthog", {"host": host, "project_id": "prj1"}), secret="secret"
        )
    assert "posthog" in excinfo.value.safe_message
    assert host not in excinfo.value.safe_message
    assert host not in str(excinfo.value)
    assert get.await_count == 0


@pytest.mark.asyncio
async def test_posthog_pull_accepts_valid_host(monkeypatch) -> None:
    get = AsyncMock(return_value=(200, {"results": [
        {"id": "p1", "created_at": "2024-01-01T00:00:00Z",
         "distinct_ids": ["d1"], "properties": {}},
    ]}))
    monkeypatch.setattr(adapters, "_http_get", get)
    conn = PostHogConnector()
    events = await conn.pull(
        _cfg("posthog", {"host": "https://app.posthog.com", "project_id": "prj1"}), secret="secret"
    )
    assert len(events) == 1
    assert events[0].source == "posthog"
    get.assert_awaited_once()
    assert _host_of(get.await_args.args[0]) == POSTHOG_VALID_HOST


# ── Jira — domain builds https://<domain>.atlassian.net ────────────────────
# A bare malicious IP is NOT rejected here by itself: the CONSTRUCTED host is
# `<domain>.atlassian.net`, which is a genuine subdomain of an allowlisted
# domain (resolves to Atlassian infra, not an SSRF). The cases below are the
# ones that break URL construction (scheme / userinfo / port / path injection)
# and must fail closed.

JIRA_MALICIOUS_DOMAIN = [
    "https://127.0.0.1",          # scheme injection
    "https://169.254.169.254",    # scheme injection
    "https://attacker.com",       # scheme injection
    "evil.com@127.0.0.1",         # userinfo injection
    "127.0.0.1:8443",             # port injection
    "a/b",                        # path injection
]
JIRA_VALID_DOMAIN = "acme"
JIRA_VALID_HOST = "acme.atlassian.net"


@pytest.mark.asyncio
@pytest.mark.parametrize("domain", JIRA_MALICIOUS_DOMAIN)
async def test_jira_test_connection_rejects_malicious_domain(monkeypatch, domain: str) -> None:
    get = AsyncMock(return_value=(200, {"displayName": "Ada"}))
    monkeypatch.setattr(adapters, "_http_get", get)
    conn = JiraConnector()
    result = await conn.test_connection(_cfg("jira", {"domain": domain}), secret="secret")
    assert not result.ok
    assert result.status == "error"
    assert "jira" in result.detail
    assert "invalid domain URL" in result.detail
    assert domain not in result.detail
    assert get.await_count == 0


@pytest.mark.asyncio
async def test_jira_test_connection_accepts_valid_domain(monkeypatch) -> None:
    get = AsyncMock(return_value=(200, {"displayName": "Ada"}))
    monkeypatch.setattr(adapters, "_http_get", get)
    conn = JiraConnector()
    result = await conn.test_connection(
        _cfg("jira", {"domain": JIRA_VALID_DOMAIN, "user_email": "ada@example.com"}), secret="secret"
    )
    assert result.ok
    get.assert_awaited_once()
    assert _host_of(get.await_args.args[0]) == JIRA_VALID_HOST


@pytest.mark.asyncio
@pytest.mark.parametrize("domain", JIRA_MALICIOUS_DOMAIN)
async def test_jira_pull_rejects_malicious_domain(monkeypatch, domain: str) -> None:
    get = AsyncMock(return_value=(200, {"issues": []}))
    monkeypatch.setattr(adapters, "_http_get", get)
    conn = JiraConnector()
    # F-4: a denied host in a pull path is a TYPED failure (never a silent []).
    with pytest.raises(ConnectorPullDeniedError) as excinfo:
        await conn.pull(_cfg("jira", {"domain": domain}), secret="secret")
    assert "jira" in excinfo.value.safe_message
    assert domain not in excinfo.value.safe_message
    assert domain not in str(excinfo.value)
    assert get.await_count == 0


@pytest.mark.asyncio
async def test_jira_pull_accepts_valid_domain(monkeypatch) -> None:
    get = AsyncMock(return_value=(200, {"issues": [
        {"id": "1", "key": "ACME-1",
         "fields": {"summary": "s", "updated": "2024-01-01T00:00:00Z",
                    "status": {"name": "Open"}}},
    ]}))
    monkeypatch.setattr(adapters, "_http_get", get)
    conn = JiraConnector()
    events = await conn.pull(
        _cfg("jira", {"domain": JIRA_VALID_DOMAIN, "user_email": "ada@example.com"}), secret="secret"
    )
    assert len(events) == 1
    assert events[0].source == "jira"
    get.assert_awaited_once()
    assert _host_of(get.await_args.args[0]) == JIRA_VALID_HOST


# ── Zendesk — domain builds https://<domain>.zendesk.com ───────────────────

ZENDESK_MALICIOUS_DOMAIN = [
    "https://127.0.0.1",
    "https://attacker.com",
    "evil.com@127.0.0.1",
    "127.0.0.1:8443",
    "a/b",
]
ZENDESK_VALID_DOMAIN = "acme"
ZENDESK_VALID_HOST = "acme.zendesk.com"


@pytest.mark.asyncio
@pytest.mark.parametrize("domain", ZENDESK_MALICIOUS_DOMAIN)
async def test_zendesk_test_connection_rejects_malicious_domain(monkeypatch, domain: str) -> None:
    get = AsyncMock(return_value=(200, {"user": {"name": "Ada"}}))
    monkeypatch.setattr(adapters, "_http_get", get)
    conn = ZendeskConnector()
    result = await conn.test_connection(_cfg("zendesk", {"domain": domain}), secret="secret")
    assert not result.ok
    assert result.status == "error"
    assert "zendesk" in result.detail
    assert "invalid domain URL" in result.detail
    assert domain not in result.detail
    assert get.await_count == 0


@pytest.mark.asyncio
async def test_zendesk_test_connection_accepts_valid_domain(monkeypatch) -> None:
    get = AsyncMock(return_value=(200, {"user": {"name": "Ada"}}))
    monkeypatch.setattr(adapters, "_http_get", get)
    conn = ZendeskConnector()
    result = await conn.test_connection(_cfg("zendesk", {"domain": ZENDESK_VALID_DOMAIN}), secret="secret")
    assert result.ok
    get.assert_awaited_once()
    assert _host_of(get.await_args.args[0]) == ZENDESK_VALID_HOST


@pytest.mark.asyncio
@pytest.mark.parametrize("domain", ZENDESK_MALICIOUS_DOMAIN)
async def test_zendesk_pull_rejects_malicious_domain(monkeypatch, domain: str) -> None:
    get = AsyncMock(return_value=(200, {"tickets": []}))
    monkeypatch.setattr(adapters, "_http_get", get)
    conn = ZendeskConnector()
    # F-4: a denied host in a pull path is a TYPED failure (never a silent []).
    with pytest.raises(ConnectorPullDeniedError) as excinfo:
        await conn.pull(_cfg("zendesk", {"domain": domain}), secret="secret")
    assert "zendesk" in excinfo.value.safe_message
    assert domain not in excinfo.value.safe_message
    assert domain not in str(excinfo.value)
    assert get.await_count == 0


@pytest.mark.asyncio
async def test_zendesk_pull_accepts_valid_domain(monkeypatch) -> None:
    get = AsyncMock(return_value=(200, {"tickets": [
        {"id": "1", "subject": "s", "status": "open", "priority": "high",
         "updated_at": "2024-01-01T00:00:00Z"},
    ]}))
    monkeypatch.setattr(adapters, "_http_get", get)
    conn = ZendeskConnector()
    events = await conn.pull(_cfg("zendesk", {"domain": ZENDESK_VALID_DOMAIN}), secret="secret")
    assert len(events) == 1
    assert events[0].source == "zendesk"
    get.assert_awaited_once()
    assert _host_of(get.await_args.args[0]) == ZENDESK_VALID_HOST


# ── Dune — host is FIXED (https://api.dune.com) ────────────────────────────
# `query_id` / `execution_id` only ever reach the PATH, so they cannot move
# the host off the allowlist. The gate is still enforced before every HTTP
# call; the deny path is exercised by forcing the validator to fail closed.

DUNE_VALID_HOST = "api.dune.com"


@pytest.mark.asyncio
async def test_dune_test_connection_fails_closed_when_host_denied(monkeypatch) -> None:
    seen: list[str] = []

    def _deny(url: str, **kwargs: Any) -> None:
        seen.append(url)
        return None

    monkeypatch.setattr(adapters, "validated_https_host", _deny)
    get = AsyncMock(return_value=(200, {"username": "dune-user"}))
    monkeypatch.setattr(adapters, "_http_get", get)
    conn = DuneConnector()
    result = await conn.test_connection(_cfg("dune", {}), secret="secret")
    assert not result.ok
    assert result.status == "error"
    assert "dune" in result.detail
    assert "invalid query URL" in result.detail
    assert seen  # the gate ran before any HTTP
    assert get.await_count == 0


@pytest.mark.asyncio
async def test_dune_test_connection_accepts_fixed_host(monkeypatch) -> None:
    get = AsyncMock(return_value=(200, {"username": "dune-user"}))
    monkeypatch.setattr(adapters, "_http_get", get)
    conn = DuneConnector()
    result = await conn.test_connection(_cfg("dune", {}), secret="secret")
    assert result.ok
    get.assert_awaited_once()
    assert _host_of(get.await_args.args[0]) == DUNE_VALID_HOST


@pytest.mark.asyncio
async def test_dune_pull_fails_closed_when_host_denied(monkeypatch) -> None:
    seen: list[str] = []

    def _deny(url: str, **kwargs: Any) -> None:
        seen.append(url)
        return None

    monkeypatch.setattr(adapters, "validated_https_host", _deny)
    post = AsyncMock(return_value=(200, {"execution_id": "e1"}))
    monkeypatch.setattr(adapters, "_http_post", post)
    conn = DuneConnector()
    # F-4: a denied host in a pull path is a TYPED failure (never a silent []).
    with pytest.raises(ConnectorPullDeniedError) as excinfo:
        await conn.pull(_cfg("dune", {"query_ids": ["1"]}), secret="secret")
    assert seen  # the gate ran before any HTTP
    assert "dune" in excinfo.value.safe_message
    assert post.await_count == 0


@pytest.mark.asyncio
async def test_dune_pull_accepts_fixed_host(monkeypatch) -> None:
    post = AsyncMock(return_value=(200, {"execution_id": "e1"}))
    get = AsyncMock(return_value=(200, {"result": {"rows": [{"a": 1}]}}))
    monkeypatch.setattr(adapters, "_http_post", post)
    monkeypatch.setattr(adapters, "_http_get", get)
    conn = DuneConnector()
    events = await conn.pull(_cfg("dune", {"query_ids": ["1"]}), secret="secret")
    assert len(events) == 1
    assert events[0].source == "dune"
    post.assert_awaited_once()
    assert _host_of(post.await_args.args[0]) == DUNE_VALID_HOST
    get.assert_awaited_once()
    assert _host_of(get.await_args.args[0]) == DUNE_VALID_HOST


# ── Braze — allowlisted rest_api_base PATH PREFIX must survive (F-1) ────────

BRAZE_PATH_BASE = "https://rest.iad-01.braze.com/custom-proxy"


def test_braze_base_for_preserves_allowlisted_path_prefix() -> None:
    conn = BrazeConnector()
    base = conn._base_for(_cfg("braze", {"rest_api_base": BRAZE_PATH_BASE}))
    assert base == "https://rest.iad-01.braze.com/custom-proxy"


def test_braze_base_for_strips_only_trailing_slash_from_path() -> None:
    conn = BrazeConnector()
    base = conn._base_for(
        _cfg("braze", {"rest_api_base": "https://rest.iad-01.braze.com/custom-proxy/"})
    )
    assert base == "https://rest.iad-01.braze.com/custom-proxy"


def test_braze_base_for_fails_closed_on_denied_base() -> None:
    conn = BrazeConnector()
    base = conn._base_for(_cfg("braze", {"rest_api_base": "https://attacker.com/path"}))
    assert base == ""


@pytest.mark.asyncio
async def test_braze_pull_denied_base_raises_typed_failure(monkeypatch) -> None:
    import services.integrations.connectors.braze as braze_mod

    get = AsyncMock(return_value=(200, {}))
    monkeypatch.setattr(braze_mod, "_get", get)
    conn = BrazeConnector()
    # F-4: a denied base in a pull path is a TYPED failure (never a silent []).
    with pytest.raises(ConnectorPullDeniedError) as excinfo:
        await conn.pull(_cfg("braze", {"rest_api_base": "https://attacker.com"}),
                        secret="secret")
    assert "braze" in excinfo.value.safe_message
    assert "attacker.com" not in excinfo.value.safe_message
    assert get.await_count == 0


@pytest.mark.asyncio
async def test_braze_pull_preserves_path_prefix_on_allowlisted_base(monkeypatch) -> None:
    import services.integrations.connectors.braze as braze_mod

    get = AsyncMock(return_value=(200, {"emails": [], "campaigns": [], "canvases": []}))
    monkeypatch.setattr(braze_mod, "_get", get)
    conn = BrazeConnector()
    events = await conn.pull(_cfg("braze", {"rest_api_base": BRAZE_PATH_BASE}),
                             secret="secret")
    assert events == []
    assert get.await_count >= 4  # hard_bounces, unsubscribes, campaigns, canvases
    for call in get.await_args_list:
        url = str(call.args[0])
        assert url.startswith("https://rest.iad-01.braze.com/custom-proxy/"), url


# ── WS7 retire consumption — the marker has real in-process effect (F-3) ────


def test_retired_connector_resolves_to_none() -> None:
    assert get_connector("shopify") is not None
    result = retire_connector_type(_fresh_registry_state(), "shopify")
    assert result.status == "retired"
    assert is_retired("shopify") is True
    assert get_connector("shopify") is None


def test_list_descriptors_excludes_retired_type() -> None:
    types_before = {d["connector_type"] for d in list_descriptors()}
    assert "shopify" in types_before
    retire_connector_type(_fresh_registry_state(), "shopify")
    types_after = {d["connector_type"] for d in list_descriptors()}
    assert "shopify" not in types_after


def test_descriptor_for_excludes_retired_type() -> None:
    from services.integrations.connectors.registry import descriptor_for

    assert descriptor_for("shopify") is not None
    retire_connector_type(_fresh_registry_state(), "shopify")
    assert descriptor_for("shopify") is None


def test_repeat_retire_is_already_retired() -> None:
    state = _fresh_registry_state()
    first = retire_connector_type(state, "shopify")
    second = retire_connector_type(state, "shopify")
    assert first.status == "retired"
    assert second.status == "already_retired"
    assert second.retired_at == first.retired_at


def test_retired_other_connector_untouched() -> None:
    retire_connector_type(_fresh_registry_state(), "shopify")
    assert get_connector("shopify") is None
    # A non-retired connector resolves normally.
    assert get_connector("dune") is not None
