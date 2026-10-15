"""
Aether Service — SDK Drift Detection Engine

Detects four classes of SDK-level drift:
  1. schema_drift       — schema_hash in heartbeat does not match the expected hash for that SDK version
  2. stale_sdk          — sdk_version is below the minimum supported version
  3. replay_storm       — event submission rate has exceeded the replay threshold
  4. payload_anomaly    — abnormally high dropped-event ratio

All incidents are stored in Redis (TTL = 24 h) and published to the Kafka
SDK_DRIFT_DETECTED topic for downstream alerting pipelines.
"""

from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from shared.logger.logger import get_logger, metrics
from shared.store import get_store

logger = get_logger("aether.service.sdk_drift")

_INCIDENT_TTL_SECONDS = 86_400       # 24 h
_REPLAY_RATE_WINDOW   = 60           # seconds for sliding window
_REPLAY_RATE_THRESHOLD = 500         # events/window above which replay storm is flagged
_DROP_RATE_THRESHOLD   = 0.20        # 20 % drop rate triggers payload anomaly

# Canonical schema hashes per SDK version — populated from remote config in production.
# A missing entry means "unknown version; no schema drift check performed."
_EXPECTED_SCHEMA_HASHES: dict[str, str] = {
    "7.0.0": "expected-hash-7-0-0",
    "6.0.0": "expected-hash-6-0-0",
}

_MIN_SUPPORTED_VERSION = "6.0.0"


# ─────────────────────────────────────────────────────────────────────────────
# Data models
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class DriftIncident:
    incident_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    tenant_id: str = ""
    sdk_id: str = ""
    drift_type: str = ""      # schema_drift | stale_sdk | replay_storm | payload_anomaly
    severity: str = "warning" # info | warning | critical
    description: str = ""
    detected_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    schema_hash_expected: str = ""
    schema_hash_observed: str = ""
    sdk_version: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ─────────────────────────────────────────────────────────────────────────────
# Service
# ─────────────────────────────────────────────────────────────────────────────

