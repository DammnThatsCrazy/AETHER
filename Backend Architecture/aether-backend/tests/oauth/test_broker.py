"""AuthorizationBroker tests with a fake token endpoint and in-memory creds."""

from __future__ import annotations

from typing import Any, Mapping
from urllib.parse import parse_qs, urlparse

import pytest
from pydantic import SecretStr

from services.integrations.oauth.broker import AuthorizationBroker, OAuthBrokerError
from services.integrations.oauth.provider_config import OAuthProviderConfig
from services.integrations.oauth.state import OAuthStateError
from shared.credentials.in_memory import InMemoryCredentialBackend
from shared.credentials.service import CredentialService
from shared.credentials.types import ClientSecretCredential, OAuthTokenCredential
from shared.integration_contracts.identity import ProviderIdentity

pytestmark = pytest.mark.asyncio

_TENANT = "tenant-broker"
_IDENTITY = ProviderIdentity(family="hubspot", product="crm", capability="contacts_read")
_REDIRECT = "https://app.example.com/oauth/callback"

# Obviously-fake fixtures (no real secrets).
_FAKE_CLIENT_ID = "fake-client-id"
_FAKE_CLIENT_SECRET = "fake-client-secret-value"  # noqa: S105 - test placeholder
_FAKE_ACCESS = "fake-access-token-abc"  # noqa: S105 - test placeholder
_FAKE_REFRESH = "fake-refresh-token-abc"  # noqa: S105 - test placeholder
_FAKE_ACCESS_2 = "fake-access-token-def"  # noqa: S105 - test placeholder


def _config(pkce: bool = True) -> OAuthProviderConfig:
    return OAuthProviderConfig(
        authorize_url="https://provider.example.com/oauth/authorize",
        token_url="https://provider.example.com/oauth/token",
        scopes=("contacts.read", "contacts.write"),
        pkce=pkce,
        refresh_supported=True,
        client_credential_ref="oauth-client:hubspot:crm",
    )


class FakeTokenEndpoint:
    """Records POSTs and returns a canned token response."""

    def __init__(self, response: dict[str, Any]) -> None:
        self.response = response
        self.calls: list[tuple[str, dict[str, str]]] = []

    async def __call__(self, url: str, data: Mapping[str, str]) -> Mapping[str, Any]:
        self.calls.append((url, dict(data)))
        return self.response


async def _seed_client(creds: CredentialService, config: OAuthProviderConfig) -> None:
    await creds.create(
        _TENANT,
        config.client_credential_ref,
        ClientSecretCredential(
            client_id=_FAKE_CLIENT_ID,
            client_secret=SecretStr(_FAKE_CLIENT_SECRET),
        ),
    )


def _fresh_creds() -> CredentialService:
    return CredentialService(backend=InMemoryCredentialBackend(store={}))


async def test_build_authorization_url_contains_required_params() -> None:
    creds = _fresh_creds()
    config = _config(pkce=True)
    await _seed_client(creds, config)
    broker = AuthorizationBroker(credentials=creds)

    challenge = await broker.build_authorization_url(
        _TENANT, _IDENTITY, config, _REDIRECT
    )

    parsed = urlparse(challenge.url)
    params = {k: v[0] for k, v in parse_qs(parsed.query).items()}
    assert params["client_id"] == _FAKE_CLIENT_ID
    assert params["redirect_uri"] == _REDIRECT
    assert params["scope"] == "contacts.read contacts.write"
    assert params["state"] == challenge.state
    assert params["response_type"] == "code"
    assert params["code_challenge_method"] == "S256"
    assert params["code_challenge"]
    assert challenge.code_verifier is not None


async def test_build_without_pkce_omits_challenge() -> None:
    creds = _fresh_creds()
    config = _config(pkce=False)
    await _seed_client(creds, config)
    broker = AuthorizationBroker(credentials=creds)

    challenge = await broker.build_authorization_url(
        _TENANT, _IDENTITY, config, _REDIRECT
    )
    assert challenge.code_verifier is None
    assert "code_challenge" not in challenge.url


