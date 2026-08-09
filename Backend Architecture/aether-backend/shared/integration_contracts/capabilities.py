"""Provider-neutral capability adapters (the typed acquisition seam).

Each protocol names ONE acquisition capability. An adapter that does not
implement a capability does not exist on the plugin (its accessor returns
``None``); an adapter that implements a capability but cannot handle a specific
operation returns :func:`AdapterResult.not_supported <shared.integration_contracts.results.AdapterResult.not_supported>`
for that operation — adapters NEVER raise for an unsupported operation.

Every async protocol method returns :class:`AdapterResult`, so success/failure,
retryability, and rate-limit signals travel in the same envelope.

:data:`CAPABILITY_ADAPTER_METHODS` maps each plugin accessor attribute name to
the protocol methods a conforming adapter must expose — the certification
harness uses it to verify protocol conformance structurally.
"""

from __future__ import annotations

from typing import Any, Mapping, Optional, Protocol

from shared.integration_contracts.acquisition import AcquisitionContext, ProviderAccount
from shared.integration_contracts.events import RawProviderRecord, ReadBatch
from shared.integration_contracts.results import AdapterResult


class AuthAdapter(Protocol):
    """Credential validation and live connectivity test."""

    async def validate_credentials(
        self, context: AcquisitionContext
    ) -> AdapterResult[Any]: ...

    async def test(self, context: AcquisitionContext) -> AdapterResult[Any]: ...


class AccountAdapter(Protocol):
    """Account discovery and selection for multi-account providers."""

    async def discover_accounts(
        self, context: AcquisitionContext
    ) -> AdapterResult[list[ProviderAccount]]: ...

    async def select_account(
        self, context: AcquisitionContext, *, account_id: str
    ) -> AdapterResult[Any]: ...


class PullAdapter(Protocol):
    """Cursor-addressable pull ingestion (poll sync)."""

    async def fetch(
        self,
        context: AcquisitionContext,
        *,
        cursor: Optional[str],
        limit: Optional[int] = None,
    ) -> AdapterResult[ReadBatch]: ...

    async def initial_backfill(
        self, context: AcquisitionContext
    ) -> AdapterResult[ReadBatch]: ...


class WebhookAdapter(Protocol):
    """Inbound webhook verification and payload parsing."""

    def verify(
        self, raw_body: bytes, headers: Mapping[str, str], secret: Optional[str]
    ) -> bool: ...

    def parse(
        self, payload: dict[str, Any], *, headers: Mapping[str, str]
    ) -> list[RawProviderRecord]: ...


class ReportAdapter(Protocol):
    """Report-based ingestion (provider maintains the report)."""

    async def fetch_report(
        self, context: AcquisitionContext, *, report: str
    ) -> AdapterResult[list[RawProviderRecord]]: ...


class StreamAdapter(Protocol):
    """Stream/subscription-based ingestion."""

    async def subscribe(self, context: AcquisitionContext) -> AdapterResult[Any]: ...


class ReconciliationAdapter(Protocol):
    """Snapshot-based reconciliation between provider state and ours."""

    async def snapshot(
        self, context: AcquisitionContext, *, since: Optional[str]
    ) -> AdapterResult[list[RawProviderRecord]]: ...


# Adapter attribute name -> the protocol methods a conforming adapter exposes.
# ``adapter_attr`` keys match the :class:`CapabilitySet` field names and the
# :class:`ProviderPlugin` accessor names.
CAPABILITY_ADAPTER_METHODS: Mapping[str, tuple[str, ...]] = {
    "auth": ("validate_credentials", "test"),
    "account": ("discover_accounts", "select_account"),
    "pull": ("fetch", "initial_backfill"),
    "webhook": ("verify", "parse"),
    "report": ("fetch_report",),
    "stream": ("subscribe",),
    "reconciliation": ("snapshot",),
}


__all__ = [
    "CAPABILITY_ADAPTER_METHODS",
    "AccountAdapter",
    "AuthAdapter",
    "PullAdapter",
    "ReconciliationAdapter",
    "ReportAdapter",
    "StreamAdapter",
    "WebhookAdapter",
]
