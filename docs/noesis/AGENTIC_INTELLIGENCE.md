---
title: Noesis Agentic Intelligence
slug: noesis/agentic-intelligence
section: architecture
visibility: I
audience: [dev-senior, architect, ai]
status: experimental
since_version: "8.11.0"
source_files:
  - Backend Architecture/aether-backend/services/noesis/adapters/agentic_intelligence_adapter.py
  - Backend Architecture/aether-backend/services/noesis/service.py
---

# Noesis Agentic Intelligence

Noesis now has deterministic, read-only Agentic Intelligence intents for
answering questions about agent inventory, agent activity, MCP topology,
authorization/account access, provider verification, verification mismatches,
permission risk, and evidence paths.

## Evidence classifications

Agentic answers include one of the following classifications on rows or claim
metadata:

```text
observed_fact
provider_confirmed_fact
deterministic_computation
probabilistic_inference
recommendation
insufficient_evidence
```

These classifications are mapped into the existing Noesis evidence envelope so
older clients continue to receive `fact`, `computation`, `inference`, and
`recommendation` claim types while newer agentic surfaces can display the more
specific label.

## Safety boundary

The adapter only reads observation repositories. It does not execute provider
actions, mutate grants, revoke access, write graph state, or retrieve raw
credentials. Permission-risk answers are recommendations for human review.

## Product-surface intents

Noesis also supports read-only product-surface questions backed by `AgenticProductSurfacesService`:

- `agent_profile360_lookup` builds Agent Profile 360 evidence for an agent target from observed activity, MCP, tool, account/grant, risk, Silver, and canonical activity rows.
- `journey_agentic_steps_lookup` returns Journey v2-compatible agentic steps from tenant-scoped canonical activity.
- `campaign_agentic_influence_lookup` summarizes observed agentic campaign touchpoints and reports whether evidence is eligible for attribution modeling.

These intents label claims as observed facts or deterministic computations. They must not claim causality, perform provider actions, mutate grants, or write graph state.
