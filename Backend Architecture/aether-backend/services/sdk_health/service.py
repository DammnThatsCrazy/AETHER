"""
Aether Service — SDK Health Monitoring

Manages per-SDK heartbeat ingestion, fleet-level health scoring, and silent SDK detection.
Every active SDK instance is expected to emit a signed heartbeat every ~60 seconds.

Health score (0–100) is composed of 5 weighted sub-scores:
  connectivity   0.25  — endpoint reachability + auth validity
  throughput     0.25  — ingestion success rate
  integrity      0.20  — schema consistency + low drop rate
  auth_consent   0.15  — auth valid + consent valid flags
  freshness      0.15  — recency of last heartbeat

Heartbeats are stored in Redis (TTL = 2× heartbeat interval = 300 s).
Fleet state changes are published to Kafka topic SDK_HEALTH_STATE_CHANGED.
"""

from __future__ import annotations

import hashlib
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from shared.logger.logger import get_logger, metrics
from shared.store import get_store

logger = get_logger("aether.service.sdk_health")

_HEARTBEAT_TTL_SECONDS = 300       # 5 min — 2× expected 60 s interval
_SILENT_THRESHOLD_SECONDS = 300    # flag as silent after 5 min of no heartbeat
_MIN_SUPPORTED_VERSION = "6.0.0"   # bump via remote config in production


# ─────────────────────────────────────────────────────────────────────────────
# Data models
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class SDKHeartbeat:
    """Payload emitted by each SDK instance on a regular interval."""
    tenant_id: str
    sdk_id: str                          # stable UUID per SDK installation
    sdk_version: str
    platform: str                        # web | ios | android | react-native
    app_version: str = ""
    queue_depth: int = 0                 # events waiting to flush
    retry_count: int = 0                 # cumulative retries since last heartbeat
    dropped_events: int = 0              # events dropped due to consent / error
    endpoint_latency_ms: float = 0.0     # last measured ingest round-trip
    ingestion_success_rate: float = 1.0  # 0.0–1.0 over last flush window
    schema_hash: str = ""                # hash of active event schema
    auth_valid: bool = True
    consent_valid: bool = True
    wallet_connected: bool = False
    config_version: str = "0"
    rollout_cohort: str = "default"
    reported_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SDKHealthScore:
    """Composite health score for a single SDK instance."""
    sdk_id: str
    tenant_id: str
    composite: float                 # 0–100
    connectivity: float              # 0–1
    throughput: float                # 0–1
    integrity: float                 # 0–1
    auth_consent: float              # 0–1
    freshness: float                 # 0–1
    status: str                      # healthy | degraded | unhealthy | silent
    last_heartbeat_at: str = ""
    computed_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SDKFleetStatus:
    """Aggregate fleet health for a tenant."""
    tenant_id: str
    total_instances: int
    healthy_count: int
    degraded_count: int
    unhealthy_count: int
    silent_count: int
    avg_health_score: float
    platforms: dict[str, int]            # platform → count
    versions: dict[str, int]             # sdk_version → count
    computed_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ─────────────────────────────────────────────────────────────────────────────
# Service
# ─────────────────────────────────────────────────────────────────────────────

