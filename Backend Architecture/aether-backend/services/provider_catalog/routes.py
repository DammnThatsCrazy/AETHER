"""
Aether — Provider Source Catalog Kyber Admin Routes

Operator-only routes exposing the Olympus provider source catalog,
Dune access modes, chain extraction plans, extraction products,
lake source manifests, source-model matrix, and anti-distillation alerts.

All routes require Kyber operator authentication.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Request

from shared.common.common import APIResponse, NotFoundError
from shared.logger.logger import get_logger

from services.provider_catalog.catalog import (
    DUNE_ACCESS_MODES,
    CHAIN_EXTRACTION_PLANS,
    EXTRACTION_PRODUCTS,
    PROVIDER_CATALOG,
    get_provider,
    get_providers_by_phase,
    get_providers_by_category,
    get_enabled_providers,
    get_cost_profile,
    get_rate_limit_profile,
)
from services.integrations.connectors.base import ImplementationStatus, PriorityPhase

logger = get_logger("aether.service.provider_catalog.routes")

# ── Router setup ──────────────────────────────────────────────────────────────

providers_router = APIRouter(
    prefix="/v1/admin/kyber/providers",
    tags=["Admin — Kyber Provider Catalog"],
)

dune_router = APIRouter(
    prefix="/v1/admin/kyber/dune",
    tags=["Admin — Kyber Dune"],
)

lake_router = APIRouter(
    prefix="/v1/admin/kyber/lake",
    tags=["Admin — Kyber Lake"],
)

features_router = APIRouter(
    prefix="/v1/admin/kyber/features",
    tags=["Admin — Kyber Features"],
)

intelligence_router = APIRouter(
    prefix="/v1/admin/kyber/intelligence",
    tags=["Admin — Kyber Intelligence"],
)


def _require_operator(request: Request):
    from services.security.request_context import require_kyber_operator
    return require_kyber_operator(request)


# ══════════════════════════════════════════════════════════════════════════════
# PROVIDER CATALOG ROUTES
# ══════════════════════════════════════════════════════════════════════════════

@providers_router.get("/catalog")
async def list_provider_catalog(
    request: Request,
    phase: Optional[str] = None,
    category: Optional[str] = None,
    enabled_only: bool = False,
):
    """List all Olympus-owned provider sources.

    Optional filters:
    - phase: phase_1_foundation | phase_2_enrichment | phase_3_depth
    - category: onchain | cex | prediction_market | social_web3 | social_web2 | protocol_specific
    - enabled_only: exclude DISABLED_COMPLIANCE_REVIEW entries
    """
    _require_operator(request)

    catalog = PROVIDER_CATALOG
    if phase:
        try:
            phase_enum = PriorityPhase(phase)
            catalog = [p for p in catalog if p.priority_phase == phase_enum]
        except ValueError:
            pass
    if category:
        catalog = [p for p in catalog if p.provider_category == category]
    if enabled_only:
        catalog = [p for p in catalog if p.implementation_status != ImplementationStatus.DISABLED_COMPLIANCE_REVIEW]

    items = [p.model_dump() for p in catalog]
    return APIResponse(data={
        "items": items,
        "count": len(items),
        "total_in_catalog": len(PROVIDER_CATALOG),
    }).to_dict()


@providers_router.get("/overview")
async def provider_catalog_overview(request: Request):
    """Summary statistics: coverage by phase, implementation status counts, category breakdown."""
    _require_operator(request)

    by_phase: Dict[str, int] = {}
    by_category: Dict[str, int] = {}
    by_status: Dict[str, int] = {}

    for p in PROVIDER_CATALOG:
        phase_key = p.priority_phase.value
        by_phase[phase_key] = by_phase.get(phase_key, 0) + 1

        cat_key = p.provider_category
        by_category[cat_key] = by_category.get(cat_key, 0) + 1

        status_key = p.implementation_status.value
        by_status[status_key] = by_status.get(status_key, 0) + 1

    enabled = [p for p in PROVIDER_CATALOG
               if p.implementation_status != ImplementationStatus.DISABLED_COMPLIANCE_REVIEW]

    return APIResponse(data={
        "total_providers": len(PROVIDER_CATALOG),
        "enabled_providers": len(enabled),
        "disabled_compliance_review": len(PROVIDER_CATALOG) - len(enabled),
        "by_phase": by_phase,
        "by_category": by_category,
        "by_implementation_status": by_status,
        "phases_defined": [p.value for p in PriorityPhase if p != PriorityPhase.NOT_SCHEDULED],
    }).to_dict()


@providers_router.get("/{provider_id}")
async def get_provider_detail(provider_id: str, request: Request):
    """Full detail for a single provider source."""
    _require_operator(request)

    provider = get_provider(provider_id)
    if not provider:
        raise NotFoundError("provider")

    cost_profile = get_cost_profile(provider.cost_profile_id)
    rate_limit_profile = get_rate_limit_profile(provider.rate_limit_profile_id)

    return APIResponse(data={
        "provider": provider.model_dump(),
        "cost_profile": cost_profile.model_dump() if cost_profile else None,
        "rate_limit_profile": rate_limit_profile.model_dump() if rate_limit_profile else None,
    }).to_dict()


@providers_router.get("/{provider_id}/cost")
async def get_provider_cost(provider_id: str, request: Request):
    """Cost profile for a provider."""
    _require_operator(request)

    provider = get_provider(provider_id)
    if not provider:
        raise NotFoundError("provider")

    cost_profile = get_cost_profile(provider.cost_profile_id)
    return APIResponse(data=cost_profile.model_dump() if cost_profile else {}).to_dict()


@providers_router.get("/{provider_id}/rate-limits")
async def get_provider_rate_limits(provider_id: str, request: Request):
    """Rate limit profile for a provider."""
    _require_operator(request)

    provider = get_provider(provider_id)
    if not provider:
        raise NotFoundError("provider")

    rate_limit = get_rate_limit_profile(provider.rate_limit_profile_id)
    return APIResponse(data=rate_limit.model_dump() if rate_limit else {}).to_dict()


@providers_router.get("/{provider_id}/provenance")
async def get_provider_provenance(provider_id: str, request: Request):
    """Provenance and compliance status for a provider."""
    _require_operator(request)

    provider = get_provider(provider_id)
    if not provider:
        raise NotFoundError("provider")

    return APIResponse(data={
        "provider_id": provider_id,
        "license_status": provider.license_status,
        "terms_status": provider.terms_status,
        "commercial_use_status": provider.commercial_use_status,
        "model_training_status": provider.model_training_status,
        "compliance_status": provider.compliance_status,
        "provenance_required": provider.provenance_required,
        "license_metadata_required": provider.license_metadata_required,
        "terms_metadata_required": provider.terms_metadata_required,
        "commercial_use_review_required": provider.commercial_use_review_required,
        "model_training_review_required": provider.model_training_review_required,
        "risk_tier": provider.risk_tier.value,
        "implementation_status": provider.implementation_status.value,
        "last_verified_at": provider.last_verified_at,
    }).to_dict()


@providers_router.post("/{provider_id}/validate-policy")
async def validate_provider_policy(provider_id: str, request: Request):
    """Validate a provider's current policy gates and return gate status."""
    _require_operator(request)

    provider = get_provider(provider_id)
    if not provider:
        raise NotFoundError("provider")

    gates: List[Dict[str, Any]] = []

    gates.append({
        "gate": "license_status",
        "pass": provider.license_status not in ("pending_review", "blocked"),
        "current_value": provider.license_status,
    })
    gates.append({
        "gate": "terms_status",
        "pass": provider.terms_status not in ("pending_review", "blocked"),
        "current_value": provider.terms_status,
    })
    gates.append({
        "gate": "compliance_status",
        "pass": provider.compliance_status == "approved",
        "current_value": provider.compliance_status,
    })
    gates.append({
        "gate": "implementation_status",
        "pass": provider.implementation_status not in (
            ImplementationStatus.DISABLED_COMPLIANCE_REVIEW,
            ImplementationStatus.DEPRECATED,
        ),
        "current_value": provider.implementation_status.value,
    })

    all_pass = all(g["pass"] for g in gates)

    return APIResponse(data={
        "provider_id": provider_id,
        "policy_gates": gates,
        "all_gates_pass": all_pass,
        "can_activate": all_pass,
    }).to_dict()


