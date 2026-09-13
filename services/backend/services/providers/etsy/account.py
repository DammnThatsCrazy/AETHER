"""Etsy account discovery and selection (:class:`AccountAdapter`).

Etsy orders are scoped to ONE shop per credential: the ``shop_id`` the OAuth
credential was minted for. Discovery returns a single :class:`ProviderAccount`
keyed ``shop:{shop_id}``. Discovery NEVER requires live auth — it is a
deterministic, network-free structural derivation from the credential's
``shop_id`` (mirroring the reference Shopify pattern's never-requires-auth
rule).
"""

from __future__ import annotations

from typing import Any

from shared.integration_contracts.acquisition import AcquisitionContext, ProviderAccount
from shared.integration_contracts.results import AdapterResult, AdapterStatus

from services.providers.etsy.auth import _credential_dict


def _shop_account(shop_id: str) -> ProviderAccount:
    """Deterministic, network-free account derived from the shop id."""
    return ProviderAccount(
        account_id=f"shop:{shop_id}",
        display_name=f"Etsy shop {shop_id}",
        external_id=shop_id,
        currency=None,
        metadata={"shop_id": shop_id},
    )


class EtsyAccountAdapter:
    """AccountAdapter: single shop account, discovery never requires auth."""

    async def discover_accounts(
        self, context: AcquisitionContext
    ) -> AdapterResult[list[ProviderAccount]]:
        shop_id = str(_credential_dict(context).get("shop_id") or "").strip()
        if not shop_id:
            return AdapterResult(
                success=False,
                status=AdapterStatus.PERMANENT_ERROR,
                error_code="shop_id_missing",
                retryable=False,
                data={"detail": "shop_id is required for account discovery"},
            )
        return AdapterResult.ok([_shop_account(shop_id)])

    async def select_account(
        self, context: AcquisitionContext, *, account_id: str
    ) -> AdapterResult[Any]:
        """Validate the selected account matches the credential's shop_id."""
        shop_id = str(_credential_dict(context).get("shop_id") or "").strip()
        expected = f"shop:{shop_id}"
        if account_id == expected:
            return AdapterResult.ok({"account_id": account_id})
        return AdapterResult(
            success=False,
            status=AdapterStatus.PERMANENT_ERROR,
            error_code="account_mismatch",
            retryable=False,
            data={"detail": f"account_id {account_id!r} does not match resolved shop {expected!r}"},
        )


__all__ = ["EtsyAccountAdapter", "_shop_account"]
