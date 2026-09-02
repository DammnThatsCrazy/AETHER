"""Verification evidence service (identity assurance layer, prompt §5x/§56).

Wraps :class:`VerificationEvidenceRepository` to issue and revoke durable,
tenant-scoped proof that an identifier's ownership was verified. Emitting or
revoking evidence *best-effort* triggers a resolution replay so the resolver
(Agent C) re-scores affected identities — but a replay failure must NEVER break
evidence issuance, so the trigger is wrapped in a broad try/except.

This module is additive and mirrors ``decision_evidence.py``'s style. It never
persists a raw OTP/token and never logs PII or secrets.
"""

from __future__ import annotations

import uuid
from typing import Any, Optional

from shared.common.common import utc_now
from shared.events.events import Event, EventProducer, Topic
from shared.logger.logger import get_logger

from .metrics import IdentityMetrics
from .models import (
    IdentitySignalType,
    VerificationEvidence,
    VerificationEvidenceStatus,
    VerificationEvidenceType,
)
from .verification_repository import VerificationEvidenceRepository

logger = get_logger("aether.service.identity.evidence")


# Operator-facing evidence is redacted (§56): secret-ish fields (proof_digest,
# proof_reference, issuer_subject_hash, consent_snapshot, raw metadata) are
# dropped. Only these non-sensitive fields are surfaced.
_REDACTED_EVIDENCE_FIELDS = (
    "id",
    "identifier_hash",
    "identifier_type",
    "evidence_type",
    "verification_method",
    "status",
    "verified_at",
    "revoked_at",
    "expires_at",
    "assurance_level",
    "issuer",
    "canonical_entity_id",
)

# Evidence-type -> resolver signal mapping.
_EVIDENCE_SIGNAL_MAP = {
    VerificationEvidenceType.EMAIL_OWNERSHIP_VERIFIED.value: (
        IdentitySignalType.EMAIL_OWNERSHIP_VERIFIED
    ),
    VerificationEvidenceType.WALLET_OWNERSHIP_VERIFIED.value: (
        IdentitySignalType.WALLET_SIGNATURE_VERIFIED
    ),
    VerificationEvidenceType.PHONE_OWNERSHIP_VERIFIED.value: (
        IdentitySignalType.PHONE_HASH
    ),
}


