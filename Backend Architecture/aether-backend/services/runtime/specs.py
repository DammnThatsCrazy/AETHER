"""Aether Runtime — Worker specs for the application lifespan.

``build_worker_specs`` maps every long-running loop worker that main.py's
lifespan previously started ad-hoc onto a supervised :class:`WorkerSpec`.
Each factory returns a FRESH coroutine per (re)start and performs its own
imports so a broken optional module surfaces as a supervised crash instead
of an import error at spec-build time.

Consumer-attach style wiring (ingestion workers, profile360 workers,
measurement identity consumer, notification consumers) is NOT represented
here — those stay as direct attach calls in the lifespan.

The no-orphan sweep (program sec10/sec11) registered every worker that existed
as a builder function or work unit without a role owner (reward delivery outbox,
card-linked graph outbox, stablecoin polling, interop scan, derivatives venue
sweeps, x402 reconciliation, credential expiry sweep, capability-readiness
revalidation, dead-letter sweeper, settlement reconciliation, reward reservation
release, reward claim reconciliation). Builders still being authored in the same
wave are registered lazily too: a missing module surfaces as a supervised crash,
never an import error at spec-build time, and most new specs are flag-gated OFF
by default until both the flag and the builder are live.

Adding a new supervised worker later is a one-line
``specs.append(WorkerSpec(...))`` in this function plus a role claim in
``services/runtime/roles.py::ROLE_TO_SPEC_NAMES`` so the no-orphan topology test
never sees an unclaimed spec.
"""

from __future__ import annotations

