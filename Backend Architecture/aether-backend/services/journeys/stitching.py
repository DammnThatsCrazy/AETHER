"""Tenant-scoped cross-device journey continuity stitching.

Additive in-memory projection used by tenant/admin APIs and by ingestion tests. The
SDK only observes lifecycle events; this service scores and explains continuity.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
import uuid

JOURNEY_EVENT_TYPES = {
    "journey_started",
    "journey_paused",
    "journey_resumed",
    "journey_continued",
    "journey_completed",
    "journey_abandoned",
    "journey_checkpoint",
}

MAX_STEPS_PER_JOURNEY = 500
MAX_EVENT_PAYLOAD_BYTES = 65_536

STRONG_SIGNALS = {"user_id_match", "wallet_match", "email_hash_match"}
SUPPORT_SIGNALS = {"anonymous_id_match", "fingerprint_match", "campaign_continuity", "timestamp_proximity", "behavioral_continuity"}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class JourneyEventRecord:
    event_id: str
    event_type: str
    timestamp: str
    session_id: str
    anonymous_id: str
    user_id: str | None
    platform: str | None
    device_type: str | None
    properties: dict[str, Any]
    confidence: float
    confidence_signals: list[str]


@dataclass
class JourneyRecord:
    journey_id: str
    tenant_id: str
    primary_user_id: str | None
    primary_anonymous_id: str | None
    journey_name: str | None
    journey_type: str | None
    status: str
    started_at: str
    updated_at: str
    completed_at: str | None = None
    abandoned_at: str | None = None
    events: list[JourneyEventRecord] = field(default_factory=list)
    handoffs: list[dict[str, Any]] = field(default_factory=list)
    confidence: float = 0.0
    confidence_signals: list[str] = field(default_factory=list)


class JourneyStitchingService:
    def __init__(self) -> None:
        self._journeys: dict[str, dict[str, JourneyRecord]] = {}
        self._event_ids: set[tuple[str, str]] = set()
        self._dropped: list[dict[str, Any]] = []

    def reset(self) -> None:
        self._journeys.clear()
        self._event_ids.clear()
        self._dropped.clear()

    def score(self, *, user_id: str | None = None, anonymous_id: str | None = None, wallet: str | None = None,
              email_hash: str | None = None, fingerprint: str | None = None, campaign: dict[str, Any] | None = None,
              timestamp_proximity: bool = True, behavioral_continuity: bool = False) -> tuple[float, list[str]]:
        signals: list[str] = []
        score = 0.0
        if user_id:
            signals.append("user_id_match")
            score += 0.72
        if wallet:
            signals.append("wallet_match")
            score += 0.68
        if email_hash:
            signals.append("email_hash_match")
            score += 0.66
        if anonymous_id:
            signals.append("anonymous_id_match")
            score += 0.46
        if fingerprint:
            signals.append("fingerprint_match")
            score += 0.28
        if campaign:
            signals.append("campaign_continuity")
            score += 0.12
        if timestamp_proximity:
            signals.append("timestamp_proximity")
            score += 0.08
        if behavioral_continuity:
            signals.append("behavioral_continuity")
            score += 0.10
        if "fingerprint_match" in signals and not (set(signals) & (STRONG_SIGNALS | {"anonymous_id_match"})):
            score = min(score, 0.49)
        return min(round(score, 2), 0.99), signals

    def ingest_event(self, tenant_id: str, event: dict[str, Any]) -> JourneyRecord | None:
        import json as _json
        if len(_json.dumps(event, default=str)) > MAX_EVENT_PAYLOAD_BYTES:
            self._dropped.append({"reason": "payload_too_large", "event_id": event.get("id")})
            return None
        event_id = str(event.get("id") or uuid.uuid4())
        if (tenant_id, event_id) in self._event_ids:
            return None
        self._event_ids.add((tenant_id, event_id))

        event_type = str(event.get("type") or "")
        props = event.get("properties") if isinstance(event.get("properties"), dict) else {}
        if event_type == "track" and isinstance(props, dict) and props.get("journeyEventType") in JOURNEY_EVENT_TYPES:
            event_type = str(props["journeyEventType"])
        if event_type not in JOURNEY_EVENT_TYPES:
            return None

        context = event.get("context") if isinstance(event.get("context"), dict) else {}
        device = context.get("device") if isinstance(context.get("device"), dict) else {}
        campaign = context.get("campaign") if isinstance(context.get("campaign"), dict) else None
        fingerprint = context.get("fingerprint") if isinstance(context.get("fingerprint"), dict) else {}
        confidence, signals = self.score(
            user_id=event.get("userId"),
            anonymous_id=event.get("anonymousId"),
            fingerprint=fingerprint.get("id"),
            campaign=campaign,
            behavioral_continuity=event_type in {"journey_continued", "journey_checkpoint"},
        )
        if isinstance(props.get("confidence"), (int, float)):
            confidence = max(confidence, min(float(props["confidence"]), 0.99))
        if isinstance(props.get("confidenceSignals"), list):
            signals = sorted(set(signals + [str(s) for s in props["confidenceSignals"]]))

        journey_id = str(props.get("journeyId") or self._find_candidate_id(tenant_id, event, confidence) or f"jrn_{uuid.uuid4().hex[:12]}")
        tenant_journeys = self._journeys.setdefault(tenant_id, {})
        record = tenant_journeys.get(journey_id)
        timestamp = str(event.get("timestamp") or now_iso())
        if record is None:
            record = JourneyRecord(
                journey_id=journey_id,
                tenant_id=tenant_id,
                primary_user_id=event.get("userId"),
                primary_anonymous_id=event.get("anonymousId"),
                journey_name=props.get("journeyName") or props.get("journeyType"),
                journey_type=props.get("journeyType") or props.get("journeyName"),
                status=event_type.replace("journey_", ""),
                started_at=timestamp,
                updated_at=timestamp,
                confidence=confidence,
                confidence_signals=signals,
            )
            tenant_journeys[journey_id] = record
        record.status = str(props.get("journeyStatus") or event_type.replace("journey_", ""))
        record.updated_at = timestamp
        record.primary_user_id = record.primary_user_id or event.get("userId")
        record.primary_anonymous_id = record.primary_anonymous_id or event.get("anonymousId")
        record.journey_name = record.journey_name or props.get("journeyName")
        record.journey_type = record.journey_type or props.get("journeyType")
        record.confidence = max(record.confidence, confidence)
        record.confidence_signals = sorted(set(record.confidence_signals + signals))
        if event_type == "journey_completed":
            record.completed_at = timestamp
        if event_type == "journey_abandoned":
            record.abandoned_at = timestamp

        event_record = JourneyEventRecord(
            event_id=event_id,
            event_type=event_type,
            timestamp=timestamp,
            session_id=str(event.get("sessionId") or ""),
            anonymous_id=str(event.get("anonymousId") or ""),
            user_id=event.get("userId"),
            platform=context.get("platform") or device.get("platform") or context.get("library", {}).get("name"),
            device_type=device.get("type"),
            properties=props,
            confidence=confidence,
            confidence_signals=signals,
        )
        if len(record.events) >= MAX_STEPS_PER_JOURNEY:
            self._dropped.append({"reason": "max_steps_exceeded", "journey_id": journey_id, "event_id": event_id})
            return record
        last = record.events[-1] if record.events else None
        record.events.append(event_record)
        if last and (last.session_id != event_record.session_id or last.device_type != event_record.device_type):
            record.handoffs.append({
                "from_session_id": last.session_id,
                "to_session_id": event_record.session_id,
                "from_device_type": last.device_type,
                "to_device_type": event_record.device_type,
                "confidence": confidence,
                "confidence_signals": signals,
                "detected_at": timestamp,
            })
        return record

    def _find_candidate_id(self, tenant_id: str, event: dict[str, Any], confidence: float) -> str | None:
        if confidence < 0.6:
            return None
        for journey in self._journeys.get(tenant_id, {}).values():
            if journey.status in {"completed", "abandoned"}:
                continue
            if event.get("userId") and journey.primary_user_id == event.get("userId"):
                return journey.journey_id
            if event.get("anonymousId") and journey.primary_anonymous_id == event.get("anonymousId"):
                return journey.journey_id
        return None

    def list_for_user(self, tenant_id: str, user_id: str) -> list[JourneyRecord]:
        return [j for j in self._journeys.get(tenant_id, {}).values() if j.primary_user_id == user_id or j.primary_anonymous_id == user_id]

    def get(self, tenant_id: str, journey_id: str) -> JourneyRecord | None:
        return self._journeys.get(tenant_id, {}).get(journey_id)

    def health(self, tenant_id: str | None = None) -> dict[str, Any]:
        journeys = [j for tid, js in self._journeys.items() for j in js.values() if tenant_id is None or tid == tenant_id]
        events = [e for j in journeys for e in j.events]
        handoffs = [h for j in journeys for h in j.handoffs]
        low = [j for j in journeys if j.confidence < 0.6]
        by_platform: dict[str, int] = {}
        for e in events:
            by_platform[str(e.platform or "unknown")] = by_platform.get(str(e.platform or "unknown"), 0) + 1
        return {
            "journey_count": len(journeys),
            "journey_event_count": len(events),
            "handoff_count": len(handoffs),
            "handoff_success_rate": round(len([j for j in journeys if j.completed_at and j.handoffs]) / max(len(handoffs), 1), 2),
            "low_confidence_count": len(low),
            "confidence_distribution": {
                "high": len([j for j in journeys if j.confidence >= 0.8]),
                "medium": len([j for j in journeys if 0.6 <= j.confidence < 0.8]),
                "low": len(low),
            },
            "sdk_emission_by_platform": by_platform,
            "dropped_invalid_events": len(self._dropped),
            "overlink_warnings": len([j for j in journeys if "fingerprint_match" in j.confidence_signals and not (set(j.confidence_signals) & STRONG_SIGNALS)]),
        }

    def dropped_events(self, tenant_id: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
        """Return recorded dropped/invalid journey events for operator diagnostics.

        The diagnostics endpoint surfaces these so operators can see tenant /
        event / reason details, not just a count. Kept consistent with the
        ``dropped_invalid_events`` count reported by ``health()``.
        """
        items = [d for d in self._dropped if tenant_id is None or d.get("tenant_id") == tenant_id]
        return items[-limit:]


def serialize_journey(journey: JourneyRecord) -> dict[str, Any]:
    return {
        "journey_id": journey.journey_id,
        "tenant_id": journey.tenant_id,
        "primary_user_id": journey.primary_user_id,
        "primary_anonymous_id": journey.primary_anonymous_id,
        "journey_name": journey.journey_name,
        "journey_type": journey.journey_type,
        "status": journey.status,
        "started_at": journey.started_at,
        "updated_at": journey.updated_at,
        "completed_at": journey.completed_at,
        "abandoned_at": journey.abandoned_at,
        "confidence": journey.confidence,
        "confidence_signals": journey.confidence_signals,
        "handoffs": journey.handoffs,
        "steps": [e.__dict__ for e in journey.events],
        "timeline": [e.__dict__ for e in journey.events],
        "completion_rate": 1 if journey.completed_at else 0,
    }


journey_stitcher = JourneyStitchingService()
