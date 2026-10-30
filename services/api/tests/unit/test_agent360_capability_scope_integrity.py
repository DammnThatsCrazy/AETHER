"""Fail-closed checks for Agent360's canonical capability grant reader."""

import os
import sys
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
