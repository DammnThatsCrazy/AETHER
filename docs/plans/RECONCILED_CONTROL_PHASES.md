---
title: Reconciled Control Plane — Phases
slug: plans/reconciled-control-phases
section: architecture
visibility: I
audience: [architect, dev-senior, exec]
status: experimental
since_version: "8.12.0"
canonical_owner: backend@aether
---

# Reconciled Control Plane — Implementation Program

Program ledger for Aether's Reconciled Control Plane (managed-integration
convergence). Architecture + invariants:
[`docs/architecture/RECONCILED_CONTROL_PLANE.md`](../architecture/RECONCILED_CONTROL_PLANE.md).

## Program scope and source of truth

The canonical specification is the **Reconciled Control Plane Blueprint**
(§0–§40). Every phase below cites its spec anchors. Phase anchors use the
conventions:

- `§NN.M` — blueprint section / contract sub-number (e.g. `§32.12` is
  Reconciliation Engine **step 12**);
- `§12.N` — Closed-Loop Reconciliation **contract** N (e.g. `§12.5`
  `ChangeSetContract`).

Program boundary (unchanged from Phase 0): the blueprint paste available at
Phase-0 planning time was truncated at §40; **§41+ is unavailable and governs
day-1 production activation**. No phase below flips a production switch; every
capability ships flag-gated default OFF and is exercised by tests until a
§41+ review lifts the boundary.

The whole §0–40 build is delivered on one stacked lane
(`feat/reconciled-control-plane`, base `ws/lane0-basefix` = the
SDK-universal-ingestion integration head). The canonical completion gate is
`make ci-check` at the **lane tip** (docs drift strict clean, generated docs
regenerated, `git status` empty); per the build directive, focused unit tests
run as modules land but the full gate is deferred to the end of the §0–40
build, not per phase.

---

## Phase 0 — Managed-integration abstraction + reconcile skeleton (landed)

| Deliverable | Spec anchor | Status |
|---|---|---|
| `ManagedIntegration` abstraction: 21 kinds + CP-12 typed availability | §6, §4 (CP-12) | ✅ implemented |
| Contract-Spine twin extension: `packages/shared/managed-integrations.ts` ↔ `services/managed_integrations/contracts.py`, parity-gated | §6–7 twin pattern | ✅ implemented |
| Governance domain `reconciled_control` (operator-only, explicit grants, out of `ALL_DOMAINS`) | §21 role model (read slice) | ✅ implemented |
| Config + flags `AETHER_RECONCILED_CONTROL_*` (all default OFF) | — | ✅ implemented |
| Desired-state assembly from release-channel policy (`desired_policy.py`) | §22, §28–29 channels | ✅ implemented |
| Read-only observed-state adapters over SDK-health / provider-runtime / capability authorities (`sensors.py`) | §24, §15 provenance | ✅ implemented |
| Reconcile classification: `match/acceptable/actionable/blocked/unknown`, DRAFT change summary | §32 steps 1–11, §12.1–12.4 | ✅ implemented |
| Durable `managed_integrations` + `reconcile_runs` tables (additive alembic) + direct-SQL repositories | §6, §12.4 | ✅ implemented |
| Read-only operator surface `GET /v1/admin/kyber/managed-integrations[/{id}]` | — | ✅ implemented |
| Tests: CP-12 distinctness, reconcile classification, flag-OFF parity, repo round-trip, twin/domain parity | — | ✅ targeted tests pass |
| Full env-stripped `make ci-check` = 0 | — | ✅ passed at lane tip (`9f6158eb`, 78/0) |

### Phase-0 boundary (what the skeleton does not do)

- **No live reconcile trigger.** Nothing periodically reconciles a real
  integration in Phase 0; the reconcile machinery is exercised by tests only.
- **No actuator / applied ChangeSet.** A reconcile never mutates anything
  (CP-08 boundary). Drift evidence is persisted and read, never acted on.

---

## Phase 1 — ChangeSet planning + change-risk engine (landed)

