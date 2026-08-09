"""WooCommerce account discovery and selection (:class:`AccountAdapter`).

WooCommerce has ONE account per store site: the store itself. Discovery returns
a single :class:`ProviderAccount` keyed ``site:{host}``. Discovery NEVER
requires live auth — it is a deterministic, network-free structural derivation
from the SSRF-validated ``site_url`` host (mirroring the reference Shopify
pattern's never-requires-auth rule).
"""

from __future__ import annotations

from typing import Any

from shared.integration_contracts.acquisition import AcquisitionContext, ProviderAccount
from shared.integration_contracts.results import AdapterResult, AdapterStatus

from services.providers.woocommerce.auth import _raw_site_url, _site_host


def _site_account(host: str) -> ProviderAccount:
    """Deterministic, network-free account derived from the store host."""
    return ProviderAccount(
        account_id=f"site:{host}",
        display_name=host,
        external_id=None,
        currency=None,
        metadata={"site_host": host, "site_id": None},
    )


class WooCommerceAccountAdapter:
    """AccountAdapter: single store account, discovery never requires auth."""

    async def discover_accounts(
        self, context: AcquisitionContext
    ) -> AdapterResult[list[ProviderAccount]]:
        raw_url = _raw_site_url(context)
        host = _site_host(context)  # validated allowlisted host
        if not raw_url:
            return AdapterResult(
                success=False,
                status=AdapterStatus.PERMANENT_ERROR,
                error_code="site_url_missing",
                retryable=False,
                data={"detail": "site_url is required for account discovery"},
            )
        if not host:
            return AdapterResult(
                success=False,
                status=AdapterStatus.PERMANENT_ERROR,
                error_code="site_url_invalid",
                retryable=False,
                data={
                    "detail": "site_url is not a valid public https host "
                    "(structural gate; resolver-level check required at live-auth time)"
                },
            )
        return AdapterResult.ok([_site_account(host)])

    async def select_account(
        self, context: AcquisitionContext, *, account_id: str
    ) -> AdapterResult[Any]:
        """Validate the selected account matches the resolved store host."""
        host = _site_host(context)
        expected = f"site:{host}"
        if account_id == expected:
            return AdapterResult.ok({"account_id": account_id})
        return AdapterResult(
            success=False,
            status=AdapterStatus.PERMANENT_ERROR,
            error_code="account_mismatch",
            retryable=False,
            data={"detail": f"account_id {account_id!r} does not match resolved store {expected!r}"},
        )


__all__ = ["WooCommerceAccountAdapter", "_site_account"]
