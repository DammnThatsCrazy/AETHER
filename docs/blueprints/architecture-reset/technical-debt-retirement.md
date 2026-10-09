---
title: Aether Architecture Reset Technical-Debt Retirement Ledger
slug: blueprints/architecture-reset/technical-debt-retirement
section: blueprints
visibility: I
audience: [architect, dev-senior, ops]
status: experimental
since_version: 0.1.0
---

# Technical-debt retirement ledger

The [runtime](runtime-authority-map.md), [product](product-surface-map.md) and
[delivery](delivery-authority-map.md) maps say what each stage's single authority
should be. This page and its machine-checked registry,
[`config/debt_retirement_ledger.yaml`](../../../config/debt_retirement_ledger.yaml),
say how everything outside that authority disappears. The rule is:

> A cutover is finished when the replaced path is gone, not when the new path works.

`scripts/validate_debt_retirement_ledger.py` enforces the registry. It runs in
`make repo-doctor` and, as the `debt_retirement_ledger` router check, in every
PR-lane plan, because any change can delete a path a row names. It fails when a
row has no string id or repeats one, is missing a required field, drops or malforms the recorded baseline that `--report` compares against, leaves
`authority`, `compatibility`, `rollback` or `retire` blank, names a path that is
empty, absolute, outside the repository or no longer exists, is `deletion-ready`
or `removed` while a consumer remains or without parity and usage evidence, is
`removed` while its duplicate still exists, or keeps a
`converge`/`deprecated` row past its deadline. The deadline is what stops a
compatibility layer from becoming permanent. Re-deciding a row means writing a
new date in a reviewed change.

This page records measurements and decisions as of `Development` `e41a801`
(2026-10-09). It is not a readiness claim: nothing here makes a path
production-ready, and `scripts/production_status.py` stays the readiness
scorecard.

## One authority per class of truth

The rule is one decision-maker per responsibility, not one file or one service.
Providers stay plugins, SDKs stay platform clients, and domain algorithms stay
separate.

| Responsibility | Canonical authority | Ledger row | State |
|---|---|---|---|
| Intake admission | shared ingress contract and policy decision; source-specific auth and trust stay per source | `intake-sdk-batch-v1-v2`, `intake-provider-runtime-vs-legacy-connectors` | converge |
| Evidence and replay identity | one append-only L0 record; `ProviderRawRightsAdmission` for provider raw data | `evidence-single-admission-and-replay` | converge |
| Normalization | registry-routed Silver dispatcher with versioned adapters | `normalization-one-fact-authority` | converge |
| Identity | `services/backend/services/identity` | `identity-single-resolver`, `identity-legacy-resolution-module` | retain, deprecated |
| Graph mutation | `MutationIntent` to `GraphMutationGateway.apply` | `graph-single-mutation-gateway` | converge |
| Journey and value | measurement journey compiler | `intelligence-journey-and-value-composition` | converge |
| Governed action | delivery intent, job and receipt | `action-single-delivery-authority` | converge |
| 360 presentation | shared primitives plus per-entity adapters | `product-shared-360-primitives` | converge |
| Normal PR decision | `verification / disposition` | `delivery-pr-workflows-into-one-plan` | converge |
| Environment shape | `config/deployment_profiles.yaml` | `delivery-profile-registries` | converge |

### Decision: provider raw admission

