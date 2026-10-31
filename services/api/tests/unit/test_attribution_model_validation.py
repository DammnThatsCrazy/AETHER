"""Exact attribution run/config lineage is persisted without a calibration claim."""

from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID, uuid4

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[2]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))
os.environ.setdefault("AETHER_ENV", "local")
os.environ.setdefault("JWT_SECRET", "test-secret")

from value.economic.attribution_model_validation import (  # noqa: E402
    _decision_for,
    _decision_id_for_scope,
    _same_decision,
    validate_attribution_run_model,
)


def _fixtures():
    now = datetime.now(timezone.utc)
    run_id, config_id = str(uuid4()), str(uuid4())
    config = {
        "tenant_id": "tenant-a", "model_config_id": config_id,
        "model_type": "linear", "model_version": "v2", "status": "active",
        "effective_from": now,
    }
    run = {
        "tenant_id": "tenant-a", "attribution_run_id": run_id,
        "model_config_id": config_id, "model_type": "linear",
        "model_version": "v2", "status": "complete", "created_at": now,
        "model_config_snapshot": {
            **config, "effective_from": str(now),
            "click_lookback_window": 24,
            "view_lookback_window": 168,
            "identity_confidence_min": 0.0,
            "fraud_policy": "exclude",
            "direct_traffic_policy": "include",
            "engaged_view_threshold_ms": 0,
        },
    }
    return run, config


def test_exact_decision_is_deterministic_and_uncalibrated():
    run, config = _fixtures()
    first = _decision_for("tenant-a", run, config)
    second = _decision_for("tenant-a", run, config)
    assert first["decision_id"] == second["decision_id"]
    assert first["calibration_state"] == "unvalidated"
    assert _same_decision(
        {**first, "attribution_run_id": UUID(first["attribution_run_id"]),
         "model_config_id": UUID(first["model_config_id"])}, first
    )
    assert not _same_decision({**first, "tenant_id": "tenant-b"}, first)


@pytest.mark.parametrize("binding_change", [
    {"tenant_id": "tenant-b"},
    {"attribution_run_id": str(uuid4())},
    {"model_config_id": str(uuid4())},
    {"config_snapshot_sha256": "f" * 64},
    {"config_snapshot_sha256": "not-a-sha256"},
])
def test_decision_id_is_bound_to_exact_tenant_run_config_and_snapshot(binding_change):
    run, config = _fixtures()
    decision = _decision_for("tenant-a", run, config)
    binding = {
        "tenant_id": "tenant-a",
        "attribution_run_id": run["attribution_run_id"],
        "model_config_id": run["model_config_id"],
        "config_snapshot_sha256": decision["config_snapshot_sha256"],
    }
    assert _decision_id_for_scope(**binding) == decision["decision_id"]
    assert _decision_id_for_scope(**(binding | binding_change)) != decision["decision_id"]


@pytest.mark.parametrize("mutation", [
    lambda run, config: run.update(model_config_id=None),
    lambda run, config: run.update(status="pending"),
    lambda run, config: run["model_config_snapshot"].update(model_version="v3"),
    lambda run, config: config.update(tenant_id="tenant-b"),
    lambda run, config: config.update(model_version="v3"),
    lambda run, config: config.update(status="inactive"),
    lambda run, config: config.update(name="changed after run"),
    lambda run, config: config.update(effective_until=run["created_at"] - timedelta(seconds=1)),
])
def test_invalid_lineage_fails_closed(mutation):
    run, config = _fixtures()
    mutation(run, config)
    with pytest.raises(ValueError, match="lineage"):
        _decision_for("tenant-a", run, config)


@pytest.mark.parametrize("field", [
    "click_lookback_window", "view_lookback_window", "identity_confidence_min",
    "fraud_policy", "direct_traffic_policy", "engaged_view_threshold_ms",
])
def test_missing_effective_setting_fails_closed(field):
    run, config = _fixtures()
    del run["model_config_snapshot"][field]
    with pytest.raises(ValueError, match="lineage"):
        _decision_for("tenant-a", run, config)


@pytest.mark.asyncio
async def test_producer_rejects_a_different_returned_run():
    run, config = _fixtures()

    class Runs:
        async def get_run(self, run_id, tenant_id):
            return run

    with pytest.raises(ValueError, match="tenant attribution run"):
        await validate_attribution_run_model("tenant-a", str(uuid4()), runs=Runs())


@pytest.mark.asyncio
async def test_producer_uses_exact_tenant_run_and_config():
    run, config = _fixtures()

    class Runs:
        async def get_run(self, run_id, tenant_id):
            return run if tenant_id == "tenant-a" and run_id == run["attribution_run_id"] else None

        async def get_model_config(self, tenant_id, config_id):
            assert tenant_id == "tenant-a"
            return config if config_id == config["model_config_id"] else None

    class Decisions:
        def __init__(self):
            self.rows = {}

        async def insert(self, decision):
            prior = self.rows.setdefault(decision["attribution_run_id"], decision)
            assert _same_decision(prior, decision)
            return prior

    decisions = Decisions()
    first = await validate_attribution_run_model(
        "tenant-a", run["attribution_run_id"], runs=Runs(), decisions=decisions
    )
    second = await validate_attribution_run_model(
        "tenant-a", run["attribution_run_id"], runs=Runs(), decisions=decisions
    )
    assert first == second
    assert first["validation_state"] == "exact_config_lineage_validated"
    with pytest.raises(ValueError, match="tenant attribution run"):
        await validate_attribution_run_model(
            "tenant-b", run["attribution_run_id"], runs=Runs(), decisions=decisions
        )


@pytest.mark.asyncio
async def test_attribution_reader_joins_only_matching_decision(monkeypatch):
    from journeys.measurement.repositories import attribution_run_repo
    from value.economic import attribution_model_validation as validation
    from value.economic.economic360_provider import RepositoryAttributionCreditReader

    run, config = _fixtures()
    conversion_id = str(uuid4())
    run.update(conversion_id=conversion_id, is_active=True, completed_at=run["created_at"])
    decision = _decision_for("tenant-a", run, config)

    class Runs:
        async def get_active_run(self, tenant_id, requested_conversion):
            return run if (tenant_id, requested_conversion) == ("tenant-a", conversion_id) else None

        async def get_model_config(self, tenant_id, config_id):
            return config if (tenant_id, config_id) == ("tenant-a", run["model_config_id"]) else None

        async def list_credits_for_run(self, tenant_id, run_id, *, limit):
            return []

    class Decisions:
        async def get(self, tenant_id, run_id):
            return decision if (tenant_id, run_id) == ("tenant-a", run["attribution_run_id"]) else None

    monkeypatch.setattr(attribution_run_repo, "AttributionRunRepository", Runs)
    monkeypatch.setattr(validation, "AttributionModelValidationRepository", Decisions)
    result = await RepositoryAttributionCreditReader().read("tenant-a", [conversion_id])
    assert result["runs"][0]["modelGovernance"]["decisionId"] == decision["decision_id"]
    decision["tenant_id"] = "tenant-b"
    result = await RepositoryAttributionCreditReader().read("tenant-a", [conversion_id])
    assert result["runs"][0]["modelGovernance"]["state"] == "unknown"
    decision["tenant_id"] = "tenant-a"
    config["model_version"] = "changed"
    result = await RepositoryAttributionCreditReader().read("tenant-a", [conversion_id])
    assert result["runs"][0]["modelGovernance"]["state"] == "unknown"
