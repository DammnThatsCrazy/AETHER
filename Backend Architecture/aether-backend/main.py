"""
Aether Backend — Main Application
Mounts 65 service routers across all backend domains.
Applies middleware and serves the unified API.

Run:
    uvicorn main:app --reload --port 8000

Routes:
    GET  /                              Root
    GET  /v1/health                     Health check (deep probe)
    GET  /v1/metrics                    Internal metrics
    POST /v1/batch                    Canonical SDK batch events
    POST /v1/ingest/events[/batch]    Deprecated server-side connector aliases
    POST /v1/ingest/feed                External API feed
    GET  /v1/identity/profiles/{id}     Get profile
    PUT  /v1/identity/profiles/{id}     Upsert profile
    POST /v1/identity/merge             Merge identities
    GET  /v1/identity/profiles/{id}/graph  Profile graph
    POST /sdk/identity/resolve          Cross-device wallet identity resolution
    POST /v1/analytics/events/query     Query events
    GET  /v1/analytics/events/{id}      Get event
    GET  /v1/analytics/dashboard/summary  Dashboard
    POST /v1/analytics/export           Data export
    POST /v1/analytics/graphql          GraphQL endpoint
    WS   /v1/analytics/ws/events        Real-time stream (authenticated)
    GET  /v1/ml/models                  List ML models
    POST /v1/ml/predict                 Single prediction
    POST /v1/ml/predict/batch           Batch prediction
    GET  /v1/ml/features/{id}           Feature serving
    GET  /v1/agent/status               Agent status
    POST /v1/agent/tasks                Submit task
    GET  /v1/agent/tasks/{id}           Task status
    GET  /v1/agent/audit                Audit trail
    POST /v1/agent/kill-switch          Kill switch
    GET  /v1/campaigns                  List campaigns
    POST /v1/campaigns                  Create campaign
    GET  /v1/campaigns/{id}             Get campaign
    PATCH /v1/campaigns/{id}            Update campaign
    DELETE /v1/campaigns/{id}           Delete campaign
    GET  /v1/campaigns/{id}/attribution Attribution
    POST /v1/consent/records            Record consent
    GET  /v1/consent/records/{user_id}  Get consent
    POST /v1/consent/dsr                Submit DSR
    GET  /v1/consent/dsr                List DSRs
    POST   /v1/notifications/intelligence             Emit intelligence notification
    GET    /v1/notifications/intelligence             List intelligence notifications
    GET    /v1/notifications/intelligence/{id}        Get single notification
    PATCH  /v1/notifications/intelligence/{id}/approve    Operator approve
    PATCH  /v1/notifications/intelligence/{id}/suppress   Operator suppress
    PATCH  /v1/notifications/intelligence/{id}/escalate   Operator escalate
    PATCH  /v1/notifications/intelligence/{id}/annotate   Operator annotate
    POST   /v1/notifications/intelligence/{id}/replay     Re-deliver to channels
    GET    /v1/notifications/intelligence/{id}/audit       Full audit trail
    GET    /v1/notifications/config               Get tenant notification config
    PUT    /v1/notifications/config               Update tenant notification config
    GET    /v1/notifications/channels             List user notification channels
    POST   /v1/notifications/channels             Register channel
    PATCH  /v1/notifications/channels/{id}        Update channel
    DELETE /v1/notifications/channels/{id}        Remove channel
    POST   /v1/notifications/channels/{id}/test   Test channel delivery
    GET    /v1/notifications/channels/slack/connect  Initiate Slack OAuth
    GET    /v1/notifications/channels/slack/callback Slack OAuth callback
    POST   /v1/notifications/slack/callback       Slack interactive handler
    POST   /v1/notifications/telegram/callback    Telegram inline keyboard handler
    POST   /v1/notifications/webhooks             Create webhook (legacy)
    GET    /v1/notifications/webhooks             List webhooks (legacy)
    DELETE /v1/notifications/webhooks/{id}        Delete webhook (legacy)
    POST   /v1/notifications/alerts               Create alert (legacy)
    GET    /v1/notifications/alerts               List alerts (legacy)
    POST /v1/tenants                    Public sign-up (no auth)
    POST /v1/auth/recover               Recover lost API key via email (no auth)
    POST /v1/auth/register              Step 1 email sign-up: send OTP (no auth)
    POST /v1/auth/verify-email          Step 2: verify OTP, create tenant (no auth)
    POST /v1/auth/resend-verification   Resend OTP (no auth)
    POST /v1/auth/login                 Email+password login → API key (no auth)
    POST /v1/auth/sso/callback          SSO via Auth0 JWT → API key (no auth)
    GET  /v1/auth/sso/providers         List SSO providers (no auth)
    DELETE /v1/me/account               Self-service account deletion
    POST /v1/admin/tenants/{id}/deactivate  Deactivate tenant (admin)
    DELETE /v1/admin/tenants/{id}           GDPR delete tenant (admin)
    GET  /v1/me                         Caller profile + plan summary
    GET  /v1/me/usage                   Current-period usage stats (quota, RPM, days remaining)
    GET  /v1/me/api-keys                List caller's API keys (paginated)
    POST /v1/me/api-keys                Create API key (self-service)
    PATCH /v1/me/api-keys/{id}          Rename API key
    DELETE /v1/me/api-keys/{id}         Revoke API key
    POST /v1/contact/enterprise         Submit enterprise inquiry
    POST /v1/billing/checkout           Create Stripe Checkout session
    POST /v1/billing/portal             Create Stripe Billing Portal session
    GET  /v1/billing/invoices           List invoices
    GET  /v1/billing/invoices/{id}      Get invoice
    POST /v1/admin/billing/overage-cycle  Trigger overage invoice cycle (admin)
    POST /v1/admin/tenants              Create tenant
    GET  /v1/admin/tenants/{id}         Get tenant
    PATCH /v1/admin/tenants/{id}        Update tenant
    POST /v1/admin/tenants/{id}/api-keys  Create API key
    GET  /v1/admin/tenants/{id}/api-keys  List API keys
    DELETE /v1/admin/api-keys/{id}      Revoke API key
    GET  /v1/admin/tenants/{id}/billing Billing
    POST /v1/fraud/evaluate             Evaluate fraud
    POST /v1/fraud/evaluate/batch       Batch fraud evaluation
    GET  /v1/fraud/config               Fraud configuration
    PUT  /v1/fraud/config               Update fraud config
    GET  /v1/fraud/stats                Fraud statistics
    POST /v1/attribution/resolve        Resolve attribution
    POST /v1/attribution/touchpoints    Record touchpoint
    GET  /v1/attribution/journey/{id}   User journey
    GET  /v1/attribution/models         List attribution models
    POST /v1/rewards/evaluate               Evaluate reward eligibility (A6)
    POST /v1/rewards/evaluate/batch         Batch evaluate (max 50)
    GET  /v1/rewards/decisions              List eligibility decisions
    GET  /v1/rewards/decisions/{id}         Get decision
    POST /v1/rewards/campaigns              Create reward campaign
    GET  /v1/rewards/campaigns              List reward campaigns
    GET  /v1/rewards/campaigns/{id}         Get campaign
    PATCH /v1/rewards/campaigns/{id}        Update campaign
    POST /v1/rewards/campaigns/{id}/pause   Pause campaign
    POST /v1/rewards/campaigns/{id}/resume  Resume campaign
    POST /v1/rewards/campaigns/{id}/archive Archive campaign
    POST /v1/rewards/campaigns/{id}/rules   Add rule to campaign
    GET  /v1/rewards/campaigns/{id}/rules   List rules in campaign
    GET  /v1/rewards/rules/{id}             Get rule
    PATCH /v1/rewards/rules/{id}            Update rule
    POST /v1/rewards/rules/{id}/enable      Enable rule
    POST /v1/rewards/rules/{id}/disable     Disable rule
    GET  /v1/rewards/actions                List action payloads
    GET  /v1/rewards/actions/{id}           Get action payload
    POST /v1/rewards/actions/{id}/approve   Approve pending action
    POST /v1/rewards/actions/{id}/reject    Reject pending action
    POST /v1/rewards/actions/{id}/deliver   Deliver action payload
    POST /v1/rewards/actions/{id}/cancel    Cancel action
    GET  /v1/rewards/proofs                 List on-chain proofs
    GET  /v1/rewards/proofs/{id}            Get proof
    POST /v1/rewards/proofs/{id}/revoke     Revoke proof
    POST /v1/rewards/proofs/verify          Verify proof
    POST /v1/rewards/receipts               Record execution receipt
    GET  /v1/rewards/receipts               List receipts
    GET  /v1/rewards/receipts/{id}          Get receipt
    POST /v1/rewards/rails                  Configure delivery rail
    GET  /v1/rewards/rails                  List configured rails
    GET  /v1/rewards/rails/{id}             Get rail config
    PATCH /v1/rewards/rails/{id}            Update rail config
    POST /v1/rewards/rails/{id}/verify      Verify rail config
    POST /v1/rewards/rails/{id}/disable     Disable rail
    GET  /v1/rewards/queue/stats            Legacy queue stats
    POST /v1/oracle/proof/generate      Generate proof (internal)
    POST /v1/oracle/proof/verify        Verify proof
    GET  /v1/oracle/signer              Oracle signer info
    GET  /v1/oracle/config              Oracle configuration
    POST /v1/automation/ingest          Automation pipeline ingest
    GET  /v1/automation/metrics/{id}    Campaign metrics
    GET  /v1/automation/overview        Platform overview
    GET  /v1/automation/insights        Automated insights
    POST /v1/automation/report/{id}     Campaign report
    GET  /v1/diagnostics/health          Diagnostics health check
    GET  /v1/diagnostics/errors          List tracked errors
    GET  /v1/diagnostics/report          Diagnostics report
    POST /v1/diagnostics/errors/{fp}/resolve   Resolve error
    POST /v1/diagnostics/errors/{fp}/suppress  Suppress error
    GET  /v1/diagnostics/circuit-breakers      Circuit breaker states
    GET  /v1/conversions                       List canonical conversions
    GET  /v1/conversions/{id}/attribution      Conversion attribution run + credits
    GET  /v1/journeys/{id}                     Active journey version
    GET  /v1/attribution/runs                  List attribution runs
    POST /v1/attribution/runs                  Trigger attribution run
    POST /v1/attribution/backfills             Schedule attribution backfill
    GET  /v1/spend                             List spend records
    POST /v1/spend/imports                     Manual spend import
    GET  /v1/measurement/overview              Measurement quality overview
    GET  /v1/measurement/health                Connector health statuses
    GET  /v1/kyber/measurement/overview        Operator measurement overview
    POST /v1/kyber/measurement/tenants/{id}/recompute-all  Recompute all conversions
    POST /v1/providers/keys                    Store BYOK key
    GET  /v1/providers/keys                    List BYOK keys (masked)
    DELETE /v1/providers/keys/{provider}       Delete BYOK key
    GET  /v1/providers/usage                   Provider usage stats
    GET  /v1/providers/usage/summary           Tenant usage summary
    GET  /v1/providers/health                  Provider health + circuit breakers
    GET  /v1/providers/categories              List provider categories
    POST /v1/providers/test                    Test a provider call
"""

