---
title: Identity Resolution Architecture
slug: identity-resolution
section: architecture
visibility: I
audience: [dev-senior, architect]
status: experimental
since_version: "0.1.0"
---

# Identity Resolution Architecture

## Overview

Identity resolution is the process by which Aether merges fragmented
observations from SDKs, providers, and connectors into a single canonical
entity within the tenant-scoped intelligence graph.

## Resolution Pipeline

```
raw observations → Bronze normalization → identity keys extraction
→ deterministic match → probabilistic candidate scoring
→ merge decision → graph entity upsert → outbox event
```

## Key Concepts

- **Identity keys**: deterministic identifiers (email, phone, external ID)
  extracted during Bronze normalization.
- **Merge rules**: tenant-configurable policies that control when two
  candidate entities should be merged vs. kept separate.
- **Split recovery**: mechanism to undo an incorrect merge when new
  evidence arrives.
- **Source namespace**: the scope in which source identifiers are unique.
  Registry idempotency is tenant- and namespace-scoped; equal raw IDs from a
  CSV upload, connector, or SDK remain separate evidence until the resolver
  evaluates their claims.

## Import-First, SDK-Later Continuity

Historical imports and later SDK observations enter the same identity
resolution service through distinct source identities. Repeated observations
of one identifier within the same source namespace are idempotent. A matching
identifier from another namespace creates a separate source identity, while
shared claims (for example, an email) may still provide evidence for the
backend resolver to link or merge compatible identities. The SDK does not
assign a canonical entity.

## Invariants

- Identity resolution never creates observations — it links them.
- A merge is always reversible through split recovery.
- Resolution runs after normalization, never before.
- Probabilistic scoring is advisory; merge decisions are deterministic
  given the same input set.

## Current State

Identity resolution is implemented in the backend resolution service.
See `services/backend/services/identity/` for the
runtime implementation.
