"""Semantic retention sweep.

Proves the sweep tombstones aged Silver observations and deletes aged
(recomputable) Gold projections past the ``standard_90d`` window, while leaving
fresh rows untouched.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from repositories.repos import reset_in_memory_stores
from services.semantic_intelligence.models import utc_now
from services.semantic_intelligence.repositories.base_fact_repo import (
    SemanticFactRepository,
)
from services.semantic_intelligence.retention import sweep_tenant

TENANT = "tenant_retain"

_SILVER_TABLE = "silver_semantic_observations"
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
