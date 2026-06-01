---
title: Playbooks
slug: ai/playbooks
section: ai
visibility: I
audience: [ai, architect, dev-senior, ops, exec]
status: beta
since_version: "8.9.0"
source_files:
  - Backend Architecture/aether-backend/services/intelligence/playbooks.py
  - Backend Architecture/aether-backend/services/intelligence/routes.py
  - packages/shared/decision-outcome-intelligence.ts
flags:
  - AETHER_PLAYBOOKS_ENABLED
  - AETHER_RECOMMENDATIONS_ENABLED
related:
  - ai/decision-outcome-intelligence
  - ai/outcome-ledger
  - ai/recommendation-families
  - ai/investigation-workspace
---

# Playbooks

Playbooks turn recurring graph-native recommendation patterns into governed, reusable operational workflows. They are not a separate product layer: a playbook evaluation still enters the same recommendation → investigation → decision → action → outcome → ledger lifecycle used by Decision & Outcome Intelligence.

## Lifecycle

1. **Template selection** — a tenant lists built-in templates with `GET /v1/intelligence/playbooks/templates`.
2. **Tenant playbook creation** — `POST /v1/intelligence/playbooks/from-template` copies a template into a tenant-owned `PlaybookDefinition`.
3. **Trigger evaluation** — `POST /v1/intelligence/playbooks/{playbook_id}/evaluate` compares submitted graph/signals/context against the playbook trigger schema.
4. **Recommendation generation** — matched playbooks call the Recommendation Family Registry and persist governed recommendations linked to the `playbook_id` and `playbook_run_id`.
5. **Human control** — generated candidate actions are not executed automatically. Existing approval, authorization metadata, and audit controls still apply.
6. **Outcome capture** — decisions, actions, and outcomes are recorded through existing OODA endpoints.
7. **ROI reporting** — performance endpoints aggregate runs, value, capture rate, success rate, stale runs, incomplete runs, and confidence deltas.

## Built-in templates

| Template | Category | Primary signals |
| --- | --- | --- |
| High-LTV Churn Save | `retention` | `churn_probability`, `ltv_predicted_usd`, `trust_score`, `engagement_decline` |
| Expansion Signal Routing | `expansion` | `usage_growth`, `account_health`, `relationship_influence_score`, `ltv_predicted_usd` |
| Fraud Cluster Review | `fraud_review` | `suspicious_cluster_score`, `anomaly_score`, `trust_score`, `shared_wallet_count`, `velocity_score` |
| Campaign Waste Reduction | `attribution_optimization` | `campaign_spend`, `roas`, `attribution_confidence`, `conversion_rate`, `path_conflict_score` |
| Journey Friction Repair | `journey_optimization` | `dropoff_rate`, `friction_score`, `repeated_failure_event`, `conversion_probability` |
| Agent Failure Review | `agent_governance` | `agent_failure_rate`, `tool_error_rate`, `unauthorized_attempts`, `agent_spend_rate`, `approval_escalation_rate` |
| Reward Eligibility Review | `rewards_optimization` | `reward_eligibility_score`, `fraud_risk_score`, `referral_value`, `campaign_alignment`, `economic_expected_value` |
| Operational Loop Repair | `operational_failure` | `stale_loop_count`, `missing_outcome_count`, `failed_action_count`, `integration_error_rate`, `workflow_latency` |

## API examples

### List templates

```http
GET /v1/intelligence/playbooks/templates
```

### Create from template

```http
POST /v1/intelligence/playbooks/from-template
Content-Type: application/json

{
  "template_id": "high_ltv_churn_save",
  "name": "Enterprise churn save",
  "enabled": true
}
```

### Evaluate a playbook

```http
POST /v1/intelligence/playbooks/{playbook_id}/evaluate
Content-Type: application/json

{
  "entity_id": "acct_123",
  "signals": {
    "churn_probability": 0.72,
    "ltv_predicted_usd": 1200,
    "trust_score": 0.8,
    "engagement_decline": 0.35
  }
}
```

Matched evaluations return `matched: true`, trigger match details, generated recommendation IDs, and `evaluated_at`. No-match evaluations return `matched: false` plus `skipped_reason` without mutating recommendations.

### Runs and performance

```http
GET /v1/intelligence/playbooks/{playbook_id}/runs
GET /v1/intelligence/playbooks/{playbook_id}/performance
GET /v1/intelligence/playbooks/performance/summary
```

## Performance metrics and ROI

Playbook performance includes:

- `runs_total` and `runs_completed`
- `recommendations_generated`, `decisions_recorded`, `actions_logged`, `outcomes_observed`
- `success_count`, `failure_count`, `neutral_count`
- `expected_value_total`, `observed_value_total`, and `pending_value_total`
- `outcome_capture_rate` and `success_rate`
- `average_confidence_delta`
- `stale_run_count` and `incomplete_run_count`

`pending_value_total` is the non-negative difference between expected recommendation value and observed outcome value. Outcome capture and success rates use tenant-scoped recommendation/action/outcome relationships and never mix tenant data.

## Governance and tenant isolation

Playbooks require write permission to create or evaluate and read permission to list, inspect runs, or view performance. Evaluation loads the tenant-owned playbook before any generation work and returns not found for cross-tenant access. Generated recommendations retain existing candidate action approval levels, governance flags, graph mutation behavior, event emission, and human-in-the-loop controls.

## Feature flags and rollout

`AETHER_PLAYBOOKS_ENABLED` gates create/evaluate behavior. `AETHER_RECOMMENDATIONS_ENABLED` must also be enabled for generated recommendations to be useful in tenant workflows. Roll out by enabling templates for internal tenants, validating no-match rates and stale run counts, then expanding to production tenants by vertical.
