"""OAuth authorization broker.

Drives the three server-side legs of an OAuth authorization-code flow and lands
the result in the credential platform:

1. :meth:`AuthorizationBroker.build_authorization_url` — mint a signed state, an
   optional PKCE pair, and the provider consent URL. The PKCE verifier and the
   provider config are held in a per-flow store keyed by the state's nonce; the
   verifier is *never* placed in the (signed-but-not-encrypted) state token.
2. :meth:`AuthorizationBroker.complete_authorization` — verify the returned
   state, exchange the code at the token endpoint (server-side POST, client
   secret injected from ``credential_service``), and store the tokens as an
   :class:`OAuthTokenCredential`.
3. :meth:`AuthorizationBroker.refresh` — swap a stored refresh token for a new
   access token and rotate the stored credential in place.

The client_id/client_secret are resolved from a
:class:`ClientSecretCredential` referenced by the provider config — the broker
holds no app secrets of its own. Results are typed and secret-free: an
:class:`AuthorizationResult` carries scope, expiry, a masked identifier, and the
credential ref, never token material.

HTTP is injected. Any ``async def post(url, data) -> Mapping`` works, so tests
pass a fake token endpoint; when nothing is injected the broker falls back to a
minimal ``httpx`` POST. Like the nonce store, the in-memory flow store is
process-local — a durable implementation of :class:`FlowStore` is the follow-up
for multi-replica deployments.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable, Mapping, Optional, Protocol
from urllib.parse import urlencode

from shared.credentials.service import CredentialService, credential_service
from shared.credentials.types import (
    ClientSecretCredential,
    OAuthTokenCredential,
    masked_identifier,
)
from shared.integration_contracts.identity import ProviderIdentity
from shared.logger.logger import get_logger
from shared.temporal.instant import ensure_aware_utc, to_iso_utc

from .pkce import generate_pkce
from .provider_config import OAuthProviderConfig
from .state import (
    InMemoryNonceStore,
    OAuthState,
    SingleUseNonceStore,
    issue_state,
    verify_state,
)

logger = get_logger("aether.integrations.oauth.broker")

#: An injected async POST: ``await http(url, form_data) -> parsed JSON mapping``.
HttpPost = Callable[[str, Mapping[str, str]], Awaitable[Mapping[str, Any]]]


class OAuthBrokerError(Exception):
    """A fail-closed broker rejection carrying a stable, non-disclosing reason."""

    def __init__(self, reason: str, message: Optional[str] = None) -> None:
        self.reason = reason
        super().__init__(message or reason)


@dataclass(frozen=True)
class AuthorizationChallenge:
    """What the caller needs to start a flow. ``code_verifier`` is present only
    when the provider uses PKCE, and is echoed for callers that persist it
    themselves; the broker also retains it internally keyed by the state nonce."""

    url: str
    state: str
    code_verifier: Optional[str]


@dataclass(frozen=True)
class AuthorizationResult:
    """The secret-free outcome of a completed or refreshed authorization."""

    tenant_id: str
    identity_key: str
    credential_ref: str
    scope: list[str]
    expires_at: Optional[str]
    masked_identifier: str
    refreshed: bool = False


@dataclass
class _FlowContext:
    """Per-flow secrets/config held server-side between authorize and callback."""

    config: OAuthProviderConfig
    code_verifier: Optional[str] = None


class FlowStore(Protocol):
    """Stores per-flow context (config + PKCE verifier) keyed by state nonce."""

    def put(self, nonce: str, context: _FlowContext) -> None: ...

    def take(self, nonce: str) -> Optional[_FlowContext]: ...


@dataclass
class InMemoryFlowStore:
    """Process-local flow store. Durable impl is a follow-up (see module doc)."""

    _flows: dict[str, _FlowContext] = field(default_factory=dict)

    def put(self, nonce: str, context: _FlowContext) -> None:
        self._flows[nonce] = context

    def take(self, nonce: str) -> Optional[_FlowContext]:
        return self._flows.pop(nonce, None)


async def _default_http_post(
    url: str, data: Mapping[str, str]
) -> Mapping[str, Any]:
    """Fallback token-endpoint POST using ``httpx``; raises on HTTP >= 400."""
    import httpx

    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.post(url, data=dict(data))
    if response.status_code >= 400:
        raise OAuthBrokerError(
            "token_exchange_failed", f"token endpoint returned HTTP {response.status_code}"
        )
    body = response.json()
    if not isinstance(body, Mapping):
        raise OAuthBrokerError("token_response_invalid", "token endpoint returned no object")
    return body


def _parse_scope(raw: Any) -> list[str]:
    """Normalize a scope value (space- or comma-delimited string, or list)."""
    if raw is None:
        return []
    if isinstance(raw, (list, tuple)):
        return [str(item) for item in raw if str(item)]
    text = str(raw)
    separator = "," if "," in text else " "
    return [part.strip() for part in text.split(separator) if part.strip()]


def _expiry_from(expires_in: Any) -> Optional[datetime]:
    """Turn an ``expires_in`` seconds value into an aware UTC expiry instant."""
    if expires_in is None:
        return None
    try:
        seconds = int(expires_in)
    except (TypeError, ValueError):
        return None
    return ensure_aware_utc(datetime.now(timezone.utc) + timedelta(seconds=seconds))


class AuthorizationBroker:
    """Server-side driver for OAuth authorization-code flows."""

    def __init__(
        self,
        *,
        credentials: Optional[CredentialService] = None,
        nonce_store: Optional[SingleUseNonceStore] = None,
        flow_store: Optional[FlowStore] = None,
        http: Optional[HttpPost] = None,
    ) -> None:
        self._credentials = credentials or credential_service
        self._nonce_store = nonce_store or InMemoryNonceStore()
        self._flow_store: FlowStore = flow_store or InMemoryFlowStore()
        self._http: HttpPost = http or _default_http_post

    @staticmethod
    def oauth_ref(identity: ProviderIdentity) -> str:
        """Canonical credential ref for the tokens of one provider capability."""
        return f"oauth:{identity.family}:{identity.product}:{identity.capability}"

    async def _client_credential(
        self, tenant_id: str, config: OAuthProviderConfig
    ) -> ClientSecretCredential:
        cred = await self._credentials.get(tenant_id, config.client_credential_ref)
        if not isinstance(cred, ClientSecretCredential):
            raise OAuthBrokerError(
                "client_credential_missing",
                f"no client credential at ref {config.client_credential_ref!r}",
            )
        return cred

    async def build_authorization_url(
        self,
        tenant_id: str,
        identity: ProviderIdentity,
        config: OAuthProviderConfig,
        redirect_uri: str,
        *,
        extra_params: Optional[Mapping[str, str]] = None,
    ) -> AuthorizationChallenge:
        """Build the provider consent URL and mint the flow's signed state.

        Async because the public ``client_id`` is read from the stored client
        credential (the single source of truth for app identity). The PKCE
        verifier and provider config are retained internally keyed by the state
        nonce so :meth:`complete_authorization` needs only the returned state.
        """
        client = await self._client_credential(tenant_id, config)
        state_token = issue_state(tenant_id, identity, redirect_uri)
        # Re-verify our own fresh token (no nonce store) to recover the nonce we
        # key the flow context by — the nonce is never exposed to the caller.
        state = verify_state(state_token)

        params: dict[str, str] = {
            "response_type": "code",
            "client_id": client.client_id,
            "redirect_uri": redirect_uri,
            "scope": " ".join(config.scopes),
            "state": state_token,
        }

        verifier: Optional[str] = None
        if config.pkce:
            pair = generate_pkce()
            verifier = pair.verifier
            params["code_challenge"] = pair.challenge
            params["code_challenge_method"] = pair.method
        if extra_params:
            params.update(dict(extra_params))

        self._flow_store.put(
            state.nonce, _FlowContext(config=config, code_verifier=verifier)
        )
        url = f"{config.authorize_url}?{urlencode(params)}"
        logger.info(
            "oauth.authorize_url tenant=%s identity=%s pkce=%s",
            tenant_id,
            identity.key,
            config.pkce,
        )
        return AuthorizationChallenge(url=url, state=state_token, code_verifier=verifier)

    async def complete_authorization(
        self,
        state_token: str,
        code: str,
        *,
        http: Optional[HttpPost] = None,
    ) -> AuthorizationResult:
        """Verify the callback state, exchange ``code``, and store the tokens."""
        state = verify_state(state_token, nonce_store=self._nonce_store)
        context = self._flow_store.take(state.nonce)
        if context is None:
            raise OAuthBrokerError(
                "flow_not_found", "no in-flight authorization matches this state"
            )
        config = context.config
        client = await self._client_credential(state.tenant_id, config)

        data: dict[str, str] = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": state.redirect_uri,
            "client_id": client.client_id,
            "client_secret": client.client_secret.get_secret_value(),
        }
        if config.pkce and context.code_verifier:
            data["code_verifier"] = context.code_verifier

        body = await self._post(config.token_url, data, http)
        return await self._store_tokens(
            state.tenant_id, state.identity, body, refreshed=False
        )

    async def refresh(
        self,
        tenant_id: str,
        identity: ProviderIdentity,
        config: OAuthProviderConfig,
        *,
        http: Optional[HttpPost] = None,
    ) -> AuthorizationResult:
        """Exchange the stored refresh token for a new access token and rotate."""
        if not config.refresh_supported:
            raise OAuthBrokerError(
                "refresh_unsupported", "provider does not support refresh tokens"
            )
        ref = self.oauth_ref(identity)
        existing = await self._credentials.get(tenant_id, ref)
        if not isinstance(existing, OAuthTokenCredential) or existing.refresh_token is None:
            raise OAuthBrokerError(
                "refresh_token_missing", "no stored refresh token for this identity"
            )
        client = await self._client_credential(tenant_id, config)

        data: dict[str, str] = {
            "grant_type": "refresh_token",
            "refresh_token": existing.refresh_token.get_secret_value(),
            "client_id": client.client_id,
            "client_secret": client.client_secret.get_secret_value(),
        }
        body = dict(await self._post(config.token_url, data, http))
        # Many providers omit refresh_token on refresh; keep the existing one so
        # the rotated credential stays refreshable.
        if not body.get("refresh_token"):
            body["refresh_token"] = existing.refresh_token.get_secret_value()
        return await self._store_tokens(tenant_id, identity, body, refreshed=True)

    async def _post(
        self, url: str, data: Mapping[str, str], http: Optional[HttpPost]
    ) -> Mapping[str, Any]:
        poster = http or self._http
        body = await poster(url, data)
        if not isinstance(body, Mapping):
            raise OAuthBrokerError(
                "token_response_invalid", "token endpoint returned no object"
            )
        return body

    async def _store_tokens(
        self,
        tenant_id: str,
        identity: ProviderIdentity,
        body: Mapping[str, Any],
        *,
        refreshed: bool,
    ) -> AuthorizationResult:
        access = str(body.get("access_token") or "")
        if not access:
            raise OAuthBrokerError(
                "token_response_invalid", "token response carried no access_token"
            )
        refresh_value = body.get("refresh_token")
        scope = _parse_scope(body.get("scope"))
        expires_at = _expiry_from(body.get("expires_in"))

        from pydantic import SecretStr

        credential = OAuthTokenCredential(
            access_token=SecretStr(access),
            refresh_token=SecretStr(str(refresh_value)) if refresh_value else None,
            scope=scope,
            expires_at=expires_at,
        )
        ref = self.oauth_ref(identity)
        if refreshed:
            await self._credentials.rotate(tenant_id, ref, credential)
        else:
            await self._credentials.create(
                tenant_id, ref, credential, metadata={"identity": identity.key}
            )
        return AuthorizationResult(
            tenant_id=tenant_id,
            identity_key=identity.key,
            credential_ref=ref,
            scope=scope,
            expires_at=to_iso_utc(expires_at) if expires_at else None,
            masked_identifier=masked_identifier(credential),
            refreshed=refreshed,
        )


__all__ = [
    "AuthorizationBroker",
    "AuthorizationChallenge",
    "AuthorizationResult",
    "FlowStore",
    "HttpPost",
    "InMemoryFlowStore",
    "OAuthBrokerError",
]
