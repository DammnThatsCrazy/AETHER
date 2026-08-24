<!-- DO NOT EDIT — generated from packages/shared/contracts/outcome-type-registry.json -->
<!-- Run: python scripts/generate_platform_contracts.py -->

# Outcome360 — Outcome Type Registry

Contract version: `1.0.0`

Canonical outcome-type vocabulary the Outcome360 projection consumes — every type belongs to exactly one domain.

| Domain | Outcome type | Name | Description |
|---|---|---|---|
| `security` | `access_control_enforced` | Access Control Enforced | An entitlement or access decision was evaluated and enforced correctly (allow/deny matches policy). |
| `agentic` | `agent_objective_attainment` | Agent Objective Attainment | An agent-executed objective/OKR was attained within its declared budget and constraints. |
| `agentic` | `agent_task_completion` | Agent Task Completion | An agent-executed task reached its terminal success state with corroborating evidence. |
| `commercial` | `campaign_conversion` | Campaign Conversion | A campaign subject completed a target conversion event (signup, purchase, order, closed-won). |
| `fraud` | `chargeback_avoidance` | Chargeback Avoidance | A dispute was resolved in the subject's favor without chargeback loss, or a predicted dispute was prevented. |
| `institutional` | `compliance_milestone_met` | Compliance Milestone Met | A compliance or regulatory milestone (audit, certification, filing, attestation) was met on schedule. |
| `product` | `engagement_completion` | Engagement Completion | A product workflow (onboarding, activation, migration) reached its defined completion state. |
| `fraud` | `fraud_prevention_hit` | Fraud Prevention Hit | A fraudulent activity was blocked or intercepted before material loss occurred. |
| `institutional` | `governance_proposal_passed` | Governance Proposal Passed | A governance proposal reached quorum and passed according to the governing policy. |
| `commercial` | `journey_completion` | Journey Completion | A journey reached its terminal converted state (backed by the measurement journey engine). |
| `onchain` | `onchain_settlement_completed` | On-Chain Settlement Completed | An on-chain settlement finalized on its target chain with the expected finality. |
| `operational` | `reconciliation_completed` | Reconciliation Completed | A ledger or system reconciliation reached zero outstanding variance within the window. |
| `product` | `retention_window_achieved` | Retention Window Achieved | A subject retained engagement past a contractual or product retention window. |
| `economic` | `revenue_attainment` | Revenue Attainment | Recognized revenue attained the declared target within the measurement window. |
| `economic` | `roas_attainment` | Return on Ad Spend Attainment | Return on ad spend attained the declared target for the campaign or episode. |
| `operational` | `sla_attainment` | SLA Attainment | A service-level agreement (latency, uptime, response) was met within the measurement window. |
