---
title: Support 360 Backend Blueprint
slug: blueprints/support360
section: architecture
visibility: I
audience: [architect, dev-senior]
status: stable
since_version: 0.1.0
canonical_owner: platform@aether
estimated_read_minutes: 5
toc_depth: 3
---

# Support 360 Backend Blueprint

## Contract status

This is a repository-reconstructed implementation contract for the Support 360
product surface. Alignment with the original 3,013-line Aether 360 backend
single source of truth remains pending. The product surface is one of 18
catalogued surfaces; `support360` is also a technical projection because its
bounded canonical read has a dedicated provider.

## Authority boundary

Support 360 is a read-only projection. It does not own support cases,
communications, identity, journeys, risk, or outcomes. The provider currently
reads tenant-scoped `silver_comms_facts` records classified as support. It
accepts only an exact `recipient_entity_id` match to an entity subject, and
rechecks tenant and category before returning a fact.

The provider emits structural interaction metadata, event timestamps, and
evidence references. It never returns communication payloads. A source-reported
`support_case_id` remains an opaque reference tied to its source evidence; it
does not establish a canonical case or case lifecycle.

## Runtime contract

- The mounted `/v1/experience360/frames` route evaluates frame and slot policy
  before provider reads and composes the returned projection through the shared
  360 frame runtime.
- The technical projection registry keeps Support 360 `in_flight` until its
  required joins and provider behavior are complete.
- The product surface binds the Support360 provider to
  `support_communications` for entity subjects. Other subject kinds use only
  their separately declared provider bindings.
- Results must retain tenant scope, source timestamps, section state, evidence
  provenance, and explicit provider limitations. Policy suppression must not
  be inferred as absence.

## Explicit gaps

- There is no canonical support case authority or lifecycle provider.
- There is no exact sender, profile, agent, episode, or source join for support
  messages in this provider.
- Support-to-journey linkage has no canonical join.
- A support-specific freshness service level and historical replay are not
  available.
- No authoritative support business outcome producer is connected.
- Risk and value context remain dependent on their own providers and policy;
  this provider does not derive either.

Until these gaps close, affected slots stay unknown or degraded and the
projection must not be described as a complete Support 360 implementation.
