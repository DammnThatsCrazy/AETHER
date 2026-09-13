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
    cors_origins: list[str] = field(default_factory=lambda: [
        "http://localhost:3000",
        "https://app.aether.io",
    ])
    deprecation_window_months: int = 12


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

    @property
    def is_production(self) -> bool:
        return self.env == Environment.PRODUCTION


# Singleton
settings = Settings()
