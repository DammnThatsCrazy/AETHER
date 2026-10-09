---
title: Aether Root Architecture
slug: architecture/aether-root-architecture
section: architecture
visibility: I
audience: [architect, dev-senior, ops, security]
status: experimental
since_version: 0.1.0
---

# Aether Root Architecture

This document defines the **target** of the architecture reset. It is not a claim
that every layer is implemented or ready for a design partner. The migration
ledger in `docs/blueprints/architecture-reset/README.md` records what is present,
what must change, and the evidence required before an old path can retire.

## Purpose and one proof path

Aether is a tenant-scoped intelligence graph runtime. It captures activity from
SDKs, connectors, webhooks, imports, and partner systems; retains replayable
evidence; normalizes facts; resolves entities; builds governed graph state;
and serves intelligence with traceable explanations and controlled actions.
Kyber is the internal operator control plane for diagnosis, review, recovery,
and release operations. It does not become a second source of graph or identity
truth.

```text
tenant and access
  -> source and intake
  -> evidence and event log
  -> normalization and source classification
  -> identity and entity resolution
  -> governed graph mutation and projection
  -> journeys, touchpoints, value, and intelligence
  -> product view and explanation
  -> governed action
  -> measured outcome
  -> correction, replay, and evaluation
```

The minimum product proof is: provision a tenant, connect a source, capture an
event, normalize it, resolve its entity, populate the graph, render a profile
and journey, apply a lens, show the supporting evidence, surface a permitted
action, and record its outcome. Each stage needs visible success, failure, and
recovery states. A local fixture proves integration only; design-partner and
production claims require their separate live evidence and canonical gates.

## Authority boundaries

| Domain | Target authority | Existing implementation to preserve during migration |
| --- | --- | --- |
| Tenant, access, consent, and rights | Backend tenant and policy authorities decide admission before data use or action. | Existing backend auth, tenant, consent, rights, and billing services. |
| Source-native records | The source system remains authoritative for its own orders, payments, messages, and similar records. | SDKs emit observations; connectors own provider auth, sync, webhooks, and cursors. |
| Canonical contracts | One versioned contract vocabulary, with adapters for older clients and source-specific schemas. | `packages/shared/contracts/` and its generators and validators. |
| Evidence and normalization | Tenant-scoped raw evidence and a replay identity precede normalized facts; source trust and lineage stay attached. | `services/backend/services/ingestion/`, the observation envelope registry, and durable lake/outbox paths. |
| Identity | The backend resolver owns canonical entity decisions, review, correction, and restatement. | `services/backend/services/identity/`; source identity is scoped by tenant and `source_namespace`. |
| Graph | All canonical state transitions are authorized, idempotent mutation intents with ledger evidence. | `services/backend/shared/graph/mutation_gateway.py` and graph projection owners. |
| Intelligence | Versioned lenses, journeys, attribution, value, and recommendations read governed facts and carry evidence. | Existing backend computation and intelligence services; projection registries. |
| Customer presentation | Aether composes read-only governed views and requests permitted actions. | Existing Aether frontend and mobile clients. |
| Operator control | Kyber inspects health, authorizes repairs, and records audit trails through backend authorities. | Existing Kyber frontend, operator routes, jobs, and runbooks. |

The table identifies a migration direction, not proof that every listed
implementation already satisfies the target. We extend the existing authorities
before moving directories. A path move must keep import, API, schema, data,
deployment, and docs compatibility until its consumers are migrated.
The existing spine and projection registries remain domain-level governance;
"one runtime spine" describes the end-to-end product flow, not a replacement
registry or permission to flatten distinct domain semantics.

## Truth, time, and lifecycle

Every output must distinguish the kind of truth it represents:

| Level | Meaning |
| --- | --- |
| L0 | Raw evidence |
| L1 | Normalized fact |
| L2 | Resolved entity |
| L3 | Inferred relationship |
| L4 | Computed journey or value |
| L5 | Lens interpretation |
| L6 | Recommendation |
| L7 | Action or outcome |
| L8 | User-confirmed truth |

These are target semantics, not a claim that an L0-L8 field exists today.
Results must expose whether they are known, unknown, inferred, conflicting,
system-confirmed, user-confirmed, or waiting for review. Provenance includes
tenant, source namespace, source record identity, contract and algorithm
versions, event and ingestion times, policy decisions, and causal evidence.
Unknown, missing, empty, and numeric zero stay distinct. Late or corrected
events may revise derived state while retaining the previous decision and its
reason. Object lifecycles for sources, profiles, journeys, agents, and lens
results must be explicit, with transitions controlled by the owning service.

The target lifecycle vocabulary is:

| Object | Target states |
| --- | --- |
| Source | created, configured, auth_pending, connected, syncing, healthy, degraded, failed, revoked, disconnected, archived |
| Profile | candidate, active, merged, split, review_needed, suppressed, deleted, archived |
| Journey | forming, active, converted, abandoned, recomputed, closed, archived |
| Agent | declared, created, active, delegated, acting, paused, revoked, expired, terminated, archived |
| Lens result | queued, running, completed, stale, recomputed, suppressed, archived |

These values require owner review and compatibility mapping against existing
runtime states before they become contract enums. They are not a migration by
declaration. Event time, source time, ingestion time, processing time, and
recomputation time remain distinguishable, including late arrivals and
historical reads.

## Control plane under every stage

