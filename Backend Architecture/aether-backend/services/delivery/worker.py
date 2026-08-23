"""DeliveryWorker — polls DeliveryJobs and dispatches via ProviderAdapters.

Uses lease semantics (SELECT FOR UPDATE SKIP LOCKED in PostgreSQL mode) so
multiple workers can run safely. Implements exponential backoff with jitter,
dead-letter after max_attempts, and durable ProviderReceipt recording.

Never marks a Suggestion or Notification as DELIVERED until a ProviderReceipt
with a real external_id is persisted.
"""

from __future__ import annotations

import asyncio
import random
import uuid
from datetime import datetime, timezone, timedelta
from typing import Any, Optional

from shared.logger.logger import get_logger

logger = get_logger("aether.delivery.worker")

# Backoff parameters
_BACKOFF_BASE_SECONDS = 30
_BACKOFF_MULTIPLIER = 2
_BACKOFF_MAX_SECONDS = 1800   # 30 minutes
_BACKOFF_JITTER = 0.20        # ±20%

_DEFAULT_BATCH_SIZE = 10
_DEFAULT_LEASE_SECONDS = 120
_DEFAULT_POLL_INTERVAL_SECONDS = 5


def _compute_next_attempt_at(attempt_number: int) -> str:
    """Exponential backoff with ±20% jitter, capped at _BACKOFF_MAX_SECONDS."""
    delay = _BACKOFF_BASE_SECONDS * (_BACKOFF_MULTIPLIER ** (attempt_number - 1))
    delay = min(delay, _BACKOFF_MAX_SECONDS)
    jitter = delay * _BACKOFF_JITTER * (2 * random.random() - 1)
    delay = max(1, delay + jitter)
    at = datetime.now(timezone.utc) + timedelta(seconds=delay)
    return at.isoformat()


