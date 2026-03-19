"""
Aether ML -- Prediction Cache

Redis-backed caching layer for model predictions with per-model TTLs,
model-version awareness, automatic invalidation on version change,
and hit/miss metrics.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Optional

logger = logging.getLogger("aether.serving.cache")


# =============================================================================
# CONFIGURATION
# =============================================================================


# Default TTLs (in seconds) per model -- real-time models get short TTLs,
# server-side models that score infrequently get long ones.
DEFAULT_MODEL_TTLS: dict[str, int] = {
    "intent_prediction": 30,         # 30 s   -- evolves within a session
    "bot_detection": 60,             # 1 min  -- per-session classification
    "session_scorer": 30,            # 30 s   -- engagement changes fast
    "churn_prediction": 86_400,      # 24 h   -- daily re-scoring
    "ltv_prediction": 86_400,        # 24 h   -- daily re-scoring
    "journey_prediction": 3_600,     # 1 h    -- journey is semi-stable
    "campaign_attribution": 3_600,   # 1 h    -- attribution rarely changes
    "anomaly_detection": 300,        # 5 min  -- traffic-pattern dependent
    "identity_resolution": 3_600,    # 1 h    -- identity graph is stable
}


@dataclass
class CacheConfig:
    """Tunable parameters for the prediction cache."""

    redis_url: str = "redis://localhost:6379"
    default_ttl: int = 300             # 5 minutes fallback TTL
    max_ttl: int = 86_400              # 24-hour ceiling
    prefix: str = "aether:pred:"
    enable_metrics: bool = True
    model_ttls: dict[str, int] = field(default_factory=dict)


# =============================================================================
# PREDICTION CACHE
# =============================================================================


class PredictionCache:
    """
    Redis-backed prediction cache.

    Features
    --------
    - Deterministic cache keys derived from model name + sorted feature vector.
    - Per-model TTLs with a configurable ceiling.
    - Model-version awareness: when a new version is registered via
      ``on_model_update`` all stale predictions for the old version are
      automatically invalidated.
    - In-process hit / miss / set counters exposed through ``stats()``.
    - Graceful degradation: if Redis is unavailable every operation is a no-op
      so inference continues without caching.
    """

    def __init__(self, config: Optional[CacheConfig] = None) -> None:
        self.config = config or CacheConfig()
        self._client: Any = None
        self._connected: bool = False

        # In-process metrics
        self._hits: int = 0
        self._misses: int = 0
        self._sets: int = 0

        # Track model versions so we can auto-invalidate on upgrade.
        self._current_versions: dict[str, str] = {}

    # --------------------------------------------------------------------- #
    # Connection
    # --------------------------------------------------------------------- #

    @property
    def client(self) -> Any:
        """Lazy Redis connection.

        Defers the ``import redis`` to first access so the rest of the
        serving code works even when ``redis`` is not installed (e.g. in
        unit-test environments).
        """
        if self._client is None:
            self._connect()
        return self._client

    def _connect(self) -> None:
        """Establish a Redis connection."""
        try:
            import redis as redis_lib

            self._client = redis_lib.from_url(
                self.config.redis_url,
                decode_responses=True,
                socket_connect_timeout=2,
                socket_timeout=1,
            )
            # Verify connectivity with a ping.
            self._client.ping()
            self._connected = True
            logger.info("Prediction cache connected to %s", self.config.redis_url)
        except Exception as exc:
            logger.warning(
                "Redis unavailable (%s) -- prediction caching disabled", exc
            )
            self._client = None
            self._connected = False

    # --------------------------------------------------------------------- #
    # Cache operations
    # --------------------------------------------------------------------- #

    def get(self, model_name: str, features: dict[str, Any]) -> Optional[dict[str, Any]]:
        """Look up a cached prediction.

        Parameters
        ----------
        model_name:
            Canonical model name (e.g. ``"intent_prediction"``).
        features:
            The exact feature dict that was used at prediction time.

        Returns
        -------
        The cached prediction dict, or ``None`` on a miss (or Redis error).
        """
        if self._client is None:
            self._misses += 1
            return None

        key = self._make_key(model_name, features)
        try:
            raw = self._client.get(key)
            if raw is not None:
                self._hits += 1
                return json.loads(raw)
            self._misses += 1
            return None
        except Exception as exc:
            logger.debug("Cache GET error for %s: %s", key, exc)
            self._misses += 1
            return None

    def set(
        self,
        model_name: str,
        features: dict[str, Any],
        prediction: Any,
        ttl: Optional[int] = None,
    ) -> None:
        """Store a prediction in the cache.

        Parameters
        ----------
        model_name:
            Canonical model name.
        features:
            The feature dict used for this prediction.
        prediction:
            The prediction result (must be JSON-serializable).
        ttl:
            Time-to-live in seconds.  Falls back to the per-model default
            or the global default if not provided.
        """
        if self._client is None:
            return

        key = self._make_key(model_name, features)
        effective_ttl = min(
            ttl or self._get_model_ttl(model_name),
            self.config.max_ttl,
        )

        try:
            serialized = json.dumps(prediction, default=str)
            self._client.setex(key, effective_ttl, serialized)
            self._sets += 1
        except Exception as exc:
            logger.debug("Cache SET error for %s: %s", key, exc)

    def get_entity(
        self,
        model_name: str,
        model_version: str,
        entity_type: str,
        entity_id: str,
    ) -> Optional[dict[str, Any]]:
        """Look up a cached entity-level prediction (user, session, etc.).

        Entity keys are more readable than feature-hash keys and are used
        for server-side models that score by identity ID rather than a raw
        feature vector.
        """
        if self._client is None:
            self._misses += 1
            return None

        key = self._make_entity_key(model_name, model_version, entity_type, entity_id)
        try:
            raw = self._client.get(key)
            if raw is not None:
                self._hits += 1
                return json.loads(raw)
            self._misses += 1
            return None
        except Exception as exc:
            logger.debug("Cache GET entity error for %s: %s", key, exc)
            self._misses += 1
            return None

    def set_entity(
        self,
        model_name: str,
        model_version: str,
        entity_type: str,
        entity_id: str,
        prediction: dict[str, Any],
        ttl: Optional[int] = None,
    ) -> None:
        """Cache a prediction keyed by entity (user, session, wallet)."""
        if self._client is None:
            return

        key = self._make_entity_key(model_name, model_version, entity_type, entity_id)
        effective_ttl = min(
            ttl or self._get_model_ttl(model_name),
            self.config.max_ttl,
        )
        try:
            self._client.setex(key, effective_ttl, json.dumps(prediction, default=str))
            self._sets += 1
        except Exception as exc:
            logger.debug("Cache SET entity error for %s: %s", key, exc)

    # --------------------------------------------------------------------- #
    # Invalidation
    # --------------------------------------------------------------------- #

    def invalidate(self, model_name: str) -> int:
        """Delete all cached predictions for a model.

        Uses ``SCAN`` to avoid blocking Redis on large key sets.

        Returns the number of keys deleted.
        """
        if self._client is None:
            return 0

        pattern = f"{self.config.prefix}{model_name}:*"
        cursor: int = 0
        deleted: int = 0

        try:
            while True:
                cursor, keys = self._client.scan(
                    cursor=cursor, match=pattern, count=200
                )
                if keys:
                    deleted += self._client.delete(*keys)
                if cursor == 0:
                    break
        except Exception as exc:
            logger.error("Cache invalidation error for %s: %s", model_name, exc)

        logger.info("Invalidated %d cached predictions for %s", deleted, model_name)
        return deleted

    def on_model_update(self, model_name: str, new_version: str) -> None:
        """Handle a model version change by invalidating stale predictions.

        Call this from the model-reload workflow so that predictions cached
        under the old version are not served after the new model is deployed.
        """
        old_version = self._current_versions.get(model_name)
        if old_version is not None and old_version != new_version:
            logger.info(
                "Model %s updated %s -> %s, invalidating cache",
                model_name,
                old_version,
                new_version,
            )
            self.invalidate(model_name)
        self._current_versions[model_name] = new_version

    # --------------------------------------------------------------------- #
    # Metrics / health
    # --------------------------------------------------------------------- #

    def stats(self) -> dict[str, Any]:
        """Return cache hit/miss/set counters and derived hit rate."""
        total = self._hits + self._misses
        return {
            "hits": self._hits,
            "misses": self._misses,
            "sets": self._sets,
            "hit_rate": round(self._hits / max(total, 1) * 100, 2),
            "total_requests": total,
            "connected": self._connected,
        }

    def reset_metrics(self) -> None:
        """Reset in-process counters (useful in tests)."""
        self._hits = 0
        self._misses = 0
        self._sets = 0

    def health_check(self) -> bool:
        """Return ``True`` if the Redis connection is alive."""
        if self._client is None:
            return False
        try:
            return bool(self._client.ping())
        except Exception:
            return False

    # --------------------------------------------------------------------- #
    # Key construction
    # --------------------------------------------------------------------- #

    def _make_key(self, model_name: str, features: dict[str, Any]) -> str:
        """Create a deterministic cache key from model name and feature dict.

        Features are sorted by key name and numeric values are rounded to
        four decimal places so that floating-point noise does not cause
        cache misses.
        """
        sorted_items = sorted(features.items(), key=lambda kv: kv[0])
        parts = "|".join(f"{k}={_round_value(v)}" for k, v in sorted_items)
        version = self._current_versions.get(model_name, "0")
        raw = f"{model_name}:{version}:{parts}"
        digest = hashlib.md5(raw.encode()).hexdigest()[:16]
        return f"{self.config.prefix}{model_name}:{digest}"

    def _make_entity_key(
        self,
        model_name: str,
        model_version: str,
        entity_type: str,
        entity_id: str,
    ) -> str:
        """Build a human-readable cache key for entity-level predictions."""
        return (
            f"{self.config.prefix}{model_name}:{entity_type}:{entity_id}:v{model_version}"
        )

    def _get_model_ttl(self, model_name: str) -> int:
        """Resolve the TTL for a model (config override > default map > global)."""
        if model_name in self.config.model_ttls:
            return self.config.model_ttls[model_name]
        if model_name in DEFAULT_MODEL_TTLS:
            return DEFAULT_MODEL_TTLS[model_name]
        return self.config.default_ttl


# =============================================================================
# HELPERS
# =============================================================================


def _round_value(v: Any) -> str:
    """Round numeric values for cache-key stability."""
    if isinstance(v, float):
        return f"{v:.4f}"
    return str(v)


class CacheKeyBuilder:
    @staticmethod
    def build(model_name: str, model_version: str, features: dict[str, Any], prefix: str = 'aether:pred:') -> str:
        sorted_items = sorted(features.items(), key=lambda kv: kv[0])
        parts = '|'.join(f"{k}={_round_value(v)}" for k, v in sorted_items)
        digest = hashlib.md5(f"{model_name}:{model_version}:{parts}".encode()).hexdigest()[:16]
        return f"{prefix}{model_name}:v{model_version}:{digest}"

    @staticmethod
    def build_entity(model_name: str, model_version: str, entity_type: str, entity_id: str, prefix: str = 'aether:pred:') -> str:
        return f"{prefix}{model_name}:{entity_type}:{entity_id}:v{model_version}"

    @staticmethod
    def invalidation_pattern(model_name: str, prefix: str = 'aether:pred:') -> str:
        return f"{prefix}{model_name}:*"
