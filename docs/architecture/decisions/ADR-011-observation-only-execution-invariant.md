---
title: "ADR-011: Observation-Only Execution Invariant"
slug: decisions/adr-011-observation-only-execution-invariant
section: reference
visibility: I
audience: [architect, dev-senior]
status: stable
since_version: "0.1.0"
source_files:
  - services/api/value/derivatives/adapters/base.py
  - services/api/actions/agentic_observability/foundation.py
canonical_owner: platform@aether
source_hashes:
  "services/api/actions/agentic_observability/foundation.py": "sha256:4bba69eec57048849dfb87ed9e33e7a5e76db633afcb18fd303a9bf04066597a"
  "services/api/value/derivatives/adapters/base.py": "sha256:46b4fe9cf745c563365da72d207ee3fd08f000df816678acf7db19835519370f"
---

# ADR-011: Observation-Only Execution Invariant

**Status**: Accepted (8.12.0); applies platform-wide to economic domains

## Context

Stablecoin, derivatives, and interoperability intelligence observe
external financial systems. The single most damaging failure mode would
be Aether acting on those systems — placing orders, relaying messages,
moving funds — whether by code, misconfiguration, or prompt-injected
agent behavior.

## Decision

`execution_by_aether = false` is enforced in depth, not policy:

1. **Database**: `CHECK (execution_by_aether = FALSE)` on every table
   that could describe an action.
2. **Models**: `execution_by_aether: Literal[False] = False` — a payload
   claiming execution fails validation.
3. **Routes**: write endpoints run `check_no_execution` before
   persisting.
4. **Adapters**: constructors assert read-only credential authority;
   the conformance suite fails any adapter emitting execution claims.
5. **Intelligence**: Noesis is read-only by construction; OODA produces
   suggestions whose execution gate is a separate, still-OFF flag, and
   no economic suggestion class is executable.

## Consequences

- Adding any execution capability requires touching all five layers —
  impossible to do accidentally.
- Recovery/remediation always routes to a human operator with an
  audited action trail (Kyber ops surfaces).