class DeliveryWorker:
    """Polls DeliveryJob queue and dispatches via ProviderAdapterRegistry."""

    def __init__(
        self,
        job_repo: Any = None,
        intent_repo: Any = None,
        attempt_repo: Any = None,
        receipt_repo: Any = None,
        resource_link_repo: Any = None,
        adapter_registry: Any = None,
        *,
        worker_id: Optional[str] = None,
        batch_size: int = _DEFAULT_BATCH_SIZE,
        lease_seconds: int = _DEFAULT_LEASE_SECONDS,
        poll_interval_seconds: float = _DEFAULT_POLL_INTERVAL_SECONDS,
    ) -> None:
        self._job_repo = job_repo
        self._intent_repo = intent_repo
        self._attempt_repo = attempt_repo
        self._receipt_repo = receipt_repo
        self._resource_link_repo = resource_link_repo
        self._registry = adapter_registry
        self._worker_id = worker_id or f"worker-{uuid.uuid4().hex[:8]}"
        self._batch_size = batch_size
        self._lease_seconds = lease_seconds
        self._poll_interval = poll_interval_seconds
        self._running = False
        self._task: Optional[asyncio.Task] = None  # type: ignore[type-arg]

    # ── lifecycle ─────────────────────────────────────────────────────────────

    async def start(self) -> None:
        """Start the background poll loop."""
        from repositories.delivery_repos import (
            DeliveryJobRepository, DeliveryIntentRepository,
            DeliveryAttemptRepository, ProviderReceiptRepository,
            ExternalResourceLinkRepository,
        )
        from services.delivery.adapters.base import ProviderAdapterRegistry

        if self._job_repo is None:
            self._job_repo = DeliveryJobRepository()
        if self._intent_repo is None:
            self._intent_repo = DeliveryIntentRepository()
        if self._attempt_repo is None:
            self._attempt_repo = DeliveryAttemptRepository()
        if self._receipt_repo is None:
            self._receipt_repo = ProviderReceiptRepository()
        if self._resource_link_repo is None:
            self._resource_link_repo = ExternalResourceLinkRepository()
        if self._registry is None:
            self._registry = ProviderAdapterRegistry.default()

        self._running = True
        self._task = asyncio.create_task(self._poll_loop(), name="delivery-worker")
        logger.info(f"DeliveryWorker {self._worker_id!r} started")

    async def stop(self) -> None:
        """Gracefully stop the worker."""
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info(f"DeliveryWorker {self._worker_id!r} stopped")

    # ── poll loop ─────────────────────────────────────────────────────────────

    async def _poll_loop(self) -> None:
        while self._running:
            try:
                jobs = await self._job_repo.lease_next_batch(
                    worker_id=self._worker_id,
                    batch_size=self._batch_size,
                    lease_seconds=self._lease_seconds,
                )
                if jobs:
                    await asyncio.gather(
                        *[self._process_job(job) for job in jobs],
                        return_exceptions=True,
                    )
                else:
                    await asyncio.sleep(self._poll_interval)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error(f"DeliveryWorker poll error: {exc}", exc_info=True)
                await asyncio.sleep(self._poll_interval)

    # ── job processing ────────────────────────────────────────────────────────

    async def _process_job(self, job: dict[str, Any]) -> None:
        job_id = job.get("id", "unknown")
        provider = job.get("provider_adapter", "")
        tenant_id = job.get("tenant_id", "")
        attempt_number = job.get("attempt_count", 0) + 1

        logger.info(
            f"Processing delivery job={job_id!r} provider={provider!r} "
            f"attempt={attempt_number} tenant={tenant_id!r}"
        )

        start_ms = _now_ms()
        receipt_raw = None
        try:
            adapter = self._registry.get_or_raise(provider)
            credential = await self._resolve_credential(job)

            receipt_raw = await adapter.dispatch(
                payload=job.get("payload") or {},
                provider_config=job.get("provider_config") or {},
                credential=credential,
                idempotency_key=job.get("idempotency_key"),
            )
        except Exception as exc:
            duration_ms = _now_ms() - start_ms
            await self._on_failure(job, exc, attempt_number, duration_ms)
            return

        # Provider call succeeded — now persist (separate try so DB errors
        # don't re-trigger _on_failure and cause duplicate deliveries on retry)
        duration_ms = _now_ms() - start_ms
        try:
            await self._on_success(job, receipt_raw, attempt_number, duration_ms)
        except Exception as exc:
            logger.error(
                f"Persistence error after successful provider call job={job_id!r}: {exc}",
                exc_info=True,
            )

    async def _on_success(
        self, job: dict[str, Any], receipt_raw: Any,
        attempt_number: int, duration_ms: int,
    ) -> None:
        from services.delivery.models import (
            DeliveryAttemptOutcome, DeliveryJobState,
            DeliveryAttempt, ProviderReceipt, ExternalResourceLink,
            DeliveryIntentStatus,
        )

        job_id = job["id"]
        intent_id = job.get("intent_id", "")
        tenant_id = job.get("tenant_id", "")
        channel = job.get("channel", "notification")
        provider = job.get("provider_adapter", "")

        # Persist DeliveryAttempt
        attempt = DeliveryAttempt(
            job_id=job_id,
            intent_id=intent_id,
            tenant_id=tenant_id,
            attempt_number=attempt_number,
            outcome=DeliveryAttemptOutcome.SUCCESS,
            provider_adapter=provider,
            external_id=receipt_raw.external_id,
            http_status=receipt_raw.http_status,
            duration_ms=duration_ms,
            raw_response=receipt_raw.raw_response,
        )
        await self._attempt_repo.insert(attempt.id, attempt.model_dump())

        # Persist ProviderReceipt — validates non-empty, non-sim external_id
        try:
            from services.delivery.models import DeliveryChannel
            ch_enum = DeliveryChannel(channel) if channel in [c.value for c in DeliveryChannel] else DeliveryChannel.NOTIFICATION
            receipt = ProviderReceipt(
                job_id=job_id,
                intent_id=intent_id,
                tenant_id=tenant_id,
                provider_adapter=provider,
                external_id=receipt_raw.external_id,
                channel=ch_enum,
                raw_response=receipt_raw.raw_response,
            )
            await self._receipt_repo.insert(receipt.id, receipt.model_dump())
        except Exception as exc:
            logger.error(f"ProviderReceipt validation failed for job={job_id!r}: {exc}")
            # This should never happen if adapters follow contract; treat as failure
            await self._mark_job_failed(job, f"ProviderReceipt invalid: {exc}", attempt_number)
            return

        # Update job → DELIVERED (lease-guarded: a stale worker whose lease
        # expired and whose batch was re-claimed must not overwrite the new
        # owner's active job — see DeliveryJobRepository.release_job)
        await self._job_repo.release_job(job_id, self._worker_id, {
            "state": DeliveryJobState.DELIVERED.value,
            "attempt_count": attempt_number,
            "leased_by": None,
            "lease_expires_at": None,
            "updated_at": _now_iso(),
        })

        # Load intent to get source object type/id for downstream steps
        intent_data = await self._intent_repo.find_by_id(intent_id) if intent_id else None
        source_type = (intent_data or {}).get("source_type", "")
        source_id = (intent_data or {}).get("source_id", "")

        # Persist ExternalResourceLink — always, with source object fields for outcome routing
        raw = receipt_raw.raw_response or {}
        external_url = raw.get("url") or raw.get("permalink") or raw.get("html_url")
        link = ExternalResourceLink(
            tenant_id=tenant_id,
            intent_id=intent_id,
            receipt_id=receipt.id,
            provider=provider,
            external_id=receipt_raw.external_id,
            external_url=external_url,
            aether_object_type=source_type,
            aether_object_id=source_id,
        )
        await self._resource_link_repo.insert(link.id, link.model_dump())

        # Transition source suggestion to DELIVERED only after confirmed provider receipt
        if source_type == "suggestion" and source_id:
            await self._advance_suggestion_delivered(source_id, receipt.id)

        # Check if all jobs for this intent are done
        await self._maybe_complete_intent(intent_id, tenant_id, DeliveryIntentStatus.DELIVERED)

        logger.info(
            f"Delivery SUCCESS job={job_id!r} external_id={receipt_raw.external_id!r} "
            f"attempt={attempt_number} duration={duration_ms}ms"
        )

    async def _on_failure(
        self, job: dict[str, Any], exc: Exception,
        attempt_number: int, duration_ms: int,
    ) -> None:
        from services.delivery.adapters.base import RetryableProviderError
        from services.delivery.models import (
            DeliveryAttemptOutcome, DeliveryJobState,
            DeliveryAttempt, DeliveryIntentStatus,
        )

        job_id = job["id"]
        intent_id = job.get("intent_id", "")
        tenant_id = job.get("tenant_id", "")
        provider = job.get("provider_adapter", "")
        max_attempts = job.get("max_attempts", 5)

        is_retryable = isinstance(exc, RetryableProviderError)
        outcome = (
            DeliveryAttemptOutcome.RETRYABLE if is_retryable
            else DeliveryAttemptOutcome.FAILURE
        )

        attempt = DeliveryAttempt(
            job_id=job_id,
            intent_id=intent_id,
            tenant_id=tenant_id,
            attempt_number=attempt_number,
            outcome=outcome,
            provider_adapter=provider,
            error_message=str(exc)[:1000],
            duration_ms=duration_ms,
        )
        await self._attempt_repo.insert(attempt.id, attempt.model_dump())

        if attempt_number >= max_attempts or not is_retryable:
            # Dead-letter the job (lease-guarded — see release_job)
            await self._job_repo.release_job(job_id, self._worker_id, {
                "state": DeliveryJobState.DEAD_LETTER.value,
                "attempt_count": attempt_number,
                "last_error": str(exc)[:500],
                "leased_by": None,
                "lease_expires_at": None,
                "updated_at": _now_iso(),
            })
            logger.error(
                f"Delivery DEAD-LETTER job={job_id!r} provider={provider!r} "
                f"attempt={attempt_number}/{max_attempts}: {exc}"
            )
            await self._maybe_complete_intent(
                intent_id, tenant_id, DeliveryIntentStatus.FAILED
            )
        else:
            # Schedule retry, respecting provider Retry-After when present
            retry_after = getattr(exc, "retry_after_seconds", None)
            if retry_after:
                from datetime import timedelta
                retry_at = (datetime.now(timezone.utc) + timedelta(seconds=int(retry_after))).isoformat()
            else:
                retry_at = _compute_next_attempt_at(attempt_number)
            await self._job_repo.release_job(job_id, self._worker_id, {
                "state": DeliveryJobState.FAILED.value,
                "attempt_count": attempt_number,
                "last_error": str(exc)[:500],
                "next_attempt_at": retry_at,
                "leased_by": None,
                "lease_expires_at": None,
                "updated_at": _now_iso(),
            })
            logger.warning(
                f"Delivery RETRY job={job_id!r} provider={provider!r} "
                f"attempt={attempt_number}/{max_attempts} next_at={retry_at}: {exc}"
            )

    async def _mark_job_failed(
        self, job: dict[str, Any], error: str, attempt_number: int
    ) -> None:
        from services.delivery.models import DeliveryJobState
        await self._job_repo.release_job(job["id"], self._worker_id, {
            "state": DeliveryJobState.DEAD_LETTER.value,
            "attempt_count": attempt_number,
            "last_error": error[:500],
            "leased_by": None,
            "lease_expires_at": None,
            "updated_at": _now_iso(),
        })

    async def _maybe_complete_intent(
        self, intent_id: str, tenant_id: str, status: Any
    ) -> None:
        """Mark intent DELIVERED/FAILED if all its jobs have reached a terminal state."""
        if not intent_id:
            return
        try:
            from services.delivery.models import DeliveryJobState, DeliveryIntentStatus
            jobs = await self._job_repo.find_many(
                filters={"intent_id": intent_id, "tenant_id": tenant_id},
                limit=200,
            )
            terminal = {DeliveryJobState.DELIVERED.value, DeliveryJobState.DEAD_LETTER.value, DeliveryJobState.CANCELLED.value}
            if all(j.get("state") in terminal for j in jobs):
                all_delivered = all(j.get("state") == DeliveryJobState.DELIVERED.value for j in jobs)
                final_status = (
                    DeliveryIntentStatus.DELIVERED.value if all_delivered
                    else DeliveryIntentStatus.FAILED.value
                )
                await self._intent_repo.update(intent_id, {
                    "status": final_status,
                    "updated_at": _now_iso(),
                })
        except Exception as exc:
            logger.warning(f"Intent completion check failed for {intent_id!r}: {exc}")

    async def _resolve_credential(self, job: dict[str, Any]) -> Optional[str]:
        """Look up credential from vault via secret_ref in provider_config.

        Raises RetryableProviderError on transient vault failures so the job
        is retried rather than dead-lettered.
        """
        from services.delivery.adapters.base import RetryableProviderError
        provider_config = job.get("provider_config") or {}
        secret_ref = provider_config.get("secret_ref")
        if not secret_ref:
            return None
        try:
            from repositories.repos import ProvidersRepository
            repo = ProvidersRepository()
            record = await repo.find_by_id(secret_ref)
            if record:
                return record.get("api_key") or record.get("token")
            return None
        except Exception as exc:
            logger.warning(f"Credential resolution failed for secret_ref={secret_ref!r}: {exc}")
            raise RetryableProviderError(
                f"Transient vault failure resolving credential: {exc}"
            ) from exc

    async def _advance_suggestion_delivered(self, suggestion_id: str, receipt_id: str) -> None:
        """Transition a suggestion to DELIVERED status after confirmed provider receipt."""
        try:
            from services.suggestions.repository import SuggestionRepository
            repo = SuggestionRepository()
            await repo.update(suggestion_id, {
                "status": "delivered",
                "delivery_receipt_id": receipt_id,
                "delivered_at": _now_iso(),
            })
            logger.info("suggestion_delivered id=%s receipt=%s", suggestion_id, receipt_id)
        except Exception as exc:
            logger.warning("advance_suggestion_delivered_failed id=%s: %s", suggestion_id, exc)

    # ── one-shot dispatch (used by routes/tests) ──────────────────────────────

    async def dispatch_now(self, job: dict[str, Any]) -> dict[str, Any]:
        """Synchronously dispatch a single job and return the result dict."""
        await self._process_job(job)
        updated = await self._job_repo.find_by_id(job["id"])
        return updated or job


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _now_ms() -> int:
    import time
    return int(time.time() * 1000)


# Module-level singleton — started from main.py lifespan
delivery_worker = DeliveryWorker()
