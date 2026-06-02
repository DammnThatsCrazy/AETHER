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


# ---------------------------------------------------------------------------
# Model Extraction Defense
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ModelExtractionDefenseConfig:
    """Model extraction defense layer — protects ML serving endpoints."""
    enabled: bool = _env_bool("ENABLE_EXTRACTION_DEFENSE", False)
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
# Master settings
# ---------------------------------------------------------------------------

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
    quicknode: QuickNodeConfig = field(default_factory=QuickNodeConfig)

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

    def __post_init__(self):
        _is_non_local = self.env != Environment.LOCAL
        _is_prod = self.env == Environment.PRODUCTION

        # ── Pricing option ────────────────────────────────────────────────────
        if self.rate_limit.pricing_option not in ("A", "B", "C"):
            raise RuntimeError(
                f"PRICING_OPTION must be one of A, B, C "
                f"(got: {self.rate_limit.pricing_option!r})"
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

    @property
    def is_production(self) -> bool:
        return self.env == Environment.PRODUCTION

    @property
    def log_level(self) -> str:
        return {
            Environment.LOCAL: "DEBUG",
            Environment.DEV: "DEBUG",
            Environment.STAGING: "INFO",
            Environment.PRODUCTION: "WARNING",
        }.get(self.env, "INFO")


# Singleton
settings = Settings()
