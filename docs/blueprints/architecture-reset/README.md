---
title: Aether Architecture Reset Delivery Plan
slug: blueprints/architecture-reset
section: blueprints
visibility: I
audience: [architect, dev-senior, ops, security]
status: experimental
since_version: 0.1.0
---

# Aether architecture reset delivery plan

## Mission and status

The target is [Aether Root Architecture](../../architecture/AETHER_ROOT_ARCHITECTURE.md):
one tenant-to-outcome runtime spine, with Kyber as the internal operator plane
and the failure, replay, schema, isolation, authority, lifecycle, evaluation,
cost, and security controls beneath every stage. This is a **controlled
authority and repository migration**. Working behavior stays available while
canonical paths take ownership; existing clients and data migrate through
adapters, aliases, and evidence-backed cutovers. The target repo tree is not a
reason to create duplicate packages or independent microservices.

This plan is in accumulation. It is not a merge-readiness, design-partner, or
production-readiness declaration. The integration base is `Development` at
`17503aef9fa3a9515a029471796f1ee3510a5b2c` (2026-10-04 checkout).
The implementation branch is `codex/aether-architecture-reset`, targeting
`Development`. This commit is a repository baseline, **not** a verified
known-good staging or production snapshot; the old/new equivalence ledger
must obtain that evidence before a destructive cutover. The existing
`packages/ios/.build/` artifact in the original checkout is untracked and is
not part of the reset.

At the initial baseline, draft PR #732 proposes `Development` into `main` and
PR #733 proposes the universal connector runtime into `Development`. The
connector PR is an integration dependency, not an alternate provider runtime
for this program. Its live merge state and exact changed files must be
rechecked at each integration boundary. We do not base an authority decision
on a PR description alone.

## One orchestrator, bounded execution

The orchestrator owns this root target, sequencing, shared/generated surfaces,
cross-slice architecture decisions, integration, verification, and final
disposition. Execution agents receive a short work order with: owned paths,
the target behavior, invariants, compatibility requirement, focused commands,
and explicit non-claims. They do not need the linked planning conversations or
the entire program context to complete a slice. Two agents never edit the same
surface concurrently. Generated docs, shared contracts, root configuration,
and cross-cutting migration artifacts are integrated centrally.

Each agent reports what changed, why, focused results, and unresolved risks.
The orchestrator reviews code and evidence before accepting a slice, closes
cross-slice gaps, and revises the remaining work orders. The branch remains
draft during implementation; an agent's focused checks never imply PR or
release readiness.

## PR boundaries and merge order

PR #734 is the architecture authority frame: target architecture, current-to-target
inventories, cutover and proof ledgers, route-state evidence, delivery ownership,
and focused tests for existing route states. It does not change application
routes, service behavior, package boundaries, public SDKs, APIs, schemas,
migrations, graph/event behavior, runtime configuration, or deployment behavior.
Keep the PR draft until its documentation and frame-level evidence are reviewed.

After #734 lands on `Development`, rebase and review the existing universal
connector runtime PR #733 against the accepted source/intake, evidence, identity,
and graph authorities. Preserve its explicit durable-rights, certification,
and provider-backed proof gaps. Follow with separately bounded identity, graph
mutation, replay/data-rights, product-surface, repository, and delivery slices;
order them by the dependency each slice actually has and do not stack blindly.
Each implementation PR should target `Development` once its prerequisite is
merged, carry its own compatibility and rollback evidence, and link back to this
frame. PR #732 is a `Development` to `main` release promotion: hold it until the
architecture/runtime cutovers are reconciled on `Development` and required
staging evidence is recorded or explicitly dispositioned.

## Baseline inventories and authority decisions

| Inventory | Question it must answer | Status |
| --- | --- | --- |
| [Runtime authority](runtime-authority-map.md) | Which current code owns intake, evidence, normalization, identity, graph mutation, replay, intelligence, actions, and recovery? | Mapped; runtime behavior is unchanged in this frame; replay durability and provider cutovers remain pending |
| [Product surfaces](product-surface-map.md) | Which customer and operator routes, 360 components, truth states, and aliases already exist? | Mapped; identity route-state assertions are in this frame; target navigation and activation-state changes remain follow-up work |
| [Delivery controls](delivery-authority-map.md) | Which commands, docs ownership rules, CI paths, profiles, and deployment controls are truly authoritative? | Mapped; this frame changes no verification or deployment behavior; delivery cutovers pending |

