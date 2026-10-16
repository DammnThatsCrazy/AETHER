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

import asyncio
import hashlib
import json
import re
import uuid
from contextlib import suppress
from datetime import timedelta
from typing import Any, Optional

from shared.logger.logger import get_logger

from governance.security.repositories import _ScopedRepo
from shared.common.common import parse_iso, utc_now

from .models import IdentitySignalType
from .hashing import hash_value

logger = get_logger("aether.identity.resolution_replay")

_REPLAY_CLAIM_LEASE_SECONDS = 300
_REPLAY_CLAIM_HEARTBEAT_SECONDS = 60


# identifier_type → verified-ownership signal type. Wallet proof additionally
# requires a chain namespace and an exact consented anonymous subject.
_IDENTIFIER_SIGNAL_TYPES: dict[str, IdentitySignalType] = {
    "email": IdentitySignalType.EMAIL_OWNERSHIP_VERIFIED,
    "email_hash": IdentitySignalType.EMAIL_OWNERSHIP_VERIFIED,
    "email_ownership_verified": IdentitySignalType.EMAIL_OWNERSHIP_VERIFIED,
    "wallet": IdentitySignalType.WALLET_SIGNATURE_VERIFIED,
}

# The observed alias type that shares the same hash as each verified signal type,
# so component discovery can find entities carrying only the observed identifier.
_OBSERVED_ALIAS_TYPES: dict[IdentitySignalType, IdentitySignalType] = {
    IdentitySignalType.EMAIL_OWNERSHIP_VERIFIED: IdentitySignalType.EMAIL_HASH,
    IdentitySignalType.WALLET_SIGNATURE_VERIFIED: IdentitySignalType.WALLET_ADDRESS,
}


