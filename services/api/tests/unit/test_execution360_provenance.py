"""Exact, bounded Bronze ingress provenance for Execution360 telemetry."""

from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[2]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

os.environ.setdefault("AETHER_ENV", "local")
os.environ.setdefault("JWT_SECRET", "test-secret")

from actions.agent.execution360_provenance import read_execution_source_provenance  # noqa: E402
from repositories import repos  # noqa: E402


TENANT = "execution-provenance-tenant"
TIME = "2026-10-25T12:00:00+00:00"


def _bronze(
    *,
    event_id: str = "bronze-event-1",
    tenant_id: str = TENANT,
    schema_version: str = "7.0",
    event_type: str = "agent_tool_call_observed",
) -> dict:
    return {
        "id": f"bronze-row-{tenant_id}-{event_id}-{schema_version}",
        "tenant_id": tenant_id,
        "event_id": event_id,
        "schema_version": schema_version,
        "event_type": event_type,
        # PostgreSQL returns this typed column as datetime.
        "event_timestamp": datetime(2026, 10, 25, 12, tzinfo=timezone.utc),
        "payload": {
            "event_id": event_id,
            "event_type": event_type,
            "observation_envelope": {
                "tenancy": {"tenant_id": tenant_id},
                "observation": {
                    "observation_id": event_id,
                    "observation_type": event_type,
                    "occurred_at": TIME,
                },
                "source": {"source_provider": "authenticated-provider-claim"},
                "rights": {"source_id": "source-1"},
                "provenance": {
                    "source_trust": "PUBLIC_CLIENT",
                    "credential_class": "PUBLIC_CLIENT",
                    "signature_status": "not_present",
                    "adapter": "sdk",
                    "adapter_version": "1.0.0",
                },
            },
            "properties": {"prompt": "must-not-be-exposed"},
        },
    }


@pytest.mark.asyncio
async def test_exact_bronze_join_accepts_typed_database_timestamp_without_payload_leak(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Conn:
        async def fetch(self, sql: str, tenant_id: str, event_ids: list[str], bound: int):
            assert "WHERE tenant_id = $1 AND event_id = ANY($2::text[])" in sql
            assert (tenant_id, event_ids, bound) == (TENANT, ["bronze-event-1"], 3)
            return [_bronze()]

    class Acquire:
        async def __aenter__(self):
            return Conn()

        async def __aexit__(self, *_args: object):
            return None

    class Pool:
        def acquire(self):
            return Acquire()

    async def get_pool():
        return Pool()

    monkeypatch.setattr(repos, "get_pool", get_pool)
    read = await read_execution_source_provenance(
        tenant_id=TENANT,
        events=(("bronze-event-1", "agent_tool_call_observed"),),
    )
    assert read.available and read.scope_known and not read.truncated
    assert len(read.rows) == 1
    record = read.rows[0]
    assert record["sourceEventId"] == "bronze-event-1"
    assert record["sourceId"] == "source-1"
    assert record["bronzeSchemaVersion"] == "7.0"
    assert record["sourceIdentityVerified"] is False
    assert record["externalExecutionVerified"] is False
    assert record["evidenceRef"]["source"] == "bronze_sdk_events"
    assert "must-not-be-exposed" not in str(record)


@pytest.mark.asyncio
async def test_duplicate_schema_versions_and_mismatched_envelopes_remain_unlinked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def no_pool():
        return None

    monkeypatch.setattr(repos, "get_pool", no_pool)
    malformed = _bronze(event_id="bronze-event-2")
    malformed["payload"]["observation_envelope"]["tenancy"]["tenant_id"] = "other-tenant"
    monkeypatch.setitem(
        repos._IN_MEMORY_STORES,
        "bronze_sdk_events",
        {
            "first": _bronze(),
            "second-version": _bronze(schema_version="8.0"),
            "malformed": malformed,
            "foreign": _bronze(event_id="bronze-event-2", tenant_id="other-tenant"),
        },
    )
    read = await read_execution_source_provenance(
        tenant_id=TENANT,
        events=(
            ("bronze-event-1", "agent_tool_call_observed"),
            ("bronze-event-2", "agent_tool_call_observed"),
        ),
    )
    assert read.available and not read.scope_known
    assert read.rows == []
    assert read.unmatched_count == 2
    assert read.reason == "source_provenance_exact_join_incomplete"
