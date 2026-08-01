"""Canonical ``IntegrationAdapter`` facade (§17) — the Integration Control Plane keystone.

This module composes the pieces built by the earlier waves into the single
lifecycle contract every capability adapter presents:

* :class:`IntegrationAdapter` is the abstract §17 lifecycle interface. Every
  operation returns a typed :class:`AdapterResult`, and the *default* for each
  is an honest ``not_supported`` — a subclass overrides only what it genuinely
  implements and an unsupported op is a typed result, never an exception.
* :class:`ConnectorIntegrationAdapter` is the concrete adapter for AETHER's
  existing inbound connectors. It does not re-implement provider I/O: it
  delegates to the existing :class:`BaseConnector`, resolves secrets through the
  credential platform, delegates OAuth to the :class:`AuthorizationBroker`, and
  maps the connector's legacy result types onto :class:`AdapterResult` via the
  bridge mappers in ``shared.integration_contracts.results``.

The wave is additive: nothing here mutates the connector framework, the manifest
system, the credential service, or the OAuth broker. Capability is gated by the
provider's :class:`ProviderManifest`, so the adapter never claims more than the
manifest honestly declares.
"""

from __future__ import annotations

import abc
import time
from dataclasses import dataclass
from typing import Any, Optional

from services.integrations.connectors.base import (
    BaseConnector,
    ConnectorConfig,
    ConnectorSyncStatus,
    NormalizedEvent,
    SyncResult,
)
from services.integrations.connectors.registry import get_connector
from services.integrations.oauth.broker import (
    AuthorizationBroker,
    AuthorizationResult,
    OAuthBrokerError,
)
from services.integrations.oauth.provider_config import OAuthProviderConfig
from shared.credentials.service import (
    CredentialService,
    connector_ref,
    credential_service,
)
from shared.integration_contracts.catalog import manifest_by_family
from shared.integration_contracts.identity import (
    CapabilityId,
    ProductId,
    ProviderFamily,
    ProviderIdentity,
)
from shared.integration_contracts.lifecycle import (
    ConnectionState,
    from_connector_sync_status,
)
from shared.integration_contracts.manifest import ProviderManifest
from shared.integration_contracts.results import (
    AdapterResult,
    AdapterStatus,
    from_connection_test,
    from_sync_result,
)

# ── Shared helpers ──────────────────────────────────────────────────────────

# Projection of a connector's coarse sync status onto (success, AdapterStatus)
# for :meth:`health_check`. Mirrors ``results._SYNC_STATUS_MAP`` but keyed to a
# bare status (no ``SyncResult`` in hand).
_HEALTH_STATUS_MAP: dict[str, tuple[bool, AdapterStatus]] = {
    "healthy": (True, AdapterStatus.OK),
    "syncing": (True, AdapterStatus.OK),
    "never_synced": (True, AdapterStatus.OK),
    "degraded": (False, AdapterStatus.RETRYABLE_ERROR),
    "failed": (False, AdapterStatus.RETRYABLE_ERROR),
    "disabled": (False, AdapterStatus.PERMANENT_ERROR),
}


def _elapsed_ms(start: float) -> float:
    """Wall-independent elapsed milliseconds since a ``time.perf_counter`` mark."""
    return (time.perf_counter() - start) * 1000.0


def _authorization_data(result: AuthorizationResult) -> dict[str, Any]:
    """Secret-free projection of an :class:`AuthorizationResult` for result data."""
    return {
        "identity_key": result.identity_key,
        "credential_ref": result.credential_ref,
        "scope": list(result.scope),
        "expires_at": result.expires_at,
        "masked_identifier": result.masked_identifier,
        "refreshed": result.refreshed,
    }


@dataclass
class AdapterContext:
    """The per-call context threaded through every lifecycle operation.

    ``config`` is the connector's tenant-scoped, non-secret configuration.
    Secret resolution prefers an explicitly injected ``secret`` (used by tests
    and pre-resolved callers), then ``secret_ref``, then the connector's
    ``config.secret_ref``, and finally the canonical
    ``connector:{tenant}:{type}`` ref.
    """

    tenant_id: str
    connector_type: str
    config: Optional[ConnectorConfig] = None
    secret_ref: Optional[str] = None
    secret: Optional[str] = None
    correlation_id: Optional[str] = None


# ── The §17 lifecycle contract ──────────────────────────────────────────────


