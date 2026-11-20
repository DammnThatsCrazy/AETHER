---
title: "ADR-012: Observation-Only Everywhere"
slug: decisions/adr-012-observation-only-everywhere
section: reference
visibility: I
audience: [architect, dev-senior]
status: stable
since_version: "0.1.0"
source_files:
  - services/api/actions/agent/user_agents.py
  - services/api/actions/agent/invocation_receipts.py
  - services/api/value/x402/settlement_observer.py
  - services/api/value/x402/provenance.py
  - services/api/journeys/comms/suppression_authority.py
canonical_owner: platform@aether
source_hashes:
  "services/api/actions/agent/invocation_receipts.py": "sha256:03396ce4fa7f262f12cc8acaa36805c8bd644e961e6e3423a45383327e991de2"
  "services/api/actions/agent/user_agents.py": "sha256:6e8c6935786206280889003297253f1401cd67573ff490a78349840555b1af20"
  "services/api/journeys/comms/suppression_authority.py": "sha256:bed3da364d61525d840253f935c6584443771143ab8516f37e1bd70ea4ba34dc"
  "services/api/value/x402/provenance.py": "sha256:fe227df986d4c03f770d97d6236bc4c5c5ee4410db66415dd38b7a697779d556"
  "services/api/value/x402/settlement_observer.py": "sha256:d7779f89245892329488cfc587ae4afa4988b012494e4b5acce736acec45874e"
---

# ADR-012: Observation-Only Everywhere

**Status**: Accepted. Extends [ADR-011](ADR-011-observation-only-execution-invariant.md)
from economic domains to every domain.

## Context

ADR-011 made Aether observation-only for stablecoin, derivatives and
interoperability systems. Elsewhere Aether still acted: it admitted or refused
a tenant agent's action before it ran (`POST /v1/agents/{id}/execute`), called
MCP tools and read MCP resources on an agent's behalf, ran an x402 paywall
(402 challenges, mandatory spend approvals, entitlements and settlement state),
and carried a flag to write suppressions back into a tenant's email provider.

Agents now hold their own inboxes, phone numbers, accounts and budgets, issued
by other platforms. Aether's job is to see and explain what humans, agents and
organizations do across those platforms, with evidence. Acting on their behalf
would make Aether a participant in the activity it is meant to observe, and a
target for prompt-injected or compromised agents.

## Decision

Aether observes. It never acts in the world on behalf of a tenant, a human or
an agent. In particular Aether never:

1. sends a message as, or for, a tenant or agent to a third party;
2. invokes a tool, reads a resource, or calls an API for an agent;
3. admits, refuses or gates an agent's action before it happens;
4. issues payment challenges, approves spend, grants entitlements or owns
   settlement state;
5. writes state back into a source system (for example a provider's
   suppression list);
6. executes a financial action (ADR-011 remains in force).

Aether may:

- read source systems with read-only access and the tenant's rights grant;
- record authority granted elsewhere (an inbox's permissions, a card's spend
  limit, an OAuth scope, a tenant's declared grant) and judge each observed
  action as inside, outside or unknown relative to it, after the fact;
- verify what a source reports (for example an x402 payment on-chain);
- notify its own customers about its own findings (the Delivery service:
  push, email, and messages or tickets in the tenant's own tools). This is
  Aether talking to its users, not acting for them;
- let operators repair Aether's own state through governed Kyber paths.

## What changed

| Former acting path | Now |
|---|---|
| `POST /v1/agents/{id}/execute` admission gate and `.../status` callback | Removed. `/v1/agents` keeps declaration and history routes; observed runs arrive through `POST /v1/batch`. |
| MCP tool invocation and resource reads (`actions/agent/invocation_runtime.py`) | Removed. `invocation_receipts.py` keeps historical receipts readable. |
| Backend agent lifecycle consumer and mapper | Removed. The Silver `AgentExecutionProjector` alone owns observed agent run state. |
| x402 commerce control plane (challenge middleware, approvals, entitlements, policies, pricing, protected resources, signer authority, settlement tracker, reconciliation, commerce metering and workers; Kyber approval queue) | Removed. `POST /v1/x402/capture` records a reported exchange and `value/x402/settlement_observer.py` verifies the payment on-chain; only that observer is an authoritative x402 producer. Historical commerce records stay readable and erasable. |
| `AETHER_COMMS_SUPPRESSION_WRITE_BACK` | Removed. Suppressions are recorded, never written back. |

## Consequences

- Adding any acting capability needs a new ADR that supersedes this one.
- Agent attribution on observed payments stays as reported until an identity
  binding resolves it.
- An x402 payment that is not final yet is `pending`; reporting it again
  re-checks the chain. There is no background re-check loop.
- Tables written by the retired paths are kept for history and erasure; no
  migration drops them.
