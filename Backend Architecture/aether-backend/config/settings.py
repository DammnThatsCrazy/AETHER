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
    """Token bucket defaults per API key tier."""
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
    encryption_key: str = _env("PROVIDER_GATEWAY_ENCRYPTION_KEY", "")
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
# Master settings
# ---------------------------------------------------------------------------

@dataclass
class Settings:
    env: Environment = Environment(_env("AETHER_ENV", "local"))
    debug: bool = _env_bool("DEBUG", True)

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

    def __post_init__(self):
        if self.env != Environment.LOCAL and self.auth.jwt_secret == "change-me-in-production":
            raise RuntimeError("JWT_SECRET must be set in non-local environments")
        if (
            self.provider_gateway.enabled
            and self.env != Environment.LOCAL
            and not self.provider_gateway.encryption_key
        ):
            raise RuntimeError(
                "PROVIDER_GATEWAY_ENCRYPTION_KEY must be set when "
                "Provider Gateway is enabled in non-local environments"
            )
        if (
            self.extraction_defense.enabled
            and self.env != Environment.LOCAL
            and self.extraction_defense.watermark_secret_key
            == "aether-wm-default-change-me"
        ):
            raise RuntimeError(
                "WATERMARK_SECRET_KEY must be changed from default when "
                "extraction defense is enabled in non-local environments"
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