class IntegrationAdapter(abc.ABC):
    """Abstract §17 lifecycle interface.

    Every operation returns a typed :class:`AdapterResult`. The default for each
    is a typed ``not_supported`` result so a subclass only overrides what it
    genuinely supports; adapters must never *raise* for an unsupported op.
    :meth:`normalize` is the one synchronous hook and defaults to identity.
    """

    # ── Authorization / credentials ──
    async def begin_authorization(
        self,
        context: AdapterContext,
        *,
        redirect_uri: Optional[str] = None,
        oauth_config: Optional[OAuthProviderConfig] = None,
        extra_params: Optional[dict[str, str]] = None,
    ) -> AdapterResult[Any]:
        return AdapterResult.not_supported("begin_authorization")

    async def complete_authorization(
        self,
        context: AdapterContext,
        *,
        state: Optional[str] = None,
        code: Optional[str] = None,
    ) -> AdapterResult[Any]:
        return AdapterResult.not_supported("complete_authorization")

    async def validate_credentials(
        self,
        context: AdapterContext,
        credentials: Optional[str] = None,
    ) -> AdapterResult[Any]:
        return AdapterResult.not_supported("validate_credentials")

    async def rotate_credentials(
        self,
        context: AdapterContext,
        *,
        oauth_config: Optional[OAuthProviderConfig] = None,
    ) -> AdapterResult[Any]:
        return AdapterResult.not_supported("rotate_credentials")

    # ── Account / configuration setup ──
    async def discover_accounts(self, context: AdapterContext) -> AdapterResult[Any]:
        return AdapterResult.not_supported("discover_accounts")

    async def select_account(
        self, context: AdapterContext, *, account_id: Optional[str] = None
    ) -> AdapterResult[Any]:
        return AdapterResult.not_supported("select_account")

    async def validate_configuration(self, context: AdapterContext) -> AdapterResult[Any]:
        return AdapterResult.not_supported("validate_configuration")

    # ── Webhooks ──
    async def register_webhooks(self, context: AdapterContext) -> AdapterResult[Any]:
        return AdapterResult.not_supported("register_webhooks")

    async def verify_webhook_registration(
        self, context: AdapterContext
    ) -> AdapterResult[Any]:
        return AdapterResult.not_supported("verify_webhook_registration")

    # ── Sync ──
    async def run_initial_backfill(self, context: AdapterContext) -> AdapterResult[Any]:
        return AdapterResult.not_supported("run_initial_backfill")

    async def run_incremental_sync(
        self, context: AdapterContext, cursor: Optional[str] = None
    ) -> AdapterResult[Any]:
        return AdapterResult.not_supported("run_incremental_sync")

    async def reconcile(self, context: AdapterContext) -> AdapterResult[Any]:
        return AdapterResult.not_supported("reconcile")

    # ── Operational ──
    async def health_check(self, context: AdapterContext) -> AdapterResult[Any]:
        return AdapterResult.not_supported("health_check")

    async def disconnect(self, context: AdapterContext) -> AdapterResult[Any]:
        return AdapterResult.not_supported("disconnect")

    async def revoke_upstream_authorization(
        self, context: AdapterContext
    ) -> AdapterResult[Any]:
        return AdapterResult.not_supported("revoke_upstream_authorization")

    # ── Normalization (synchronous) ──
    def normalize(self, raw_record: Any) -> Any:
        """Map a raw provider record toward the canonical envelope.

        Default is identity; a subclass delegates to the provider's normalizer.
        """
        return raw_record


# ── Concrete adapter over an existing BaseConnector ─────────────────────────


