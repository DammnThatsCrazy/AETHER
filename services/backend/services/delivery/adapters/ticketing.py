"""Ticketing adapter — delegates to Linear or Jira based on provider_config.

Selects the appropriate underlying adapter based on `provider_config.backend`.
"""

from __future__ import annotations

from typing import Any, Optional

from shared.logger.logger import get_logger

from services.delivery.adapters.base import (
    AdapterReceipt,
    ConfigurationError,
    ProviderAdapter,
)

logger = get_logger("aether.delivery.adapters.ticketing")

_SUPPORTED_BACKENDS = ("linear", "jira")


class TicketingAdapter(ProviderAdapter):
    """Routing ticketing adapter — dispatches to Linear or Jira."""

    adapter_name = "ticketing"

    async def dispatch(
        self,
        payload: dict[str, Any],
        provider_config: dict[str, Any],
        *,
        credential: Optional[str] = None,
        idempotency_key: Optional[str] = None,
    ) -> AdapterReceipt:
        backend = provider_config.get("backend", "").lower()
        if backend not in _SUPPORTED_BACKENDS:
            raise ConfigurationError(
                f"TicketingAdapter requires provider_config.backend to be one of "
                f"{_SUPPORTED_BACKENDS}, got: {backend!r}"
            )

        if backend == "linear":
            from services.delivery.adapters.linear import LinearAdapter
            delegate: ProviderAdapter = LinearAdapter()
        else:  # jira
            from services.delivery.adapters.jira import JiraAdapter
            delegate = JiraAdapter()

        logger.info(f"TicketingAdapter routing to backend={backend!r}")
        receipt = await delegate.dispatch(
            payload,
            provider_config,
            credential=credential,
            idempotency_key=idempotency_key,
        )
        # Re-wrap external_id with backend prefix for traceability
        return AdapterReceipt(
            external_id=f"ticket:{backend}:{receipt.external_id}",
            raw_response=receipt.raw_response,
            http_status=receipt.http_status,
        )