The [cutover inventory](cutover-inventory.md) gives the first `keep`, `merge`,
`simplify`, and `defer` decisions for overlapping paths. It names consumers,
compatibility and rollback obligations, and remaining proof before any old
authority or physical directory can retire.

For each candidate removal or move, the inventory must identify all consumers,
runtime calls, API/route names, schemas and migrations, generated artifacts,
CI impact selection, docs `source_files`, deployment references, and rollback.
Disposition is `keep`, `merge`, `move`, `simplify`, `defer`, `archive`, or
`delete`, with a reason and evidence. Product release class (`core`, `beta`,
`experimental`, `internal`, `deprecated`, `archived`, `removed`) is separate
from feature maturity (L0 concept through L7 production hardened). Unknown
maturity stays unknown; a route, test, or mock is not a readiness score.

## Non-negotiable behavior

- Every admitted production observation, identity, graph write/read, cache,
  lens result, replay job, and action has explicit tenant scope and source or
  actor provenance. Rights and consent are checked at the owning boundary.
- SDKs and provider adapters emit evidence and hints. The backend resolver
  decides canonical identity; equal raw IDs from different `source_namespace`
  values are distinct until claims are evaluated. Weak evidence cannot
  silently merge people; review, split, and restatement remain possible.
- Graph state changes through `MutationIntent` and
  `GraphMutationGateway.apply`, with idempotency and an auditable ledger.
  Read models, UI pages, and Kyber diagnostics do not become write authorities.
- Raw evidence and normalized facts keep lineage, time and version semantics.
  Source classification differs from campaign identity. Missing, empty, and
  zero differ. A journey event is not an attribution credit.
- A recommendation needs a reproducible evidence trail. An external action
  requires its own authorization, policy, audit, and outcome receipt. Feature
  flags or entitlements cannot bypass auth, RBAC, tenancy, consent, or rights.
- Existing APIs, source data, staging wake/sleep, marketing handoffs, and
  mobile/deep links remain available until a tested compatibility path and
  rollback exist. Archived code is visibly historical and does not execute
  in the default production path.

## Ordered work packages

| Slice | Owner and scope | Dependency | Acceptance evidence |
| --- | --- | --- | --- |
| R0 Inventory and reference | Orchestrator integrates the three maps, maps current-to-target ownership, captures Git and deployment baseline, and records old/new behavior. | Current `Development`; concurrent PR state. | Every proposed cut has a consumer/authority/rollback record; deploy claims explicitly distinguish known from unverified. |
| R1 Canonical source-to-graph path | Runtime agents converge SDK and provider observations on existing contracts and admission, evidence, normalization, backend identity, and graph gateway. Integrate PR #733 after it lands. | R0; connector/identity ownership review. | Tenant isolation, provenance, idempotency, replay identity, late-binding/no-merge, failure handling, and graph mutation focused checks pass. No duplicate ingress or write path is introduced. |
| R2 Recovery and control plane | Runtime/operator agents close concrete gaps in quarantine, durable replay/backfill, correction/restatement, schema compatibility, diagnostics, rights, permission, and audit behavior. | R1 and threat/failure model. | Authorized tenant-scoped recovery can be demonstrated from retained evidence, including failed and corrected events; adverse cases fail closed. |
| R3 Customer and operator experience | Product agents preserve deep links while composing shared 360 presentation, activation-to-first-value states, customer navigation, evidence and explanation, and Kyber diagnostics. | R1 read contracts and R2 safety. | Populated, empty, loading, error, partial/stale, denied, and review-needed states are testable; Kyber controls remain workforce scoped. |
| R4 Repository consolidation | Orchestrator owns the final path map and moves only genuinely duplicated or misplaced code, with import/route aliases and generator/CI/deploy path updates. | R1-R3 owners stabilized. | A developer can locate one authority per core domain from the root; builds and core contract tests pass; archives are non-runtime. |
| R5 Delivery simplification | Delivery agents reshape existing verification selection and environment overlays from measured overlap, preserving normal PR authority, security, docs, plan, and release gates. | R0 impact inventory; R1-R4 selected proof tests. | Fast PR confidence, staging integration, and nightly depth are distinct; no required invariant loses coverage. Existing deployment plans and wake/sleep remain valid. |
| R6 End-to-end proof and cutover | Orchestrator integrates all slices, runs the fixture tenant flow, then obtains provider-backed and staging evidence, runs failure/replay/rollback rehearsal, reviews docs and source hashes, reconciles the root GitHub README with implemented behavior, and finalizes the draft PR. | R1-R5 complete. | Old/new parity and recovery evidence are recorded; the root README accurately describes the implemented architecture and developer starting points; the terminal normal PR disposition passes. Design-partner or production claims additionally require their own live and release evidence. |

