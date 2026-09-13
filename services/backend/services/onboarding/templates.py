"""Package-specific onboarding templates."""
from __future__ import annotations

from typing import Any

from shared.common.common import utc_now
from .models import ImplementationSuccessCriteria


def _step(title: str, category: str, owner_type: str = "shared", required: bool = True, description: str = "") -> dict[str, Any]:
    return {"title": title, "description": description or title, "category": category, "owner_type": owner_type, "required": required}


def _template(template_id: str, package_id: str, name: str, description: str, steps: list[dict[str, Any]], criteria: ImplementationSuccessCriteria, playbooks: list[str], integrations: list[str], audit_exports: list[str]) -> dict[str, Any]:
    now = utc_now().isoformat()
    return {
        "template_id": template_id,
        "package_id": package_id,
        "name": name,
        "description": description,
        "default_steps": steps,
        "default_success_criteria": criteria.model_dump(),
        "recommended_playbooks": playbooks,
        "recommended_integrations": integrations,
        "recommended_audit_exports": audit_exports,
        "created_at": now,
        "updated_at": now,
    }

ONBOARDING_TEMPLATES: list[dict[str, Any]] = [
    _template(
        "tpl_revenue_intelligence_graph",
        "revenue_intelligence_graph",
        "Revenue Intelligence Graph",
        "Contract-to-value onboarding for retention, expansion, Profile360, integrations, and outcome proof.",
        [
            _step("tenant created", "tenant_setup", "olympus"),
            _step("SDK installed", "sdk", "tenant"),
            _step("commerce events mapped", "events", "shared"),
            _step("customer identity resolution verified", "identity", "shared"),
            _step("Profile360 active", "graph", "olympus"),
            _step("retention recommendations enabled", "intelligence", "olympus"),
            _step("expansion recommendations enabled", "intelligence", "olympus"),
            _step("outcome ledger enabled", "outcomes", "olympus"),
            _step("retention/expansion playbooks configured", "playbooks", "shared"),
            _step("CRM/marketing integration configured", "integrations", "shared"),
            _step("first outcomes captured", "outcomes", "shared"),
            _step("value review completed", "expansion", "shared"),
        ],
        ImplementationSuccessCriteria(required_events_received=["commerce.order", "subscription.renewal", "customer.updated"], minimum_event_volume=100, graph_active=True, recommendations_generated=True, playbooks_configured=True, integrations_connected=True, outcomes_observed=True, value_threshold=1.0, training_completed=True, go_live_approved=True),
        ["retention_save", "expansion_motion"], ["crm", "marketing_automation"], ["outcome_audit", "recommendation_audit"],
    ),
    _template(
        "tpl_fraud_risk_intelligence_graph", "fraud_risk_intelligence_graph", "Fraud & Risk Intelligence Graph",
        "Fraud-review onboarding from event/entity mapping to investigation, queue actions, audits, and avoided-loss outcomes.",
        [_step("tenant created", "tenant_setup", "olympus"), _step("SDK/events configured", "sdk", "tenant"), _step("identity/entity mapping verified", "identity", "shared"), _step("graph traversal active", "graph", "olympus"), _step("fraud review recommendations enabled", "intelligence", "olympus"), _step("investigation workspace enabled", "intelligence", "olympus"), _step("fraud cluster playbook configured", "playbooks", "shared"), _step("review queue/action integration configured", "integrations", "shared"), _step("audit export configured", "integrations", "olympus"), _step("avoided-loss outcomes captured", "outcomes", "shared")],
        ImplementationSuccessCriteria(required_events_received=["risk.signal", "transaction.attempted", "identity.linked"], minimum_event_volume=100, graph_active=True, recommendations_generated=True, playbooks_configured=True, integrations_connected=True, outcomes_observed=True, go_live_approved=True),
        ["fraud_cluster_review"], ["review_queue", "case_management"], ["decision_audit", "investigation_audit"],
    ),
    _template(
        "tpl_agent_governance_graph", "agent_governance_graph", "Agent Governance Graph",
        "Agent governance onboarding with agent event capture, H2A/A2H/A2A graph activation, approval controls, and audit exports.",
        [_step("agent event capture configured", "sdk", "tenant"), _step("agent identity mapping verified", "identity", "shared"), _step("H2A/A2H/A2A relationships active", "graph", "olympus"), _step("agent governance recommendations enabled", "intelligence", "olympus"), _step("approval policies configured", "intelligence", "shared"), _step("agent failure playbook configured", "playbooks", "shared"), _step("action dispatch configured", "integrations", "shared"), _step("audit export configured", "integrations", "olympus"), _step("agent outcomes captured", "outcomes", "shared")],
        ImplementationSuccessCriteria(required_events_received=["agent.task", "agent.decision", "approval.requested"], minimum_event_volume=50, graph_active=True, recommendations_generated=True, playbooks_configured=True, integrations_connected=True, outcomes_observed=True, go_live_approved=True),
        ["agent_failure_response"], ["action_dispatch", "approval_queue"], ["agent_governance_audit", "action_dispatch_audit"],
    ),
    _template(
        "tpl_operational_decision_intelligence", "operational_decision_intelligence", "Operational Decision Intelligence",
        "OODA onboarding covering recommendations, decisions, actions, feedback, playbooks, integrations, and value review.",
        [_step("OODA lifecycle enabled", "intelligence", "olympus"), _step("recommendations enabled", "intelligence", "olympus"), _step("decision records enabled", "intelligence", "shared"), _step("action logging enabled", "integrations", "shared"), _step("outcome feedback enabled", "outcomes", "shared"), _step("playbooks configured", "playbooks", "shared"), _step("integrations configured", "integrations", "shared"), _step("outcome ledger enabled", "outcomes", "olympus"), _step("value review completed", "expansion", "shared")],
        ImplementationSuccessCriteria(required_events_received=["recommendation.generated", "decision.recorded", "action.logged"], minimum_event_volume=25, graph_active=True, recommendations_generated=True, playbooks_configured=True, integrations_connected=True, outcomes_observed=True, value_threshold=1.0, go_live_approved=True),
        ["ooda_value_loop"], ["ticketing", "ops_action_log"], ["decision_audit", "outcome_audit"],
    ),
    _template(
        "tpl_program_integrity_planning", "program_integrity_graph_planning", "Program Integrity Graph Planning",
        "Government planning path for program integrity use cases, audit requirements, HITL policy, investigation workflows, and readiness review.",
        [_step("use case mapped", "contract", "shared"), _step("entity/case schema mapped", "events", "shared"), _step("audit requirements documented", "integrations", "shared"), _step("human-in-the-loop policy configured", "intelligence", "shared"), _step("investigation workflow configured", "playbooks", "shared"), _step("decision audit export configured", "integrations", "olympus"), _step("outcome tracking configured", "outcomes", "shared"), _step("deployment readiness reviewed", "training", "shared")],
        ImplementationSuccessCriteria(required_events_received=["case.opened", "eligibility.decision"], minimum_event_volume=10, graph_active=False, playbooks_configured=True, integrations_connected=True, training_completed=True, go_live_approved=True),
        ["program_integrity_investigation"], ["case_management"], ["decision_audit", "compliance_audit"],
    ),
    _template(
        "tpl_critical_infrastructure_planning", "critical_infrastructure_coordination_graph_planning", "Critical Infrastructure Coordination Graph Planning",
        "Planning onboarding for dependency mapping, operational events, incident/action workflows, audit exports, and tabletop criteria.",
        [_step("dependency entities mapped", "events", "shared"), _step("operational events mapped", "events", "shared"), _step("incident/action workflows configured", "integrations", "shared"), _step("playbooks configured", "playbooks", "shared"), _step("audit export configured", "integrations", "olympus"), _step("deployment readiness reviewed", "training", "shared"), _step("tabletop/pilot success criteria defined", "expansion", "shared")],
        ImplementationSuccessCriteria(required_events_received=["incident.opened", "dependency.status", "action.dispatched"], minimum_event_volume=10, graph_active=False, playbooks_configured=True, integrations_connected=True, training_completed=True, go_live_approved=True),
        ["critical_infrastructure_incident"], ["incident_management", "status_page"], ["incident_audit", "action_dispatch_audit"],
    ),
]