async def test_complete_authorization_exchanges_and_stores_token() -> None:
    creds = _fresh_creds()
    config = _config(pkce=True)
    await _seed_client(creds, config)
    fake = FakeTokenEndpoint(
        {
            "access_token": _FAKE_ACCESS,
            "refresh_token": _FAKE_REFRESH,
            "expires_in": 3600,
            "scope": "contacts.read contacts.write",
        }
    )
    broker = AuthorizationBroker(credentials=creds, http=fake)

    challenge = await broker.build_authorization_url(
        _TENANT, _IDENTITY, config, _REDIRECT
    )
    result = await broker.complete_authorization(challenge.state, "auth-code-123")

    # The token endpoint received the code, secret, and PKCE verifier.
    assert fake.calls, "token endpoint was not called"
    url, sent = fake.calls[0]
    assert url == config.token_url
    assert sent["grant_type"] == "authorization_code"
    assert sent["code"] == "auth-code-123"
    assert sent["client_secret"] == _FAKE_CLIENT_SECRET
    assert sent["code_verifier"] == challenge.code_verifier

    # Result is secret-free.
    assert result.credential_ref == "oauth:hubspot:crm:contacts_read"
    assert result.scope == ["contacts.read", "contacts.write"]
    assert result.expires_at is not None
    assert _FAKE_ACCESS not in result.masked_identifier

    # Stored credential is retrievable and carries the real access token.
    stored = await creds.get(_TENANT, result.credential_ref)
    assert isinstance(stored, OAuthTokenCredential)
    assert stored.access_token.get_secret_value() == _FAKE_ACCESS

    # Masked metadata never leaks plaintext.
    metadata = CredentialService.masked_metadata(stored)
    assert _FAKE_ACCESS not in str(metadata)
    assert _FAKE_REFRESH not in str(metadata)


async def test_complete_authorization_rejects_replayed_state() -> None:
    creds = _fresh_creds()
    config = _config(pkce=True)
    await _seed_client(creds, config)
    fake = FakeTokenEndpoint(
        {"access_token": _FAKE_ACCESS, "refresh_token": _FAKE_REFRESH, "expires_in": 60}
    )
    broker = AuthorizationBroker(credentials=creds, http=fake)

    challenge = await broker.build_authorization_url(
        _TENANT, _IDENTITY, config, _REDIRECT
    )
    await broker.complete_authorization(challenge.state, "auth-code-123")
    # Replay is caught at the signed-state layer before any second exchange.
    with pytest.raises((OAuthStateError, OAuthBrokerError)) as exc:
        await broker.complete_authorization(challenge.state, "auth-code-123")
    assert exc.value.reason in {"state_replayed", "flow_not_found"}
    # The token endpoint was only ever hit for the first, legitimate exchange.
    assert len(fake.calls) == 1


async def test_refresh_rotates_stored_token() -> None:
    creds = _fresh_creds()
    config = _config(pkce=True)
    await _seed_client(creds, config)
    fake = FakeTokenEndpoint(
        {
            "access_token": _FAKE_ACCESS,
            "refresh_token": _FAKE_REFRESH,
            "expires_in": 3600,
            "scope": "contacts.read",
        }
    )
    broker = AuthorizationBroker(credentials=creds, http=fake)

    challenge = await broker.build_authorization_url(
        _TENANT, _IDENTITY, config, _REDIRECT
    )
    await broker.complete_authorization(challenge.state, "auth-code-123")

    # Refresh returns a new access token; provider omits a fresh refresh_token.
    refresh_fake = FakeTokenEndpoint(
        {"access_token": _FAKE_ACCESS_2, "expires_in": 3600, "scope": "contacts.read"}
    )
    result = await broker.refresh(_TENANT, _IDENTITY, config, http=refresh_fake)

    assert result.refreshed is True
    url, sent = refresh_fake.calls[0]
    assert sent["grant_type"] == "refresh_token"
    assert sent["refresh_token"] == _FAKE_REFRESH

    stored = await creds.get(_TENANT, result.credential_ref)
    assert isinstance(stored, OAuthTokenCredential)
    assert stored.access_token.get_secret_value() == _FAKE_ACCESS_2
    # The prior refresh token is preserved when the provider omits a new one.
    assert stored.refresh_token is not None
    assert stored.refresh_token.get_secret_value() == _FAKE_REFRESH


async def test_refresh_without_stored_token_raises() -> None:
    creds = _fresh_creds()
    config = _config(pkce=True)
    await _seed_client(creds, config)
    broker = AuthorizationBroker(credentials=creds)
    with pytest.raises(OAuthBrokerError) as exc:
        await broker.refresh(_TENANT, _IDENTITY, config)
    assert exc.value.reason == "refresh_token_missing"
