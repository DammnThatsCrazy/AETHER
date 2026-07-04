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
