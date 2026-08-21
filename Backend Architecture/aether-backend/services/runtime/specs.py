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

    def _semantic_reconciler() -> Coroutine[Any, Any, None]:
        """Recompute Gold semantic projections from Silver evidence + repair drift.

        Phase-B semantic worker: a periodic safety-net that re-derives each
        subject's Gold entity/sentiment state from the immutable Silver
        observations and repairs projections that no longer match. Gated on
        ``settings.semantic.reconciler_enabled`` (default OFF).
        """
        from services.semantic_intelligence.reconciler import (
            build_semantic_reconciler_coro,
        )

        return build_semantic_reconciler_coro()

    def _semantic_retention() -> Coroutine[Any, Any, None]:
        """Age out Silver semantic evidence + Gold projections past their window.

        Phase-B semantic worker: tombstones aged Silver observations and deletes
        aged (recomputable) Gold rows per ``retention_class`` window. Gated on
        ``settings.semantic.retention_enabled`` (default OFF).
        """
        from services.semantic_intelligence.retention import (
            build_semantic_retention_coro,
        )

        return build_semantic_retention_coro()

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

    def _kyber_retention_sweep() -> Coroutine[Any, Any, None]:
        """Delete terminal, aged-out rows from Kyber's short-lived tables.

        The storage-plane lifecycle resolves the correct ``short_lived`` window
        but can only reach externalized objects and Bronze rows; Kyber's
        session / step-up / challenge tables are plain JSONB rows, so nothing
        acted on that window. This loop is the executor. It rides the existing
        ``maintenance`` role alongside ``retention_sweep`` for the same reason
        directory sync does — one periodic loop does not justify a new runtime
        role and its deploy-profile/compose/Terraform fan-out.
        """
        from services.kyber.retention import build_kyber_retention_coro

        return build_kyber_retention_coro()

    def _kyber_graph_projector() -> Coroutine[Any, Any, None]:
        """Project the graph mutation ledger into Kyber Graph topology.

        Rides the existing ``graph-writer`` role, which owns no loop specs today
        and is otherwise consumer-attached. A projection whose only input is the
        graph mutation ledger belongs with the graph writers by definition, and
        a new runtime role would fan out across roles.py, RUNTIME_ROLES, deploy
        profiles, compose, Terraform and two topology validators for one loop.
        """
        from services.kyber.graph.projector import build_kyber_graph_projector_coro

        return build_kyber_graph_projector_coro()

    def _kyber_incident_correlation() -> Coroutine[Any, Any, None]:
        """Attach loose incident signals, then merge same-release incidents.

        Rides the existing ``maintenance`` role alongside ``kyber_directory_sync``
        and ``kyber_retention_sweep``, for the same reason both of those do: one
        periodic loop does not justify a new runtime role and the deploy-profile,
        compose, Terraform and topology-validator fan-out that comes with one.
        Not ``graph-writer`` — this reads no ledger.
        """
        from services.kyber.ops.correlation import build_incident_correlator_coro

        return build_incident_correlator_coro()

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

    def _payment_canonical_repair() -> Coroutine[Any, Any, None]:
        from services.integrations.providers.payment_rails.repair_worker import (
            build_payment_canonical_repair_coro,
        )

        return build_payment_canonical_repair_coro()

    def _payment_alert_eval() -> Coroutine[Any, Any, None]:
        from services.integrations.providers.payment_rails.alert_worker import (
            build_payment_alert_eval_coro,
        )

        return build_payment_alert_eval_coro()

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
        # Phase-B semantic workers: both ride the existing ``semantic-worker``
        # role (they operate the same Silver→Gold plane the classifier feeds)
        # and are gated on their own kill-switch flags, default OFF. Not
        # required=True: a stalled reconciler/retention sweep degrades a
        # maintenance function, it must never abort startup.
        WorkerSpec(
            name="semantic_reconciler",
            factory=_semantic_reconciler,
            role="semantic-worker",
            enabled=lambda: bool(settings.semantic.reconciler_enabled),
        ),
        WorkerSpec(
            name="semantic_retention",
            factory=_semantic_retention,
            role="semantic-worker",
            enabled=lambda: bool(settings.semantic.retention_enabled),
        ),
        WorkerSpec(
            name="kyber_directory_sync",
            factory=_kyber_directory_sync,
            enabled=lambda: bool(settings.kyber_workforce.directory_sync_enabled),
        ),
        # Gated by the same master switch as the storage-plane retention sweep:
        # this worker is the Kyber half of FT-8 retention, not a second policy.
        WorkerSpec(
            name="kyber_retention_sweep",
            factory=_kyber_retention_sweep,
            enabled=lambda: bool(settings.storage_plane.lifecycle_retention_enabled),
        ),
        # The Kyber Graph is a projection: if this loop stops, the operational
        # graph freezes at whatever it had already built and keeps answering.
        # `required=False` is deliberate — a frozen graph must degrade the Kyber
        # console, not take the API process down with it.
        WorkerSpec(
            name="kyber_graph_projector",
            factory=_kyber_graph_projector,
            # Gated on the workforce plane because the Kyber Graph is only
            # readable through it: projecting topology no one can read would
            # burn ledger reads for nothing.
            enabled=lambda: bool(settings.kyber_workforce.workforce_identity_enabled),
        ),
        # Not required=True: a stalled correlator degrades the incident view, it
        # must not abort startup. Same gate as the projector — the ops plane is
        # only readable through the workforce plane, so correlating what nobody
        # can read would burn writes for nothing.
        WorkerSpec(
            name="kyber_incident_correlation",
            factory=_kyber_incident_correlation,
            enabled=lambda: bool(settings.kyber_workforce.workforce_identity_enabled),
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
        # Financial canonical-repair safety net: scans the durable receipt ledger
        # for incomplete deliveries and idempotently re-drives canonical emission
        # / outbox enqueue. Gated on both the payment-rails master flag and the
        # canonical-repair flag (default ON outside local) so it self-heals
        # delivery gaps in staging/production but stays off in local dev.
        WorkerSpec(
            name="payment_canonical_repair",
            factory=_payment_canonical_repair,
            enabled=lambda: bool(
                settings.payment_rails.enabled
                and settings.payment_rails.canonical_repair_enabled
            ),
        ),
        # Derived-condition alert evaluator: runs alert_eval.py on a timer so the
        # payment-rail conditions with no single-series PromQL form
        # (reconciliation-conflict backlog, backlog growth, outbox stalling,
        # provider silence) actually fire instead of being present-but-inert.
        # Gated on the payment-rails master flag AND its own eval flag (default
        # off) so it never runs when the plane is off or the operator has not
        # opted in. Not required=True: a stalled evaluator degrades alerting, it
        # must not abort startup.
        WorkerSpec(
            name="payment_alert_eval",
            factory=_payment_alert_eval,
            enabled=lambda: bool(
                settings.payment_rails.enabled
                and settings.payment_rails.alert_eval_enabled
            ),
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