**Shape:** the *planning half* of the reconciliation loop. Drift that Phase 0
classifies as `actionable` now becomes a **typed, risk-assessed, concurrency-
guarded ChangeSet draft** — still never applied. Adds the canonical §33
taxonomy, the §34 status *vocabulary*, and the §39 risk engine so every
future execution decision is pre-computed and durable.

| Deliverable | Spec anchor | Status |
|---|---|---|
| Canonical drift taxonomy — all 22 §33 types as first-class vocabulary (distinct from the 6-type Phase-0 *emitted* subset; nothing narrowed) | §33 | ✅ implemented |
| ChangeSet status vocabulary (`draft→planned→…→committed/rolled_back` + `cancelled/blocked/failed/superseded`) | §34 | ✅ implemented |
| Risk classes `R0 trivial … R5 destructive` + `security_emergency` with automation rules | §39 | ✅ implemented |
| Change-action kinds (the typed operations an actuator may perform; §36 actuator names as vocabulary) | §36 (Day-1 list) | ✅ implemented |
| `change_planning.py` — `plan_from_drift`: candidate ChangeSet generation | §32 step 12, §12.5 | ✅ implemented |
| Control-topology blast-radius calculator over the managed-integration graph (tenant / env / kind / source-origin fan-out) | §32 step 13 | ✅ implemented |
| Risk engine `assess_risk` → `risk_class/automation_allowed/required_approval_refs` | §32 step 14, §12.6 | ✅ implemented |
| Automation-authority decision — which risk classes may auto-proceed; everything else routes to approval/action | §32 step 15 | ✅ implemented |
| Concurrency + idempotency guard: `desired_revision`/`observed_revision`/`reconcile_sequence`/`changeset_id`/`idempotency_key`/`lease_owner`/`lease_expiry`; invalidation check "never apply a stale ChangeSet" | §35 | ✅ implemented |
| Durable `change_sets` table (planning rows: scope, revisions, changes, risk_ref, status, guards) + repository + additive alembic + storage policy | §12.5 | ✅ implemented |
| Read-only operator surface for change-sets (list/detail, flags + risk/guard fields) | — | ✅ implemented |
| Tests: taxonomy distinctness, planning, blast radius, risk classes, automation authority, guard invalidation, repo round-trip, flag-OFF parity, twin/domain parity | — | ✅ targeted tests pass |

### Phase-1 boundary

- **No execution.** A ChangeSet in Phase 1 is a *candidate*: it can be
  `draft`/`planned` (+ terminal `superseded` when invalidated), never
  `ready`/`rolling_out`. Transitions that imply mutation are modeled but
  unreachable while no executor exists (illegal transitions fail closed from
  the start — §34).
- **No approval engine, no actuator.** Phase 2 wires execution + approval.
- ChangeSets are created by tests and (when the operator surface is live) by
  on-demand operator action; production reconcile→plan wiring is Phase 3.

---

## Phase 2 — Typed actuator engine + execution (CP-08 lift, scoped) (landed)

**Shape:** the *execution half*. Lifts CP-08 for changes the control plane
itself can drive through typed actuators, with the §34 state machine as the
single source of truth, approval gating by §21 role, verify-or-rollback, LKG
established only after verification, and full evidence. **All mutation rides a
live reconcile/ChangeSet that is flag-gated OFF.**