import asyncio
import os
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

    # ── no-orphan sweep (program sec10/sec11) ────────────────────────────────
    # Workers that existed as builder functions or work units but were never
    # registered with a role owner. Each factory lazily imports its builder so a
    # builder still being authored in this wave (or that the integration pass
    # must author) surfaces as a supervised crash instead of an import error at
    # spec-build time. All of these default OFF except the reward outbox drain.

    def _reward_delivery_outbox() -> Coroutine[Any, Any, None]:
        from services.rewards.delivery_outbox import (
            build_reward_delivery_outbox_worker,
        )

        return build_reward_delivery_outbox_worker()

    def _card_linked_graph_outbox() -> Coroutine[Any, Any, None]:
        from services.card_linked_payments.graph_outbox import (
            CardLinkedGraphOutboxWorker,
        )

        return CardLinkedGraphOutboxWorker().build_coro()

    def _stablecoin_provider_polling() -> Coroutine[Any, Any, None]:
        # Authored by INT-C in this wave: wraps StablecoinPollingScheduler
        # poll_provider / poll_finality behind a supervised loop factory.
        from services.stablecoins.polling import build_stablecoin_polling_loop

        return build_stablecoin_polling_loop()

    def _interop_scan() -> Coroutine[Any, Any, None]:
        # Wraps InteropProviderAdapter.scan via services/interop/scan_worker;
        # gated on settings.interop.adapters_enabled (inert by default).
        from services.interop.lifecycle import build_interop_scan_coro

        return build_interop_scan_coro()

    def _derivatives_venue_sweep() -> Coroutine[Any, Any, None]:
        # Authored by INT-C in this wave (venue reconciliation sweeps).
        from services.derivatives.multi_venue import build_venue_sweep_coro

        return build_venue_sweep_coro()

    def _x402_reconciliation() -> Coroutine[Any, Any, None]:
        # Authored by INT-C in this wave (delegates to the commerce
        # reconciliation engine).
        from services.x402.settlement import build_x402_reconciliation_coro

        return build_x402_reconciliation_coro()

    def _credential_expiry_sweep() -> Coroutine[Any, Any, None]:
        # Authored by the credential sweep agent (1B) in this wave.
        from services.providers.credentials.sweeper import (
            build_credential_expiry_sweeper,
        )

        return build_credential_expiry_sweeper()

    def _readiness_revalidation() -> Coroutine[Any, Any, None]:
        # Builder authored by the capability-readiness agent (1A) in this wave.
        from services.readiness_graph.revalidation_worker import (
            build_readiness_revalidation_worker,
        )

        return build_readiness_revalidation_worker()

    def _dead_letter_sweeper() -> Coroutine[Any, Any, None]:
        # Authored by INT-C in this wave (dead-letter requeue sweep over the
        # rewards DLQ / payment dead-lettered receipts / interop dead letters).
        from services.runtime.dead_letter_sweeper import (
            build_dead_letter_sweeper_coro,
        )

        return build_dead_letter_sweeper_coro()

    def _settlement_reconciliation() -> Coroutine[Any, Any, None]:
        # Authored by INT-C in this wave (payment-rails canonical repair seam).
        from services.integrations.providers.payment_rails.settlement import (
            build_settlement_reconciliation_coro,
        )

        return build_settlement_reconciliation_coro()

    def _reward_reservation_release() -> Coroutine[Any, Any, None]:
        # Authored by the rewards reservation-release agent in this wave
        # (expired budget-reservation release).
        from services.rewards.reservation_release import (
            get_reservation_release_service,
        )

        return get_reservation_release_service().build_release_loop(
            ttl_seconds=3600
        )

    def _reward_claim_reconciliation() -> Coroutine[Any, Any, None]:
        # Authored by the rewards claim-reconciliation agent in this wave.
        from services.rewards.reconcile import get_reward_claim_reconciler

        return get_reward_claim_reconciler().build_reconcile_loop(
            tenant_id=os.getenv("DEFAULT_TENANT_ID", "tenant_local_dev"),
            interval_s=300,
        )

    def _reward_receipt_evidence() -> Coroutine[Any, Any, None]:
        # Durable reward receipt-evidence recording (builder exists).
        from services.rewards.receipt_evidence import (
            get_receipt_evidence_service,
        )

        return get_receipt_evidence_service().build_evidence_loop()

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
        # ── no-orphan sweep registrations ────────────────────────────────────
        # Rewards durable delivery outbox drain (builder exists; idles when the
        # rewards job table is empty, like notification_outbox / export sweeps).
        # Un-gated for parity with those drain loops; a dedicated
        # AETHER_REWARDS_OUTBOX_ENABLED gate is proposed in wiringNeeds.
        WorkerSpec(
            name="reward_delivery_outbox",
            factory=_reward_delivery_outbox,
        ),
        # Card-linked graph projection outbox (builder exists). Gated on the
        # card-linked payment-rails plane: nothing to project when it is off.
        WorkerSpec(
            name="card_linked_graph_outbox",
            factory=_card_linked_graph_outbox,
            enabled=lambda: bool(settings.card_linked_payment_rails.enabled),
        ),
        # Stablecoin provider/finality polling. Builder authored (INT-C) in this
        # wave; gated on the stablecoin intelligence plane.
        WorkerSpec(
            name="stablecoin_provider_polling",
            factory=_stablecoin_provider_polling,
            enabled=lambda: bool(settings.stablecoin_intelligence.enabled),
        ),
        # Cross-chain adapter scan (interop). Builder pending (the interop scan
        # agent); gated on the interop adapter framework flag.
        WorkerSpec(
            name="interop_scan",
            factory=_interop_scan,
            enabled=lambda: bool(settings.interop.adapters_enabled),
        ),
        # Derivatives venue reconciliation sweep. Builder authored (INT-C) in
        # this wave; gated on the derivatives reconciliation flag.
        WorkerSpec(
            name="derivatives_venue_sweep",
            factory=_derivatives_venue_sweep,
            enabled=lambda: bool(settings.derivatives.reconciliation_enabled),
        ),
        # x402 settlement reconciliation. Builder authored (INT-C) in this
        # wave; gated on the intelligence-graph x402 layer flag.
        WorkerSpec(
            name="x402_reconciliation",
            factory=_x402_reconciliation,
            enabled=lambda: bool(settings.intelligence_graph.enable_x402_layer),
        ),
        # Credential-authority expiry/overlap sweep. Builder authored (Agent
        # 1B) in this wave; gated on the provider gateway plane. A dedicated
        # AETHER_CREDENTIAL_EXPIRY_SWEEP_ENABLED override is proposed in
        # wiringNeeds.
        WorkerSpec(
            name="credential_expiry_sweep",
            factory=_credential_expiry_sweep,
            enabled=lambda: bool(settings.provider_gateway.enabled),
        ),
        # Capability-readiness revalidation (Agent 1A's worker). Gated off by
        # default via the proposed RuntimeConfig flag so it stays inert until
        # the flag is live; the builder itself is already authored.
        WorkerSpec(
            name="readiness_revalidation",
            factory=_readiness_revalidation,
            enabled=lambda: bool(
                getattr(
                    settings.runtime,
                    "capability_readiness_revalidation_enabled",
                    False,
                )
            ),
        ),
        # Dead-letter requeue sweeper. Builder authored (INT-C) in this wave;
        # gated off by default via the proposed RuntimeConfig flag.
        WorkerSpec(
            name="dead_letter_sweeper",
            factory=_dead_letter_sweeper,
            enabled=lambda: bool(
                getattr(settings.runtime, "dead_letter_sweeper_enabled", False)
            ),
        ),
        # Settlement-state reconciliation. Builder authored (INT-C) in this
        # wave; gated off by default via the proposed payment-rails flag.
        WorkerSpec(
            name="settlement_reconciliation",
            factory=_settlement_reconciliation,
            enabled=lambda: bool(
                getattr(
                    settings.payment_rails,
                    "settlement_reconciliation_enabled",
                    False,
                )
            ),
        ),
        # Reward budget-reservation release. Builder authored (rewards agent) in
        # this wave; gated off by default via the proposed rewards flags (no
        # rewards config block exists yet, so both the config and the flag ride
        # wiringNeeds).
        WorkerSpec(
            name="reward_reservation_release",
            factory=_reward_reservation_release,
            enabled=lambda: bool(
                getattr(
                    getattr(settings, "rewards", None),
                    "reservation_release_enabled",
                    False,
                )
            ),
        ),
        # Reward claim-state reconciliation. Builder authored (rewards agent) in
        # this wave; same proposed rewards-config gate as reservation release.
        WorkerSpec(
            name="reward_claim_reconciliation",
            factory=_reward_claim_reconciliation,
            enabled=lambda: bool(
                getattr(
                    getattr(settings, "rewards", None),
                    "claim_reconciliation_enabled",
                    False,
                )
            ),
        ),
        # Reward receipt-evidence recording (builder exists). Gates on the same
        # proposed rewards-config block; idle until the flag is live.
        WorkerSpec(
            name="reward_receipt_evidence",
            factory=_reward_receipt_evidence,
            enabled=lambda: bool(
                getattr(
                    getattr(settings, "rewards", None),
                    "receipt_evidence_enabled",
                    False,
                )
            ),
        ),
    ]
