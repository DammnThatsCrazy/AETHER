---
title: Agentic Product Surfaces
slug: architecture/agentic-product-surfaces
section: architecture
visibility: I
audience: [dev-senior, architect, ai, ops]
status: experimental
since_version: "8.11.0"
source_files:
  - Backend Architecture/aether-backend/services/agentic_observability/product_surfaces.py
  - Backend Architecture/aether-backend/services/agentic_observability/routes.py
  - Backend Architecture/aether-backend/services/noesis/adapters/agentic_intelligence_adapter.py
---

# Agentic Product Surfaces

Aether now exposes read-only Agentic Intelligence product-surface adapters that assemble already-ingested observations into tenant-scoped read models. These adapters do not execute provider actions, revoke grants, mutate external systems, or infer causality beyond the stored evidence.

## Source of truth

The source-of-truth inputs are:

- `obs_agent_activities`, `obs_agent_connections`, `obs_agent_tools`, `obs_external_accounts`, and `obs_agent_risk_signals` compatibility observation stores.
- Typed Silver fact tables such as `silver_agent_activity_facts`, `silver_mcp_connection_facts`, `silver_agent_tool_invocation_facts`, and `silver_agent_risk_facts`.
- `canonical_activity` rows where `source_system = 'agentic_observability'`.

## Read models

The service `AgenticProductSurfacesService` provides three internal-preview read models:

1. **Agent Profile 360 evidence** — combines observed activity, MCP connections, tools, external accounts/grants, risk signals, and canonical activity for one agent.
2. **Journey v2 agentic steps** — returns Journey v2-compatible steps from tenant-scoped agentic canonical activity.
3. **Campaign agentic influence** — returns observed agentic campaign touchpoints and marks them `eligible_for_modeling` only when evidence exists. This does not claim attribution or causality.

## Kyber endpoints

Kyber operators can inspect these read models through:

- `GET /v1/admin/kyber/agentic-observability/agents/{agent_id}/profile360`
- `GET /v1/admin/kyber/agentic-observability/journey-v2?agent_id={agent_id}`
- `GET /v1/admin/kyber/agentic-observability/campaigns/{campaign_id}/influence`

All endpoints use the authenticated tenant context and only read repository-backed evidence.

## Noesis intents

Noesis can answer read-only questions with evidence classifications for:

- `agent_profile360_lookup`
- `journey_agentic_steps_lookup`
- `campaign_agentic_influence_lookup`

Claims are labeled as observed facts or deterministic computations. Unsupported causal claims remain out of scope until the release-level attribution and evidence-precedence tests are complete.

## Release status

This closes part of the product-surface gap but does not make Agentic Intelligence GA-ready. Human and Organization Profile 360, Cluster360, full campaign attribution execution, outcomes, exports, and the release-level end-to-end scenario remain required for GA.
