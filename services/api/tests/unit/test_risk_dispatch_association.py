from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from actions.agent.risk_dispatch_association import read_risk_dispatches, validate_current_risk_decision


class Repository:
    def __init__(self, value):
        self.value = value

    async def list_for_subject(self, *args, **kwargs):
        return self.value

    async def find_many(self, **kwargs):
        return self.value

    async def find_by_id(self, identifier):
        return self.value.get(identifier)


@pytest.mark.asyncio
async def test_current_decision_rejects_supersession_ambiguity_and_incomplete_history():
    now = datetime.now(timezone.utc)
    decision = SimpleNamespace(record_kind="decision", intervention_id="i", effective_at=now - timedelta(seconds=2),
                               record_id="r", decision_state="approved", tenant_id="t", subject_kind="agent",
                               subject_id="s", intervention_type="review", recorded_at=now, observed_at=now)
    link = {"subject_kind": "agent", "subject_id": "s", "intervention_id": "i", "record_id": "r",
            "action_key": "review"}
    await validate_current_risk_decision("t", link, Repository(SimpleNamespace(records=[decision], complete=True)))
    newer = SimpleNamespace(record_kind="decision", intervention_id="i", effective_at=now - timedelta(seconds=1),
                            record_id="r2", decision_state="rejected", tenant_id="t", subject_kind="agent",
                            subject_id="s", intervention_type="review", recorded_at=now, observed_at=now)
    for result in (SimpleNamespace(records=[decision, newer], complete=True),
                   SimpleNamespace(records=[decision, decision], complete=True),
                   SimpleNamespace(records=[decision], complete=False)):
        with pytest.raises(ValueError):
            await validate_current_risk_decision("t", link, Repository(result))

    for field, value in (("tenant_id", "other"), ("subject_id", "other"), ("subject_kind", "entity"),
                         ("intervention_type", "other"), ("recorded_at", now + timedelta(days=1)),
                         ("observed_at", now + timedelta(days=1))):
        original = getattr(decision, field)
        setattr(decision, field, value)
        with pytest.raises(ValueError):
            await validate_current_risk_decision("t", link, Repository(SimpleNamespace(records=[decision], complete=True)))
        setattr(decision, field, original)


@pytest.mark.asyncio
async def test_reader_validates_exact_joins_and_fails_closed():
    now = datetime.now(timezone.utc)
    record = SimpleNamespace(tenant_id="t", record_id="r", subject_id="s", subject_kind="entity",
                             intervention_id="i", intervention_type="review", record_kind="decision",
                             decision_state="approved", recorded_at=now - timedelta(seconds=2),
                             observed_at=now - timedelta(seconds=2), effective_at=now - timedelta(seconds=2))
    link = {"kind": "risk_intervention", "link_state": "caller_associated", "record_id": "r",
            "subject_id": "s", "subject_kind": "entity", "intervention_id": "i", "action_key": "review",
            "action_type": "review", "recommendation_id": "rec"}
    row = {"id": "d", "dispatch_id": "d", "tenant_id": "t", "action_id": "a", "decision_id": "dec",
           "recommendation_id": "rec", "risk_action_association_record_id": "r", "risk_action_association": link,
           "status": "queued", "created_at": now.isoformat()}
    action = {"tenant_id": "t", "action_id": "a", "decision_id": "dec", "recommendation_id": "rec", "action_type": "review"}
    decision = {"tenant_id": "t", "decision_id": "dec", "recommendation_id": "rec", "decision_status": "approved",
                "selected_action": {"action_key": "review", "action_type": "review"}}
    recommendation = {"tenant_id": "t", "recommendation_id": "rec", "entity_id": "s"}
    kwargs = dict(tenant_id="t", record=record, dispatches=Repository([row]), actions=Repository({"a": action}),
                  decisions=Repository({"dec": decision}), recommendations=Repository({"rec": recommendation}))
    rows, complete = await read_risk_dispatches(**kwargs)
    assert complete and rows[0]["externalEffect"] == "not_independently_verified"
    for field in ("recorded_at", "observed_at", "effective_at"):
        original = getattr(record, field)
        setattr(record, field, now + timedelta(seconds=1))
        assert await read_risk_dispatches(**kwargs) == ([], False)
        setattr(record, field, original)
    record.decision_state = "rejected"
    assert await read_risk_dispatches(**kwargs) == ([], False)
    record.decision_state = "approved"
    record.record_kind = "outcome"
    assert await read_risk_dispatches(**kwargs) == ([], False)
    record.record_kind = "decision"
    recommendation["entity_id"] = "other"
    assert await read_risk_dispatches(**kwargs) == ([], False)
    recommendation["entity_id"] = "s"
    recommendation["population_id"] = "population"
    assert await read_risk_dispatches(**kwargs) == ([], False)
    recommendation.pop("population_id")
    action["tenant_id"] = "other"
    assert await read_risk_dispatches(**kwargs) == ([], False)


@pytest.mark.asyncio
@pytest.mark.parametrize("tenant,kind,state", [("other", "decision", "approved"),
                                              ("t", "outcome", "approved"),
                                              ("t", "decision", "rejected")])
async def test_empty_dispatches_do_not_validate_invalid_record(tenant, kind, state):
    record = SimpleNamespace(tenant_id=tenant, record_kind=kind, decision_state=state, record_id="r")
    rows, complete = await read_risk_dispatches(tenant_id="t", record=record, dispatches=Repository([]),
                                                actions=Repository({}), decisions=Repository({}),
                                                recommendations=Repository({}))
    assert rows == [] and not complete
