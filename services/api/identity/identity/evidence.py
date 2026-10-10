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
    ) -> None:
        self._repo = repo or VerificationEvidenceRepository()
        self._metrics = metrics or IdentityMetrics()
        # Optional injected replay service — tests pass a fake and assert it was
        # called; None means lazily construct the real one at trigger time.
        self._replay_service = replay_service

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
        await self._trigger_replay(
            tenant_id=tenant_id,
            identifier_type=identifier_type,
            identifier_hash=identifier_hash,
            trigger_type="verification_evidence_issued",
            trigger_id=evidence.id,
            policy_version=policy_version,
            consent_snapshot=consent_snapshot,
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
        await self._trigger_replay(
            tenant_id=tenant_id,
            identifier_type=row.get("identifier_type", ""),
            identifier_hash=row.get("identifier_hash", ""),
            trigger_type="verification_evidence_revoked",
            trigger_id=evidence_id,
            policy_version=row.get("policy_version", "1.0.0"),
            consent_snapshot=row.get("consent_snapshot"),
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
    ) -> None:
        """Best-effort resolution replay fan-out.

        Uses an injected replay service when present (tests); otherwise lazily
        constructs the real resolver + replay service. Lazy imports avoid an
        import cycle and tolerate Agent C's ``resolution_replay`` not yet being
        present. Any failure is swallowed — replay must never break evidence.
        """
        try:
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
            )
            self._metrics.record_resolution_replay("requested")
        except Exception as exc:  # noqa: BLE001 - replay must never break evidence
            logger.warning("resolution replay trigger failed: %s", exc)
            try:
                self._metrics.record_resolution_replay("error")
            except Exception:  # noqa: BLE001 - metrics are best-effort too
                pass


__all__ = ["EvidenceService"]
