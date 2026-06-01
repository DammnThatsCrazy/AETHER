from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from repositories.repos import reset_in_memory_stores
from services.intelligence import routes
from services.intelligence.solution_packages import SOLUTION_PACKAGES, integrity_hash, redact_secrets


class Tenant:
    def __init__(self, tenant_id="tenant-a", permissions=None):
        self.tenant_id = tenant_id
        self.permissions = set(permissions or {"read", "write", "admin", "export"})
        self.user_id = "user-1"

    def require_permission(self, permission):
        if permission not in self.permissions:
            raise AssertionError(f"missing permission {permission}")


def req(tenant_id="tenant-a", permissions=None):
    return SimpleNamespace(state=SimpleNamespace(tenant=Tenant(tenant_id, permissions)))


@pytest.fixture(autouse=True)
def clean():
    reset_in_memory_stores()


@pytest.mark.asyncio
async def seed_loop(tenant_id="tenant-a"):
    rec = {
        "recommendation_id": "rec-1",
        "tenant_id": tenant_id,
        "entity_id": "entity-1",
        "recommendation_type": "operational_failure",
        "confidence": {"overall": 0.8},
        "evidence": [{"evidence_id": "ev-1", "source_type": "event", "source_id": "event-1", "summary": "signal"}],
        "policy_governance_flags": ["human_approval_required"],
        "data_freshness": {"status": "fresh"},
        "status": "generated",
        "expected_value": 100,
        "created_at": "2026-06-01T00:00:00Z",
    }
    decision = {"decision_id": "dec-1", "tenant_id": tenant_id, "recommendation_id": "rec-1", "actor_id": "actor-1", "selected_action": {"action_key": "a1"}, "rejected_actions": [], "decision_status": "approved", "reason": "ok", "comment": "approved", "created_at": "2026-06-01T00:01:00Z"}
    action = {"action_id": "act-1", "tenant_id": tenant_id, "decision_id": "dec-1", "action_type": "ticket", "status": "executed", "authorization_metadata": {"approval_id": "ap-1", "api_key": "secret"}, "created_at": "2026-06-01T00:02:00Z"}
    dispatch = {"dispatch_id": "disp-1", "tenant_id": tenant_id, "action_id": "act-1", "decision_id": "dec-1", "recommendation_id": "rec-1", "target_type": "ticket", "status": "delivered", "payload": {"safe": True, "secret": "hidden"}, "idempotency_key": "idem-1", "created_at": "2026-06-01T00:03:00Z"}
    receipt = {"receipt_id": "rcpt-1", "dispatch_id": "disp-1", "target_type": "ticket", "delivered_at": "2026-06-01T00:04:00Z", "status": "delivered", "raw": {}}
    outcome = {"outcome_id": "out-1", "tenant_id": tenant_id, "action_id": "act-1", "recommendation_id": "rec-1", "entity_id": "entity-1", "outcome_type": "revenue", "value": 250, "label": "success", "observed_window": {"start": "2026-06-01", "end": "2026-06-02"}, "computed_at": "2026-06-02T00:00:00Z", "confidence_delta": 0.05}
    playbook = {"playbook_id": "pb-1", "tenant_id": tenant_id, "name": "Ops", "trigger": "operational_failure", "recommendation_types": ["operational_failure"], "created_at": "2026-06-01T00:00:00Z"}
    run = {"run_id": "run-1", "playbook_id": "pb-1", "tenant_id": tenant_id, "status": "completed", "generated_recommendation_ids": ["rec-1"], "started_at": "2026-06-01T00:00:00Z"}
    await routes._recommendations.insert("rec-1", rec)
    await routes._decisions.insert("dec-1", decision)
    await routes._actions.insert("act-1", action)
    await routes._dispatches.insert("disp-1", dispatch)
    await routes._delivery_receipts.insert("rcpt-1", receipt)
    await routes._outcomes.insert("out-1", outcome)
    await routes._playbooks.insert("pb-1", playbook)
    await routes._playbook_runs.insert("run-1", run)


def body(export_type, tenant_id="tenant-a", fmt="json"):
    return routes.AuditExportRequest(export_type=export_type, tenant_id=tenant_id, time_window={"start": "2026-06-01", "end": "2026-06-30"}, format=fmt, include_evidence=True, include_dispatch_receipts=True, include_confidence_deltas=True)


def unwrap(resp):
    return resp["data"]


def test_package_definitions_load_and_government_is_planning():
    assert len(SOLUTION_PACKAGES) == 6
    gov = [p for p in SOLUTION_PACKAGES if "government_planning" in (p.market if isinstance(p.market, list) else [p.market])]
    assert gov
    assert all(p.readiness_status == "government_planning" for p in gov)


@pytest.mark.asyncio
async def test_audit_export_type_listing_creation_hash_and_secret_redaction():
    await seed_loop()
    types = unwrap(await routes.list_audit_export_types(req()))
    assert types["count"] == 8
    created = unwrap(await routes.create_audit_export(body("action_dispatch_audit"), req()))
    assert created["status"] == "generated"
    download = unwrap(await routes.download_audit_export(created["export_id"], req()))
    payload_text = json.dumps(download["payload"])
    assert "hidden" not in payload_text and "secret" in payload_text
    assert download["integrity_hash"] == integrity_hash(download["payload"])
    assert download["payload"][0]["delivery_receipts"][0]["receipt_id"] == "rcpt-1"


@pytest.mark.asyncio
async def test_audit_export_tenant_isolation():
    await seed_loop("tenant-a")
    created = unwrap(await routes.create_audit_export(body("recommendation_audit", tenant_id="tenant-a"), req("tenant-a")))
    with pytest.raises(Exception):
        await routes.get_audit_export(created["export_id"], req("tenant-b"))
    with pytest.raises(Exception):
        await routes.create_audit_export(body("recommendation_audit", tenant_id="tenant-b"), req("tenant-a"))


@pytest.mark.asyncio
async def test_outcome_and_playbook_audit_contents():
    await seed_loop()
    outcome_export = unwrap(await routes.create_audit_export(body("outcome_audit"), req()))
    outcome_payload = unwrap(await routes.download_audit_export(outcome_export["export_id"], req()))["payload"]
    assert outcome_payload[0]["confidence_delta"] == 0.05
    playbook_export = unwrap(await routes.create_audit_export(body("playbook_run_audit"), req()))
    playbook_payload = unwrap(await routes.download_audit_export(playbook_export["export_id"], req()))["payload"]
    assert playbook_payload["playbooks"][0]["playbook_id"] == "pb-1"
    assert playbook_payload["linked_outcomes"][0]["outcome_id"] == "out-1"


@pytest.mark.asyncio
async def test_tenant_package_fit_and_kyber_readiness_endpoints():
    await seed_loop()
    metrics = await routes._tenant_usage_metrics("tenant-a")
    fits = routes._tenant_package_fit_from_metrics("tenant-a", metrics)
    assert fits[0]["package_fit_score"] > 0
    readiness = unwrap(await routes.kyber_package_readiness(req(permissions={"admin"})))
    assert readiness["count"] == 6
    deployment = unwrap(await routes.kyber_deployment_readiness(req(permissions={"admin"})))
    assert any(i["name"] == "government_ready_planning" for i in deployment["items"])


def test_redact_secrets_helper_excludes_raw_secrets():
    assert redact_secrets({"api_key": "abc", "nested": {"secret": "xyz"}}) == {"api_key": "[redacted]", "nested": {"secret": "[redacted]"}}