class EvidenceService:
    """Issue / revoke ownership-verification evidence with replay fan-out."""

    def __init__(
        self,
        repo: Optional[VerificationEvidenceRepository] = None,
        metrics: Optional[IdentityMetrics] = None,
        replay_service: Any = None,
        producer: Optional[EventProducer] = None,
    ) -> None:
        self._repo = repo or VerificationEvidenceRepository()
        self._metrics = metrics or IdentityMetrics()
        # Optional injected replay service — tests pass a fake and assert it was
        # called; None routes replay through the async event worker (production)
        # or lazily constructs the real service inline (local without a bus).
        self._replay_service = replay_service
        # Event producer for verification-lifecycle + replay-request events.
        # Optional/injectable (tests); when absent it is lazily resolved from the
        # shared registry, mirroring the resolver. A lookup failure degrades to
        # no-publish — events must never break evidence issuance.
        self._producer = producer

    async def issue_evidence(
        self,
        *,
        tenant_id: str,
        identifier_type: str,
        identifier_hash: str,
        verification_method: str,
        evidence_type: str = VerificationEvidenceType.EMAIL_OWNERSHIP_VERIFIED.value,
        issuer: str = "aether",
        issuer_subject_hash: Optional[str] = None,
        challenge_id: Optional[str] = None,
        source_event_id: Optional[str] = None,
        proof_reference: Optional[str] = None,
        proof_digest: Optional[str] = None,
        assurance_level: str = "verified",
        consent_snapshot: Optional[dict] = None,
        expires_at: Optional[str] = None,
        policy_version: str = "1.0.0",
        metadata: Optional[dict] = None,
    ) -> VerificationEvidence:
        """Build, persist, and return a :class:`VerificationEvidence` row.

        After persistence a resolution replay is triggered best-effort; a replay
        failure is swallowed so evidence issuance always succeeds.
        """
        evidence = VerificationEvidence(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            evidence_type=evidence_type,
            identifier_type=identifier_type,
            identifier_hash=identifier_hash,
            verification_method=verification_method,
            assurance_level=assurance_level,
            issuer=issuer,
            issuer_subject_hash=issuer_subject_hash,
            challenge_id=challenge_id,
            source_event_id=source_event_id,
            proof_reference=proof_reference,
            proof_digest=proof_digest,
            status=VerificationEvidenceStatus.ACTIVE.value,
            verified_at=utc_now().isoformat(),
            expires_at=expires_at,
            policy_version=policy_version,
            consent_snapshot=consent_snapshot,
            metadata=dict(metadata or {}),
        )
        await self._repo.create(evidence)
        self._metrics.record_evidence_active(evidence_type)
        verification = {
            "evidence_id": evidence.id,
            "issuer": issuer,
            "method": verification_method,
            "policy_version": policy_version,
        }
        await self._publish_lifecycle(
            Topic.IDENTITY_VERIFICATION_COMPLETED,
            tenant_id=tenant_id,
            payload={
                "evidence_id": evidence.id,
                "identifier_type": identifier_type,
                "identifier_hash": identifier_hash,
                "evidence_type": evidence_type,
                "verification_method": verification_method,
                "issuer": issuer,
                "assurance_level": assurance_level,
                "policy_version": policy_version,
            },
        )
        await self._trigger_replay(
            tenant_id=tenant_id,
            identifier_type=identifier_type,
            identifier_hash=identifier_hash,
            trigger_type="verification_evidence_issued",
            trigger_id=evidence.id,
            policy_version=policy_version,
            consent_snapshot=consent_snapshot,
            verification=verification,
        )
        return evidence

    async def revoke_evidence(
        self, tenant_id: str, evidence_id: str, reason: str = ""
    ) -> Optional[dict]:
        """Revoke an evidence row and best-effort trigger a replay.

        Returns the updated row, or ``None`` if it did not exist for the tenant.
        """
        row = await self._repo.revoke(tenant_id, evidence_id, reason=reason)
        if row is None:
            return None
        self._metrics.record_evidence_revoked(row.get("evidence_type", ""))
        verification = {
            "evidence_id": evidence_id,
            "issuer": row.get("issuer", ""),
            "method": row.get("verification_method", ""),
            "policy_version": row.get("policy_version", "1.0.0"),
            "revoked": True,
        }
        await self._publish_lifecycle(
            Topic.IDENTITY_VERIFICATION_REVOKED,
            tenant_id=tenant_id,
            payload={
                "evidence_id": evidence_id,
                "identifier_type": row.get("identifier_type", ""),
                "identifier_hash": row.get("identifier_hash", ""),
                "evidence_type": row.get("evidence_type", ""),
                "verification_method": row.get("verification_method", ""),
                "issuer": row.get("issuer", ""),
                "reason": reason,
            },
        )
        await self._trigger_replay(
            tenant_id=tenant_id,
            identifier_type=row.get("identifier_type", ""),
            identifier_hash=row.get("identifier_hash", ""),
            trigger_type="verification_evidence_revoked",
            trigger_id=evidence_id,
            policy_version=row.get("policy_version", "1.0.0"),
            consent_snapshot=row.get("consent_snapshot"),
            verification=verification,
        )
        return row

    async def list_for_entity(
        self, tenant_id: str, canonical_entity_id: str
    ) -> list[dict]:
        """Operator-facing, REDACTED evidence for an entity (§56)."""
        rows = await self._repo.get_for_entity(tenant_id, canonical_entity_id)
        return [self._redact(row) for row in rows]

    def evidence_to_signal(self, evidence: Any) -> tuple[IdentitySignalType, str]:
        """Map an evidence row/object to a resolver signal + identifier hash."""
        if isinstance(evidence, dict):
            evidence_type = evidence.get("evidence_type")
            identifier_hash = evidence.get("identifier_hash", "")
        else:
            evidence_type = getattr(evidence, "evidence_type", None)
            identifier_hash = getattr(evidence, "identifier_hash", "")
        signal = _EVIDENCE_SIGNAL_MAP.get(
            evidence_type, IdentitySignalType.EMAIL_OWNERSHIP_VERIFIED
        )
        return signal, identifier_hash or ""

    # ── internals ──────────────────────────────────────────────────────────

    @staticmethod
    def _redact(row: dict) -> dict:
        return {key: row.get(key) for key in _REDACTED_EVIDENCE_FIELDS if key in row}

    def _resolve_producer(self) -> Optional[EventProducer]:
        """Return the event producer, falling back to the shared registry.

        verification.py / routes.py construct this service without a producer, so
        when none was injected obtain the process-wide producer (the same one the
        resolver and operator merge route publish through). The import is deferred
        to avoid a provider import cycle. A lookup failure degrades to no-publish
        — events must never break evidence issuance.
        """
        if self._producer is not None:
            return self._producer
        try:
            from dependencies.providers import get_producer

            self._producer = get_producer()
        except Exception as exc:  # noqa: BLE001 - never break issuance
            logger.warning("evidence service could not obtain a producer: %s", exc)
            return None
        return self._producer

    async def _publish_lifecycle(
        self, topic: Topic, *, tenant_id: str, payload: dict
    ) -> None:
        """Best-effort publish of a verification-lifecycle event.

        Never raises — a bus failure must not break issuance/revocation. Payloads
        carry only hashed identifiers and provenance, never raw PII or secrets.
        """
        try:
            producer = self._resolve_producer()
            if producer is None:
                return
            await producer.publish(Event(
                topic=topic,
                tenant_id=tenant_id,
                source_service="identity",
                payload=payload,
            ))
        except Exception as exc:  # noqa: BLE001 - lifecycle events are best-effort
            logger.warning(
                "verification lifecycle publish failed (%s): %s", topic, exc
            )

    async def _trigger_replay(
        self,
        *,
        tenant_id: str,
        identifier_type: str,
        identifier_hash: str,
        trigger_type: str,
        trigger_id: str,
        policy_version: str,
        consent_snapshot: Optional[dict],
        verification: Optional[dict] = None,
    ) -> None:
        """Fan out a resolution replay for the affected identifier.

        Production path (no inline service injected): publish
        ``IDENTITY_RESOLUTION_REPLAY_REQUESTED`` so the durable, retryable replay
        worker (services.runtime.consumer_specs) runs it off the request path.
        Fallback path (an injected replay service — tests — or no producer
        available — local without a bus): run the replay inline. Lazy imports
        avoid an import cycle. Any failure is swallowed — replay must NEVER break
        evidence issuance.
        """
        try:
            # Async worker path: emit an event a registered consumer will run.
            if self._replay_service is None:
                producer = self._resolve_producer()
                if producer is not None:
                    await producer.publish(Event(
                        topic=Topic.IDENTITY_RESOLUTION_REPLAY_REQUESTED,
                        tenant_id=tenant_id,
                        source_service="identity",
                        payload={
                            "tenant_id": tenant_id,
                            "identifier_type": identifier_type,
                            "identifier_hash": identifier_hash,
                            "trigger_type": trigger_type,
                            "trigger_id": trigger_id,
                            "policy_version": policy_version,
                            "consent_snapshot": consent_snapshot,
                            "verification": verification,
                        },
                    ))
                    self._metrics.record_resolution_replay("requested")
                    return

            # Inline fallback: injected service (tests) or no producer (local).
            replay = self._replay_service
            if replay is None:
                from .resolution_replay import ResolutionReplayService
                from .repository import IdentityResolutionRepository
                from .graph_writer import IdentityGraphWriter
                from .audit import IdentityAuditWriter
                from .conflicts import IdentityConflictManager
                from .metrics import IdentityMetrics as _Metrics
                from .resolver import IdentityResolutionService

                repo = IdentityResolutionRepository()
                metrics = _Metrics()
                resolver = IdentityResolutionService(
                    repo=repo,
                    graph_writer=IdentityGraphWriter(repo, metrics),
                    audit_writer=IdentityAuditWriter(repo),
                    conflict_manager=IdentityConflictManager(repo),
                    metrics=metrics,
                )
                replay = ResolutionReplayService(resolver=resolver, repo=repo)
            await replay.request_replay(
                tenant_id=tenant_id,
                identifier_type=identifier_type,
                identifier_hash=identifier_hash,
                trigger_type=trigger_type,
                trigger_id=trigger_id,
                policy_version=policy_version,
                consent_snapshot=consent_snapshot,
                verification=verification,
            )
            self._metrics.record_resolution_replay("requested")
        except Exception as exc:  # noqa: BLE001 - replay must never break evidence
            logger.warning("resolution replay trigger failed: %s", exc)
            try:
                self._metrics.record_resolution_replay("error")
            except Exception:  # noqa: BLE001 - metrics are best-effort too
                pass


__all__ = ["EvidenceService"]