The table is a dependency plan, not evidence that later slices have started.
Each package may contain several small commits with one coherent repo state per
commit. Cross-cutting docs, generated files, registries, and workflow changes
remain orchestrator-owned so parallel agents do not race on shared authority.

## Proof ledger

The [proof ledger](proof-ledger.md) is the old/new equivalence record. It must
distinguish **code present**, **focused
local pass**, **fixture end-to-end pass**, **hosted PR authority**, **staging
rehearsal**, **provider-backed tenant proof**, and **release gate**. Record exact
command, base/commit, environment, fixture or tenant, output location, and
failure disposition. Minimum rows are: tenant provision/auth; source connect
and health; evidence durability; normalization; identity decision and
correction; graph mutation/query; profile/journey/lens/value; explanation;
governed action/outcome; failure quarantine; replay/backfill; billing/access;
and staging wake, deploy, smoke, sleep. The first empty or denied state is part
of the proof, not a special case to hide.

Known gaps at this baseline include the lack of a verified current staging
snapshot for the reset, no provider-backed certification established by these
documents, and the connector PR's stated durable tenant-rights grant storage
dependency. Those are tracked as gaps, not reasons to disable a fail-closed
guard. The product inventory found a route-state matrix drift for Aether
identity routes; this branch adds named loading, empty, error, populated, and
capability assertions, and the focused route-state validator passes. That
repair does not prove the full tenant journey.

The initial `make docs-generate` run regenerated and proved idempotence for
derived docs, and the frontmatter checks passed. Its final strict drift report
failed on **35 source-linked pages**. A separate run against the unmodified
`Development` baseline reported the same 35 stale pages and zero missing
source paths. They remain a review backlog for finalization; this program
will not globally restamp their hashes to make a draft slice appear complete.

## Integration and finalization rule

The orchestrator integrates landed `Development` changes at slice boundaries
and resolves conflicts against the accepted authority map. Source categories
are checked against
`docs/source-of-truth/repo_consistency_ownership.json` before changing derived
surfaces. Generated and sync-managed docs come from their generators. Every
stale source-linked page is reviewed against its `source_files`; only reviewed
pages receive refreshed `source_hashes` through `make docs-generate-changed`.

During accumulation use focused local tests, lint, type checks, docs
generation, and targeted validators. Do not run `make
verification-disposition`, `make ci-check`, `make release-gate`, or hosted PR CI
per slice or push. At finalization, perform architecture and clarification
review, complete required code/docs changes, regenerate derived docs, prove
idempotency, run focused checks, and make the draft PR ready for review. The
`ready_for_review` event launches `.github/workflows/repo-consistency.yml` and
its terminal `verification / disposition` authority. A material fix may
justify rerunning a failed authority. Broad `make ci-check` and
`make release-gate` retain their trusted-main/nightly/release roles or run
when explicitly requested; they are not a second ordinary PR blocker.

The reset is complete only when the root architecture describes working code,
the repo and runtime have one clear authority per core domain, the proof ledger
and compatibility/rollback evidence are complete, generated and authored docs
are reviewed, and the required PR authority passes. Until then this plan and
the root document identify the target and progress, not readiness.