| Control | Required behavior |
| --- | --- |
| Failure and degradation | Bounded retry, quarantine/dead-letter handling, partial-state visibility, and tenant-safe empty/error states. |
| Replay and backfill | Tenant-scoped, authorized, idempotent jobs from retained evidence; versioned recomputation, diff, and restatement records. |
| Schema governance | Versioned contracts, compatibility adapters, migration policy, and SDK/provider compatibility windows. |
| Isolation and authority | Tenant scope on events, storage, graph, cache, jobs, flags, billing, and reads; RBAC, consent, rights, and action approvals. |
| Data lifecycle | Retention, deletion, export, source disconnect, tenant offboarding, and invalidation of derived state. |
| Trust and security | Source trust classification, poisoning defense, audit logs, threat model, and fail-closed action eligibility. |
| Quality and cost | Golden datasets, false-merge checks, lens/attribution evaluation, per-tenant usage and replay/query cost. |
| Operations | Health, failed-event, identity-review, graph, billing/access, and deployment diagnostics with runbooks and rollback. |

No unscoped production event, graph mutation, lens result, replay, or action is
valid. Weak evidence alone cannot silently merge people. An unexplained result
cannot be promoted into an automated action. Feature flags and entitlements
never override access or data-rights checks.

## Product and operator surfaces

The Aether customer navigation target is **Snapshot, Graph, Profiles, Journeys,
Signals, Lenses, Value, Connectors, and Settings**. Specialized 360 pages are
compositions of shared `EntityHeader`, `SummaryCards`, `EvidenceTimeline`,
`RelationshipGraph`, `JourneyPanel`, `CommunicationPanel`, `ValuePanel`,
`LensPanel`, `ConfidencePanel`, `ExplanationDrawer`, and `ActionPanel` primitives.
The backend keeps its precise contracts even when the customer vocabulary is
simpler. Legacy routes and names require aliases and usage evidence before
removal.

Kyber owns operator workflows: tenant activation, source/SDK/connector health,
failed-event inspection, identity review, graph diagnostics, authorized
replay/backfill, contract diagnostics, feature availability, billing/access,
cost, incidents, and release readiness. An operator UI is an interface to
backend authorities, not an alternate registry or write path.

## Repository shape and migration rule

The desired root is readable as `apps/`, `packages/`, `services/`, `infra/`,
`tests/`, and `docs/`, with configuration and tooling in `config/` and
`scripts/`. Logical packages are contracts, UI, SDKs, intake, normalization,
identity, graph, lenses, explanations, actions, readiness, and shared
utilities. Runtime services are API, workers, webhooks, connectors, replay,
and billing. Deployment environments are local, preview, staging, pilot
production, and production; capabilities are overlays, not new environments.

This layout is a destination, not an instruction to copy code into parallel
packages or deploy more microservices. Today `services/backend/` is the
deployed Python authority, `packages/shared/contracts/` is the contract source,
`frontend/aether/` is the customer web app, `frontend/kyber/` is the operator
web app, and `deploy/aws/` contains the active AWS implementation. A physical
move occurs only after the target owner, import/API adapters, deployment paths,
generated artifacts, docs ownership, and rollback have been verified together.
Historical trees remain explicitly archived and cannot become new authorities.

## Feature and evidence states

Every capability records both product disposition and evidence maturity.
Disposition is `core`, `beta`, `experimental`, `internal`, `deprecated`,
`archived`, or `removed`. Maturity is L0 concept, L1 scaffold, L2 local
prototype, L3 integrated, L4 fixture-proven, L5 staging-proven, L6 design-partner
ready, or L7 production hardened. A label is supported by evidence rather
than inferred from code presence.

Readiness is four distinct decisions: **feature readiness** records that
evidence ladder; **tenant readiness** checks tenant, users, entitlement,
billing/pilot, source, ingestion, graph, views, and value for that tenant;
**runtime readiness** reports ingestion, identity, graph, connector, SDK,
API, and UI health; **release readiness** joins PR authority, staging and
smoke evidence, risks, rollback, and operator runbooks. One green dimension
cannot substitute for another.

The target core includes tenant/access, SDK and connector intake, evidence,
normalization, identity, graph, profile/journey/lens views, explanations,
basic value, tenant readiness, pilot billing/access, and staged deployment.
Advanced Campaign/Communications/Value views and recommendations begin as
beta candidates. Advanced Agent 360, X402, Gnosis/plugins, Harness automation,
sovereign/multicloud assumptions, and advanced agent-commerce or financial
rail observations are experimental candidates. Actual status and removal
decisions follow the evidence-backed disposition inventory; safety controls
remain required even when a feature is hidden.

## Verification and release authority

During migration, agents run focused tests, static checks, and targeted docs
validation for their owned slice. The current normal PR authority remains
`verification / disposition` in `.github/workflows/repo-consistency.yml`,
started at `ready_for_review` after integration. Staging validates the real
tenant proof path and operational recovery. Nightly and release checks cover
deep connector/SDK matrices, replay, performance, security, mobile/Kyber, and
experimental modules. Moving checks between tiers requires impact and failure
evidence; it never silently drops contract, tenant, auth, consent, audit, or
deployment protection. `make ci-check` and `make release-gate` serve their
existing broad and release roles.

The reset is complete only after the repo has one owner for each core domain,
canonical intake and graph mutation paths, safe compatibility for existing
clients and data, a partner tenant that can traverse the proof path with
diagnosable failures and recovery, a comprehensible root layout, reviewed docs,
and explicit hosted/staging/release evidence. A green focused test alone does
not establish merge or production readiness.
