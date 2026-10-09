"""Safety contract for the retained SDK identity-resolve compatibility route.

The old wallet cache and cluster helpers were retired when canonical identity
resolution moved to the backend identity service. SDK wallet and device claims
are evidence, not proof of a prior person identity.
"""

from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

import pytest
from starlette.requests import Request

from config.settings import settings
from repositories.repos import reset_in_memory_stores
from services.consent.authority import ConsentReceiptRepository
from services.sdk import routes

TENANT = "tenant-sdk-route-contract"


@pytest.fixture(autouse=True)
def _reset_stores():
    reset_in_memory_stores()


def _request(*, tenant_id: str = TENANT, site_ids: list[str] | None = None) -> Request:
    return Request({
        "type": "http", "method": "POST", "path": "/sdk/identity/resolve",
        "headers": [], "query_string": b"",
        "state": {"tenant": SimpleNamespace(tenant_id=tenant_id, site_ids=site_ids)},
    })


def _enable(monkeypatch) -> None:
    monkeypatch.setattr(settings, "identity_continuity", replace(
        settings.identity_continuity,
        resolution_enabled=True,
        sdk_late_binding_enabled=True,
        anonymous_to_known_binding_enabled=True,
    ))


async def _grant(anonymous_id: str, *, state: str = "granted") -> None:
    await ConsentReceiptRepository().record(
        receipt_id=f"receipt-{TENANT}-{anonymous_id}", tenant_id=TENANT,
        purpose="analytics", state=state, anonymous_id=anonymous_id,
        mode="opt_in", metadata={"scope": "identity"},
    )


class _ResolverSpy:
    def __init__(self, existing_aliases: list[str] | None = None) -> None:
        self.events: list[tuple[dict, str]] = []
        self.alias_queries: list[tuple] = []
        self.existing_aliases = existing_aliases or []
        self._repo = self

    async def find_subjects_by_alias(self, *args):
        self.alias_queries.append(args)
        return self.existing_aliases

    async def resolve_event(self, event: dict, tenant_id: str):
        self.events.append((event, tenant_id))
        return SimpleNamespace(decision=SimpleNamespace(value="create"), reason_codes=["new_entity"])


def test_app_scope_requires_authenticated_site_and_rejects_spoofing():
    assert routes._authenticated_app_scope(_request(), "site-a") == (
        None, "sdk_app_scope_unavailable"
    )
    assert routes._authenticated_app_scope(_request(site_ids=["site-a"]), "site-b") == (
        None, "sdk_app_not_authorized"
    )
    assert routes._authenticated_app_scope(_request(site_ids=["site-a", "site-b"]), None) == (
        None, "sdk_app_scope_required"
    )
    assert routes._authenticated_app_scope(_request(site_ids=["site-a"]), None) == (
        "site-a", None
    )


def test_delivery_identity_is_stable_and_scoped_to_tenant_app_and_user():
    identity = routes._stable_event_id(TENANT, "anon-a", "site-a", "user-a")
    assert identity == routes._stable_event_id(TENANT, "anon-a", "site-a", "user-a")
    assert len({
        identity,
        routes._stable_event_id("other-tenant", "anon-a", "site-a", "user-a"),
        routes._stable_event_id(TENANT, "anon-a", "site-b", "user-a"),
        routes._stable_event_id(TENANT, "anon-a", "site-a", "user-b"),
    }) == 4


@pytest.mark.asyncio
async def test_wallet_only_claim_cannot_resolve_prior_identity(monkeypatch):
    _enable(monkeypatch)
    await _grant("anon-wallet")
    spy = _ResolverSpy()
    monkeypatch.setattr(routes, "_get_identity_resolver", lambda: spy)
    result = await routes.resolve_identity(
        routes.IdentityResolveRequest(
            anonymous_id="anon-wallet",
            wallets=[routes.WalletRef(address="0xDeAdBeEf", vm="evm")],
            tenant_app_key="site-a",
        ), _request(site_ids=["site-a"]),
    )
    assert result.resolved is False and result.identity is None
    assert result.reason_codes == ["unverified_identity_claims_ignored"]
    assert spy.events == [] and spy.alias_queries == []


@pytest.mark.asyncio
async def test_first_seen_user_claim_excludes_unverified_wallet_and_fingerprint(monkeypatch):
    _enable(monkeypatch)
    await _grant("anon-user")
    spy = _ResolverSpy()
    monkeypatch.setattr(routes, "_get_identity_resolver", lambda: spy)
    result = await routes.resolve_identity(
        routes.IdentityResolveRequest(
            anonymous_id="anon-user", user_id="user-a",
            wallets=[routes.WalletRef(address="0xDeAdBeEf", vm="evm")],
            device_fingerprint="unverified-device", email_hash="a" * 64,
            tenant_app_key="site-a",
        ), _request(site_ids=["site-a"]),
    )
    assert result.resolved is False and result.identity is None
    assert result.resolution_outcome == "create"
    assert len(spy.events) == 1
    event, tenant_id = spy.events[0]
    assert tenant_id == TENANT and event["tenant_id"] == TENANT
    assert event["user_id"] == "user-a"
    assert event["context"]["identity_namespace"] == "site-a"
    assert event["properties"] == {}
    for unverified in ("wallets", "device_fingerprint", "email_hash"):
        assert unverified not in event


@pytest.mark.asyncio
async def test_existing_user_alias_is_not_selected_by_client_claim(monkeypatch):
    _enable(monkeypatch)
    await _grant("anon-existing")
    spy = _ResolverSpy(existing_aliases=["canonical-existing"])
    monkeypatch.setattr(routes, "_get_identity_resolver", lambda: spy)
    result = await routes.resolve_identity(
        routes.IdentityResolveRequest(
            anonymous_id="anon-existing", user_id="existing-user", tenant_app_key="site-a"
        ), _request(site_ids=["site-a"]),
    )
    assert result.resolved is False and result.identity is None
    assert result.reason_codes == ["unverified_identity_claims_ignored"]
    assert len(spy.alias_queries) == 1 and spy.alias_queries[0][0] == TENANT
    assert spy.events == []


@pytest.mark.asyncio
async def test_revoked_consent_blocks_before_alias_lookup(monkeypatch):
    _enable(monkeypatch)
    await _grant("anon-revoked", state="revoked")
    spy = _ResolverSpy()
    monkeypatch.setattr(routes, "_get_identity_resolver", lambda: spy)
    result = await routes.resolve_identity(
        routes.IdentityResolveRequest(
            anonymous_id="anon-revoked", user_id="user-a", tenant_app_key="site-a"
        ), _request(site_ids=["site-a"]),
    )
    assert result.resolved is False and result.reason_codes == ["consent_revoked"]
    assert spy.alias_queries == [] and spy.events == []
