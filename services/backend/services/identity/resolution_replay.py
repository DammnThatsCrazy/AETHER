"""Resolution replay — re-run the EXISTING resolver when verified evidence arrives.

This is a thin, idempotent wrapper over :class:`IdentityResolutionService`, NOT a
new matcher. When verified identifier ownership becomes available (e.g. an email
OTP is validated), the same identifier hash may already be carried as an OBSERVED
alias by one or more previously-fragmented canonical entities. Replaying the
resolver with a single synthetic verified-ownership signal lets that deterministic
evidence discover and (policy permitting) merge those fragments — reusing every
existing suppression / consent / conflict rule rather than re-implementing it.

Idempotency: a completed job for ``{tenant_id}:{trigger_id}:{policy_version}`` is
never re-run, so a duplicate verification callback cannot double-merge.
"""

from __future__ import annotations

from typing import Any, Optional

from shared.logger.logger import get_logger

from services.security.repositories import _ScopedRepo

from .models import IdentitySignalType

logger = get_logger("aether.identity.resolution_replay")


# identifier_type → verified-ownership signal type. Only email is wired for now;
# wallet / phone can be added here later without touching the replay flow.
_IDENTIFIER_SIGNAL_TYPES: dict[str, IdentitySignalType] = {
    "email": IdentitySignalType.EMAIL_OWNERSHIP_VERIFIED,
    "email_hash": IdentitySignalType.EMAIL_OWNERSHIP_VERIFIED,
    "email_ownership_verified": IdentitySignalType.EMAIL_OWNERSHIP_VERIFIED,
}

# The observed alias type that shares the same hash as each verified signal type,
# so component discovery can find entities carrying only the observed identifier.
_OBSERVED_ALIAS_TYPES: dict[IdentitySignalType, IdentitySignalType] = {
    IdentitySignalType.EMAIL_OWNERSHIP_VERIFIED: IdentitySignalType.EMAIL_HASH,
}


class _ReplayJobsRepo(_ScopedRepo):
    """Idempotency ledger for replay jobs (JSONB-backed / in-memory)."""

    def __init__(self) -> None:
        super().__init__("identity_resolution_replay_jobs")


class ResolutionReplayService:
    """Re-run the existing resolver when verified ownership evidence arrives."""

    def __init__(
        self,
        resolver: Any,
        repo: Any,
        metrics: Any = None,
        jobs_repo: Any = None,
    ) -> None:
        self._resolver = resolver
        self._repo = repo
        self._metrics = metrics
        self._jobs = jobs_repo or _ReplayJobsRepo()

    async def request_replay(
        self,
        *,
        tenant_id: str,
        identifier_type: str,
        identifier_hash: str,
        trigger_type: str,
        trigger_id: str,
        policy_version: str = "1.0.0",
        consent_snapshot: Optional[dict] = None,
    ) -> dict:
        """Idempotently replay resolution for a verified identifier.

        Returns a status dict; never raises — any failure marks the job failed
        and returns ``{"status": "error", ...}``.
        """
        key = f"{tenant_id}:{trigger_id}:{policy_version}"

        # ── Idempotency: a completed job is never re-run ──────────────────
        try:
            existing = await self._jobs.find_by_id(key)
        except Exception:  # noqa: BLE001 - missing ledger row is not an error
            existing = None
        if existing and existing.get("status") == "completed":
            return {"status": "noop", "idempotent": True, "key": key}

        try:
            sig_type = _IDENTIFIER_SIGNAL_TYPES.get((identifier_type or "").strip().lower())
            if sig_type is None:
                await self._mark(
                    key, tenant_id, trigger_type, trigger_id, policy_version,
                    "failed", error=f"unsupported identifier_type: {identifier_type!r}",
                )
                return {
                    "status": "error",
                    "error": f"unsupported identifier_type: {identifier_type!r}",
                    "key": key,
                    "idempotent": False,
                }

            # Record an in-progress job before doing any work.
            await self._mark(
                key, tenant_id, trigger_type, trigger_id, policy_version, "in_progress",
            )

            # ── Component discovery (bounded, blueprint §29) ──────────────
            # Entities that already own this identifier hash under the verified
            # alias, plus those carrying only the observed alias of the same hash.
            ids_verified = await self._repo.find_subjects_by_alias(
                tenant_id, sig_type, identifier_hash
            )
            observed_type = _OBSERVED_ALIAS_TYPES.get(sig_type)
            ids_observed: list[str] = []
            if observed_type is not None:
                ids_observed = await self._repo.find_subjects_by_alias(
                    tenant_id, observed_type, identifier_hash
                )

            # ── Build ONE synthetic verified event and run the resolver ───
            synthetic = {
                "event_id": f"verify:{trigger_id}",
                "tenant_id": tenant_id,
                "context": {"consent": consent_snapshot},
                "_pre_hashed_signals": [
                    {
                        "type": sig_type.value,
                        "hash": identifier_hash,
                        "display": "[REDACTED:email_hash]",
                    }
                ],
                "source": "resolution_replay",
            }
            decision = await self._resolver.resolve_event(synthetic, tenant_id)

            affected = sorted(set(ids_verified) | set(ids_observed))
            summary = {
                "decision": decision.decision.value,
                "canonical_entity_id": decision.canonical_entity_id,
                "reason_codes": list(decision.reason_codes),
                "affected": affected,
            }
            await self._mark(
                key, tenant_id, trigger_type, trigger_id, policy_version,
                "completed", summary=summary,
            )
            if self._metrics is not None:
                try:
                    self._metrics.record_resolve(success=True, tenant_id=tenant_id)
                except Exception:  # noqa: BLE001 - metrics must never break replay
                    pass

            return {
                "status": "complete",
                "decision": decision.decision.value,
                "canonical_entity_id": decision.canonical_entity_id,
                "reason_codes": list(decision.reason_codes),
                "affected": affected,
                "key": key,
                "idempotent": False,
            }
        except Exception as exc:  # noqa: BLE001 - replay must never raise
            logger.warning("resolution replay failed for key=%s: %s", key, exc)
            try:
                await self._mark(
                    key, tenant_id, trigger_type, trigger_id, policy_version,
                    "failed", error=str(exc),
                )
            except Exception:  # noqa: BLE001
                pass
            return {"status": "error", "error": str(exc), "key": key, "idempotent": False}

    async def _mark(
        self,
        key: str,
        tenant_id: str,
        trigger_type: str,
        trigger_id: str,
        policy_version: str,
        status: str,
        *,
        summary: Optional[dict] = None,
        error: Optional[str] = None,
    ) -> None:
        """Upsert the replay job row (insert is an upsert on id)."""
        await self._jobs.insert(key, {
            "tenant_id": tenant_id,
            "trigger_type": trigger_type,
            "trigger_id": trigger_id,
            "policy_version": policy_version,
            "status": status,
            "summary": summary,
            "error": error,
        })