| Deliverable | Spec anchor | Status |
|---|---|---|
| Typed actuator interface + registry: `plan/preflight/apply/verify/rollback(?)` per actuator | §36 | ✅ implemented |
| Day-1 actuator vocabulary bound to existing write-authorities where substrate exists (remote-manifest, connector, provider-runtime, mapping, repository-upgrade, authorization, quarantine, replay, backfill, rollback, notification) | §36 | ✅ implemented |
| ChangeSet state machine executor (guarded transitions; illegal transitions fail closed) | §34, §32 step 18 | ✅ implemented |
| Verify step (technical + semantic health) | §32 step 19, §12.9 | ✅ implemented (§32.19 verify-or-rollback; §12.9 health *axes* arrive with the Phase-4 rollout engine) |
| Commit-or-rollback; rollback with last-known-good ref + queue/replay policy | §32 steps 20–21, §12.11–12.12 | ✅ implemented |
| LKG established **only after** verification passes | §12.12 | ✅ implemented |
| Evidence record on every executed/attempted change (before/after refs, claim type, confidence, contradictory evidence) | §32 step 22, §12.13 | ✅ implemented |
| `ActionRequired`/exception surfaced when a change cannot resolve | §32 step 23, §12.14 | ✅ implemented |
| Approval gating by §21 role; evidence records which authority was exercised | §21, §32 step 17 | ✅ implemented |
| Control-finding epistemic discipline (`observed/verified/correlated/inferred/predicted`; never label correlation as causality) | §12.15–12.16 | ✅ implemented |
| Durable execution tables (change-set state history, evidence, LKG, rollback) + repositories + alembic + storage policies | §12.5, 12.11–12.14 | ✅ implemented |
| Tests: state-machine transition legality, actuator registry, verify/rollback decisioning, LKG-after-verify, evidence completeness, approval-role gating, flag-OFF parity | — | ✅ targeted tests pass |

### Phase-2 boundary

- **No autonomous production trigger.** Executors run when an operator or a
  later-phase scheduler submits a ChangeSet through the governed path; nothing
  auto-acts on drift yet.
- **Simulation/shadow and schema/mapping drift automation** are Phase 3 — a
  ChangeSet may carry a `simulation_ref` placeholder but cannot require one
  until Phase 3 provides the simulator.
- Rollout/percentage gating (`§12.8`) is a Phase 4 concern; Phase 2 executes
  an approved plan atomically.

---

## Phase 3 — Admission, discovery/mapping/source-authority, scheduler, simulation (landed)

**Shape:** close the loop from *real integrations* into the machinery —
registration of discovered integrations through the §16 admission lifecycle, a
flag-gated scheduler that turns reconcile runs (Phase 0) + planning (Phase 1)
+ execution (Phase 2) into a continuous loop, automatic semantic-mapping
candidates (§18) and source-authority reconciliation (§19), and the simulation/
shadow plane that later phases require before moderate-risk automation (§37,
§20).

| Deliverable | Spec anchor | Status |
|---|---|---|
| Integration admission: registration of integrations discovered from the existing authorities (SDK installs, provider connections, connectors, imports, feeds) through the §16 lifecycle states | §16 | ✅ implemented |
| Local-first discovery manifests (metadata-only by default; source code / production values never uploaded by default) | §17 | ✅ implemented |
| Automatic semantic-mapping candidate engine (`SemanticMappingCandidate[]`; candidates are epistemic proposals, never truth) + authorization/shadow remain separate | §18, §8.1 | ✅ implemented |
| Source-authority rules + observation-equivalence keys + candidate grouping (multi-source reconciliation); transport idempotency ≠ semantic dedup | §19, §9.1–9.2 | ✅ implemented |
| Real schema fingerprinting + schema/mapping drift automation pipeline (profile→diff→compile→candidate→sensitivity→authorization→confidence/semantic-loss), auto-promote only when all gates hold | §25, §38 | ✅ implemented |
| Dry-run + lightweight operational Digital Twin for an IntegrationPlan / ManagedIntegration (safe simulation without raw production data) | §20 | ✅ implemented |
| Simulation + shadow plane: authoritative current path vs non-authoritative candidate path; compare schema/mapping/policy/joinability/continuity/metrics/latency/drops/dupes/cost; **no shadow result mutates canonical graph state** | §37, §12.7 | ✅ implemented |
| Flag-gated scheduler: periodic reconcile + plan + execute through the governed path; honours §32 freshness window and §35 guards | §32, §35 | ✅ implemented |
| Operator + tenant surfaces for review/action items that automation routes (approvals, exceptions) | §21, §12.14 | ✅ implemented — operator surface (approvals + action-required review routes); the *tenant* console is deliberately deferred — the `reconciled_control` domain carries no tenant grant (Phase-0 governance decision) |
| Tests: admission-state legality, mapping-candidate gating, source-authority equivalence, schema/mapping auto-promotion gates, shadow no-mutation, scheduler fresh/guard behaviour (flag OFF), flag-OFF parity | — | ✅ targeted tests pass |

