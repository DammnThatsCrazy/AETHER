"""Provider adapter base — ABC + registry + error types.

Every provider adapter must subclass ProviderAdapter and implement `dispatch()`.
The ProviderAdapterRegistry is a singleton; call `ProviderAdapterRegistry.default()`
to get the pre-registered registry with all built-in adapters.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Optional


# ─── Error hierarchy ─────────────────────────────────────────────────────────

class DeliveryError(Exception):
    """Base class for all delivery-layer errors."""


class ProviderError(DeliveryError):
    """Non-retryable provider error (e.g., bad credentials, 4xx)."""

    def __init__(self, message: str, http_status: Optional[int] = None) -> None:
        super().__init__(message)
        self.http_status = http_status


class RetryableProviderError(DeliveryError):
    """Transient provider error — the job should be retried (e.g., 429, 5xx)."""

    def __init__(self, message: str, http_status: Optional[int] = None,
                 retry_after_seconds: Optional[int] = None) -> None:
        super().__init__(message)
        self.http_status = http_status
        self.retry_after_seconds = retry_after_seconds


class ConfigurationError(DeliveryError):
    """Adapter is misconfigured — missing credentials or unsupported settings."""


class SSRFBlockedError(DeliveryError):
    """Outbound URL resolves to a private/loopback address — request blocked."""


class ConnectorSyncError(DeliveryError):
    """Connector sync failed and health has been updated to error state."""

    def __init__(self, message: str, connector_type: str, tenant_id: str) -> None:
        super().__init__(message)
        self.connector_type = connector_type
        self.tenant_id = tenant_id


# ─── AdapterReceipt ──────────────────────────────────────────────────────────

class AdapterReceipt:
    """Return value from ProviderAdapter.dispatch() — carries the external_id."""

    __slots__ = ("external_id", "raw_response", "http_status")

    def __init__(self, external_id: str, raw_response: dict[str, Any],
                 http_status: int = 200) -> None:
        if not external_id:
            raise ValueError("AdapterReceipt.external_id must not be empty")
        if external_id.startswith("sim-"):
            raise ValueError(
                f"AdapterReceipt.external_id {external_id!r} is a simulated ID. "
                "Provider adapters must return real external IDs."
            )
        self.external_id = external_id
        self.raw_response = raw_response
        self.http_status = http_status

    def __repr__(self) -> str:
        return f"AdapterReceipt(external_id={self.external_id!r}, http_status={self.http_status})"


# ─── ProviderAdapter ABC ─────────────────────────────────────────────────────

class ProviderAdapter(ABC):
    """Abstract base for all delivery provider adapters."""

    #: Matches `DeliveryJob.provider_adapter`
    adapter_name: str = ""

    @abstractmethod
    async def dispatch(
        self,
        payload: dict[str, Any],
        provider_config: dict[str, Any],
        *,
        credential: Optional[str] = None,
        idempotency_key: Optional[str] = None,
    ) -> AdapterReceipt:
        """Dispatch a payload to the provider.

        Args:
            payload: The message payload (title, body, etc.).
            provider_config: Channel-level config (workspace_id, channel_id, etc.).
            credential: Resolved secret from the vault (token, API key).
            idempotency_key: Provider-level deduplication key where supported.

        Returns:
            AdapterReceipt with a real provider external_id.

        Raises:
            ProviderError: Non-retryable — bad credentials, 4xx, etc.
            RetryableProviderError: Transient — rate-limit, 5xx.
            ConfigurationError: Missing required config or credential.
        """

    async def verify_inbound(
        self,
        raw_body: bytes,
        headers: dict[str, str],
        *,
        credential: Optional[str] = None,
    ) -> bool:
        """Verify an inbound webhook signature. Default: always accept (override per provider)."""
        return True


# ─── ProviderAdapterRegistry ─────────────────────────────────────────────────

class ProviderAdapterRegistry:
    """Registry of named ProviderAdapter instances."""

    def __init__(self) -> None:
        self._adapters: dict[str, ProviderAdapter] = {}

    def register(self, adapter: ProviderAdapter) -> None:
        self._adapters[adapter.adapter_name] = adapter

    def get(self, adapter_name: str) -> Optional[ProviderAdapter]:
        return self._adapters.get(adapter_name)

    def get_or_raise(self, adapter_name: str) -> ProviderAdapter:
        adapter = self._adapters.get(adapter_name)
        if adapter is None:
            raise ConfigurationError(
                f"No provider adapter registered for {adapter_name!r}. "
                f"Available: {list(self._adapters)}"
            )
        return adapter

    def list_names(self) -> list[str]:
        return list(self._adapters)

    @classmethod
    def default(cls) -> "ProviderAdapterRegistry":
        """Build and return the registry with all built-in adapters registered."""
        from services.delivery.adapters.slack import SlackAdapter
        from services.delivery.adapters.webhook import WebhookAdapter
        from services.delivery.adapters.linear import LinearAdapter
        from services.delivery.adapters.jira import JiraAdapter
        from services.delivery.adapters.crm import CRMAdapter
        from services.delivery.adapters.marketing import MarketingAdapter
        from services.delivery.adapters.ticketing import TicketingAdapter
        from services.delivery.adapters.agent_assist import AgentAssistAdapter

        registry = cls()
        registry.register(SlackAdapter())
        registry.register(WebhookAdapter())
        registry.register(LinearAdapter())
        registry.register(JiraAdapter())
        registry.register(CRMAdapter())
        registry.register(MarketingAdapter())
        registry.register(TicketingAdapter())
        registry.register(AgentAssistAdapter())
        return registry
