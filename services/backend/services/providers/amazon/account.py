"""Amazon account discovery and selection (:class:`AccountAdapter`).

Amazon orders are scoped to the authenticated seller marketplace (the LWA
credential holder, identified by ``seller_id``). Discovery returns a single
:class:`ProviderAccount` keyed ``seller:{seller_id}`` — the seller_id is the
account. Discovery NEVER requires live auth — it is a deterministic,
network-free structural result (mirroring the reference Shopify pattern's
never-requires-auth rule).
"""

from __future__ import annotations

from typing import Any

from shared.integration_contracts.acquisition import AcquisitionContext, ProviderAccount
from shared.integration_contracts.results import AdapterResult, AdapterStatus

from services.providers.amazon.auth import _credential_dict


def _amazon_account(seller_id: str) -> ProviderAccount:
    """Deterministic, network-free default Amazon seller account."""
    return ProviderAccount(
        account_id=f"seller:{seller_id}",
        display_name=f"Amazon seller {seller_id}",
        external_id=seller_id,
        currency=None,
        metadata={"account_scope": "seller_marketplace"},
    )


class AmazonAccountAdapter:
    """AccountAdapter: single seller-scoped account, discovery never requires auth."""

    async def discover_accounts(
        self, context: AcquisitionContext
    ) -> AdapterResult[list[ProviderAccount]]:
        seller_id = str(_credential_dict(context).get("seller_id") or "").strip()
        if not seller_id:
            return AdapterResult(
                success=False,
                status=AdapterStatus.PERMANENT_ERROR,
                error_code="credential_missing_fields",
                retryable=False,
                data={"detail": "seller_id is required for account discovery"},
            )
        return AdapterResult.ok([_amazon_account(seller_id)])

    async def select_account(
        self, context: AcquisitionContext, *, account_id: str
    ) -> AdapterResult[Any]:
        seller_id = str(_credential_dict(context).get("seller_id") or "").strip()
        if seller_id and account_id == f"seller:{seller_id}":
            return AdapterResult.ok({"account_id": account_id})
        return AdapterResult(
            success=False,
            status=AdapterStatus.PERMANENT_ERROR,
            error_code="account_mismatch",
            retryable=False,
            data={"detail": f"account_id {account_id!r} is not the amazon seller account"},
        )


__all__ = ["AmazonAccountAdapter", "_amazon_account"]
