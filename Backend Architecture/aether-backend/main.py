"""
Aether Backend — Main Application
Mounts 17 core services + up to 3 Intelligence Graph services (feature-flagged).
Applies middleware and serves the unified API.

Run:
    uvicorn main:app --reload --port 8000

Routes:
    GET  /                              Root
    GET  /v1/health                     Health check (deep probe)
    GET  /v1/metrics                    Internal metrics
    POST /v1/ingest/events              Single SDK event
    POST /v1/ingest/events/batch        Batch SDK events
    POST /v1/ingest/feed                External API feed
    GET  /v1/identity/profiles/{id}     Get profile
    PUT  /v1/identity/profiles/{id}     Upsert profile
    POST /v1/identity/merge             Merge identities
    GET  /v1/identity/profiles/{id}/graph  Profile graph
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
    POST /v1/notifications/webhooks     Create webhook
    GET  /v1/notifications/webhooks     List webhooks
    DELETE /v1/notifications/webhooks/{id}  Delete webhook
    POST /v1/notifications/alerts       Create alert
    GET  /v1/notifications/alerts       List alerts
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
    POST /v1/rewards/evaluate           Evaluate reward eligibility
    POST /v1/rewards/campaigns          Create reward campaign
    GET  /v1/rewards/campaigns          List reward campaigns
    GET  /v1/rewards/campaigns/{id}     Get campaign details
    GET  /v1/rewards/queue/stats        Reward queue stats
    GET  /v1/rewards/user/{address}     User reward history
    POST /v1/rewards/process            Process reward queue
    GET  /v1/rewards/proof/{id}         Get reward proof
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

import sys
import os
from contextlib import asynccontextmanager
from typing import AsyncGenerator

# Ensure project root is on sys.path
sys.path.insert(0, os.path.dirname(__file__))

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
from services.identity.routes import router as identity_router
from services.analytics.routes import router as analytics_router
from services.ml_serving.routes import router as ml_router
from services.agent.routes import router as agent_router
from services.campaign.routes import router as campaign_router
from services.consent.routes import router as consent_router
from services.notification.routes import router as notification_router
from services.admin.routes import router as admin_router
from services.traffic.routes import router as traffic_router
from services.fraud.routes import router as fraud_router
from services.attribution.routes import router as attribution_router
from services.rewards.routes import router as rewards_router
from services.oracle.routes import router as oracle_router
from services.analytics_automation.routes import router as automation_router
from services.diagnostics.routes import router as diagnostics_router
from services.providers.routes import router as providers_router
from services.lake.routes import router as lake_router
from services.intelligence.routes import router as intelligence_router
from services.intelligence.extraction_intel import router as extraction_intel_router
from services.profile.routes import router as profile_router
from services.population.routes import router as population_router
from services.expectations.routes import router as expectations_router
from services.behavioral.routes import router as behavioral_router
from services.rwa.routes import router as rwa_router
from services.web3.routes import router as web3_router
from services.crossdomain.routes import router as crossdomain_router


# ═══════════════════════════════════════════════════════════════════════
# LIFESPAN — startup / shutdown hooks
# ═══════════════════════════════════════════════════════════════════════

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """
    Manages the full lifecycle of shared resources:
      - startup:  connect cache, graph DB, event producer
      - shutdown: gracefully close all connections
    """
    registry = get_registry()
    await registry.startup()

    # Provider Gateway (feature-flagged)
    from dependencies.providers import _init_provider_gateway
    provider_gateway = _init_provider_gateway()
    if provider_gateway:
        await provider_gateway.startup()
        app.state.provider_gateway = provider_gateway
        logger.info("Provider Gateway initialised")

    logger.info(
        f"Aether Backend started | env={settings.env.value} "
        f"| debug={settings.debug} | version={settings.api.version}"
    )

    yield  # --- app runs here ---

    # Graceful shutdown: drain connections and close backends
    logger.info("Initiating graceful shutdown...")
    if provider_gateway:
        await provider_gateway.shutdown()
    await registry.shutdown()
    logger.info("Aether Backend shut down gracefully")


# ═══════════════════════════════════════════════════════════════════════
# APP FACTORY
# ═══════════════════════════════════════════════════════════════════════

def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.api.title,
        description=settings.api.description,
        version=settings.api.version,
        docs_url="/docs",
        redoc_url="/redoc",
        lifespan=lifespan,
    )

    # ── CORS ──────────────────────────────────────────────────────
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.api.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=[
            "X-Request-ID",
            "X-Response-Time",
            "X-RateLimit-Limit",
            "X-RateLimit-Remaining",
            "X-RateLimit-Reset",
        ],
    )

    # ── Auth / Logging / Rate Limit / Error Handling Middleware ────
    register_middleware(app)

    # ── Mount all 17 core service routers ──────────────────────────
    app.include_router(gateway_router)
    app.include_router(ingestion_router)
    app.include_router(identity_router)
    app.include_router(analytics_router)
    app.include_router(ml_router)
    app.include_router(agent_router)
    app.include_router(campaign_router)
    app.include_router(consent_router)
    app.include_router(notification_router)
    app.include_router(admin_router)
    app.include_router(traffic_router)
    app.include_router(fraud_router)
    app.include_router(attribution_router)
    app.include_router(rewards_router)
    app.include_router(oracle_router)
    app.include_router(automation_router)
    app.include_router(diagnostics_router)
    app.include_router(providers_router)
    app.include_router(lake_router)
    app.include_router(intelligence_router)
    app.include_router(extraction_intel_router)
    app.include_router(profile_router)
    app.include_router(population_router)
    app.include_router(expectations_router)
    app.include_router(behavioral_router)
    app.include_router(rwa_router)
    app.include_router(web3_router)
    app.include_router(crossdomain_router)

    # ── Intelligence Graph services (feature-flagged) ───────────
    ig = settings.intelligence_graph

    if ig.enable_commerce_layer:
        from services.commerce.routes import router as commerce_router
        app.include_router(commerce_router)
        logger.info("Intelligence Graph: Commerce service (L3a) mounted")

    if ig.enable_onchain_layer:
        from services.onchain.routes import router as onchain_router
        app.include_router(onchain_router)
        logger.info("Intelligence Graph: On-Chain Action service (L0) mounted")

    if ig.enable_x402_layer:
        from services.x402.routes import router as x402_router
        app.include_router(x402_router)
        logger.info("Intelligence Graph: x402 Interceptor service (L3b) mounted")

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
