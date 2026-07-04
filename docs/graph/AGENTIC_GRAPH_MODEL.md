---
title: Agentic Delegated Authority Graph Model
slug: graph/agentic-graph-model
section: architecture
visibility: I
audience: [dev-senior, architect, ai]
status: experimental
since_version: "8.11.0"
source_files:
  - Backend Architecture/aether-backend/services/agentic_observability/provider_framework.py
---

# Agentic Delegated Authority Graph Model

Agentic provider projections use provider-neutral vertices and edges. X content,
for example, is represented as `ProviderAction` or `ExternalObject` with provider
metadata, not as an `XPost` vertex.

## Initial provider-neutral vertices

- `ExternalAccount`
- `AuthorizationGrant`
- `ProviderAction`
- `ProviderVerification`

All projection records include canonical `tenantId`. Authorization-to-account
edges include temporal fields such as `valid_from`, `valid_to`, and `is_current`.
The helper builds projection records only; graph writes remain owned by the
outbox/projection worker.
