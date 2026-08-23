"""
Aether Backend — Durable reward-delivery outbox.

Routes reward rail delivery (esp. ``tenant_webhook``) through a DURABLE, leased
outbox instead of the in-memory ``queue.py``. It reuses the ``services/delivery``
durability primitives — leased jobs, exponential backoff + jitter, dead-letter,
and a validated :class:`ProviderReceipt` — but on a **rewards-owned job table**
(``reward_delivery_jobs``) so it never contends with the platform delivery
worker that owns ``delivery_jobs``.

Guarantees
----------
* **Durable-before-ack.** ``enqueue()`` writes a durable job row and leaves the
  reward action in ``pending``. The action is only marked ``delivered`` *after*
  a :class:`ProviderReceipt` with a real ``external_id`` is persisted — never
  before. A failed job dead-letters and marks the action ``failed``.
* **PR-1 SSRF + signing preserved.** Dispatch goes through the reward
  :class:`TenantWebhookAdapter` (its DNS-resolving SSRF blocklist + HTTPS
  enforcement + HMAC signing), and the destination is re-validated before
  enqueue. No plaintext response body is buffered beyond the adapter's cap.
* **Exact, tenant-scoped, retryable.** Retries use the delivery worker's
  exponential backoff with jitter; permanent failures dead-letter after
  ``max_attempts``.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from urllib.parse import urlparse

from repositories.repos import BaseRepository
from services.rewards.rails import TenantWebhookAdapter
from shared.common.common import utc_now
from shared.logger.logger import get_logger, metrics

logger = get_logger("aether.service.rewards.delivery_outbox")

_DEFAULT_MAX_ATTEMPTS = 6
_WEBHOOK_PROVIDER = "tenant_webhook"


def _now_iso() -> str:
    return utc_now().isoformat()


# ═══════════════════════════════════════════════════════════════════════════
# DURABLE, LEASED JOB TABLE (rewards-owned)
# ═══════════════════════════════════════════════════════════════════════════

class RewardDeliveryJobRepository(BaseRepository):
    """Durable, leased outbox jobs for reward delivery (``reward_delivery_jobs``).

    Mirrors ``DeliveryJobRepository.lease_next_batch`` (SELECT ... FOR UPDATE
    SKIP LOCKED in PostgreSQL; cooperative in-memory lease) but on a separate
    table so the platform delivery worker never leases — and dead-letters —
    reward jobs it has no adapter for.
    """

    def __init__(self) -> None:
        super().__init__("reward_delivery_jobs")

    async def lease_next_batch(self, worker_id: str, batch_size: int, lease_seconds: int) -> list[dict[str, Any]]:
        pool = await self._ensure_pool()
        if pool is None:
            now_str = _now_iso()
            results: list[dict[str, Any]] = []
            for job in list(self._store.values()):
                if len(results) >= batch_size:
                    break
                state = job.get("state", "")
                lease_expires_at = job.get("lease_expires_at", "")
                expired_lease = state == "leased" and lease_expires_at and lease_expires_at <= now_str
                if not expired_lease and state not in ("queued", "failed"):
                    continue
                next_at = job.get("next_attempt_at", "")
                if next_at and next_at > now_str:
                    continue
                expire = (utc_now() + timedelta(seconds=lease_seconds)).isoformat()
                job["state"] = "leased"
                job["leased_by"] = worker_id
                job["lease_expires_at"] = expire
                job["updated_at"] = now_str
                results.append(job)
            return results

        await self._ensure_table()
        try:
            rows = await pool.fetch(
                """
                UPDATE reward_delivery_jobs
                SET data = jsonb_set(
                        jsonb_set(
                            jsonb_set(data, '{state}', '"leased"'),
                            '{leased_by}', $1::jsonb
                        ),
                        '{lease_expires_at}',
                        to_jsonb((NOW() + ($3 * INTERVAL '1 second'))::text)
                    ),
                    updated_at = NOW()
                WHERE id IN (
                    SELECT id FROM reward_delivery_jobs
                    WHERE (
                            data->>'state' IN ('queued', 'failed')
                            OR (data->>'state' = 'leased'
                                AND (data->>'lease_expires_at')::timestamptz <= NOW())
                          )
                      AND (data->>'next_attempt_at' IS NULL
                           OR (data->>'next_attempt_at')::timestamptz <= NOW())
                    ORDER BY (data->>'next_attempt_at')::timestamptz ASC
                    LIMIT $2
                    FOR UPDATE SKIP LOCKED
                )
                RETURNING data
                """,
                json.dumps(worker_id), batch_size, lease_seconds,
            )
            return [json.loads(r["data"]) for r in rows]
        except Exception as exc:
            logger.warning("reward lease_next_batch failed: %s", exc)
            return []

    async def status_counts(self, tenant_id: str) -> dict[str, int]:
        jobs = await self.find_many(filters={"tenant_id": tenant_id}, limit=10000)
        counts: dict[str, int] = {}
        for j in jobs:
            counts[j.get("state", "unknown")] = counts.get(j.get("state", "unknown"), 0) + 1
        return counts

    async def release_job(
        self,
        job_id: str,
        worker_id: str,
        update: dict[str, Any],
    ) -> Optional[dict[str, Any]]:
        """Apply a post-processing state update only while this worker still
        owns the lease.

        The release paths (delivered / failed / dead_letter) must not let a
        STALE worker overwrite a batch that another worker re-claimed after
        the lease expired — that split-brain double-delivers in the
        rewards/delivery fan-out. This is a no-op (returns None, mutates
        nothing) when the job is currently leased by a DIFFERENT worker; the
        current owner's release succeeds exactly as before. An unleased job
        (direct-dispatch path) is still releasable.
        """
        pool = await self._ensure_pool()
        now_str = _now_iso()
        if pool is None:
            job = self._store.get(job_id)
            if job is None:
                return None
            current_owner = job.get("leased_by")
            if current_owner is not None and current_owner != worker_id:
                logger.warning(
                    "release_job skipped job=%s: lease held by %r "
                    "(worker %r is stale)", job_id, current_owner, worker_id,
                )
                return None
            job.update(update)
            job["updated_at"] = now_str
            return job

        await self._ensure_table()
        existing = await self.find_by_id(job_id)
        if existing is None:
            return None
        if existing.get("leased_by") not in (None, worker_id):
            logger.warning(
                "release_job skipped job=%s: lease held by %r "
                "(worker %r is stale)", job_id, existing.get("leased_by"), worker_id,
            )
            return None
        merged = {**existing, **update}
        merged["updated_at"] = now_str
        row = await pool.fetchrow(
            f"""
            UPDATE {self.table_name}
            SET data = $2::jsonb, updated_at = NOW()
            WHERE id = $1
              AND (data->>'leased_by' IS NULL OR data->>'leased_by' = $3)
            RETURNING data
            """,
            job_id, json.dumps(merged, default=str), worker_id,
        )
        if row is None:
            logger.warning(
                "release_job skipped job=%s: lease re-claimed while releasing "
                "(worker %r)", job_id, worker_id,
            )
            return None
        return json.loads(row["data"])


# ═══════════════════════════════════════════════════════════════════════════
# WEBHOOK SENDER (reuses PR-1 hardened TenantWebhookAdapter)
# ═══════════════════════════════════════════════════════════════════════════

class SenderResult:
    """Outcome of one dispatch attempt."""

    __slots__ = ("outcome", "external_id", "response_code", "error", "raw")

    def __init__(self, outcome: str, *, external_id: Optional[str] = None,
                 response_code: Optional[int] = None, error: Optional[str] = None,
                 raw: Optional[dict] = None) -> None:
        # outcome ∈ {"success", "retryable", "fatal"}
        self.outcome = outcome
        self.external_id = external_id
        self.response_code = response_code
        self.error = error
        self.raw = raw or {}


class RewardWebhookSender:
    """Dispatches a reward webhook via the PR-1 hardened TenantWebhookAdapter."""

    def __init__(self) -> None:
        self._adapter = TenantWebhookAdapter()

    async def send(self, job: dict) -> SenderResult:
        provider_config = job.get("provider_config") or {}
        webhook_url = provider_config.get("webhook_url")
        # Resolve the signing secret from the credential authority at the narrow
        # send site — the job row carries only a secret_ref (plus an optional
        # local/test inline secret), never durable plaintext.
        from services.rewards.webhook_secret import (
            TransientSecretResolutionError,
            resolve_signing_secret,
        )

        tenant_id = job.get("tenant_id", "")
        rail_config_for_resolve = {
            "config": {
                "secret_ref": provider_config.get("secret_ref"),
                "signing_secret": provider_config.get("signing_secret", ""),
            }
        }
        try:
            signing_secret = await resolve_signing_secret(tenant_id, rail_config_for_resolve)
        except TransientSecretResolutionError as exc:
            # Authority / DB / KMS temporarily unreachable — RETRYABLE, so the
            # outbox schedules a backoff retry instead of dead-lettering the job
            # (and failing the reward action) on its first attempt.
            return SenderResult(
                "retryable",
                error=f"reward webhook secret resolution unavailable: {exc}",
            )
        if not signing_secret:
            return SenderResult(
                "fatal",
                error="reward webhook signing secret could not be resolved "
                      "(no active credential for secret_ref)",
            )
        rail_config = {
            "webhook_url": webhook_url,
            "config": {
                "signing_secret": signing_secret,
                "timeout_ms": provider_config.get("timeout_ms", 10000),
            },
        }
        action = {"payload": job.get("payload") or {}}
        result = await self._adapter.deliver(action, rail_config)

        idem = (job.get("payload") or {}).get("idempotency_key") or job.get("idempotency_key")
        if result.success:
            # external_id = the idempotency/delivery id the tenant echoes back.
            return SenderResult(
                "success", external_id=idem or f"whk-{uuid.uuid4().hex}",
                response_code=result.response_code, raw={"response_code": result.response_code},
            )

        code = result.response_code
        err = result.error or "delivery failed"
        if code is not None and 400 <= code < 500 and code != 429:
            return SenderResult("fatal", response_code=code, error=err)
        if code is not None and (code >= 500 or code == 429):
            return SenderResult("retryable", response_code=code, error=err)
        # No HTTP status → network/timeout OR a fail-closed config/SSRF block.
        lowered = err.lower()
        if any(tok in lowered for tok in ("ssrf", "https", "malformed", "missing", "not available", "invalid webhook")):
            return SenderResult("fatal", error=err)
        return SenderResult("retryable", error=err)


# ═══════════════════════════════════════════════════════════════════════════
# OUTBOX SERVICE
# ═══════════════════════════════════════════════════════════════════════════

class RewardDeliveryOutbox:
    """Enqueue + drain durable reward deliveries."""

    def __init__(
        self,
        job_repo: Optional[RewardDeliveryJobRepository] = None,
        receipt_repo: Any = None,
        action_repo: Any = None,
        sender: Optional[RewardWebhookSender] = None,
        *,
        worker_id: Optional[str] = None,
    ) -> None:
        self._jobs = job_repo or RewardDeliveryJobRepository()
        self._sender = sender or RewardWebhookSender()
        self._receipt_repo = receipt_repo
        self._action_repo = action_repo
        self._worker_id = worker_id or f"reward-outbox-{uuid.uuid4().hex[:8]}"

    def _receipts(self):
        if self._receipt_repo is None:
            from repositories.delivery_repos import ProviderReceiptRepository
            self._receipt_repo = ProviderReceiptRepository()
        return self._receipt_repo

    def _actions(self):
        if self._action_repo is None:
            from services.rewards.repositories import RewardActionRepository
            self._action_repo = RewardActionRepository()
        return self._action_repo

    # ── enqueue ───────────────────────────────────────────────────────────

    async def enqueue(self, action: dict, rail_config: dict, tenant_id: str) -> dict:
        """Durably enqueue a reward delivery for any outbox-deliverable rail.

        The rail is taken from the action (default ``tenant_webhook``). Webhook
        jobs run the PR-1 hardened SSRF check BEFORE the job is written; other
        rails (internal_credit / stripe_credit / x402_credit) enqueue their
        payload for the registered sender. A rail with no registered sender is
        refused at enqueue (fail-closed) — the outbox never holds an
        undeliverable job. Returns the persisted job row.
        """
        import os

        from services.rewards.senders import has_sender

        rail = action.get("rail") or "tenant_webhook"
        if not has_sender(rail):
            metrics.increment("rewards_outbox_rejected", labels={"tenant_id": tenant_id, "reason": "no_sender"})
            raise ValueError(f"rail {rail!r} has no registered outbox sender")

        payload = action.get("payload") or {}
        config = rail_config.get("config", rail_config) if isinstance(rail_config, dict) else {}

        if rail != "tenant_webhook":
            return await self._enqueue_generic(rail, action, config, payload, tenant_id)

        webhook_url = (
            rail_config.get("webhook_url")
            or config.get("webhook_url")
            or (rail_config.get("config", {}) or {}).get("webhook_url")
        )
        # Persist a secret_ref, NEVER the plaintext secret. The secret is
        # resolved from the credential authority at the narrow signing call
        # site (RewardWebhookSender.send). A legacy inline secret is tolerated
        # in local/test only.
        from services.rewards.webhook_secret import make_secret_ref

        secret_ref = config.get("secret_ref") or rail_config.get("secret_ref") or make_secret_ref()
        inline_secret = ""
        if os.getenv("AETHER_ENV", "local").lower() in ("local", "test"):
            inline_secret = config.get("signing_secret", "") or rail_config.get("signing_secret", "")
        timeout_ms = int(config.get("timeout_ms", rail_config.get("timeout_ms", 10000)))

        # PR-1 SSRF / transport validation before persisting a durable job.
        env = os.getenv("AETHER_ENV", "local").lower()
        is_local = env in ("local", "test")
        reason = TenantWebhookAdapter()._validate_destination(webhook_url, is_local=is_local)
        if reason is not None:
            metrics.increment("rewards_outbox_rejected", labels={"tenant_id": tenant_id, "reason": "ssrf_blocked"})
            raise ValueError(f"webhook destination rejected before enqueue: {reason}")

        job_id = str(uuid.uuid4())
        idem = payload.get("idempotency_key") or f"whk-{job_id}"
        job = {
            "tenant_id": tenant_id,
            "action_id": action.get("id"),
            "provider_adapter": _WEBHOOK_PROVIDER,
            "channel": "webhook",
            "state": "queued",
            "payload": payload,
            "provider_config": {
                "webhook_url": webhook_url,
                "secret_ref": secret_ref,
                # Local/test convenience only; never populated in deployed envs.
                "signing_secret": inline_secret,
                "timeout_ms": timeout_ms,
                "host": urlparse(webhook_url).hostname if isinstance(webhook_url, str) else None,
            },
            "idempotency_key": idem,
            "attempt_count": 0,
            "max_attempts": _DEFAULT_MAX_ATTEMPTS,
            "next_attempt_at": _now_iso(),
            "last_error": None,
        }
        stored = await self._jobs.insert(job_id, job)
        metrics.increment("rewards_outbox_enqueued", labels={"tenant_id": tenant_id, "rail": rail})
        logger.info("reward webhook enqueued job=%s action=%s host=%s",
                    job_id, action.get("id"), job["provider_config"]["host"])
        return stored

    async def _enqueue_generic(
        self, rail: str, action: dict, config: dict, payload: dict, tenant_id: str
    ) -> dict:
        """Enqueue a non-webhook rail (internal_credit / stripe_credit /
        x402_credit) — no SSRF check; the sender resolves its own credentials.
        No plaintext secret is stored; only a secret_ref (for rails that need
        one) travels on the job."""
        job_id = str(uuid.uuid4())
        idem = payload.get("idempotency_key") or f"{rail}-{job_id}"
        job = {
            "tenant_id": tenant_id,
            "action_id": action.get("id"),
            "provider_adapter": rail,
            "rail": rail,
            "channel": "ledger" if rail in ("internal_credit", "x402_credit") else "api",
            "state": "queued",
            "payload": payload,
            "provider_config": {
                # secret_ref only — the sender resolves the real credential
                # from the authority at the narrow send site.
                "secret_ref": config.get("secret_ref"),
                "stripe_customer_id": config.get("stripe_customer_id"),
            },
            "idempotency_key": idem,
            "attempt_count": 0,
            "max_attempts": _DEFAULT_MAX_ATTEMPTS,
            "next_attempt_at": _now_iso(),
            "last_error": None,
        }
        stored = await self._jobs.insert(job_id, job)
        metrics.increment("rewards_outbox_enqueued", labels={"tenant_id": tenant_id, "rail": rail})
        logger.info("reward %s enqueued job=%s action=%s", rail, job_id, action.get("id"))
        return stored

    # ── drain (lease + dispatch + receipt) ────────────────────────────────

    async def drain(self, *, batch_size: int = 10, lease_seconds: int = 120) -> dict:
        """Lease and process a batch of runnable jobs. Returns a summary dict."""
        jobs = await self._jobs.lease_next_batch(self._worker_id, batch_size, lease_seconds)
        delivered = retried = dead_lettered = 0
        for job in jobs:
            outcome = await self._process_job(job)
            if outcome == "delivered":
                delivered += 1
            elif outcome == "dead_letter":
                dead_lettered += 1
            else:
                retried += 1
        return {
            "leased": len(jobs), "delivered": delivered,
            "retried": retried, "dead_lettered": dead_lettered,
        }

    def _sender_for(self, job: dict):
        """Resolve the sender for a job's rail via the registry, falling back
        to the default webhook sender for legacy webhook jobs."""
        rail = job.get("rail") or (
            "tenant_webhook" if job.get("provider_adapter") == _WEBHOOK_PROVIDER else None
        )
        if rail and rail != "tenant_webhook":
            from services.rewards.senders import get_sender

            sender = get_sender(rail)
            if sender is not None:
                return sender
        return self._sender

    async def _process_job(self, job: dict) -> str:
        job_id = job["id"]
        tenant_id = job.get("tenant_id", "")
        attempt = int(job.get("attempt_count", 0)) + 1
        max_attempts = int(job.get("max_attempts", _DEFAULT_MAX_ATTEMPTS))

        result = await self._sender_for(job).send(job)

        if result.outcome == "success":
            # DURABLE-BEFORE-ACK: persist the ProviderReceipt FIRST; only then
            # is the delivery real. If the receipt is invalid/unpersistable the
            # job is retried, never marked delivered.
            try:
                receipt_id = await self._record_receipt(job, result)
            except Exception as exc:
                logger.error("reward receipt persist failed job=%s: %s", job_id, exc)
                return await self._schedule_retry_or_dlq(job, attempt, max_attempts,
                                                         f"receipt persist failed: {exc}")
            # Lease-guarded: a stale worker whose batch was re-claimed must
            # not overwrite the new owner's active job (see release_job).
            await self._jobs.release_job(job_id, self._worker_id, {
                "state": "delivered", "attempt_count": attempt,
                "receipt_id": receipt_id, "external_id": result.external_id,
                "leased_by": None, "lease_expires_at": None, "delivered_at": _now_iso(),
            })
            await self._mark_action_delivered(job, receipt_id)
            metrics.increment("rewards_outbox_delivered", labels={"tenant_id": tenant_id})
            logger.info("reward webhook delivered job=%s receipt=%s external_id=%s",
                        job_id, receipt_id, result.external_id)
            return "delivered"

        if result.outcome == "fatal":
            await self._dead_letter(job, attempt, result.error or "fatal error")
            return "dead_letter"

        return await self._schedule_retry_or_dlq(job, attempt, max_attempts, result.error or "retryable error")

    async def _schedule_retry_or_dlq(self, job: dict, attempt: int, max_attempts: int, error: str) -> str:
        if attempt >= max_attempts:
            await self._dead_letter(job, attempt, error)
            return "dead_letter"
        from services.delivery.worker import _compute_next_attempt_at
        next_at = _compute_next_attempt_at(attempt)
        await self._jobs.release_job(job["id"], self._worker_id, {
            "state": "failed", "attempt_count": attempt, "last_error": error[:500],
            "next_attempt_at": next_at, "leased_by": None, "lease_expires_at": None,
        })
        metrics.increment("rewards_outbox_retry", labels={"tenant_id": job.get("tenant_id", "")})
        logger.warning("reward webhook retry job=%s attempt=%s/%s next=%s err=%s",
                       job["id"], attempt, max_attempts, next_at, error[:200])
        return "retry"

    async def _dead_letter(self, job: dict, attempt: int, error: str) -> None:
        await self._jobs.release_job(job["id"], self._worker_id, {
            "state": "dead_letter", "attempt_count": attempt, "last_error": error[:500],
            "leased_by": None, "lease_expires_at": None,
        })
        # Reward action can NEVER be 'delivered' without a receipt → mark failed.
        action_id = job.get("action_id")
        tenant_id = job.get("tenant_id", "")
        if action_id and self._actions():
            try:
                await self._actions().transition(
                    action_id, tenant_id, "failed",
                    extra={"last_delivery_error": error[:500]},
                )
            except Exception as exc:
                logger.warning("reward action failed-transition error action=%s: %s", action_id, exc)
        metrics.increment("rewards_outbox_dead_lettered", labels={"tenant_id": tenant_id})
        logger.error("reward webhook DEAD-LETTER job=%s attempt=%s err=%s", job["id"], attempt, error[:200])

    async def _record_receipt(self, job: dict, result: SenderResult) -> str:
        """Persist a validated ProviderReceipt (rejects empty/sim external ids).

        The receipt records the job's REAL rail and channel so an
        internal_credit / stripe_credit / x402_credit delivery is not mislabeled
        as a tenant_webhook and stays findable through provider-scoped receipt
        lookups. The webhook constants are the fallback only for legacy webhook
        jobs (which carry no explicit rail).
        """
        from services.delivery.models import DeliveryChannel, ProviderReceipt
        rail = job.get("rail") or job.get("provider_adapter") or _WEBHOOK_PROVIDER
        try:
            channel = DeliveryChannel(job.get("channel") or "webhook")
        except ValueError:
            channel = DeliveryChannel.WEBHOOK
        receipt = ProviderReceipt(
            job_id=job["id"],
            intent_id=job.get("action_id", ""),      # link back to the reward action
            tenant_id=job.get("tenant_id", ""),
            provider_adapter=rail,
            external_id=result.external_id or "",
            channel=channel,
            raw_response=result.raw,
        )
        await self._receipts().insert(receipt.id, receipt.model_dump())

        # Durable receipt evidence: every reward-outbox delivery receipt leaves
        # an immutable audit trace (RewardReceiptEvidenceService.record).
        # Best-effort at the edge — a recording failure must not fail a
        # delivery that already has a durable ProviderReceipt.
        try:
            from services.rewards.receipt_evidence import get_receipt_evidence_service
            await get_receipt_evidence_service().record(
                "delivery",
                tenant_id=job.get("tenant_id", ""),
                receipt_id=receipt.id,
                rail=rail,
                external_id=result.external_id or receipt.id,
                status="delivered",
                action_id=job.get("action_id"),
            )
        except Exception as exc:  # noqa: BLE001 — evidence is best-effort
            logger.warning(f"reward delivery receipt evidence record failed rid={receipt.id}: {exc}")
        return receipt.id

    async def _mark_action_delivered(self, job: dict, receipt_id: str) -> None:
        action_id = job.get("action_id")
        tenant_id = job.get("tenant_id", "")
        if not action_id or not self._actions():
            return
        try:
            action = await self._actions().transition(
                action_id, tenant_id, "delivered",
                extra={"delivery_receipt_id": receipt_id, "delivery_job_id": job["id"]},
            )
            # Commit the budget reservation now that the spend is final.
            res_id = (action or {}).get("reservation_id")
            if res_id:
                try:
                    from services.rewards.budget import BudgetReservationService
                    await BudgetReservationService().commit(res_id, tenant_id=tenant_id)
                except Exception as exc:
                    logger.warning("reward outbox budget commit failed res=%s: %s", res_id, exc)
        except Exception as exc:
            logger.warning("reward action delivered-transition error action=%s: %s", action_id, exc)

    async def status(self, tenant_id: str) -> dict:
        return await self._jobs.status_counts(tenant_id)

    async def dead_letter_depth(self) -> int:
        """Cross-tenant count of dead-lettered jobs (DLQ sweeper metric)."""
        rows = await self._jobs.find_many(filters={"state": "dead_letter"}, limit=10000)
        return len(rows)

    async def redeliver(self, job_id: str, tenant_id: str) -> dict:
        """Operator replay: requeue a failed/dead-lettered job for another attempt."""
        job = await self._jobs.find_by_id(job_id)
        if job is None or job.get("tenant_id") != tenant_id:
            raise ValueError("reward delivery job not found for tenant")
        await self._jobs.update(job_id, {
            "state": "queued", "next_attempt_at": _now_iso(),
            "leased_by": None, "lease_expires_at": None,
        })
        metrics.increment("rewards_outbox_replayed", labels={"tenant_id": tenant_id})
        return await self._jobs.find_by_id(job_id)


# Module-level singleton for route wiring.
reward_delivery_outbox = RewardDeliveryOutbox()


async def build_reward_delivery_outbox_worker(poll_interval_seconds: float = 5.0) -> None:
    """Long-running drain loop (for supervisor wiring).

    Not auto-started here — wire into the runtime supervisor to run continuously.
    Drains a batch each tick; sleeps when idle.
    """
    import asyncio
    outbox = RewardDeliveryOutbox()
    logger.info("reward delivery outbox worker started")
    while True:
        try:
            summary = await outbox.drain(batch_size=10)
            if summary["leased"] == 0:
                await asyncio.sleep(poll_interval_seconds)
        except asyncio.CancelledError:
            logger.info("reward delivery outbox worker stopped")
            raise
        except Exception as exc:
            logger.error("reward delivery outbox worker error: %s", exc)
            await asyncio.sleep(poll_interval_seconds)