#733 and #734 each introduced a provider raw-admission gate. #734 judged
persisted Bronze fields (license, terms, commercial use, quarantine) and kept
rejected rows; #733 requires a fresh tenant-scoped rights decision and an active
`tenant_byod_data` grant before any write, verifies the stored evidence, and
fails closed in staging and production when the grant store is not durable.
The maintainer chose #733's gate as the single authority. #734's gate and its
retain-and-`partial` sync result were removed. A denied record is not retained;
retained-denial audit receipts are an open follow-up if wanted. The race between
admission and revocation is closed by a per-grant lock shared between raw-record
writers and revocation (#739), with real-PostgreSQL evidence in the proof ledger.

## Baseline and the net-negative rule

`python scripts/validate_debt_retirement_ledger.py --report` prints current size
against the baseline recorded in the ledger. All counts are from `git ls-files`.

| Measure | Baseline (2026-10-09) |
|---|---|
| Tracked files | 8,429 (services 3,137; frontend 1,713; docs 1,107; tests 770; packages 710; scripts 284; deploy 165; config 93) |
| Python / TypeScript test files | 1,434 / 443 |
| Validator scripts | 72 |
| Workflows / triggered on `ready_for_review` | 27 / 11 |
| Deployment-profile registry lines (six files) | 1,295 |
| Backend service directories | 142 |
| Archived docs | 219 files under `docs/archive` |

The reduction targets in the reset plan are planning ranges, not results. They
become results only when `--report` shows them. R4 (repository consolidation)
and R5 (delivery simplification) are expected to be net-negative: they must
remove more tracked files, workflows or registry lines than they add, and each
cutover PR states what it makes deletable.

## What the first pass found

These are measurements, each tied to a ledger row.

- **Abandoned package.** `packages/skeleton-crew` is a README with no source and
  no `package.json`, and the README contains committed merge-conflict markers.
  Nothing referenced it; it is deleted in the PR that introduced this ledger.
  Row `repository-skeleton-crew-package`.
- **A TypeScript test estate nobody runs.** `vitest.config.fps.ts` is the only
  config that includes 93 TypeScript files under `tests/`, and no workflow,
  Makefile target, package script or suite registers it. Run by hand on
  2026-10-09 it executed 74 files (580 tests) green, 10 files failed to resolve
  `@aether/web`, and 9 were skipped. This is a verification gap before it is
  dead weight. Status: #741 registered them as the PR-lane suite
  `functionality-proof-ts` (84 files / 666 tests green, 9 skipped by
  `describe.skip`); the next step is to map each file's invariant to a proof
  package or Python suite and retire the duplicates. Row
  `verification-unrun-typescript-test-estate`.
- **Two Profile360 implementations in Kyber.** `components/entities/` and
  `components/profile360/` each hold a view, a summary, a drill stack and utils,
  and both export a component named `Profile360DrillStack` with different props
  and state models. Status: the `entities` copy (`Entity360View` and the files
  only it used) was exported but never rendered and is deleted, leaving
  `components/profile360/` as the only implementation; the per-entity 360 views
  remain. Row `product-shared-360-primitives`.
- **Unmounted frontend code.** Import-graph reachability from the app entry points
  found 139 Kyber source files (5,433 lines: feature hooks, commerce, approvals,
  entitlements and economics components, unused barrels) that nothing reaches.
  They are deleted; the backend endpoints they would have called are unchanged.
  Eight more are kept for a product decision (three unrouted pages, an unrendered
  agent profile, and four modules alive only through their own tests), listed in
  `config/frontend_reachability.yaml` against ledger row
  `product-kyber-unmounted-code-pending`. `scripts/validate_frontend_reachability.py`
  now fails any PR that adds an unreachable Kyber file, and fails an allowlist
  entry that is stale, so the list can only shrink. The Aether app had 58
  unreachable files: 50 are deleted (1,704 lines) and eight are kept because the
  identity-continuity-gates workflow and component tests depend on three barrels
  and the identity panels they export; it is under the same check. Rows `product-kyber-unmounted-code`, `product-kyber-unmounted-code-pending`,
  `product-aether-unmounted-code` and `product-aether-unmounted-code-pending`.
- **A legacy resolution module.** `services/backend/services/resolution` held an
  engine, consumer, rules, signals and repository that nothing registered and
  whose graph entry points already failed closed. Those seven files (1,353
  lines) and the pending, audit, reject and config routes they backed are
  deleted; three fail-closed tombstone routes remain until the Aether
  user-profile page stops requesting the cluster read. Rows
  `identity-legacy-resolution-engine` and `identity-legacy-resolution-module`.
- **Settings flags that gate nothing.** 100 fields in
  `services/backend/config/settings.py` read an environment variable that no
  production Python consults, so setting them changed nothing while env examples,
  release flag lists, runbooks and capability overlays presented them as
  controls. They included reserved partner and marketplace flags, per-engine
  extraction-mesh switches, comms campaign and journey switches, suggestion
  adapter switches, Dune access modes, a Jira credential block, a password-policy
  block, and four thresholds the code hardcodes. One looked like a safety
  control (`COMMERCE_APPROVAL_REQUIRED_ALL`, `AETHER_LOCATION_IDENTITY_MERGE_BLOCKED`);
  the guarantee holds structurally and is now pinned by a test instead of a
  flag. One documented staleness window (`KYBER_DIRECTORY_MAX_STALE_HOURS`) was
  never read: the real control is `KYBER_DIRECTORY_MAX_AGE_HOURS`, and the runbook
  now names it. All 100 are deleted, and `scripts/validate_settings_flags.py` fails
  any PR that adds a settings field nothing reads. `ML_MODE` is the one remaining
  unread field; the release profiles pin it, so it goes with that profile
  dimension. Rows `delivery-unread-settings-flags` and
  `delivery-unread-settings-flags-pending`.
- **Backend code nothing mounts.** Import-graph reachability from `main.py`, the
  packages loaded by name and every script, workflow or Dockerfile that names a
  module (descriptive registries, docs, tests and a script's path or checklist
  entry do not count; a script must import the module or name it as a dotted
  string) leaves 133 of 1,984 production modules, about 32,700 lines,
  unreachable. Nine had no test, document or registry mention and are deleted
  (940 lines). The 133 that remain are
  built and not connected: most are tested (Communication360, managed
  integrations, the derivatives runtime, the OAuth broker, provider tenant
  routes, identity calibration and split services, geo), some are documented as
  shipped (seven suggestion adapters, commerce workers, x402 approvals routes),
  and removing them is a product call. They are frozen in
  `config/backend_reachability.yaml` against ledger row
  `product-backend-unmounted-code-pending`, and
  `scripts/validate_backend_reachability.py` fails any PR that adds a module
  nothing reaches or leaves a stale allowlist entry. Rows
  `product-backend-unmounted-code` and `product-backend-unmounted-code-pending`.
- **Two handlers on one URL.** `tests/unit/test_route_conflicts.py` froze 7
  duplicates but compared path-parameter names literally, so it could not see
  `/profile/{user_id}/pnl` shadowing `/profile/{entity_id}/pnl`. Comparing with
  parameter names erased and include prefixes applied finds 15, and all 15 are
  resolved: the gate now allows none, and a second test pins the owner of each
  URL that had a shadowed copy. The five `/v1/admin/kyber/*` copies in
  `services/intelligence/routes.py` were dead (the Kyber hook calls the
  `admin/routes.py` shape and passes a `window` the copies did not accept). The
  other ten were resolved by choosing the handler on evidence. The Stripe webhook
  is served by `admin/webhook_routes.py`, the fuller and tested handler (it
  gains `invoice.payment_succeeded` and `invoice.created` from the inline copy,
  whose API-key cache refresh was redundant because `APIKeyValidator` reads the
  billing account's plan tier on every request). The attribution model catalog
  and `/pnl` keep the served handler, because both frontends read them. Four of
  the six economic sub-resources were empty response models that shadowed the
  real aggregation with no read-permission check and, for web2, no credit-consent
  check; the profile handlers (which the tests and Profile 360 docs describe) now
  serve them, so those four bodies change and web2 returns 403 without credit
  consent. The other two (`/agentic`, `/campaigns`) keep the economic handlers,
  which compute spend and ROAS, and every `services/economic` route now requires
  the `read` permission. The `services/social` wrapper called the same aggregator
  as the handler it shadowed and is deleted. Rows
  `intelligence-duplicate-route-handlers` and `product-legacy-social-route`.
- **Eleven workflows start on `ready_for_review`** beside the canonical
  disposition. #734's R5 audit found no safe removal yet: similar commands do
  not prove equal selection or evidence. Row `delivery-pr-workflows-into-one-plan`.
- **Six profile registries** (1,295 lines) plus `config/readiness_model.yaml`
  each carry their own environment vocabulary. Row `delivery-profile-registries`.
- **A quarantined local stack** under `deploy/legacy-staging` that contradicts
  the canonical staging profile but is still mounted by the root
  `docker-compose.yml`. Row `delivery-legacy-staging-compose`.

## Retirement rules

A row moves `retain`, `converge`, `deprecated`, `deletion-ready`, `removed`.

| Thing | Before it is deletion-ready | Removal PR must also |
|---|---|---|
| Service, route, module | consumer list is empty or migrated; parity evidence on the same fixtures; rollback named | delete its tests, fixtures, config keys, flags, docs and workflow rules |
| Package, script, config, doc | usage evidence (search of workflows, Makefile, package scripts, registries, imports) | regenerate indexes; review source-linked docs; refresh only reviewed hashes |
| Test | its invariant is covered by a cheaper authoritative test, or the code it tested is gone | cite the covering test and any failure history; never delete to turn a run green |
| Compatibility adapter or alias | deadline in the ledger | delete at the deadline, or re-decide with a new date |
| Feature flag | every environment has the same value, or no production code reads it (`scripts/validate_settings_flags.py` fails a settings field nothing reads) | remove the flag and both branches |

**Tests.** Classify by unique invariant, not file count. For each invariant keep
the cheapest authoritative test, one boundary or contract test where a boundary
exists, and one real integration proof elsewhere. A test that only verifies an
implementation detail is a removal candidate. A test that is not run by any
suite (above) is first a gap to close.

## Delivery tiers and budgets

PR confidence proves confidence. Staging proves integration. Nightly proves
depth. `verification / disposition` stays the one blocking PR status.

| Tier | Contents | Budget |
|---|---|---|
| Local fast loop | focused tests, type checks, lint on edited code | 30 to 90 s (target) |
| Normal PR (`ready_for_review`) | install, typecheck, lint, changed-package tests, contract compatibility, ingestion, identity and graph-write smoke, UI boot smoke | narrow PR under 5 min (target); contract, SDK or shared-kernel PR 5 to 10 min; global change may exceed |
| Staging validation | deploy a verified immutable candidate, seed a fixture tenant, connect a test source, ingest, normalize, resolve, populate the graph, render Profile / Journey / Lens, verify the explanation drawer, access state and operator diagnostics | explicitly invoked; not part of the PR budget |
| Nightly regression | full connector and SDK matrices, browser and device matrix, large graph fixtures, performance, advanced identity, replay and backfill, poisoning and anomaly, mobile and Kyber, experimental modules | scheduled |

Observed: #734's hosted finalization ran about six minutes (02:14:56 to 02:20:58 UTC
on 2026-10-09), and the local `verification-disposition` on #733 had an 87 s
critical path and 383 s summed suite time. These are single data points, not a
distribution.

## Environments and flags

Profiles describe environments; flags describe capabilities. Do not let a
capability become a deployment profile.

| Target name | Existing expression |
|---|---|
| `local` | `local`, `local-full` |
| `preview` | `preview` (ephemeral, cost-capped); `demo` is decided separately |
| `staging` | `staging` with `full` and `pilot` lanes and `awake`/`asleep` state |
| `pilot-prod` | none exists; decide whether it is a posture of `production-lean` before wiring |
| `production` | `production-lean`, `production-scale`, `enterprise-isolated` as postures |

No Terraform state key or profile name is renamed by this ledger. Capability
overlays (`enable-communications`, `enable-campaigns`, `enable-agent-beta`,
`enable-x402-experimental`, `enable-kyber-internal`, `enable-gcp-oauth`,
`enable-advanced-value`, `enable-sovereign-controls`) are flags, not profiles.

**Staging holds.** A push to `main` builds an immutable release and, through
`deploy.yml`, rolls it out to staging only when the repository variable
`STAGING_RUNTIME_ENABLED` is `true`. The weekday timer deploys the newest release
built from `main` unless `STAGING_WAKE_HOLD` is `true` (see
[Staging wake / sleep](../../STAGING-WAKE-SLEEP.md)). Neither variable should be
enabled until the maintainer is ready for staging evidence.

## Classification

Everything is `core`, `beta`, `experimental`, `internal`, `deprecated`,
`archived` or `removed`, by whether it directly supports the proof path
tenant, source, evidence, normalization, resolution, graph, intelligence,
explanation, action, outcome.

| Class | Scope |
|---|---|
| Core | tenant runtime, auth and session, workspace/user/role model, SDK heartbeat, connector and webhook ingestion, raw evidence capture, event normalization, source classification, identity stitching, graph population, Profile and Journey views, lens application, evidence and explainability, basic value layer, tenant readiness, pilot billing and access, staging and production deployment |
| Beta | Communications 360, Campaign view, advanced Value views, advanced recommendations and syndicates, cohort versioning, admin readiness dashboard, developer docs, procurement and trust surfaces, partner onboarding |
| Experimental | advanced Agent 360 lifecycle and lineage, X402 observations, Gnosis and plugin marketplace, Harness automation, sovereign and Omega assumptions, multi-cloud paths, advanced agent-commerce modeling, financial rail and card observability |
| Archive or remove | dead routes, duplicate pages, old terminology, unused feature flags and deployment profiles, old docs manifests, stale fixtures, duplicate graph mocks, duplicate 360 components, obsolete naming layers, legacy Audience and Campaign terminology, abandoned proofs of concept, implementation-detail tests, docs checks unrelated to changed code |

[`config/service_classification.yaml`](../../../config/service_classification.yaml)
binds one class and one runtime-spine stage to each of the 142 backend service
directories, and `scripts/validate_service_classification.py` (run by
`make repo-doctor` and as the `service_classification` router check in every
PR-lane plan) fails when a directory that holds Python source has no entry, an
entry has no directory, a class or stage is outside the vocabulary, a reason is
blank, or a `deprecated` service has no row in the ledger. A directory holding
only `__pycache__` is not a service. `--report` prints counts per class.

The first pass is **proposed**, derived from each package's own docstring and the
lists above, and is not a readiness claim: 51 core, 47 beta, 33 experimental, 9
internal, 2 deprecated (`resolution`, `social`). The maintainer reviews and edits
it like any other change; a reclassification is a one-line diff. The same binding
for frontend apps and shared packages is the next registry step.

## Shared 360 composition

Build one set of primitives and compose views from them. Data semantics stay
per entity.

Primitives: `EntityHeader`, `SummaryCards`, `EvidenceTimeline`,
`RelationshipGraph`, `JourneyPanel`, `CommunicationPanel`, `ValuePanel`,
`LensPanel`, `ConfidencePanel`, `ExplanationDrawer`, `ActionPanel`.

| View | Composition |
|---|---|
| Profile 360 | EntityHeader, SummaryCards, EvidenceTimeline, RelationshipGraph, JourneyPanel, LensPanel, ExplanationDrawer, ActionPanel |
| Campaign | EntityHeader, SummaryCards, TouchpointPanel, JourneyPanel, ValuePanel, AttributionPanel, ExplanationDrawer, ActionPanel |
| Agent | EntityHeader, EvidenceTimeline, RelationshipGraph, AuthorityPanel, ToolUsagePanel, JourneyPanel, ExplanationDrawer |
| Communications | EntityHeader, MessageTimeline, RelationshipGraph, JourneyPanel, SignalPanel, ExplanationDrawer |

## Truth, lifecycle and readiness vocabulary

These are views over vocabularies that already exist. Do not add a parallel enum.

- **Truth levels** L0 raw evidence, L1 normalized fact, L2 resolved entity, L3
  inferred relationship, L4 computed journey or value, L5 lens interpretation,
  L6 recommendation, L7 action or outcome, L8 user-confirmed truth. The
  [runtime map](runtime-authority-map.md) already assigns an owner to each.
  Knowledge state (known, unknown, inferred, conflicting, system-confirmed,
  user-confirmed, needs review) reuses `EpistemicStatus` in
  `services/backend/shared/contracts_models/epistemic.py`; there is no
  `CONFIRMED` member yet, so user confirmation needs a typed attestation
  (L8) owned by the relevant domain before any adapter is built. Process state
  and knowledge state stay independent.
- **Lifecycle states** for source (created to archived), profile (candidate,
  active, merged, split, review_needed, suppressed, deleted, archived), journey,
  agent and lens result are proposed vocabulary. Each should extend the
  existing state field of its owning model, and none exists as one queryable
  lifecycle today.
- **Readiness** already has a canonical, deliberately multidimensional model:
  `config/readiness_model.yaml` separates implementation completion, runtime
  integration, external activation and per-environment evidence so that a
  missing credential never reads as unfinished code. The proposed feature ladder
  L0 concept, L1 scaffold, L2 local prototype, L3 integrated, L4 fixture-proven,
  L5 staging-proven, L6 design-partner ready, L7 production hardened is a
  display view derived from those dimensions (for example L1 is `SCAFFOLDED`, L3
  is `RUNTIME_INTEGRATED`, L4 is `VERIFIED`, L5 and later need `staging`
  environment evidence). Tenant, release and runtime readiness stay with their
  current owners (`tenant_readiness`, `scripts/production_status.py`, runtime
  health).

## Sequence

Each step is its own PR on `Development` and states what it makes deletable.

1. This ledger, its validator, and the first deletion (`packages/skeleton-crew`).
2. Wire the unrun TypeScript tests into one registered suite (done in #741, with
   the 10 unresolved imports fixed); map invariants and retire duplicates.
3. Provider cutover: finish R1 for providers, then SDK V1 and V2 dual-read
   parity per tenant, then the V1 write path.
4. Retire `services/backend/services/resolution`: the unregistered engine and
   its routes are deleted; the three tombstone routes go with the Aether
   identity-cluster section.
5. Kyber Profile360: one implementation (done: the orphaned second one is
   deleted), then shared primitives for the other 360 views.
6. Delivery: make each `ready_for_review` workflow a worker of the canonical
   plan or move it to staging, nightly or release; derive profile names from
   `config/deployment_profiles.yaml`.
7. SDK convergence matrix (Web, Server, React Native, Android, iOS; V1 and V2)
   and a shared semantic core.
8. Bind a class to frontend apps and shared packages, then re-measure with
   `--report` on both validators.
