"""
Aether Backend — Attribution Resolver

Resolves attribution for reward eligibility by collecting touchpoints
from the user journey and applying the configured attribution model.

Design:
    - ``AttributionResolver`` is the primary entry point.  It accepts raw
      touchpoint dicts, converts them to ``Touchpoint`` objects, filters by
      the configured lookback window, and delegates to the selected model.
    - ``JourneyStore`` uses the profile-selected tenant-scoped durable cache
      (DynamoDB for lean profiles, Redis for scale profiles) and the
      deterministic in-memory store only for local/testing.

Integration:
    Consumed by ``services.attribution.routes`` and by the reward-evaluation
    pipeline in ``services.rewards``.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from services.attribution.models import (
    ActorWeightedModel,
    AttributionModel,
    AttributionResult,
    DataDrivenModel,
    ExposureAwareModel,
    FirstTouchModel,
    LastTouchModel,
    LinearModel,
    PositionBasedModel,
    TimeDecayModel,
    Touchpoint,
)
from shared.common.common import parse_event_time
from shared.store import redis_url_from_env

logger = logging.getLogger("aether.attribution.resolver")

try:
    import boto3 as _boto3_journey

    BOTO3_JOURNEY_AVAILABLE = True
except ImportError:  # pragma: no cover - boto3 is a production dependency
    _boto3_journey = None  # type: ignore[assignment]
    BOTO3_JOURNEY_AVAILABLE = False

try:
    import redis as _redis_journey

    REDIS_JOURNEY_AVAILABLE = True
except ImportError:  # pragma: no cover - redis is a production dependency
    _redis_journey = None  # type: ignore[assignment]
    REDIS_JOURNEY_AVAILABLE = False


def _inmemory_journey_store_allowed() -> bool:
    return (
        os.getenv("AETHER_ENV", "local").lower() == "local"
        or os.getenv("AETHER_ALLOW_INMEMORY_JOURNEY_STORE", "0") == "1"
    )


# ========================================================================
# CONFIGURATION
# ========================================================================

@dataclass
class AttributionConfig:
    """Resolver configuration."""

    default_model: str = "last_touch"
    lookback_window_hours: int = 720   # 30 days
    min_touchpoints: int = 1


# ========================================================================
# JOURNEY STORE
# ========================================================================

class JourneyStore:
    """
    Tenant-scoped touchpoint store keyed by (tenant_id, user_id).

    Tenant isolation is enforced at the key level — touchpoints from
    Tenant A are never visible to Tenant B even for the same user_id.

    Hosted profiles use the Terraform-managed cache backend selected by
    ``CACHE_BACKEND``. Local and test profiles retain the deterministic
    in-memory implementation. Keeping the selection here makes the module-
    level route singleton safe during hosted application import instead of
    discovering the missing durable path only after an ECS task starts.
    """

    def __init__(self) -> None:
        cache_backend = os.getenv("CACHE_BACKEND", "").strip().lower()
        table_name = os.getenv("DYNAMODB_CACHE_TABLE", "").strip()
        if (
            cache_backend == "dynamodb"
            and table_name
            and BOTO3_JOURNEY_AVAILABLE
            and not _inmemory_journey_store_allowed()
        ):
            self._backend = DynamoDBJourneyStore(table_name)
            self._store: dict[tuple[str, str], list[dict[str, Any]]] | None = None
            return
        redis_url = os.getenv("REDIS_URL", "").strip()
        redis_host = os.getenv("REDIS_HOST", "").strip()
        if (
            cache_backend == "redis"
            and (redis_url or redis_host)
            and REDIS_JOURNEY_AVAILABLE
            and not _inmemory_journey_store_allowed()
        ):
            self._backend = RedisJourneyStore(redis_url or redis_url_from_env())
            self._store = None
            return
        if not _inmemory_journey_store_allowed():
            raise RuntimeError(
                "JourneyStore is disabled outside local mode. Configure the selected durable "
                "cache backend (DYNAMODB_CACHE_TABLE for dynamodb or REDIS_URL/REDIS_HOST "
                "for redis), or set AETHER_ALLOW_INMEMORY_JOURNEY_STORE=1 for an explicit "
                "override."
            )
        self._backend: DynamoDBJourneyStore | RedisJourneyStore | None = None
        self._store: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)

    def _key(self, tenant_id: str, user_id: str) -> tuple[str, str]:
        return (tenant_id, user_id)

    def add(self, tenant_id: str, user_id: str, touchpoint: dict[str, Any]) -> None:
        """Append a raw touchpoint dict for a (tenant, user) pair."""
        if self._backend is not None:
            self._backend.add(tenant_id, user_id, touchpoint)
            return
        assert self._store is not None
        self._store[self._key(tenant_id, user_id)].append(touchpoint)

    def get(self, tenant_id: str, user_id: str) -> list[dict[str, Any]]:
        """Return all stored touchpoints for a (tenant, user) pair (oldest first)."""
        if self._backend is not None:
            return self._backend.get(tenant_id, user_id)
        assert self._store is not None
        return list(self._store.get(self._key(tenant_id, user_id), []))

    def clear(self, tenant_id: str, user_id: str) -> int:
        """Remove all touchpoints for a (tenant, user) pair. Returns count removed."""
        if self._backend is not None:
            return self._backend.clear(tenant_id, user_id)
        assert self._store is not None
        count = len(self._store.pop(self._key(tenant_id, user_id), []))
        return count

    def count(self, tenant_id: str, user_id: str) -> int:
        if self._backend is not None:
            return self._backend.count(tenant_id, user_id)
        assert self._store is not None
        return len(self._store.get(self._key(tenant_id, user_id), []))

    def all_user_ids(self, tenant_id: str) -> list[str]:
        if self._backend is not None:
            return self._backend.all_user_ids(tenant_id)
        assert self._store is not None
        return [uid for (tid, uid) in self._store if tid == tenant_id]


class DynamoDBJourneyStore:
    """Synchronous DynamoDB journey store used by the existing route API.

    The attribution routes historically expose synchronous ``add``/``get``
    methods, so this adapter intentionally uses the synchronous boto3 resource
    API rather than changing every route and caller at once. Each journey is a
    single DynamoDB item with an atomic ``list_append`` update, which preserves
    touchpoints across API task instances and concurrent writes. Touchpoints
    are JSON strings inside the DynamoDB list so arbitrary JSON properties,
    including floating-point values, remain valid DynamoDB attributes.
    """

    _KEY_PREFIX = "aether:journey:"

    def __init__(self, table_name: str) -> None:
        if not BOTO3_JOURNEY_AVAILABLE:
            raise RuntimeError(
                "boto3 is required for the DynamoDB attribution store. "
                "Install boto3>=1.34.0."
            )
        self._table_name = table_name
        self._table = None

    def _get_table(self):
        if self._table is None:
            self._table = _boto3_journey.resource("dynamodb").Table(self._table_name)  # type: ignore[union-attr]
        return self._table

    @classmethod
    def _key(cls, tenant_id: str, user_id: str) -> str:
        identity = f"{tenant_id}\0{user_id}".encode("utf-8")
        return cls._KEY_PREFIX + hashlib.sha256(identity).hexdigest()

    def add(self, tenant_id: str, user_id: str, touchpoint: dict[str, Any]) -> None:
        """Atomically append one touchpoint to a tenant/user journey."""
        self._get_table().update_item(
            Key={"cache_key": self._key(tenant_id, user_id)},
            UpdateExpression=(
                "SET #tenant_id = :tenant_id, #user_id = :user_id, "
                "#touchpoints = list_append(if_not_exists(#touchpoints, :empty), :touchpoint), "
                "#updated_at = :updated_at"
            ),
            ExpressionAttributeNames={
                "#tenant_id": "tenant_id",
                "#user_id": "user_id",
                "#touchpoints": "touchpoints",
                "#updated_at": "updated_at",
            },
            ExpressionAttributeValues={
                ":tenant_id": tenant_id,
                ":user_id": user_id,
                ":empty": [],
                ":touchpoint": [
                    json.dumps(touchpoint, separators=(",", ":"), default=str)
                ],
                ":updated_at": datetime.now(timezone.utc).isoformat(),
            },
        )

    def get(self, tenant_id: str, user_id: str) -> list[dict[str, Any]]:
        response = self._get_table().get_item(
            Key={"cache_key": self._key(tenant_id, user_id)},
            ProjectionExpression="#touchpoints",
            ExpressionAttributeNames={"#touchpoints": "touchpoints"},
        )
        item = response.get("Item") or {}
        touchpoints = item.get("touchpoints") or []
        return [
            json.loads(touchpoint)
            if isinstance(touchpoint, str)
            else touchpoint
            for touchpoint in touchpoints
        ]

    def clear(self, tenant_id: str, user_id: str) -> int:
        response = self._get_table().delete_item(
            Key={"cache_key": self._key(tenant_id, user_id)},
            ReturnValues="ALL_OLD",
        )
        return len((response.get("Attributes") or {}).get("touchpoints") or [])

    def count(self, tenant_id: str, user_id: str) -> int:
        return len(self.get(tenant_id, user_id))

    def all_user_ids(self, tenant_id: str) -> list[str]:
        user_ids: list[str] = []
        last_key = None
        while True:
            kwargs: dict[str, Any] = {
                "ProjectionExpression": "cache_key, #tenant_id, #user_id",
                "ExpressionAttributeNames": {
                    "#tenant_id": "tenant_id",
                    "#user_id": "user_id",
                },
            }
            if last_key:
                kwargs["ExclusiveStartKey"] = last_key
            response = self._get_table().scan(**kwargs)
            for item in response.get("Items", []):
                if (
                    str(item.get("cache_key", "")).startswith(self._KEY_PREFIX)
                    and item.get("tenant_id") == tenant_id
                    and item.get("user_id") is not None
                ):
                    user_ids.append(str(item["user_id"]))
            last_key = response.get("LastEvaluatedKey")
            if not last_key:
                return user_ids


class RedisJourneyStore:
    """Synchronous Redis journey store used by scale-oriented profiles.

    Journeys are Redis lists containing compact JSON touchpoints. A separate
    tenant-scoped set indexes user IDs so ``all_user_ids`` does not need to
    scan unrelated cache keys. Redis list/set operations are atomic, and the
    transaction used for clear keeps the count and deletion together.
    """

    _KEY_PREFIX = "aether:journey:"
    _INDEX_PREFIX = "aether:journey:index:"

    def __init__(self, redis_url: str) -> None:
        if not REDIS_JOURNEY_AVAILABLE:
            raise RuntimeError(
                "redis is required for the Redis attribution store. "
                "Install redis>=5.0."
            )
        self._redis_url = redis_url
        self._redis = _redis_journey.Redis.from_url(  # type: ignore[union-attr]
            redis_url,
            decode_responses=True,
        )

    @classmethod
    def _key(cls, tenant_id: str, user_id: str) -> str:
        identity = f"{tenant_id}\0{user_id}".encode("utf-8")
        return cls._KEY_PREFIX + hashlib.sha256(identity).hexdigest()

    @classmethod
    def _index_key(cls, tenant_id: str) -> str:
        return cls._INDEX_PREFIX + hashlib.sha256(tenant_id.encode("utf-8")).hexdigest()

    def add(self, tenant_id: str, user_id: str, touchpoint: dict[str, Any]) -> None:
        """Append a touchpoint and register the user in the tenant index."""
        with self._redis.pipeline(transaction=True) as pipe:
            pipe.rpush(
                self._key(tenant_id, user_id),
                json.dumps(touchpoint, separators=(",", ":"), default=str),
            )
            pipe.sadd(self._index_key(tenant_id), user_id)
            pipe.execute()

    def get(self, tenant_id: str, user_id: str) -> list[dict[str, Any]]:
        raw_touchpoints = self._redis.lrange(self._key(tenant_id, user_id), 0, -1)
        return [json.loads(touchpoint) for touchpoint in raw_touchpoints]

    def clear(self, tenant_id: str, user_id: str) -> int:
        with self._redis.pipeline(transaction=True) as pipe:
            pipe.llen(self._key(tenant_id, user_id))
            pipe.delete(self._key(tenant_id, user_id))
            pipe.srem(self._index_key(tenant_id), user_id)
            results = pipe.execute()
        return int(results[0] or 0)

    def count(self, tenant_id: str, user_id: str) -> int:
        return int(self._redis.llen(self._key(tenant_id, user_id)))

    def all_user_ids(self, tenant_id: str) -> list[str]:
        return sorted(self._redis.smembers(self._index_key(tenant_id)))


# ========================================================================
# RESOLVER
# ========================================================================

class AttributionResolver:
    """
    Orchestrates touchpoint collection and model selection.

    Usage::

        resolver = AttributionResolver(AttributionConfig(default_model="linear"))
        result = await resolver.resolve(
            user_id="user_123",
            event={"event_type": "conversion"},
            touchpoints=[
                {"channel": "social", "source": "twitter", ...},
                {"channel": "organic", "source": "google", ...},
            ],
        )
    """

    def __init__(self, config: Optional[AttributionConfig] = None) -> None:
        self.config = config or AttributionConfig()
        self._models: dict[str, AttributionModel] = {}
        self._register_defaults()

    # -- model registry ---------------------------------------------------

    def _register_defaults(self) -> None:
        """Register all built-in attribution models."""
        defaults: list[AttributionModel] = [
            FirstTouchModel(),
            LastTouchModel(),
            LinearModel(),
            TimeDecayModel(),
            PositionBasedModel(),
            DataDrivenModel(),
            ActorWeightedModel(),
            ExposureAwareModel(),
        ]
        for model in defaults:
            self._models[model.name] = model

    def get_model(self, name: str) -> AttributionModel:
        """Look up a model by name.  Raises ``KeyError`` if not found."""
        if name not in self._models:
            raise KeyError(f"Unknown attribution model: {name!r}")
        return self._models[name]

    def list_models(self) -> list[str]:
        """Return the names of all registered models."""
        return sorted(self._models.keys())

    # -- resolution -------------------------------------------------------

    async def resolve(
        self,
        user_id: str,
        event: dict[str, Any],
        touchpoints: list[dict[str, Any]],
        model_name: Optional[str] = None,
        *,
        lookback_window_hours: Optional[int] = None,
    ) -> AttributionResult:
        """
        Resolve attribution for a user event.

        Steps:
            1. Convert raw dicts to ``Touchpoint`` objects.
            2. Filter by the lookback window.
            3. Validate minimum touchpoint count.
            4. Select and run the configured (or overridden) model.

        Args:
            user_id:      The user whose journey is being attributed.
            event:        The conversion / target event dict.
            touchpoints:  Raw touchpoint dicts from the journey store or
                          provided inline.
            model_name:   Optional override for the attribution model.
            lookback_window_hours: Optional per-resolution lookback override.
                          This is used when replaying a model-config snapshot
                          whose horizon differs from the resolver default.

        Returns:
            An ``AttributionResult`` with weighted credits summing to 1.0.
        """
        # Step 1 — convert
        typed_touchpoints = self._parse_touchpoints(touchpoints)

        # Step 2 — filter by lookback window
        # Historical recomputation must evaluate lookback relative to the
        # conversion, not wall-clock time. A conversion event with no valid
        # timestamp has no anchor, so refuse to attribute rather than silently
        # anchoring the window to now() (which over-credits).
        reference_time = _event_reference_time(event)
        if reference_time is None:
            logger.warning(
                "Attribution skipped for user=%s: conversion event has no valid timestamp",
                user_id,
            )
            return AttributionResult(credits=[], model_used="none", total_credit=0.0)
        # The canonical measurement engine can replay an immutable model-config
        # snapshot whose click/view horizon is longer than this resolver's
        # process-wide default.  An explicit per-run horizon must therefore win;
        # otherwise valid historical touches are silently capped at 30 days.
        effective_lookback_hours = (
            self.config.lookback_window_hours
            if lookback_window_hours is None
            else int(lookback_window_hours)
        )
        cutoff = reference_time - timedelta(hours=effective_lookback_hours)
        filtered = [
            tp for tp in typed_touchpoints
            if cutoff <= tp.timestamp <= reference_time
        ]

        # Sort chronologically
        filtered.sort(key=lambda tp: tp.timestamp)

        # Step 3 — validate
        if len(filtered) < self.config.min_touchpoints:
            logger.warning(
                "Insufficient touchpoints for user=%s: found=%d required=%d",
                user_id, len(filtered), self.config.min_touchpoints,
            )
            return AttributionResult(credits=[], model_used="none", total_credit=0.0)

        # Step 4 — run model
        selected = model_name or self.config.default_model
        model = self.get_model(selected)

        result = await model.attribute(filtered)
        logger.info(
            "Attribution resolved: user=%s model=%s touchpoints=%d",
            user_id, selected, len(filtered),
        )
        return result

    # -- private helpers --------------------------------------------------

    @staticmethod
    def _parse_touchpoints(raw: list[dict[str, Any]]) -> list[Touchpoint]:
        """Convert raw dicts to ``Touchpoint`` objects.

        The touchpoint time comes from ``timestamp`` or, if absent, ``occurred_at``
        (the canonical touchpoint column). A touchpoint with no parseable time is
        EXCLUDED rather than stamped with now(): fabricating a time would place it
        inside every lookback window and over-credit it.
        """
        touchpoints: list[Touchpoint] = []
        for item in raw:
            ts_raw = item.get("timestamp")
            if ts_raw is None:
                ts_raw = item.get("occurred_at")

            # Only a string or a datetime is a candidate instant; anything else
            # (including absent) is "missing" rather than "invalid" — same
            # bucket the pre-refactor type check used.
            if not isinstance(ts_raw, (str, datetime)):
                logger.warning("Excluding touchpoint with missing timestamp")
                continue

            ts = parse_event_time(ts_raw)
            if ts is None:
                logger.warning(
                    "Excluding touchpoint with invalid timestamp: %r",
                    item.get("timestamp") or item.get("occurred_at"),
                )
                continue

            touchpoints.append(
                Touchpoint(
                    channel=item.get("channel", "unknown"),
                    source=item.get("source", "unknown"),
                    campaign=item.get("campaign", ""),
                    timestamp=ts,
                    event_type=item.get("event_type", "pageview"),
                    properties=item.get("properties", {}),
                )
            )
        return touchpoints


def _event_reference_time(event: dict[str, Any]) -> Optional[datetime]:
    """Return the conversion event's reference time.

    Distinguishes two cases the old code collapsed into a silent now():
      - No time supplied at all → this is a real-time resolve() call, so the
        conversion is happening now; now() is the correct anchor.
      - A time WAS supplied but is unparseable/wrong-typed → return None so the
        caller refuses to attribute rather than scoring the window against a
        wall-clock time unrelated to the (corrupt) conversion time.

    The durable pipeline (AttributionEngine.run_for_conversion) is stricter
    still: a stored conversion with no valid occurred_at fails the run.
    """
    raw = None
    for key in ("timestamp", "occurred_at", "created_at"):
        val = event.get(key)
        if val is not None:
            raw = val
            break
    if raw is None:
        # No conversion time field present at all → real-time resolve(); the
        # conversion is happening now, so now() is the correct anchor. A field
        # that IS present but empty/invalid falls through to the refuse paths
        # below (never silently coerced to now).
        return datetime.now(timezone.utc)
    if not isinstance(raw, (str, datetime)):
        return None
    # A time WAS supplied (present, non-None) — parse_event_time() cannot
    # itself tell "absent" from "invalid" (both give None), which is exactly
    # why the presence check above happens BEFORE this call, not inside
    # parse_event_time. A present-but-unparseable value refuses (returns
    # None) rather than being coerced to now().
    return parse_event_time(raw)