# ══════════════════════════════════════════════════════════════════════════════
# DUNE ROUTES
# ══════════════════════════════════════════════════════════════════════════════

@dune_router.get("/access-modes")
async def get_dune_access_modes(request: Request):
    """Three Dune access modes: dune_api, dune_datashare, dune_sim."""
    _require_operator(request)

    items = [m.model_dump() for m in DUNE_ACCESS_MODES]
    return APIResponse(data={"items": items, "count": len(items)}).to_dict()


@dune_router.get("/chains")
async def get_chain_extraction_plans(
    request: Request,
    priority: Optional[str] = None,
):
    """P0/P1/P2 chain extraction plans.

    Filter by priority: P0_CRITICAL | P1_HIGH | P2_MEDIUM
    """
    _require_operator(request)

    plans = CHAIN_EXTRACTION_PLANS
    if priority:
        plans = [p for p in plans if p.priority == priority]

    items = [p.model_dump() for p in plans]

    by_priority: Dict[str, int] = {}
    for p in items:
        k = p.get("priority", "unknown")
        by_priority[k] = by_priority.get(k, 0) + 1

    return APIResponse(data={
        "items": items,
        "count": len(items),
        "by_priority": by_priority,
    }).to_dict()


@dune_router.get("/extraction-products")
async def get_extraction_products(request: Request):
    """10 Dune extraction product specs with schema and consumer mappings."""
    _require_operator(request)

    items = [p.model_dump() for p in EXTRACTION_PRODUCTS]
    return APIResponse(data={"items": items, "count": len(items)}).to_dict()


