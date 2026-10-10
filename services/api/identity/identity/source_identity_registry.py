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
from .hashing import hash_value
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
            source_namespace=source_namespace,
            source_record_id=source_record_id,
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
        # An anonymous/device identifier can be shared over time. If an
        # existing source record already carries a different authenticated
        # app user, preserve a separate source record for this binding instead
        # of overwriting provenance. The canonical resolver independently
        # decides whether the two observations may be linked.
        if (
            existing
            and existing.user_id
            and user_id
            and existing.user_id != user_id
        ):
            existing = None
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
            source_record_id=source_record_id,
            status="unresolved",
            first_seen_at=now,
            last_seen_at=now,
            created_at=now,
            updated_at=now,
        )
        await self._repo.create_source_identity(record)
        # Repo generates its own id (in-memory path ignores record.id); fetch stored row
        stored = await self._repo.find_source_identity_by_identifier(
            tenant_id, "external_id", external_id, source_namespace=source_namespace
        ) if external_id else None
        if not stored and anonymous_id:
            stored = await self._repo.find_source_identity_by_identifier(
                tenant_id, "anonymous_id", anonymous_id, source_namespace=source_namespace
            )
        if not stored and user_id:
            stored = await self._repo.find_source_identity_by_identifier(
                tenant_id, "user_id", user_id, source_namespace=source_namespace
            )
        if not stored and source_record_id:
            stored = await self._repo.find_source_identity_by_identifier(
                tenant_id,
                "source_record_id",
                source_record_id,
                source_namespace=source_namespace,
            )
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

    async def ensure_provisional_profile(
        self, *, tenant_id: str, source_identity_id: str
    ) -> str:
        """Attach imported source evidence to its own provisional profile.

        This is intentionally source-local. It does not inspect shared email or
        phone claims, create aliases, or merge profiles. Import, connector and
        SDK callers use it only when the canonical resolver has not authorized
        an ownership link, so ambiguous evidence remains an addressable
        provisional profile instead of being attached to a candidate.
        """
        row = await self._repo.get_source_identity(source_identity_id)
        if not row or row.get("tenant_id") != tenant_id:
            raise ValueError("source identity is unavailable in this tenant")
        if row.get("source_kind") not in {"csv", "connector", "sdk"}:
            raise ValueError("source kind is not eligible for provisionalization")
        if row.get("status") not in {"unresolved", "provisional"}:
            raise ValueError("source identity is not eligible for provisionalization")

        canonical_entity_id = row.get("canonical_entity_id")
        if canonical_entity_id:
            existing_subject = await self._repo.get_subject_by_canonical_entity_id(
                tenant_id, str(canonical_entity_id)
            )
            if not existing_subject:
                raise ValueError("source identity points to a missing profile")
            return str(canonical_entity_id)

        subject = await self._repo.ensure_provisional_source_subject(
            tenant_id=tenant_id,
            source_identity_id=source_identity_id,
            source_kind=str(row.get("source_kind") or ""),
            source_namespace=str(row.get("source_namespace") or ""),
        )
        record = self._dict_to_record(row)
        record.canonical_entity_id = str(subject["canonical_entity_id"])
        await self._repo.update_source_identity(record)
        return record.canonical_entity_id

    async def _find_existing(
        self,
        tenant_id: str,
        source_system_id: str,
        source_namespace: Optional[str] = None,
        external_id: Optional[str] = None,
        anonymous_id: Optional[str] = None,
        user_id: Optional[str] = None,
        device_id: Optional[str] = None,
        installation_id: Optional[str] = None,
        session_id: Optional[str] = None,
        account_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        runtime_id: Optional[str] = None,
        source_record_id: Optional[str] = None,
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
            ("source_record_id", source_record_id),
        ]:
            if not identifier_value:
                continue
            result = await self._repo.find_source_identity_by_identifier(
                tenant_id,
                identifier_type,
                identifier_value,
                source_namespace=source_namespace,
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
            source_record_id=d.get("source_record_id"),
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
        source_record_id: Optional[str] = None,
        import_id: Optional[str] = None,
        import_commit_id: Optional[str] = None,
        hash_sensitive_value: bool = False,
    ) -> IdentityClaimRecord:
        """Normalize and store an identity claim.

        Normalization rules:
        - email: lowercase, strip whitespace, normalize domain
        - phone: E.164 format
        - provider IDs: preserve as-is but normalize whitespace
        """
        normalized_claim_value = self._normalize_claim_value(claim_type, raw_value)
        if hash_sensitive_value and claim_type in {"email", "phone"}:
            normalized_value = hash_value(
                normalized_claim_value,
                scope=f"{claim_type}:{tenant_id}",
            )
        else:
            normalized_value = normalized_claim_value
        if not normalized_value:
            raise ValueError("identity claim value is invalid")
        stored_raw_value = (
            None
            if hash_sensitive_value and claim_type in {"email", "phone"}
            else raw_value
        )

        source_identity = await self._repo.get_source_identity(source_identity_id)
        if (
            source_identity is None
            or source_identity.get("tenant_id") != tenant_id
        ):
            raise ValueError("source identity is unavailable in this tenant")
        source_suppressed = source_identity.get("status") == "suppressed"

        # Check for duplicate claim (same source_identity + claim_type + normalized_value)
        existing = await self._repo.find_claim(
            tenant_id, source_identity_id, claim_type, normalized_value,
            source_record_id=source_record_id,
        )
        if existing and existing.get("status") == "active":
            if import_id is not None or import_commit_id is not None:
                existing_record = self._dict_to_claim_record(existing)
                existing_record.import_id = import_id or existing_record.import_id
                existing_record.import_commit_id = (
                    import_commit_id or existing_record.import_commit_id
                )
                existing_record.updated_at = utc_now()
                await self._repo.update_claim(existing_record)
            return self._dict_to_claim_record(existing)

        if existing:
            # Expired evidence may be renewed by a fresh import. Suppression
            # is a durable non-resurrection boundary: neither a replay nor a
            # claim refresh may reactivate the claim or its source identity.
            if existing.get("status") == "suppressed" or source_suppressed:
                return self._dict_to_claim_record(existing)
            existing["status"] = "active"
            existing["verification_status"] = verification_status
            existing["confidence_hint"] = confidence_hint
            existing["expires_at"] = expires_at
            if import_id is not None:
                existing["import_id"] = import_id
            if import_commit_id is not None:
                existing["import_commit_id"] = import_commit_id
            existing["updated_at"] = utc_now().isoformat()
            await self._repo.update_claim(self._dict_to_record(existing))
            return self._dict_to_record(existing)

        if source_suppressed:
            await self._persist_identifier_suppression(
                tenant_id=tenant_id,
                claim_type=claim_type,
                normalized_value=normalized_claim_value,
                digest_is_hashed=False,
                reason="source_identity_suppressed",
            )

        now = utc_now()
        record = IdentityClaimRecord(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            source_identity_id=source_identity_id,
            source_record_id=source_record_id,
            import_id=import_id,
            import_commit_id=import_commit_id,
            claim_type=claim_type,
            normalized_value=normalized_value,
            raw_value=stored_raw_value,
            verification_status=verification_status,
            confidence_hint=confidence_hint,
            occurred_at=occurred_at,
            ingested_at=now,
            expires_at=expires_at,
            pii_classification=self._classify_pii(claim_type, normalized_value),
            status="suppressed" if source_suppressed else "active",
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

    async def _persist_identifier_suppression(
        self,
        *,
        tenant_id: str,
        claim_type: str,
        normalized_value: str,
        digest_is_hashed: bool,
        reason: str,
    ) -> None:
        signal_type = {"email": "email_hash", "phone": "phone_hash"}.get(claim_type)
        if not signal_type or not normalized_value:
            return
        identifier_hash = (
            normalized_value
            if digest_is_hashed
            else hash_value(normalized_value, scope=f"{claim_type}:{tenant_id}")
        )
        await self._repo.create_suppression_rule(
            tenant_id=tenant_id,
            identifier_hash=identifier_hash,
            identifier_type=signal_type,
            reason=reason,
            created_by="source_identity_suppression",
        )

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
        source_namespace: Optional[str] = None,
        **identifiers: Optional[str],
    ) -> Optional[SourceIdentityRecord]:
        """Public lookup by identifier, optionally within a source namespace."""
        return await self._find_existing(
            tenant_id, "", source_namespace=source_namespace, **identifiers
        )

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
            source_record_id=d.get("source_record_id"),
            import_id=d.get("import_id"),
            import_commit_id=d.get("import_commit_id"),
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
            updated_at=d.get("updated_at", d.get("created_at", "")),
        )

    async def mark_suppressed(
        self, source_identity_id: str, reason: str = "manual"
    ) -> None:
        """Suppress a source identity, claims, and their linkable identifiers.

        A source/claim tombstone alone is insufficient: later live SDK evidence
        can arrive without consulting the source registry. Persist tenant-scoped
        suppression rules for email and phone digests so the resolver also
        refuses to recreate aliases from those identifiers.
        """
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
            claim_type = str(claim_dict.get("claim_type") or "")
            normalized_value = str(claim_dict.get("normalized_value") or "")
            if identity and normalized_value:
                raw_value_retained = claim_dict.get("raw_value") is not None
                digest_is_hashed = (
                    not raw_value_retained
                    and len(normalized_value) == 64
                    and all(char in "0123456789abcdef" for char in normalized_value.lower())
                )
                await self._persist_identifier_suppression(
                    tenant_id=identity["tenant_id"],
                    claim_type=claim_type,
                    normalized_value=normalized_value,
                    digest_is_hashed=digest_is_hashed,
                    reason=reason,
                )
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
