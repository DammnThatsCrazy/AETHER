"""Inbound provider webhook gateway for the provider-neutral runtime.

Flow: resolve a candidate → verify → parse → bind connection scope → validate
declared webhook stream → rights admission → raw store → WebhookInbox → normalize
→ bridge. Unresolved or unverified requests emit tenantless denial telemetry
with a generic public response; full request bodies are retained only after a
current tenant rights decision admits the raw artifact.

Verification NEVER silently trusts a delivery. A webhook is accepted only when
the connection proves ownership of it:

* a signature scheme (e.g. ``shopify_hmac``) requires a configured webhook
  secret that verifies the delivery;
* ``manifest.webhooks.verification_scheme == "endpoint_secret"`` requires a
  per-connection endpoint token presented by the caller (header
  ``X-Aether-Webhook-Endpoint-Token``) that constant-time-matches the
  connection's configured webhook secret.

A missing secret/token is a misconfiguration: the delivery is DENIED, never
silently trusted. There is no "no secret ⇒ trust" path, because this endpoint
is public and unauthenticated by API key (see ``PUBLIC_PATH_PREFIXES``) — trust
must come from cryptographic proof the caller holds the connection's secret,
not from its absence.

Team seams consumed here (constructor-injected; defaults resolve lazily):
``connectors.provider_runtime.registry`` (``registry.get(identity_key)``),
``connectors.provider_runtime.connection`` (``ProviderConnectionRepository``),
``connectors.provider_runtime.credential_broker`` (``CredentialBroker.reveal``),
``connectors.provider_runtime.raw_store`` (``RawProviderRecordStore.ingest``),
``connectors.provider_runtime.normalization`` (``NormalizationEngine(plugin).run``),
``connectors.provider_runtime.bridge`` (``EventBridge.ingest_events``).
"""

from __future__ import annotations

import inspect
import json
import uuid
from typing import Any, Mapping, Optional

from repositories.delivery_repos import WebhookInboxRepository
from actions.delivery.security import sanitize_headers
from connectors.provider_runtime.errors import (
    CredentialMissing,
    ProviderNotInstalled,
)
from shared.integration_contracts.events import make_raw_record
from shared.logger.logger import get_logger, metrics

logger = get_logger("aether.provider_runtime.webhook")

# Raw-provider-record type for denial records (metadata only, no payload).
_DENIAL_RECORD_TYPE = "webhook_denial"
_SHOPIFY_ORDERS_IDENTITY = "shopify.admin.orders_read"
_UNBOUND_DENIAL_REASONS = frozenset(
    {
        "invalid_payload",
        "shop_domain_invalid",
        "shop_account_ambiguous",
        "shop_account_not_found",
        "shop_account_not_selected",
        "shop_domain_mismatch",
        "webhook_mode_disabled",
        "graphql_webhook_requires_hydration",
        "webhook_not_supported",
        "verification_failed",
        "connection_not_found",
    }
)


def _shopify_webhook_mode_denial(identity_key: str, connection: Any) -> str | None:
    """Return the closed denial reason for a Shopify mode that cannot ingest hooks.

    Shopify REST and GraphQL pull modes are poll-only. The explicit
    ``rest_webhook`` mode is the only mode that may reach signature verification
    and REST-shaped parsing. Missing configuration preserves the pull default
    (REST) and therefore does not silently enable the public webhook surface.
    """
    if identity_key != _SHOPIFY_ORDERS_IDENTITY:
        return None
    mode = (
        str((getattr(connection, "config", None) or {}).get("orders_api") or "rest").strip().lower()
    )
    if mode == "rest_webhook":
        return None
    if mode == "graphql":
        return "graphql_webhook_requires_hydration"
    return "webhook_mode_disabled"


def _connection_from_row(row: Optional[dict]) -> Optional[Any]:
    """Build a ProviderConnection from a stored row, stripping the repo-injected
    ``id`` key (ProviderConnection is ``extra="forbid"``)."""
    if row is None:
        return None
    from connectors.provider_runtime.connection import ProviderConnection

    return ProviderConnection.model_validate({k: v for k, v in row.items() if k != "id"})


def _connection_account_id(connection: Any) -> str:
    selected = getattr(connection, "selected_accounts", None) or []
    return str(selected[0]) if selected else ""


