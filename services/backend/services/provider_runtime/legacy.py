"""Legacy-compatibility plugin — adapt existing BaseConnectors to the UPR seam (Team C).

Every existing inbound connector is wrapped in a :class:`LegacyConnectorPlugin`:
identity ``<connector_type>.ingestion.connector``, a manifest derived from the
connector's own descriptor (re-validated at construction), and adapters that
delegate to the legacy connector wherever the provider-neutral seam maps
cleanly:

* **auth** — ``connector.test_connection`` lifted via
  :func:`from_connection_test <shared.integration_contracts.results.from_connection_test>`;
* **pull** — ``connector.pull`` (the exact ``BaseConnector.pull`` signature) with
  each :class:`NormalizedEvent` wrapped into a :class:`RawProviderRecord`;
* **webhook** — :func:`verify_provider_webhook_signature` for verification and
  ``connector.parse_webhook`` for parsing;
* **account / reconciliation** — adapters exist only when the manifest claims
  the capability, and each operation is an honest
  :func:`AdapterResult.not_supported <shared.integration_contracts.results.AdapterResult.not_supported>`
  where the legacy surface cannot be driven through the neutral context.

The normalizer preserves the legacy provider-namespaced ``event_type`` (e.g.
``email_opened``) rather than renaming into the provider-neutral vocabulary —
renaming is explicitly out of scope for the compatibility plugin.
"""

from __future__ import annotations

import hashlib
import logging
from typing import Any, Mapping, Optional

from services.integrations.connectors.base import (
    BaseConnector,
    ConnectorConfig,
    NormalizedEvent,
)
from services.integrations.webhook_policy import verify_provider_webhook_signature
from shared.credentials.types import StructuredCredential, to_plaintext_json
from shared.integration_contracts.acquisition import AcquisitionContext, ProviderAccount
from shared.integration_contracts.capabilities import (
    AccountAdapter,
    AuthAdapter,
    PullAdapter,
    ReconciliationAdapter,
    WebhookAdapter,
)
from shared.integration_contracts.catalog import manifest_from_connector_descriptor
from shared.integration_contracts.events import (
    AetherEvent,
    RawProviderRecord,
    ReadBatch,
    make_raw_record,
)
from shared.integration_contracts.identity import (
    CapabilityId,
    ProductId,
    ProviderFamily,
    ProviderIdentity,
)
from shared.integration_contracts.manifest import (
    ManifestValidationError,
    ProviderManifest,
    validate_manifest,
)
from shared.integration_contracts.normalization import EventNormalizer, NormalizationResult
from shared.integration_contracts.results import AdapterResult, from_connection_test

from services.provider_runtime.errors import ManifestInvalid
from services.provider_runtime.plugin import BaseProviderPlugin

logger = logging.getLogger(__name__)

# Legacy connectors expose one product ("ingestion") with one capability
# ("connector"); the connector_type (family) makes the identity unique.
_LEGACY_PRODUCT = "ingestion"
_LEGACY_CAPABILITY = "connector"

# Secret-bearing fields in priority order for the primary secret extraction.
_SECRET_FIELDS = (
    "api_key",
    "access_token",
    "client_secret",
    "secret",
    "private_key",
    "service_account_json",
    "token",
)


# ── Secret + config resolution ──────────────────────────────────────────────


def _resolve_secret(credential: Optional[StructuredCredential]) -> Optional[str]:
    """Extract a plaintext secret from a structured credential, explicitly.

    Every reveal is an auditable ``get_secret_value()`` call; the extracted
    string is passed straight to the legacy connector (``test_connection`` /
    ``pull``) and is never stored, logged, or returned. Multi-member
    credentials without a single primary secret fall back to the deterministic
    canonical JSON form so no secret material is dropped.
    """
    if credential is None:
        return None
    for field in _SECRET_FIELDS:
        value = getattr(credential, field, None)
        if value is not None:
            return value.get_secret_value()
    return to_plaintext_json(credential)


def _config_for(context: AcquisitionContext, connector: BaseConnector) -> ConnectorConfig:
    """Build a tenant-scoped legacy ConnectorConfig from an AcquisitionContext."""
    return ConnectorConfig(
        tenant_id=context.tenant_id,
        connector_type=connector.connector_type,  # type: ignore[arg-type]
        config=context.config,
        secret_configured=context.credential is not None,
    )


