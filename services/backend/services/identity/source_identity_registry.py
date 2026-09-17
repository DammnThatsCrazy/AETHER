"""Source Identity Registry — registers every external/source identity before canonical resolution.

Responsibilities:
- create source identity
- normalize identifiers
- dedupe source identities
- track first_seen/last_seen
- associate claims
- protect tenant namespace

Every CSV row, Shopify customer, Stripe customer, SDK anonymous ID, SDK user ID,
mobile installation ID, API subject, and agent ID becomes a source identity.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from shared.common.common import utc_now
from shared.logger.logger import get_logger

from .claim_normalizer import normalize_email, normalize_phone, normalize_provider_id
from .models import (
    ConfidenceBand,
    IdentityClaimRecord,
    IdentityDecisionRecord,
    IdentityEdgeRecord,
    IdentityGraphVersionRecord,
    ProjectionType,
    SourceIdentityRecord,
)
from .repository import IdentityResolutionRepository

logger = get_logger("aether.identity.source_registry")


class SourceIdentityRegistry:
    """Registry for source-scoped identities."""

    def __init__(self, repo: IdentityResolutionRepository) -> None:
        self._repo = repo

    async def register_source_identity(
        self,
        tenant_id: str,
        source_system_id: str,
        source_kind: str,
        source_namespace: str,
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
        """Register or find an existing source identity.

        Idempotent: if a source identity with the same identifiers already exists
        for this tenant, return it. Otherwise create a new one.
        """
        now = utc_now()

        # Check for existing by any identifier (idempotency)
        existing = await self._find_existing(
            tenant_id,
            source_system_id,
            external_id=external_id,
            anonymous_id=anonymous_id,
            user_id=user_id,
            device_id=device_id,
            installation_id=installation_id,
            session_id=session_id,
            account_id=account_id,
            agent_id=agent_id,
            runtime_id=runtime_id,
        )
        if existing:
            # Merge new identifiers into existing record (idempotent upsert)
            if not existing.user_id and user_id:
                existing.user_id = user_id
            if not existing.external_id and external_id:
                existing.external_id = external_id
            if not existing.device_id and device_id:
                existing.device_id = device_id
            if not existing.installation_id and installation_id:
                existing.installation_id = installation_id
            if not existing.session_id and session_id:
                existing.session_id = session_id
            if not existing.account_id and account_id:
                existing.account_id = account_id
            if not existing.agent_id and agent_id:
                existing.agent_id = agent_id
            if not existing.runtime_id and runtime_id:
                existing.runtime_id = runtime_id
            existing.last_seen_at = now
            await self._repo.update_source_identity(existing)
            return existing

        # Create new source identity
        record = SourceIdentityRecord(
            id=str(uuid.uuid4()),
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
            status="unresolved",
            first_seen_at=now,
            last_seen_at=now,
            created_at=now,
            updated_at=now,
        )
        await self._repo.create_source_identity(record)
        # Repo generates its own id (in-memory path ignores record.id); fetch stored row
        stored = await self._repo.find_source_identity_by_identifier(tenant_id, "external_id", external_id) if external_id else None
        if not stored and anonymous_id:
            stored = await self._repo.find_source_identity_by_identifier(tenant_id, "anonymous_id", anonymous_id)
        if not stored and user_id:
            stored = await self._repo.find_source_identity_by_identifier(tenant_id, "user_id", user_id)
        if stored:
            # Return the canonical stored record so id matches repo's id
            record = self._dict_to_record(stored)
        logger.info(
            "source_identity.created",
            extra={
                "tenant_id": tenant_id,
                "source_identity_id": record.id,
                "source_kind": source_kind,
            },
        )
        return record

    async def _find_existing(
        self,
        tenant_id: str,
        source_system_id: str,
        external_id: Optional[str] = None,
        anonymous_id: Optional[str] = None,
        user_id: Optional[str] = None,
        device_id: Optional[str] = None,
        installation_id: Optional[str] = None,
        session_id: Optional[str] = None,
        account_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        runtime_id: Optional[str] = None,
    ) -> Optional[SourceIdentityRecord]:
        """Find an existing source identity by any matching identifier."""
        # Check by each identifier type — prefer user_id/auth-id over anonymous_id
        # so that identify() calls match on the authoritative user_id first.
        for identifier_type, identifier_value in [
            ("external_id", external_id),
            ("user_id", user_id),
            ("anonymous_id", anonymous_id),
            ("device_id", device_id),
            ("installation_id", installation_id),
            ("session_id", session_id),
            ("account_id", account_id),
            ("agent_id", agent_id),
            ("runtime_id", runtime_id),
        ]:
            if not identifier_value:
                continue
            result = await self._repo.find_source_identity_by_identifier(
                tenant_id, identifier_type, identifier_value
            )
            if result:
                return self._dict_to_record(result)
        return None

    @staticmethod
    def _dict_to_record(d: dict) -> SourceIdentityRecord:
        """Convert a repository dict row into a SourceIdentityRecord."""
        return SourceIdentityRecord(
            id=d.get("id", ""),
            tenant_id=d.get("tenant_id", ""),
            source_system_id=d.get("source_system_id", ""),
            source_kind=d.get("source_kind", d.get("kind", "")),
            source_namespace=d.get("source_namespace", ""),
            external_id=d.get("external_id"),
            anonymous_id=d.get("anonymous_id"),
            user_id=d.get("user_id"),
            device_id=d.get("device_id"),
            installation_id=d.get("installation_id"),
            session_id=d.get("session_id"),
            account_id=d.get("account_id"),
            agent_id=d.get("agent_id"),
            runtime_id=d.get("runtime_id"),
            canonical_entity_id=d.get("canonical_entity_id"),
            status=d.get("status", "unresolved"),
            first_seen_at=d.get("first_seen_at", ""),
            last_seen_at=d.get("last_seen_at", ""),
            created_at=d.get("created_at", ""),
            updated_at=d.get("updated_at", ""),
        )

    async def upsert_identity_claim(
        self,
        tenant_id: str,
        source_identity_id: str,
        claim_type: str,
        raw_value: str,
        verification_status: str = "observed",
        confidence_hint: Optional[float] = None,
        occurred_at: Optional[str] = None,
        expires_at: Optional[str] = None,
        pii_classification: str = "none",
        idempotency_key: Optional[str] = None,
    ) -> IdentityClaimRecord:
        """Normalize and store an identity claim.

        Normalization rules:
        - email: lowercase, strip whitespace, normalize domain
        - phone: E.164 format
        - provider IDs: preserve as-is but normalize whitespace
        """
        normalized_value = self._normalize_claim_value(claim_type, raw_value)

        # Check for duplicate claim (same source_identity + claim_type + normalized_value)
        existing = await self._repo.find_claim(
            tenant_id, source_identity_id, claim_type, normalized_value
        )
        if existing and existing.get("status") == "active":
            return existing

        if existing:
            # Reactivate suppressed/expired claim
            existing["status"] = "active"
            existing["verification_status"] = verification_status
            existing["confidence_hint"] = confidence_hint
            existing["expires_at"] = expires_at
            existing["updated_at"] = utc_now().isoformat()
            await self._repo.update_claim(self._dict_to_record(existing))
            return self._dict_to_record(existing)

        now = utc_now()
        record = IdentityClaimRecord(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            source_identity_id=source_identity_id,
            claim_type=claim_type,
            normalized_value=normalized_value,
            raw_value=raw_value,
            verification_status=verification_status,
            confidence_hint=confidence_hint,
            occurred_at=occurred_at,
            ingested_at=now,
            expires_at=expires_at,
            pii_classification=self._classify_pii(claim_type, normalized_value),
            status="active",
            created_at=now,
        )
        await self._repo.create_claim(record)
        logger.info(
            "identity.claim.created",
            extra={
                "tenant_id": tenant_id,
                "claim_id": record.id,
                "claim_type": claim_type,
            },
        )
        return record

    def _normalize_claim_value(self, claim_type: str, raw_value: str) -> str:
        """Normalize a claim value based on its type."""
        if not raw_value:
            return ""

        if claim_type == "email":
            return normalize_email(raw_value)
        elif claim_type == "phone":
            return normalize_phone(raw_value)
        elif claim_type in ("external_customer_id", "app_user_id", "account_id"):
            return normalize_provider_id(raw_value)
        elif claim_type in ("anonymous_id", "device_id", "installation_id", "session_id"):
            return raw_value.strip().lower()
        else:
            return raw_value.strip()

    def _classify_pii(self, claim_type: str, normalized_value: str) -> str:
        """Classify PII level for a claim."""
        sensitive_types = {"email", "phone", "wallet_address", "auth_subject"}
        moderate_types = {"name", "address", "device_id", "installation_id"}

        if claim_type in sensitive_types:
            return "sensitive"
        elif claim_type in moderate_types:
            return "moderate"
        elif claim_type in {"external_customer_id", "user_id", "account_id", "agent_id"}:
            return "low"
        return "none"

    async def find_existing_source_identity(
        self,
        tenant_id: str,
        **identifiers: Optional[str],
    ) -> Optional[SourceIdentityRecord]:
        """Public lookup by any identifier."""
        return await self._find_existing(tenant_id, "", **identifiers)

    async def get_claims_for_source_identity(
        self, source_identity_id: str
    ) -> list[IdentityClaimRecord]:
        """List all active claims for a source identity."""
        dicts = await self._repo.get_claims_for_source(source_identity_id)
        return [self._dict_to_claim_record(d) for d in dicts]

    def _dict_to_claim_record(self, d: dict) -> IdentityClaimRecord:
        """Convert a repository dict row into an IdentityClaimRecord."""
        return IdentityClaimRecord(
            id=d.get("id", ""),
            tenant_id=d.get("tenant_id", ""),
            source_identity_id=d.get("source_identity_id", ""),
            claim_type=d.get("claim_type", ""),
            normalized_value=d.get("normalized_value", ""),
            raw_value=d.get("raw_value"),
            verification_status=d.get("verification_status", "observed"),
            confidence_hint=d.get("confidence_hint"),
            occurred_at=d.get("occurred_at"),
            ingested_at=d.get("ingested_at", ""),
            expires_at=d.get("expires_at"),
            pii_classification=d.get("pii_classification", "none"),
            status=d.get("status", "active"),
            created_at=d.get("created_at", ""),
        )

    async def mark_suppressed(
        self, source_identity_id: str, reason: str = "manual"
    ) -> None:
        """Mark a source identity and its claims as suppressed."""
        now = utc_now().isoformat()
        identity = await self._repo.get_source_identity(source_identity_id)
        if identity:
            identity["status"] = "suppressed"
            identity["updated_at"] = now
            record = self._dict_to_record(identity)
            record.status = "suppressed"
            record.updated_at = now
            await self._repo.update_source_identity(record)

        # Suppress all active claims
        claims = await self._repo.get_claims_for_source(source_identity_id)
        for claim_dict in claims:
            if claim_dict.get("status") == "active":
                claim_dict["status"] = "suppressed"
                claim_dict["updated_at"] = now
                await self._repo.update_claim(self._dict_to_claim_record(claim_dict))

        logger.info(
            "source_identity.suppressed",
            extra={
                "source_identity_id": source_identity_id,
                "reason": reason,
            },
        )
