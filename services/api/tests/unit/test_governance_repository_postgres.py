import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from intelligence.model_governance.evaluations import ModelEvaluationRepository
from value.economic.attribution_model_validation import ValueModelApprovalRepository


@pytest.mark.asyncio
@pytest.mark.parametrize("encoded", [True, False])
@pytest.mark.parametrize("reader", ["get_evaluation", "latest_for_artifact"])
async def test_evaluation_postgres_read_decodes_all_evidence(monkeypatch, encoded, reader):
    metrics = {"expected_calibration_error": 0.2}
    samples = [{"prediction_id": "prediction-1", "outcome_id": "outcome-1"}]
    row = {
        "evaluation_id": "evaluation-1", "tenant_id": "tenant-a",
        "metrics": json.dumps(metrics) if encoded else metrics,
        "sample_refs": json.dumps(samples) if encoded else samples,
    }

    async def fetchrow(query, *parameters):
        assert "tenant_id=$1" in query
        assert parameters[0] == "tenant-a"
        return row

    async def pool():
        return SimpleNamespace(fetchrow=fetchrow)

    repository = ModelEvaluationRepository()
    monkeypatch.setattr(repository, "_pool", pool)
    if reader == "get_evaluation":
        result = await repository.get_evaluation("tenant-a", "evaluation-1")
    else:
        result = await repository.latest_for_artifact(
            "tenant-a", "profile360", "model-a", "v1", "a" * 64,
        )
    assert result["sample_refs"] == samples
    assert result["metrics"] == metrics


@pytest.mark.asyncio
async def test_approval_insert_conflict_target_matches_migration_primary_key(monkeypatch):
    migration_path = (
        Path(__file__).resolve().parents[2] / "alembic" / "versions"
        / "20261030_model_governance_evaluations_approvals.py"
    )
    spec = importlib.util.spec_from_file_location("governance_migration", migration_path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    statements = []
    monkeypatch.setattr(migration, "op", SimpleNamespace(execute=statements.append))
    migration.upgrade()
    approval_ddl = statements[0].split("CREATE TABLE value_model_approval_decisions", 1)[1]
    assert "decision_id TEXT PRIMARY KEY" in approval_ddl
    repository = ValueModelApprovalRepository()

    async def fetchrow(query, *parameters):
        assert "ON CONFLICT (decision_id) DO NOTHING" in query
        assert parameters == ("approval-1", "tenant-a")
        return {"inserted": 1}

    async def pool():
        return SimpleNamespace(fetchrow=fetchrow)

    monkeypatch.setattr(repository, "_pool", pool)
    assert await repository.insert({"decision_id": "approval-1", "tenant_id": "tenant-a"})