class _ReplayJobsRepo(_ScopedRepo):
    """Idempotency ledger for replay jobs (JSONB-backed / in-memory)."""

    def __init__(self) -> None:
        super().__init__("identity_resolution_replay_jobs")

    async def claim(
        self, key: str, record: dict, *, lease_seconds: int = _REPLAY_CLAIM_LEASE_SECONDS
    ) -> tuple[bool, Optional[dict]]:
        """Atomically claim, retry, or reclaim a stale replay job.

        A competing request can only observe the existing row; it cannot
        replace an active ``in_progress`` or successful ``completed`` job.
        Failed jobs, legacy completed jobs whose resolver summary records an
        internal error, and expired in-progress leases may be atomically
        reclaimed. A fencing token prevents an expired owner from overwriting
        the result of its successor.
        """
        now = utc_now().isoformat()
        claim = {
            **record,
            "id": key,
            "created_at": now,
            "updated_at": now,
        }
        tenant_id = str(record.get("tenant_id") or "")

        pool = await self._ensure_pool()
        if pool is None:
            existing = self._store.get(key)
            if existing is not None:
                if (
                    self._tenant_guard
                    and str(existing.get("tenant_id") or "") != tenant_id
                ):
                    return False, None
                retryable_internal_error = (
                    existing.get("status") == "completed"
                    and "internal_error"
                    in (existing.get("summary") or {}).get("reason_codes", [])
                )
                stale_in_progress = False
                if existing.get("status") == "in_progress":
                    try:
                        updated_at = parse_iso(
                            str(existing.get("updated_at") or existing.get("created_at"))
                        )
                        stale_in_progress = (
                            utc_now() - updated_at
                        ).total_seconds() >= lease_seconds
                    except Exception:  # noqa: BLE001 - malformed lease fails closed
                        stale_in_progress = False
                if (
                    existing.get("status") != "failed"
                    and not retryable_internal_error
                    and not stale_in_progress
                ):
                    return False, existing
                claim["created_at"] = existing.get("created_at", now)
            self._store[key] = claim
            return True, claim

        await self._ensure_table()
        row = await pool.fetchrow(
            f"""INSERT INTO {self.table_name}
                    (id, data, tenant_id, created_at, updated_at)
                VALUES ($1, $2::jsonb, $3, NOW(), NOW())
                ON CONFLICT (id) DO UPDATE
                    SET data = EXCLUDED.data, updated_at = NOW()
                    WHERE COALESCE({self.table_name}.tenant_id, '') = EXCLUDED.tenant_id
                      AND (
                        {self.table_name}.data->>'status' = 'failed'
                        OR (
                          {self.table_name}.data->>'status' = 'in_progress'
                          AND {self.table_name}.updated_at <=
                              NOW() - ($4::int * INTERVAL '1 second')
                        )
                        OR (
                          {self.table_name}.data->>'status' = 'completed'
                          AND COALESCE(
                            {self.table_name}.data->'summary'->'reason_codes',
                            '[]'::jsonb
                          ) ? 'internal_error'
                        )
                      )
                RETURNING data""",
            key,
            json.dumps(claim, default=str),
            tenant_id,
            lease_seconds,
        )
        if row is not None:
            data = row["data"]
            return True, json.loads(data) if isinstance(data, str) else dict(data)
        return False, await self.find_by_id(key)

    async def renew_claim(self, key: str, tenant_id: str, lease_token: str) -> bool:
        """Extend an owned in-progress lease without changing its fencing token."""
        now = utc_now().isoformat()
        pool = await self._ensure_pool()
        if pool is None:
            current = self._store.get(key)
            if (
                not current
                or current.get("tenant_id") != tenant_id
                or current.get("status") != "in_progress"
                or current.get("lease_token") != lease_token
            ):
                return False
            current["updated_at"] = now
            return True

        await self._ensure_table()
        row = await pool.fetchrow(
            f"""UPDATE {self.table_name}
                SET updated_at = NOW()
                WHERE id = $1 AND tenant_id = $2
                  AND data->>'status' = 'in_progress'
                  AND data->>'lease_token' = $3
                RETURNING id""",
            key,
            tenant_id,
            lease_token,
        )
        return row is not None

    async def finish_claim(
        self, key: str, tenant_id: str, lease_token: str, fields: dict
    ) -> bool:
        """Finish a replay only while the caller still owns its lease."""
        now = utc_now().isoformat()
        pool = await self._ensure_pool()
        if pool is None:
            current = self._store.get(key)
            if (
                not current
                or current.get("tenant_id") != tenant_id
                or current.get("status") != "in_progress"
                or current.get("lease_token") != lease_token
            ):
                return False
            current.update(fields)
            current["updated_at"] = now
            return True

        await self._ensure_table()
        row = await pool.fetchrow(
            f"""UPDATE {self.table_name}
                SET data = data || $4::jsonb,
                    updated_at = NOW()
                WHERE id = $1 AND tenant_id = $2
                  AND data->>'status' = 'in_progress'
                  AND data->>'lease_token' = $3
                RETURNING id""",
            key,
            tenant_id,
            lease_token,
            json.dumps(fields, default=str),
        )
        return row is not None


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

    async def completed_replay_result(
        self, tenant_id: str, trigger_id: str, policy_version: str = "1.0.0"
    ) -> Optional[dict]:
        """Return a tenant-owned completed replay without recomputing inputs.

        This supports evidence written before wallet subjects were durably
        encrypted. Such rows cannot reproduce the original evidence
        fingerprint, but an already completed successful job has a safe cached
        outcome. Legacy jobs completed with an internal resolver error are not
        successful cache entries and require reverification.
        """
        key = f"{tenant_id}:{trigger_id}:{policy_version}"
        existing = await self._jobs.find_by_id(key)
        if (
            not existing
            or existing.get("tenant_id") != tenant_id
            or existing.get("status") != "completed"
            or existing.get("trigger_id", trigger_id) != trigger_id
            or existing.get("policy_version", policy_version) != policy_version
        ):
            return None
        summary = existing.get("summary") or {}
        if "internal_error" in (summary.get("reason_codes") or []):
            return None
        return {
            "status": "noop",
            "idempotent": True,
            "key": key,
            "policy_version": policy_version,
            "decision": summary.get("decision"),
            "canonical_entity_id": summary.get("canonical_entity_id"),
        }

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
        chain_namespace: Optional[str] = None,
        subject_hint_id: Optional[str] = None,
        identity_namespace: Optional[str] = None,
    ) -> dict:
        """Idempotently replay resolution for a verified identifier.

        Returns a status dict; never raises — any failure marks the job failed
        and returns ``{"status": "error", ...}``.
        """
        key = f"{tenant_id}:{trigger_id}:{policy_version}"
        normalized_identifier_type = (identifier_type or "").strip().lower()
        # Bind a completed idempotency key to the immutable evidence input. A
        # reused trigger id with a different value or consent snapshot is a
        # caller error, not permission to silently skip new evidence.
        normalized_chain_namespace = str(chain_namespace or "").strip().lower()
        normalized_identity_namespace = str(identity_namespace or "").strip()
        subject_hint_hash = hash_value(
            str(subject_hint_id or "").strip(),
            scope=f"wallet-proof-subject:{tenant_id}",
        )
        fingerprint_payload = {
            "identifier_type": normalized_identifier_type,
            "identifier_hash": identifier_hash,
            "consent_snapshot": consent_snapshot,
        }
        if normalized_identifier_type == "wallet":
            fingerprint_payload.update({
                "chain_namespace": normalized_chain_namespace,
                "subject_hint_hash": subject_hint_hash,
                "identity_namespace": normalized_identity_namespace,
            })
        evidence_fingerprint = hashlib.sha256(json.dumps(
            fingerprint_payload,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")).hexdigest()

        # ── Idempotency: completed jobs are never re-run ──
        try:
            existing = await self._jobs.find_by_id(key)
        except Exception:  # noqa: BLE001 - missing ledger row is not an error
            existing = None
        if (
            existing
            and existing.get("evidence_fingerprint") is not None
            and existing.get("evidence_fingerprint") != evidence_fingerprint
        ):
            return {
                "status": "error",
                "error": "trigger_id_reused_with_different_evidence",
                "key": key,
                "idempotent": False,
                "policy_version": policy_version,
            }
        existing_internal_error = (
            existing
            and "internal_error"
            in (existing.get("summary") or {}).get("reason_codes", [])
        )
        if (
            existing
            and existing.get("status") == "completed"
            and not existing_internal_error
        ):
            if existing.get("evidence_fingerprint") != evidence_fingerprint:
                return {
                    "status": "error",
                    "error": "trigger_id_reused_with_different_evidence",
                    "key": key,
                    "idempotent": False,
                    "policy_version": policy_version,
                }
            summary = existing.get("summary") or {}
            return {
                "status": "noop", "idempotent": True, "key": key,
                "policy_version": policy_version,
                "decision": summary.get("decision"),
                "canonical_entity_id": summary.get("canonical_entity_id"),
            }
        owns_claim = False
        lease_token = str(uuid.uuid4())
        heartbeat: Optional[asyncio.Task] = None

        try:
            sig_type = _IDENTIFIER_SIGNAL_TYPES.get(normalized_identifier_type)
            if sig_type is None:
                return {
                    "status": "error",
                    "error": f"unsupported identifier_type: {identifier_type!r}",
                    "key": key,
                    "idempotent": False,
                }

            if sig_type == IdentitySignalType.WALLET_SIGNATURE_VERIFIED and (
                not subject_hint_id
                or not re.fullmatch(
                    r"(?:eip155:[1-9][0-9]*|solana:[a-z0-9][a-z0-9._-]{0,63})",
                    normalized_chain_namespace,
                )
            ):
                return {
                    "status": "error",
                    "error": "wallet replay requires subject and chain scope",
                    "key": key,
                    "idempotent": False,
                }

            # Claim before any resolver or graph work. A duplicate request
            # that loses the conditional write returns without side effects.
            owns_claim, current = await self._jobs.claim(key, {
                "tenant_id": tenant_id,
                "trigger_type": trigger_type,
                "trigger_id": trigger_id,
                "policy_version": policy_version,
                "evidence_fingerprint": evidence_fingerprint,
                "status": "in_progress",
                "summary": None,
                "error": None,
                "lease_token": lease_token,
            })
            if not owns_claim:
                if (
                    current
                    and current.get("evidence_fingerprint") is not None
                    and current.get("evidence_fingerprint") != evidence_fingerprint
                ):
                    return {
                        "status": "error",
                        "error": "trigger_id_reused_with_different_evidence",
                        "key": key,
                        "idempotent": False,
                        "policy_version": policy_version,
                    }
                if current and current.get("status") == "completed":
                    if current.get("evidence_fingerprint") != evidence_fingerprint:
                        return {
                            "status": "error",
                            "error": "trigger_id_reused_with_different_evidence",
                            "key": key,
                            "idempotent": False,
                            "policy_version": policy_version,
                        }
                    summary = current.get("summary") or {}
                    return {
                        "status": "noop",
                        "idempotent": True,
                        "key": key,
                        "policy_version": policy_version,
                        "decision": summary.get("decision"),
                        "canonical_entity_id": summary.get("canonical_entity_id"),
                    }
                if current and current.get("status") == "in_progress":
                    return {
                        "status": "in_progress",
                        "idempotent": True,
                        "key": key,
                        "policy_version": policy_version,
                    }
                return {
                    "status": "error",
                    "error": "replay_claim_unavailable",
                    "key": key,
                    "idempotent": False,
                    "policy_version": policy_version,
                }

            heartbeat = asyncio.create_task(
                self._renew_claim_periodically(key, tenant_id, lease_token)
            )

            supports_policy = getattr(self._resolver, "supports_policy_version", None)
            if callable(supports_policy) and not supports_policy(policy_version):
                await self._mark(
                    key, tenant_id, trigger_type, trigger_id, policy_version, "failed",
                    error=f"unsupported policy_version: {policy_version}",
                    evidence_fingerprint=evidence_fingerprint,
                    lease_token=lease_token,
                )
                return {
                    "status": "error",
                    "error": f"unsupported policy_version: {policy_version}",
                    "key": key,
                    "idempotent": False,
                    "policy_version": policy_version,
                }

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
            # Wallet control proof is tied to the exact consented anonymous
            # subject that initiated the challenge. Do not turn a successful
            # proof into a wallet-only global replay.
            pre_hashed_signals = [
                {
                    "type": sig_type.value,
                    "hash": identifier_hash,
                    "display": "[REDACTED:verified_identifier]",
                }
            ]
            if sig_type == IdentitySignalType.WALLET_SIGNATURE_VERIFIED:
                scoped_subject_id = (
                    f"{normalized_identity_namespace}:{str(subject_hint_id).strip()}"
                    if normalized_identity_namespace
                    else str(subject_hint_id).strip()
                )
                pre_hashed_signals.append({
                    "type": IdentitySignalType.ANONYMOUS_ID.value,
                    "hash": scoped_subject_id,
                    "display": "[REDACTED:anonymous_id]",
                })
            synthetic = {
                "event_id": f"verify:{trigger_id}",
                "tenant_id": tenant_id,
                "context": {
                    "consent": consent_snapshot,
                    "identity_namespace": normalized_identity_namespace,
                },
                "_pre_hashed_signals": pre_hashed_signals,
                "source": "resolution_replay",
            }
            decision = await self._resolver.resolve_event(
                synthetic, tenant_id, policy_version=policy_version
            )
            if "unsupported_policy_version" in (decision.reason_codes or []):
                raise ValueError(f"unsupported policy_version: {policy_version}")
            if "internal_error" in (decision.reason_codes or []):
                # Older replay jobs could incorrectly persist a resolver
                # NOOP/internal_error as completed. Raise into the normal
                # failure path so new jobs stay retryable and those legacy
                # rows can be reclaimed by the atomic claim above.
                raise RuntimeError("identity resolution replay failed")

            affected = sorted(set(ids_verified) | set(ids_observed))
            summary = {
                "decision": decision.decision.value,
                "canonical_entity_id": decision.canonical_entity_id,
                "reason_codes": list(decision.reason_codes),
                "affected": affected,
                "policy_version": policy_version,
                "restatement_status": decision.restatement_status,
                "restatement_job_id": decision.restatement_job_id,
            }
            await self._mark(
                key, tenant_id, trigger_type, trigger_id, policy_version,
                "completed", summary=summary,
                evidence_fingerprint=evidence_fingerprint,
                lease_token=lease_token,
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
                "restatement_status": decision.restatement_status,
                "restatement_job_id": decision.restatement_job_id,
                "key": key,
                "idempotent": False,
                "policy_version": policy_version,
            }
        except Exception as exc:  # noqa: BLE001 - replay must never raise
            logger.warning("resolution replay failed for key=%s: %s", key, exc)
            if owns_claim:
                try:
                    await self._mark(
                        key, tenant_id, trigger_type, trigger_id, policy_version,
                        "failed", error=str(exc),
                        evidence_fingerprint=evidence_fingerprint,
                        lease_token=lease_token,
                    )
                except Exception:  # noqa: BLE001
                    pass
            return {"status": "error", "error": str(exc), "key": key, "idempotent": False}
        finally:
            if heartbeat is not None:
                heartbeat.cancel()
                with suppress(asyncio.CancelledError):
                    await heartbeat

    async def _renew_claim_periodically(
        self, key: str, tenant_id: str, lease_token: str
    ) -> None:
        while True:
            await asyncio.sleep(_REPLAY_CLAIM_HEARTBEAT_SECONDS)
            try:
                renewed = await self._jobs.renew_claim(key, tenant_id, lease_token)
            except Exception as exc:  # noqa: BLE001 - the lease remains fenced
                logger.warning(
                    "resolution replay claim heartbeat failed for key=%s: %s",
                    key,
                    type(exc).__name__,
                )
                continue
            if not renewed:
                logger.warning("resolution replay claim lease was lost for key=%s", key)
                return

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
        evidence_fingerprint: Optional[str] = None,
        lease_token: str,
    ) -> bool:
        """Finish only if this worker still owns the claim fencing token."""
        updated = await self._jobs.finish_claim(key, tenant_id, lease_token, {
            "status": status,
            "summary": summary,
            "error": error,
        })
        if not updated:
            logger.warning("resolution replay result ignored after lease loss for key=%s", key)
        return updated
