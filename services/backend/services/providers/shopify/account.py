"""Shopify account discovery and selection (:class:`AccountAdapter`).

Shopify has ONE account per shop: the shop itself. Discovery returns a single
:class:`ProviderAccount` keyed ``shop:{shop_domain}``. REST structural
discovery can return a deterministic domain-derived account without live auth;
a live ``/shop.json`` lookup is attempted for REST credentials and may fall
back to the domain-derived account. GraphQL requires an authenticated ``shop
{ id }`` lookup; a failed lookup is a typed discovery failure because v2
object identity cannot use a mutable domain as its account key.
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
    _source_account_realm,
)

_REQUEST_TIMEOUT_SECONDS = 10.0


class _ShopifyAccountFailure(Exception):
    def __init__(self, status: AdapterStatus, code: str) -> None:
        super().__init__(code)
        self.status = status
        self.code = code


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
    """Authenticated shop lookup; returns ``None`` on failure for caller classification."""
    import httpx

    if str(context.config.get("orders_api") or "rest").lower() == "graphql":
        from services.providers.shopify.graphql_pull import GRAPHQL_API_VERSION, _SHOP_GID_RE, _post

        token = cred.get("shop_access_token")
        if not token:
            return None
        url = f"https://{shop_domain}/admin/api/{GRAPHQL_API_VERSION}/graphql.json"
        try:
            async with _http_client() as client:
                body = await _post(
                    client,
                    url,
                    str(token),
                    "query AetherShopAccount { shop { id name } currentAppInstallation { accessScopes { handle } } }",
                    {},
                )
            shop = body["data"].get("shop")
            if (
                not isinstance(shop, dict)
                or not isinstance(shop.get("id"), str)
                or not _SHOP_GID_RE.fullmatch(shop["id"])
            ):
                raise _ShopifyAccountFailure(AdapterStatus.RETRYABLE_ERROR, "shop_identity_missing")
            installation = body["data"].get("currentAppInstallation")
            scopes = installation.get("accessScopes") if isinstance(installation, dict) else None
            if not isinstance(scopes, list) or any(
                not isinstance(scope, dict) or not isinstance(scope.get("handle"), str)
                for scope in scopes
            ):
                raise _ShopifyAccountFailure(
                    AdapterStatus.RETRYABLE_ERROR, "order_scope_evidence_missing"
                )
            if "read_orders" not in {scope["handle"] for scope in scopes}:
                raise _ShopifyAccountFailure(AdapterStatus.PERMANENT_ERROR, "read_orders_required")
        except _ShopifyAccountFailure:
            raise
        except Exception:  # noqa: BLE001 - caller turns missing GraphQL identity into failure
            return None
        return ProviderAccount(
            account_id=f"shop:{shop_domain}",
            display_name=str(shop.get("name") or shop_domain),
            external_id=shop["id"],
            currency=None,
            metadata={
                "shop_domain": shop_domain,
                "shop_gid": shop["id"],
                "source_account_realm": _source_account_realm(context),
            },
        )

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
        orders_api = str(context.config.get("orders_api") or "rest").lower()
        if orders_api not in {"rest", "rest_webhook", "graphql"}:
            return AdapterResult(
                success=False,
                status=AdapterStatus.PERMANENT_ERROR,
                error_code="orders_api_invalid",
                retryable=False,
                data={"detail": "orders_api must be rest, rest_webhook, or graphql"},
            )
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
        if orders_api == "graphql" and not _source_account_realm(context):
            return AdapterResult(
                success=False,
                status=AdapterStatus.PERMANENT_ERROR,
                error_code="source_account_realm_invalid",
                retryable=False,
                data={"detail": "GraphQL source_account_realm must be explicitly live or test"},
            )
        cred = _credential_dict(context)
        account: Optional[ProviderAccount] = None
        # Live lookup only when a credential is present; structural discovery
        # must never require live auth.
        if any(cred.get(key) for key in ("shop_access_token", "api_key")):
            try:
                account = await _fetch_shop_account(context, shop_domain, cred)
            except _ShopifyAccountFailure as exc:
                return AdapterResult(
                    success=False,
                    status=exc.status,
                    error_code=exc.code,
                    retryable=exc.status
                    in (AdapterStatus.RETRYABLE_ERROR, AdapterStatus.RATE_LIMITED),
                    data={"detail": exc.code.replace("_", " ")},
                )
        if orders_api == "graphql" and (account is None or not account.external_id):
            return AdapterResult(
                success=False,
                status=AdapterStatus.RETRYABLE_ERROR,
                error_code="shop_identity_unverified",
                retryable=True,
                data={"detail": "authenticated Shopify shop identity is unavailable"},
            )
        if account is None:
            account = _domain_account(shop_domain)
        return AdapterResult.ok([account])

    async def select_account(
        self, context: AcquisitionContext, *, account_id: str
    ) -> AdapterResult[Any]:
        """Validate the selected account matches the resolved shop."""
        orders_api = str(context.config.get("orders_api") or "rest").lower()
        if orders_api not in {"rest", "rest_webhook", "graphql"}:
            return AdapterResult(
                success=False,
                status=AdapterStatus.PERMANENT_ERROR,
                error_code="orders_api_invalid",
                retryable=False,
            )
        shop_domain = _shop_domain(context)
        if orders_api == "graphql" and not _source_account_realm(context):
            return AdapterResult(
                success=False,
                status=AdapterStatus.PERMANENT_ERROR,
                error_code="source_account_realm_invalid",
                retryable=False,
            )
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