from __future__ import annotations

import asyncio
import sys
import os
from contextlib import asynccontextmanager
from typing import AsyncGenerator

# Ensure project root and repo root are on sys.path
sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config.settings import settings
from dependencies.providers import get_registry
from middleware.middleware import register_middleware
from shared.logger.logger import get_logger

logger = get_logger("aether.main")

# Import all service routers
from services.gateway.routes import router as gateway_router
from services.ingestion.routes import router as ingestion_router
from services.ingestion.batch import router as batch_router
from services.identity.routes import router as identity_router
from services.identity.reconciliation_routes import router as identity_reconciliation_router
from services.analytics.routes import router as analytics_router
from services.ml_serving.routes import router as ml_router
from services.ml_serving.kyber_ml_admin import router as kyber_ml_admin_router
from services.campaign.routes import router as campaign_router, sources_router as campaign_sources_router, mapping_router as campaign_mapping_router, quality_router as campaign_quality_router
from services.comms.routes import router as comms_router, admin_router as comms_admin_router
from services.economic.routes import router as economic_router
from services.consent.routes import router as consent_router
from services.notification_intelligence.routes import router as notification_router
from services.jobs.routes import router as jobs_router
from services.jobs.kyber_routes import router as jobs_kyber_router
from services.export import register_export_handlers
from services.export.routes import router as exports_router
from services.admin.routes import router as admin_router
from services.traffic.routes import router as traffic_router
from services.fraud.routes import router as fraud_router
from services.attribution.routes import router as attribution_router
from services.rewards.routes import router as rewards_router
from services.oracle.routes import router as oracle_router
from services.analytics_automation.routes import router as automation_router
from services.diagnostics.routes import router as diagnostics_router, commerce_diagnostics_router
from services.providers.routes import router as providers_router
from services.capabilities.routes import router as capabilities_router
from services.lake.routes import router as lake_router
from services.intelligence.routes import kyber_admin_router, router as intelligence_router
from services.intelligence.customer_success import admin_router as customer_success_admin_router, tenant_router as value_review_router
from services.intelligence.extraction_intel import router as extraction_intel_router
from services.profile.routes import router as profile_router, profile360_router
from services.reconciliation.coverage_routes import router as sdk_coverage_router
from services.population.routes import router as population_router
from services.semantic_intelligence.routes import (
    campaign_router as campaign_semantic_router,
    graph_router as graph_semantic_router,
    kyber_router as kyber_semantic_router,
    population_router as population_semantic_router,
    router as semantic_intelligence_router,
)
from services.expectations.routes import router as expectations_router
from services.behavioral.routes import router as behavioral_router
from services.rwa.routes import router as rwa_router
from services.web3.routes import router as web3_router
from services.crossdomain.routes import router as crossdomain_router
from services.agent.teams_routes import router as agent_teams_router
from services.agent.feedback_routes import router as agent_feedback_router
from services.agent.scoring_routes import router as scoring_router
from services.diagnostics.queue_routes import router as diagnostics_queue_router
from services.diagnostics.observability_routes import router as diagnostics_observability_router
from services.diagnostics.guardrails_routes import router as guardrails_router
from services.consent.audit_routes import router as audit_router
from services.admin.billing_subscription_routes import router as admin_billing_subscription_router
from services.admin.webhook_routes import router as stripe_webhook_router
from services.registration.routes import router as registration_router
from services.me.routes import router as me_router
from services.billing.routes import router as billing_router, admin_overage_router, kyber_revops_router
from services.auth.routes import router as auth_router, admin_auth_router
from services.contact.routes import router as contact_router
from services.recommendations.routes import router as recommendations_router
from services.notification.routes import router as notification_alerts_router
from services.pnl.routes import router as pnl_router
from services.resolution.routes import router as resolution_router
from services.signals.routes import router as signals_router
from services.social.routes import router as social_router
from services.geo.routes import router as geo_router

