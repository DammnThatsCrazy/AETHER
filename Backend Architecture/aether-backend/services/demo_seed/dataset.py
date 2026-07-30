from __future__ import annotations

from .manifest import DEFAULT_NAMESPACE, build_manifest, stable_id
from .models import SeedManifest, SeedRecord


def v1_manifest(namespace: str = DEFAULT_NAMESPACE) -> SeedManifest:
    """Small representative dataset whose records are visible to real APIs."""
    definitions = (
        ("tenant", "tenants", "demo-tenant", -86400, {
            "name": "Aether Demonstration Tenant",
            "status": "active",
            "is_demo_tenant": True,
            "plan": "sandbox",
        }),
        ("user", "users", "demo-operator", -82800, {
            "email": "demo.operator@example.invalid",
            "display_name": "Demo Operator",
            "status": "active",
        }),
        ("entity", "entities", "sample-customer", -7200, {
            "entity_type": "human",
            "display_name": "Synthetic Customer",
            "metadata": {"segment": "demonstration"},
        }),
        ("campaign", "campaigns", "launch-campaign", -5400, {
            "name": "Synthetic Launch Campaign",
            "status": "active",
            "channel": "email",
        }),
        ("commerce", "economic_resources", "inference-resource", -3600, {
            "resource_type": "inference",
            "provider": "internal_demo",
            "capability": "synthetic-inference",
            "protocol": "x402",
            "pricing": {"amount": "0.01", "currency": "USDC"},
        }),
        ("payment_rail", "payment_intents", "inference-payment", -1800, {
            "agent_id": "synthetic-agent",
            "amount": "0.01",
            "currency": "USDC",
            "provider": "internal_demo",
            "protocol": "x402",
            "settlement_status": "settled",
        }),
        ("payment_rail", "settlement_events", "inference-settlement", -1740, {
            "agent_id": "synthetic-agent",
            "status": "settled",
            "amount": "0.01",
            "currency": "USDC",
            "provider": "internal_demo",
            "protocol": "x402",
        }),
        ("operator_alert", "alerts", "review-alert", -900, {
            "severity": "warning",
            "status": "open",
            "title": "Synthetic review example",
        }),
        ("connector", "providers", "internal-connector", -850, {
            "name": "Synthetic Internal Connector",
            "provider_type": "internal_demo",
            "status": "configured",
            "credentials_configured": False,
            "health_status": "unknown",
            "credentials_ref": None,
        }),
        ("usage", "metering_evidence", "metered-events", -800, {
            "source_path": "synthetic_seed",
            "source_provider": "internal_demo",
            "event_id": "synthetic-usage-event",
            "dedupe_key": "synthetic-seed-usage-v1",
            "billable": False,
            "billing_reason": "synthetic demonstration evidence",
            "excluded_reason": "synthetic_seed",
            "schema_version": "1.0.0",
            "usage_dimension": "events",
            "quantity": 12,
            "metadata": {"provider_origin": "internal_sandbox"},
            "_time_offsets": {"received_at": -800, "metered_at": -800},
        }),
        ("data_quality", "data_quality_scores", "tenant-quality-score", -750, {
            "_seed_target_id": "tenant:{tenant_id}",
            "scope": "tenant",
            "availability": "available",
            "status": "warning",
            "overall_intelligence_quality_score": 0.78,
            "event_quality_score": 0.82,
            "schema_stability_score": 0.74,
            "identity_resolution_score": 0.77,
            "graph_quality_score": 0.79,
            "profile_quality_score": 0.76,
            "recommendation_quality_score": 0.8,
            "outcome_feedback_quality_score": 0.73,
            "playbook_quality_score": 0.83,
            "_time_offsets": {"calculated_at": -750},
        }),
        ("import", "import_sessions", "customer-import", -700, {
            "status": "validated",
            "source_kind": "file_upload",
            "file_count": 1,
            "row_count": 3,
            "created_by": "synthetic-seed",
        }),
        ("investigation", "investigations", "identity-review", -650, {
            "title": "Synthetic identity review",
            "status": "open",
            "severity": "medium",
            "investigation_type": "identity_resolution",
            "summary": "Synthetic evidence requiring operator review.",
        }),
        ("commerce_resource", "commerce_resources", "protected-report", -600, {
            "name": "Synthetic Protected Report",
            "description": "Synthetic resource used to demonstrate governed access.",
            "resource_type": "api",
            "path_pattern": "^/v1/demo/reports/.*$",
            "active": True,
            "price": {"amount": "0.01", "currency": "USDC"},
        }),
        ("commerce_policy", "commerce_policies", "sandbox-spend-policy", -550, {
            "name": "Synthetic Sandbox Spend Policy",
            "rule_type": "spend_limit",
            "active": True,
            "rules": {"max_amount_usd": 1.0, "requires_approval": True},
        }),
        ("commerce_facilitator", "commerce_facilitators", "sandbox-facilitator", -500, {
            "name": "Synthetic Sandbox Facilitator",
            "facilitator_type": "x402",
            "active": True,
            "health_status": "unknown",
            "accepted_assets": [{"symbol": "USDC", "network": "sandbox"}],
        }),
        ("commerce_approval", "commerce_approvals", "report-approval", -450, {
            "challenge_id": "synthetic-challenge-v1",
            "requester_id": "synthetic-agent",
            "requester_type": "agent",
            "amount_usd": 0.01,
            "asset_symbol": "USDC",
            "chain": "sandbox",
            "priority": "normal",
            "status": "approved",
            "decision_reason": "Synthetic demonstration approval",
        }),
        ("commerce_settlement", "commerce_settlements", "report-settlement", -400, {
            "state": "settled",
            "amount": "0.01",
            "asset_symbol": "USDC",
            "chain": "sandbox",
            "provider": "internal_demo",
            "retries": 0,
        }),
        ("commerce_entitlement", "commerce_entitlements", "report-entitlement", -350, {
            "holder_id": "synthetic-agent",
            "holder_type": "agent",
            "granted_to": "synthetic-agent",
            "scope": "read",
            "status": "active",
            "reuse_count": 0,
            "_time_offsets": {"expires_at": 86400},
        }),
    )
    records: list[SeedRecord] = []
    ids: dict[str, str] = {}
    for domain, repository, logical_name, offset, payload in definitions:
        record_id = stable_id(namespace, domain, logical_name)
        ids[logical_name] = record_id
        records.append(SeedRecord(
            domain=domain,
            repository=repository,
            logical_name=logical_name,
            record_id=record_id,
            offset_seconds=offset,
            payload=dict(payload),
        ))

    # Reconcile the representative payment event to its underlying intent.
    for record in records:
        if record.logical_name == "inference-settlement":
            record.payload["intent_id"] = ids["inference-payment"]
        elif record.logical_name == "report-approval":
            record.payload["resource_id"] = ids["protected-report"]
        elif record.logical_name == "report-settlement":
            record.payload["resource_id"] = ids["protected-report"]
            record.payload["approval_id"] = ids["report-approval"]
        elif record.logical_name == "report-entitlement":
            record.payload["resource_id"] = ids["protected-report"]
            record.payload["settlement_id"] = ids["report-settlement"]
    return build_manifest(records, namespace=namespace)