# ══════════════════════════════════════════════════════════════════════════════
# LAKE ROUTES
# ══════════════════════════════════════════════════════════════════════════════

@lake_router.get("/source-manifests")
async def list_source_manifests(request: Request):
    """All registered source manifests for Olympus-owned provider sources."""
    _require_operator(request)

    # Source manifests derived from the provider catalog
    manifests = []
    for provider in PROVIDER_CATALOG:
        manifests.append({
            "source_manifest_id": provider.source_manifest_id,
            "provider_id": provider.provider_id,
            "provider_name": provider.provider_name,
            "provider_category": provider.provider_category,
            "source_category": provider.source_category,
            "access_method": provider.access_method,
            "lake_write_policy": provider.lake_write_policy.value,
            "graph_write_policy": provider.graph_write_policy.value,
            "model_training_eligibility": provider.model_training_eligibility.value,
            "priority_phase": provider.priority_phase.value,
            "implementation_status": provider.implementation_status.value,
            "compliance_status": provider.compliance_status,
            "lake_layer_tags": provider.lake_layer_tags,
            "ml_value_tags": provider.ml_value_tags,
        })

    return APIResponse(data={"items": manifests, "count": len(manifests)}).to_dict()


@lake_router.get("/capacity")
async def get_lake_capacity(request: Request):
    """Estimated vs actual capacity by lake layer from provider catalog size estimates."""
    _require_operator(request)

    layer_estimates: Dict[str, Dict[str, Any]] = {}

    for provider in PROVIDER_CATALOG:
        for layer_tag in provider.lake_layer_tags:
            if layer_tag not in layer_estimates:
                layer_estimates[layer_tag] = {
                    "layer": layer_tag,
                    "provider_count": 0,
                    "enabled_provider_count": 0,
                }
            layer_estimates[layer_tag]["provider_count"] += 1
            if provider.implementation_status != ImplementationStatus.DISABLED_COMPLIANCE_REVIEW:
                layer_estimates[layer_tag]["enabled_provider_count"] += 1

    return APIResponse(data={
        "layers": list(layer_estimates.values()),
        "total_providers": len(PROVIDER_CATALOG),
        "note": "Size estimates per chain available via /v1/admin/kyber/dune/chains",
    }).to_dict()


@lake_router.get("/coverage")
async def get_lake_coverage(request: Request):
    """Source coverage by phase and category."""
    _require_operator(request)

    phase_1 = get_providers_by_phase(PriorityPhase.PHASE_1_FOUNDATION)
    phase_2 = get_providers_by_phase(PriorityPhase.PHASE_2_ENRICHMENT)
    phase_3 = get_providers_by_phase(PriorityPhase.PHASE_3_DEPTH)

    return APIResponse(data={
        "phase_1_foundation": {
            "count": len(phase_1),
            "providers": [p.provider_id for p in phase_1],
        },
        "phase_2_enrichment": {
            "count": len(phase_2),
            "providers": [p.provider_id for p in phase_2],
        },
        "phase_3_depth": {
            "count": len(phase_3),
            "providers": [p.provider_id for p in phase_3],
        },
        "categories": list({p.provider_category for p in PROVIDER_CATALOG}),
    }).to_dict()


