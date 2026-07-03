"""Unit tests — canonical communication contracts (ADR-C1/C2/C5)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
BACKEND_ROOT = ROOT / "Backend Architecture" / "aether-backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import pytest

pytest.importorskip("pydantic", reason="Backend deps not installed")


class TestTaxonomyAgainstRegistry:
    """The comms taxonomy must stay a subset of the canonical JSON registry."""

    def _registry_types(self) -> set[str]:
        registry = json.loads(
            (ROOT / "packages" / "shared" / "contracts" / "event-registry.json").read_text()
        )
        return {e["type"] for e in registry["events"]}

    def test_all_communication_events_in_registry(self):
        from services.comms.contracts import COMMUNICATION_EVENT_TYPES
        missing = COMMUNICATION_EVENT_TYPES - self._registry_types()
        assert not missing, f"comms taxonomy not in registry: {sorted(missing)}"

    def test_registry_comms_family_projects_to_communication_facts(self):
        registry = json.loads(
            (ROOT / "packages" / "shared" / "contracts" / "event-registry.json").read_text()
        )
        from services.comms.contracts import COMMUNICATION_EVENT_TYPES
        for event in registry["events"]:
            if event["type"] in COMMUNICATION_EVENT_TYPES:
                assert event["silverProjection"] == "communication_facts", event["type"]

    def test_lifecycle_events_present(self):
        from services.comms.contracts import EMAIL_LIFECYCLE_EVENTS
        expected = {
            "email_queued", "email_processed", "email_sent", "email_delivered",
            "email_deferred", "email_bounced", "email_dropped", "email_opened",
            "email_clicked", "email_replied", "email_spam_complaint",
            "email_suppressed", "unsubscribe_observed",
        }
        assert EMAIL_LIFECYCLE_EVENTS == expected

    def test_every_event_has_state_channel_direction(self):
        from services.comms.contracts import (
            COMMUNICATION_EVENT_TYPES, EVENT_STATE_MAP,
            EVENT_CHANNEL_MAP, EVENT_DIRECTION_MAP,
        )
        for t in COMMUNICATION_EVENT_TYPES:
            assert t in EVENT_STATE_MAP, f"no state for {t}"
            assert t in EVENT_CHANNEL_MAP, f"no channel for {t}"
            assert t in EVENT_DIRECTION_MAP, f"no direction for {t}"


class TestJourneyRoles:
    """ADR-C5 journey inclusion policy."""

    def test_lifecycle_noise_is_state_only(self):
        from services.comms.contracts import JourneyRole, journey_role_for
        for t in ("email_queued", "email_processed", "email_deferred",
                  "email_bounced", "email_dropped", "email_suppressed"):
            assert journey_role_for(t) == JourneyRole.STATE_ONLY, t

    def test_human_click_and_reply_are_active_steps(self):
        from services.comms.contracts import JourneyRole, journey_role_for
        assert journey_role_for("email_clicked") == JourneyRole.ACTIVE_STEP
        assert journey_role_for("email_replied") == JourneyRole.ACTIVE_STEP

    def test_machine_click_is_excluded(self):
        from services.comms.contracts import JourneyRole, journey_role_for
        role = journey_role_for("email_clicked", suspected_machine_activity=True)
        assert role == JourneyRole.EXCLUDED

    def test_automated_reply_is_excluded(self):
        from services.comms.contracts import JourneyRole, journey_role_for
        role = journey_role_for("email_replied", is_automated_response=True)
        assert role == JourneyRole.EXCLUDED

    def test_unsubscribe_and_complaint_are_outcomes(self):
        from services.comms.contracts import JourneyRole, journey_role_for
        assert journey_role_for("unsubscribe_observed") == JourneyRole.OUTCOME
        assert journey_role_for("email_spam_complaint") == JourneyRole.OUTCOME


class TestActivityFamilyRouting:
    """Phase 6 — business-meaning family routing, never hard-coded."""

    def test_marketing_routes_to_campaign(self):
        from services.comms.contracts import activity_family_for
        assert activity_family_for("marketing") == "campaign"
        assert activity_family_for("sales") == "campaign"

    def test_transactional_routes_to_commerce(self):
        from services.comms.contracts import activity_family_for
        assert activity_family_for("transactional") == "commerce"

    def test_account_security_support_route_to_web2(self):
        from services.comms.contracts import activity_family_for
        for c in ("account", "security", "support", "operational"):
            assert activity_family_for(c) == "web2", c

    def test_agent_participation_routes_to_agent(self):
        from services.comms.contracts import activity_family_for
        assert activity_family_for("agent_generated") == "agent"
        assert activity_family_for("marketing", actor_kind="agent") == "agent"

    def test_actor_kind_from_provenance_never_defaults_to_human_for_outbound(self):
        from services.comms.contracts import ActorKind, actor_kind_from_provenance
        kind = actor_kind_from_provenance(direction="outbound", sender_is_organization=True)
        assert kind == ActorKind.ORGANIZATION
        kind = actor_kind_from_provenance(direction="outbound", agent_id="agent-1")
        assert kind == ActorKind.AGENT
        kind = actor_kind_from_provenance(direction="inbound")
        assert kind == ActorKind.HUMAN


class TestCanonicalActivityKey:
    """ADR-C4 — source-derived, replay-stable."""

    def test_deterministic(self):
        from services.comms.contracts import canonical_activity_key
        a = canonical_activity_key("t1", "klaviyo", "acct", "ev-1", "email_clicked")
        b = canonical_activity_key("t1", "klaviyo", "acct", "ev-1", "email_clicked")
        assert a == b

    def test_distinct_per_semantic_type_and_tenant(self):
        from services.comms.contracts import canonical_activity_key
        base = canonical_activity_key("t1", "klaviyo", "acct", "ev-1", "email_clicked")
        assert canonical_activity_key("t2", "klaviyo", "acct", "ev-1", "email_clicked") != base
        assert canonical_activity_key("t1", "klaviyo", "acct", "ev-1", "email_opened") != base


class TestPayloadContract:
    def test_payload_validates_required_fields(self):
        from services.comms.contracts import CommunicationEventPayload
        payload = CommunicationEventPayload(
            tenant_id="t1", provider="klaviyo", provider_event_id="ev-1",
            occurred_at="2026-07-01T00:00:00+00:00",
        )
        assert payload.channel == "email"
        assert payload.message_category.value == "marketing"

    def test_confidence_bounds_enforced(self):
        from services.comms.contracts import CommunicationEventPayload
        with pytest.raises(Exception):
            CommunicationEventPayload(
                tenant_id="t1", provider="p", provider_event_id="e",
                occurred_at="2026-07-01T00:00:00+00:00",
                engagement_confidence=1.5,
            )


class TestProductBoundary:
    """ADR-C1 — Aether observes; it never originates communications."""

    def test_no_send_capable_surface_in_comms_domain(self):
        comms_dir = BACKEND_ROOT / "services" / "comms"
        banned = ("smtplib", "send_email(", "def send_message", "sendmail")
        for path in comms_dir.glob("*.py"):
            source = path.read_text()
            for marker in banned:
                assert marker not in source, f"{path.name} contains send capability: {marker}"
