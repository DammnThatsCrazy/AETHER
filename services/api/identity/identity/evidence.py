"""Verification evidence service (identity assurance layer, prompt §5x/§56).

Wraps :class:`VerificationEvidenceRepository` to issue and revoke durable,
tenant-scoped proof that an identifier's ownership was verified. Issuing
evidence best-effort triggers a resolution replay. Revocation removes the
verified alias when no unexpired active proof remains; it never replays the
revoked proof as an affirmative signal.

This module is additive and mirrors ``decision_evidence.py``'s style. It never
persists a raw OTP/token and never logs PII or secrets.
"""

from __future__ import annotations

import uuid
from typing import Any, Optional

from shared.common.common import parse_iso, utc_now
from shared.logger.logger import get_logger

from .hashing import decrypt_wallet_subject_binding, encrypt_wallet_subject_binding
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
        subject_hint_id: Optional[str] = None,
        identity_namespace: Optional[str] = None,
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
            subject_hint_ciphertext=(
                encrypt_wallet_subject_binding(subject_hint_id, tenant_id)
                if identifier_type == "wallet" and subject_hint_id
                else None
            ),
            identity_namespace=identity_namespace,
            metadata=dict(metadata or {}),
        )
        await self._repo.create(evidence)
        self._metrics.record_evidence_active(evidence_type)
        replay_result = await self._trigger_replay(
            tenant_id=tenant_id,
            identifier_type=identifier_type,
            identifier_hash=identifier_hash,
            trigger_type="verification_evidence_issued",
            trigger_id=evidence.id,
            policy_version=policy_version,
            consent_snapshot=consent_snapshot,
            chain_namespace=(metadata or {}).get("chain_namespace"),
            subject_hint_id=subject_hint_id,
            identity_namespace=identity_namespace,
        )
        await self._bind_entity_if_resolved(evidence.id, tenant_id, replay_result)
        return evidence

    async def revoke_evidence(
        self, tenant_id: str, evidence_id: str, reason: str = ""
    ) -> Optional[dict]:
        """Revoke evidence and remove its verified alias when no active proof remains.

        Returns the updated row, or ``None`` if it did not exist for the tenant.
        Raises when alias cleanup fails so callers do not report revocation as
        complete while the proof-derived alias is still active.
        """
        row = await self._repo.revoke(tenant_id, evidence_id, reason=reason)
        if row is None:
            return None
        self._metrics.record_evidence_revoked(row.get("evidence_type", ""))
        await self._remove_verified_alias_if_unreferenced(tenant_id, row)
        return row

    async def _remove_verified_alias_if_unreferenced(
        self, tenant_id: str, revoked_evidence: dict
    ) -> None:
        """Revoke proof-derived aliases only after the last live proof is gone.

        This is a removal path: revoked evidence is never sent through the
        affirmative verified-signal replay service. Existing SAME_AS topology
        is not reversed here; graph splits remain an explicit repair action.
        """
        identifier_type = str(revoked_evidence.get("identifier_type") or "").lower()
        alias_type = {
            "email": IdentitySignalType.EMAIL_OWNERSHIP_VERIFIED,
            "email_hash": IdentitySignalType.EMAIL_OWNERSHIP_VERIFIED,
            "wallet": IdentitySignalType.WALLET_SIGNATURE_VERIFIED,
        }.get(identifier_type)
        identifier_hash = str(revoked_evidence.get("identifier_hash") or "")
        if alias_type is None or not identifier_hash:
            return

        try:
            equivalent_types = (
                ("email", "email_hash")
                if identifier_type in {"email", "email_hash"}
                else (identifier_type,)
            )
            has_live_proof = False
            for equivalent_type in equivalent_types:
                offset = 0
                while True:
                    remaining = await self._repo.get_active_for_identifier(
                        tenant_id,
                        equivalent_type,
                        identifier_hash,
                        limit=100,
                        offset=offset,
                    )
                    for evidence in remaining:
                        expires_at = evidence.get("expires_at")
                        if not expires_at:
                            has_live_proof = True
                            break
                        try:
                            if utc_now() < parse_iso(str(expires_at)):
                                has_live_proof = True
                                break
                        except Exception:  # noqa: BLE001 - malformed expiry fails closed
                            continue
                    if has_live_proof or len(remaining) < 100:
                        break
                    offset += 100
                if has_live_proof:
                    break
            if has_live_proof:
                return

            from .repository import IdentityResolutionRepository

            resolution_repo = IdentityResolutionRepository()
            while aliases := await resolution_repo.find_aliases_by_signal(
                tenant_id, alias_type, identifier_hash, limit=50
            ):
                for alias in aliases:
                    await resolution_repo.revoke_alias(alias["id"])
        except Exception as exc:  # noqa: BLE001 - evidence revocation is durable
            logger.warning(
                "verification evidence alias removal failed",
                extra={
                    "tenant_id": tenant_id,
                    "evidence_id": revoked_evidence.get("id"),
                    "error_type": type(exc).__name__,
                },
            )
            raise RuntimeError("verification evidence alias removal failed") from exc

    async def retry_evidence_replay(
        self, tenant_id: str, evidence_id: str
    ) -> dict:
        """Retry replay from the durable, encrypted wallet subject binding.

        This supports operator reconciliation after a resolver outage without
        retaining the caller's raw anonymous identifier in process state.
        """
        row = await self._repo.get_for_tenant(tenant_id, evidence_id)
        if row is None:
            return {"status": "not_found"}
        if row.get("status") == VerificationEvidenceStatus.EXPIRED.value:
            return {"status": "expired_evidence"}
        if row.get("status") != VerificationEvidenceStatus.ACTIVE.value:
            return {"status": "inactive_evidence"}
        expires_at = row.get("expires_at")
        if expires_at:
            try:
                expired = utc_now() >= parse_iso(str(expires_at))
            except Exception:  # noqa: BLE001 - malformed expiry must fail closed
                expired = True
            if expired:
                try:
                    await self._repo.expire_if_active(tenant_id, evidence_id)
                except Exception as exc:  # noqa: BLE001 - replay remains blocked
                    logger.warning(
                        "expired verification evidence status update failed",
                        extra={
                            "tenant_id": tenant_id,
                            "evidence_id": evidence_id,
                            "error_type": type(exc).__name__,
                        },
                    )
                return {"status": "expired_evidence"}
        subject_hint_id = self._recover_subject_hint(row, tenant_id)
        if row.get("identifier_type") == "wallet" and not subject_hint_id:
            try:
                replay = self._get_replay_service()
                completed_result = getattr(replay, "completed_replay_result", None)
                cached = (
                    await completed_result(
                        tenant_id,
                        evidence_id,
                        row.get("policy_version", "1.0.0"),
                    )
                    if callable(completed_result)
                    else None
                )
            except Exception as exc:  # noqa: BLE001 - never expose replay internals
                logger.warning(
                    "legacy wallet replay cache lookup failed",
                    extra={
                        "tenant_id": tenant_id,
                        "evidence_id": evidence_id,
                        "error_type": type(exc).__name__,
                    },
                )
                return {"status": "error"}
            if cached is not None:
                try:
                    self._metrics.record_resolution_replay("requested")
                except Exception:  # noqa: BLE001 - metrics are best-effort
                    pass
                await self._bind_entity_if_resolved(evidence_id, tenant_id, cached)
                return cached
            return {"status": "reverification_required"}
        result = await self._trigger_replay(
            tenant_id=tenant_id,
            identifier_type=row.get("identifier_type", ""),
            identifier_hash=row.get("identifier_hash", ""),
            trigger_type="verification_evidence_issued",
            trigger_id=evidence_id,
            policy_version=row.get("policy_version", "1.0.0"),
            consent_snapshot=row.get("consent_snapshot"),
            chain_namespace=(row.get("metadata") or {}).get("chain_namespace"),
            subject_hint_id=subject_hint_id,
            identity_namespace=row.get("identity_namespace"),
        )
        await self._bind_entity_if_resolved(evidence_id, tenant_id, result)
        return result or {"status": "error", "error": "resolution replay failed"}

    @staticmethod
    def _recover_subject_hint(row: dict, tenant_id: str) -> Optional[str]:
        ciphertext = str(row.get("subject_hint_ciphertext") or "")
        if not ciphertext:
            return None
        return decrypt_wallet_subject_binding(ciphertext, tenant_id) or None

    async def _bind_entity_if_resolved(
        self, evidence_id: str, tenant_id: str, result: Optional[dict]
    ) -> None:
        if not result or result.get("status") not in {"complete", "noop"}:
            return
        if str(result.get("decision") or "").lower() not in {"create", "link", "merge"}:
            return
        canonical_entity_id = result.get("canonical_entity_id")
        if not canonical_entity_id:
            return
        try:
            await self._repo.bind_entity(tenant_id, evidence_id, canonical_entity_id)
        except Exception as exc:  # noqa: BLE001 - evidence issuance remains durable
            logger.warning(
                "verification evidence entity binding failed: %s", exc
            )

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
        chain_namespace: Optional[str] = None,
        subject_hint_id: Optional[str] = None,
        identity_namespace: Optional[str] = None,
    ) -> Optional[dict]:
        """Best-effort resolution replay fan-out.

        Uses an injected replay service when present (tests); otherwise lazily
        constructs the real resolver + replay service. Lazy imports avoid an
        import cycle and tolerate Agent C's ``resolution_replay`` not yet being
        present. Any failure is swallowed — replay must never break evidence.
        """
        try:
            replay = self._get_replay_service()
            result = await replay.request_replay(
                tenant_id=tenant_id,
                identifier_type=identifier_type,
                identifier_hash=identifier_hash,
                trigger_type=trigger_type,
                trigger_id=trigger_id,
                policy_version=policy_version,
                consent_snapshot=consent_snapshot,
                chain_namespace=chain_namespace,
                subject_hint_id=subject_hint_id,
                identity_namespace=identity_namespace,
            )
            self._metrics.record_resolution_replay("requested")
            return result if isinstance(result, dict) else None
        except Exception as exc:  # noqa: BLE001 - replay must never break evidence
            logger.warning("resolution replay trigger failed: %s", exc)
            try:
                self._metrics.record_resolution_replay("error")
            except Exception:  # noqa: BLE001 - metrics are best-effort too
                pass
            return None

    def _get_replay_service(self) -> Any:
        """Get the injected replay service or construct the production service."""
        if self._replay_service is None:
            from .resolution_replay import ResolutionReplayService
            from .repository import IdentityResolutionRepository
            from .graph_writer import IdentityGraphWriter
            from .audit import IdentityAuditWriter
            from .conflicts import IdentityConflictManager
            from .resolver import IdentityResolutionService

            repo = IdentityResolutionRepository()
            metrics = IdentityMetrics()
            resolver = IdentityResolutionService(
                repo=repo,
                graph_writer=IdentityGraphWriter(repo, metrics),
                audit_writer=IdentityAuditWriter(repo),
                conflict_manager=IdentityConflictManager(repo),
                metrics=metrics,
            )
            self._replay_service = ResolutionReplayService(resolver=resolver, repo=repo)
        return self._replay_service


__all__ = ["EvidenceService"]