# ── NormalizedEvent -> RawProviderRecord wrapping ───────────────────────────


def _stable_provider_record_id(event: NormalizedEvent) -> str:
    """Deterministic provider_record_id when the event carries no external id.

    sha256 of ``source:event_type:external_id`` so the same event always yields
    the same id (dedup-safe across re-delivery).
    """
    material = f"{event.source}:{event.event_type}:{event.external_id or ''}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:24]


def _wrap_event(
    event: NormalizedEvent,
    *,
    family: str,
    tenant_id: str,
    connection_id: str = "",
    account_id: str = "",
    acquisition_mode: str = "poll",
    cursor: Optional[str] = None,
    webhook_delivery_id: Optional[str] = None,
) -> RawProviderRecord:
    """Wrap one legacy :class:`NormalizedEvent` into a :class:`RawProviderRecord`.

    The legacy provider-namespaced ``event_type`` (e.g. ``email_opened``) is
    preserved verbatim as ``provider_record_type`` AND in
    ``metadata.legacy_event_type``; the normalizer reads it back so the legacy
    event type survives into the :class:`AetherEvent` intact.
    """
    return make_raw_record(
        provider_identity=f"{family}.{_LEGACY_PRODUCT}.{_LEGACY_CAPABILITY}",
        tenant_id=tenant_id,
        connection_id=connection_id,
        account_id=account_id,
        provider_record_type=event.event_type,
        provider_record_id=event.external_id or _stable_provider_record_id(event),
        acquisition_mode=acquisition_mode,
        provider_occurred_at=event.occurred_at,
        cursor=cursor,
        webhook_delivery_id=webhook_delivery_id,
        payload=event.properties,
        metadata={"legacy_event_type": event.event_type, "source": event.source},
    )


# ── Capability adapters ─────────────────────────────────────────────────────


class _LegacyAuthAdapter(AuthAdapter):
    """Delegates credential validation to ``connector.test_connection``."""

    def __init__(self, connector: BaseConnector) -> None:
        self._connector = connector

    async def validate_credentials(
        self, context: AcquisitionContext
    ) -> AdapterResult[Any]:
        return await self.test(context)

    async def test(self, context: AcquisitionContext) -> AdapterResult[Any]:
        config = _config_for(context, self._connector)
        secret = _resolve_secret(context.credential)
        result = await self._connector.test_connection(config, secret=secret)
        return from_connection_test(result)


class _LegacyPullAdapter(PullAdapter):
    """Delegates cursor-addressable pull ingestion to ``connector.pull``."""

    def __init__(self, connector: BaseConnector) -> None:
        self._connector = connector

    async def _pull(
        self, context: AcquisitionContext, *, since: Optional[str], limit: Optional[int] = None
    ) -> AdapterResult[ReadBatch]:
        config = _config_for(context, self._connector)
        secret = _resolve_secret(context.credential)
        events = await self._connector.pull(config, since=since, secret=secret)
        family = self._connector.connector_type
        records = [
            _wrap_event(
                event,
                family=family,
                tenant_id=context.tenant_id,
                connection_id=context.connection_id,
                account_id=context.account_id,
                acquisition_mode="poll",
                cursor=since,
            )
            for event in events
        ]
        # The legacy pull is a single snapshot per recency cursor — there is no
        # page API to ask for "the next page". ``limit`` (when given) is honored
        # as a page bound via a client-side slice, and ``has_more`` honestly
        # reports whether records beyond the slice exist. A follow-up ``fetch``
        # with ``next_cursor`` re-pulls through the connector's recency cursor
        # (which advances for cursor-honoring connectors) and is deduped
        # downstream by ``provider_record_id`` for the rest.
        total = len(records)
        if limit is not None and limit >= 0:
            page = records[:limit]
            has_more = total > limit
        else:
            page = records
            has_more = False
        next_cursor = page[-1].provider_occurred_at if page else since
        return AdapterResult.ok(
            data=ReadBatch(records=page, next_cursor=next_cursor, has_more=has_more),
            account={
                "cursor": since,
                "next_cursor": next_cursor,
                "event_count": len(page),
                "total_count": total,
            },
        )

    async def fetch(
        self,
        context: AcquisitionContext,
        *,
        cursor: Optional[str],
        limit: Optional[int] = None,
    ) -> AdapterResult[ReadBatch]:
        return await self._pull(context, since=cursor, limit=limit)

    async def initial_backfill(
        self, context: AcquisitionContext
    ) -> AdapterResult[ReadBatch]:
        return await self._pull(context, since=None)


