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

The Support 360 product contract is source-aligned with the Aether 360 backend
single source of truth. The product surface is one of 18 catalogued surfaces;
`support360` is also a technical projection because its bounded canonical
reads have a dedicated provider. Provider and slot coverage remains partial.

## Authority boundary

Support 360 is a read-only projection. It does not own support cases,
communications, identity, journeys, risk, or outcomes. For entity subjects,
the provider reads tenant-scoped `silver_comms_facts` records classified as
support and accepts only an exact `recipient_entity_id` match. For canonical
support-case subjects, it joins communication facts through the exact tenant,
provider connection, and source case ID from the canonical case record, then
rechecks each returned fact.

The provider emits structural interaction metadata, event timestamps, and
evidence references. It suppresses message bodies and unresolved participant
IDs. The case path joins persisted lifecycle events and reports communication
history as current-store coverage only; complete source history and freshness
remain unknown. Case resolution describes observed lifecycle state and does not
establish a separately attributed business outcome.

Case-scoped callback, assignment and handoff, SLA, and journey context events
are retained by their own append-only support authorities. The projection
rechecks exact tenant, case, provider connection, event, and canonical identity
links where applicable. A source-reported SLA timer is not a measured breach;
a journey link does not by itself prove an episode relationship. When an
EpisodeRecord explicitly cites the verified case journey-link event and names
the same journey, the provider can report that exact relation as partial
evidence. These reads do not establish upstream event authorship, complete
source history, or historical state.

## Runtime contract

- The mounted `/v1/experience360/frames` route evaluates frame and slot policy
  before provider reads and composes the returned projection through the shared
  360 frame runtime.
- The technical projection registry keeps Support 360 `in_flight` until its
  required joins and provider behavior are complete.
- The product surface binds case lifecycle reads to `case_summary`,
  `resolution`, and `evidence_trace`. Exact case-linked communication metadata
  supports `conversation_history` for canonical `support_case` subjects, after
  that slot passes policy. Entity communication reads retain their separate
  exact recipient binding under `support_communications`.
- The `risk` slot routes to Risk360 only after frame policy allows the slot.
  Risk360 first proves the exact tenant-owned support case, then joins only
  case-keyed assessments and signals with risk and case evidence. This path does
  not establish complete risk history, signal coverage, a freshness SLA,
  business outcome, or contagion authority.
- `callbacks`, `agents`, `participants`, `sla`, and `journey_links` expose only
  the exact records admitted by their respective tenant and case joins.
  `sla` still lacks canonical measurement-contract evaluation. The optional
  episode relation requires the episode to cite the exact case journey-link
  event; shared journey ID alone is insufficient.
- Results must retain tenant scope, source timestamps, section state, evidence
  provenance, and explicit provider limitations. Policy suppression must not
  be inferred as absence.

## Explicit gaps

- Callback and assignment source authorship, complete history, historical
  replay, and freshness are not established. SLA timer observations lack a
  canonical measurement contract and breach evaluation. Episode relations
  require a producer to persist exact case event evidence; population coverage
  remains unknown.
- Participant identity is limited to exact current provider account bindings;
  historical membership and message-content policy remain unproven. Message
  bodies remain suppressed.
- Communication source-history completeness, a support-specific freshness
  service level, and historical replay are unavailable.
- No authoritative support business outcome attribution is connected.
- Risk history, support-case freshness, risk outcome attribution, and
  case-specific contagion remain unknown. Value context depends on its own
  provider and policy; this provider does not derive it.

Until these gaps close, affected slots stay unknown or degraded and the
projection must not be described as a complete Support 360 implementation.
