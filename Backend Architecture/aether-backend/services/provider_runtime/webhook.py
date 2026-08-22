"""Inbound provider webhook gateway for the provider-neutral runtime.

Flow: WebhookInbox (best-effort, before any business logic) → verify →
parse → raw store → normalize → bridge. Mirrors
``ConnectorService.ingest_webhook``'s ordering and its WebhookInbox usage, and
keeps the denial principle: a failed verification ALWAYS leaves an auditable
metadata-only denial record in the raw store — never a silent drop.

Verification NEVER silently trusts a delivery. A webhook is accepted only when
the connection proves ownership of it:

* a signature scheme (e.g. ``shopify_hmac``) requires a configured webhook
  secret that verifies the delivery;
* ``manifest.webhooks.verification_scheme == "endpoint_secret"`` requires a
  per-connection endpoint token presented by the caller (header
  ``X-Aether-Webhook-Endpoint-Token``) that constant-time-matches the
  connection's configured webhook secret.

A missing secret/token is a misconfiguration: the delivery is DENIED with an
auditable denial record, never silently trusted. There is no "no secret ⇒
trust" path, because this endpoint is public and unauthenticated by API key
(see ``PUBLIC_PATH_PREFIXES``) — trust must come from cryptographic proof the
caller holds the connection's secret, not from its absence.

Team seams consumed here (constructor-injected; defaults resolve lazily):
``services.provider_runtime.registry`` (``registry.get(identity_key)``),
``services.provider_runtime.connection`` (``ProviderConnectionRepository``),
``services.provider_runtime.credential_broker`` (``CredentialBroker.reveal``),
``services.provider_runtime.raw_store`` (``RawProviderRecordStore.ingest``),
``services.provider_runtime.normalization`` (``NormalizationEngine(plugin).run``),
``services.provider_runtime.bridge`` (``EventBridge.ingest_events``).
"""

from __future__ import annotations

import inspect
import json
import uuid
from typing import Any, Mapping, Optional

from repositories.delivery_repos import WebhookInboxRepository
from services.delivery.security import sanitize_headers
from services.provider_runtime.errors import (
    CredentialMissing,
    ProviderNotInstalled,
)
from shared.integration_contracts.events import make_raw_record
from shared.logger.logger import get_logger

logger = get_logger("aether.provider_runtime.webhook")

# Raw-provider-record type for denial records (metadata only, no payload).
_DENIAL_RECORD_TYPE = "webhook_denial"


def _connection_from_row(row: Optional[dict]) -> Optional[Any]:
    """Build a ProviderConnection from a stored row, stripping the repo-injected
    ``id`` key (ProviderConnection is ``extra="forbid"``)."""
    if row is None:
        return None
    from services.provider_runtime.connection import ProviderConnection
    return ProviderConnection.model_validate(
        {k: v for k, v in row.items() if k != "id"}
    )


def _connection_account_id(connection: Any) -> str:
    selected = getattr(connection, "selected_accounts", None) or []
    return str(selected[0]) if selected else ""


