"""Journey dispatch association requires exact tenant and canonical records."""
from __future__ import annotations
from datetime import datetime, timezone
import pytest
from actions.agent.journey_dispatch_association import read_journey_dispatches


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["valid", "foreign", "wrong_version", "wrong_recommendation", "wrong_action", "foreign_decision", "unapproved", "future", "before_occurrence", "before_recording", "truncated", "missing_policy", "foreign_policy", "wrong_policy_action", "wrong_policy_resource", "future_policy"])
async def test_exact_journey_dispatch_chain(case):
    link = {"kind": "journey_action_intent", "link_state": "caller_associated", "record_id": "intent-1",
            "subject_id": "journey-1", "version_id": "version-1", "action_key": "notice",
            "action_type": "send", "recommendation_id": "rec-1"}
    dispatch = {"id": "dispatch-1", "dispatch_id": "dispatch-1", "tenant_id": "tenant-a",
                "action_id": "action-1", "decision_id": "decision-1", "recommendation_id": "rec-1",
                "dispatch_policy_decision_id": "policy-1",
                "journey_action_association_record_id": "intent-1", "journey_action_association": link,
                "status": "delivered", "created_at": "2026-10-18T10:00:02Z"}
    action = {"tenant_id": "tenant-a", "action_id": "action-1", "decision_id": "decision-1",
              "recommendation_id": "rec-1", "action_type": "send"}
    decision = {"tenant_id": "tenant-a", "decision_id": "decision-1", "recommendation_id": "rec-1",
                "decision_status": "approved", "selected_action": {"action_key": "notice", "action_type": "send"}}
    recommendation = {"tenant_id": "tenant-a", "recommendation_id": "rec-1"}
    policy_decision = {"decision_id": "policy-1", "tenant_id": "tenant-a", "policy_key": "action.dispatch",
                       "actor_id": "user-1", "actor_type": "tenant_user", "action": "dispatch",
                       "resource_type": "action", "resource_id": "action-1", "allowed": True,
                       "evaluated_at": "2026-10-18T10:00:01Z"}
    if case == "missing_policy":
        dispatch.pop("dispatch_policy_decision_id")
    if case == "foreign_policy":
        policy_decision["tenant_id"] = "tenant-b"
    if case == "wrong_policy_action":
        policy_decision["allowed"] = False
    if case == "wrong_policy_resource":
        policy_decision["resource_id"] = "other-action"
    if case == "future_policy":
        policy_decision["evaluated_at"] = "2999-10-18T10:00:01Z"
    if case == "foreign": dispatch["tenant_id"] = "tenant-b"
    if case == "wrong_version": link["version_id"] = "other"
    if case == "wrong_recommendation": link["recommendation_id"] = "other"
    if case == "wrong_action": action["action_type"] = "other"
    if case == "foreign_decision": decision["tenant_id"] = "tenant-b"
    if case == "unapproved": decision["decision_status"] = "rejected"
    if case == "future": dispatch["created_at"] = "2999-10-18T10:00:02Z"
    if case in {"before_occurrence", "before_recording"}: dispatch["created_at"] = "2026-10-18T09:59:59Z"
    class Dispatches:
        async def find_many(self, *, filters, limit):
            assert filters == {"tenant_id": "tenant-a", "journey_action_association_record_id": "intent-1"}
            return [dispatch] * limit if case == "truncated" else [dispatch]
    class Record:
        def __init__(self, row): self.row = row
        async def find_by_id(self, key): return self.row
    rows, complete = await read_journey_dispatches(tenant_id="tenant-a", journey_id="journey-1", version_id="version-1",
        record_id="intent-1", action_key="notice", action_type="send", recommendation_id="rec-1",
        recorded_at=datetime(2026, 10, 18, 9 if case == "before_occurrence" else 10, tzinfo=timezone.utc),
        occurred_at=datetime(2026, 10, 18, 9 if case == "before_recording" else 10, tzinfo=timezone.utc), dispatches=Dispatches(),
        actions=Record(action), decisions=Record(decision), recommendations=Record(recommendation),
        policy_decisions=Record(policy_decision))
    if case == "valid":
        assert complete and rows[0]["status"] == "delivered"
        assert rows[0]["externalEffect"] == "not_independently_verified"
        assert {ref["source"] for ref in rows[0]["evidenceRefs"]} == {
            "action_dispatches", "action_feedback", "decision_records", "recommendations",
            "security_policy_decisions",
        }
        assert rows[0]["dispatchAuthorization"]["decision_id"] == "policy-1"
    else:
        assert not complete and rows == []