class WebhookGateway:
    """Inbound provider webhooks: verify → parse → raw store → normalize → bridge.
    The full request body enters WebhookInbox only after ownership verification."""

    def __init__(
        self,
        *,
        raw_store: Any = None,
        normalization: Any = None,
        bridge: Any = None,
        connections: Any = None,
        accounts: Any = None,
        broker: Any = None,
        registry: Any = None,
        inbox: Any = None,
    ) -> None:
        self.raw_store = raw_store
        self.normalization = normalization
        self.bridge = bridge
        self.connections = connections
        self.accounts = accounts
        self.broker = broker
        self.registry = registry
        self.inbox = inbox

    # ── Seam defaults (resolved lazily so imports stay decoupled) ──────────

    def _registry(self) -> Any:
        if self.registry is None:
            from connectors.provider_runtime.registry import registry

            self.registry = registry
        return self.registry

    def _connections(self) -> Any:
        if self.connections is None:
            from connectors.provider_runtime.connection import (
                ProviderConnectionRepository,
            )

            self.connections = ProviderConnectionRepository()
        return self.connections

    def _broker(self) -> Any:
        if self.broker is None:
            from connectors.provider_runtime.credential_broker import CredentialBroker

            self.broker = CredentialBroker()
        return self.broker

    def _accounts(self) -> Any:
        if self.accounts is None:
            from connectors.provider_runtime.acquisition import ProviderAccountRepository

            self.accounts = ProviderAccountRepository()
        return self.accounts

    def _raw_store(self) -> Any:
        if self.raw_store is None:
            from connectors.provider_runtime.raw_store import RawProviderRecordStore

            self.raw_store = RawProviderRecordStore()
        return self.raw_store

    def _normalization_engine(self, plugin: Any) -> Any:
        if self.normalization is not None:
            return self.normalization
        from connectors.provider_runtime.normalization import NormalizationEngine

        return NormalizationEngine(plugin)

    def _bridge(self) -> Any:
        if self.bridge is None:
            from connectors.provider_runtime.bridge import EventBridge

            self.bridge = EventBridge()
        return self.bridge

    # ── Ingest ─────────────────────────────────────────────────────────────

    async def ingest(
        self,
        identity_key: str,
        *,
        raw_body: bytes,
        headers: Mapping[str, str],
        signature: Optional[str] = None,
        tenant_id: str = "",
    ) -> dict[str, Any]:
        """Verify, parse, persist and bridge one inbound provider webhook.

        Returns ``{"accepted": True, "record_count": N, "event_count": M}`` on
        success, or an ``{"accepted": False, ...}`` acknowledgement for
        verification/payload failures (the caller decides the HTTP status).
        """
        # 1. Resolve the plugin (hard error when missing).
        plugin = self._registry().get(identity_key)
        if plugin is None:
            raise ProviderNotInstalled(
                f"provider {identity_key} is not installed in the runtime registry"
            )
        shopify_domain: str | None = None
        shopify_account_id: str | None = None
        payload: dict[str, Any] | None = None
        if identity_key == _SHOPIFY_ORDERS_IDENTITY:
            # Parse the signed bytes only to choose a candidate connection. The
            # body is still untrusted here: it is never retained or persisted
            # until that candidate's HMAC verifies and the binding is rechecked.
            payload = self._parse_payload(raw_body, headers)
            if payload is None:
                self._record_unbound_denial("invalid_payload")
                return self._denied("webhook_rejected", "webhook_rejected")
            from connectors.providers.shopify.webhook import ShopifyWebhookAdapter

            try:
                shopify_domain = ShopifyWebhookAdapter.shop_domain_from_payload(
                    payload, headers=headers
                )
            except Exception:
                self._record_unbound_denial("shop_domain_invalid")
                return self._denied("webhook_rejected", "webhook_rejected")
            (
                connection,
                shopify_account_id,
                routing_error,
            ) = await self._find_shopify_connection_for_domain(
                tenant_id, identity_key, shopify_domain
            )
            if connection is None or shopify_account_id is None:
                denial = routing_error or "shop_account_not_found"
                self._record_unbound_denial(denial)
                return self._denied("webhook_rejected", "webhook_rejected")
        else:
            connection = await self._find_connection(tenant_id, identity_key)
            if connection is None:
                self._record_unbound_denial("connection_not_found")
                return self._denied("webhook_rejected", "webhook_rejected")
        mode_denial = _shopify_webhook_mode_denial(identity_key, connection)
        if mode_denial is not None:
            # Mode checks happen before provider authentication. The caller's
            # tenant hint therefore cannot be used for a Bronze denial write.
            self._record_unbound_denial(mode_denial)
            return {
                "accepted": False,
                "reason": "webhook_rejected",
                "error_code": "webhook_rejected",
                "inbox_id": None,
                "record_count": 0,
                "event_count": 0,
            }
        webhook = plugin.webhook()
        if webhook is None:
            self._record_unbound_denial("webhook_not_supported")
            return {
                "accepted": False,
                "reason": "webhook_rejected",
                "record_count": 0,
                "event_count": 0,
            }

        # 2. Resolve the webhook secret per credential shape.
        secret = await self._resolve_webhook_secret(connection)

        # 4. Verify — NEVER silently trust. A webhook is accepted only when the
        # connection proves ownership of the delivery:
        #   * signature scheme  ⇒ a configured secret must verify the delivery;
        #   * endpoint_secret   ⇒ a per-connection endpoint token presented by
        #     the caller must match the connection's configured secret.
        # A missing secret/token is a misconfiguration and is DENIED without
        # tenant-scoped persistence — there is no "no secret ⇒ trust" path.
        manifest = plugin.manifest()
        scheme = None
        try:
            scheme = manifest.webhooks.verification_scheme  # type: ignore[attr-defined]
        except Exception:  # pragma: no cover - defensive; webhooks model always present
            scheme = None
        verified = False
        verification_detail = ""
        if scheme == "endpoint_secret":
            presented = headers.get("X-Aether-Webhook-Endpoint-Token", "").strip() or (
                signature or ""
            )
            if not secret:
                verification_detail = (
                    "endpoint_secret scheme but no per-connection webhook "
                    "secret/token configured; cannot prove ownership"
                )
            elif not presented:
                verification_detail = (
                    "endpoint_secret scheme requires a caller-presented endpoint token"
                )
            else:
                from actions.delivery.security import constant_time_compare

                verified = bool(constant_time_compare(presented, secret))
                if not verified:
                    verification_detail = "endpoint token verification failed"
                else:
                    verification_detail = "verified via per-connection endpoint token"
        else:
            if not secret:
                # Signature scheme with no secret configured: nothing to verify
                # against. Deny — never auto-accept.
                verification_detail = (
                    "signature verification scheme but no webhook secret configured; cannot verify"
                )
            else:
                try:
                    verified = bool(webhook.verify(raw_body, headers, secret))
                except Exception as exc:  # pragma: no cover - adapter may raise
                    logger.warning(
                        "provider webhook verification raised provider=%s error_type=%s",
                        identity_key,
                        type(exc).__name__,
                    )
                    verified = False
                if not verified:
                    verification_detail = "signature verification failed"
        if not verified:
            # The routing tenant and candidate connection remain untrusted
            # until the secret verifies. Keep this in tenantless telemetry.
            self._record_unbound_denial("verification_failed")
            return {
                "accepted": False,
                "reason": "webhook_rejected",
                "error_code": "webhook_rejected",
                "inbox_id": None,
                "record_count": 0,
                "event_count": 0,
            }

        if identity_key == _SHOPIFY_ORDERS_IDENTITY:
            # Re-read the connection and selected account after HMAC proof to
            # close the gap between candidate selection and persistence.
            (
                refreshed,
                refreshed_account_id,
                binding_error,
            ) = await self._find_shopify_connection_for_domain(
                tenant_id, identity_key, shopify_domain or ""
            )
            if (
                refreshed is None
                or refreshed_account_id != shopify_account_id
                or refreshed.connection_id != connection.connection_id
                or binding_error is not None
            ):
                await self._store_denial(
                    connection,
                    reason="shop_account_binding_changed",
                    error_code="shopify_account_binding_changed",
                    signature=signature,
                    account_id=shopify_account_id,
                )
                return self._denied(
                    "shop_account_binding_changed", "shopify_account_binding_changed"
                )
            connection = refreshed
            mode_denial = _shopify_webhook_mode_denial(identity_key, connection)
            if mode_denial is not None:
                await self._store_denial(
                    connection,
                    reason=mode_denial,
                    error_code=mode_denial,
                    signature=signature,
                    account_id=shopify_account_id,
                )
                return self._denied(mode_denial, mode_denial)

        # Retain the request only after verification, provider parsing, exact
        # account binding, and declared-stream activation checks succeed.
        inbox_id: Optional[str] = None

        # 3. Parse → validate the declared webhook stream → raw store → normalize → bridge.
        if payload is None:
            payload = self._parse_payload(raw_body, headers)
        if payload is None:
            await self._store_denial(
                connection,
                reason="invalid_payload",
                error_code="webhook_invalid_payload",
                signature=signature,
                inbox_id=inbox_id,
                account_id=shopify_account_id,
            )
            return {
                "accepted": False,
                "reason": "invalid_payload",
                "detail": "webhook body was not valid JSON",
                "inbox_id": inbox_id,
                "record_count": 0,
                "event_count": 0,
            }
        try:
            records = webhook.parse(payload, headers=headers) or []
        except Exception as exc:  # pragma: no cover - adapter parse failure
            logger.warning(
                "provider webhook parse failed tenant=%s provider=%s error_type=%s",
                tenant_id,
                identity_key,
                type(exc).__name__,
            )
            await self._store_denial(
                connection,
                reason="parse_failed",
                error_code="webhook_parse_failed",
                signature=signature,
                inbox_id=inbox_id,
                account_id=shopify_account_id,
            )
            return {
                "accepted": False,
                "reason": "parse_failed",
                "detail": "webhook payload could not be parsed",
                "inbox_id": inbox_id,
                "record_count": 0,
                "event_count": 0,
            }

        if identity_key == _SHOPIFY_ORDERS_IDENTITY:
            if any(
                record.metadata.get("shopify_shop_domain") != shopify_domain for record in records
            ):
                await self._store_denial(
                    connection,
                    reason="shop_domain_mismatch",
                    error_code="shopify_shop_domain_mismatch",
                    signature=signature,
                    inbox_id=inbox_id,
                    account_id=shopify_account_id,
                )
                return self._denied(
                    "shop_domain_mismatch",
                    "shopify_shop_domain_mismatch",
                    inbox_id=inbox_id,
                )

        stream_error = self._webhook_stream_error(records, manifest, connection)
        if stream_error is not None:
            await self._store_denial(
                connection,
                reason=stream_error,
                error_code=stream_error,
                signature=signature,
                inbox_id=inbox_id,
                account_id=shopify_account_id,
            )
            return {
                "accepted": False,
                "reason": stream_error,
                "error_code": stream_error,
                "inbox_id": inbox_id,
                "record_count": 0,
                "event_count": 0,
            }

        try:
            records = self._bind_records_to_connection(
                records,
                connection,
                identity_key=identity_key,
                expected_account_id=shopify_account_id,
            )
        except ValueError:
            await self._store_denial(
                connection,
                reason="scope_mismatch",
                error_code="webhook_scope_mismatch",
                signature=signature,
                inbox_id=inbox_id,
                account_id=shopify_account_id,
            )
            return {
                "accepted": False,
                "reason": "scope_mismatch",
                "inbox_id": inbox_id,
                "record_count": 0,
                "event_count": 0,
            }

        try:
            persisted_outcomes = await self._raw_store().ingest(records, tenant_id=tenant_id)
            if len(persisted_outcomes) != len(records):
                raise ValueError("raw store returned an incomplete webhook batch")
            persisted_records = []
            for raw_record, (persisted_record, _was_new) in zip(records, persisted_outcomes):
                if (
                    persisted_record.tenant_id != tenant_id
                    or persisted_record.provider_identity != identity_key
                    or persisted_record.connection_id != connection.connection_id
                    or persisted_record.account_id != raw_record.account_id
                    or persisted_record.stream_id != raw_record.stream_id
                ):
                    raise ValueError("raw store returned a record outside webhook scope")
                persisted_records.append(persisted_record)
        except Exception as exc:
            logger.warning(
                "provider webhook raw ingest failed tenant=%s provider=%s error=%s",
                tenant_id,
                identity_key,
                type(exc).__name__,
            )
            return {
                "accepted": False,
                "reason": "raw_persist_failed",
                "inbox_id": None,
                "record_count": 0,
                "event_count": 0,
            }

        records = persisted_records
        # The canonical tenant rights gate is part of raw_store.ingest. Do not
        # retain the request body in WebhookInbox until that admission succeeds.
        # An empty parse has no raw admission decision, so its body is not retained.
        if persisted_records:
            inbox_id = await self._write_inbox(
                tenant_id,
                identity_key,
                raw_body,
                headers,
                signature,
            )

        async def finish_identity_lifecycle(status: str) -> None:
            if not inbox_id:
                return
            try:
                from identity.identity.provider_evidence_anchors import (
                    ProviderIdentityEvidenceAnchorRepository,
                )

                await ProviderIdentityEvidenceAnchorRepository().finish_lifecycle(
                    tenant_id=tenant_id,
                    lifecycle_type="provider_webhook_inbox",
                    lifecycle_id=inbox_id,
                    status=status,
                )
            except Exception as exc:
                logger.warning(
                    "provider webhook evidence lifecycle close failed tenant=%s error=%s",
                    tenant_id,
                    type(exc).__name__,
                )

        if persisted_outcomes and inbox_id:
            try:
                from identity.identity.provider_evidence import (
                    capture_durable_provider_customer_evidence,
                )

                await capture_durable_provider_customer_evidence(
                    persisted_records,
                    persisted_outcomes,
                    tenant_id=tenant_id,
                    connection_id=connection.connection_id,
                    account_id=shopify_account_id or _connection_account_id(connection),
                    lifecycle_type="provider_webhook_inbox",
                    lifecycle_id=inbox_id,
                )
            except Exception as exc:  # evidence failure stays out of resolver candidates
                logger.warning(
                    "provider webhook identity evidence capture failed tenant=%s "
                    "provider=%s error=%s",
                    tenant_id,
                    identity_key,
                    type(exc).__name__,
                )
        engine = self._normalization_engine(plugin)
        try:
            events = await self._normalize_records(engine, records)
            if any(event.tenant_id != tenant_id for event in events):
                raise ValueError("normalizer returned an event outside webhook tenant")
        except Exception as exc:
            logger.warning(
                "provider webhook normalization failed tenant=%s provider=%s error=%s",
                tenant_id,
                identity_key,
                type(exc).__name__,
            )
            await finish_identity_lifecycle("failed")
            return {
                "accepted": False,
                "reason": "normalization_failed",
                "inbox_id": inbox_id,
                "record_count": len(records),
                "event_count": 0,
            }
        accepted_count = 0
        if events:
            try:
                accepted_count = await self._bridge().ingest_events(tenant_id, events)
            except Exception as exc:
                logger.warning(
                    "provider webhook event persistence failed tenant=%s provider=%s error=%s",
                    tenant_id,
                    identity_key,
                    type(exc).__name__,
                )
                await finish_identity_lifecycle("failed")
                return {
                    "accepted": False,
                    "reason": "event_persist_failed",
                    "inbox_id": inbox_id,
                    "record_count": len(records),
                    "event_count": 0,
                }
        if inbox_id:
            try:
                await self._mark_inbox_processed(inbox_id)
            except Exception as exc:  # pragma: no cover - best-effort
                logger.warning(
                    "provider webhook inbox close failed tenant=%s error=%s",
                    tenant_id,
                    type(exc).__name__,
                )
                await finish_identity_lifecycle("failed")
            else:
                await finish_identity_lifecycle("completed")
        return {
            "accepted": True,
            "verified": verified,
            "record_count": len(records),
            "event_count": accepted_count,
            "detail": verification_detail or "webhook accepted",
            "inbox_id": inbox_id,
        }

    # ── Internals ───────────────────────────────────────────────────────────

    @staticmethod
    def _bind_records_to_connection(
        records: list[Any],
        connection: Any,
        *,
        identity_key: str,
        expected_account_id: str | None = None,
    ) -> list[Any]:
        """Scope provider-shaped records with the verified connection.

        Webhook adapters lack a trusted tenant argument. A source payload may
        claim IDs, but cannot choose another tenant, connection, or account.
        An unscoped delivery for a multi-account connection is ambiguous.
        """
        selected = [str(value) for value in (connection.selected_accounts or [])]
        bound = []
        for record in records:
            if record.provider_identity != identity_key:
                raise ValueError("webhook provider identity mismatch")
            if record.tenant_id and record.tenant_id != connection.tenant_id:
                raise ValueError("webhook tenant mismatch")
            if record.connection_id and record.connection_id != connection.connection_id:
                raise ValueError("webhook connection mismatch")
            account_id = record.account_id
            if expected_account_id is not None:
                if account_id and account_id != expected_account_id:
                    raise ValueError("webhook account does not match verified shop")
                account_id = expected_account_id
            if not account_id:
                if len(selected) != 1:
                    raise ValueError("webhook account is ambiguous")
                account_id = selected[0]
            if account_id not in selected:
                raise ValueError("webhook account mismatch")
            bound.append(
                record.model_copy(
                    update={
                        "tenant_id": connection.tenant_id,
                        "connection_id": connection.connection_id,
                        "account_id": account_id,
                    }
                )
            )
        return bound

    @staticmethod
    def _webhook_stream_error(
        records: list[Any], manifest: Any, connection: Any | None = None
    ) -> Optional[str]:
        """Validate explicit stream claims before provider records are persisted.

        V1 plugins have no stream inventory and keep their capability-level
        behavior. Once a plugin declares streams, each emitted record must name
        one that explicitly supports webhook acquisition.
        """
        declared = getattr(manifest, "streams", None) or ()
        if not declared:
            return None

        streams = {
            str(stream.stream_id): stream
            for stream in declared
            if getattr(stream, "stream_id", None)
        }
        for record in records:
            stream_id = str(getattr(record, "stream_id", None) or "").strip()
            if not stream_id:
                return "provider_stream_id_missing"
            stream = streams.get(stream_id)
            if stream is None:
                return "provider_stream_not_found"
            if "webhook" not in (getattr(stream, "acquisition_modes", ()) or ()):
                return "provider_stream_not_webhook"
            activation_field = getattr(stream, "activation_config_field", None)
            activation_value = getattr(stream, "activation_config_value", None)
            if activation_field is not None:
                fields = getattr(getattr(manifest, "configuration", None), "fields", ()) or ()
                defaults = {
                    field.name: getattr(field, "default_value", None)
                    for field in fields
                    if getattr(field, "name", None)
                }
                config = getattr(connection, "config", None) or {}
                actual = config.get(activation_field)
                if actual is None:
                    actual = defaults.get(activation_field)
                if actual != activation_value:
                    return "provider_stream_inactive"
        return None

    async def _find_connection(self, tenant_id: str, identity_key: str) -> Optional[Any]:
        """Locate a unique tenant/provider connection; ambiguity fails closed."""
        rows = await self._connections().find_many(
            filters={"tenant_id": tenant_id, "provider_identity": identity_key},
            limit=2,
        )
        if len(rows) != 1:
            return None
        return _connection_from_row(rows[0])

    async def _find_shopify_connection_for_domain(
        self, tenant_id: str, identity_key: str, shop_domain: str
    ) -> tuple[Any | None, str | None, str | None]:
        """Resolve one selected, persisted Shopify account by signed-body domain.

        The domain is untrusted when this runs; it narrows candidate credentials
        only. The caller must verify HMAC and call this again before retention or
        raw persistence. Both the connection selection and account discovery
        record must identify exactly one selected account.
        """
        from connectors.providers.shopify.auth import _validated_shop_domain

        normalized_domain = _validated_shop_domain(shop_domain)
        if not normalized_domain:
            return None, None, "shop_domain_invalid"
        rows = await self._connections().find_many(
            filters={"tenant_id": tenant_id, "provider_identity": identity_key},
            # Shopify connections are few. If the cap is reached, ambiguity is
            # safer than routing from a truncated candidate set.
            limit=10001,
        )
        if len(rows) > 10000:
            return None, None, "shop_account_ambiguous"

        matches: list[tuple[Any, str]] = []
        has_unselected_match = False
        has_config_mismatch = False
        for row in rows:
            connection = _connection_from_row(row)
            if connection is None:
                continue
            account_rows = await self._accounts().list_for_connection(
                connection.connection_id, limit=1001
            )
            if len(account_rows) > 1000:
                return None, None, "shop_account_ambiguous"
            selected = {str(value) for value in (connection.selected_accounts or [])}
            config_domain_value = (connection.config or {}).get("shop_domain")
            config_domain = (
                _validated_shop_domain(str(config_domain_value)) if config_domain_value else None
            )
            for account in account_rows:
                if (
                    account.tenant_id != tenant_id
                    or account.connection_id != connection.connection_id
                    or account.provider_identity != identity_key
                ):
                    continue
                account_prefix = f"{connection.connection_id}:"
                if not account.account_id.startswith(account_prefix):
                    continue
                provider_account_id = account.account_id[len(account_prefix) :]
                if (
                    provider_account_id != f"shop:{normalized_domain}"
                    or account.metadata.get("shop_domain") != normalized_domain
                ):
                    continue
                if config_domain_value and config_domain != normalized_domain:
                    has_config_mismatch = True
                    continue
                if provider_account_id not in selected:
                    has_unselected_match = True
                    continue
                matches.append((connection, provider_account_id))

        if len(matches) > 1:
            return None, None, "shop_account_ambiguous"
        if len(matches) == 1:
            connection, account_id = matches[0]
            return connection, account_id, None
        if has_unselected_match:
            return None, None, "shop_account_not_selected"
        if has_config_mismatch:
            return None, None, "shop_domain_mismatch"
        return None, None, "shop_account_not_found"

    @staticmethod
    def _denied(reason: str, error_code: str, *, inbox_id: Optional[str] = None) -> dict[str, Any]:
        return {
            "accepted": False,
            "reason": reason,
            "error_code": error_code,
            "inbox_id": inbox_id,
            "record_count": 0,
            "event_count": 0,
        }

    @staticmethod
    def _record_unbound_denial(reason: str) -> None:
        """Count an unauthenticated denial without trusting its tenant hint."""
        safe_reason = reason if reason in _UNBOUND_DENIAL_REASONS else "other"
        metrics.increment(
            "provider_webhook_unbound_denials_total",
            labels={"reason": safe_reason},
        )

    async def _write_inbox(
        self,
        tenant_id: str,
        identity_key: str,
        raw_body: bytes,
        headers: Mapping[str, str],
        signature: Optional[str],
    ) -> Optional[str]:
        """Store a verified delivery body in WebhookInbox on a best-effort basis."""
        inbox_id: Optional[str] = None
        try:
            repo = self.inbox or WebhookInboxRepository()
            inbox_id = str(uuid.uuid4())
            safe_headers = sanitize_headers(dict(headers or {}))
            await repo.insert(
                inbox_id,
                {
                    "id": inbox_id,
                    "tenant_id": tenant_id,
                    "provider": identity_key,
                    "headers": safe_headers,
                    "raw_body": raw_body.decode("utf-8", errors="replace"),
                    "signature": signature or "",
                    "timestamp": "",
                    "verified": True,
                    "processed": False,
                },
            )
        except Exception as exc:  # pragma: no cover - best-effort, never break ingestion
            logger.warning(f"provider webhook inbox write failed tenant={tenant_id}: {exc}")
        return inbox_id

    async def _mark_inbox_processed(self, inbox_id: str) -> None:
        repo = self.inbox or WebhookInboxRepository()
        await repo.update(inbox_id, {"processed": True, "verified": True})

    async def _resolve_webhook_secret(self, connection: Any) -> Optional[str]:
        credential_ref = getattr(connection, "credential_ref", None)
        if not credential_ref:
            return None
        try:
            revealed = await self._broker().reveal(connection.tenant_id, credential_ref)
        except Exception as exc:  # pragma: no cover - best-effort
            logger.warning(
                f"provider webhook secret resolution failed tenant={connection.tenant_id}: {exc}"
            )
            return None
        return _extract_webhook_secret(revealed)

    async def _store_denial(
        self,
        connection: Any,
        *,
        reason: str,
        error_code: str,
        signature: Optional[str],
        inbox_id: Optional[str] = None,
        account_id: str | None = None,
    ) -> None:
        """Persist an auditable metadata-only denial record (no payload)."""
        try:
            identity = connection.provider_identity
            record = make_raw_record(
                provider_identity=identity,
                provider_record_id=f"denial-{uuid.uuid4().hex}",
                provider_record_type=_DENIAL_RECORD_TYPE,
                payload={},  # deliberately empty — the unverified payload is never stored
                tenant_id=connection.tenant_id,
                connection_id=connection.connection_id,
                account_id=(
                    account_id if account_id is not None else _connection_account_id(connection)
                ),
                acquisition_mode="webhook",
                metadata={
                    "denial": True,
                    "reason": reason,
                    "error_code": error_code,
                    "signature_present": bool(signature),
                    "inbox_id": inbox_id,
                },
            )
            await self._raw_store().ingest([record])
        except Exception as exc:  # pragma: no cover - denial is best-effort, but never silent
            logger.warning(
                f"provider webhook denial record failed tenant={connection.tenant_id}: {exc}"
            )

    @staticmethod
    def _parse_payload(
        raw_body: bytes,
        headers: Mapping[str, str],
    ) -> Optional[dict[str, Any]]:
        raw_text = raw_body.decode("utf-8", errors="replace") if raw_body else ""
        if not raw_text.strip():
            return {}
        try:
            parsed = json.loads(raw_text)
        except (json.JSONDecodeError, UnicodeDecodeError):
            return None
        return parsed if isinstance(parsed, dict) else {"items": parsed}

    async def _normalize_records(self, engine: Any, records: list[Any]) -> list[Any]:
        if not records:
            return []
        result = engine.run(records)
        if inspect.isawaitable(result):
            result = await result
        if isinstance(result, (list, tuple)):
            return list(result)
        events = getattr(result, "events", None)
        if events is not None:
            return list(events)
        return []