class SDKHealthService:
    """
    Core SDK health monitoring service.

    Uses shared DurableStore (Redis-backed) for heartbeat storage.
    Publishes Kafka events for state changes.
    """

    def __init__(self) -> None:
        self._heartbeat_store = get_store("sdk_heartbeats")
        self._score_store = get_store("sdk_health_scores")

    # ── Heartbeat Ingestion ───────────────────────────────────────────────

    async def ingest_heartbeat(self, hb: SDKHeartbeat) -> SDKHealthScore:
        """Store heartbeat and return computed health score."""
        key = self._heartbeat_key(hb.tenant_id, hb.sdk_id)
        await self._heartbeat_store.set(key, hb.to_dict(), ttl_seconds=_HEARTBEAT_TTL_SECONDS)

        score = self._compute_score(hb)
        await self._score_store.set(
            self._score_key(hb.tenant_id, hb.sdk_id),
            score.to_dict(),
            ttl_seconds=_HEARTBEAT_TTL_SECONDS,
        )

        # Prometheus counters
        metrics.increment(
            "aether_sdk_heartbeats_total",
            labels={"tenant_id": hb.tenant_id, "platform": hb.platform},
        )
        metrics.observe(
            "aether_sdk_queue_depth",
            float(hb.queue_depth),
            labels={"tenant_id": hb.tenant_id, "platform": hb.platform},
        )
        if hb.dropped_events > 0:
            metrics.increment(
                "aether_sdk_dropped_events_total",
                value=hb.dropped_events,
                labels={"tenant_id": hb.tenant_id},
            )
        metrics.observe(
            "aether_sdk_health_score",
            score.composite,
            labels={"tenant_id": hb.tenant_id, "sdk_id": hb.sdk_id[:8]},
        )

        # Fire-and-forget Kafka publish
        await self._publish_heartbeat_event(hb, score)

        # Fire-and-forget drift checks (non-blocking — never delay heartbeat response)
        import asyncio
        asyncio.ensure_future(self._run_drift_checks_async(hb))

        logger.info(
            "sdk_health.heartbeat_ingested",
            extra={
                "tenant_id": hb.tenant_id,
                "sdk_id": hb.sdk_id,
                "score": score.composite,
                "status": score.status,
            },
        )
        return score

    # ── Health Scoring ────────────────────────────────────────────────────

    async def score_sdk(self, sdk_id: str, tenant_id: str) -> Optional[SDKHealthScore]:
        """Retrieve the most recent health score for an SDK instance."""
        key = self._score_key(tenant_id, sdk_id)
        raw = await self._score_store.get(key)
        if raw is None:
            hb_raw = await self._heartbeat_store.get(self._heartbeat_key(tenant_id, sdk_id))
            if hb_raw is None:
                return None
            hb = SDKHeartbeat(**{k: hb_raw[k] for k in SDKHeartbeat.__dataclass_fields__ if k in hb_raw})
            return self._compute_score(hb)
        return SDKHealthScore(**{k: raw[k] for k in SDKHealthScore.__dataclass_fields__ if k in raw})

    def _compute_score(self, hb: SDKHeartbeat) -> SDKHealthScore:
        """Compute weighted composite health score from heartbeat fields."""
        # 1. Connectivity (endpoint reachability + auth)
        latency_score = max(0.0, 1.0 - (hb.endpoint_latency_ms / 5000.0))  # degrades linearly to 5 s
        connectivity = latency_score if hb.auth_valid else latency_score * 0.5

        # 2. Throughput (ingestion success rate, inverted retry pressure)
        retry_penalty = min(1.0, hb.retry_count / 20.0)
        throughput = hb.ingestion_success_rate * (1.0 - retry_penalty * 0.3)

        # 3. Integrity (drop rate + schema presence)
        total_events = max(1, hb.queue_depth + hb.dropped_events)
        drop_rate = min(1.0, hb.dropped_events / total_events)
        schema_ok = 1.0 if hb.schema_hash else 0.7
        integrity = (1.0 - drop_rate) * schema_ok

        # 4. Auth + consent
        auth_consent = (
            (1.0 if hb.auth_valid else 0.0) * 0.6 +
            (1.0 if hb.consent_valid else 0.5) * 0.4
        )

        # 5. Freshness (age of heartbeat relative to TTL)
        try:
            reported_dt = datetime.fromisoformat(hb.reported_at.replace("Z", "+00:00"))
            age_seconds = (datetime.now(timezone.utc) - reported_dt).total_seconds()
        except Exception:
            age_seconds = 0.0
        freshness = max(0.0, 1.0 - age_seconds / _HEARTBEAT_TTL_SECONDS)

        # Weighted composite
        composite = 100.0 * (
            0.25 * connectivity +
            0.25 * throughput +
            0.20 * integrity +
            0.15 * auth_consent +
            0.15 * freshness
        )
        composite = round(min(100.0, max(0.0, composite)), 2)

        # Status band
        if composite >= 80:
            status = "healthy"
        elif composite >= 50:
            status = "degraded"
        else:
            status = "unhealthy"

        return SDKHealthScore(
            sdk_id=hb.sdk_id,
            tenant_id=hb.tenant_id,
            composite=composite,
            connectivity=round(connectivity, 4),
            throughput=round(throughput, 4),
            integrity=round(integrity, 4),
            auth_consent=round(auth_consent, 4),
            freshness=round(freshness, 4),
            status=status,
            last_heartbeat_at=hb.reported_at,
        )

    # ── Fleet Status ──────────────────────────────────────────────────────

    async def get_fleet_status(self, tenant_id: str) -> SDKFleetStatus:
        """Compute fleet-level health summary for all SDK instances in a tenant."""
        scores = await self._score_store.find(tenant_id=tenant_id)
        heartbeats = await self._heartbeat_store.find(tenant_id=tenant_id)

        now_ts = time.time()
        platforms: dict[str, int] = {}
        versions: dict[str, int] = {}
        healthy = degraded = unhealthy = silent = 0
        composite_sum = 0.0

        # Track silent SDKs from heartbeat store (may have no score if TTL expired)
        for hb_raw in heartbeats:
            platform = hb_raw.get("platform", "unknown")
            version = hb_raw.get("sdk_version", "unknown")
            platforms[platform] = platforms.get(platform, 0) + 1
            versions[version] = versions.get(version, 0) + 1

        for score_raw in scores:
            s = score_raw.get("composite", 0.0)
            st = score_raw.get("status", "unknown")
            composite_sum += s
            if st == "healthy":
                healthy += 1
            elif st == "degraded":
                degraded += 1
            else:
                unhealthy += 1

        silent_list = await self.detect_silent_sdks(tenant_id)
        silent = len(silent_list)

        total = len(scores) + silent
        avg_score = (composite_sum / len(scores)) if scores else 0.0

        return SDKFleetStatus(
            tenant_id=tenant_id,
            total_instances=total,
            healthy_count=healthy,
            degraded_count=degraded,
            unhealthy_count=unhealthy,
            silent_count=silent,
            avg_health_score=round(avg_score, 2),
            platforms=platforms,
            versions=versions,
        )

    async def detect_silent_sdks(self, tenant_id: str) -> list[dict[str, Any]]:
        """Return SDK IDs that have not sent a heartbeat within the silence threshold."""
        heartbeats = await self._heartbeat_store.find(tenant_id=tenant_id)
        silent = []
        now_ts = time.time()
        for hb_raw in heartbeats:
            try:
                reported_str = hb_raw.get("reported_at", "")
                reported_dt = datetime.fromisoformat(reported_str.replace("Z", "+00:00"))
                age = (datetime.now(timezone.utc) - reported_dt).total_seconds()
                if age > _SILENT_THRESHOLD_SECONDS:
                    silent.append({
                        "sdk_id": hb_raw.get("sdk_id"),
                        "tenant_id": tenant_id,
                        "last_seen": reported_str,
                        "age_seconds": age,
                    })
            except Exception:
                continue
        return silent

    # ── Internal Helpers ──────────────────────────────────────────────────

    @staticmethod
    def _heartbeat_key(tenant_id: str, sdk_id: str) -> str:
        return f"{tenant_id}:{sdk_id}"

    @staticmethod
    def _score_key(tenant_id: str, sdk_id: str) -> str:
        return f"score:{tenant_id}:{sdk_id}"

    async def _run_drift_checks_async(self, hb: SDKHeartbeat) -> None:
        """Run drift checks asynchronously without blocking the heartbeat response."""
        try:
            from services.sdk_drift.service import get_sdk_drift_detector
            detector = get_sdk_drift_detector()
            await detector.run_all_checks(hb.to_dict())
        except Exception as exc:
            logger.debug(f"Drift check skipped: {exc}")

    async def _publish_heartbeat_event(self, hb: SDKHeartbeat, score: SDKHealthScore) -> None:
        try:
            from shared.events.events import EventProducer, Event, Topic
            producer = EventProducer()
            event = Event(
                event_id=str(uuid.uuid4()),
                topic=Topic.SDK_HEALTH_HEARTBEAT,
                version="1.0",
                tenant_id=hb.tenant_id,
                source_service="sdk_health",
                payload={
                    "sdk_id": hb.sdk_id,
                    "platform": hb.platform,
                    "sdk_version": hb.sdk_version,
                    "health_score": score.composite,
                    "status": score.status,
                },
            )
            await producer.publish(event)
        except Exception as exc:
            logger.debug(f"SDK health Kafka publish skipped: {exc}")


# Module-level singleton
_sdk_health_service: Optional[SDKHealthService] = None


def get_sdk_health_service() -> SDKHealthService:
    global _sdk_health_service
    if _sdk_health_service is None:
        _sdk_health_service = SDKHealthService()
    return _sdk_health_service
