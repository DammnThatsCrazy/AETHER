import pytest

from value.economic.attribution_model_validation import (
    ValueModelApprovalRepository,
    decide_value_model_approval,
)


TENANT = "tenant-value-test"
RUN_ID = "00000000-0000-4000-8000-000000000101"
CONFIG_ID = "00000000-0000-4000-8000-000000000102"


class Runs:
    def __init__(self):
        self.config = {
            "tenant_id": TENANT,
            "model_config_id": CONFIG_ID,
            "model_type": "last_touch",
            "model_version": "v2",
            "status": "active",
            "effective_from": "2026-01-01T00:00:00Z",
            "effective_until": None,
            "click_lookback_window": 30,
            "view_lookback_window": 1,
            "identity_confidence_min": 0.9,
            "fraud_policy": "exclude",
            "direct_traffic_policy": "last_touch",
            "engaged_view_threshold_ms": 1000,
        }
        self.run = {
            "tenant_id": TENANT,
            "conversion_id": "00000000-0000-4000-8000-000000000103",
            "attribution_run_id": RUN_ID,
            "model_config_id": CONFIG_ID,
            "model_type": "last_touch",
            "model_version": "v2",
            "status": "complete",
            "created_at": "2026-01-02T00:00:00Z",
            "model_config_snapshot": dict(self.config),
        }

    async def get_run(self, run_id, *, tenant_id):
        return dict(self.run) if run_id == RUN_ID and tenant_id == TENANT else None

    async def get_model_config(self, tenant_id, config_id):
        return dict(self.config) if tenant_id == TENANT and config_id == CONFIG_ID else None


class Decisions:
    async def get(self, tenant_id, run_id):
        return None

    async def insert(self, decision):
        return decision


@pytest.mark.asyncio
async def test_value_approval_is_derived_from_authenticated_actor_and_exact_run_lineage(monkeypatch):
    monkeypatch.setenv("AETHER_ENV", "local")
    repository = ValueModelApprovalRepository()
    result = await decide_value_model_approval(
        TENANT, RUN_ID, "approved", actor_id="admin-1", reason="Reviewed exact run evidence.",
        runs=Runs(), decisions=Decisions(), approvals=repository,
    )
    assert result["tenant_id"] == TENANT
    assert result["attribution_run_id"] == RUN_ID
    assert result["model_config_id"] == CONFIG_ID
    assert result["validation_decision_id"].startswith("amv_")
    assert result["actor_id"] == "admin-1"
    assert result["decision"] == "approved"
    assert (await repository.latest(TENANT, RUN_ID))["decision_id"] == result["decision_id"]


@pytest.mark.asyncio
async def test_value_approval_rejects_free_form_decision_and_missing_actor(monkeypatch):
    monkeypatch.setenv("AETHER_ENV", "local")
    with pytest.raises(ValueError):
        await decide_value_model_approval(
            TENANT, RUN_ID, "calibrated", actor_id="admin-1", reason="Review",
            runs=Runs(), decisions=Decisions(), approvals=ValueModelApprovalRepository(),
        )
    with pytest.raises(ValueError):
        await decide_value_model_approval(
            TENANT, RUN_ID, "approved", actor_id=" ", reason="Review",
            runs=Runs(), decisions=Decisions(), approvals=ValueModelApprovalRepository(),
        )
