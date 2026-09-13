# DO NOT EDIT — generated from packages/shared/contracts/outcome-type-registry.json
# Run: python scripts/generate_platform_contracts.py
"""Generated outcome-type registry (Outcome360)."""

from __future__ import annotations

OUTCOME_TYPE_REGISTRY_CONTRACT_VERSION = "1.0.0"

# Outcome domains a type may belong to (sorted).
OUTCOME_DOMAINS: tuple[str, ...] = (
    "agentic",
    "commercial",
    "economic",
    "fraud",
    "institutional",
    "onchain",
    "operational",
    "product",
    "security",
)

# Registered outcome types (sorted).
OUTCOME_TYPE_IDS: tuple[str, ...] = (
    "access_control_enforced",
    "agent_objective_attainment",
    "agent_task_completion",
    "campaign_conversion",
    "chargeback_avoidance",
    "compliance_milestone_met",
    "engagement_completion",
    "fraud_prevention_hit",
    "governance_proposal_passed",
    "journey_completion",
    "onchain_settlement_completed",
    "reconciliation_completed",
    "retention_window_achieved",
    "revenue_attainment",
    "roas_attainment",
    "sla_attainment",
)

# Full outcome-type definitions (sorted by id).
OUTCOME_TYPE_DEFINITIONS: dict[str, dict] = {
    "access_control_enforced": {
        "description": "An entitlement or access decision was evaluated and enforced correctly (allow/deny matches policy).",
        "domain": "security",
        "id": "access_control_enforced",
        "name": "Access Control Enforced"
    },
    "agent_objective_attainment": {
        "description": "An agent-executed objective/OKR was attained within its declared budget and constraints.",
        "domain": "agentic",
        "id": "agent_objective_attainment",
        "name": "Agent Objective Attainment"
    },
    "agent_task_completion": {
        "description": "An agent-executed task reached its terminal success state with corroborating evidence.",
        "domain": "agentic",
        "id": "agent_task_completion",
        "name": "Agent Task Completion"
    },
    "campaign_conversion": {
        "description": "A campaign subject completed a target conversion event (signup, purchase, order, closed-won).",
        "domain": "commercial",
        "id": "campaign_conversion",
        "name": "Campaign Conversion"
    },
    "chargeback_avoidance": {
        "description": "A dispute was resolved in the subject's favor without chargeback loss, or a predicted dispute was prevented.",
        "domain": "fraud",
        "id": "chargeback_avoidance",
        "name": "Chargeback Avoidance"
    },
    "compliance_milestone_met": {
        "description": "A compliance or regulatory milestone (audit, certification, filing, attestation) was met on schedule.",
        "domain": "institutional",
        "id": "compliance_milestone_met",
        "name": "Compliance Milestone Met"
    },
    "engagement_completion": {
        "description": "A product workflow (onboarding, activation, migration) reached its defined completion state.",
        "domain": "product",
        "id": "engagement_completion",
        "name": "Engagement Completion"
    },
    "fraud_prevention_hit": {
        "description": "A fraudulent activity was blocked or intercepted before material loss occurred.",
        "domain": "fraud",
        "id": "fraud_prevention_hit",
        "name": "Fraud Prevention Hit"
    },
    "governance_proposal_passed": {
        "description": "A governance proposal reached quorum and passed according to the governing policy.",
        "domain": "institutional",
        "id": "governance_proposal_passed",
        "name": "Governance Proposal Passed"
    },
    "journey_completion": {
        "description": "A journey reached its terminal converted state (backed by the measurement journey engine).",
        "domain": "commercial",
        "id": "journey_completion",
        "name": "Journey Completion"
    },
    "onchain_settlement_completed": {
        "description": "An on-chain settlement finalized on its target chain with the expected finality.",
        "domain": "onchain",
        "id": "onchain_settlement_completed",
        "name": "On-Chain Settlement Completed"
    },
    "reconciliation_completed": {
        "description": "A ledger or system reconciliation reached zero outstanding variance within the window.",
        "domain": "operational",
        "id": "reconciliation_completed",
        "name": "Reconciliation Completed"
    },
    "retention_window_achieved": {
        "description": "A subject retained engagement past a contractual or product retention window.",
        "domain": "product",
        "id": "retention_window_achieved",
        "name": "Retention Window Achieved"
    },
    "revenue_attainment": {
        "description": "Recognized revenue attained the declared target within the measurement window.",
        "domain": "economic",
        "id": "revenue_attainment",
        "name": "Revenue Attainment"
    },
    "roas_attainment": {
        "description": "Return on ad spend attained the declared target for the campaign or episode.",
        "domain": "economic",
        "id": "roas_attainment",
        "name": "Return on Ad Spend Attainment"
    },
    "sla_attainment": {
        "description": "A service-level agreement (latency, uptime, response) was met within the measurement window.",
        "domain": "operational",
        "id": "sla_attainment",
        "name": "SLA Attainment"
    },
}

__all__ = [
    "OUTCOME_DOMAINS",
    "OUTCOME_TYPE_DEFINITIONS",
    "OUTCOME_TYPE_IDS",
    "OUTCOME_TYPE_REGISTRY_CONTRACT_VERSION",
]