class ConnectorIntegrationAdapter(IntegrationAdapter):
    """Adapt an existing inbound :class:`BaseConnector` to the §17 contract.

    Honest by construction: capability is gated by ``manifest`` (OAuth only when
    ``authentication.type == "oauth2"`` *and* a broker is wired; incremental
    sync only when ``sync.incremental``; backfill only when
    ``sync.initial_backfill``). Everything the connector/manifest does not
    evidence returns ``not_supported`` — the adapter fabricates nothing.
    """

    def __init__(
        self,
        *,
        connector: BaseConnector,
        manifest: ProviderManifest,
        broker: Optional[AuthorizationBroker] = None,
        credentials: Optional[CredentialService] = None,
    ) -> None:
        self.connector = connector
        self.manifest = manifest
        self.broker = broker
        self._credentials = credentials or credential_service

    # ── Internal helpers ──
    def _config(self, context: AdapterContext) -> ConnectorConfig:
        if context.config is not None:
            return context.config
        return ConnectorConfig(
            tenant_id=context.tenant_id,
            connector_type=context.connector_type,  # type: ignore[arg-type]
        )

    async def _resolve_secret(self, context: AdapterContext) -> Optional[str]:
        if context.secret is not None:
            return context.secret
        ref = context.secret_ref
        if ref is None and context.config is not None:
            ref = context.config.secret_ref
        if ref is None:
            ref = connector_ref(context.tenant_id, context.connector_type)
        return await self._credentials.reveal(context.tenant_id, ref)

    def _identity(self) -> ProviderIdentity:
        return ProviderIdentity(
            family=ProviderFamily(self.manifest.provider_family),
            product=ProductId(self.manifest.product_id),
            capability=CapabilityId(self.manifest.capability_id),
        )

    def _oauth_ready(self) -> bool:
        return (
            self.manifest.authentication.type == "oauth2" and self.broker is not None
        )

    def _wrap_pull(
        self,
        result: "list[NormalizedEvent] | SyncResult",
        *,
        cursor: Optional[str],
        latency_ms: float,
        correlation_id: Optional[str],
    ) -> AdapterResult[Any]:
        """Wrap a connector pull (event list or ``SyncResult``) into a result."""
        if isinstance(result, SyncResult):
            return from_sync_result(result).model_copy(
                update={
                    "latency_ms": latency_ms,
                    "correlation_id": correlation_id,
                    "data": list(result.events),
                    "account": {"cursor": cursor, "event_count": result.events_ingested},
                }
            )
        events = list(result)
        next_cursor = events[-1].occurred_at if events else cursor
        return AdapterResult.ok(
            data=events,
            latency_ms=latency_ms,
            correlation_id=correlation_id,
            account={
                "cursor": cursor,
                "next_cursor": next_cursor,
                "event_count": len(events),
            },
        )

    # ── Authorization / credentials ──
    async def begin_authorization(
        self,
        context: AdapterContext,
        *,
        redirect_uri: Optional[str] = None,
        oauth_config: Optional[OAuthProviderConfig] = None,
        extra_params: Optional[dict[str, str]] = None,
    ) -> AdapterResult[Any]:
        if not self._oauth_ready():
            return AdapterResult.not_supported("begin_authorization")
        if not redirect_uri:
            return AdapterResult(
                success=False,
                status=AdapterStatus.PERMANENT_ERROR,
                error_code="redirect_uri_required",
                correlation_id=context.correlation_id,
            )
        assert self.broker is not None  # narrowed by _oauth_ready
        try:
            challenge = await self.broker.build_authorization_url(
                context.tenant_id,
                self._identity(),
                oauth_config,  # type: ignore[arg-type]
                redirect_uri,
                extra_params=extra_params,
            )
        except OAuthBrokerError as exc:
            return AdapterResult(
                success=False,
                status=AdapterStatus.UNAUTHORIZED,
                error_code=exc.reason,
                correlation_id=context.correlation_id,
            )
        return AdapterResult.ok(
            data={"authorization_url": challenge.url, "state": challenge.state},
            correlation_id=context.correlation_id,
        )

    async def complete_authorization(
        self,
        context: AdapterContext,
        *,
        state: Optional[str] = None,
        code: Optional[str] = None,
    ) -> AdapterResult[Any]:
        if not self._oauth_ready():
            return AdapterResult.not_supported("complete_authorization")
        if not state or not code:
            return AdapterResult(
                success=False,
                status=AdapterStatus.PERMANENT_ERROR,
                error_code="state_and_code_required",
                correlation_id=context.correlation_id,
            )
        assert self.broker is not None
        try:
            result = await self.broker.complete_authorization(state, code)
        except OAuthBrokerError as exc:
            return AdapterResult(
                success=False,
                status=AdapterStatus.UNAUTHORIZED,
                error_code=exc.reason,
                correlation_id=context.correlation_id,
            )
        return AdapterResult.ok(
            data=_authorization_data(result), correlation_id=context.correlation_id
        )

    async def validate_credentials(
        self,
        context: AdapterContext,
        credentials: Optional[str] = None,
    ) -> AdapterResult[Any]:
        start = time.perf_counter()
        config = self._config(context)
        secret = (
            credentials if credentials is not None else await self._resolve_secret(context)
        )
        result = await self.connector.test_connection(config, secret=secret)
        return from_connection_test(result).model_copy(
            update={
                "latency_ms": _elapsed_ms(start),
                "correlation_id": context.correlation_id,
            }
        )

    async def rotate_credentials(
        self,
        context: AdapterContext,
        *,
        oauth_config: Optional[OAuthProviderConfig] = None,
    ) -> AdapterResult[Any]:
        # Only OAuth token refresh is a first-class, honest rotation here; an
        # api_key rotation needs new key material we cannot fabricate.
        if not self._oauth_ready():
            return AdapterResult.not_supported("rotate_credentials")
        assert self.broker is not None
        try:
            result = await self.broker.refresh(
                context.tenant_id,
                self._identity(),
                oauth_config,  # type: ignore[arg-type]
            )
        except OAuthBrokerError as exc:
            return AdapterResult(
                success=False,
                status=AdapterStatus.UNAUTHORIZED,
                error_code=exc.reason,
                correlation_id=context.correlation_id,
            )
        return AdapterResult.ok(
            data=_authorization_data(result), correlation_id=context.correlation_id
        )

    # ── Configuration ──
    async def validate_configuration(self, context: AdapterContext) -> AdapterResult[Any]:
        config = self._config(context)
        try:
            self.connector.validate_config(config)
        except ValueError as exc:
            return AdapterResult(
                success=False,
                status=AdapterStatus.PERMANENT_ERROR,
                error_code="invalid_configuration",
                correlation_id=context.correlation_id,
                data={"detail": str(exc)},
            )
        return AdapterResult.ok(
            data={"detail": "configuration valid"},
            correlation_id=context.correlation_id,
        )

    # ── Sync ──
    async def run_initial_backfill(self, context: AdapterContext) -> AdapterResult[Any]:
        if not self.manifest.sync.initial_backfill:
            return AdapterResult.not_supported("run_initial_backfill")
        start = time.perf_counter()
        config = self._config(context)
        secret = await self._resolve_secret(context)
        result = await self.connector.pull(config, since=None, secret=secret)
        return self._wrap_pull(
            result,
            cursor=None,
            latency_ms=_elapsed_ms(start),
            correlation_id=context.correlation_id,
        )

    async def run_incremental_sync(
        self, context: AdapterContext, cursor: Optional[str] = None
    ) -> AdapterResult[Any]:
        if not self.manifest.sync.incremental:
            return AdapterResult.not_supported("run_incremental_sync")
        start = time.perf_counter()
        config = self._config(context)
        secret = await self._resolve_secret(context)
        result = await self.connector.pull(config, since=cursor, secret=secret)
        return self._wrap_pull(
            result,
            cursor=cursor,
            latency_ms=_elapsed_ms(start),
            correlation_id=context.correlation_id,
        )

    # ── Operational ──
    async def health_check(self, context: AdapterContext) -> AdapterResult[Any]:
        config = self._config(context)
        status: ConnectorSyncStatus = config.sync_status
        state: ConnectionState = from_connector_sync_status(status)
        success, adapter_status = _HEALTH_STATUS_MAP.get(
            status, (False, AdapterStatus.PERMANENT_ERROR)
        )
        data = {
            "sync_status": status,
            "lifecycle_state": state.value,
            "last_synced_at": config.last_synced_at,
            "error_count": config.error_count,
        }
        if success:
            return AdapterResult.ok(data=data, correlation_id=context.correlation_id)
        return AdapterResult(
            success=False,
            status=adapter_status,
            error_code=f"health:{status}",
            retryable=adapter_status == AdapterStatus.RETRYABLE_ERROR,
            correlation_id=context.correlation_id,
            data=data,
        )

    async def disconnect(self, context: AdapterContext) -> AdapterResult[Any]:
        # Minimal, honest local-state flip. Upstream revocation is a separate,
        # explicitly-unsupported operation here.
        previous: Optional[str] = None
        if context.config is not None:
            previous = context.config.sync_status
            context.config.enabled = False
            context.config.sync_status = "disabled"
        return AdapterResult.ok(
            data={
                "disconnected": True,
                "connector_type": context.connector_type,
                "previous_sync_status": previous,
            },
            correlation_id=context.correlation_id,
        )

    # ── Normalization ──
    def normalize(self, raw_record: Any) -> Any:
        normalizer = getattr(self.connector, "normalize", None)
        if callable(normalizer):
            return normalizer(raw_record)
        return raw_record


# ── Factory ─────────────────────────────────────────────────────────────────


def integration_adapter_for(
    connector_type: str,
    *,
    broker: Optional[AuthorizationBroker] = None,
    credentials: Optional[CredentialService] = None,
) -> ConnectorIntegrationAdapter:
    """Build a :class:`ConnectorIntegrationAdapter` for a registered connector.

    Pulls the connector from the registry and its honest manifest from the
    derived catalog. Raises :class:`KeyError` for an unknown connector type so a
    miswired call fails loudly rather than producing a silently-inert adapter.
    """
    connector = get_connector(connector_type)
    if connector is None:
        raise KeyError(f"no connector registered for {connector_type!r}")
    manifest = manifest_by_family.get(connector_type)
    if manifest is None:
        raise KeyError(f"no manifest for connector {connector_type!r}")
    return ConnectorIntegrationAdapter(
        connector=connector,
        manifest=manifest,
        broker=broker,
        credentials=credentials,
    )


__all__ = [
    "AdapterContext",
    "ConnectorIntegrationAdapter",
    "IntegrationAdapter",
    "integration_adapter_for",
]