### Phase-3 boundary

- **No autonomous self-updating.** "Discovery never equals authorization"
  (CP-03) and "capability never equals enablement" (CP-04) hold: discovery,
  mapping candidates, and schema/mapping promotion all stop at review/action
  unless every §38 gate passes **and** the change's own risk class allows
  automation (Phase 1 engine decides authority).
- Tenant-side client upgrades stay behind §28 self-adaptation policy and the
  Phase-4 rollout gates; the scheduler may *propose*, never silently force, a
  tenant-controlled binary change (§30).

---

## Phase 4 — Progressive delivery + fleet upgrade controller + console vocabulary (landed)

**Shape:** make §40 progressive delivery generic infrastructure over every
managed artifact, drive the §29 fleet-upgrade controller through it, and expose
the plane in the Kyber console vocabulary (the Phase-0 "no route-registry
capability declaration" caveat closes here).

| Deliverable | Spec anchor | Status |
|---|---|---|
| Universal progressive-delivery rings (Olympus internal → test tenants → 1% → 5% → 20% → 50% → 100%) as generic rollout infrastructure | §40 | ✅ implemented |
| Rollout engine: cohorts, current stage/percentage, health gates, advance/pause/rollback conditions | §12.8 | ✅ implemented |
| Health-gated canary + auto-pause/auto-rollback on gate breach | §12.9, §39 R2 | ✅ implemented |
| Fleet upgrade controller composition: release registry ↔ artifact manifest ↔ fleet version inventory ↔ lifecycle ↔ compatibility matrix ↔ tenant update policy ↔ upgrade planner → rollout/rollback/evidence | §29 | ✅ implemented (planner composition; rollout/rollback/evidence ride the Phase-2 executor + §40 delivery facts) |
| Tenant update channels operationalized over delivery rings (pinned/security_auto/patch_auto/compatible_auto/managed_stable; **never** equate `managed_stable` with uncontrolled `latest`) | §28–29 | ✅ implemented |
| Platform-specific upgrade-behavior policy table (fully-managed vs host/builder-mediated vs prohibited) | §30 | ✅ implemented (11-row §30 table mirrored; host-mediated rows resolve to the `action` path — no hidden promise; nothing in §30 is prohibited, so none is invented) |
| Kyber console: capability vocabulary entry for the reconciled-control domain + `kyber_routes` registry declarations + workforce grant surfacing | §21, §3.2 | ✅ implemented (`kyber.reconciled_control.read` + evidence-read role-template grants + 6 route declarations; closes the Phase-0 "no route-registry capability declaration" caveat) |
| Tests: ring ordering/gating, health-gate pause/rollback, canary advance, update-channel→ring resolution, fleet-controller planning, console vocabulary, flag-OFF parity | — | ✅ targeted tests pass |

### Phase-4 boundary

- **Tenant production activation is not assumed.** Rings above 0% deliver to
  tenants only under tenant update policy + approvals (Phase 2 engine, §21);
  turning rings on for real traffic sits behind the §41+ review gate.

---

## Cross-cutting (holds every phase)

- **Contracts first.** Each phase lands TS↔Python contract twins + parity tests
  before engine code (Data-Exchange twin pattern), and extends the governance
  domain only via explicit grants — never `ALL_DOMAINS`.
- **Fail closed.** New statuses/classes/gates default to deny; illegal
  transitions and unknown drift types are rejected, not coerced.
- **Evidence-backed.** No classification or decision is asserted without a
  provenance-bearing observation (§15, §24, CP-12).
- **Additive.** Alembic migrations are additive only; every table carries a
  `config/storage_policies.yaml` entry; no drops, no destructive edits.
- **Flag-gated OFF.** `AETHER_RECONCILED_CONTROL_*` govern every capability;
  production flips require the §41+ review.

No phase is claimed complete ahead of `make ci-check` at that phase's tip (all
phases land first on this lane, then one full gate at the lane tip per the
build directive). **Lane-tip gate result:** env-stripped `make ci-check` = 78
gates / 0 failed at `9f6158eb` (2026-09-06); docs drift strict clean,
generated docs regenerated, `git status` empty.
