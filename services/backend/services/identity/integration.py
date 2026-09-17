"""Source identity wire-up for production ingestion paths.

Wires the SourceIdentityRegistry into:
- SDK ingestion adapter (SDK events → source identity creation)
- SDK lifecycle routes (heartbeat, identify, alias, reset)
- Provider sync (Shopify, Stripe, CRM — when they emit customer data)
- CSV import pipeline (when rows are ingested)

This module is the bridge between the identity continuity runtime
and the actual ingestion entry points.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from services.identity.source_identity_registry import SourceIdentityRegistry
from services.identity.models import SourceIdentityRecord

logger = logging.getLogger("aether.identity.integration")


class IdentityIngestionWire:
    """Bridges ingestion paths to the source identity registry.

    In production, each ingestion entry point calls
    ``ensure_source_identity`` to guarantee that every observed
    external identifier becomes a source-scoped identity record
    before canonical resolution.
    """

    def __init__(self, registry: SourceIdentityRegistry) -> None:
        self._registry = registry

    async def ensure_source_identity(
        self,
        tenant_id: str,
        source_system_id: str,
        source_kind: str,
        source_namespace: str,
        *,
        external_id: Optional[str] = None,
        anonymous_id: Optional[str] = None,
        user_id: Optional[str] = None,
        device_id: Optional[str] = None,
        installation_id: Optional[str] = None,
        session_id: Optional[str] = None,
        account_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        runtime_id: Optional[str] = None,
        idempotency_key: Optional[str] = None,
        source_record_id: Optional[str] = None,
    ) -> SourceIdentityRecord:
        """Ensure a source identity exists for the given identifiers.

        Idempotent: returns existing record if one matches by any
        identifier, otherwise creates a new one.
        """
        return await self._registry.register_source_identity(
            tenant_id=tenant_id,
            source_system_id=source_system_id,
            source_kind=source_kind,
            source_namespace=source_namespace,
            external_id=external_id,
            anonymous_id=anonymous_id,
            user_id=user_id,
            device_id=device_id,
            installation_id=installation_id,
            session_id=session_id,
            account_id=account_id,
            agent_id=agent_id,
            runtime_id=runtime_id,
            idempotency_key=idempotency_key,
            source_record_id=source_record_id,
        )

    async def extract_and_register_from_sdk_event(
        self,
        tenant_id: str,
        source_system_id: str,
        normalized_event: dict[str, Any],
    ) -> Optional[SourceIdentityRecord]:
        """Extract identity fields from a normalized SDK event and register.

        Called by the SDK ingestion adapter after the event is validated.
        """
        anonymous_id = normalized_event.get("anonymous_id")
        user_id = normalized_event.get("user_id")
        device_id = normalized_event.get("device_id")
        installation_id = normalized_event.get("installation_id")
        session_id = normalized_event.get("session_id")
        idempotency_key = normalized_event.get("idempotency_key")

        if not anonymous_id and not user_id and not installation_id:
            return None

        sdk_name = normalized_event.get("sdk_name", "aether-web")
        source_namespace = normalized_event.get(
            "source_namespace", f"{sdk_name}:unknown"
        )

        return await self.ensure_source_identity(
            tenant_id=tenant_id,
            source_system_id=source_system_id,
            source_kind="sdk" if user_id else "sdk",
            source_namespace=source_namespace,
            anonymous_id=anonymous_id,
            user_id=user_id,
            device_id=device_id,
            installation_id=installation_id,
            session_id=session_id,
            idempotency_key=idempotency_key,
        )

    async def extract_and_register_from_provider_customer(
        self,
        tenant_id: str,
        source_system_id: str,
        provider: str,
        customer_data: dict[str, Any],
    ) -> Optional[SourceIdentityRecord]:
        """Extract identity fields from a provider customer record and register.

        Called by connector/provider sync when customer data is ingested.
        """
        external_id = customer_data.get("id") or customer_data.get("customer_id")
        email = customer_data.get("email")
        phone = customer_data.get("phone")
        user_id = customer_data.get("user_id") or customer_data.get("app_user_id")
        device_id = customer_data.get("device_id")
        account_id = customer_data.get("account_id")

        if not external_id and not email:
            return None

        return await self.ensure_source_identity(
            tenant_id=tenant_id,
            source_system_id=source_system_id,
            source_kind="connector",
            source_namespace=f"{provider}:{tenant_id}",
            external_id=str(external_id) if external_id else None,
            user_id=user_id,
        )
