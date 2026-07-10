"""Aether Runtime — Worker specs for the application lifespan.

``build_worker_specs`` maps every long-running loop worker that main.py's
lifespan previously started ad-hoc onto a supervised :class:`WorkerSpec`.
Each factory returns a FRESH coroutine per (re)start and performs its own
imports so a broken optional module surfaces as a supervised crash instead
of an import error at spec-build time.

Consumer-attach style wiring (ingestion workers, profile360 workers,
measurement identity consumer, notification consumers) is NOT represented
here — those stay as direct attach calls in the lifespan.

Adding a new supervised worker later (e.g. the jobs platform's
``build_job_worker_coro`` / ``build_lease_sweeper_coro`` /
``build_schedule_tick_coro`` or the notifications outbox worker) is a
one-line ``specs.append(WorkerSpec(...))`` in this function.
"""

from __future__ import annotations

import asyncio
from typing import Any, Coroutine

from services.runtime.supervisor import WorkerSpec


def build_worker_specs(*, registry: Any, settings: Any) -> list[WorkerSpec]:
    """Build the supervised worker specs for the current lifespan workers.

    Args:
        registry: the ResourceRegistry (shared cache / producer / consumer).
        settings: the config.settings.Settings singleton.

    required=True workers (event replay, notification SLA, retention sweep)
    abort startup in staging/production if their first start fails; the
    supervisor only enforces ``required`` in those environments.
    """

    # ── factories (fresh coroutine per call) ──────────────────────────────

    def _event_replay() -> Coroutine[Any, Any, None]:
        from services.events.worker import start_replay_worker

        return start_replay_worker()

    def _overage_cron() -> Coroutine[Any, Any, None]:
        from services.billing.cron import run_monthly_overage_cron

        return run_monthly_overage_cron()

    def _notification_sla() -> Coroutine[Any, Any, None]:
        from services.notification_intelligence.lifecycle import start_sla_worker

        return start_sla_worker(producer=registry.producer)

    def _dune_polling() -> Coroutine[Any, Any, None]:
        # Canonical Dune worker: governed scheduler with schedule store +
        # admin routes. The legacy services.integrations.dune_feeder loop is
        # intentionally NOT started (it previously leaked an orphaned task).
        from services.dune_feeder.scheduler import start_dune_polling_worker

        return start_dune_polling_worker()

    def _retention_sweep() -> Coroutine[Any, Any, None]:
        from services.security.retention_worker import retention_sweep_loop

        return retention_sweep_loop()

    async def _run_delivery_worker() -> None:
        """Own a DeliveryWorker instance for the lifetime of this coroutine.

        DeliveryWorker.start() spawns its own internal poll task; awaiting it
        here ties that task's lifetime to the supervised coroutine, and
        worker.stop() in the finally block guarantees the internal task is
        cancelled and drained on shutdown or crash-restart.
        """
        from services.delivery.worker import DeliveryWorker

        worker = DeliveryWorker(
            batch_size=getattr(settings.delivery, "batch_size", 10),
            poll_interval_seconds=getattr(settings.delivery, "poll_interval_seconds", 5),
        )
        await worker.start()
        try:
            if worker._task is not None:
                await asyncio.shield(worker._task)
        finally:
            await worker.stop()

    def _delivery_worker() -> Coroutine[Any, Any, None]:
        return _run_delivery_worker()

    def _webhook_inbox() -> Coroutine[Any, Any, None]:
        from repositories.delivery_repos import (
            WebhookInboxRepository,
            ExternalOutcomeEventRepository,
            ExternalResourceLinkRepository,
        )
        from repositories.repos import (
            SuggestionsRepository,
            NotificationIntelligenceRepository,
        )
        from services.delivery.outcome_processor import (
            OutcomeRouter,
            WebhookInboxProcessor,
        )

        processor = WebhookInboxProcessor(
            inbox_repo=WebhookInboxRepository(),
            outcome_repo=ExternalOutcomeEventRepository(),
            link_repo=ExternalResourceLinkRepository(),
            router=OutcomeRouter(
                outcome_repo=ExternalOutcomeEventRepository(),
                link_repo=ExternalResourceLinkRepository(),
                suggestion_repo=SuggestionsRepository(),
                notification_repo=NotificationIntelligenceRepository(),
            ),
        )
        return processor.run()

    # ── Durable job control plane (services/jobs) ────────────────────────
    def _job_worker() -> Coroutine[Any, Any, None]:
        from services.jobs.worker import build_job_worker_coro

        return build_job_worker_coro()

    def _job_lease_sweeper() -> Coroutine[Any, Any, None]:
        from services.jobs.worker import build_lease_sweeper_coro

        return build_lease_sweeper_coro()

    def _job_scheduler() -> Coroutine[Any, Any, None]:
        from services.jobs.scheduler import build_schedule_tick_coro

        return build_schedule_tick_coro()

    def _notification_outbox() -> Coroutine[Any, Any, None]:
        from services.notification_intelligence.delivery_outbox import (
            build_notification_outbox_worker,
        )

        return build_notification_outbox_worker()

    # ── specs (registration order mirrors the old lifespan start order) ───

    return [
        WorkerSpec(
            name="event_replay",
            factory=_event_replay,
            required=True,
        ),
        WorkerSpec(
            name="billing_overage_cron",
            factory=_overage_cron,
        ),
        WorkerSpec(
            name="notification_sla",
            factory=_notification_sla,
            required=True,
        ),
        WorkerSpec(
            name="dune_polling",
            factory=_dune_polling,
        ),
        WorkerSpec(
            name="retention_sweep",
            factory=_retention_sweep,
            required=True,
        ),
        WorkerSpec(
            name="delivery_worker",
            factory=_delivery_worker,
            enabled=lambda: bool(settings.delivery.enabled),
        ),
        WorkerSpec(
            name="webhook_inbox",
            factory=_webhook_inbox,
            enabled=lambda: bool(settings.delivery.enabled),
        ),
        # Durable job control plane: worker leases + runs jobs, sweeper recovers
        # expired leases/expired jobs, scheduler fires cron schedules. Required
        # in staging/prod — a durable job platform with no worker silently never
        # runs submitted work.
        WorkerSpec(
            name="job_worker",
            factory=_job_worker,
            required=True,
        ),
        WorkerSpec(
            name="job_lease_sweeper",
            factory=_job_lease_sweeper,
            required=True,
        ),
        WorkerSpec(
            name="job_scheduler",
            factory=_job_scheduler,
            required=True,
        ),
        WorkerSpec(
            name="notification_outbox",
            factory=_notification_outbox,
        ),
    ]