class SDKDriftDetector:
    """
    Runs drift checks against SDK heartbeat data.

    All checks are additive and non-blocking — they fire and store results
    without affecting the heartbeat ingest latency path.
    """

    def __init__(self) -> None:
        self._incident_store = get_store("sdk_drift_incidents")
        self._counter_store  = get_store("sdk_event_rate_counters")

    # ── Public API ────────────────────────────────────────────────────────

    async def run_all_checks(self, heartbeat_raw: dict[str, Any]) -> list[DriftIncident]:
        """
        Run all four drift checks against a heartbeat dict.

        Returns the list of incidents detected (may be empty).
        """
        incidents: list[DriftIncident] = []

        schema_incident = await self.check_schema_drift(heartbeat_raw)
        if schema_incident:
            incidents.append(schema_incident)

        stale_incident = self.check_stale_sdk(heartbeat_raw)
        if stale_incident:
            incidents.append(stale_incident)

        replay_incident = await self.check_replay_storm(heartbeat_raw)
        if replay_incident:
            incidents.append(replay_incident)

        anomaly_incident = self.check_payload_anomaly(heartbeat_raw)
        if anomaly_incident:
            incidents.append(anomaly_incident)

        # Persist + publish each incident
        for incident in incidents:
            await self._persist_incident(incident)
            await self._publish_drift_event(incident)
            metrics.increment(
                "aether_sdk_drift_incidents_total",
                labels={
                    "tenant_id": incident.tenant_id,
                    "drift_type": incident.drift_type,
                },
            )

        if incidents:
            logger.info(
                "sdk_drift.incidents_detected",
                extra={
                    "tenant_id": heartbeat_raw.get("tenant_id"),
                    "sdk_id": heartbeat_raw.get("sdk_id"),
                    "incident_count": len(incidents),
                    "types": [i.drift_type for i in incidents],
                },
            )

        return incidents

    # ── Individual Checks ─────────────────────────────────────────────────

    async def check_schema_drift(self, hb: dict[str, Any]) -> Optional[DriftIncident]:
        """Flag if the SDK's active schema hash doesn't match the expected hash for its version."""
        sdk_version = hb.get("sdk_version", "")
        observed_hash = hb.get("schema_hash", "")

        if not observed_hash or not sdk_version:
            return None  # Insufficient data — skip check

        expected_hash = _EXPECTED_SCHEMA_HASHES.get(sdk_version)
        if expected_hash is None:
            return None  # Unknown version — no baseline to compare

        if observed_hash != expected_hash:
            return DriftIncident(
                tenant_id=hb.get("tenant_id", ""),
                sdk_id=hb.get("sdk_id", ""),
                drift_type="schema_drift",
                severity="critical",
                description=(
                    f"SDK {sdk_version} reports schema hash {observed_hash!r}, "
                    f"expected {expected_hash!r}. Possible schema migration or SDK version mismatch."
                ),
                schema_hash_expected=expected_hash,
                schema_hash_observed=observed_hash,
                sdk_version=sdk_version,
            )
        return None

    def check_stale_sdk(self, hb: dict[str, Any]) -> Optional[DriftIncident]:
        """Flag if the SDK version is below the minimum supported version."""
        sdk_version = hb.get("sdk_version", "")
        if not sdk_version:
            return None

        if self._version_lt(sdk_version, _MIN_SUPPORTED_VERSION):
            return DriftIncident(
                tenant_id=hb.get("tenant_id", ""),
                sdk_id=hb.get("sdk_id", ""),
                drift_type="stale_sdk",
                severity="warning",
                description=(
                    f"SDK version {sdk_version} is below the minimum supported version "
                    f"{_MIN_SUPPORTED_VERSION}. Please upgrade."
                ),
                sdk_version=sdk_version,
            )
        return None

    async def check_replay_storm(self, hb: dict[str, Any]) -> Optional[DriftIncident]:
        """
        Flag if the cumulative event rate for this SDK has exceeded the replay threshold.

        Uses a Redis counter keyed by (tenant_id, sdk_id) with a 60-second TTL.
        The heartbeat's retry_count is used as a proxy for event throughput.
        """
        tenant_id = hb.get("tenant_id", "")
        sdk_id = hb.get("sdk_id", "")
        retry_count = int(hb.get("retry_count", 0))
        queue_depth = int(hb.get("queue_depth", 0))

        counter_key = f"replay_rate:{tenant_id}:{sdk_id}"
        raw = await self._counter_store.get(counter_key)
        prev_rate = int(raw.get("rate", 0)) if raw else 0
        new_rate = prev_rate + retry_count + queue_depth

        await self._counter_store.set(
            counter_key,
            {"rate": new_rate, "sdk_id": sdk_id, "tenant_id": tenant_id},
            ttl_seconds=_REPLAY_RATE_WINDOW,
        )

        if new_rate > _REPLAY_RATE_THRESHOLD:
            return DriftIncident(
                tenant_id=tenant_id,
                sdk_id=sdk_id,
                drift_type="replay_storm",
                severity="critical",
                description=(
                    f"SDK event rate {new_rate} exceeds replay storm threshold "
                    f"{_REPLAY_RATE_THRESHOLD} within {_REPLAY_RATE_WINDOW}s window."
                ),
                extra={"event_rate": new_rate, "threshold": _REPLAY_RATE_THRESHOLD},
            )
        return None

    def check_payload_anomaly(self, hb: dict[str, Any]) -> Optional[DriftIncident]:
        """Flag if the dropped-event ratio is abnormally high."""
        dropped = int(hb.get("dropped_events", 0))
        success_rate = float(hb.get("ingestion_success_rate", 1.0))
        queue_depth = int(hb.get("queue_depth", 0))

        total_events = max(1, dropped + queue_depth)
        drop_rate = dropped / total_events

        if drop_rate > _DROP_RATE_THRESHOLD:
            return DriftIncident(
                tenant_id=hb.get("tenant_id", ""),
                sdk_id=hb.get("sdk_id", ""),
                drift_type="payload_anomaly",
                severity="warning",
                description=(
                    f"SDK dropped-event ratio is {drop_rate:.1%} (threshold {_DROP_RATE_THRESHOLD:.0%}). "
                    f"Possible consent filtering, schema mismatch, or backend rejection."
                ),
                extra={
                    "drop_rate": drop_rate,
                    "dropped_events": dropped,
                    "ingestion_success_rate": success_rate,
                },
            )
        return None

    # ── Query Incidents ───────────────────────────────────────────────────

    async def get_incidents(
        self,
        tenant_id: str,
        drift_type: Optional[str] = None,
        severity: Optional[str] = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Return drift incidents for a tenant, optionally filtered."""
        incidents = await self._incident_store.get_list(
            f"incidents:{tenant_id}", limit=limit
        )
        if drift_type:
            incidents = [i for i in incidents if i.get("drift_type") == drift_type]
        if severity:
            incidents = [i for i in incidents if i.get("severity") == severity]
        return incidents

    async def get_report(self, tenant_id: str) -> dict[str, Any]:
        """Aggregate drift report for a tenant."""
        incidents = await self._incident_store.get_list(f"incidents:{tenant_id}", limit=500)
        by_type: dict[str, int] = {}
        by_severity: dict[str, int] = {}
        for inc in incidents:
            dt = inc.get("drift_type", "unknown")
            sv = inc.get("severity", "unknown")
            by_type[dt] = by_type.get(dt, 0) + 1
            by_severity[sv] = by_severity.get(sv, 0) + 1

        metrics.increment("aether_sdk_stale_count", value=by_type.get("stale_sdk", 0),
                          labels={"tenant_id": tenant_id})

        return {
            "tenant_id": tenant_id,
            "total_incidents": len(incidents),
            "by_type": by_type,
            "by_severity": by_severity,
            "recent_incidents": incidents[-10:],
        }

    # ── Internal Helpers ──────────────────────────────────────────────────

    async def _persist_incident(self, incident: DriftIncident) -> None:
        await self._incident_store.set(
            incident.incident_id,
            incident.to_dict(),
            ttl_seconds=_INCIDENT_TTL_SECONDS,
        )
        await self._incident_store.append_list(
            f"incidents:{incident.tenant_id}",
            incident.to_dict(),
        )

    async def _publish_drift_event(self, incident: DriftIncident) -> None:
        try:
            from shared.events.events import EventProducer, Event, Topic
            producer = EventProducer()
            event = Event(
                event_id=str(uuid.uuid4()),
                topic=Topic.SDK_DRIFT_DETECTED,
                version="1.0",
                tenant_id=incident.tenant_id,
                source_service="sdk_drift",
                payload={
                    "incident_id": incident.incident_id,
                    "sdk_id": incident.sdk_id,
                    "drift_type": incident.drift_type,
                    "severity": incident.severity,
                    "description": incident.description,
                },
            )
            await producer.publish(event)
        except Exception as exc:
            logger.debug(f"SDK drift Kafka publish skipped: {exc}")

    @staticmethod
    def _version_lt(v1: str, v2: str) -> bool:
        """Return True if v1 < v2 using simple semver comparison."""
        try:
            def parse(v: str) -> tuple[int, ...]:
                return tuple(int(x) for x in v.split(".")[:3])
            return parse(v1) < parse(v2)
        except Exception:
            return False


# Module-level singleton
_sdk_drift_detector: Optional[SDKDriftDetector] = None


def get_sdk_drift_detector() -> SDKDriftDetector:
    global _sdk_drift_detector
    if _sdk_drift_detector is None:
        _sdk_drift_detector = SDKDriftDetector()
    return _sdk_drift_detector
