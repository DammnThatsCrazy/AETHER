"""
Aether Security — Extraction Defense Mesh Configuration

Centralized configuration for the Extraction Defense Mesh, extending
the existing ExtractionDefenseConfig with mesh-specific settings.

Used by: middleware, ML serving, monitoring.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field


@dataclass
class MeshBudgetConfig:
    """Distributed budget engine configuration."""
    redis_db: int = int(os.getenv("EXTRACTION_REDIS_DB", "2"))
    # Feature fingerprint HLL precision
    hll_precision: int = 14
    # Budget window cleanup interval (seconds)
    cleanup_interval_seconds: int = 300


@dataclass
class MeshExpectationConfig:
    """Extraction expectation engine configuration."""
    # Minimum requests before baselines activate
    min_history_for_baselines: int = 3
    # History retention per actor
    max_history_per_actor: int = 500
    # History TTL in Redis (seconds)
    history_ttl_seconds: int = 7200


@dataclass
class MeshScorerConfig:
    """Extraction risk scorer configuration."""
    # EMA smoothing alpha (higher = more responsive)
    ema_alpha: float = 0.3
    # Band thresholds
    yellow_threshold: float = 30.0
    orange_threshold: float = 55.0
    red_threshold: float = 80.0


@dataclass
class MeshPolicyConfig:
    """Extraction policy engine configuration."""
    # Output precision for rounded mode
    rounded_precision: int = 2
    # Bucket size for bucketed mode (0.1 = 10 buckets)
    bucket_size: float = 0.1


@dataclass
class MeshAttributionConfig:
    """Attribution and canary service configuration."""
    # Max lineage records in memory
    max_lineage_records: int = 10000
    # Max canary hit records in memory
    max_canary_hits: int = 1000
    # Canary match tolerance (L2 distance)
    canary_tolerance: float = 0.05
    # Number of canaries per family
    canaries_per_family: int = 20


@dataclass
class ExtractionMeshFullConfig:
    """Complete mesh configuration."""
    enabled: bool = os.getenv("ENABLE_EXTRACTION_MESH", "false").lower() == "true"
    budget: MeshBudgetConfig = field(default_factory=MeshBudgetConfig)
    expectation: MeshExpectationConfig = field(default_factory=MeshExpectationConfig)
    scorer: MeshScorerConfig = field(default_factory=MeshScorerConfig)
    policy: MeshPolicyConfig = field(default_factory=MeshPolicyConfig)
    attribution: MeshAttributionConfig = field(default_factory=MeshAttributionConfig)