# Profile 360 (additive — multi-entity identity, delegation, flows, behavior, realtime)
from services.entities.routes import router as entities_router
from services.delegation.routes import router as delegation_router
from services.flows.routes import router as flows_router
from services.behavior.routes import router as behavior_router
from services.agent.user_agents import router as user_agents_router
from services.realtime.routes import router as realtime_router
from services.operational_intelligence.routes import router as operational_graph_router
from services.entity_intelligence.routes import router as entity_intelligence_router
from services.profile360_workers import attach_profile360_workers
from services.investigation.routes import router as investigation_router
from services.governance.routes import router as governance_router
from services.security.routes import router as security_router
from services.security.admin_routes import admin_router as security_admin_router
from services.policy.routes import router as policy_router
from services.dsr_propagation.routes import router as dsr_propagation_router
from services.tenant_readiness.routes import router as tenant_readiness_router
from services.metering_evidence.routes import router as metering_evidence_router
from services.events.routes import router as events_router
from services.sdk.routes import router as sdk_router
from services.journeys.routes import router as journeys_router, admin_router as journey_health_router
from services.sdk_health.routes import router as sdk_health_router
from services.sdk_drift.routes import router as sdk_drift_router
from services.sdk_config.routes import router as sdk_config_router
from services.noesis.routes import router as noesis_router
from services.onboarding.routes import router as onboarding_router, admin_router as onboarding_admin_router
from services.reliability import admin_router as reliability_admin_router, tenant_router as reliability_status_router
from services.data_quality import (
    admin_router as data_quality_admin_router,
    tenant_router as data_quality_tenant_router,
)

from services.kyber_operator.routes import router as kyber_operator_router
from services.cluster.routes import router as cluster_router

# Canonical Measurement (conversions, journeys, attribution, spend, quality, ops, experiments)
from services.measurement.routes.conversions import router as measurement_conversions_router
from services.measurement.routes.journeys import router as measurement_journeys_router, web3_router as measurement_web3_router
from services.measurement.routes.attribution import router as measurement_attribution_router
from services.measurement.routes.spend import router as measurement_spend_router
from services.measurement.routes.quality import router as measurement_quality_router
from services.measurement.routes.kyber import router as measurement_kyber_router
from services.measurement.routes.integrity import router as measurement_integrity_router
from services.measurement.routes.experiments import router as measurement_experiments_router
from services.imports.routes import router as imports_router
from services.imports.kyber_routes import router as imports_kyber_router

# ML predict routes — imported from the ML serving package when available.
# When ML_SERVING_INLINE=true (E2 consolidated image) the predict routes are
# served in-process. When unset/false the httpx proxy (ml_router above) handles
# them and the try-block below is a no-op.
_ml_predict_router = None
_ml_startup_fn = None
try:
    if os.getenv("ML_SERVING_INLINE", "false").lower() == "true":
        from serving.src.api import router as _ml_predict_router, startup_ml as _ml_startup_fn
except ImportError:
    pass


