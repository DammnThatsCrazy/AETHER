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

    def _kyber_directory_sync() -> Coroutine[Any, Any, None]:
        """Reconcile Kyber workforce principals against Google Workspace.

        Runs under the existing ``maintenance`` role rather than a dedicated
        runtime role: it is a single periodic loop, and a new role would fan out
        across roles.py, RUNTIME_ROLES, deploy profiles, compose, Terraform and
        two topology validators for no operational benefit. Staleness is what
        matters here, not throughput — a principal whose directory state is
        older than the configured window fails closed for privileged access.
        """
        from services.kyber.identity.directory_sync import build_directory_sync_coro

        return build_directory_sync_coro()

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

    def _export_expiry_sweep() -> Coroutine[Any, Any, None]:
        from services.export import build_export_expiry_sweep_coro

        return build_export_expiry_sweep_coro()

    def _event_outbox_relay() -> Coroutine[Any, Any, None]:
        from services.ingestion.outbox_relay import build_event_outbox_relay_coro

        return build_event_outbox_relay_coro()

    def _payment_rail_sync() -> Coroutine[Any, Any, None]:
        from services.integrations.providers.payment_rails.sync_worker import (
            build_payment_rail_sync_coro,
        )

        return build_payment_rail_sync_coro()

    def _bronze_object_compaction() -> Coroutine[Any, Any, None]:
        from services.storage_lifecycle.worker import build_bronze_compaction_coro

        return build_bronze_compaction_coro()

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
            name="kyber_directory_sync",
            factory=_kyber_directory_sync,
            enabled=lambda: bool(settings.kyber_workforce.directory_sync_enabled),
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
        # Ingestion V2 event-outbox relay (FT-6): drains event_outbox to the
        # bus so downstream Bronze→Silver/identity/measurement work runs in a
        # replayable worker instead of the request. Gated on the V2 relay flag
        # so it never runs when the transactional ingest path is off.
        WorkerSpec(
            name="event_outbox_relay",
            factory=_event_outbox_relay,
            enabled=lambda: bool(settings.ingestion_v2.outbox_relay_enabled),
        ),
        # Physical deletion of expired export artifacts (tombstones remain).
        WorkerSpec(
            name="export_expiry_sweep",
            factory=_export_expiry_sweep,
        ),
        # Payment Rail Observability: periodic provider-truth pull + staleness
        # reconciliation + card-linked Gold materialization. Gated on the
        # payment-rails flag so it never runs when the plane is off.
        WorkerSpec(
            name="payment_rail_sync",
            factory=_payment_rail_sync,
            enabled=lambda: bool(settings.payment_rails.enabled),
        ),
        # Object-backed Bronze compaction (FT-8): packs cold Bronze payloads
        # into externalized objects (hot searchable metadata stays in Postgres)
        # and schedules the FT-7 storage reconciler. Gated on the storage-plane
        # flags so it never runs while the object write path is off.
        WorkerSpec(
            name="bronze_object_compaction",
            factory=_bronze_object_compaction,
            enabled=lambda: bool(
                (
                    settings.storage_plane.bronze_compaction_enabled
                    and settings.storage_plane.externalization_enabled
                )
                or settings.storage_plane.reconciler_enabled
            ),
        ),
    ]
