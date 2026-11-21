"""Aether-hosted venue OAuth: Olympus app credential, per-link tenant tokens."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlsplit

import pytest

from repositories.repos import VenueAccountLinkRepository
from value.derivatives.venue_oauth import VenueOAuthError, VenueOAuthService

TENANT = "tenant_oauth"


class TokenEndpoint:
    def __init__(self, scope="wallet:user:read wallet:accounts:read", expires_in=3600):
        self.calls = []
        self.scope = scope
        self.expires_in = expires_in

    async def __call__(self, url, data):
        self.calls.append((url, dict(data)))
        return {"access_token": f"at-{len(self.calls)}", "refresh_token": "rt-1",
                "scope": self.scope, "expires_in": self.expires_in}


async def _service(http=None):
    from connectors.integrations.oauth.state import InMemoryNonceStore

    VenueAccountLinkRepository()._store.clear()
    service = VenueOAuthService(http=http or TokenEndpoint(), nonce_store=InMemoryNonceStore(), flows={})
    await service.configure_app(venue="coinbase_futures", client_id="olympus-app", client_secret="s3cret")
    return service


async def _start(service, tenant=None):
    return await service.start(
        tenant_id=tenant or TENANT, venue="coinbase_futures", subject_id="member_1", account_ref="cb-portfolio-1",
        consent_receipt_id="cr_oauth", redirect_uri="https://app.example/oauth/return",
    )


async def test_app_credential_lives_under_the_olympus_scope():
    from shared.credentials.service import credential_service

    service = await _service()
    status = await service.app_status("coinbase_futures")
    assert status["configured"] and status["client_id"] == "olympus-app"
    assert await credential_service.get(TENANT, "venue_oauth_app:coinbase_futures") is None
    assert await credential_service.get("olympus", "venue_oauth_app:coinbase_futures") is not None


async def test_start_builds_a_pkce_authorize_url_without_secrets():
    service = await _service()
    challenge = await _start(service)
    query = parse_qs(urlsplit(challenge["authorize_url"]).query)
    assert query["client_id"] == ["olympus-app"] and query["code_challenge_method"] == ["S256"]
    assert "s3cret" not in challenge["authorize_url"] and "code_verifier" not in query
    assert query["scope"] == ["wallet:user:read wallet:accounts:read wallet:transactions:read"]


async def test_complete_links_the_account_with_a_tenant_held_token():
    from connectors.provider_runtime.credential_broker import credential_broker

    http = TokenEndpoint()
    service = await _service(http)
    challenge = await _start(service)
    link = await service.complete(tenant_id=TENANT, state_token=challenge["state"], code="auth-code")
    assert link.method.value == "oauth" and link.source_relationship == "personal_account"
    assert link.account_ref == "cb-portfolio-1" and link.consent_receipt_id == "cr_oauth"
    token = await credential_broker.reveal(TENANT, link.credential_ref)
    assert token.access_token.get_secret_value() == "at-1"
    exchange = http.calls[0][1]
    assert exchange["client_secret"] == "s3cret" and exchange["code_verifier"]
    # Single use: the same state cannot be redeemed twice.
    with pytest.raises(VenueOAuthError):
        await service.complete(tenant_id=TENANT, state_token=challenge["state"], code="auth-code")


async def test_state_is_bound_to_the_tenant_that_started_it():
    service = await _service()
    challenge = await _start(service)
    with pytest.raises(VenueOAuthError) as exc:
        await service.complete(tenant_id="another_tenant", state_token=challenge["state"], code="c")
    assert exc.value.reason == "state_tenant_mismatch"


async def test_a_mutating_granted_scope_is_refused():
    service = await _service(TokenEndpoint(scope="wallet:user:read wallet:buys:create trade"))
    challenge = await _start(service)
    with pytest.raises(VenueOAuthError) as exc:
        await service.complete(tenant_id=TENANT, state_token=challenge["state"], code="c")
    assert exc.value.reason == "granted_scope_not_read_only"
    assert await service._link_service().list_links(TENANT) == []


async def test_unconfigured_app_and_unsupported_venue_are_refused():
    from connectors.integrations.oauth.state import InMemoryNonceStore
    from shared.credentials.service import credential_service

    await credential_service.delete("olympus", "venue_oauth_app:coinbase_futures")
    bare = VenueOAuthService(http=TokenEndpoint(), nonce_store=InMemoryNonceStore(), flows={})
    with pytest.raises(VenueOAuthError) as exc:
        await _start(bare)
    assert exc.value.reason == "venue_oauth_app_not_configured"
    with pytest.raises(VenueOAuthError) as exc:
        await bare.start(tenant_id=TENANT, venue="kalshi", subject_id="s", account_ref="a",
                         consent_receipt_id="c", redirect_uri="https://x")
    assert exc.value.reason == "venue_oauth_not_supported"


async def test_expired_token_is_refreshed_and_rotated_in_place():
    from connectors.provider_runtime.credential_broker import credential_broker
    from shared.credentials.types import OAuthTokenCredential

    http = TokenEndpoint()
    service = await _service(http)
    challenge = await _start(service)
    link = await service.complete(tenant_id=TENANT, state_token=challenge["state"], code="c")
    expired = OAuthTokenCredential(
        access_token="old", refresh_token="rt-1", scope=["wallet:user:read"],
        expires_at=datetime.now(timezone.utc) - timedelta(minutes=1),
    )
    fresh = await service.refresh_if_expired(link, expired)
    assert fresh.access_token.get_secret_value() == "at-2"
    assert http.calls[-1][1]["grant_type"] == "refresh_token"
    stored = await credential_broker.reveal(TENANT, link.credential_ref)
    assert stored.access_token.get_secret_value() == "at-2"
    assert (await service.refresh_if_expired(link, fresh)) is fresh
