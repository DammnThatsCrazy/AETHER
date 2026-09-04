---
title: Kyber Revenue Intelligence
slug: ai/kyber-revenue-intelligence
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
  - ai/kyber-strategic-observability
  - ai/playbooks
  - ai/recommendation-families
last_synced_commit: "4e6fdad"
---

# Kyber Revenue Intelligence

Kyber Revenue Intelligence turns aggregate OODA value signals into internal Olympus Labs expansion, packaging, customer success, and vertical solution recommendations.

It is internal-only and never exposes raw tenant-private graph intelligence across tenants.

## Opportunity logic

Revenue opportunities are generated from:

- tenants with measurable observed value and healthy outcome capture
- tenants with stale or incomplete loops that need services intervention
- recommendation families with strong adoption and success rates
- playbook templates with recurring runs and ROI
- vertical solution signals across fraud, agent governance, growth, and operational reliability

Opportunity types include:

- `usage_expansion`
- `module_expansion`
- `integration_expansion`
- `services_expansion`
- `enterprise_expansion`
- `government_solution`

Each opportunity includes a reason, supporting aggregate metrics, estimated value, confidence, and recommended Olympus action.

## Internal recommendation examples

- Tenant is ready for Decision Intelligence Pro upsell when expansion score is strong and value capture is visible.
- Tenant has stale loops and low outcome capture, so Kyber recommends an implementation review.
- Fraud-review usage and avoided-loss value suggest a Fraud & Risk module packaging opportunity.
- Agent Governance adoption across tenants suggests an enterprise module or government package.

## API example

```http
GET /v1/admin/kyber/revenue-opportunities?window=90d
```

The response returns an internal opportunity feed. Tenant-level account health is allowed for Olympus operators; cross-tenant opportunity rows use aggregate product signals and operational diagnostics rather than raw tenant evidence.

## Agentic operator endpoints

Kyber operators can inspect per-tenant agentic activity and economic health via:

| Endpoint | Description |
|---|---|
| `GET /operator/agentic/overview` | Cross-tenant aggregate: active agents, active delegations, total spend, subagent count, abandoned payment count, top protocols/providers/capabilities, recent failures |
| `GET /operator/agentic/agents/{agent_id}` | Single agent detail: config, behavior profile, intent and settlement counts, recent executions |
| `GET /operator/agentic/authorization-violations` | Delegations that exceeded their granted scope (revoked entries as proxy signal) |
| `GET /operator/agentic/spend-limits` | Agents where total spend exceeds 3× the per-tenant average — potential budget overruns |
| `GET /operator/agentic/trust` | Agent behavior profiles ranked by risk_score for trust triage |
| `GET /operator/agentic/x402/flows` | Recent x402 payment lifecycle flows across tenants |
| `GET /operator/agentic/x402/failures` | Recent payment failures for remediation |
| `GET /operator/agentic/x402/timeouts` | Payment timeout events |
| `GET /operator/agentic/settlements` | Recent settlement events |
| `GET /operator/agentic/delegations` | Active delegation grants |
| `GET /operator/agentic/subagents` | Registered subagent relationships |
| `GET /operator/agentic/anomalies` | Behavioral anomaly signals |

All endpoints require Kyber operator authentication and are cross-tenant read-only.

## Identity health operator endpoints

Kyber operators can audit identity resolution quality across all tenants:

| Endpoint | Description |
|---|---|
| `GET /v1/admin/kyber/identity-health` | Per-tenant identity quality metrics (total entities, aliases, conflict rate) |
| `GET /v1/admin/kyber/resolution-queue` | Paginated global conflict queue across all tenants |
| `GET /v1/admin/kyber/merge-split-audit` | Cross-tenant merge/split ledger (date-range filtered) |
| `GET /v1/admin/kyber/resolution-health` | Per-tenant resolver throughput, error rate, queue depth |

All four require `kyber:identity:read` permission. Results are read-only — no identity writes go through Kyber endpoints.

## Governance

Kyber revenue recommendations do not execute tenant actions. They are internal operator guidance for account planning, product packaging, and solution strategy. Tenant-facing decisions, approvals, actions, and outcomes still flow through governed Aether OODA APIs.
