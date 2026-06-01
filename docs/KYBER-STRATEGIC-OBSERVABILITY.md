---
title: Kyber Strategic Observability
slug: ai/kyber-strategic-observability
section: ai
visibility: I
audience: [ai, architect, dev-senior, ops, exec]
status: beta
since_version: "8.9.0"
source_files:
  - Backend Architecture/aether-backend/services/admin/kyber_strategic.py
  - Backend Architecture/aether-backend/services/admin/routes.py
  - frontend/kyber/src/components/recommendation-observability-panel.tsx
flags:
  - KYBER_RECOMMENDATION_OBSERVABILITY_ENABLED
related:
  - ai/decision-outcome-intelligence
  - ai/outcome-ledger
  - ai/playbooks
---

# Kyber Strategic Observability

Kyber is Olympus Labs' internal operator console. Aether remains the tenant-facing product for recommendations, decisions, actions, outcomes, investigations, playbooks, and outcome ledgers.

Kyber Strategic Observability aggregates OODA health, tenant value, recommendation family quality, playbook ROI, model/scoring drift, and vertical solution signals. It does **not** expose raw tenant-private graph intelligence, evidence payloads, or event contents across tenants.

## Access model

All `/v1/admin/kyber/*` endpoints require admin/operator permission. Tenant-level account health is allowed for Olympus operators. Cross-tenant views must be aggregate, anonymized, or operational diagnostics.

Allowed:

- Tenant account health and value totals.
- Recommendation family counts and aggregate outcome rates.
- Playbook template adoption and ROI aggregates.
- Confidence distribution and scoring penalty summaries.
- Revenue opportunities derived from aggregate health signals.

Forbidden:

- Raw tenant graph paths across tenants.
- Raw private recommendation evidence from one tenant shown to another tenant.
- Tenant event payloads or profile contents in cross-tenant views.

## Endpoints

```http
GET /v1/admin/kyber/strategic-overview?window=30d
GET /v1/admin/kyber/tenant-value-health?window=30d
GET /v1/admin/kyber/tenant-expansion-opportunities?window=30d
GET /v1/admin/kyber/tenant-churn-risk?window=30d
GET /v1/admin/kyber/recommendation-family-performance?window=30d
GET /v1/admin/kyber/playbook-performance?window=30d
GET /v1/admin/kyber/outcome-capture-health?window=30d
GET /v1/admin/kyber/model-confidence-drift?window=30d
GET /v1/admin/kyber/vertical-solution-signals?window=30d
GET /v1/admin/kyber/revenue-opportunities?window=30d
```

Supported windows are `7d`, `30d`, `90d`, and `lifetime`. Every response includes `generated_at` and `data_freshness`.

## Strategic metrics

The strategic overview summarizes:

- total tenants, OODA-enabled tenants, and active OODA tenants
- recommendations, decisions, actions, and outcomes
- outcome capture rate
- observed, expected, and pending value
- top recommendation family and playbook template
- tenants ready for expansion and tenants at risk
- model confidence health

## Scoring

Tenant health score blends view, decision, action, outcome capture, success rate, stale loops, incomplete loops, and confidence deltas.

Expansion score blends observed value, outcome capture, playbook usage, recommendation family depth, integration usage when available, and positive confidence deltas.

Churn risk score blends low engagement, low outcome capture, stale/incomplete loops, negative confidence deltas, and unused playbooks.

Model drift status uses confidence distribution, confidence deltas, suppression rate, low-confidence rate, freshness penalties, governance penalties, and risk penalties.

## Rollout

Keep `KYBER_RECOMMENDATION_OBSERVABILITY_ENABLED` disabled until admin endpoints have representative OODA data. Roll out first to Olympus operators, validate no raw tenant payloads appear, then use the console for customer success and product strategy rituals.