# ═══════════════════════════════════════════════════════════════════════
# LIFESPAN — startup / shutdown hooks
# ═══════════════════════════════════════════════════════════════════════

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """
    Manages the full lifecycle of shared resources:
      - startup:  connect cache, graph DB, event producer; wire consumer
                  attachments; start supervised background workers
      - shutdown: stop all supervised workers, gracefully close connections
    """
    from config.settings import Environment
    from services.runtime import WorkerSupervisor, build_worker_specs
    from services.runtime.roles import should_start_consumers, should_start_workers

    # Runtime-role gating (PR 4 / FT-4). With WORKER_ROLES_ENABLED off, both
    # gates are True → this lifespan is byte-identical to before. With it on, a
    # pure "api" process starts neither the stream consumers nor the supervised
    # workers — those run in dedicated role processes via
    # `python -m services.runtime.run_role <role>`; the "all" role still starts
    # everything.
    _role = settings.runtime.aether_role
    _roles_gated = settings.runtime.worker_roles_enabled
    _start_consumers = (not _roles_gated) or should_start_consumers(_role)
    _start_workers = (not _roles_gated) or should_start_workers(_role)

    registry = get_registry()
    await registry.startup()

    # Announce ML model artifacts when running inline (E2 consolidated image).
    if _ml_startup_fn is not None:
        _ml_startup_fn()

    # Consumer-attach wiring is fail-closed in staging/production: a broken
    # attachment means silently dropped events, so abort startup there.
    # Local/dev keep the historical warn-and-continue behaviour.
    _attach_fail_closed = settings.env in (Environment.STAGING, Environment.PRODUCTION)

    def _attach_step(label: str, attach_fn) -> None:
        try:
            attach_fn()
        except Exception as e:
            if _attach_fail_closed:
                logger.error(f"{label} wiring failed: {e}")
                raise RuntimeError(
                    f"{label} wiring failed in {settings.env.value}"
                ) from e
            logger.warning(f"{label} wiring skipped: {e}")

    # Consumer-attach wiring + stream-consumer start. Gated by runtime role:
    # skipped entirely for a pure "api" process (whose events are produced and
    # handled by dedicated worker-role processes). Flag off → _start_consumers
    # True → identical to before.
    if _start_consumers:
        # Ingestion workers — sdk_bronze_writer, silver_normalizer, identity_signal_emitter
        def _attach_ingestion() -> None:
            from services.ingestion.workers import attach_ingestion_workers
            attach_ingestion_workers(registry.consumer, registry.producer)
        _attach_step("Ingestion worker", _attach_ingestion)

        # Profile 360 — attach derived workers to the shared consumer.
        # Strictly additive: workers consume new topics + a few existing ones,
        # write to new tables only, and never mutate existing service state.
        _attach_step(
            "Profile 360 worker",
            lambda: attach_profile360_workers(registry.consumer, registry.graph),
        )

        # Measurement — identity change → journey rebuild → attribution recompute
        def _attach_measurement_identity() -> None:
            from services.measurement.identity_consumer import MeasurementIdentityConsumer
            MeasurementIdentityConsumer(producer=registry.producer).register(registry.consumer)
        _attach_step("Measurement identity consumer", _attach_measurement_identity)

    # Measurement — register algorithmic attribution models (markov, shapley_heuristic).
    # Model registration also serves API attribution queries, so it is
    # unconditional (independent of the stream-consumer role gate).
    try:
        from services.measurement.engine.algorithmic_attribution import register_algorithmic_models
        from services.attribution.resolver import AttributionResolver, AttributionConfig
        _resolver = AttributionResolver(AttributionConfig())
        register_algorithmic_models(_resolver)
        app.state.algorithmic_attribution_resolver = _resolver
    except Exception as e:  # pragma: no cover — defensive
        logger.warning(f"Algorithmic attribution model registration skipped: {e}")

    if _start_consumers:
        # Notification Intelligence — attach Kafka consumers.
        def _attach_notification_intelligence() -> None:
            from services.notification_intelligence.consumer import attach_notification_consumers
            attach_notification_consumers(
                registry.consumer,
                producer=registry.producer,
                cache=registry.cache,
            )
        _attach_step("Notification intelligence consumer", _attach_notification_intelligence)

        try:
            await registry.consumer.start()
        except Exception as e:  # pragma: no cover — defensive
            logger.warning(f"Kafka consumer start skipped: {e}")

    # Provider Gateway (feature-flagged)
    from dependencies.providers import _init_provider_gateway
    provider_gateway = _init_provider_gateway()
    if provider_gateway:
        await provider_gateway.startup()
        app.state.provider_gateway = provider_gateway
        logger.info("Provider Gateway initialised")

    # Noesis startup validation
    try:
        from services.noesis.startup import NoesisStartupValidator
        noesis_errors = NoesisStartupValidator().validate()
        if noesis_errors:
            for err in noesis_errors:
                logger.error("Noesis startup validation failed: %s", err)
            raise RuntimeError(f"Noesis startup validation failed: {'; '.join(noesis_errors)}")
    except ImportError:
        pass  # Noesis module not present in this build

    # Job handlers must be registered before the supervised job worker starts
    # claiming, or already-enqueued export jobs would fail as unknown types.
    register_export_handlers()
    from services.imports.commit import register_import_handlers

    register_import_handlers()  # import.commit / import.replay

    # Supervised long-running loop workers: event replay, billing overage
    # cron, notification SLA expiry, Dune polling (canonical scheduler only —
    # the legacy services.integrations.dune_feeder loop is no longer started),
    # retention sweep, delivery worker, and webhook inbox processor.
    # Crash → log + metric + exponential-backoff restart; required workers
    # abort startup in staging/production if their first start fails.
    # Gated by runtime role: a pure "api" process starts no supervised workers
    # (they run in dedicated role processes via run_role). Flag off →
    # _start_workers True → identical to before.
    supervisor: WorkerSupervisor | None = None
    if _start_workers:
        supervisor = WorkerSupervisor()
        for spec in build_worker_specs(registry=registry, settings=settings):
            supervisor.register(spec)
        app.state.worker_supervisor = supervisor
        await supervisor.start_all()

    logger.info(
        f"Aether Backend started | env={settings.env.value} "
        f"| debug={settings.debug} | version={settings.api.version}"
    )

    yield  # --- app runs here ---

    # Graceful shutdown: stop workers, drain connections, close backends
    logger.info("Initiating graceful shutdown...")
    if supervisor is not None:
        await supervisor.stop_all()
    if provider_gateway:
        await provider_gateway.shutdown()
    await registry.shutdown()
    logger.info("Aether Backend shut down gracefully")


# ═══════════════════════════════════════════════════════════════════════
# APP FACTORY
# ═══════════════════════════════════════════════════════════════════════

