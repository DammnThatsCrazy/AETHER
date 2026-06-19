"""E2E tests: Bronze ingest → Bronze→Silver promotion pipeline (Dune feeder)."""
from __future__ import annotations

import importlib
import sys
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "Backend Architecture" / "aether-backend"
_PREFIXES = ("config", "services", "shared", "middleware", "dependencies", "repositories")


@contextmanager
def backend_module_path():
    original = list(sys.path)
    for prefix in _PREFIXES:
        for name in list(sys.modules):
            if name == prefix or name.startswith(f"{prefix}."):
                sys.modules.pop(name, None)
    sys.path.insert(0, str(BACKEND_ROOT))
    try:
        yield
    finally:
        sys.path[:] = original
        for prefix in _PREFIXES:
            for name in list(sys.modules):
                if name == prefix or name.startswith(f"{prefix}."):
                    sys.modules.pop(name, None)


@pytest.fixture()
def feeder(monkeypatch):
    monkeypatch.setenv("AETHER_ENV", "local")
    monkeypatch.setenv("JWT_SECRET", "test-secret")
    with backend_module_path():
        repos = importlib.import_module("repositories.repos")
        repos.reset_in_memory_stores()
        lake = importlib.import_module("repositories.lake")
        svc = importlib.import_module("services.integrations.dune_feeder.service")
        bronze = lake.BronzeRepository("dune_feeder")
        silver = lake.SilverRepository("dune_feeder")
        make_raw = lake.make_raw_record
        yield SimpleNamespace(
            bronze_repo=bronze,
            silver_repo=silver,
            promotion_service=svc.PromotionService(),
            record_feeder_run=svc.record_feeder_run,
            get_feeder_health=svc.get_feeder_health,
            make_raw_record=make_raw,
        )


def _fresh_row(entity_id: str = "e1", **extra) -> dict:
    return {
        "entity_id": entity_id,
        "entity_type": "wallet",
        "ingested_at": datetime.now(timezone.utc).isoformat(),
        "value": 100,
        **extra,
    }


def _stale_row(entity_id: str = "e1") -> dict:
    stale_ts = (datetime.now(timezone.utc) - timedelta(hours=48)).isoformat()
    return {"entity_id": entity_id, "entity_type": "wallet", "ingested_at": stale_ts, "value": 100}


@pytest.mark.asyncio
async def test_bronze_to_silver_promotion_pass(feeder):
    bronze = feeder.bronze_repo
    for i in range(3):
        await bronze.ingest(
            source="dune", source_tag="dune:q1",
            provider_record_id=f"q1:exec1:{i}",
            payload=_fresh_row(entity_id=f"e{i}"),
            schema_version="1.0",
            entity_id=f"e{i}", entity_type="wallet", tenant_id="t1",
        )

    result = await feeder.promotion_service.promote_batch(
        feeder.bronze_repo, feeder.silver_repo,
        source_tag="dune:q1", tenant_id="t1",
        entity_id_field="entity_id",
        required_fields=["entity_id"], max_age_hours=24, null_rate_threshold=0.3,
    )

    assert result["promoted_count"] > 0
    assert result["rejected_count"] == 0


@pytest.mark.asyncio
async def test_bronze_to_silver_freshness_gate(feeder):
    # Insert raw bronze record with an old ingested_at directly
    stale_ts = (datetime.now(timezone.utc) - timedelta(hours=48)).isoformat()
    raw = feeder.make_raw_record(
        source="dune", source_tag="dune:q2",
        provider_record_id="q2:exec1:0",
        payload={"entity_id": "e-stale", "entity_type": "wallet", "value": 1},
        entity_id="e-stale", entity_type="wallet", tenant_id="t1",
    )
    raw["ingested_at"] = stale_ts  # override to stale timestamp
    await feeder.bronze_repo.insert(raw["id"], raw)

    result = await feeder.promotion_service.promote_batch(
        feeder.bronze_repo, feeder.silver_repo,
        source_tag="dune:q2", tenant_id="t1",
        entity_id_field="entity_id",
        required_fields=["entity_id"], max_age_hours=24, null_rate_threshold=0.3,
    )

    assert result["promoted_count"] == 0
    assert result["rejected_count"] > 0
    reasons = [r.get("failed_checks", []) for r in result.get("rejection_reasons", [])]
    flat = [c for sublist in reasons for c in sublist]
    assert any("freshness" in c for c in flat)


@pytest.mark.asyncio
async def test_bronze_to_silver_null_rate_gate(feeder):
    # Row with >30% null values: 4 null out of 6 payload fields = 67%
    # Promotion checks payload directly (row_data = payload.get("row", payload))
    high_null_payload = {
        "entity_id": "e-null", "entity_type": "wallet",
        "f1": None, "f2": None, "f3": None, "f4": None,
    }
    raw = feeder.make_raw_record(
        source="dune", source_tag="dune:q3",
        provider_record_id="q3:exec1:0",
        payload=high_null_payload,
        entity_id="e-null", entity_type="wallet", tenant_id="t1",
    )
    await feeder.bronze_repo.insert(raw["id"], raw)

    result = await feeder.promotion_service.promote_batch(
        feeder.bronze_repo, feeder.silver_repo,
        source_tag="dune:q3", tenant_id="t1",
        entity_id_field="entity_id",
        required_fields=["entity_id"], max_age_hours=24, null_rate_threshold=0.3,
    )

    assert result["promoted_count"] == 0
    reasons = [r.get("failed_checks", []) for r in result.get("rejection_reasons", [])]
    flat = [c for sublist in reasons for c in sublist]
    assert any("null_rate" in c for c in flat)


@pytest.mark.asyncio
async def test_bronze_to_silver_required_fields_gate(feeder):
    # Row missing the required field "account_id"
    raw = feeder.make_raw_record(
        source="dune", source_tag="dune:q4",
        provider_record_id="q4:exec1:0",
        payload={"entity_id": "e-missing", "entity_type": "wallet"},
        entity_id="e-missing", entity_type="wallet", tenant_id="t1",
    )
    await feeder.bronze_repo.insert(raw["id"], raw)

    result = await feeder.promotion_service.promote_batch(
        feeder.bronze_repo, feeder.silver_repo,
        source_tag="dune:q4", tenant_id="t1",
        entity_id_field="entity_id",
        required_fields=["entity_id", "account_id"],
        max_age_hours=24, null_rate_threshold=0.3,
    )

    assert result["promoted_count"] == 0
    reasons = [r.get("failed_checks", []) for r in result.get("rejection_reasons", [])]
    flat = [c for sublist in reasons for c in sublist]
    assert any("required_fields" in c for c in flat)


@pytest.mark.asyncio
async def test_feeder_run_recorded(feeder):
    await feeder.record_feeder_run(
        tenant_id="t1",
        source="dune",
        source_tag="dune:q5",
        rows_ingested=10,
        rows_promoted=8,
        rows_rejected=2,
    )

    records = await feeder.get_feeder_health(tenant_id="t1")
    assert records, "Expected at least one feeder run record"
    health = records[0]
    assert health.get("rows_ingested") == 10
    assert health.get("rows_promoted") == 8
    assert health.get("rows_rejected") == 2