class WebhookGateway:
    """Inbound provider webhooks: verify → parse → raw store → normalize → bridge.
    WebhookInbox best-effort BEFORE verification (mirror ConnectorService.ingest_webhook)."""

    def __init__(
        self,
        *,
        raw_store: Any = None,
        normalization: Any = None,
        bridge: Any = None,
        connections: Any = None,
        broker: Any = None,
        registry: Any = None,
        inbox: Any = None,
    ) -> None:
        self.raw_store = raw_store
        self.normalization = normalization
        self.bridge = bridge
        self.connections = connections
        self.broker = broker
        self.registry = registry
        self.inbox = inbox

    # ── Seam defaults (resolved lazily so imports stay decoupled) ──────────

    def _registry(self) -> Any:
        if self.registry is None:
            from services.provider_runtime.registry import registry
            self.registry = registry
        return self.registry

    def _connections(self) -> Any:
        if self.connections is None:
            from services.provider_runtime.connection import (
                ProviderConnectionRepository,
            )
            self.connections = ProviderConnectionRepository()
        return self.connections

    def _broker(self) -> Any:
        if self.broker is None:
            from services.provider_runtime.credential_broker import CredentialBroker
            self.broker = CredentialBroker()
        return self.broker

    def _raw_store(self) -> Any:
        if self.raw_store is None:
            from services.provider_runtime.raw_store import RawProviderRecordStore
            self.raw_store = RawProviderRecordStore()
        return self.raw_store

    def _normalization_engine(self, plugin: Any) -> Any:
        if self.normalization is not None:
            return self.normalization
        from services.provider_runtime.normalization import NormalizationEngine
        return NormalizationEngine(plugin)

    def _bridge(self) -> Any:
        if self.bridge is None:
            from services.provider_runtime.bridge import EventBridge
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
        # 1. Resolve the plugin (hard error when missing) + connection.
        plugin = self._registry().get(identity_key)
        if plugin is None:
            raise ProviderNotInstalled(
                f"provider {identity_key} is not installed in the runtime registry"
            )
        connection = await self._find_connection(tenant_id, identity_key)
        if connection is None:
            raise CredentialMissing(
                f"no connection for tenant={tenant_id!r} provider={identity_key!r}"
            )
        webhook = plugin.webhook()
        if webhook is None:
            await self._store_denial(
                connection, reason="webhook_not_supported",
                error_code="webhook_not_supported", signature=signature,
            )
            return {"accepted": False, "reason": "webhook_not_supported",
                    "record_count": 0, "event_count": 0}

        # 2. WebhookInbox BEFORE verification (best-effort, mirror service.py).
        inbox_id = await self._write_inbox(
            tenant_id, identity_key, raw_body, headers, signature,
        )

        # 3. Resolve the webhook secret per credential shape.
        secret = await self._resolve_webhook_secret(connection)

        # 4. Verify — NEVER silently trust. A webhook is accepted only when the
        # connection proves ownership of the delivery:
        #   * signature scheme  ⇒ a configured secret must verify the delivery;
        #   * endpoint_secret   ⇒ a per-connection endpoint token presented by
        #     the caller must match the connection's configured secret.
        # A missing secret/token is a misconfiguration and is DENIED with an
        # auditable denial record — there is no "no secret ⇒ trust" path.
        manifest = plugin.manifest()
        scheme = None
        try:
            scheme = manifest.webhooks.verification_scheme  # type: ignore[attr-defined]
        except Exception:  # pragma: no cover - defensive; webhooks model always present
            scheme = None
        verified = False
        verification_detail = ""
        if scheme == "endpoint_secret":
            presented = headers.get(
                "X-Aether-Webhook-Endpoint-Token", ""
            ).strip() or (signature or "")
            if not secret:
                verification_detail = (
                    "endpoint_secret scheme but no per-connection webhook "
                    "secret/token configured; cannot prove ownership"
                )
            elif not presented:
                verification_detail = (
                    "endpoint_secret scheme requires a caller-presented "
                    "endpoint token"
                )
            else:
                from services.delivery.security import constant_time_compare

                verified = bool(constant_time_compare(presented, secret))
                if not verified:
                    verification_detail = "endpoint token verification failed"
                else:
                    verification_detail = (
                        "verified via per-connection endpoint token"
                    )
        else:
            if not secret:
                # Signature scheme with no secret configured: nothing to verify
                # against. Deny — never auto-accept.
                verification_detail = (
                    "signature verification scheme but no webhook secret "
                    "configured; cannot verify"
                )
            else:
                try:
                    verified = bool(webhook.verify(raw_body, headers, secret))
                except Exception as exc:  # pragma: no cover - adapter may raise
                    logger.warning(
                        f"provider webhook verify raised tenant={tenant_id} "
                        f"provider={identity_key}: {exc}"
                    )
                    verified = False
                if not verified:
                    verification_detail = "signature verification failed"
        if not verified:
            # Auditable metadata-only denial record (never a payload), then the
            # non-accepted acknowledgement. Mirrors service.py's quarantine.
            await self._store_denial(
                connection, reason="verification_failed",
                error_code="webhook_verification_failed", signature=signature,
                inbox_id=inbox_id,
            )
            logger.warning(
                f"provider webhook rejected tenant={tenant_id} "
                f"provider={identity_key}: {verification_detail}"
            )
            return {"accepted": False, "reason": "verification_failed",
                    "detail": verification_detail, "inbox_id": inbox_id,
                    "record_count": 0, "event_count": 0}

        # 5. Parse → raw store → normalize → bridge.
        payload = self._parse_payload(raw_body, headers)
        if payload is None:
            await self._store_denial(
                connection, reason="invalid_payload",
                error_code="webhook_invalid_payload", signature=signature,
                inbox_id=inbox_id,
            )
            return {"accepted": False, "reason": "invalid_payload",
                    "detail": "webhook body was not valid JSON", "inbox_id": inbox_id,
                    "record_count": 0, "event_count": 0}
        try:
            records = webhook.parse(payload, headers=headers) or []
        except Exception as exc:  # pragma: no cover - adapter parse failure
            logger.warning(
                f"provider webhook parse raised tenant={tenant_id} "
                f"provider={identity_key}: {exc}"
            )
            await self._store_denial(
                connection, reason="parse_failed",
                error_code="webhook_parse_failed", signature=signature,
                inbox_id=inbox_id,
            )
            return {"accepted": False, "reason": "parse_failed",
                    "detail": str(exc)[:200], "inbox_id": inbox_id,
                    "record_count": 0, "event_count": 0}

        if records:
            try:
                await self._raw_store().ingest(records)
            except Exception as exc:  # pragma: no cover - best-effort
                logger.warning(
                    f"provider webhook raw ingest failed tenant={tenant_id} "
                    f"provider={identity_key}: {exc}"
                )
        engine = self._normalization_engine(plugin)
        events = await self._normalize_records(engine, records)
        if events:
            try:
                await self._bridge().ingest_events(tenant_id, events)
            except Exception as exc:  # pragma: no cover - best-effort
                logger.warning(
                    f"provider webhook bridge failed tenant={tenant_id} "
                    f"provider={identity_key}: {exc}"
                )
        if inbox_id:
            try:
                await self._mark_inbox_processed(inbox_id)
            except Exception as exc:  # pragma: no cover - best-effort
                logger.warning(
                    f"provider webhook inbox close failed tenant={tenant_id}: {exc}"
                )
        return {
            "accepted": True,
            "verified": verified,
            "record_count": len(records),
            "event_count": len(events),
            "detail": verification_detail or "webhook accepted",
            "inbox_id": inbox_id,
        }

    # ── Internals ───────────────────────────────────────────────────────────

    async def _find_connection(self, tenant_id: str, identity_key: str) -> Optional[Any]:
        """Locate the tenant's connection for a provider (first match wins)."""
        rows = await self._connections().find_many(
            filters={"tenant_id": tenant_id, "provider_identity": identity_key},
            limit=1,
        )
        if not rows:
            return None
        return _connection_from_row(rows[0])

    async def _write_inbox(
        self,
        tenant_id: str,
        identity_key: str,
        raw_body: bytes,
        headers: Mapping[str, str],
        signature: Optional[str],
    ) -> Optional[str]:
        """WebhookInbox best-effort BEFORE verification (mirror service.py)."""
        inbox_id: Optional[str] = None
        try:
            repo = self.inbox or WebhookInboxRepository()
            inbox_id = str(uuid.uuid4())
            safe_headers = sanitize_headers(dict(headers or {}))
            await repo.insert(inbox_id, {
                "id": inbox_id,
                "tenant_id": tenant_id,
                "provider": identity_key,
                "headers": safe_headers,
                "raw_body": raw_body.decode("utf-8", errors="replace"),
                "signature": signature or "",
                "timestamp": "",
                "verified": False,
                "processed": False,
            })
        except Exception as exc:  # pragma: no cover - best-effort, never break ingestion
            logger.warning(
                f"provider webhook inbox write failed tenant={tenant_id}: {exc}"
            )
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
                f"provider webhook secret resolution failed "
                f"tenant={connection.tenant_id}: {exc}"
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
                account_id=_connection_account_id(connection),
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
        raw_body: bytes, headers: Mapping[str, str],
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
