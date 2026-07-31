"""
Aether Backend — Central Configuration
12-Factor compliant: all config sourced from environment variables with sensible defaults.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class Environment(str, Enum):
    LOCAL = "local"
    DEV = "dev"
    # Hermetic CI/compose environment (deploy/integration/*): production-shaped
    # strictness — non-local fail-closed startup checks apply and explicit
    # integration-only secrets/backends must be provided — but never a deploy
    # target, so staging/production-only gates (e.g. mandatory route-policy
    # enforcement, strict worker-start abort) do not apply.
    INTEGRATION = "integration"
    STAGING = "staging"
    PRODUCTION = "production"


def _env(key: str, default: str = "") -> str:
    return os.environ.get(key, default)


def _env_int(key: str, default: int = 0) -> int:
    return int(os.environ.get(key, str(default)))


def _env_bool(key: str, default: bool = False) -> bool:
    return os.environ.get(key, str(default)).lower() in ("true", "1", "yes")


def _env_list(key: str, default: str = "", sep: str = ",") -> list[str]:
    raw = os.environ.get(key, default)
    return [item.strip() for item in raw.split(sep) if item.strip()] if raw else []


# ---------------------------------------------------------------------------
# Database connections
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class TimescaleDBConfig:
    host: str = _env("TSDB_HOST", "localhost")
    port: int = _env_int("TSDB_PORT", 5432)
    database: str = _env("TSDB_DATABASE", "aether")
    user: str = _env("TSDB_USER", "aether")
    password: str = _env("TSDB_PASSWORD", "")
    pool_min: int = _env_int("TSDB_POOL_MIN", 5)
    pool_max: int = _env_int("TSDB_POOL_MAX", 20)

    @property
    def dsn(self) -> str:
        return f"postgresql://{self.user}:{self.password}@{self.host}:{self.port}/{self.database}"


@dataclass(frozen=True)
class NeptuneConfig:
    endpoint: str = _env("NEPTUNE_ENDPOINT", "localhost")
    port: int = _env_int("NEPTUNE_PORT", 8182)
    region: str = _env("AWS_REGION", "us-east-1")

    @property
    def url(self) -> str:
        return f"wss://{self.endpoint}:{self.port}/gremlin"


@dataclass(frozen=True)
class RedisConfig:
    host: str = _env("REDIS_HOST", "localhost")
    port: int = _env_int("REDIS_PORT", 6379)
    db: int = _env_int("REDIS_DB", 0)
    password: str = _env("REDIS_PASSWORD", "")
    pool_size: int = _env_int("REDIS_POOL_SIZE", 10)

    @property
    def url(self) -> str:
        auth = f":{self.password}@" if self.password else ""
        return f"redis://{auth}{self.host}:{self.port}/{self.db}"


@dataclass(frozen=True)
class DynamoDBConfig:
    region: str = _env("AWS_REGION", "us-east-1")
    endpoint: Optional[str] = _env("DYNAMODB_ENDPOINT", "") or None
    table_prefix: str = _env("DYNAMODB_TABLE_PREFIX", "aether_")


@dataclass(frozen=True)
class OpenSearchConfig:
    endpoint: str = _env("OPENSEARCH_ENDPOINT", "localhost")
    port: int = _env_int("OPENSEARCH_PORT", 9200)
    region: str = _env("AWS_REGION", "us-east-1")


# ---------------------------------------------------------------------------
# Event bus (Kafka / SNS+SQS)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class EventBusConfig:
    broker_type: str = _env("EVENT_BROKER", "kafka")  # "kafka" or "sns_sqs"
    kafka_brokers: str = _env("KAFKA_BROKERS", "localhost:9092")
    consumer_group: str = _env("KAFKA_CONSUMER_GROUP", "aether-backend")
    sns_topic_arn: str = _env("SNS_TOPIC_ARN", "")
    sqs_queue_url: str = _env("SQS_QUEUE_URL", "")


# ---------------------------------------------------------------------------
# API / Rate limit settings
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class RateLimitConfig:
    """Self-serve plan rate limiting configuration.

    Burst RPM limits are sourced from shared.plans.catalog.PLAN_CATALOG —
    P1=100, P2=500, P3=1200, P4=3000. The legacy free_rpm/pro_rpm/
    enterprise_rpm fields are deprecated and will be removed once all
    callers migrate to PlanTier.
    """
    pricing_option: str = _env("PRICING_OPTION", "B")
    quota_redis_ttl_days: int = _env_int("QUOTA_REDIS_TTL_DAYS", 35)
    quota_flush_interval_s: int = _env_int("QUOTA_FLUSH_INTERVAL_S", 60)
    # Deprecated: legacy 3-tier RPM limits. Removed in step 03.
    free_rpm: int = 60
    pro_rpm: int = 600
    enterprise_rpm: int = 6000


@dataclass(frozen=True)
class APIConfig:
    version: str = "v1"
    title: str = "Aether API"
    description: str = "Aether Backend — Unified API"
    cors_origins: list[str] = field(default_factory=lambda: _env_list(
        "CORS_ORIGINS", "http://localhost:3000,https://app.aether.io"
    ))
    deprecation_window_months: int = 12
    max_request_body_bytes: int = _env_int("MAX_REQUEST_BODY_MB", 10) * 1024 * 1024


# ---------------------------------------------------------------------------
# JWT / Auth
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class AuthConfig:
    jwt_secret: str = _env("JWT_SECRET", "change-me-in-production")
    jwt_secret_previous: str = _env("JWT_SECRET_PREVIOUS", "")
    jwt_algorithm: str = "HS256"
    jwt_expiry_minutes: int = _env_int("JWT_EXPIRY_MINUTES", 60)
    api_key_header: str = "X-API-Key"


# ---------------------------------------------------------------------------
# Intelligence Graph — feature flags for progressive layer activation
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class IntelligenceGraphConfig:
    """Feature flags for Unified On-Chain Intelligence Graph layers."""
    enable_agent_layer: bool = _env_bool("IG_AGENT_LAYER", False)           # L2
    enable_commerce_layer: bool = _env_bool("IG_COMMERCE_LAYER", False)     # L3a
    enable_x402_layer: bool = _env_bool("IG_X402_LAYER", False)             # L3b
    enable_onchain_layer: bool = _env_bool("IG_ONCHAIN_LAYER", False)       # L0
    enable_trust_scoring: bool = _env_bool("IG_TRUST_SCORING", False)       # Composite
    enable_bytecode_risk: bool = _env_bool("IG_BYTECODE_RISK", False)       # Rule-based
    enable_rpc_gateway: bool = _env_bool("IG_RPC_GATEWAY", False)           # L6
    # Agentic Commerce (L3b+) — extends x402 capture into full control plane.
    enable_commerce_control_plane: bool = _env_bool("COMMERCE_CONTROL_PLANE_ENABLED", True)
    commerce_approval_required_all: bool = _env_bool("COMMERCE_APPROVAL_REQUIRED_ALL", True)
    commerce_v2_protocol: bool = _env_bool("COMMERCE_V2_PROTOCOL", True)
    commerce_default_facilitator: str = _env("COMMERCE_DEFAULT_FACILITATOR", "aether-local")
    commerce_base_rpc: str = _env("COMMERCE_BASE_RPC", "https://mainnet.base.org")
    commerce_solana_rpc: str = _env("COMMERCE_SOLANA_RPC", "https://api.mainnet-beta.solana.com")
    commerce_enable_v2: bool = _env_bool("COMMERCE_ENABLE_V2", True)
    commerce_feature_flag: str = _env("COMMERCE_FEATURE_FLAG", "ga")


# ---------------------------------------------------------------------------
# Communications Intelligence — rollout feature flags (Phase 36)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class CommsConfig:
    """Feature flags for Communications Intelligence rollout.

    Recommended activation order: ingestion → campaign projection →
    journeys → graph → profile360 → campaign360 → noesis
    (docs/comms/COMMS_RELEASE_READINESS.md).
    """
    ingestion_enabled: bool = _env_bool("AETHER_COMMS_INGESTION_ENABLED", True)
    campaign_projection_enabled: bool = _env_bool("AETHER_COMMS_CAMPAIGN_PROJECTION_ENABLED", True)
    journeys_enabled: bool = _env_bool("AETHER_COMMS_JOURNEYS_ENABLED", True)
    graph_enabled: bool = _env_bool("AETHER_COMMS_GRAPH_ENABLED", True)
    profile360_enabled: bool = _env_bool("AETHER_COMMS_PROFILE360_ENABLED", True)
    campaign360_enabled: bool = _env_bool("AETHER_COMMS_CAMPAIGN360_ENABLED", True)
    noesis_enabled: bool = _env_bool("AETHER_COMMS_NOESIS_ENABLED", True)
    # Attribution policy switches (ADR-C8)
    reported_opens_as_view_through: bool = _env_bool("AETHER_COMMS_OPENS_VIEW_THROUGH", False)
    replies_attribution_eligible: bool = _env_bool("AETHER_COMMS_REPLIES_ELIGIBLE", True)


@dataclass(frozen=True)
class QuickNodeConfig:
    """L6 Infrastructure Backbone — single shared RPC gateway."""
    api_key: str = _env("QUICKNODE_API_KEY", "")
    endpoint: str = _env("QUICKNODE_ENDPOINT", "")
    x402_enabled: bool = _env_bool("QUICKNODE_X402_ENABLED", False)
    max_rps: int = _env_int("QUICKNODE_MAX_RPS", 100)


# ---------------------------------------------------------------------------
# Provider Gateway — BYOK, failover, usage metering
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ProviderGatewayConfig:
    """Multi-provider abstraction with BYOK support and automatic failover."""
    enabled: bool = _env_bool("PROVIDER_GATEWAY_ENABLED", False)
    # BYOK_ENCRYPTION_KEY is the canonical name; PROVIDER_GATEWAY_ENCRYPTION_KEY is a legacy alias.
    encryption_key: str = _env("BYOK_ENCRYPTION_KEY", "") or _env("PROVIDER_GATEWAY_ENCRYPTION_KEY", "")
    # Set during key rotation: old key so in-flight tokens remain decryptable.
    # Clear once all rows are re-encrypted (see scripts/byok_reencrypt.py).
    encryption_key_previous: str = _env("BYOK_ENCRYPTION_KEY_PREVIOUS", "")
    # Additional provider API keys (system defaults)
    alchemy_api_key: str = _env("ALCHEMY_API_KEY", "")
    alchemy_endpoint: str = _env("ALCHEMY_ENDPOINT", "")
    infura_api_key: str = _env("INFURA_API_KEY", "")
    infura_project_id: str = _env("INFURA_PROJECT_ID", "")
    etherscan_api_key: str = _env("ETHERSCAN_API_KEY", "")
    moralis_api_key: str = _env("MORALIS_API_KEY", "")
    # Failover tunables
    max_retries: int = _env_int("PROVIDER_MAX_RETRIES", 2)
    circuit_breaker_threshold: int = _env_int("PROVIDER_CB_THRESHOLD", 5)
    circuit_breaker_timeout_s: int = _env_int("PROVIDER_CB_TIMEOUT_S", 30)
    # Metering
    meter_flush_interval_s: int = _env_int("PROVIDER_METER_FLUSH_S", 60)
    # ── Durable credential authority ───────────────────────────────────────
    # Encryption cipher for the durable multi-slot provider-credential store.
    # "local"   → AES-256-GCM (non-production, for local/test only)
    # "aws_kms" → KMS envelope encryption (customer-managed CMK)
    # Fail-closed: staging/production MUST be "aws_kms" with a key id set (see
    # CredentialCipherStartupValidator).
    credential_cipher: str = _env("CREDENTIAL_CIPHER", "local")
    credential_kms_key_id: str = _env("CREDENTIAL_KMS_KEY_ID", "")
    aws_region: str = _env("AWS_REGION", "us-east-1")
    # Bounded caches for decrypted values / metadata (Redis is never the sole
    # authority — the durable table is). TTLs in seconds; overlap window in hours.
    credential_decrypt_cache_ttl_s: int = _env_int("CREDENTIAL_DECRYPT_CACHE_TTL_S", 60)
    credential_metadata_cache_ttl_s: int = _env_int("CREDENTIAL_METADATA_CACHE_TTL_S", 30)
    credential_rotation_overlap_hours: int = _env_int("CREDENTIAL_ROTATION_OVERLAP_HOURS", 24)


# ---------------------------------------------------------------------------
# Model Extraction Defense
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ModelExtractionDefenseConfig:
    """Model extraction defense layer — protects ML serving endpoints."""
    enabled: bool = _env_bool("ENABLE_EXTRACTION_DEFENSE", False)
    # When True, protected ML prediction routes fail closed (HTTP 503) if
    # neither the Extraction Defense Mesh nor the legacy defense layer is
    # available. Left False by default (allow-but-warn) for backward
    # compatibility; production profiles set REQUIRE_EXTRACTION_DEFENSE=true.
    require_defense: bool = _env_bool("REQUIRE_EXTRACTION_DEFENSE", False)
    enable_output_noise: bool = _env_bool("ENABLE_OUTPUT_NOISE", True)
    enable_watermark: bool = _env_bool("ENABLE_WATERMARK", True)
    enable_query_analysis: bool = _env_bool("ENABLE_QUERY_ANALYSIS", True)
    watermark_secret_key: str = _env("WATERMARK_SECRET_KEY", "aether-wm-default-change-me")
    canary_secret_seed: str = _env("CANARY_SECRET_SEED", "aether-canary-seed-change-me")
    # Rate limits (per-API-key)
    key_max_per_minute: int = _env_int("EXTRACTION_KEY_RPM", 60)
    key_max_per_hour: int = _env_int("EXTRACTION_KEY_RPH", 1000)
    key_max_per_day: int = _env_int("EXTRACTION_KEY_RPD", 10000)
    # Rate limits (per-IP)
    ip_max_per_minute: int = _env_int("EXTRACTION_IP_RPM", 120)
    ip_max_per_hour: int = _env_int("EXTRACTION_IP_RPH", 3000)
    ip_max_per_day: int = _env_int("EXTRACTION_IP_RPD", 30000)
    # Output perturbation
    logit_noise_std: float = float(_env("EXTRACTION_NOISE_STD", "0.02"))
    output_precision: int = _env_int("EXTRACTION_OUTPUT_PRECISION", 2)


@dataclass(frozen=True)
class ExtractionMeshConfig:
    """Extraction Defense Mesh — distributed multi-identity defense layer."""
    enabled: bool = _env_bool("ENABLE_EXTRACTION_MESH", False)
    # Budget engine
    budget_engine_enabled: bool = _env_bool("EXTRACTION_BUDGET_ENABLED", True)
    # Expectation engine
    expectation_engine_enabled: bool = _env_bool("EXTRACTION_EXPECTATION_ENABLED", True)
    # Policy engine
    policy_engine_enabled: bool = _env_bool("EXTRACTION_POLICY_ENABLED", True)
    # Attribution / canary
    attribution_enabled: bool = _env_bool("EXTRACTION_ATTRIBUTION_ENABLED", True)
    canary_secret_seed: str = _env("EXTRACTION_CANARY_SEED", "aether-mesh-canary-seed")
    # Telemetry
    telemetry_enabled: bool = _env_bool("EXTRACTION_TELEMETRY_ENABLED", True)
    # Privileged callers (comma-separated tenant IDs)
    privileged_tenants: list[str] = field(default_factory=lambda: _env_list(
        "EXTRACTION_PRIVILEGED_TENANTS", ""
    ))
    privileged_api_keys: list[str] = field(default_factory=lambda: _env_list(
        "EXTRACTION_PRIVILEGED_API_KEYS", ""
    ))
    # Batch restriction
    batch_internal_only: bool = _env_bool("EXTRACTION_BATCH_INTERNAL_ONLY", True)
    # Disclosure defaults
    default_output_precision: int = _env_int("EXTRACTION_OUTPUT_PRECISION", 2)
    # Alerting thresholds
    alert_on_orange: bool = _env_bool("EXTRACTION_ALERT_ON_ORANGE", True)
    alert_on_red: bool = _env_bool("EXTRACTION_ALERT_ON_RED", True)


# ---------------------------------------------------------------------------
# Email
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class EmailConfig:
    """Transactional email configuration.

    provider=ses   → uses boto3 (AWS SDK). Requires AWS credentials in env.
    provider=sendgrid → uses requests + SENDGRID_API_KEY.
    EMAIL_ENABLED=false disables all sending (default) — safe for local dev.
    """
    enabled: bool = _env_bool("EMAIL_ENABLED", False)
    provider: str = _env("EMAIL_PROVIDER", "ses")       # "ses" | "sendgrid"
    from_address: str = _env("EMAIL_FROM_ADDRESS", "noreply@aether.io")
    from_name: str = _env("EMAIL_FROM_NAME", "AETHER")
    aws_region: str = _env("EMAIL_AWS_REGION", "us-east-1")
    sendgrid_api_key: str = _env("SENDGRID_API_KEY", "")
    app_url: str = _env("APP_URL", "http://localhost:3000")


# ---------------------------------------------------------------------------
# Auth0 / SSO
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Auth0Config:
    """Auth0 tenant configuration for SSO (Google, Apple, Microsoft, Twitter/X, Slack).

    Set AUTH0_DOMAIN and AUTH0_API_AUDIENCE from the Auth0 Dashboard.
    Leave blank in AETHER_ENV=local to bypass RS256 validation and run without Auth0.
    """
    domain: str = _env("AUTH0_DOMAIN", "")
    api_audience: str = _env("AUTH0_API_AUDIENCE", "")
    client_id: str = _env("AUTH0_CLIENT_ID", "")


# ---------------------------------------------------------------------------
# Password / Email Auth
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class PasswordAuthConfig:
    """Configuration for the native email+password sign-up flow."""
    otp_ttl_seconds: int = _env_int("OTP_TTL_SECONDS", 600)      # 10 minutes
    min_password_length: int = _env_int("MIN_PASSWORD_LENGTH", 8)
    max_login_attempts: int = _env_int("MAX_LOGIN_ATTEMPTS", 10)  # per IP per minute


# ---------------------------------------------------------------------------
# Stripe Billing
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class StripeBillingConfig:
    """Stripe Billing integration configuration.

    All Price IDs map to entries in shared.plans.catalog.PLAN_CATALOG. Pricing
    amounts are NOT duplicated here — only the Stripe Price IDs themselves.

    In non-local environments with enabled=True, secret_key, webhook_secret,
    price_p1..price_p4, and checkout/portal URLs are required (validated in
    Settings.__post_init__). In AETHER_ENV=local, missing values are tolerated
    and admin Stripe routes return mocked URLs.

    overage_price_id is OPTIONAL. It is only required when charging Aether
    overage through Stripe invoices. When absent, Stripe overage invoicing is
    disabled and existing internal overage calculation remains authoritative.
    """
    enabled: bool = _env_bool("STRIPE_BILLING_ENABLED", False)
    secret_key: str = _env("STRIPE_SECRET_KEY", "")
    webhook_secret: str = _env("STRIPE_WEBHOOK_SECRET", "")
    price_p1: str = _env("STRIPE_PRICE_P1", "")
    price_p2: str = _env("STRIPE_PRICE_P2", "")
    price_p3: str = _env("STRIPE_PRICE_P3", "")
    price_p4: str = _env("STRIPE_PRICE_P4", "")
    overage_price_id: str = _env("STRIPE_OVERAGE_PRICE_ID", "")
    checkout_success_url: str = _env(
        "STRIPE_CHECKOUT_SUCCESS_URL",
        "http://localhost:3000/billing/success?session_id={CHECKOUT_SESSION_ID}",
    )
    checkout_cancel_url: str = _env(
        "STRIPE_CHECKOUT_CANCEL_URL",
        "http://localhost:3000/billing/cancel",
    )
    portal_return_url: str = _env(
        "STRIPE_PORTAL_RETURN_URL",
        "http://localhost:3000/billing",
    )

    @property
    def overage_invoicing_enabled(self) -> bool:
        return bool(self.overage_price_id)


# ---------------------------------------------------------------------------
# ClickHouse (CIS cognitive telemetry warehouse)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ClickHouseConfig:
    host: str = _env("CLICKHOUSE_HOST", "localhost")
    port: int = _env_int("CLICKHOUSE_PORT", 9000)
    http_port: int = _env_int("CLICKHOUSE_HTTP_PORT", 8123)
    database: str = _env("CLICKHOUSE_DB", "aether_cis")
    user: str = _env("CLICKHOUSE_USER", "default")
    password: str = _env("CLICKHOUSE_PASSWORD", "")
    pool_size: int = _env_int("CLICKHOUSE_POOL_SIZE", 5)


# ---------------------------------------------------------------------------
# Cognitive Integrity System
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class CISConfig:
    enabled: bool = _env_bool("CIS_ENABLED", False)
    mutation_gateway_enabled: bool = _env_bool("CIS_MUTATION_GATEWAY", True)
    drift_threshold: float = float(_env("CIS_DRIFT_THRESHOLD", "0.25"))
    contamination_threshold: float = float(_env("CIS_CONTAMINATION_THRESHOLD", "0.60"))
    quarantine_on_high_risk: bool = _env_bool("CIS_QUARANTINE_HIGH_RISK", True)
    health_compute_interval_s: int = _env_int("CIS_HEALTH_INTERVAL_S", 300)
    # Scoring weights (must sum to 1.0; validated at runtime)
    health_weight_structural: float = float(_env("CIS_WEIGHT_STRUCTURAL", "0.20"))
    health_weight_semantic: float = float(_env("CIS_WEIGHT_SEMANTIC", "0.20"))
    health_weight_retrieval: float = float(_env("CIS_WEIGHT_RETRIEVAL", "0.15"))
    health_weight_provenance: float = float(_env("CIS_WEIGHT_PROVENANCE", "0.20"))
    health_weight_contamination: float = float(_env("CIS_WEIGHT_CONTAMINATION", "0.15"))
    health_weight_volatility: float = float(_env("CIS_WEIGHT_VOLATILITY", "0.10"))


# ---------------------------------------------------------------------------
# Decision & Outcome Intelligence feature flags
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class DecisionOutcomeIntelligenceConfig:
    recommendations_enabled: bool = _env_bool("AETHER_RECOMMENDATIONS_ENABLED", False)
    decision_records_enabled: bool = _env_bool("AETHER_DECISION_RECORDS_ENABLED", False)
    outcome_feedback_enabled: bool = _env_bool("AETHER_OUTCOME_FEEDBACK_ENABLED", False)
    playbooks_enabled: bool = _env_bool("AETHER_PLAYBOOKS_ENABLED", False)
    kyber_observability_enabled: bool = _env_bool("KYBER_RECOMMENDATION_OBSERVABILITY_ENABLED", False)
    confidence_threshold: float = float(_env("AETHER_RECOMMENDATION_CONFIDENCE_THRESHOLD", "0.35"))


@dataclass(frozen=True)
class SecurityGovernanceConfig:
    """Governance control-plane settings.

    Kyber security routes are restricted to Olympus operators. An operator is
    recognised ONLY by an explicit signal that Aether tenant tokens never carry:
    the ``kyber:operator`` permission, or membership in this allowlist of
    internal operator tenant IDs. No regular Aether tenant — even one holding the
    legacy ``admin`` permission — may access Kyber.
    """
    kyber_operator_permission: str = _env("KYBER_OPERATOR_PERMISSION", "kyber:operator")
    kyber_operator_tenant_ids: list[str] = field(default_factory=lambda: _env_list(
        "KYBER_OPERATOR_TENANT_IDS", ""
    ))


# ---------------------------------------------------------------------------
# Trust Plane — staged-activation flags (PR 1: sessions, credentials, legacy
# auth containment). Under the founding-tenant posture these are ON in
# staging/production and OFF in local/dev, so existing frontends and the
# current test suite keep the legacy API-key path. Each flag may be explicitly
# overridden by its env var. See config/posture/founding_tenant_production.yaml
# and docs/FOUNDING-TENANT-PRODUCTION.md.
# ---------------------------------------------------------------------------

# Default-ON for non-local environments; explicit env var always wins.
_TRUST_DEFAULT_ON = _env("AETHER_ENV", "local") not in ("local", "dev")


@dataclass(frozen=True)
class TrustPlaneConfig:
    """Human sessions vs. service credentials vs. public ingest identifiers."""

    # Master switch for the trust plane.
    trust_plane_enabled: bool = _env_bool("TRUST_PLANE_ENABLED", _TRUST_DEFAULT_ON)
    # Human auth paths issue durable sessions, never reusable API keys.
    human_sessions_enabled: bool = _env_bool("HUMAN_SESSIONS_ENABLED", _TRUST_DEFAULT_ON)
    # Scoped, rotatable, revocable machine credentials.
    service_credentials_enabled: bool = _env_bool("SERVICE_CREDENTIALS_ENABLED", _TRUST_DEFAULT_ON)
    # Non-secret, ingest-only public identifiers.
    public_ingest_identifier_enabled: bool = _env_bool(
        "PUBLIC_INGEST_IDENTIFIER_ENABLED", _TRUST_DEFAULT_ON
    )
    # Legacy broad tenant registration is CONTAINED in staging/production and
    # preserved in local/dev (so existing local flows keep working). Explicit
    # env var always wins.
    legacy_tenant_registration_enabled: bool = _env_bool(
        "LEGACY_TENANT_REGISTRATION_ENABLED", not _TRUST_DEFAULT_ON
    )

    # Session lifetimes (minutes). Conservative defaults; override per env.
    session_idle_minutes: int = _env_int("SESSION_IDLE_MINUTES", 60)
    session_absolute_minutes: int = _env_int("SESSION_ABSOLUTE_MINUTES", 12 * 60)


# ---------------------------------------------------------------------------
# Route Policy Registry (PR 2) — authorization-as-protocol.
#
# The per-route Kyber operator gate (services/security/request_context.py) is
# always active. These flags govern the middleware authorization boundary
# that classifies every request against config/route_registry.yaml:
#   - policy_enforcement_enabled: run the policy boundary.
#   - route_registry_enforced: when True, the hook DENIES unclassified routes and
#     Kyber routes reached by non-operators. False is an explicit local/dev
#     observe mode; staging and production reject it during validation.
#   - kyber_operator_gate_enforced: informational — the canonical per-route gate
#     is unconditional; documents that operator gating is active.
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class RouteRegistryConfig:
    policy_enforcement_enabled: bool = _env_bool("POLICY_ENFORCEMENT_ENABLED", True)
    route_registry_enforced: bool = _env_bool(
        "ROUTE_REGISTRY_ENFORCED", _env("AETHER_ENV", "local") not in ("local", "dev", "test")
    )
    kyber_operator_gate_enforced: bool = _env_bool("KYBER_OPERATOR_GATE_ENFORCED", True)


# ---------------------------------------------------------------------------
# Kyber workforce identity plane.
#
# Kyber operators are Olympus WORKFORCE principals (Google SSO + a trusted
# device + role templates + purpose-bound tenant access scopes), not Aether
# tenants carrying a `kyber:operator` permission. The legacy tenant-permission
# path remains available in local/dev via
# KYBER_LEGACY_OPERATOR_IDENTITY_ALLOWED so existing local flows and the current
# test suite keep working; staging/production reject that combination during
# validation (see Settings.__post_init__ →
# KYBER_WORKFORCE_ENFORCEMENT_REQUIRED).
#
# Every flag is independently overridable so the migration can be rolled out and
# rolled BACK per environment without a code change.
# ---------------------------------------------------------------------------

# Default-ON for deploy targets; local/dev default OFF. Explicit env var wins.
_KYBER_DEFAULT_ON = _env("AETHER_ENV", "local") not in ("local", "dev")


@dataclass(frozen=True)
class KyberWorkforceConfig:
    """Workforce identity, device trust, backend authorization and bootstrap."""

    # ── Plane switches ────────────────────────────────────────────────────────
    #: Master switch: resolve Kyber callers as workforce principals.
    workforce_identity_enabled: bool = _env_bool(
        "KYBER_WORKFORCE_IDENTITY_ENABLED", _KYBER_DEFAULT_ON
    )
    #: A Kyber session must be bound to an approved, non-revoked device.
    device_trust_required: bool = _env_bool("KYBER_DEVICE_TRUST_REQUIRED", _KYBER_DEFAULT_ON)
    #: Enforce declared route capabilities at the authorization boundary.
    #: False is an explicit observe mode (warn + metric, no denial).
    backend_authz_enforced: bool = _env_bool("KYBER_BACKEND_AUTHZ_ENFORCED", _KYBER_DEFAULT_ON)
    #: Purpose-bound, expiring tenant access scopes (scope v2).
    scope_v2_enabled: bool = _env_bool("KYBER_SCOPE_V2_ENABLED", True)
    #: Require fresh step-up for high-disclosure / high-impact actions.
    step_up_required: bool = _env_bool("KYBER_STEP_UP_REQUIRED", _KYBER_DEFAULT_ON)
    #: Keep honouring the legacy tenant-permission / tenant-id operator path.
    legacy_operator_identity_allowed: bool = _env_bool(
        "KYBER_LEGACY_OPERATOR_IDENTITY_ALLOWED", not _KYBER_DEFAULT_ON
    )

    # ── Google Workspace SSO (OIDC) ───────────────────────────────────────────
    google_client_id: str = _env("KYBER_GOOGLE_CLIENT_ID", "")
    google_client_secret: str = _env("KYBER_GOOGLE_CLIENT_SECRET", "")
    google_redirect_uri: str = _env("KYBER_GOOGLE_REDIRECT_URI", "")
    google_hosted_domain: str = _env("KYBER_GOOGLE_HOSTED_DOMAIN", "")
    google_discovery_url: str = _env(
        "KYBER_GOOGLE_DISCOVERY_URL",
        "https://accounts.google.com/.well-known/openid-configuration",
    )

    # ── WebAuthn device binding / step-up ─────────────────────────────────────
    webauthn_rp_id: str = _env("KYBER_WEBAUTHN_RP_ID", "")
    webauthn_rp_name: str = _env("KYBER_WEBAUTHN_RP_NAME", "Kyber")
    webauthn_origin: str = _env("KYBER_WEBAUTHN_ORIGIN", "")

    # ── Founder bootstrap (a break-glass first-principal path) ────────────────
    bootstrap_enabled: bool = _env_bool("KYBER_BOOTSTRAP_ENABLED", False)
    bootstrap_founder_email: str = _env("KYBER_BOOTSTRAP_FOUNDER_EMAIL", "")
    bootstrap_founder_google_subject: str = _env("KYBER_BOOTSTRAP_FOUNDER_GOOGLE_SUBJECT", "")

    # ── Directory sync ────────────────────────────────────────────────────────
    directory_sync_enabled: bool = _env_bool("KYBER_DIRECTORY_SYNC_ENABLED", False)
    directory_max_stale_hours: int = _env_int("KYBER_DIRECTORY_MAX_STALE_HOURS", 24)

    # ── Session cookie ────────────────────────────────────────────────────────
    session_cookie_secure: bool = _env_bool("KYBER_SESSION_COOKIE_SECURE", _KYBER_DEFAULT_ON)


# ---------------------------------------------------------------------------
# Runtime roles, deployment profile & backend selectors (PR 4 / FT-4).
#
# AETHER_ROLE selects which slice of the process runs: the HTTP API server, a
# specific class of background worker, or (default) EVERYTHING in one process.
# The single-process "all" role is the local/dev default and stays behaviourally
# identical to today. Non-local deployments run explicit roles so the API
# process no longer starts every worker, consumer, and cron in-request.
#
# Backend selectors declare which concrete backend each subsystem binds to;
# PRODUCTION rejects in-memory backends (a memory cache/database is never a
# correctness source in production). See services/runtime/roles.py for the
# role → worker mapping and docs/BACKEND-EXECUTION-MODEL.md.
# ---------------------------------------------------------------------------

# Canonical set of runtime roles accepted by AETHER_ROLE / run_role. "all" is
# the single-process default (local/dev); "api" is the pure HTTP server; the
# worker classes are split out of the request lifecycle; and "lean-worker" is
# the consolidated execution group that packs every worker role into a single
# task for the cost-capped profiles (see services/runtime/roles.py::
# EXECUTION_GROUPS). Packing is a deployment decision only — each hosted role
# keeps its own queue, consumer group, DLQ and metrics label.
#
# tests/unit/test_runtime_roles.py asserts this set equals roles.ALL_ROLES.
# That is not busywork: this is the set AETHER_ROLE is validated against, so a
# role present in roles.py but missing here is a task that refuses to boot.
RUNTIME_ROLES: frozenset[str] = frozenset(
    {
        "api",
        "outbox-relay",
        "stream-worker",
        "identity-worker",
        "graph-writer",
        "measurement-worker",
        "semantic-worker",
        "materializer",
        "maintenance",
        "lean-worker",
        "all",
    }
)


@dataclass(frozen=True)
class RuntimeConfig:
    """Runtime role selection, deployment profile, and backend selectors."""

    # Which slice of the process to run. "all" (default) = single-process;
    # explicit roles required in staging/production (see __post_init__).
    aether_role: str = _env("AETHER_ROLE", "all")
    # Deployment profile label — drives compose/helm wiring & ops tooling.
    deployment_profile: str = _env("DEPLOYMENT_PROFILE", "local-live")

    # Backend selectors — the concrete backend each subsystem binds to.
    database_backend: str = _env("DATABASE_BACKEND", "postgres")
    cache_backend: str = _env("CACHE_BACKEND", "memory")
    event_backend: str = _env("EVENT_BACKEND", "sns_sqs")
    graph_backend: str = _env("GRAPH_BACKEND", "postgres")
    analytics_backend: str = _env("ANALYTICS_BACKEND", "postgres")
    object_backend: str = _env("OBJECT_BACKEND", "s3")
    ml_mode: str = _env("ML_MODE", "inline")

    # Master switch for the role-aware worker/consumer gating in the FastAPI
    # lifespan. Default-ON for non-local so the API process stops starting every
    # worker; OFF keeps the historical single-process lifespan byte-identical.
    worker_roles_enabled: bool = _env_bool("WORKER_ROLES_ENABLED", _TRUST_DEFAULT_ON)

    @property
    def allowed_roles(self) -> frozenset[str]:
        """The validated set of role tokens AETHER_ROLE may take."""
        return RUNTIME_ROLES

    @property
    def is_api_role(self) -> bool:
        return self.aether_role == "api"

    @property
    def is_all_role(self) -> bool:
        return self.aether_role == "all"


# ---------------------------------------------------------------------------
# Server-authoritative consent enforcement (PR 3) — consent as authority.
#
# Under the founding-tenant posture the SERVER consent-receipt store, not the
# SDK per-event `context.consent` snapshot, is the source of truth for whether
# ingestion may process an event. Absence of a server receipt is NOT permission
# (fail-closed). These flags follow the trust-plane default: ON in
# staging/production and OFF in local/dev, so existing local ingestion tests
# keep the legacy SDK-snapshot behavior. Explicit env var always wins.
#   - authoritative_consent_enforcement_enabled: /v1/batch consults the server
#     ConsentReceipt store via services.consent.authority.evaluate_consent and
#     rejects events with a stable rejection code when not allowed.
#   - tenant_compliance_policy_enabled: evaluate_data_policy consults the
#     tenant compliance profile and rejects prohibited data classes.
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ConsentAuthorityConfig:
    authoritative_consent_enforcement_enabled: bool = _env_bool(
        "AUTHORITATIVE_CONSENT_ENFORCEMENT_ENABLED", _TRUST_DEFAULT_ON
    )
    tenant_compliance_policy_enabled: bool = _env_bool(
        "TENANT_COMPLIANCE_POLICY_ENABLED", _TRUST_DEFAULT_ON
    )


# ---------------------------------------------------------------------------
# Semantic Intelligence — durable semantic/sentiment pipeline.
#
# All flags default OFF/inert in local so `make ci-check` and unit tests keep
# the deterministic in-memory store and never spin up the worker or hit a DB.
#   - durable_store_enabled: inject the Postgres-backed semantic store at
#     startup (ON in staging/prod). Local keeps the in-memory default.
#   - the semantic-worker ConsumerSpec on SDK_EVENTS_VALIDATED attaches whenever
#     that role (or local `all`) runs — deploying the role is the enable switch.
#   - replay_enabled / reconciler_enabled / retention_enabled: Phase B workers.
#   - classifier_provider: "deterministic" (default, tool-less, CI-safe),
#     "production" / "multilingual" (fail closed without creds), or "disabled".
#   - shadow_provider: candidate provider mode run IN SHADOW alongside the
#     primary ('' = off). Divergences are recorded to
#     semantic_shadow_divergences; the shadow never affects the primary write.
#   - canary_tenants: tenants routed to the candidate (production) classifier,
#     fail-closed without creds (mirrors IngestionV2Config.canary_tenants).
#   - subject_confidence_threshold: below this a resolution enters the review
#     queue instead of asserting a canonical subject.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SemanticIntelligenceConfig:
    durable_store_enabled: bool = _env_bool("SEMANTIC_DURABLE_STORE_ENABLED", _TRUST_DEFAULT_ON)
    replay_enabled: bool = _env_bool("SEMANTIC_REPLAY_ENABLED", False)
    reconciler_enabled: bool = _env_bool("SEMANTIC_RECONCILER_ENABLED", False)
    retention_enabled: bool = _env_bool("SEMANTIC_RETENTION_ENABLED", False)
    classifier_provider: str = _env("SEMANTIC_CLASSIFIER_PROVIDER", "deterministic")
    shadow_provider: str = _env("SEMANTIC_SHADOW_PROVIDER", "")
    canary_tenants: list[str] = field(
        default_factory=lambda: _env_list("SEMANTIC_CANARY_TENANTS", "")
    )
    subject_confidence_threshold: float = float(
        _env("SEMANTIC_SUBJECT_CONFIDENCE_THRESHOLD", "0.5")
    )


# ---------------------------------------------------------------------------
# Integration consent governance — additive, default-off rollout controls.
#
# These names are generated into the public integration-consent contract. The
# runtime settings mirror that contract exactly so code never infers rollout
# state from generated constants. The connector policy gate is only consulted
# when both it and the V2 control plane are enabled; flag-off behavior remains
# the existing connector behavior.
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class IntegrationConsentConfig:
    control_plane_v2_enabled: bool = _env_bool(
        "AETHER_CONSENT_CONTROL_PLANE_V2", False
    )
    connector_policy_gate_enabled: bool = _env_bool(
        "AETHER_CONNECTOR_POLICY_GATE", False
    )
    integration_discovery_enabled: bool = _env_bool(
        "AETHER_INTEGRATION_DISCOVERY", False
    )
    preference_center_v1_enabled: bool = _env_bool(
        "AETHER_PREFERENCE_CENTER_V1", False
    )
    checkout_hardening_v1_enabled: bool = _env_bool(
        "AETHER_CHECKOUT_HARDENING_V1", False
    )
    consent_lifecycle_enforcement_enabled: bool = _env_bool(
        "AETHER_CONSENT_LIFECYCLE_ENFORCEMENT", False
    )


# ---------------------------------------------------------------------------
# Credential platform — provider-neutral credential storage backend selector.
#
# ``backend`` chooses the concrete CredentialBackend (shared/credentials):
#   in_memory           — tests only (non-durable process dict)
#   local_encrypted     — default; Fernet-encrypted rows in tenant_credentials
#   aws_secrets_manager — AWS Secrets Manager (lazy boto3)
# ``aws_secret_prefix`` namespaces secrets when the AWS backend is selected.
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class CredentialPlatformConfig:
    backend: str = _env("AETHER_CREDENTIAL_BACKEND", "local_encrypted")
    aws_secret_prefix: str = _env("AETHER_CREDENTIAL_AWS_PREFIX", "aether/credentials")


# ---------------------------------------------------------------------------
# Ingestion V2 (PR 5) — typed Bronze + transactional outbox for /v1/batch.
#
# Canary rollout, default OFF. When `enabled` is True (or the request's tenant
# is listed in `canary_tenants`), POST /v1/batch routes to the V2 path:
# bulk-insert typed Bronze + the transactional outbox in ONE transaction, with
# DB uniqueness (not Redis) as the idempotency source of truth. The existing V1
# path is unchanged and used for every other tenant. `outbox_relay_enabled` is
# config-only here; the relay WORKER that drains event_outbox to the bus is a
# later PR (PR 6).
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class IngestionV2Config:
    enabled: bool = _env_bool("INGESTION_V2_ENABLED", False)
    canary_tenants: list[str] = field(
        default_factory=lambda: _env_list("INGESTION_V2_CANARY_TENANTS", "")
    )
    # Envelope required-field enforcement (staged): when ON, release-critical
    # events missing any of context.sequence / schemaVersion / surface are
    # rejected with reason `envelope_missing:<field>` (see
    # services/ingestion/validation.py). Default derives from the release
    # profile, same mechanism as ROUTE_REGISTRY_ENFORCED / _TRUST_DEFAULT_ON:
    # OFF in local/dev/integration (older SDK payloads without the canonical
    # envelope v1 stay accepted, promotion remains downstream), ON in the
    # staging/production ingestion profile. Explicit env var always wins, so
    # the enforcement can be rolled back per environment without a code change.
    envelope_required_fields_enforced: bool = _env_bool(
        "INGESTION_ENVELOPE_REQUIRED_FIELDS_ENFORCED",
        _env("AETHER_ENV", "local") in ("staging", "production"),
    )
    outbox_relay_enabled: bool = _env_bool("OUTBOX_RELAY_ENABLED", False)
    # Relay tuning (PR 6 / FT-6): claim batch size, idle poll cadence, claim
    # lease duration (crashed relays release rows when the lease lapses) and
    # the attempt ceiling after which a row is parked in dead_letter.
    outbox_relay_batch_size: int = _env_int("OUTBOX_RELAY_BATCH_SIZE", 100)
    outbox_relay_poll_interval_s: int = _env_int("OUTBOX_RELAY_POLL_INTERVAL_S", 2)
    outbox_relay_lease_seconds: int = _env_int("OUTBOX_RELAY_LEASE_SECONDS", 60)
    outbox_relay_max_attempts: int = _env_int("OUTBOX_RELAY_MAX_ATTEMPTS", 8)


# ---------------------------------------------------------------------------
# Storage Plane (PR 7 / FT-7 + PR 8 / FT-8) — Elastic Data Plane descriptor +
# object layer, object-backed Bronze compaction, and cross-store lifecycle.
#
# All flags default OFF/inert in local. The storage-policy registry itself
# (config/storage_policies.yaml) is always enforced by CI regardless of these
# flags; they gate only the RUNTIME behaviors:
#   - externalization_enabled: master switch for StorageManager.externalize()
#     writing packed objects to the object store. Per-resource-type permission
#     still comes from the policy registry (allow_object_externalization).
#   - reconciler_enabled: scheduling switch for the storage reconciler that
#     diffs the descriptor index against the object store (missing / orphan /
#     checksum-drift detection). Scheduled by the bronze_object_compaction
#     worker loop (services/storage_lifecycle/worker.py).
#   - object_bucket: S3 bucket for externalized objects when
#     settings.runtime.object_backend == "s3" (fail-closed: required then).
#   - bronze_compaction_enabled: FT-8 write path — pack cold Bronze payloads
#     into objects (hot searchable metadata always stays in Postgres).
#     Compaction only runs when externalization_enabled is ALSO true.
#   - bronze_compaction_min_age_hours / _batch_size / _interval_s: compaction
#     sweep tuning (only rows older than the age threshold are packed).
#   - lifecycle_retention_enabled: FT-8 retention — the retention sweep worker
#     additionally ages out externalized objects + Bronze rows per the policy
#     registry's retention_class/delete_behavior (legal holds always block).
#   - retention_standard_days: age applied to retention_class "standard"
#     resources by the storage-plane lifecycle (legal class is never swept).
#   - retention_short_lived_days: age applied to retention_class "short_lived"
#     resources — operational state (workforce sessions, step-up grants,
#     single-use WebAuthn / device-proof challenges) that must NOT inherit the
#     standard year-long window. Deliberately short; legal class is still
#     never swept.
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class StoragePlaneConfig:
    externalization_enabled: bool = _env_bool("STORAGE_EXTERNALIZATION_ENABLED", False)
    reconciler_enabled: bool = _env_bool("STORAGE_RECONCILER_ENABLED", False)
    object_bucket: str = _env("STORAGE_OBJECT_BUCKET", "")
    bronze_compaction_enabled: bool = _env_bool("BRONZE_OBJECT_COMPACTION_ENABLED", False)
    bronze_compaction_min_age_hours: int = _env_int("BRONZE_COMPACTION_MIN_AGE_HOURS", 72)
    bronze_compaction_batch_size: int = _env_int("BRONZE_COMPACTION_BATCH_SIZE", 500)
    bronze_compaction_interval_s: int = _env_int("BRONZE_COMPACTION_INTERVAL_S", 3600)
    lifecycle_retention_enabled: bool = _env_bool("STORAGE_LIFECYCLE_RETENTION_ENABLED", False)
    retention_standard_days: int = _env_int("STORAGE_RETENTION_STANDARD_DAYS", 365)
    retention_short_lived_days: int = _env_int("STORAGE_RETENTION_SHORT_LIVED_DAYS", 7)


# ---------------------------------------------------------------------------
# Data Quality, Drift Detection & Graph Intelligence Reliability
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class DataQualityConfig:
    """Tenant-facing data-quality views + Kyber intelligence-quality command
    center. Both default OFF; routes mount only when enabled."""
    enabled: bool = _env_bool("AETHER_DATA_QUALITY_ENABLED", False)
    kyber_intelligence_quality_enabled: bool = _env_bool("KYBER_INTELLIGENCE_QUALITY_ENABLED", False)
    watch_threshold: float = float(_env("AETHER_DATA_QUALITY_WATCH_THRESHOLD", "0.8"))
    critical_threshold: float = float(_env("AETHER_DATA_QUALITY_CRITICAL_THRESHOLD", "0.6"))


# ---------------------------------------------------------------------------
# External billing / payment provider readiness (behind flags)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ExternalBillingConfig:
    """Provider-safe external billing integration. Defaults to internal-only; no
    external billing env vars are required for local dev unless sync is enabled.
    The internal billing/revops layer is unaffected when these are off."""
    external_billing_enabled: bool = _env_bool("AETHER_EXTERNAL_BILLING_ENABLED", False)
    stripe_billing_enabled: bool = _env_bool("AETHER_STRIPE_BILLING_ENABLED", False)
    kyber_provider_sync_enabled: bool = _env_bool("KYBER_BILLING_PROVIDER_SYNC_ENABLED", False)
    provider_mode: str = _env("BILLING_PROVIDER_MODE", "internal_only")
    stripe_secret_key: str = _env("STRIPE_SECRET_KEY", "")
    stripe_webhook_secret: str = _env("STRIPE_WEBHOOK_SECRET", "")
    stripe_product_mapping_json: str = _env("STRIPE_PRODUCT_MAPPING_JSON", "")
    stripe_price_mapping_json: str = _env("STRIPE_PRICE_MAPPING_JSON", "")


# ---------------------------------------------------------------------------
# Partner ecosystem / marketplace / developer platform — FUTURE-FLAGGED ONLY
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class PartnerEcosystemConfig:
    """Partner ecosystem, marketplace, and developer platform are intentionally
    NOT implemented in this pass. These flags default OFF and gate nothing yet;
    they exist so the work can be shipped later without a config migration."""
    partner_ecosystem_enabled: bool = _env_bool("AETHER_PARTNER_ECOSYSTEM_ENABLED", False)
    marketplace_enabled: bool = _env_bool("AETHER_MARKETPLACE_ENABLED", False)
    developer_platform_enabled: bool = _env_bool("AETHER_DEVELOPER_PLATFORM_ENABLED", False)
    kyber_partner_ecosystem_enabled: bool = _env_bool("KYBER_PARTNER_ECOSYSTEM_ENABLED", False)


# ---------------------------------------------------------------------------
# Inbound data-provider / connector ingestion
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ConnectorsConfig:
    """Non-SDK connector ingestion. Master switch is OFF by default; per-connector
    enablement is per-tenant config (also off by default). Provider credentials
    are required only when a connector is enabled for a tenant."""
    enabled: bool = _env_bool("AETHER_CONNECTORS_ENABLED", False)
    kyber_connector_health_enabled: bool = _env_bool("KYBER_CONNECTOR_HEALTH_ENABLED", False)


# ---------------------------------------------------------------------------
# Provider Corpus & Data Lake (Olympus-owned sources + Dune)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ProviderCorpusConfig:
    """Olympus-owned provider corpus and data lake feature flags.

    All flags default False (fail-closed). Safety policy gates (data rights
    fail-closed checks, provenance quarantine) are NOT behind these flags —
    they are always active regardless of flag state.
    """
    # Connector taxonomy
    connector_data_rights_enabled: bool = _env_bool("AETHER_CONNECTOR_DATA_RIGHTS_ENABLED", False)
    connector_byok_enabled: bool = _env_bool("AETHER_CONNECTOR_BYOK_ENABLED", True)
    connector_actions_enabled: bool = _env_bool("AETHER_CONNECTOR_ACTIONS_ENABLED", False)
    connector_olympus_providers_enabled: bool = _env_bool("AETHER_CONNECTOR_OLYMPUS_PROVIDERS_ENABLED", False)

    # Provider source catalog
    provider_source_catalog_enabled: bool = _env_bool("AETHER_PROVIDER_SOURCE_CATALOG_ENABLED", False)
    kyber_provider_source_catalog_enabled: bool = _env_bool("KYBER_PROVIDER_SOURCE_CATALOG_ENABLED", False)
    provider_sync_enabled: bool = _env_bool("AETHER_PROVIDER_SYNC_ENABLED", False)

    # Dune access modes
    dune_datashare_enabled: bool = _env_bool("AETHER_DUNE_DATASHARE_ENABLED", False)
    dune_api_enabled: bool = _env_bool("AETHER_DUNE_API_ENABLED", False)
    dune_sim_enabled: bool = _env_bool("AETHER_DUNE_SIM_ENABLED", False)

    # Cost and rate-limit tracking
    provider_cost_profiles_enabled: bool = _env_bool("AETHER_PROVIDER_COST_PROFILES_ENABLED", False)
    provider_rate_limit_profiles_enabled: bool = _env_bool("AETHER_PROVIDER_RATE_LIMIT_PROFILES_ENABLED", False)

    # Lake provenance and lineage
    enrichment_lineage_enabled: bool = _env_bool("AETHER_ENRICHMENT_LINEAGE_ENABLED", False)
    graph_of_graphs_policy_enabled: bool = _env_bool("AETHER_GRAPH_OF_GRAPHS_POLICY_ENABLED", False)

    # Unique signal features
    unique_signal_features_enabled: bool = _env_bool("AETHER_UNIQUE_SIGNAL_FEATURES_ENABLED", False)

    # Anti-distillation controls
    anti_distillation_enabled: bool = _env_bool("AETHER_ANTI_DISTILLATION_ENABLED", False)
    kyber_anti_distillation_enabled: bool = _env_bool("KYBER_ANTI_DISTILLATION_ENABLED", False)


# ---------------------------------------------------------------------------
# OODA Suggestion Intelligence
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SuggestionsConfig:
    """Unified OODA Suggestion Intelligence layer. Master switch is OFF by
    default. Execution is a separate hard gate (also OFF by default) so
    suggestions can be created, reviewed, and delivered without enabling
    automated execution. Noesis read-only suggestion queries are independent
    of the main `enabled` flag but respect `noesis_enabled`."""
    enabled: bool = _env_bool("AETHER_SUGGESTIONS_ENABLED", False)
    auto_delivery_enabled: bool = _env_bool("AETHER_SUGGESTIONS_AUTODELIVERY_ENABLED", False)
    execution_enabled: bool = _env_bool("AETHER_SUGGESTIONS_EXECUTION_ENABLED", False)
    noesis_enabled: bool = _env_bool("AETHER_SUGGESTIONS_NOESIS_ENABLED", True)
    recommendation_adapter_enabled: bool = _env_bool("AETHER_SUGGESTIONS_RECOMMENDATION_ADAPTER_ENABLED", True)
    notification_adapter_enabled: bool = _env_bool("AETHER_SUGGESTIONS_NOTIFICATION_ADAPTER_ENABLED", True)
    data_quality_adapter_enabled: bool = _env_bool("AETHER_SUGGESTIONS_DATA_QUALITY_ADAPTER_ENABLED", True)
    sdk_health_adapter_enabled: bool = _env_bool("AETHER_SUGGESTIONS_SDK_HEALTH_ADAPTER_ENABLED", True)
    graph_adapter_enabled: bool = _env_bool("AETHER_SUGGESTIONS_GRAPH_ADAPTER_ENABLED", True)
    # Economic/interoperability adapters default OFF (fail-closed with their domains)
    stablecoin_adapter_enabled: bool = _env_bool("AETHER_SUGGESTIONS_STABLECOIN_ADAPTER_ENABLED", False)
    derivatives_adapter_enabled: bool = _env_bool("AETHER_SUGGESTIONS_DERIVATIVES_ADAPTER_ENABLED", False)
    interop_adapter_enabled: bool = _env_bool("AETHER_SUGGESTIONS_INTEROP_ADAPTER_ENABLED", False)
    kyber_enabled: bool = _env_bool("KYBER_SUGGESTIONS_ENABLED", True)
    tenant_enabled: bool = _env_bool("AETHER_TENANT_SUGGESTIONS_ENABLED", True)


# ---------------------------------------------------------------------------
# Fraud Network Intelligence
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class FraudIntelligenceConfig:
    fraud_networks_enabled: bool = _env_bool("FEATURE_FRAUD_NETWORKS", False)
    flow_trace_enabled: bool = _env_bool("FEATURE_FLOW_TRACE", False)
    risk_overlays_enabled: bool = _env_bool("FEATURE_RISK_OVERLAYS", False)
    kyber_fraud_workspace_enabled: bool = _env_bool("FEATURE_KYBER_FRAUD_WORKSPACE", False)
    tenant_fraud_intelligence_enabled: bool = _env_bool("FEATURE_TENANT_FRAUD_INTELLIGENCE", False)
    alert_risk_threshold: float = float(_env("FRAUD_ALERT_RISK_THRESHOLD", "70.0"))
    max_network_depth: int = _env_int("FRAUD_NETWORK_MAX_DEPTH", 4)
    max_flow_trace_hops: int = _env_int("FLOW_TRACE_MAX_HOPS", 10)


# ---------------------------------------------------------------------------
# Delivery Worker
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class DeliveryConfig:
    """Durable delivery worker configuration.

    Controls the DeliveryWorker poll loop, lease window, and retry behaviour.
    Provider credentials are resolved from the vault (ProvidersRepository)
    via secret_ref — never stored in this config.
    """
    enabled: bool = _env_bool("AETHER_DELIVERY_WORKER_ENABLED", True)
    batch_size: int = _env_int("DELIVERY_WORKER_BATCH_SIZE", 10)
    lease_seconds: int = _env_int("DELIVERY_WORKER_LEASE_SECONDS", 120)
    poll_interval_seconds: float = float(_env("DELIVERY_WORKER_POLL_INTERVAL_S", "5"))
    max_attempts: int = _env_int("DELIVERY_WORKER_MAX_ATTEMPTS", 5)

    # Slack provider config (system-level default; per-tenant configured in UserNotificationChannel)
    slack_bot_token: str = _env("DELIVERY_SLACK_BOT_TOKEN", "")
    slack_default_channel: str = _env("DELIVERY_SLACK_DEFAULT_CHANNEL", "#aether-notifications")

    # Webhook signing secret (for outbound X-Aether-Signature)
    webhook_signing_secret: str = _env("DELIVERY_WEBHOOK_SIGNING_SECRET", "")

    # Linear API key (system-level default)
    linear_api_key: str = _env("DELIVERY_LINEAR_API_KEY", "")

    # Jira (system-level default; per-tenant configured in connector config)
    jira_base_url: str = _env("DELIVERY_JIRA_BASE_URL", "")
    jira_email: str = _env("DELIVERY_JIRA_EMAIL", "")
    jira_api_token: str = _env("DELIVERY_JIRA_API_TOKEN", "")


# ---------------------------------------------------------------------------
# Master settings
# ---------------------------------------------------------------------------

@dataclass
class AgenticObservabilityConfig:
    enabled: bool = _env_bool("AGENTIC_OBSERVABILITY_ENABLED", True)
    mcp_enabled: bool = _env_bool("AGENTIC_MCP_OBSERVABILITY_ENABLED", True)
    external_accounts_enabled: bool = _env_bool("AGENTIC_EXTERNAL_ACCOUNTS_ENABLED", True)
    provider_verification_enabled: bool = _env_bool("AGENTIC_PROVIDER_VERIFICATION_ENABLED", False)
    communication_enabled: bool = _env_bool("AGENTIC_COMMUNICATION_OBSERVABILITY_ENABLED", True)
    protocol_enabled: bool = _env_bool("AGENTIC_PROTOCOL_OBSERVABILITY_ENABLED", True)
    kyber_enabled: bool = _env_bool("KYBER_AGENTIC_OBSERVABILITY_ENABLED", True)


@dataclass(frozen=True)
class AgenticObservabilityIngestionConfig:
    """Routes agentic observations through the canonical durable ingestion spine
    (typed Bronze + event_outbox → relay → SilverDispatcher → projectors) instead
    of the legacy per-service repo + synchronous graph write.

    Default OFF. When ``canonical_spine_enabled`` is True (or the request's tenant
    is listed in ``canary_tenant_ids``), agentic routes delegate to
    ``services.agentic_observability.pipeline.ingest_observation`` and graph
    projection happens asynchronously via the relay. Every other tenant keeps the
    existing synchronous path unchanged.
    """
    canonical_spine_enabled: bool = _env_bool("AGENTIC_OBS_CANONICAL_SPINE_ENABLED", False)
    canary_tenant_ids: tuple[str, ...] = field(
        default_factory=lambda: tuple(_env_list("AGENTIC_OBS_CANONICAL_SPINE_CANARY_TENANTS"))
    )


@dataclass(frozen=True)
class StablecoinIntelligenceConfig:
    """Safe rollout flags for Stablecoin Intelligence.

    Defaults are OFF until PR2-PR4 provide verified ingestion, Profile360,
    product surfaces, Kyber operations, Olympus benchmarks, and release evidence.
    """
    enabled: bool = _env_bool("AETHER_STABLECOIN_INTELLIGENCE_ENABLED", False)
    profile360_enabled: bool = _env_bool("AETHER_STABLECOIN_PROFILE360_ENABLED", False)
    attribution_enabled: bool = _env_bool("AETHER_STABLECOIN_ATTRIBUTION_ENABLED", False)
    support_enabled: bool = _env_bool("AETHER_STABLECOIN_SUPPORT_ENABLED", False)
    market_enabled: bool = _env_bool("AETHER_STABLECOIN_MARKET_ENABLED", False)
    alerts_enabled: bool = _env_bool("AETHER_STABLECOIN_ALERTS_ENABLED", False)
    realtime_enabled: bool = _env_bool("AETHER_STABLECOIN_REALTIME_ENABLED", False)
    kyber_operations_enabled: bool = _env_bool("KYBER_STABLECOIN_OPERATIONS_ENABLED", False)
    olympus_benchmarks_enabled: bool = _env_bool("OLYMPUS_STABLECOIN_BENCHMARKS_ENABLED", False)
    kill_switch: bool = _env_bool("AETHER_STABLECOIN_KILL_SWITCH", False)
    shadow_mode: bool = _env_bool("AETHER_STABLECOIN_SHADOW_MODE", True)
    # Usage metering on the stablecoin observation path (default OFF, opt-in).
    # Accept-then-meter, fail-open: records a RevOps usage-metering event AFTER an
    # observation is persisted, keyed by the deterministic observation_id so
    # replays dedupe; a metering-store failure never rejects/drops the
    # observation. Aether writes only its own billing bookkeeping.
    usage_metering_enabled: bool = _env_bool(
        "AETHER_STABLECOIN_USAGE_METERING_ENABLED", False
    )


@dataclass(frozen=True)
class ExternalAgentTelemetryConfig:
    """External Agent Telemetry Plane V1 rollout flags (default OFF).

    Aether observes telemetry from tenant-owned agents deployed on external
    surfaces. No marketplace, no agent hosting, no execution.
    """
    enabled: bool = _env_bool("AETHER_EXTERNAL_AGENT_TELEMETRY_ENABLED", False)
    kyber_enabled: bool = _env_bool("KYBER_EXTERNAL_AGENT_TELEMETRY_ENABLED", False)
    registry_enabled: bool = _env_bool("AETHER_AGENT_DEPLOYMENT_REGISTRY_ENABLED", False)
    sdk_enabled: bool = _env_bool("AETHER_AGENT_TELEMETRY_SDK_ENABLED", False)
    graph_enabled: bool = _env_bool("AETHER_AGENT_DEPLOYMENT_GRAPH_ENABLED", False)
    profile360_enabled: bool = _env_bool("AETHER_AGENT_DEPLOYMENT_PROFILE360_ENABLED", False)


@dataclass(frozen=True)
class PaymentRailsConfig:
    """Payment Rail Observability V1 rollout flags (default OFF).

    Named providers only — Privy, Stripe crypto onramp, Coinbase, MoonPay,
    Bridge. No generic webhook fallback. Aether observes and reconciles;
    it never executes or settles payments or custodies funds.
    """
    enabled: bool = _env_bool("AETHER_PAYMENT_RAILS_ENABLED", False)
    privy_enabled: bool = _env_bool("AETHER_PROVIDER_PRIVY_ENABLED", False)
    stripe_enabled: bool = _env_bool("AETHER_PROVIDER_STRIPE_ENABLED", False)
    coinbase_enabled: bool = _env_bool("AETHER_PROVIDER_COINBASE_ENABLED", False)
    moonpay_enabled: bool = _env_bool("AETHER_PROVIDER_MOONPAY_ENABLED", False)
    bridge_enabled: bool = _env_bool("AETHER_PROVIDER_BRIDGE_ENABLED", False)
    kyber_enabled: bool = _env_bool("KYBER_PAYMENT_RAILS_ENABLED", False)

    # Webhook admission controls (public endpoint hardening). Rate limiting is a
    # per-endpoint fixed-minute-window budget enforced before signature
    # verification so a flood of unverifiable bodies can't burn CPU on crypto;
    # denied webhooks (bad/stale signature, oversized body) are quarantined
    # metadata-only (sha256 + size, never the raw body) for forensics.
    webhook_rate_limit_enabled: bool = _env_bool(
        "AETHER_PAYMENT_WEBHOOK_RATE_LIMIT_ENABLED", True
    )
    webhook_rate_limit_per_minute: int = _env_int(
        "AETHER_PAYMENT_WEBHOOK_RATE_LIMIT_PER_MINUTE", 600
    )
    webhook_quarantine_denied: bool = _env_bool(
        "AETHER_PAYMENT_WEBHOOK_QUARANTINE_DENIED", True
    )
    # Consent gate on the payment-rails observation path (default OFF, opt-in).
    # When enabled, a normalized funding session is persisted/emitted only when
    # its subject (user_id) has granted the ``commerce`` consent purpose; a denied
    # observation is dropped (never persisted) and recorded metadata-only. A
    # session with no resolvable subject is allowed (there is no subject whose
    # consent could be evaluated). Fails closed: a missing consent record or an
    # unavailable consent store denies the observation.
    webhook_consent_gate_enabled: bool = _env_bool(
        "AETHER_PAYMENT_WEBHOOK_CONSENT_GATE_ENABLED", False
    )
    # Canonical-event delivery path (default OFF, opt-in). When enabled, implied
    # payment_* canonical events are written atomically to the durable Bronze +
    # event_outbox spine (ingest_many) — the supervised outbox relay publishes
    # them to the validated-events bus — instead of a direct EventProducer.publish.
    # The deterministic canonical event id is the Bronze/outbox key, so a retry is
    # a no-op (ingest_many writes an outbox row only for a newly-accepted Bronze
    # row). Default OFF keeps the direct-publish path until the relay is validated
    # end-to-end for this source.
    canonical_outbox_enabled: bool = _env_bool(
        "AETHER_PAYMENT_CANONICAL_OUTBOX_ENABLED", False
    )
    # Usage metering on the observation path (default OFF, opt-in). When enabled,
    # an accept-then-meter, fail-open hook records a RevOps usage-metering event
    # AFTER a payment_* canonical event is emitted — keyed by the deterministic
    # canonical event id so replays dedupe. A metering-store failure is swallowed
    # and never rejects or drops the observation (billing-outage-safe). Aether
    # only writes its own billing bookkeeping — never provider state.
    usage_metering_enabled: bool = _env_bool(
        "AETHER_PAYMENT_USAGE_METERING_ENABLED", False
    )


@dataclass(frozen=True)
class CardLinkedPaymentRailsConfig:
    """Card-linked payment rail observability V1 rollout and safety flags.

    Default-off observation surfaces for card-linked activity. PaymentScan is
    catalog/benchmark-only unless tenant-authorized provider evidence exists.
    EU/APAC restricted modes and provider PII blocking default on.
    """
    enabled: bool = _env_bool("AETHER_CARD_LINKED_PAYMENT_RAILS_ENABLED", False)
    paymentscan_catalog_enabled: bool = _env_bool("AETHER_PAYMENTSCAN_CATALOG_ENABLED", False)
    paymentscan_benchmarks_enabled: bool = _env_bool("AETHER_PAYMENTSCAN_BENCHMARKS_ENABLED", False)
    profile360_enabled: bool = _env_bool("AETHER_CARD_LINKED_PROFILE360_ENABLED", False)
    campaign_attribution_enabled: bool = _env_bool("AETHER_CARD_LINKED_CAMPAIGN_ATTRIBUTION_ENABLED", False)
    clustering_enabled: bool = _env_bool("AETHER_CARD_LINKED_CLUSTERING_ENABLED", False)
    kyber_enabled: bool = _env_bool("KYBER_CARD_LINKED_PAYMENT_RAILS_ENABLED", False)
    eu_restricted_mode: bool = _env_bool("AETHER_CARD_LINKED_EU_RESTRICTED_MODE", True)
    apac_restricted_mode: bool = _env_bool("AETHER_CARD_LINKED_APAC_RESTRICTED_MODE", True)
    provider_pii_block: bool = _env_bool("AETHER_CARD_LINKED_PROVIDER_PII_BLOCK", True)


@dataclass(frozen=True)
class AIEconomicsConfig:
    """AI Outcome Efficiency / AI Economics rollout flags (default OFF).

    Observes AI execution facts, prices cost from effective-dated price
    cards, aggregates workflow/outcome economics, and generates governed
    efficiency recommendations. Never changes production models, prompts,
    or routing.
    """
    enabled: bool = _env_bool("AETHER_AI_OUTCOME_EFFICIENCY_ENABLED", False)
    execution_facts_enabled: bool = _env_bool("AETHER_AI_EXECUTION_FACTS_ENABLED", False)
    economics_enabled: bool = _env_bool("AETHER_AI_ECONOMICS_ENABLED", False)
    recommendations_enabled: bool = _env_bool("AETHER_AI_EFFICIENCY_RECOMMENDATIONS_ENABLED", False)
    kyber_enabled: bool = _env_bool("KYBER_AI_EFFICIENCY_HEALTH_ENABLED", False)


@dataclass(frozen=True)
class TargetingIntelligenceConfig:
    """Cluster Targeting Intelligence rollout flags (default OFF).

    Observation-first: Aether observes targeting, leakage, holdouts, and
    journey deltas and generates OODA suggestions/export packages. It never
    executes campaigns or targets inside external platforms.
    """
    enabled: bool = _env_bool("AETHER_CLUSTER_TARGETING_INTELLIGENCE_ENABLED", False)
    exports_enabled: bool = _env_bool("AETHER_TARGETING_EXPORTS_ENABLED", False)
    ooda_suggestions_enabled: bool = _env_bool("AETHER_TARGETING_OODA_SUGGESTIONS_ENABLED", False)
    kyber_enabled: bool = _env_bool("KYBER_TARGETING_INTELLIGENCE_ENABLED", False)


@dataclass(frozen=True)
class OnePersonOpsConfig:
    """Aether/Kyber one-person operations rollout flags (default OFF).

    Worker execution bridge, durable runtime, staged graph mutation
    review-to-commit, Catalyst/Cycle automation, and the Kyber agent
    command center. Human approval gates are never removed by these flags.
    """
    runtime_durable_enabled: bool = _env_bool("AETHER_AGENT_RUNTIME_DURABLE_ENABLED", False)
    worker_bridge_enabled: bool = _env_bool("AETHER_AGENT_WORKER_BRIDGE_ENABLED", False)
    staged_mutation_review_enabled: bool = _env_bool("AETHER_STAGED_GRAPH_MUTATION_REVIEW_ENABLED", False)
    catalyst_cycle_enabled: bool = _env_bool("AETHER_CATALYST_CYCLE_AUTOMATION_ENABLED", False)
    command_center_enabled: bool = _env_bool("KYBER_AGENT_COMMAND_CENTER_ENABLED", False)
    one_person_ops_enabled: bool = _env_bool("KYBER_ONE_PERSON_OPS_ENABLED", False)


@dataclass(frozen=True)
class StablecoinDomainConfig:
    """Stablecoin economic-intelligence domain rollout flags
    (services/stablecoin — coexists with the observer-stack
    StablecoinIntelligenceConfig above). Observation-only domain —
    all flags default False (fail-closed) until staging validation."""
    ingestion_enabled: bool = _env_bool("AETHER_STABLECOIN_INGESTION_ENABLED", False)
    valuation_enabled: bool = _env_bool("AETHER_STABLECOIN_VALUATION_ENABLED", False)
    flows_enabled: bool = _env_bool("AETHER_STABLECOIN_FLOWS_ENABLED", False)
    graph_enabled: bool = _env_bool("AETHER_STABLECOIN_GRAPH_ENABLED", False)
    profile360_enabled: bool = _env_bool("AETHER_STABLECOIN_PROFILE360_ENABLED", False)
    api_enabled: bool = _env_bool("AETHER_STABLECOIN_API_ENABLED", False)
    noesis_enabled: bool = _env_bool("AETHER_STABLECOIN_NOESIS_ENABLED", False)
    kyber_enabled: bool = _env_bool("KYBER_STABLECOIN_OPS_ENABLED", False)


@dataclass(frozen=True)
class DerivativesIntelligenceConfig:
    """Derivatives Intelligence rollout flags. Observation-only domain —
    no execution capability exists behind any flag. All default False."""
    runtime_enabled: bool = _env_bool("AETHER_DERIVATIVES_RUNTIME_ENABLED", False)
    adapters_enabled: bool = _env_bool("AETHER_DERIVATIVES_ADAPTERS_ENABLED", False)
    streams_enabled: bool = _env_bool("AETHER_DERIVATIVES_STREAMS_ENABLED", False)
    reconciliation_enabled: bool = _env_bool("AETHER_DERIVATIVES_RECONCILIATION_ENABLED", False)
    pnl_enabled: bool = _env_bool("AETHER_DERIVATIVES_PNL_ENABLED", False)
    graph_enabled: bool = _env_bool("AETHER_DERIVATIVES_GRAPH_ENABLED", False)
    profile360_enabled: bool = _env_bool("AETHER_DERIVATIVES_PROFILE360_ENABLED", False)
    api_enabled: bool = _env_bool("AETHER_DERIVATIVES_API_ENABLED", False)
    noesis_enabled: bool = _env_bool("AETHER_DERIVATIVES_NOESIS_ENABLED", False)
    kyber_enabled: bool = _env_bool("KYBER_DERIVATIVES_OPS_ENABLED", False)


@dataclass(frozen=True)
class InteropIntelligenceConfig:
    """Interoperability Intelligence rollout flags. Observation-only domain —
    Aether never relays, routes, or recovers messages. All default False."""
    ingestion_enabled: bool = _env_bool("AETHER_INTEROP_INGESTION_ENABLED", False)
    lifecycle_enabled: bool = _env_bool("AETHER_INTEROP_LIFECYCLE_ENABLED", False)
    adapters_enabled: bool = _env_bool("AETHER_INTEROP_ADAPTERS_ENABLED", False)
    layerzero_enabled: bool = _env_bool("AETHER_INTEROP_LAYERZERO_ENABLED", False)
    graph_enabled: bool = _env_bool("AETHER_INTEROP_GRAPH_ENABLED", False)
    profile360_enabled: bool = _env_bool("AETHER_INTEROP_PROFILE360_ENABLED", False)
    api_enabled: bool = _env_bool("AETHER_INTEROP_API_ENABLED", False)
    noesis_enabled: bool = _env_bool("AETHER_INTEROP_NOESIS_ENABLED", False)
    kyber_enabled: bool = _env_bool("KYBER_INTEROP_OPS_ENABLED", False)


# ---------------------------------------------------------------------------
# Unified Intelligence Plane — capability flags (all default OFF; safety
# defaults ON). New planes must add zero runtime cost while disabled: every
# consumer checks its flag before doing any work, and nothing here is read
# eagerly at import time by hot paths.
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class TemporalIntegrityConfig:
    """Strict-ingestion mode ladder: off → shadow → warn → enforce.

    Reason codes and meters are computed identically in every active mode so
    shadow telemetry predicts enforcement impact. Canary tenants get the
    configured mode while everyone else stays at ``off``.
    """

    enforcement_mode: str = _env("AETHER_TEMPORAL_ENFORCEMENT_MODE", "off")
    canary_tenants: list[str] = field(
        default_factory=lambda: _env_list("AETHER_TEMPORAL_CANARY_TENANTS", "")
    )
    viewer_preferences_enabled: bool = _env_bool(
        "AETHER_VIEWER_TIMEZONE_ENABLED", False
    )

    def mode_for_tenant(self, tenant_id: str) -> str:
        if self.enforcement_mode == "off":
            return "off"
        if not self.canary_tenants or tenant_id in self.canary_tenants:
            return self.enforcement_mode
        return "off"


@dataclass(frozen=True)
class ProductIntelligenceConfig:
    enabled: bool = _env_bool("AETHER_PRODUCT_INTELLIGENCE_ENABLED", False)
    catalog_enabled: bool = _env_bool("AETHER_PRODUCT_CATALOG_ENABLED", False)


@dataclass(frozen=True)
class ContextIntelligenceConfig:
    enrichment_enabled: bool = _env_bool("AETHER_CONTEXT_ENRICHMENT_ENABLED", False)
    capsule_enabled: bool = _env_bool("AETHER_CONTEXT_CAPSULES_ENABLED", False)
    # Safety defaults — ON. Raw IP must never persist; context/behavior alone
    # must never merge identities or cause adverse action.
    block_raw_ip: bool = _env_bool("AETHER_RAW_IP_PERSISTENCE_BLOCKED", True)
    location_identity_merge_blocked: bool = _env_bool(
        "AETHER_LOCATION_IDENTITY_MERGE_BLOCKED", True
    )
    trusted_proxy_cidrs: list[str] = field(
        default_factory=lambda: _env_list("AETHER_TRUSTED_PROXY_CIDRS", "")
    )
    cloudflare_proxy_enabled: bool = _env_bool(
        "AETHER_CLOUDFLARE_PROXY_ENABLED", False
    )
    ip_hmac_rotation_hours: int = _env_int("AETHER_IP_HMAC_ROTATION_HOURS", 24)


@dataclass(frozen=True)
class TemporalObservatoryConfig:
    enabled: bool = _env_bool("AETHER_TEMPORAL_OBSERVATORY_ENABLED", False)
    mutation_gateway_mode: str = _env("AETHER_MUTATION_GATEWAY_MODE", "off")


@dataclass(frozen=True)
class ExplorationConfig:
    enabled: bool = _env_bool("AETHER_EXPLORATION_ENABLED", False)


@dataclass(frozen=True)
class ComparisonConfig:
    enabled: bool = _env_bool("AETHER_COMPARISON_INTELLIGENCE_ENABLED", False)


@dataclass
class Settings:
    env: Environment = Environment(_env("AETHER_ENV", "local"))
    debug: bool = _env_bool("DEBUG", False)

    # Databases
    timescaledb: TimescaleDBConfig = field(default_factory=TimescaleDBConfig)
    neptune: NeptuneConfig = field(default_factory=NeptuneConfig)
    redis: RedisConfig = field(default_factory=RedisConfig)
    dynamodb: DynamoDBConfig = field(default_factory=DynamoDBConfig)
    opensearch: OpenSearchConfig = field(default_factory=OpenSearchConfig)

    # Infrastructure
    event_bus: EventBusConfig = field(default_factory=EventBusConfig)
    rate_limit: RateLimitConfig = field(default_factory=RateLimitConfig)
    api: APIConfig = field(default_factory=APIConfig)
    auth: AuthConfig = field(default_factory=AuthConfig)

    # Intelligence Graph
    intelligence_graph: IntelligenceGraphConfig = field(default_factory=IntelligenceGraphConfig)
    decision_outcome: DecisionOutcomeIntelligenceConfig = field(default_factory=DecisionOutcomeIntelligenceConfig)
    security_governance: SecurityGovernanceConfig = field(default_factory=SecurityGovernanceConfig)
    trust_plane: TrustPlaneConfig = field(default_factory=TrustPlaneConfig)
    route_registry: RouteRegistryConfig = field(default_factory=RouteRegistryConfig)
    kyber_workforce: KyberWorkforceConfig = field(default_factory=KyberWorkforceConfig)
    runtime: RuntimeConfig = field(default_factory=RuntimeConfig)
    consent_authority: ConsentAuthorityConfig = field(default_factory=ConsentAuthorityConfig)
    semantic: SemanticIntelligenceConfig = field(default_factory=SemanticIntelligenceConfig)
    integration_consent: IntegrationConsentConfig = field(default_factory=IntegrationConsentConfig)
    credential_platform: CredentialPlatformConfig = field(default_factory=CredentialPlatformConfig)
    ingestion_v2: IngestionV2Config = field(default_factory=IngestionV2Config)
    storage_plane: StoragePlaneConfig = field(default_factory=StoragePlaneConfig)
    quicknode: QuickNodeConfig = field(default_factory=QuickNodeConfig)
    stablecoin_intelligence: StablecoinIntelligenceConfig = field(default_factory=StablecoinIntelligenceConfig)

    # Communications Intelligence
    comms: CommsConfig = field(default_factory=CommsConfig)

    # Provider Gateway
    provider_gateway: ProviderGatewayConfig = field(default_factory=ProviderGatewayConfig)

    # Model Extraction Defense
    extraction_defense: ModelExtractionDefenseConfig = field(
        default_factory=ModelExtractionDefenseConfig,
    )

    # Extraction Defense Mesh
    extraction_mesh: ExtractionMeshConfig = field(
        default_factory=ExtractionMeshConfig,
    )

    # Email
    email: EmailConfig = field(default_factory=EmailConfig)

    # Auth0 / SSO
    auth0: Auth0Config = field(default_factory=Auth0Config)

    # Password / Email auth
    password_auth: PasswordAuthConfig = field(default_factory=PasswordAuthConfig)

    # Stripe Billing
    stripe_billing: StripeBillingConfig = field(default_factory=StripeBillingConfig)

    # ClickHouse (CIS telemetry warehouse)
    clickhouse: ClickHouseConfig = field(default_factory=ClickHouseConfig)

    # Cognitive Integrity System
    cis: CISConfig = field(default_factory=CISConfig)

    # Data Quality / Drift / Intelligence Quality
    data_quality: DataQualityConfig = field(default_factory=DataQualityConfig)

    # External billing / payment provider readiness (behind flags)
    external_billing: ExternalBillingConfig = field(default_factory=ExternalBillingConfig)

    # Partner ecosystem / marketplace / developer platform (future-flagged only)
    partner_ecosystem: PartnerEcosystemConfig = field(default_factory=PartnerEcosystemConfig)

    # Inbound connector ingestion (master switch; per-tenant config gates each)
    connectors: ConnectorsConfig = field(default_factory=ConnectorsConfig)

    # Olympus-owned provider corpus, Dune ingestion, data lake provenance, anti-distillation
    provider_corpus: ProviderCorpusConfig = field(default_factory=ProviderCorpusConfig)

    # OODA Suggestion Intelligence (disabled by default; execution gated separately)
    suggestions: SuggestionsConfig = field(default_factory=SuggestionsConfig)

    # Fraud Network Intelligence + Flow-of-Funds (disabled by default)
    fraud_intelligence: FraudIntelligenceConfig = field(default_factory=FraudIntelligenceConfig)

    # Delivery Worker (durable provider dispatch + outcome tracking)
    delivery: DeliveryConfig = field(default_factory=DeliveryConfig)

    # Agentic Intelligence observability rollout flags
    agentic_observability: AgenticObservabilityConfig = field(default_factory=AgenticObservabilityConfig)

    # Agentic observation ingestion through the canonical durable spine (default OFF)
    agentic_observability_ingestion: AgenticObservabilityIngestionConfig = field(
        default_factory=AgenticObservabilityIngestionConfig
    )

    # Stablecoin Intelligence rollout flags
    stablecoin_intelligence: StablecoinIntelligenceConfig = field(default_factory=StablecoinIntelligenceConfig)

    # External Agent Telemetry Plane rollout flags
    external_agent_telemetry: ExternalAgentTelemetryConfig = field(default_factory=ExternalAgentTelemetryConfig)

    # Payment Rail Observability rollout flags
    payment_rails: PaymentRailsConfig = field(default_factory=PaymentRailsConfig)
    card_linked_payment_rails: CardLinkedPaymentRailsConfig = field(default_factory=CardLinkedPaymentRailsConfig)

    # AI Outcome Efficiency / AI Economics rollout flags
    ai_economics: AIEconomicsConfig = field(default_factory=AIEconomicsConfig)

    # Cluster Targeting Intelligence rollout flags
    targeting_intelligence: TargetingIntelligenceConfig = field(default_factory=TargetingIntelligenceConfig)

    # One-person operations rollout flags
    one_person_ops: OnePersonOpsConfig = field(default_factory=OnePersonOpsConfig)

    # Stablecoin / Derivatives / Interoperability economic-intelligence domains
    stablecoin: StablecoinDomainConfig = field(default_factory=StablecoinDomainConfig)
    derivatives: DerivativesIntelligenceConfig = field(default_factory=DerivativesIntelligenceConfig)
    interop: InteropIntelligenceConfig = field(default_factory=InteropIntelligenceConfig)

    # Unified Intelligence Plane
    temporal_integrity: TemporalIntegrityConfig = field(default_factory=TemporalIntegrityConfig)
    product_intelligence: ProductIntelligenceConfig = field(default_factory=ProductIntelligenceConfig)
    context_intelligence: ContextIntelligenceConfig = field(default_factory=ContextIntelligenceConfig)
    temporal_observatory: TemporalObservatoryConfig = field(default_factory=TemporalObservatoryConfig)
    exploration: ExplorationConfig = field(default_factory=ExplorationConfig)
    comparison: ComparisonConfig = field(default_factory=ComparisonConfig)

    def __post_init__(self):
        _is_non_local = self.env != Environment.LOCAL
        _is_prod = self.env == Environment.PRODUCTION

        # ── Pricing option ────────────────────────────────────────────────────
        if self.rate_limit.pricing_option not in ("A", "B", "C"):
            raise RuntimeError(
                f"PRICING_OPTION must be one of A, B, C "
                f"(got: {self.rate_limit.pricing_option!r})"
            )

        # ── Unified-platform mode flags ──────────────────────────────────────
        if self.temporal_integrity.enforcement_mode not in ("off", "shadow", "warn", "enforce"):
            raise RuntimeError(
                "AETHER_TEMPORAL_ENFORCEMENT_MODE must be one of off, shadow, warn, enforce "
                f"(got: {self.temporal_integrity.enforcement_mode!r})"
            )
        if self.temporal_observatory.mutation_gateway_mode not in ("off", "shadow", "enforce"):
            raise RuntimeError(
                "AETHER_MUTATION_GATEWAY_MODE must be one of off, shadow, enforce "
                f"(got: {self.temporal_observatory.mutation_gateway_mode!r})"
            )

        # ── Interop flag coherence ────────────────────────────────────────────
        # A provider-specific adapter flag without the adapter framework flag is
        # a misconfiguration: the adapter could never be mounted.
        if self.interop.layerzero_enabled and not self.interop.adapters_enabled:
            raise RuntimeError(
                "AETHER_INTEROP_LAYERZERO_ENABLED requires "
                "AETHER_INTEROP_ADAPTERS_ENABLED=true"
            )

        # ── JWT secret ────────────────────────────────────────────────────────
        if _is_non_local and self.auth.jwt_secret == "change-me-in-production":
            raise RuntimeError(
                "JWT_SECRET must be set in non-local environments. "
                "Generate one with: python scripts/generate_secrets.py"
            )

        # ── Database URL ──────────────────────────────────────────────────────
        if _is_non_local and not _env("DATABASE_URL"):
            raise RuntimeError(
                "DATABASE_URL must be set in non-local environments. "
                "Example: postgresql://aether:pass@db:5432/aether"
            )

        # Route policy is a runtime boundary, not just a registry coverage
        # check.  Staging/production may never boot in observe-only mode.
        # Dev/integration keep explicit flag control: default dev configs run
        # observe-only, so the mandatory check applies to deploy targets only.
        _is_deploy_target = self.env in (Environment.STAGING, Environment.PRODUCTION)
        if _is_deploy_target and not (
            self.route_registry.policy_enforcement_enabled
            and self.route_registry.route_registry_enforced
            and self.route_registry.kyber_operator_gate_enforced
        ):
            raise RuntimeError(
                "ROUTE_POLICY_ENFORCEMENT_REQUIRED: POLICY_ENFORCEMENT_ENABLED, "
                "ROUTE_REGISTRY_ENFORCED, and KYBER_OPERATOR_GATE_ENFORCED must be true"
            )

        # ── Kyber workforce identity plane ────────────────────────────────────
        # Mirrors the route-policy precedent above: the workforce plane is a
        # runtime boundary, so a deploy target may never boot with it disabled,
        # in observe mode, without device trust, with legacy operator identity
        # still accepted alongside it, with the founder bootstrap path open, or
        # with its SSO / WebAuthn anchors unset. Dev/integration keep explicit
        # flag control.
        kw = self.kyber_workforce
        if _is_deploy_target:
            _kyber_problems: list[str] = []
            if not kw.workforce_identity_enabled:
                _kyber_problems.append("KYBER_WORKFORCE_IDENTITY_ENABLED must be true")
            if not kw.backend_authz_enforced:
                _kyber_problems.append("KYBER_BACKEND_AUTHZ_ENFORCED must be true")
            if not kw.device_trust_required:
                _kyber_problems.append("KYBER_DEVICE_TRUST_REQUIRED must be true")
            if kw.legacy_operator_identity_allowed and kw.workforce_identity_enabled:
                _kyber_problems.append(
                    "KYBER_LEGACY_OPERATOR_IDENTITY_ALLOWED must be false when "
                    "workforce identity is enabled"
                )
            if kw.bootstrap_enabled:
                _kyber_problems.append("KYBER_BOOTSTRAP_ENABLED must be false")
            if kw.workforce_identity_enabled:
                for _var, _value in (
                    ("KYBER_GOOGLE_CLIENT_ID", kw.google_client_id),
                    ("KYBER_GOOGLE_REDIRECT_URI", kw.google_redirect_uri),
                    ("KYBER_WEBAUTHN_RP_ID", kw.webauthn_rp_id),
                    ("KYBER_WEBAUTHN_ORIGIN", kw.webauthn_origin),
                ):
                    if not _value:
                        _kyber_problems.append(f"{_var} must be set")
            if _kyber_problems:
                raise RuntimeError(
                    "KYBER_WORKFORCE_ENFORCEMENT_REQUIRED: " + "; ".join(_kyber_problems)
                )

        # ── BYOK encryption key ────────────────────────────────────────────────
        # Required in production so the BYOK vault is always encrypted at rest,
        # regardless of whether the Provider Gateway is explicitly enabled.
        if _is_prod and not self.provider_gateway.encryption_key:
            raise RuntimeError(
                "BYOK_ENCRYPTION_KEY (BYOK vault key) must be set in production. "
                "Generate one with: python scripts/generate_secrets.py"
            )

        # ── Provider Gateway encryption key ───────────────────────────────────
        if (
            self.provider_gateway.enabled
            and _is_non_local
            and not self.provider_gateway.encryption_key
        ):
            raise RuntimeError(
                "BYOK_ENCRYPTION_KEY must be set when "
                "Provider Gateway is enabled in non-local environments"
            )

        # ── Extraction defense secrets ────────────────────────────────────────
        # Guard unconditionally in non-local environments: a misconfigured
        # deployment with extraction defense disabled still has the secrets in
        # the codebase, and enabling it later without rotating secrets is silently
        # broken. Fail at startup so the mistake is caught before it matters.
        if (
            _is_non_local
            and self.extraction_defense.watermark_secret_key
            == "aether-wm-default-change-me"
        ):
            raise RuntimeError(
                "WATERMARK_SECRET_KEY must be set to a non-default value in "
                "non-local environments"
            )
        if (
            _is_non_local
            and self.extraction_defense.canary_secret_seed
            == "aether-canary-seed-change-me"
        ):
            raise RuntimeError(
                "CANARY_SECRET_SEED must be set to a non-default value in "
                "non-local environments"
            )

        # ── Extraction Mesh canary seed ──────────────────────────────────────
        if (
            _is_non_local
            and self.extraction_mesh.canary_secret_seed
            == "aether-mesh-canary-seed"
        ):
            raise RuntimeError(
                "EXTRACTION_CANARY_SEED must be set to a non-default value in "
                "non-local environments"
            )

        # ── SDK Config signing secret ─────────────────────────────────────────
        import os as _os
        _sdk_secret = _os.getenv("SDK_CONFIG_SECRET", "default-dev-secret-change-in-production")
        if _is_non_local and _sdk_secret == "default-dev-secret-change-in-production":
            raise RuntimeError(
                "SDK_CONFIG_SECRET must be set to a non-default value in "
                "non-local environments"
            )

        # ── Neptune ──────────────────────────────────────────────────────────
        # Neptune requires AWS infrastructure. In non-local envs where the
        # endpoint is still the placeholder "localhost", emit a clear warning so
        # operators know graph-layer features will be disabled.
        if _is_non_local and self.neptune.endpoint in ("localhost", ""):
            import logging as _logging
            _logging.getLogger("aether.settings").warning(
                "NEPTUNE_ENDPOINT is not configured (still 'localhost'). "
                "Graph intelligence features (H2H/H2A/A2H/A2A) will be "
                "unavailable until AWS Neptune is provisioned and "
                "NEPTUNE_ENDPOINT is set."
            )

        # ── Stripe Billing: required vars in non-local when enabled ───────────
        if self.stripe_billing.enabled and _is_non_local:
            sb = self.stripe_billing
            missing: list[str] = []
            if not sb.secret_key:
                missing.append("STRIPE_SECRET_KEY")
            if not sb.webhook_secret:
                missing.append("STRIPE_WEBHOOK_SECRET")
            if not sb.price_p1:
                missing.append("STRIPE_PRICE_P1")
            if not sb.price_p2:
                missing.append("STRIPE_PRICE_P2")
            if not sb.price_p3:
                missing.append("STRIPE_PRICE_P3")
            if not sb.price_p4:
                missing.append("STRIPE_PRICE_P4")
            if not sb.checkout_success_url:
                missing.append("STRIPE_CHECKOUT_SUCCESS_URL")
            if not sb.checkout_cancel_url:
                missing.append("STRIPE_CHECKOUT_CANCEL_URL")
            if not sb.portal_return_url:
                missing.append("STRIPE_PORTAL_RETURN_URL")
            if missing:
                raise RuntimeError(
                    "Stripe Billing is enabled but required env vars are missing "
                    f"in non-local environment: {', '.join(missing)}"
                )

        # ── Runtime role (PR 4) ───────────────────────────────────────────────
        # AETHER_ROLE must name a known role in every environment. In
        # staging/production the single-process "all" role is rejected: those
        # deployments must run an explicit role so the API process does not start
        # every worker/consumer/cron in-request. Local/dev keep "all" as the
        # default single-process convenience.
        if self.runtime.aether_role not in RUNTIME_ROLES:
            raise RuntimeError(
                f"AETHER_ROLE={self.runtime.aether_role!r} is not a valid role. "
                f"Valid roles: {', '.join(sorted(RUNTIME_ROLES))}"
            )
        if _is_non_local and self.runtime.aether_role == "all":
            raise RuntimeError(
                "AETHER_ROLE=all is not allowed in staging/production. Run an "
                "explicit role (api or a worker role) so the API process no "
                "longer starts every worker. See docs/BACKEND-EXECUTION-MODEL.md."
            )

        # ── Backend selectors (PR 4) ──────────────────────────────────────────
        # In-memory cache/database backends are a local-only convenience; a
        # memory backend is never a correctness source in production. Reject
        # them there so a mis-scaled deployment fails fast at startup.
        if _is_prod:
            _memory_backends = [
                name
                for name, value in (
                    ("CACHE_BACKEND", self.runtime.cache_backend),
                    ("DATABASE_BACKEND", self.runtime.database_backend),
                )
                if value == "memory"
            ]
            if _memory_backends:
                raise RuntimeError(
                    "In-memory backends are not allowed in production: "
                    f"{', '.join(_memory_backends)}=memory. Configure a durable "
                    "backend (e.g. redis/postgres). See "
                    "docs/BACKEND-EXECUTION-MODEL.md."
                )

    @property
    def is_production(self) -> bool:
        return self.env == Environment.PRODUCTION

    @property
    def log_level(self) -> str:
        return {
            Environment.LOCAL: "DEBUG",
            Environment.DEV: "DEBUG",
            Environment.INTEGRATION: "INFO",
            Environment.STAGING: "INFO",
            Environment.PRODUCTION: "WARNING",
        }.get(self.env, "INFO")


# Singleton
settings = Settings()


def get_settings() -> Settings:
    """Accessor for the settings singleton (used by dependency-style imports)."""
    return settings