def _extract_webhook_secret(revealed: Any) -> Optional[str]:
    """Extract a webhook secret from whatever ``broker.reveal`` returned.

    Handles every credential shape the provider-neutral credential platform
    defines (revealed as a :class:`StructuredCredential` object) plus a bare
    string or plain dict (legacy/vault reveal). Any structured credential
    carrying a ``webhook_secret`` (or ``secret``) field yields it, regardless
    of its concrete union member. Returns ``None`` when the credential carries
    no webhook secret — the caller must then DENY the delivery (a signature
    scheme has nothing to verify against; an ``endpoint_secret`` scheme has no
    token to match). There is no trust fallback on a missing secret.
    """
    if revealed is None:
        return None
    if isinstance(revealed, str):
        return revealed if revealed else None
    if isinstance(revealed, dict):
        value = revealed.get("webhook_secret") or revealed.get("secret")
        return _secret_value(value)
    # A StructuredCredential (or any pydantic-ish object): reveal it to a
    # plaintext dict and look for the webhook secret field generically.
    plain = _to_plaintext_dict(revealed)
    if plain is None:
        return None
    if plain.get("type") == "multi":
        components = plain.get("credentials")
        component = components.get("webhook_secret") if isinstance(components, dict) else None
        if isinstance(component, dict) and component.get("type") == "api_key":
            return _secret_value(component.get("api_key"))
        return None
    value = plain.get("webhook_secret") or plain.get("secret")
    return _secret_value(value)


def _to_plaintext_dict(revealed: Any) -> Optional[dict[str, Any]]:
    """Reveal an arbitrary credential object to a plain dict, or ``None``."""
    try:
        from shared.credentials.types import to_plaintext_dict as _reveal

        return _reveal(revealed)  # type: ignore[arg-type]
    except Exception:  # pragma: no cover - defensive; unhandled shape
        return None


def _secret_value(value: Any) -> Optional[str]:
    """Unwrap a pydantic ``SecretStr`` (or a plain string)."""
    if value is None:
        return None
    if hasattr(value, "get_secret_value"):
        return value.get_secret_value()
    return value if isinstance(value, str) and value else None


__all__ = ["WebhookGateway"]
