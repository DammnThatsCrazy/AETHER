"""eBay account discovery and selection (:class:`AccountAdapter`).

eBay orders are scoped to the authenticated eBay user (the OAuth token holder).
Discovery returns a single :class:`ProviderAccount` keyed ``user:ebay`` — the
OAuth token is the account. Discovery NEVER requires live auth — it is a
deterministic, network-free structural result (mirroring the reference Shopify
pattern's never-requires-auth rule).
"""

from __future__ import annotations

from typing import Any

from shared.integration_contracts.acquisition import AcquisitionContext, ProviderAccount
from shared.integration_contracts.results import AdapterResult, AdapterStatus

from services.providers.ebay.auth import _credential_dict


def _ebay_account() -> ProviderAccount:
    """Deterministic, network-free default eBay account."""
    return ProviderAccount(
        account_id="user:ebay",
        display_name="eBay authenticated user",
        external_id=None,
        currency=None,
        metadata={"account_scope": "oauth_user"},
    )


class EbayAccountAdapter:
    """AccountAdapter: single OAuth-scoped account, discovery never requires auth."""

    async def discover_accounts(
        self, context: AcquisitionContext
    ) -> AdapterResult[list[ProviderAccount]]:
        if not any(_credential_dict(context).get(key) for key in ("refresh_token", "access_token")):
            return AdapterResult(
                success=False,
                status=AdapterStatus.PERMANENT_ERROR,
                error_code="credential_missing_fields",
                retryable=False,
                data={"detail": "an OAuth token is required for account discovery"},
            )
        return AdapterResult.ok([_ebay_account()])

    async def select_account(
        self, context: AcquisitionContext, *, account_id: str
    ) -> AdapterResult[Any]:
        if account_id == "user:ebay":
            return AdapterResult.ok({"account_id": account_id})
        return AdapterResult(
            success=False,
            status=AdapterStatus.PERMANENT_ERROR,
            error_code="account_mismatch",
            retryable=False,
            data={"detail": f"account_id {account_id!r} is not the ebay OAuth account"},
        )


__all__ = ["EbayAccountAdapter", "_ebay_account"]