def create_app() -> FastAPI:
    _docs = None if settings.is_production else "/docs"
    _redoc = None if settings.is_production else "/redoc"
    app = FastAPI(
        title=settings.api.title,
        description=settings.api.description,
        version=settings.api.version,
        docs_url=_docs,
        redoc_url=_redoc,
        lifespan=lifespan,
    )

    # ── CORS ──────────────────────────────────────────────────────
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.api.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-API-Key", "X-Request-ID", "X-Correlation-ID", "X-Kyber-Environment"],
        expose_headers=[
            "X-Request-ID",
            "X-Response-Time",
            "X-RateLimit-Limit",
            "X-RateLimit-Remaining",
            "X-RateLimit-Reset",
            "X-Access-Tier",
            "X-Quota-Limit",
            "X-Quota-Used",
            "X-Quota-Remaining",
            "X-Quota-Reset",
            "X-Quota-Overage",
        ],
    )

    # ── Auth / Logging / Rate Limit / Error Handling Middleware ────
    register_middleware(app)

    # ── Mount all 17 core service routers ──────────────────────────
    app.include_router(gateway_router)
    app.include_router(batch_router)      # POST /v1/batch — canonical SDK ingestion
    app.include_router(ingestion_router)  # POST /v1/ingest/feed (server-side feed)
    app.include_router(identity_router)
    app.include_router(identity_reconciliation_router)
    app.include_router(analytics_router)
    app.include_router(ml_router)
    app.include_router(kyber_ml_admin_router)  # Kyber ML command center admin hooks
    app.include_router(campaign_router)
    app.include_router(campaign_sources_router)   # /v1/campaign-sources
    app.include_router(campaign_mapping_router)   # /v1/mapping-review
    app.include_router(campaign_quality_router)   # /v1/campaign-quality
    app.include_router(comms_router)              # /v1/comms — webhook, replies, click tokens, health
    app.include_router(comms_admin_router)        # /v1/comms/admin — Kyber comms fleet health
    app.include_router(economic_router)
    app.include_router(consent_router)
    app.include_router(notification_router)
    app.include_router(jobs_router)          # /v1/jobs — durable job control plane
    app.include_router(jobs_kyber_router)    # /v1/kyber/jobs — operator job timeline
    app.include_router(exports_router)       # /v1/exports — durable artifact exports
    app.include_router(admin_router)
    app.include_router(traffic_router)
    app.include_router(fraud_router)
    app.include_router(attribution_router)
    app.include_router(rewards_router)
    app.include_router(oracle_router)
    app.include_router(automation_router)
    app.include_router(diagnostics_router)
    app.include_router(commerce_diagnostics_router)
    app.include_router(providers_router)
    app.include_router(capabilities_router)
    app.include_router(lake_router)
    app.include_router(intelligence_router)
    app.include_router(kyber_admin_router)
    app.include_router(kyber_operator_router)
    app.include_router(customer_success_admin_router)
    app.include_router(value_review_router)
    app.include_router(extraction_intel_router)
    # pnl_router and social_router define /v1/profile/{id}/pnl and
    # /v1/profile/{id}/social-intelligence with richer responses than
    # profile_router's handlers; mount them first so FastAPI matches them.
    app.include_router(pnl_router)
    app.include_router(social_router)
    app.include_router(profile_router)
    app.include_router(profile360_router)
    app.include_router(sdk_coverage_router)
    app.include_router(population_router)
    app.include_router(semantic_intelligence_router)
    app.include_router(kyber_semantic_router)
    app.include_router(campaign_semantic_router)
    app.include_router(graph_semantic_router)
    app.include_router(population_semantic_router)
    app.include_router(expectations_router)
    app.include_router(behavioral_router)
    app.include_router(rwa_router)
    app.include_router(web3_router)
    app.include_router(crossdomain_router)
    # agent sub-routers are only mounted when agent layer is enabled (see below)
    app.include_router(diagnostics_queue_router)
    app.include_router(diagnostics_observability_router)
    app.include_router(guardrails_router)
    app.include_router(audit_router)
    app.include_router(admin_billing_subscription_router)
    app.include_router(stripe_webhook_router)
    app.include_router(registration_router)
    app.include_router(me_router)
    app.include_router(billing_router)
    app.include_router(admin_overage_router)
    app.include_router(kyber_revops_router)
    app.include_router(auth_router)
    app.include_router(admin_auth_router)
    app.include_router(contact_router)
    app.include_router(recommendations_router)
    app.include_router(notification_alerts_router)
    app.include_router(resolution_router)
    app.include_router(signals_router)
    app.include_router(geo_router)

    # ── Profile 360 (additive) ─────────────────────────────────────────
    app.include_router(entities_router)
    app.include_router(delegation_router)
    app.include_router(flows_router)
    app.include_router(behavior_router)
    app.include_router(realtime_router)
    app.include_router(operational_graph_router)
    app.include_router(entity_intelligence_router)
    app.include_router(cluster_router)         # Cluster360: /v1/clusters
    app.include_router(investigation_router)
    app.include_router(governance_router)
    app.include_router(security_router)
    app.include_router(security_admin_router)
    app.include_router(policy_router)
    app.include_router(dsr_propagation_router)     # /v1/dsr — DSR propagation records + impact indexes
    app.include_router(tenant_readiness_router)    # /v1/tenant/readiness — launch readiness + trust states
    app.include_router(metering_evidence_router)   # /v1/metering/evidence — usage metering evidence
    app.include_router(events_router)
    app.include_router(user_agents_router)  # Profile 360: user/org-owned agents (always-on)
    app.include_router(sdk_router)          # SDK utilities: cross-device identity resolution
    app.include_router(journeys_router)     # Cross-device journey continuity APIs
    app.include_router(journey_health_router) # Kyber journey health diagnostics

    # ── Canonical Measurement domain ──────────────────────────────────────
    # Per-conversion attribution, durable journeys, spend ledger, ROAS, quality
    app.include_router(measurement_conversions_router)   # GET/POST /v1/conversions
    app.include_router(measurement_journeys_router)      # GET/POST /v1/journeys
    app.include_router(measurement_web3_router)          # POST /v1/web3/status-change
    app.include_router(measurement_attribution_router)   # GET/POST /v1/attribution/runs|backfills|configurations|models
    app.include_router(measurement_spend_router)         # GET/POST /v1/spend
    app.include_router(measurement_quality_router)       # GET /v1/measurement/*
    app.include_router(measurement_integrity_router)     # GET /v1/measurement/definitions|results|results/{id}/explain
    app.include_router(measurement_kyber_router)         # GET/POST /v1/kyber/measurement/*
    app.include_router(measurement_experiments_router)   # GET/POST /v1/experiments
    logger.info("Canonical Measurement: 6 routers mounted")
    app.include_router(imports_router)                   # /v1/imports: upload/analyze/map/validate/templates
    app.include_router(imports_kyber_router)             # /v1/kyber/imports: operator timeline/detail/requeue
    app.include_router(sdk_health_router)   # SDK health monitoring: heartbeats + fleet status
    app.include_router(sdk_drift_router)    # SDK drift detection: schema, stale, replay storm
    app.include_router(sdk_config_router)   # SDK remote config: signed manifests + rollouts
    app.include_router(noesis_router)        # Noesis: graph-native natural-language intelligence
    app.include_router(onboarding_router)      # Customer onboarding center
    app.include_router(onboarding_admin_router) # Kyber implementation lifecycle
    app.include_router(reliability_admin_router)  # Kyber reliability command center
    app.include_router(reliability_status_router) # Tenant-safe system status

    # ── ML serving inline (E2 consolidated image) ───────────────────────
    # When ML_SERVING_INLINE=true the predict routes are handled in-process
    # rather than proxied by the ml_router httpx client above.
    if _ml_predict_router is not None:
        app.include_router(_ml_predict_router)
        logger.info("ML serving routes mounted inline (E2)")

    # ── Intelligence Graph services (feature-flagged) ───────────
    ig = settings.intelligence_graph

    if ig.enable_agent_layer:
        from services.agent.routes import router as agent_router
        app.include_router(agent_router)
        app.include_router(agent_teams_router)
        app.include_router(agent_feedback_router)
        app.include_router(scoring_router)
        logger.info("Intelligence Graph: Agent layer (L2) mounted")
    else:
        logger.info(
            "Intelligence Graph: Agent layer disabled (set IG_AGENT_LAYER=true to enable)"
        )

    if ig.enable_commerce_layer:
        from services.commerce.routes import router as commerce_router
        app.include_router(commerce_router)
        logger.info("Intelligence Graph: Commerce service (L3a) mounted")

    if ig.enable_onchain_layer:
        from services.onchain.routes import router as onchain_router
        app.include_router(onchain_router)
        logger.info("Intelligence Graph: On-Chain Action service (L0) mounted")

    # ── Cognitive Integrity System (feature-flagged) ────────────────────
    if settings.cis.enabled:
        from services.cis.routes import router as cis_router
        app.include_router(cis_router)
        logger.info("Cognitive Integrity System (CIS) routes mounted")

    # ── Data Quality / Intelligence Quality (feature-flagged) ───────────
    dq = settings.data_quality
    if dq.enabled:
        app.include_router(data_quality_tenant_router)
        logger.info("Data Quality: tenant routes mounted (/v1/data-quality)")
    else:
        logger.info("Data Quality: tenant routes disabled (set AETHER_DATA_QUALITY_ENABLED=true)")
    if dq.kyber_intelligence_quality_enabled:
        app.include_router(data_quality_admin_router)
        logger.info("Intelligence Quality: Kyber admin routes mounted (/v1/admin/kyber/intelligence-quality)")

    # ── Dune Analytics feeder (admin-only, always mounted) ──────────────
    from services.dune_feeder.routes import router as dune_feeder_router
    app.include_router(dune_feeder_router)
    logger.info("Dune feeder: admin routes mounted (/v1/admin/dune-feeder)")

    # ── Provider Source Catalog (Kyber admin, feature-flagged) ─────────
    pc = settings.provider_corpus
    if pc.kyber_provider_source_catalog_enabled:
        from services.provider_catalog.routes import (
            providers_router as kyber_providers_router,
            dune_router as kyber_dune_router,
            lake_router as kyber_lake_router,
            features_router as kyber_features_router,
            intelligence_router as kyber_intelligence_router,
        )
        app.include_router(kyber_providers_router)
        app.include_router(kyber_dune_router)
        app.include_router(kyber_lake_router)
        app.include_router(kyber_features_router)
        app.include_router(kyber_intelligence_router)
        logger.info("Provider Source Catalog: Kyber admin routes mounted (/v1/admin/kyber/providers + /dune + /lake + /features + /intelligence)")
    else:
        logger.info("Provider Source Catalog: disabled (set KYBER_PROVIDER_SOURCE_CATALOG_ENABLED=true to enable)")

    # ── Data Rights Ledger (feature-flagged) ───────────────────────────
    if pc.connector_data_rights_enabled:
        from services.integrations.data_rights.routes import (
            router as data_rights_router,
            admin_router as data_rights_admin_router,
        )
        app.include_router(data_rights_router)
        app.include_router(data_rights_admin_router)
        logger.info("Data Rights Ledger: routes mounted (/v1/integrations/data-rights + /v1/admin/kyber/data-rights)")
    else:
        logger.info("Data Rights Ledger: disabled (set AETHER_CONNECTOR_DATA_RIGHTS_ENABLED=true to enable)")

    # ── Inbound connector ingestion (feature-flagged, master switch) ────
    if settings.connectors.enabled:
        from services.integrations.connectors import (
            admin_router as connectors_admin_router,
            router as connectors_router,
        )
        from services.integrations.connectors.routes import webhook_public_router, slack_notify_router
        app.include_router(connectors_router)
        # Public webhook route always mounted when connectors are enabled;
        # security is enforced by HMAC verification inside the handler.
        app.include_router(webhook_public_router)
        app.include_router(slack_notify_router)
        if settings.connectors.kyber_connector_health_enabled:
            app.include_router(connectors_admin_router)
        logger.info("Connectors: ingestion routes mounted (/v1/integrations/connectors + /v1/integrations/webhooks + /v1/integrations/slack-notify)")
    else:
        logger.info("Connectors: disabled (set AETHER_CONNECTORS_ENABLED=true to enable)")

    if ig.enable_x402_layer:
        from services.x402.routes import router as x402_router
        from services.x402.challenge_middleware import register_challenge_middleware
        app.include_router(x402_router)
        register_challenge_middleware(app)
        logger.info("Intelligence Graph: x402 Interceptor service (L3b) mounted")

        # Agentic Commerce control plane (L3b+) — mounted alongside legacy capture.
        from services.x402.commerce_routes import (
            router as commerce_cp_router,
            approvals_router,
            entitlements_router,
            diagnostics_router as commerce_diag_router,
        )
        app.include_router(commerce_cp_router)
        app.include_router(approvals_router)
        app.include_router(entitlements_router)
        app.include_router(commerce_diag_router)
        logger.info("Intelligence Graph: Agentic Commerce control plane (L3b+) mounted")

    # ── Suggestion Intelligence (OODA) ────────────────────────────────────
    sug = settings.suggestions
    if sug.enabled:
        from services.suggestions.routes import (
            router as suggestions_router,
            admin_router as suggestions_admin_router,
            aether_router as suggestions_aether_router,
        )
        app.include_router(suggestions_router)
        if sug.kyber_enabled:
            app.include_router(suggestions_admin_router)
        if sug.tenant_enabled:
            app.include_router(suggestions_aether_router)
        logger.info("Suggestion Intelligence: routes mounted (/v1/suggestions + /v1/admin/kyber/suggestions + /v1/aether/suggestions)")
    else:
        logger.info("Suggestion Intelligence: disabled (set AETHER_SUGGESTIONS_ENABLED=true to enable)")

    # ── Fraud Network Intelligence + Flow-of-Funds (feature-flagged) ────
    fi = settings.fraud_intelligence
    if fi.fraud_networks_enabled:
        from services.fraud_networks.routes import router as fraud_networks_router
        app.include_router(fraud_networks_router)
        logger.info("Fraud Network Intelligence: routes mounted (/v1/fraud/networks)")
    else:
        logger.info("Fraud Network Intelligence: disabled (set FEATURE_FRAUD_NETWORKS=true to enable)")

    if fi.flow_trace_enabled:
        from services.flow_trace.routes import router as flow_trace_router
        app.include_router(flow_trace_router)
        logger.info("Flow-of-Funds Trace: routes mounted (/v1/flow-trace)")
    else:
        logger.info("Flow-of-Funds Trace: disabled (set FEATURE_FLOW_TRACE=true to enable)")

    if fi.risk_overlays_enabled:
        from services.risk_overlay.routes import router as risk_overlay_router
        app.include_router(risk_overlay_router)
        logger.info("Risk Overlays: routes mounted (/v1/risk-overlays)")
    else:
        logger.info("Risk Overlays: disabled (set FEATURE_RISK_OVERLAYS=true to enable)")

    # Agentic Observability Layer — observation-only; AETHER never executes.
    agentic_flags = settings.agentic_observability
    if agentic_flags.enabled:
        from services.agentic_observability.routes import router as agentic_obs_router
        app.include_router(agentic_obs_router, tags=["Agentic Observability"])
        if agentic_flags.mcp_enabled:
            from services.agentic_observability.routes import mcp_router as agentic_mcp_router
            app.include_router(agentic_mcp_router, tags=["Agentic MCP Observability"])
        if agentic_flags.protocol_enabled:
            from services.protocol_observability.routes import router as protocol_obs_router
            app.include_router(protocol_obs_router, tags=["Protocol Observability"])
        if agentic_flags.communication_enabled:
            from services.agent_comm_observability.routes import router as comm_obs_router
            app.include_router(comm_obs_router, tags=["Agent Comm Observability"])
        if agentic_flags.external_accounts_enabled:
            from services.external_account_observability.routes import router as ext_account_obs_router
            app.include_router(ext_account_obs_router, tags=["External Account Observability"])
        logger.info("Agentic Observability Layer mounted according to AGENTIC_* feature flags")
    else:
        logger.info("Agentic Observability Layer disabled (AGENTIC_OBSERVABILITY_ENABLED=false)")

    # ── Delivery API (durable provider dispatch + outcome tracking) ──────
    try:
        from services.delivery.routes import router as delivery_router, admin_router as delivery_admin_router
        app.include_router(delivery_router)
        app.include_router(delivery_admin_router)
        logger.info("Delivery: routes mounted (/v1/delivery + /v1/admin/delivery)")
    except Exception as e:  # pragma: no cover — defensive
        logger.warning(f"Delivery routes mount skipped: {e}")

    # ── Stablecoin Intelligence (feature-flagged, all surfaces off by default) ──
    try:
        from services.stablecoins.routes import (
            router as stablecoin_router,
            kyber_router as stablecoin_kyber_router,
            profile_router as stablecoin_profile_router,
        )
        app.include_router(stablecoin_router)
        app.include_router(stablecoin_kyber_router)
        app.include_router(stablecoin_profile_router)
        logger.info("Stablecoin Intelligence: routes mounted (/v1/stablecoin + /v1/admin/kyber/stablecoin + profile360)")
    except Exception as e:  # pragma: no cover — defensive
        logger.warning(f"Stablecoin Intelligence routes mount skipped: {e}")

    # ── Derivatives Intelligence (observation-only product surfaces) ──
    try:
        from services.derivatives.routes import router as derivatives_router, kyber_router as derivatives_kyber_router
        app.include_router(derivatives_router)
        app.include_router(derivatives_kyber_router)
        logger.info("Derivatives Intelligence: routes mounted (/v1/derivatives + /v1/admin/kyber/derivatives)")
    except Exception as e:  # pragma: no cover — defensive
        logger.warning(f"Derivatives Intelligence routes mount skipped: {e}")

    # ── Payment Rail Observability (named providers only; observation-only) ──
    rails_flags = settings.payment_rails
    if rails_flags.enabled:
        from services.integrations.providers.payment_rails.routes import (
            router as payment_rails_router,
            webhook_router as payment_rails_webhook_router,
        )
        app.include_router(payment_rails_router)
        app.include_router(payment_rails_webhook_router)
        logger.info(
            "Payment Rails: routes mounted (/v1/integrations/providers + "
            "/v1/integrations/webhooks/payment-rails)"
        )
    if rails_flags.enabled or rails_flags.kyber_enabled:
        from services.integrations.providers.payment_rails.kyber_routes import (
            kyber_router as payment_rails_kyber_router,
        )
        app.include_router(payment_rails_kyber_router)
        logger.info("Payment Rails: Kyber diagnostics mounted (/v1/admin/kyber/payment-rails)")
    if not (rails_flags.enabled or rails_flags.kyber_enabled):
        logger.info("Payment Rails: disabled (AETHER_PAYMENT_RAILS_ENABLED=false)")

    # ── Card-Linked Payment Rails (observation-only; nested under payment rails) ──
    card_linked_flags = settings.card_linked_payment_rails
    if card_linked_flags.enabled:
        from services.card_linked_payments.routes import router as card_linked_router
        app.include_router(card_linked_router)
        logger.info(
            "Card-Linked Payment Rails: routes mounted "
            "(/v1/integrations/providers/payment-rails/card-linked)"
        )
    if card_linked_flags.enabled or card_linked_flags.kyber_enabled:
        from services.card_linked_payments.kyber_routes import card_linked_kyber_router
        app.include_router(card_linked_kyber_router)
        logger.info(
            "Card-Linked Payment Rails: Kyber diagnostics mounted "
            "(/v1/admin/kyber/payment-rails/card-linked)"
        )
    if not (card_linked_flags.enabled or card_linked_flags.kyber_enabled):
        logger.info(
            "Card-Linked Payment Rails: disabled "
            "(AETHER_CARD_LINKED_PAYMENT_RAILS_ENABLED=false)"
        )

    # ── AI Outcome Efficiency / AI Economics (observe + recommend; never executes changes) ──
    ai_econ_flags = settings.ai_economics
    if ai_econ_flags.enabled:
        from services.economic.ai_routes import ai_router as ai_economics_router
        app.include_router(ai_economics_router)
        logger.info("AI Economics: routes mounted (/v1/economic/ai)")
    if ai_econ_flags.enabled or ai_econ_flags.kyber_enabled:
        from services.economic.ai_routes import kyber_router as ai_efficiency_kyber_router
        app.include_router(ai_efficiency_kyber_router)
        logger.info("AI Economics: Kyber health mounted (/v1/admin/kyber/ai-efficiency)")
    if not (ai_econ_flags.enabled or ai_econ_flags.kyber_enabled):
        logger.info("AI Economics: disabled (AETHER_AI_OUTCOME_EFFICIENCY_ENABLED=false)")

    # ── Cluster Targeting Intelligence (observation-first; never executes campaigns) ──
    targeting_flags = settings.targeting_intelligence
    if targeting_flags.enabled:
        from services.targeting_intelligence.routes import (
            router as targeting_router,
            scoped_router as targeting_scoped_router,
        )
        app.include_router(targeting_router)
        app.include_router(targeting_scoped_router)
        logger.info(
            "Targeting Intelligence: routes mounted (/v1/targeting-intelligence + "
            "campaign/cluster scoped reads)"
        )
    if targeting_flags.enabled or targeting_flags.kyber_enabled:
        from services.targeting_intelligence.kyber_routes import (
            kyber_router as targeting_kyber_router,
        )
        app.include_router(targeting_kyber_router)
        logger.info("Targeting Intelligence: Kyber routes mounted (/v1/admin/kyber/targeting)")
    if not (targeting_flags.enabled or targeting_flags.kyber_enabled):
        logger.info(
            "Targeting Intelligence: disabled "
            "(AETHER_CLUSTER_TARGETING_INTELLIGENCE_ENABLED=false)"
        )

    # ── External Agent Telemetry Plane (observation-only; no marketplace, no execution) ──
    telemetry_flags = settings.external_agent_telemetry
    if telemetry_flags.registry_enabled:
        from services.agent.deployment_routes import deployments_router
        app.include_router(deployments_router)
        logger.info("External Agent Telemetry: deployment registry mounted (/v1/agent/deployments)")
    if telemetry_flags.kyber_enabled:
        from services.agent.deployment_routes import kyber_router as agent_telemetry_kyber_router
        app.include_router(agent_telemetry_kyber_router)
        logger.info("External Agent Telemetry: Kyber diagnostics mounted (/v1/admin/kyber/agent-telemetry)")
    if not (telemetry_flags.registry_enabled or telemetry_flags.kyber_enabled):
        logger.info("External Agent Telemetry: disabled (AETHER_AGENT_DEPLOYMENT_REGISTRY_ENABLED=false)")

    # ── One-Person Ops runtime (worker bridge, briefings, ops alerts; approval gates never removed) ──
    ops_flags = settings.one_person_ops
    if ops_flags.worker_bridge_enabled:
        from services.agent.worker_routes import worker_router
        app.include_router(worker_router)
        logger.info("One-Person Ops: worker run routes mounted (/v1/agent/runs)")
    if ops_flags.one_person_ops_enabled or ops_flags.command_center_enabled:
        from services.agent.briefings import briefings_router
        from services.agent.ops_alerts import ops_router as agent_ops_router
        app.include_router(briefings_router)
        app.include_router(agent_ops_router)
        logger.info("One-Person Ops: briefings + ops alerts mounted (/v1/agent/briefings, /v1/agent/ops)")
    if not (
        ops_flags.worker_bridge_enabled
        or ops_flags.one_person_ops_enabled
        or ops_flags.command_center_enabled
    ):
        logger.info("One-Person Ops: disabled (KYBER_ONE_PERSON_OPS_ENABLED=false)")
    # ── Stablecoin Intelligence — observation-only; AETHER never executes ──
    if settings.stablecoin.api_enabled:
        from services.stablecoin.routes import router as stablecoin_router
        app.include_router(stablecoin_router, tags=["Stablecoin Intelligence"])
        logger.info("Stablecoin Intelligence API mounted (/v1/stablecoins)")
    else:
        logger.info("Stablecoin Intelligence API disabled (AETHER_STABLECOIN_API_ENABLED=false)")
    if settings.stablecoin.kyber_enabled:
        from services.stablecoin.admin_routes import admin_router as stablecoin_admin_router
        app.include_router(stablecoin_admin_router, tags=["Kyber Stablecoin Ops"])
        logger.info("Kyber Stablecoin Ops mounted (/v1/admin/kyber/stablecoins)")
    else:
        logger.info("Kyber Stablecoin Ops disabled (KYBER_STABLECOIN_OPS_ENABLED=false)")

    # ── Derivatives Intelligence — observation-only; no execution exists ───
    if settings.derivatives.api_enabled:
        from services.derivatives.runtime_routes import router as derivatives_router
        app.include_router(derivatives_router, tags=["Derivatives Intelligence"])
        logger.info("Derivatives Intelligence runtime API mounted (/v1/derivatives/runtime)")
    else:
        logger.info("Derivatives Intelligence API disabled (AETHER_DERIVATIVES_API_ENABLED=false)")
    if settings.derivatives.kyber_enabled:
        from services.derivatives.admin_routes import admin_router as derivatives_admin_router
        app.include_router(derivatives_admin_router, tags=["Kyber Derivatives Ops"])
        logger.info("Kyber Derivatives runtime Ops mounted (/v1/admin/kyber/derivatives/runtime)")
    else:
        logger.info("Kyber Derivatives Ops disabled (KYBER_DERIVATIVES_OPS_ENABLED=false)")

    # ── Interoperability Intelligence — observation-only; AETHER never
    #    relays, routes, or recovers cross-network messages ─────────────────
    if settings.interop.api_enabled:
        from services.interop.routes import router as interop_router
        app.include_router(interop_router, tags=["Interoperability Intelligence"])
        logger.info("Interoperability Intelligence API mounted (/v1/interoperability)")
    else:
        logger.info("Interoperability Intelligence API disabled (AETHER_INTEROP_API_ENABLED=false)")
    if settings.interop.kyber_enabled:
        from services.interop.admin_routes import admin_router as interop_admin_router
        app.include_router(interop_admin_router, tags=["Kyber Interop Ops"])
        logger.info("Kyber Interop Ops mounted (/v1/admin/kyber/interop)")
    else:
        logger.info("Kyber Interop Ops disabled (KYBER_INTEROP_OPS_ENABLED=false)")

    return app


app = create_app()


# ═══════════════════════════════════════════════════════════════════════
# ENTRYPOINT
# ═══════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.debug,
        log_level=settings.log_level.lower(),
    )