@lake_router.get("/quarantine")
async def get_quarantine_summary(request: Request):
    """Summary of quarantined Bronze records (placeholder — real counts from lake repo)."""
    _require_operator(request)

    # This endpoint surfaces quarantine status. Real counts come from BronzeRepository.
    compliance_blocked = [
        p for p in PROVIDER_CATALOG
        if p.implementation_status == ImplementationStatus.DISABLED_COMPLIANCE_REVIEW
    ]

    return APIResponse(data={
        "quarantine_summary": {
            "note": "Live Bronze quarantine counts available from lake service. "
                    "This view shows catalog-level compliance blocks.",
            "compliance_blocked_providers": len(compliance_blocked),
            "compliance_blocked_ids": [p.provider_id for p in compliance_blocked],
        },
        "policy_gates": {
            "license_required": True,
            "terms_review_required": True,
            "provenance_required": True,
            "quarantine_on_missing_license": True,
            "quarantine_on_unverified_provenance": True,
        },
    }).to_dict()


# ══════════════════════════════════════════════════════════════════════════════
# FEATURES / SIGNAL ROUTES
# ══════════════════════════════════════════════════════════════════════════════

# Source-to-model matrix built from catalog ml_value_tags
_SOURCE_MODEL_MATRIX = {
    "intent_prediction": [],
    "bot_detection": [],
    "anomaly_detection": [],
    "fraud_detection": [],
    "session_scoring": [],
    "attribution": [],
    "protocol_health": [],
    "social_sentiment": [],
    "whale_detection": [],
    "prediction_market": [],
}

for _p in PROVIDER_CATALOG:
    for _tag in _p.ml_value_tags:
        if _tag in _SOURCE_MODEL_MATRIX:
            _SOURCE_MODEL_MATRIX[_tag].append(_p.provider_id)


@features_router.get("/source-model-matrix")
async def get_source_model_matrix(request: Request):
    """Provider source → ML model consumer mapping."""
    _require_operator(request)

    matrix = []
    for provider in PROVIDER_CATALOG:
        matrix.append({
            "provider_id": provider.provider_id,
            "provider_name": provider.provider_name,
            "provider_category": provider.provider_category,
            "ml_value_tags": provider.ml_value_tags,
            "model_training_eligibility": provider.model_training_eligibility.value,
            "model_training_status": provider.model_training_status,
            "implementation_status": provider.implementation_status.value,
        })

    return APIResponse(data={
        "matrix": matrix,
        "model_consumers": _SOURCE_MODEL_MATRIX,
        "total_providers": len(matrix),
    }).to_dict()


