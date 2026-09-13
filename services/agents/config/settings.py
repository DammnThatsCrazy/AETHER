"""
Aether Agent Layer — Configuration & Settings
Central configuration for the agent controller, workers, and guardrails.
"""

from dataclasses import dataclass, field
from enum import Enum

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class WorkerType(str, Enum):
    # Discovery workers
    WEB_CRAWLER = "web_crawler"
    API_SCANNER = "api_scanner"
    SOCIAL_LISTENER = "social_listener"
    CHAIN_MONITOR = "chain_monitor"
    COMPETITOR_TRACKER = "competitor_tracker"
    # Enrichment workers
    ENTITY_RESOLVER = "entity_resolver"
    PROFILE_ENRICHER = "profile_enricher"
    TEMPORAL_FILLER = "temporal_filler"
    SEMANTIC_TAGGER = "semantic_tagger"
    QUALITY_SCORER = "quality_scorer"


class TaskPriority(int, Enum):
    CRITICAL = 0
    HIGH = 1
    MEDIUM = 2
    LOW = 3
    BACKGROUND = 4


class TaskStatus(str, Enum):
    PENDING = "pending"
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    REVIEW = "human_review"
    DISCARDED = "discarded"


# ---------------------------------------------------------------------------
# Guardrail thresholds
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ConfidenceThresholds:
    """Data below auto_accept is queued for human review; below discard is dropped."""
    auto_accept: float = 0.7
    discard: float = 0.3


# ---------------------------------------------------------------------------
# Rate-limit budgets (per source, per window)
# ---------------------------------------------------------------------------

@dataclass
class RateLimitBudget:
    source: str
    max_calls_per_minute: int = 60
    max_calls_per_hour: int = 1000
    max_calls_per_day: int = 10000


# ---------------------------------------------------------------------------
# Cost controls
# ---------------------------------------------------------------------------

@dataclass
class CostControls:
    max_hourly_spend_usd: float = 5.00
    max_daily_spend_usd: float = 50.00
    auto_scale_down: bool = True


# ---------------------------------------------------------------------------
# Agent Controller config
# ---------------------------------------------------------------------------

@dataclass
class ControllerConfig:
    task_queue_broker: str = "redis://localhost:6379/0"
    result_backend: str = "redis://localhost:6379/1"
    max_concurrent_workers: int = 20
    scheduler_interval_seconds: int = 60
    feedback_learning_enabled: bool = True


# ---------------------------------------------------------------------------
# Worker pool config
# ---------------------------------------------------------------------------

@dataclass
class WorkerPoolConfig:
    worker_type: WorkerType
    min_instances: int = 1
    max_instances: int = 10
    autoscale_queue_threshold: int = 50  # scale up when queue > this
    timeout_seconds: int = 300
    retry_max: int = 3
    retry_backoff_seconds: int = 30


# ---------------------------------------------------------------------------
# Master settings
# ---------------------------------------------------------------------------

@dataclass
class AgentLayerSettings:
    controller: ControllerConfig = field(default_factory=ControllerConfig)
    confidence: ConfidenceThresholds = field(default_factory=ConfidenceThresholds)
    cost_controls: CostControls = field(default_factory=CostControls)
    rate_limits: list[RateLimitBudget] = field(default_factory=lambda: [
        RateLimitBudget(source="dune_analytics", max_calls_per_minute=30),
        RateLimitBudget(source="twitter_x", max_calls_per_minute=60),
        RateLimitBudget(source="reddit", max_calls_per_minute=30),
        RateLimitBudget(source="etherscan", max_calls_per_minute=5, max_calls_per_hour=200),
        RateLimitBudget(source="general_web", max_calls_per_minute=120),
    ])
    worker_pools: list[WorkerPoolConfig] = field(default_factory=lambda: [
        WorkerPoolConfig(worker_type=wt) for wt in WorkerType
    ])
    kill_switch_enabled: bool = False  # toggled True to halt everything