def _header(headers: Mapping[str, str], name: str) -> str:
    """Case-insensitive single-header lookup (``str``/bytes mixed dicts)."""
    lowered = name.lower()
    for key, value in headers.items():
        if str(key).lower() == lowered:
            return str(value)
    return ""


class _LegacyWebhookAdapter(WebhookAdapter):
    """Delegates verification + parsing to the legacy connector framework."""

    def __init__(self, connector: BaseConnector) -> None:
        self._connector = connector

    def verify(
        self, raw_body: bytes, headers: Mapping[str, str], secret: Optional[str]
    ) -> bool:
        # The canonical Aether HMAC headers (see services/integrations/
        # connectors/routes.py); providers with a native verifier ignore them.
        return verify_provider_webhook_signature(
            self._connector,
            raw_body=raw_body,
            headers=headers,
            secret=secret,
            signature=_header(headers, "X-Aether-Signature") or None,
            timestamp=_header(headers, "X-Aether-Timestamp") or None,
        )

    def parse(
        self, payload: dict[str, Any], *, headers: Mapping[str, str]
    ) -> list[RawProviderRecord]:
        events = self._connector.parse_webhook(payload)
        family = self._connector.connector_type
        # No tenant/connection scoping at parse time — the ingestion service
        # binds the delivery to a tenant/connection before normalization.
        return [
            _wrap_event(
                event,
                family=family,
                tenant_id="",
                acquisition_mode="webhook",
                webhook_delivery_id=_header(headers, "X-Aether-Delivery-ID") or None,
            )
            for event in events
        ]


class _LegacyAccountAdapter(AccountAdapter):
    """Adapter for manifest-claimed account discovery.

    Legacy connectors declare ``supports_account_discovery`` without exposing a
    discover/select method (Klaviyo), so the adapter exists to satisfy the
    manifest claim but every operation is an honest ``not_supported`` — the
    adapter never fabricates an account list.
    """

    def __init__(self, connector: BaseConnector) -> None:
        self._connector = connector

    async def discover_accounts(
        self, context: AcquisitionContext
    ) -> AdapterResult[list[ProviderAccount]]:
        return AdapterResult.not_supported("discover_accounts")

    async def select_account(
        self, context: AcquisitionContext, *, account_id: str
    ) -> AdapterResult[Any]:
        return AdapterResult.not_supported("select_account")


class _LegacyReconciliationAdapter(ReconciliationAdapter):
    """Adapter for manifest-claimed reconciliation.

    The legacy reconciliation surface is connector-specific (Klaviyo's
    ``reconcile(..., external_campaign_id=...)``) and cannot be driven through
    the provider-neutral :class:`AcquisitionContext`, which carries no campaign
    scoping. The adapter exists — so the plugin is honest about exposing the
    capability — but returns ``not_supported`` for the neutral operation rather
    than fabricating a parameter. Bridge the legacy-specific reconcile once the
    neutral context grows a carrier for provider-scoped parameters.
    """

    def __init__(self, connector: BaseConnector) -> None:
        self._connector = connector

    async def snapshot(
        self,
        context: AcquisitionContext,
        *,
        since: Optional[str],
    ) -> AdapterResult[list[RawProviderRecord]]:
        return AdapterResult.not_supported("snapshot")


