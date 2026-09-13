"""Walmart Marketplace account discovery and selection (:class:`AccountAdapter`).

Walmart orders are scoped to ONE marketplace seller (the consumer id). Discovery
returns a single :class:`ProviderAccount` keyed ``seller:{consumer_id}``.
Discovery NEVER requires live auth — it is a deterministic, network-free
structural derivation from the credential's ``consumer_id`` (mirroring the
reference Shopify pattern's never-requires-auth rule).
"""

from __future__ import annotations

from typing import Any

from shared.integration_contracts.acquisition import AcquisitionContext, ProviderAccount
from shared.integration_contracts.results import AdapterResult, AdapterStatus

from services.providers.walmart.auth import _credential_dict


def _seller_account(consumer_id: str) -> ProviderAccount:
    """Deterministic, network-free account derived from the consumer id."""
    return ProviderAccount(
        account_id=f"seller:{consumer_id}",
        display_name=f"Walmart seller {consumer_id}",
        external_id=consumer_id,
        currency=None,
        metadata={"consumer_id": consumer_id},
    )


class WalmartAccountAdapter:
    """AccountAdapter: single seller account, discovery never requires auth."""

    async def discover_accounts(
        self, context: AcquisitionContext
    ) -> AdapterResult[list[ProviderAccount]]:
        consumer_id = str(_credential_dict(context).get("consumer_id") or "").strip()
        if not consumer_id:
            return AdapterResult(
                success=False,
                status=AdapterStatus.PERMANENT_ERROR,
                error_code="consumer_id_missing",
                retryable=False,
                data={"detail": "consumer_id is required for account discovery"},
            )
        return AdapterResult.ok([_seller_account(consumer_id)])

    async def select_account(
        self, context: AcquisitionContext, *, account_id: str
    ) -> AdapterResult[Any]:
        """Validate the selected account matches the credential's consumer_id."""
        consumer_id = str(_credential_dict(context).get("consumer_id") or "").strip()
        expected = f"seller:{consumer_id}"
        if account_id == expected:
            return AdapterResult.ok({"account_id": account_id})
        return AdapterResult(
            success=False,
            status=AdapterStatus.PERMANENT_ERROR,
            error_code="account_mismatch",
            retryable=False,
            data={"detail": f"account_id {account_id!r} does not match resolved seller {expected!r}"},
        )


__all__ = ["WalmartAccountAdapter", "_seller_account"]
