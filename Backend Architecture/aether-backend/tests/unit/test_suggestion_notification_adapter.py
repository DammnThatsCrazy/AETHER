"""Unit tests for the Notification Intelligence ↔ Suggestion adapter."""

from __future__ import annotations

import asyncio
import os
import sys
import uuid

os.environ.setdefault("AETHER_ENV", "local")
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))

import pytest
from unittest.mock import AsyncMock, MagicMock

from services.suggestions.adapters.notification_adapter import (
    _map_priority_to_severity,
    create_suggestion_from_notification,
    deliver_suggestion_via_notification,
)
from services.suggestions.models import (
    SuggestionClass,
    SuggestionCreate,
    SuggestionSource,
    SuggestionStatus,
)


def _run(coro):
    return asyncio.run(coro)


def _make_notif(**overrides) -> dict:
    base = {
        "id": str(uuid.uuid4()),
        "title": "Test Notification",
        "summary": "A test notification summary",
        "body": "Notification body text",
        "what": "What happened",
        "why": "Why it happened",
        "impact": "Some impact",
        "severity": "high",
        "subject_entity_id": "ent_123",
        "subject_display_name": "Test Entity",
        "source_topic": "data_quality",
        "confidence": 0.8,
        "risk_score": 0.2,
        "recommended_action": "Review the entity",
        "created_at": "2026-01-01T00:00:00Z",
    }
    base.update(overrides)
    return base


def _make_approved_suggestion(suggestion_id: str = None, delivery_eligible: bool = True) -> dict:
    return {
        "id": suggestion_id or str(uuid.uuid4()),
        "tenant_id": "tenant_abc",
        "status": SuggestionStatus.APPROVED.value,
        "title": "Test Suggestion",
        "summary": "Summary",
        "priority": "P1",
        "delivery_eligible": delivery_eligible,
        "policy_decision": {"allowed": True},
        "subject": {"id": "ent_123"},
    }


# ---------------------------------------------------------------------------
# create_suggestion_from_notification()
# ---------------------------------------------------------------------------

def test_create_from_notification_returns_suggestion_create():
    notif = _make_notif()
    result = create_suggestion_from_notification(notif, "tenant_abc")
    assert isinstance(result, SuggestionCreate)


def test_create_from_notification_sets_tenant_id():
    notif = _make_notif()
    result = create_suggestion_from_notification(notif, "tenant_xyz")
    assert result.tenant_id == "tenant_xyz"


def test_create_from_notification_sets_source_to_notification_intelligence():
    notif = _make_notif()
    result = create_suggestion_from_notification(notif, "tenant_abc")
    assert result.source == SuggestionSource.NOTIFICATION_INTELLIGENCE


def test_create_from_notification_sets_class_to_notification():
    notif = _make_notif()
    result = create_suggestion_from_notification(notif, "tenant_abc")
    assert result.suggestion_class == SuggestionClass.NOTIFICATION


def test_create_from_notification_maps_subject_entity_id():
    notif = _make_notif(subject_entity_id="ent_specific")
    result = create_suggestion_from_notification(notif, "tenant_abc")
    assert result.subject.id == "ent_specific"


def test_create_from_notification_falls_back_to_notif_id_for_subject():
    notif = _make_notif()
    del notif["subject_entity_id"]
    notif_id = notif["id"]
    result = create_suggestion_from_notification(notif, "tenant_abc")
    assert result.subject.id == notif_id


def test_create_from_notification_maps_title():
    notif = _make_notif(title="Critical Alert")
    result = create_suggestion_from_notification(notif, "tenant_abc")
    assert result.title == "Critical Alert"


def test_create_from_notification_uses_default_title_when_missing():
    notif = _make_notif()
    notif.pop("title", None)
    result = create_suggestion_from_notification(notif, "tenant_abc")
    assert result.title == "Intelligence Notification"


