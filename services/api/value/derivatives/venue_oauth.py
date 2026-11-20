"""Aether-hosted venue OAuth: Olympus-held app, tenant-held tokens per linked account.

Olympus Labs registers one OAuth application per venue that supports OAuth
(today Coinbase, for Coinbase Financial Markets futures). The app's client id
and secret are Olympus credentials, stored under the reserved ``olympus`` scope
(``venue_oauth_app:<venue>``) by a Kyber operator. The tokens a member grants
are the member's account access: they are stored per venue account link, under
the tenant, behind the link's provider connection, exactly like a read-only key.

Flow (authorization code + PKCE):

1. ``start`` — the tenant asks to link a subject; the server mints a signed,
   expiring, single-use state carrying tenant, venue, subject, account and
   consent receipt (no secret) and keeps the PKCE verifier server-side.
2. The member approves on the venue and is redirected to the tenant's app,
   which posts ``state`` + ``code`` back with its own authentication.
3. ``complete`` — the server verifies the state (same tenant, unexpired, unused),
   exchanges the code with the Olympus client secret, refuses any granted scope
   that is not read-only, and links the account with the token as its credential.

``refresh_if_expired`` swaps an expired access token for a new one with the
Olympus client and rotates the link's credential in place. The flow store is
process-local (as in the shared OAuth broker); a durable store is required
before multi-replica deployment.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable, Mapping, Optional
from urllib.parse import urlencode

from shared.integration_contracts.source_relationship import OLYMPUS_SOURCE_TENANT_ID

STATE_TTL_SECONDS = 600


class VenueOAuthError(ValueError):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class VenueOAuthApp:
    venue: str
    authorize_url: str
    token_url: str
    scopes: tuple[str, ...]

    @property
    def client_ref(self) -> str:
        return f"venue_oauth_app:{self.venue}"


VENUE_OAUTH_APPS: dict[str, VenueOAuthApp] = {
    "coinbase_futures": VenueOAuthApp(
        venue="coinbase_futures",
        authorize_url="https://login.coinbase.com/oauth2/auth",
        token_url="https://login.coinbase.com/oauth2/token",
        scopes=("wallet:user:read", "wallet:accounts:read", "wallet:transactions:read"),
    ),
}

HttpPost = Callable[[str, Mapping[str, str]], Awaitable[Mapping[str, Any]]]


async def _default_post(url: str, data: Mapping[str, str]) -> Mapping[str, Any]:
    import httpx

    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.post(url, data=dict(data), headers={"Accept": "application/json"})
        response.raise_for_status()
        return response.json()


_FLOWS: dict[str, dict[str, Any]] = {}


class VenueOAuthService:
    def __init__(
        self, *, credentials: Any = None, link_service: Any = None, http: Optional[HttpPost] = None,
        nonce_store: Any = None, flows: Optional[dict[str, dict[str, Any]]] = None,
    ) -> None:
        self._credentials = credentials
        self._links = link_service
        self._http = http or _default_post
        self._nonce_store = nonce_store
        self._flows = flows if flows is not None else _FLOWS

    def _credential_service(self) -> Any:
        if self._credentials is None:
            from shared.credentials.service import credential_service

            self._credentials = credential_service
        return self._credentials

    def _link_service(self) -> Any:
        if self._links is None:
            from value.derivatives.account_links import VenueAccountLinkService

            self._links = VenueAccountLinkService()
        return self._links

    def _nonces(self) -> Any:
        if self._nonce_store is None:
            self._nonce_store = _SHARED_NONCES
        return self._nonce_store

    @staticmethod
    def app(venue: str) -> VenueOAuthApp:
        app = VENUE_OAUTH_APPS.get(str(venue or "").lower())
        if app is None:
            raise VenueOAuthError("venue_oauth_not_supported")
        return app

    async def _client(self, app: VenueOAuthApp) -> Any:
        from shared.credentials.types import ClientSecretCredential

        client = await self._credential_service().get(OLYMPUS_SOURCE_TENANT_ID, app.client_ref)
        if not isinstance(client, ClientSecretCredential):
            raise VenueOAuthError("venue_oauth_app_not_configured")
        return client

    async def configure_app(self, *, venue: str, client_id: str, client_secret: str) -> dict[str, Any]:
        """Kyber operator: store the Olympus app credential under the olympus scope."""
        from shared.credentials.types import ClientSecretCredential

        app = self.app(venue)
        credential = ClientSecretCredential(client_id=client_id, client_secret=client_secret)
        service = self._credential_service()
        if await service.get(OLYMPUS_SOURCE_TENANT_ID, app.client_ref) is None:
            await service.create(OLYMPUS_SOURCE_TENANT_ID, app.client_ref, credential)
        else:
            await service.rotate(OLYMPUS_SOURCE_TENANT_ID, app.client_ref, credential)
        return await self.app_status(venue)

    async def app_status(self, venue: str) -> dict[str, Any]:
        app = self.app(venue)
        client = await self._credential_service().get(OLYMPUS_SOURCE_TENANT_ID, app.client_ref)
        return {"venue": app.venue, "configured": client is not None, "scopes": list(app.scopes),
                "client_id": getattr(client, "client_id", None)}

    async def start(
        self, *, tenant_id: str, venue: str, subject_id: str, account_ref: str,
        consent_receipt_id: str, redirect_uri: str,
    ) -> dict[str, Any]:
        from connectors.integrations.oauth.pkce import generate_pkce
        from connectors.integrations.oauth.state import issue_state, verify_state
        from shared.integration_contracts.identity import ProviderIdentity
        from value.derivatives.venue_sources import OAUTH_ACCESS, venue_profile

        app = self.app(venue)
        if tenant_id == OLYMPUS_SOURCE_TENANT_ID:
            raise VenueOAuthError("olympus_scope_not_linkable")
        profile = venue_profile(app.venue)
        if not profile.accepts(OAUTH_ACCESS):
            raise VenueOAuthError("venue_does_not_accept_oauth")
        for value, reason in ((subject_id, "subject_id_required"), (account_ref, "account_ref_required"),
                              (consent_receipt_id, "consent_receipt_required"),
                              (redirect_uri, "redirect_uri_required")):
            if not str(value or "").strip():
                raise VenueOAuthError(reason)
        client = await self._client(app)
        family, product, capability = profile.account_identity.split(".")
        identity = ProviderIdentity(family=family, product=product, capability=capability)
        state_token = issue_state(
            tenant_id, identity, redirect_uri, ttl_seconds=STATE_TTL_SECONDS,
            extra={"venue": app.venue, "subject_id": subject_id, "account_ref": account_ref,
                   "consent_receipt_id": consent_receipt_id},
        )
        state = verify_state(state_token)
        pair = generate_pkce()
        self._flows[state.nonce] = {"verifier": pair.verifier, "venue": app.venue}
        params = {
            "response_type": "code", "client_id": client.client_id, "redirect_uri": redirect_uri,
            "scope": " ".join(app.scopes), "state": state_token,
            "code_challenge": pair.challenge, "code_challenge_method": pair.method,
        }
        return {"authorize_url": f"{app.authorize_url}?{urlencode(params)}", "state": state_token,
                "expires_in": STATE_TTL_SECONDS}

    async def complete(self, *, tenant_id: str, state_token: str, code: str, actor: str = "system") -> Any:
        from connectors.integrations.oauth.state import OAuthStateError, verify_state
        from value.derivatives.account_links import LinkMethod
        from value.derivatives.models import ReadOnlyCredentialError, validate_read_only_scopes

        try:
            state = verify_state(state_token, nonce_store=self._nonces())
        except OAuthStateError as exc:
            raise VenueOAuthError(exc.reason) from exc
        if state.tenant_id != tenant_id:
            # A state minted for another tenant is never redeemable here.
            raise VenueOAuthError("state_tenant_mismatch")
        flow = self._flows.pop(state.nonce, None)
        extra = dict(state.extra or {})
        if flow is None or flow.get("venue") != extra.get("venue"):
            raise VenueOAuthError("flow_not_found")
        if not str(code or "").strip():
            raise VenueOAuthError("authorization_code_required")
        app = self.app(extra["venue"])
        client = await self._client(app)
        body = await self._http(app.token_url, {
            "grant_type": "authorization_code", "code": code, "redirect_uri": state.redirect_uri,
            "client_id": client.client_id, "client_secret": client.client_secret.get_secret_value(),
            "code_verifier": flow["verifier"],
        })
        credential = _token_credential(body, fallback_scopes=app.scopes)
        try:
            validate_read_only_scopes(credential.scope)
        except ReadOnlyCredentialError as exc:
            raise VenueOAuthError("granted_scope_not_read_only") from exc
        return await self._link_service().link_credential(
            tenant_id=tenant_id, subject_id=extra["subject_id"], venue=app.venue,
            account_ref=extra["account_ref"], method=LinkMethod.OAUTH, credential=credential,
            scopes=list(credential.scope), consent_receipt_id=extra["consent_receipt_id"], actor=actor,
        )

    async def refresh_if_expired(self, link: Any, credential: Any) -> Any:
        """Return a usable credential, refreshing an expired OAuth token in place."""
        from shared.credentials.types import OAuthTokenCredential

        if not isinstance(credential, OAuthTokenCredential) or not credential.is_expired():
            return credential
        if credential.refresh_token is None:
            raise VenueOAuthError("oauth_token_expired_without_refresh")
        app = self.app(link.venue)
        client = await self._client(app)
        body = dict(await self._http(app.token_url, {
            "grant_type": "refresh_token",
            "refresh_token": credential.refresh_token.get_secret_value(),
            "client_id": client.client_id, "client_secret": client.client_secret.get_secret_value(),
        }))
        body.setdefault("refresh_token", credential.refresh_token.get_secret_value())
        refreshed = _token_credential(body, fallback_scopes=tuple(credential.scope))
        await self._credential_service().rotate(link.tenant_id, link.credential_ref, refreshed)
        return refreshed


def _token_credential(body: Mapping[str, Any], *, fallback_scopes: tuple[str, ...]) -> Any:
    from shared.credentials.types import OAuthTokenCredential

    access = str(body.get("access_token") or "")
    if not access:
        raise VenueOAuthError("token_response_invalid")
    raw_scope = body.get("scope")
    scopes = (raw_scope.replace(",", " ").split() if isinstance(raw_scope, str)
              else list(raw_scope or fallback_scopes))
    expires_in = body.get("expires_in")
    expires_at = None
    if expires_in not in (None, ""):
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=int(expires_in))
    return OAuthTokenCredential(
        access_token=access, refresh_token=body.get("refresh_token") or None,
        scope=scopes, expires_at=expires_at,
    )


def _make_nonce_store() -> Any:
    from connectors.integrations.oauth.state import InMemoryNonceStore

    return InMemoryNonceStore()


_SHARED_NONCES = _make_nonce_store()


__all__ = ["VENUE_OAUTH_APPS", "VenueOAuthApp", "VenueOAuthError", "VenueOAuthService"]
