"""Shopify account discovery and selection (:class:`AccountAdapter`).

Shopify has ONE account per shop: the shop itself. Discovery returns a single
:class:`ProviderAccount` keyed ``shop:{shop_domain}``. Discovery NEVER requires
live auth for structural discovery — in a no-credential context it returns the
deterministic domain-derived account without a network call; a live
``/shop.json`` lookup is attempted only when a credential is present, and falls
back to the domain-derived account on any failure.
"""

from __future__ import annotations

from typing import Any, Optional

from shared.integration_contracts.acquisition import AcquisitionContext, ProviderAccount
from shared.integration_contracts.results import AdapterResult, AdapterStatus

from services.providers.shopify.auth import (
    _api_version,
    _credential_dict,
    _raw_shop_domain,
    _shop_domain,
)

_REQUEST_TIMEOUT_SECONDS = 10.0


def _http_client():
    """Lazy httpx client factory (backend pattern). Tests patch this seam."""
    import httpx

    return httpx.AsyncClient(timeout=_REQUEST_TIMEOUT_SECONDS)


def _domain_account(shop_domain: str) -> ProviderAccount:
    """Deterministic, network-free account derived from the shop domain."""
    return ProviderAccount(
        account_id=f"shop:{shop_domain}",
        display_name=shop_domain,
        external_id=None,
        currency=None,
        metadata={"shop_domain": shop_domain, "shop_id": None},
    )


async def _fetch_shop_account(
    context: AcquisitionContext, shop_domain: str, cred: dict[str, Any]
) -> Optional[ProviderAccount]:
    """Live /shop.json lookup; returns ``None`` on any failure (caller falls back)."""
    import httpx

    url = f"https://{shop_domain}/admin/api/{_api_version(context)}/shop.json"
    headers = {"Accept": "application/json"}
    if cred.get("shop_access_token"):
        headers["X-Shopify-Access-Token"] = cred["shop_access_token"]
        auth = None
    else:
        auth = httpx.BasicAuth(cred.get("api_key", ""), cred.get("password", ""))
    try:
        async with _http_client() as client:
            response = await client.get(url, headers=headers, auth=auth)
        if response.status_code != 200:
            return None
        shop = (response.json() or {}).get("shop") or {}
    except Exception:  # noqa: BLE001 - any failure degrades to domain-derived
        return None
    return ProviderAccount(
        account_id=f"shop:{shop_domain}",
        display_name=str(shop.get("name") or shop_domain),
        external_id=str(shop.get("id")) if shop.get("id") is not None else None,
        currency=shop.get("currency"),
        metadata={
            "shop_domain": shop_domain,
            "shop_id": shop.get("id"),
        },
    )


class ShopifyAccountAdapter:
    """AccountAdapter: single shop account, discovery-never-requires-auth."""

    async def discover_accounts(
        self, context: AcquisitionContext
    ) -> AdapterResult[list[ProviderAccount]]:
        raw_domain = _raw_shop_domain(context)
        shop_domain = _shop_domain(context)  # validated allowlisted host
        if not raw_domain:
            return AdapterResult(
                success=False,
                status=AdapterStatus.PERMANENT_ERROR,
                error_code="shop_domain_missing",
                retryable=False,
                data={"detail": "shop_domain is required for account discovery"},
            )
        if not shop_domain:
            return AdapterResult(
                success=False,
                status=AdapterStatus.PERMANENT_ERROR,
                error_code="shop_domain_invalid",
                retryable=False,
                data={"detail": "shop_domain is not a valid *.myshopify.com host"},
            )
        cred = _credential_dict(context)
        account: Optional[ProviderAccount] = None
        # Live lookup only when a credential is present; structural discovery
        # must never require live auth.
        if any(cred.get(key) for key in ("shop_access_token", "api_key")):
            account = await _fetch_shop_account(context, shop_domain, cred)
        if account is None:
            account = _domain_account(shop_domain)
        return AdapterResult.ok([account])

    async def select_account(
        self, context: AcquisitionContext, *, account_id: str
    ) -> AdapterResult[Any]:
        """Validate the selected account matches the resolved shop."""
        shop_domain = _shop_domain(context)
        expected = f"shop:{shop_domain}"
        if account_id == expected:
            return AdapterResult.ok({"account_id": account_id})
        return AdapterResult(
            success=False,
            status=AdapterStatus.PERMANENT_ERROR,
            error_code="account_mismatch",
            retryable=False,
            data={"detail": f"account_id {account_id!r} does not match resolved shop {expected!r}"},
        )


__all__ = [
    "ShopifyAccountAdapter",
    "_domain_account",
]
