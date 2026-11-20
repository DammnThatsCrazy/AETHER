---
title: Agentic Commerce — Approval Model (Retired)
slug: ai/approval-model
section: architecture
visibility: P
audience: [architect, dev-senior]
status: deprecated
since_version: 0.1.0
source_files:
  - services/api/value/x402/commerce_models.py
  - services/api/value/x402/commerce_store.py
  - services/api/intelligence/workflow/workflow360_provider.py
  - services/api/actions/agent/user_agents.py
canonical_owner: commerce@aether
estimated_read_minutes: 2
toc_depth: 3
source_hashes:
  "services/api/actions/agent/user_agents.py": "sha256:6e8c6935786206280889003297253f1401cd67573ff490a78349840555b1af20"
  "services/api/intelligence/workflow/workflow360_provider.py": "sha256:3d8bf744af89fc6d06816848c5ab3d43d5bdd6b469b3b8fd3fc505bb5c5e6848"
  "services/api/value/x402/commerce_models.py": "sha256:50dbf80d7699ccdfcd5206d94a2dadc33ae73c1c06caac80da23e953320e282a"
  "services/api/value/x402/commerce_store.py": "sha256:c55caae3f9e9f81830f493b729c8bc5ef8ba1f4f6244628c7059580e429f216e"
---

# Agentic Commerce — Approval Model (Retired)

**Status:** retired by [ADR-012](decisions/ADR-012-observation-only-everywhere.md).

Aether used to require an operator approval before any x402 spend, and could
bind an approval to an agent execution it then admitted through
`POST /v1/agents/{agent_id}/execute`. Aether is now observation-only: it does
not approve spend, admit agent actions or gate payments. The approval workflow,
its routes (`/v1/approvals`), the Kyber approval queue and the execute route
were removed.

## What remains

- **Historical decisions.** Approval requests and their immutable decisions
  written before retirement stay in the commerce store. Workflow 360 still
  shows them with the recorded permission check, and commerce erasure removes
  a subject's decisions without touching other tenants.
- **Observed authority.** Where a source system records that a human approved
  an agent's action, Aether records that grant and judges the observed action
  against it after the fact (inside, outside or unknown). It never decides.
- **Declarations.** `POST /v1/agents` still records a tenant's declaration of
  its own agent; historical execution rows stay readable.