def test_create_from_notification_maps_confidence_score():
    notif = _make_notif(confidence=0.95)
    result = create_suggestion_from_notification(notif, "tenant_abc")
    assert result.confidence_score == 0.95


def test_create_from_notification_default_confidence_when_missing():
    notif = _make_notif()
    notif.pop("confidence", None)
    result = create_suggestion_from_notification(notif, "tenant_abc")
    assert result.confidence_score == 0.7


def test_create_from_notification_maps_risk_score():
    notif = _make_notif(risk_score=0.6)
    result = create_suggestion_from_notification(notif, "tenant_abc")
    assert result.risk_score == 0.6


def test_create_from_notification_sets_source_ref():
    notif = _make_notif()
    result = create_suggestion_from_notification(notif, "tenant_abc")
    assert result.source_ref is not None
    assert result.source_ref["service"] == "notification_intelligence"
    assert result.source_ref["id"] == notif["id"]


def test_create_from_notification_has_evidence_entry():
    notif = _make_notif()
    result = create_suggestion_from_notification(notif, "tenant_abc")
    assert len(result.evidence) >= 1
    assert result.evidence[0]["type"] == "event"


# ---------------------------------------------------------------------------
# deliver_suggestion_via_notification()
# ---------------------------------------------------------------------------

def test_deliver_skips_if_not_approved():
    suggestion = _make_approved_suggestion()
    suggestion["status"] = "suggested"  # not approved
    svc = MagicMock()

    result = _run(deliver_suggestion_via_notification(suggestion, svc))
    # Should return suggestion unchanged without calling service
    assert result == suggestion
    svc.deliver_suggestion.assert_not_called()


def test_deliver_skips_if_not_delivery_eligible():
    suggestion = _make_approved_suggestion(delivery_eligible=False)
    svc = MagicMock()

    result = _run(deliver_suggestion_via_notification(suggestion, svc))
    assert result == suggestion
    svc.deliver_suggestion.assert_not_called()


def test_deliver_calls_deliver_suggestion_when_eligible():
    suggestion = _make_approved_suggestion(delivery_eligible=True)
    delivered = {**suggestion, "status": SuggestionStatus.DELIVERED.value}
    svc = MagicMock()
    svc.deliver_suggestion = AsyncMock(return_value=delivered)

    result = _run(deliver_suggestion_via_notification(suggestion, svc))
    svc.deliver_suggestion.assert_called_once()
    assert result["status"] == SuggestionStatus.DELIVERED.value


def test_deliver_skips_if_policy_blocked():
    suggestion = _make_approved_suggestion()
    suggestion["policy_decision"] = {"allowed": False, "explanation": "Policy blocked"}
    svc = MagicMock()

    result = _run(deliver_suggestion_via_notification(suggestion, svc))
    assert result == suggestion
    svc.deliver_suggestion.assert_not_called()


def test_deliver_proceeds_when_policy_allowed():
    suggestion = _make_approved_suggestion()
    suggestion["policy_decision"] = {"allowed": True}
    delivered = {**suggestion, "status": SuggestionStatus.DELIVERED.value}
    svc = MagicMock()
    svc.deliver_suggestion = AsyncMock(return_value=delivered)

    result = _run(deliver_suggestion_via_notification(suggestion, svc))
    svc.deliver_suggestion.assert_called_once()


# ---------------------------------------------------------------------------
# _map_priority_to_severity()
# ---------------------------------------------------------------------------

def test_priority_p0_maps_to_critical():
    assert _map_priority_to_severity("P0") == "critical"


def test_priority_p1_maps_to_high():
    assert _map_priority_to_severity("P1") == "high"


def test_priority_p2_maps_to_medium():
    assert _map_priority_to_severity("P2") == "medium"


def test_priority_p3_maps_to_low():
    assert _map_priority_to_severity("P3") == "low"


def test_priority_info_maps_to_info():
    assert _map_priority_to_severity("info") == "info"


def test_unknown_priority_maps_to_low():
    assert _map_priority_to_severity("unknown") == "low"