# 5 unique signal features (stubs — see services/unique_signals/)
_UNIQUE_SIGNAL_BACKLOG = [
    {
        "signal_id": "prediction_market_onchain_correlation",
        "signal_name": "Prediction Market On-Chain Correlation",
        "status": "NOT_YET_IMPLEMENTED",
        "required_providers": ["polymarket_gamma", "kalshi", "dune_api", "defi_llama"],
        "required_credentials": ["POLYMARKET_API_KEY", "KALSHI_API_KEY", "DUNE_API_KEY"],
        "output_schema": {
            "event_probability_shift": "float",
            "capital_flow_response": "float",
            "correlation_confidence": "float",
        },
        "model_training_eligible": True,
        "source_manifest_ids": [
            "manifest_polymarket_gamma", "manifest_kalshi", "manifest_dune_api", "manifest_defi_llama",
        ],
        "blocking_reason": "Requires Polymarket + Kalshi API credentials",
    },
    {
        "signal_id": "web3_social_identity_graph",
        "signal_name": "Web3 Social Identity Graph",
        "status": "NOT_YET_IMPLEMENTED",
        "required_providers": ["farcaster_neynar", "lens_protocol", "ens_public", "snapshot"],
        "required_credentials": ["NEYNAR_API_KEY"],
        "output_schema": {
            "wallet_social_edge": "graph_edge",
            "governance_participation_edge": "graph_edge",
            "social_identity_confidence": "float",
        },
        "model_training_eligible": True,
        "source_manifest_ids": [
            "manifest_farcaster_neynar", "manifest_lens_protocol",
            "manifest_ens_public", "manifest_snapshot",
        ],
        "blocking_reason": "Requires Neynar API key",
    },
    {
        "signal_id": "cex_funding_behavioral_prediction",
        "signal_name": "CEX Funding Behavioral Prediction",
        "status": "NOT_YET_IMPLEMENTED",
        "required_providers": ["binance_public", "okx", "bybit", "coingecko", "dune_api"],
        "required_credentials": ["DUNE_API_KEY", "COINGECKO_PRO_API_KEY"],
        "output_schema": {
            "funding_extreme_signal": "float",
            "liquidation_risk_context": "float",
            "open_interest_delta": "float",
        },
        "model_training_eligible": True,
        "source_manifest_ids": [
            "manifest_binance_public", "manifest_okx", "manifest_bybit",
            "manifest_coingecko", "manifest_dune_api",
        ],
        "blocking_reason": "Requires Dune API key + CoinGecko Pro for full coverage",
    },
    {
        "signal_id": "github_abandonment_risk",
        "signal_name": "GitHub Developer Abandonment Risk",
        "status": "NOT_YET_IMPLEMENTED",
        "required_providers": ["github_api", "defi_llama", "dune_api"],
        "required_credentials": ["GITHUB_OAUTH_APP_CLIENT_ID", "GITHUB_OAUTH_APP_CLIENT_SECRET"],
        "output_schema": {
            "developer_activity_score": "float",
            "protocol_abandonment_risk": "float",
            "commit_velocity_delta": "float",
        },
        "model_training_eligible": True,
        "source_manifest_ids": ["manifest_github_api", "manifest_defi_llama", "manifest_dune_api"],
        "blocking_reason": "Requires GitHub OAuth app registration",
    },
    {
        "signal_id": "social_whale_coordination_detection",
        "signal_name": "Social + Whale Coordination Detection",
        "status": "NOT_YET_IMPLEMENTED",
        "required_providers": [
            "twitter_x", "reddit", "telegram_bot", "discord_bot", "dune_api", "covalent_goldrush",
        ],
        "required_credentials": [
            "TWITTER_BEARER_TOKEN", "REDDIT_CLIENT_ID", "REDDIT_CLIENT_SECRET",
            "TELEGRAM_BOT_TOKEN", "DISCORD_BOT_TOKEN", "COVALENT_API_KEY",
        ],
        "output_schema": {
            "sentiment_spike": "float",
            "whale_cluster_movement": "float",
            "coordination_confidence": "float",
        },
        "model_training_eligible": False,
        "source_manifest_ids": [
            "manifest_twitter_x", "manifest_reddit", "manifest_telegram_bot",
            "manifest_discord_bot", "manifest_dune_api", "manifest_covalent_goldrush",
        ],
        "blocking_reason": "Social providers (Twitter/Reddit/Telegram/Discord) disabled pending compliance review",
    },
]


@features_router.get("/unique-signal-backlog")
async def get_unique_signal_backlog(request: Request):
    """5 unique cross-source signal features — implementation status and blockers."""
    _require_operator(request)

    not_started = [s for s in _UNIQUE_SIGNAL_BACKLOG if s["status"] == "NOT_YET_IMPLEMENTED"]

    return APIResponse(data={
        "items": _UNIQUE_SIGNAL_BACKLOG,
        "count": len(_UNIQUE_SIGNAL_BACKLOG),
        "not_yet_implemented": len(not_started),
        "note": "See services/unique_signals/ for implementation stubs",
    }).to_dict()


# ══════════════════════════════════════════════════════════════════════════════
# INTELLIGENCE / ANTI-DISTILLATION ROUTES
# ══════════════════════════════════════════════════════════════════════════════

@intelligence_router.get("/anti-distillation")
async def get_anti_distillation_status(request: Request):
    """Anti-distillation alert status, suspicious patterns, and configuration.

    Real suspicious pattern counts are populated by AntiDistillationService
    when AETHER_ANTI_DISTILLATION_ENABLED=true.
    """
    _require_operator(request)

    from config.settings import settings

    enabled = getattr(getattr(settings, "provider_corpus", None), "anti_distillation_enabled", False)

    return APIResponse(data={
        "anti_distillation_enabled": enabled,
        "config": {
            "rapid_diverse_query_threshold": 100,
            "address_sweep_detection": True,
            "systematic_enumeration_detection": True,
            "score_bins_by_plan": {
                "P1_HOBBYIST": 0.1,
                "P2_PROFESSIONAL": 0.05,
                "P3_GROWTH": 0.01,
                "P4_PROTOCOL": 0.001,
            },
        },
        "active_alerts": [],
        "suspicious_pattern_count_24h": 0,
        "honeypot_query_count_24h": 0,
        "note": (
            "Set AETHER_ANTI_DISTILLATION_ENABLED=true to enable live pattern detection. "
            "See services/security/anti_distillation.py for full implementation."
        ),
    }).to_dict()
