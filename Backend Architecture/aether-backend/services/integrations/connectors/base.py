"""Inbound connector framework — contracts + base adapter.

A connector pulls/receives events from an external SaaS platform and normalizes
them into Aether's event envelope for graph enrichment. Adapters are
import-safe, disabled by default, and mocked in local mode; real API calls are
credential-gated TODOs. Secrets are never stored in `ConnectorConfig.config` or
returned via the API — only a non-secret `secret_configured` signal is exposed.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

ConnectorType = Literal[
    "slack", "webhook", "shopify", "stripe", "hubspot", "salesforce",
    "klaviyo", "segment", "posthog", "ga4", "jira", "linear", "zendesk", "intercom",
]

ConnectorCategory = Literal[
    "messaging", "webhook", "commerce", "billing", "crm", "marketing",
    "product_analytics", "project", "support",
]

ConnectorSyncStatus = Literal[
    "never_synced", "syncing", "healthy", "degraded", "failed", "disabled",
]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class ConnectorConfig(BaseModel):
    """Tenant-scoped connector configuration. Never carries raw secrets."""
    config_id: str = Field(default_factory=lambda: f"conn_{uuid.uuid4().hex[:12]}")
    tenant_id: str
    connector_type: ConnectorType
    name: str = ""
    enabled: bool = False  # disabled by default
    config: dict[str, Any] = Field(default_factory=dict)  # non-secret settings only
    secret_configured: bool = False  # whether a secret exists in the vault (no value)
    secret_ref: Optional[str] = None  # vault reference, never the secret itself
    last_synced_at: Optional[str] = None
    sync_status: ConnectorSyncStatus = "never_synced"
    error_count: int = 0
    last_error_at: Optional[str] = None
    last_error_message: Optional[str] = None
    created_at: str = Field(default_factory=now_iso)
    updated_at: str = Field(default_factory=now_iso)


class ConnectorDescriptor(BaseModel):
    connector_type: ConnectorType
    label: str
    category: ConnectorCategory
    description: str
    supports_webhook: bool
    supports_pull: bool
    requires_secret: bool
    premium: bool
    ingest_event_types: list[str]
    docs_slug: str


class ConnectionTestResult(BaseModel):
    connector_type: ConnectorType
    ok: bool
    status: str  # "ok" | "not_configured" | "disabled" | "error"
    detail: str = ""
    checked_at: str = Field(default_factory=now_iso)


class NormalizedEvent(BaseModel):
    """Connector event normalized toward the SDK ingestion envelope."""
    event_type: str
    source: str  # connector_type
    external_id: Optional[str] = None
    occurred_at: str = Field(default_factory=now_iso)
    properties: dict[str, Any] = Field(default_factory=dict)


class SyncResult(BaseModel):
    connector_type: ConnectorType
    status: ConnectorSyncStatus
    events_ingested: int = 0
    events: list[NormalizedEvent] = Field(default_factory=list)
    detail: str = ""
    synced_at: str = Field(default_factory=now_iso)


class BaseConnector:
    """Base inbound connector. Subclasses set descriptors + mapping; the service
    layer owns metering/audit/reliability/data-quality side effects."""

    connector_type: ConnectorType = "webhook"
    label: str = "Base connector"
    category: ConnectorCategory = "webhook"
    description: str = "Base inbound connector"
    supports_webhook: bool = True
    supports_pull: bool = False
    requires_secret: bool = True
    premium: bool = False
    ingest_event_types: tuple[str, ...] = ()
    docs_slug: str = "operations/connectors"

    def descriptor(self) -> ConnectorDescriptor:
        return ConnectorDescriptor(
            connector_type=self.connector_type,
            label=self.label,
            category=self.category,
            description=self.description,
            supports_webhook=self.supports_webhook,
            supports_pull=self.supports_pull,
            requires_secret=self.requires_secret,
            premium=self.premium,
            ingest_event_types=list(self.ingest_event_types),
            docs_slug=self.docs_slug,
        )

    def validate_config(self, config: ConnectorConfig) -> None:
        if config.connector_type != self.connector_type:
            raise ValueError("connector_type mismatch")
        # Secrets must never be placed in the non-secret config blob.
        for key in config.config:
            if any(s in key.lower() for s in ("secret", "token", "api_key", "password", "credential")):
                raise ValueError(f"secret-like key {key!r} must not be stored in config; use the vault")

    async def test_connection(
        self, config: ConnectorConfig, secret: Optional[str] = None
    ) -> ConnectionTestResult:
        """Default mocked test. Subclasses override with a live API ping.

        When secret is provided and the environment is non-local, subclass
        implementations should make a real API health-check call.
        """
        if not config.enabled:
            return ConnectionTestResult(connector_type=self.connector_type, ok=False, status="disabled",
                                        detail="connector disabled")
        if self.requires_secret and not config.secret_configured:
            return ConnectionTestResult(connector_type=self.connector_type, ok=False, status="not_configured",
                                        detail="missing credential (configure secret in the vault)")
        return ConnectionTestResult(connector_type=self.connector_type, ok=True, status="ok",
                                    detail="mocked connection ok (local mode)")

    async def pull(
        self, config: ConnectorConfig, since: Optional[str] = None, secret: Optional[str] = None
    ) -> list[NormalizedEvent]:
        """Default mocked pull → no events. Subclasses override.

        When secret is provided and the environment is non-local, subclass
        implementations make real API list/sync calls. Must remain tenant-scoped
        and rate-limited.
        """
        return []

    def parse_webhook(self, payload: dict[str, Any]) -> list[NormalizedEvent]:
        """Map a verified inbound webhook payload to normalized events.

        Default maps the whole payload to one event; adapters refine per provider.
        """
        event_type = str(payload.get("type") or payload.get("event") or f"{self.connector_type}.event")
        return [NormalizedEvent(
            event_type=event_type,
            source=self.connector_type,
            external_id=str(payload.get("id")) if payload.get("id") is not None else None,
            properties={k: v for k, v in payload.items() if k not in ("id",)},
        )]
