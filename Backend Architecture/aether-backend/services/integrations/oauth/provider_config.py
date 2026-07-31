"""Static, secret-free OAuth provider configuration.

An :class:`OAuthProviderConfig` describes *how* to run the authorization-code
flow for one provider — the authorize/token endpoints, the scopes to request,
whether PKCE and refresh are supported, and a **credential reference** to where
the app's client_id/client_secret live in the credential platform. It never
holds a secret: only the ``client_credential_ref`` string, which the broker
resolves through ``credential_service`` at request time.

Some providers key their endpoints on a per-install value (Shopify's shop
subdomain, for example). Those appear as ``{name}`` placeholders; call
:meth:`OAuthProviderConfig.render` with the values before use::

    cfg = OAUTH_PROVIDERS["shopify"].render(shop="acme")
    # -> https://acme.myshopify.com/admin/oauth/authorize

Providers without placeholders are returned unchanged by ``render``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace

_PLACEHOLDER_RE = re.compile(r"\{([a-z_][a-z0-9_]*)\}")


@dataclass(frozen=True)
class OAuthProviderConfig:
    """Endpoint + policy description for one provider's OAuth flow.

    ``client_credential_ref`` points at a
    :class:`shared.credentials.types.ClientSecretCredential` in the credential
    platform. No secret material is stored on this object.
    """

    authorize_url: str
    token_url: str
    scopes: tuple[str, ...]
    pkce: bool
    refresh_supported: bool
    client_credential_ref: str

    @property
    def placeholders(self) -> frozenset[str]:
        """Template variable names still present in the endpoint URLs."""
        found = _PLACEHOLDER_RE.findall(self.authorize_url)
        found += _PLACEHOLDER_RE.findall(self.token_url)
        return frozenset(found)

    def render(self, **values: str) -> "OAuthProviderConfig":
        """Return a copy with ``{name}`` placeholders substituted.

        Raises :class:`KeyError` if a placeholder present in the URLs is not
        supplied — a half-templated endpoint is never returned.
        """
        missing = self.placeholders - set(values)
        if missing:
            raise KeyError(
                f"missing template values for placeholders: {sorted(missing)}"
            )
        if not self.placeholders:
            return self
        return replace(
            self,
            authorize_url=self.authorize_url.format(**values),
            token_url=self.token_url.format(**values),
        )


# A small registry of real providers. Endpoints that require a per-install value
# use ``{shop}``-style placeholders documented above. The credential refs point
# at where each app's client_id/client_secret is stored — never inline secrets.
OAUTH_PROVIDERS: dict[str, OAuthProviderConfig] = {
    # Shopify Admin — the shop subdomain templates both endpoints. Shopify's
    # public-app flow does not use PKCE (it authenticates the callback via an
    # HMAC signature) and issues non-expiring offline tokens, so refresh is off.
    "shopify": OAuthProviderConfig(
        authorize_url="https://{shop}.myshopify.com/admin/oauth/authorize",
        token_url="https://{shop}.myshopify.com/admin/oauth/access_token",
        scopes=("read_orders",),
        pkce=False,
        refresh_supported=False,
        client_credential_ref="oauth-client:shopify:admin",
    ),
    # HubSpot — fixed endpoints, refreshable access tokens, no PKCE.
    "hubspot": OAuthProviderConfig(
        authorize_url="https://app.hubspot.com/oauth/authorize",
        token_url="https://api.hubapi.com/oauth/v1/token",
        scopes=("crm.objects.contacts.read",),
        pkce=False,
        refresh_supported=True,
        client_credential_ref="oauth-client:hubspot:crm",
    ),
    # Google Analytics (GA4) via Google's OAuth 2.0 — PKCE + refresh supported.
    "google_ga4": OAuthProviderConfig(
        authorize_url="https://accounts.google.com/o/oauth2/v2/auth",
        token_url="https://oauth2.googleapis.com/token",
        scopes=("https://www.googleapis.com/auth/analytics.readonly",),
        pkce=True,
        refresh_supported=True,
        client_credential_ref="oauth-client:google:analytics",
    ),
}


__all__ = ["OAUTH_PROVIDERS", "OAuthProviderConfig"]