class _LegacyNormalizer(EventNormalizer):
    """Deterministic normalizer preserving the legacy provider-namespaced type.

    Reads the legacy ``event_type`` back from ``metadata.legacy_event_type`` and
    emits an :class:`AetherEvent` whose ``event_type`` is that legacy
    provider-namespaced value (e.g. ``email_opened``) — renaming into the
    provider-neutral ``commerce.*`` vocabulary is explicitly out of scope for
    the compatibility plugin. ``event_family`` is the provider family name;
    ``context`` carries the acquisition mode and the raw event type.

    Determinism is a hard contract: no wall-clock, randomness, or provider I/O
    — the same raw record always yields the same events.
    """

    def __init__(self, family: str) -> None:
        self._family = family

    def normalize(self, raw: RawProviderRecord) -> NormalizationResult:
        legacy_event_type = raw.metadata.get("legacy_event_type") or raw.provider_record_type
        source = raw.metadata.get("source") or self._family
        event = AetherEvent(
            event_id=hashlib.sha256(
                f"{raw.record_id}:{legacy_event_type}".encode("utf-8")
            ).hexdigest()[:32],
            event_type=legacy_event_type,
            event_family=self._family,
            tenant_id=raw.tenant_id,
            provider=source,
            provider_identity=raw.provider_identity,
            source_record_id=raw.record_id,
            occurred_at=raw.provider_occurred_at or raw.observed_at,
            observed_at=raw.observed_at,
            account_id=raw.account_id,
            data=dict(raw.payload),
            context={
                "acquisition_mode": raw.acquisition_mode,
                "connection_id": raw.connection_id,
                "provider_record_type": raw.provider_record_type,
                "provider_record_id": raw.provider_record_id,
                "cursor": raw.cursor,
            },
            schema_version="1",
        )
        return NormalizationResult(
            events=[event],
            skipped=0,
            dropped=[],
            normalizer_version="1",
        )


# ── The plugin ──────────────────────────────────────────────────────────────


class LegacyConnectorPlugin(BaseProviderPlugin):
    """A provider-neutral plugin wrapping one legacy :class:`BaseConnector`.

    Identity is the connector's ``<connector_type>.ingestion.connector``; the
    manifest is the derived catalog projection re-validated at construction;
    adapters delegate to the legacy connector wherever the neutral seam maps
    cleanly and are ``None`` where the manifest does not claim the capability.
    """

    def __init__(self, connector: BaseConnector) -> None:
        self._connector = connector
        descriptor = connector.descriptor()
        self._manifest = validate_manifest(
            manifest_from_connector_descriptor(descriptor)
        )

    @property
    def connector(self) -> BaseConnector:
        """The wrapped legacy connector."""
        return self._connector

    def identity(self) -> ProviderIdentity:
        return ProviderIdentity(
            family=ProviderFamily(self._connector.connector_type),
            product=ProductId(_LEGACY_PRODUCT),
            capability=CapabilityId(_LEGACY_CAPABILITY),
        )

    def manifest(self) -> ProviderManifest:
        return self._manifest

    def auth(self) -> Optional[AuthAdapter]:
        # Every legacy connector requires a credential, so authentication.type
        # is never "none" and the auth adapter is always present.
        return _LegacyAuthAdapter(self._connector)

    def account(self) -> Optional[AccountAdapter]:
        if (
            self._manifest.accounts.discovery_supported
            or self._manifest.accounts.selection_required
        ):
            return _LegacyAccountAdapter(self._connector)
        return None

    def pull(self) -> Optional[PullAdapter]:
        if self._manifest.sync.incremental or self._manifest.sync.initial_backfill:
            return _LegacyPullAdapter(self._connector)
        return None

    def webhook(self) -> Optional[WebhookAdapter]:
        if self._manifest.webhooks.supported:
            return _LegacyWebhookAdapter(self._connector)
        return None

    def reconciliation(self) -> Optional[ReconciliationAdapter]:
        if self._manifest.sync.reconciliation:
            return _LegacyReconciliationAdapter(self._connector)
        return None

    def normalizer(self) -> EventNormalizer:
        return _LegacyNormalizer(self._connector.connector_type)

    # report() / stream() -> None (inherited from the base).


def install_legacy_plugins(registry) -> int:
    """Register one :class:`LegacyConnectorPlugin` per legacy connector.

    Every connector is wrapped and its manifest re-validated; a connector that
    produces an invalid manifest raises :class:`ManifestInvalid` naming the
    connector (never a silent skip). Returns the number of plugins registered.
    """
    from services.integrations.connectors.registry import CONNECTORS

    count = 0
    for connector_type, connector in CONNECTORS.items():
        try:
            plugin = LegacyConnectorPlugin(connector)
        except ManifestValidationError as exc:
            raise ManifestInvalid(
                f"legacy connector {connector_type!r} produced an invalid "
                f"manifest: {'; '.join(exc.violations)}"
            ) from exc
        except Exception as exc:  # noqa: BLE001 - name ANY connector build failure
            raise ManifestInvalid(
                f"legacy connector {connector_type!r} failed to build a plugin: {exc}"
            ) from exc
        registry.register(plugin, source="legacy")
        count += 1
    return count


__all__ = [
    "LegacyConnectorPlugin",
    "install_legacy_plugins",
]
