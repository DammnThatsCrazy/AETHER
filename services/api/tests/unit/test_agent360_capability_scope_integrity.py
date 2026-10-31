"""Fail-closed checks for Agent360's canonical capability grant reader."""

import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
os.environ.setdefault("AETHER_ENV", "local")
os.environ.setdefault("JWT_SECRET", "test-secret")

from actions.agent.agent360_provider import Agent360Provider


def grant():
    return {
        "tenant_id": "tenant-a",
        "agent_id": "agent-a",
        "grantee_entity_id": "agent-a",
        "authorization_id": "grant-a",
        "authorization_kind": "capability",
        "capability_id": "tool-a",
        "scope": {"actions": ["invoke"], "resources": ["capability:tool-a"]},
        "state": "active",
    }


@pytest.mark.parametrize("field,value", [
    ("starts_at", "tomorrow"),
    ("ends_at", "2026-11-01T00:00:00"),
    ("revoked_at", 42),
])
def test_invalid_temporal_evidence_invalidates_grant_read(field, value):
    record = grant()
    record[field] = value
    assert Agent360Provider._validate_capability_grant_records(
        [record], "tenant-a", "agent-a"
    ) == ([], False)


@pytest.mark.parametrize("identifier", ["*", "tool-*", "tool-a ", " tool-a"])
def test_non_exact_capability_scope_invalidates_grant_read(identifier):
    record = grant()
    record["capability_id"] = identifier
    record["scope"]["resources"] = [f"capability:{identifier}"]
    assert Agent360Provider._validate_capability_grant_records(
        [record], "tenant-a", "agent-a"
    ) == ([], False)


def test_wildcard_server_scope_invalidates_grant_read():
    record = grant()
    record.update(capability_id=None, server_ref="srv_*")
    record["scope"]["resources"] = ["capability-server:srv_*"]
    assert Agent360Provider._validate_capability_grant_records(
        [record], "tenant-a", "agent-a"
    ) == ([], False)


def test_exact_grant_with_aware_boundaries_is_retained():
    record = grant()
    record.update(starts_at="2026-10-01T00:00:00+00:00", ends_at="2026-11-01T00:00:00+00:00")
    assert Agent360Provider._validate_capability_grant_records(
        [record], "tenant-a", "agent-a"
    ) == ([record], True)


@pytest.mark.parametrize("field,value", [
    ("authorization_id", " grant-a"),
    ("capability_id", "tool-a "),
    ("server_ref", " srv-a"),
])
def test_padded_grant_join_identifiers_invalidate_the_read(field, value):
    record = grant()
    if field == "server_ref":
        record.update(capability_id=None, server_ref=value)
        record["scope"]["resources"] = [f"capability-server:{value.strip()}"]
    else:
        record[field] = value
        if field == "capability_id":
            record["scope"]["resources"] = [f"capability:{value.strip()}"]
    assert Agent360Provider._validate_capability_grant_records(
        [record], "tenant-a", "agent-a"
    ) == ([], False)


def test_capability_policy_decision_requires_exact_tenant_agent_resource_and_time():
    decision = {
        "decision_id": "decision-1", "tenant_id": "tenant-a", "policy_key": "capability.invoke",
        "actor_type": "tenant_user", "resource_type": "capability", "resource_id": "tool-a",
        "action": "invoke", "allowed": True,
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
        "context": {"agent_id": "agent-a", "capability_id": "tool-a",
                    "capability_grant_record_id": "grant-a", "capability_observed": True},
    }
    assert Agent360Provider._validate_capability_policy_decisions(
        [decision], "tenant-a", "agent-a"
    )[1] is True
    for field, value in (("tenant_id", "tenant-b"), ("resource_id", "tool-b"),
                         ("actor_type", "agent"),
                         ("resource_id", " tool-a "),
                         ("evaluated_at", (datetime.now(timezone.utc) + timedelta(days=1)).isoformat())):
        candidate = {**decision, field: value}
        assert Agent360Provider._validate_capability_policy_decisions(
            [candidate], "tenant-a", "agent-a"
        ) == ([], False)
    candidate = {**decision, "context": {**decision["context"], "agent_id": " agent-b"}}
    assert Agent360Provider._validate_capability_policy_decisions(
        [candidate], "tenant-a", "agent-a"
    ) == ([], False)
    candidate = {**decision, "decision_id": " decision-1"}
    assert Agent360Provider._validate_capability_policy_decisions(
        [candidate], "tenant-a", "agent-a"
    ) == ([], False)
    candidate = {
        **decision,
        "context": {**decision["context"], "capability_grant_record_id": " grant-a"},
    }
    assert Agent360Provider._validate_capability_policy_decisions(
        [candidate], "tenant-a", "agent-a"
    ) == ([], False)


def test_well_formed_other_agent_evaluation_does_not_incomplete_scoped_history():
    now = datetime.now(timezone.utc).isoformat()
    own = {
        "decision_id": "decision-own", "tenant_id": "tenant-a", "policy_key": "capability.invoke",
        "actor_type": "tenant_user", "resource_type": "capability", "resource_id": "tool-a",
        "action": "invoke", "allowed": False, "evaluated_at": now,
        "context": {"agent_id": "agent-a", "capability_id": "tool-a", "capability_observed": True},
    }
    other = {
        **own,
        "decision_id": "decision-other",
        "context": {**own["context"], "agent_id": "agent-b"},
    }
    rows, complete = Agent360Provider._validate_capability_policy_decisions(
        [other, own], "tenant-a", "agent-a"
    )
    assert complete is True
    assert [row["decision_id"] for row in rows] == ["decision-own"]

    malformed_other = {**other, "action": "read"}
    rows, complete = Agent360Provider._validate_capability_policy_decisions(
        [malformed_other, own], "tenant-a", "agent-a"
    )
    assert complete is False
    assert [row["decision_id"] for row in rows] == ["decision-own"]


@pytest.mark.parametrize(
    "evaluated_at,starts_at,ends_at,revoked_at,expected",
    [
        ("2026-10-01T00:00:00Z", "2026-10-01T00:00:00Z", None, None, True),
        ("2026-09-30T23:59:59Z", "2026-10-01T00:00:00Z", None, None, False),
        ("2026-11-01T00:00:00Z", None, "2026-11-01T00:00:00Z", None, False),
        ("2026-10-20T00:00:00Z", None, None, "2026-10-20T00:00:00Z", False),
        ("2026-10-19T23:59:59Z", None, None, "2026-10-20T00:00:00Z", True),
    ],
)
def test_allowed_policy_evaluation_must_fall_within_grant_interval(
    evaluated_at, starts_at, ends_at, revoked_at, expected
):
    record = grant()
    record.update(starts_at=starts_at, ends_at=ends_at, revoked_at=revoked_at)
    evaluation = {"evaluated_at": evaluated_at}
    assert Agent360Provider._capability_evaluation_within_grant(evaluation, record) is expected
