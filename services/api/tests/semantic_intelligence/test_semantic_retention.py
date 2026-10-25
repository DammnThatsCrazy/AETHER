"""Semantic retention sweep.

Proves the sweep tombstones aged Silver observations and deletes aged
(recomputable) Gold projections past the ``standard_90d`` window, while leaving
fresh rows untouched.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from repositories.repos import reset_in_memory_stores
from intelligence.semantic_intelligence.models import utc_now
from intelligence.semantic_intelligence.repositories.base_fact_repo import (
    SemanticFactRepository,
)
from intelligence.semantic_intelligence.retention import sweep_tenant

TENANT = "tenant_retain"

_SILVER_TABLE = "silver_semantic_observations"
_MEMORY_TABLE = "semantic_memory_records"
_EMBEDDING_TABLE = "semantic_embedding_metadata"
_WORKFLOW_TABLE = "workflow_definition_revisions"
_GOLD_TABLE = "gold_entity_semantic_state"


@pytest.fixture(autouse=True)
def _isolate():
    reset_in_memory_stores()
    yield
    reset_in_memory_stores()


async def _seed_silver(record_id: str, subject: str, age_days: float, *, rclass="standard_90d"):
    repo = SemanticFactRepository(_SILVER_TABLE)
    occurred = utc_now() - timedelta(days=age_days)
    await repo.upsert(
        {
            "id": record_id,
            "tenant_id": TENANT,
            "subject_ref": subject,
            "occurred_at": occurred,
            "idempotency_key": f"silver:{record_id}",
            "data": {
                "idempotency_key": f"silver:{record_id}",
                "primary_subject_ref": subject,
                "retention_class": rclass,
                "occurred_at": occurred.isoformat(),
                "status": "classified",
            },
        }
    )


async def _seed_memory(record_id: str, subject: str, age_days: float):
    repo = SemanticFactRepository(_MEMORY_TABLE)
    occurred = utc_now() - timedelta(days=age_days)
    await repo.upsert(
        {
            "id": record_id,
            "tenant_id": TENANT,
            "subject_ref": subject,
            "occurred_at": occurred,
            "idempotency_key": f"semantic-memory:{TENANT}:{record_id}",
            "data": {
                "memory_id": record_id,
                "tenant_id": TENANT,
                "subject_ref": subject,
                "retention_class": "standard_90d",
                "status": "classified",
                "idempotency_key": f"semantic-memory:{TENANT}:{record_id}",
            },
        }
    )


async def _seed_gold(record_id: str, subject: str, age_days: float):
    repo = SemanticFactRepository(_GOLD_TABLE, mode="gold")
    occurred = utc_now() - timedelta(days=age_days)
    await repo.upsert(
        {
            "id": record_id,
            "tenant_id": TENANT,
            "subject_ref": subject,
            "occurred_at": occurred,
            "idempotency_key": f"gold:{record_id}",
            "data": {"idempotency_key": f"gold:{record_id}", "subject_ref": subject, "version": 2},
        }
    )


def _status(table: str, record_id: str):
    return SemanticFactRepository(table)._store[record_id]["data"].get("status")


def _exists(table: str, record_id: str) -> bool:
    return record_id in SemanticFactRepository(table)._store


async def test_sweep_tombstones_aged_silver_keeps_fresh():
    await _seed_silver("aged", "s_aged", age_days=200)
    await _seed_silver("fresh", "s_fresh", age_days=1)

    report = await sweep_tenant(TENANT)

    assert report["tombstoned_total"] == 1
    assert _status(_SILVER_TABLE, "aged") == "expired"
    assert _status(_SILVER_TABLE, "fresh") == "classified"


async def test_sweep_tombstones_aged_memory_keeps_fresh():
    await _seed_memory("mem_aged", "s_mem_aged", age_days=200)
    await _seed_memory("mem_fresh", "s_mem_fresh", age_days=1)

    report = await sweep_tenant(TENANT)

    assert report["tombstoned"]["semantic_memory_records"] == 1
    assert _status(_MEMORY_TABLE, "mem_aged") == "expired"
    assert _status(_MEMORY_TABLE, "mem_fresh") == "classified"


async def test_sweep_deletes_aged_gold_keeps_fresh():
    await _seed_gold("g_aged", "s_aged", age_days=200)
    await _seed_gold("g_fresh", "s_fresh", age_days=1)

    report = await sweep_tenant(TENANT)

    assert report["deleted_total"] == 1
    assert not _exists(_GOLD_TABLE, "g_aged")
    assert _exists(_GOLD_TABLE, "g_fresh")


async def test_unknown_retention_class_is_left_untouched():
    # A class we do not recognise must never be aged out (fail safe).
    await _seed_silver("aged_unknown", "s_x", age_days=400, rclass="legal_hold_forever")
    report = await sweep_tenant(TENANT)
    assert report["tombstoned_total"] == 0
    assert _status(_SILVER_TABLE, "aged_unknown") == "classified"


async def test_sweep_uses_authority_statuses_without_overwriting_restrictions():
    old = utc_now() - timedelta(days=100)
    for table, statuses in (
        (_EMBEDDING_TABLE, ("reported", "consent_restricted")),
        (_WORKFLOW_TABLE, ("active", "retired")),
    ):
        repo = SemanticFactRepository(table)
        for status in statuses:
            record_id = f"{table}:{status}"
            await repo.upsert(
                {
                    "id": record_id,
                    "tenant_id": TENANT,
                    "subject_ref": "subject-1",
                    "occurred_at": old,
                    "data": {
                        "idempotency_key": record_id,
                        "retention_class": "standard_90d",
                        "status": status,
                    },
                }
            )

    report = await sweep_tenant(TENANT)

    assert report["tombstoned"] == {
        _EMBEDDING_TABLE: 1,
        _WORKFLOW_TABLE: 1,
    }
    assert _status(_EMBEDDING_TABLE, f"{_EMBEDDING_TABLE}:reported") == "expired"
    assert _status(_EMBEDDING_TABLE, f"{_EMBEDDING_TABLE}:consent_restricted") == "consent_restricted"
    assert _status(_WORKFLOW_TABLE, f"{_WORKFLOW_TABLE}:active") == "expired"
    assert _status(_WORKFLOW_TABLE, f"{_WORKFLOW_TABLE}:retired") == "retired"
