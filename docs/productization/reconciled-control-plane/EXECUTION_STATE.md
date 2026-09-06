---
title: Execution State — Reconciled Control Plane (Phases 0–4)
slug: productization/reconciled-control-plane/execution-state
section: operations
visibility: I
audience: [architect, ops, exec]
status: experimental
since_version: "8.12.0"
canonical_owner: platform@aether
---

# Execution State — Reconciled Control Plane (Phases 0–4)

> **Delivery model:** the §0–40 build ships as one stacked lane
> (`feat/reconciled-control-plane`) on the SDK-universal-ingestion integration
> head (`ws/lane0-basefix` @ `1b616a62`) and is meant to ride the same merged
> program. Per the build directive, focused unit tests ran as each phase
> landed; the canonical full gate — env-stripped `make ci-check` = 0, docs
> drift strict clean, generated docs regenerated, `git status` empty — runs
> once at the **lane tip** after the final phase commit.

## Phase 0 — managed-integration abstraction + reconcile skeleton

**Delivered.** A reconciliation *skeleton* with durable state and a read-only
operator surface — flag-gated OFF, additive, fail-closed. Governing principles
and boundary: `docs/architecture/RECONCILED_CONTROL_PLANE.md`.

| Deliverable | Evidence |
|---|---|
| Contract-Spine twin extension (`packages/shared/managed-integrations.ts` ↔ `services/managed_integrations/contracts.py`) | `tests/contracts/test_managed_integrations_parity.py` (const-array + barrel parity) |
| Governance domain `reconciled_control` (twin + explicit operator grants, out of `ALL_DOMAINS`) | `tests/unit/test_security_governance_domain_twin.py::test_reconciled_control_domain_is_in_both_sides` |
| Desired-state + observed-state assembly from existing authorities | `desired_policy.py` / `sensors.py` (read-only, evidence-backed) |
| Reconcile classification (§32 steps 1–11) | `tests/unit/reconciled_control/` (match/actionable/blocked/unknown + CP-12 distinctness + flag-OFF parity) |
| Durable `managed_integrations` + `reconcile_runs` + direct-SQL repos | alembic `20260906_rcp_managed_integrations.py` (additive, migration-safety + temporal-integrity clean); `Backend Architecture/aether-backend/tests/managed_integrations/` |
| Read-only operator surface | `services/managed_integrations/routes.py` (2 GETs), mounted in `main.py` behind `reconciled_control.enabled AND kyber_route_enabled` (default OFF) |
| Registries + docs | `docs/source-of-truth/repo_consistency_ownership.json` category `reconciled_control_plane`; architecture + phases + this page authored. `config/implementation_ledger.yaml` is reserved for founding-tenant/release-governance items (no prior lane — data-exchange, financial-normalization — adds lane rows); this lane follows that precedent and adds none. |

## Phase 1 — ChangeSet planning + change-risk engine

**Delivered.** The planning half of the loop: typed, risk-assessed,
concurrency-guarded ChangeSet *drafts* — still never applied.

| Deliverable | Evidence |
|---|---|
| §33 taxonomy (22 types), §34 statuses, §39 risk classes + automation rules, §36 change-action kinds — all first-class vocabulary | contract twins + `tests/contracts/test_managed_integrations_parity.py` |
| `change_planning.py` (candidate plans from drift) + blast-radius + risk engine + automation authority | `tests/unit/reconciled_control/test_change_planning.py` (373 lines of assertions) |
| §35 concurrency/idempotency guards ("never apply a stale ChangeSet") | guard vocabulary in `contracts.py`; `test_change_set_flow.py` |
| Durable `change_sets` table + repository + additive alembic `20260906_rcp_change_sets.py` | backend `tests/managed_integrations/test_change_sets_repository.py` |
| Read-only operator change-set surface (list/detail) | `routes.py` + `test_routes_review_surface.py` |

## Phase 2 — Typed actuator engine + execution (CP-08 lift, scoped)

**Delivered.** The execution half behind the §34 state machine: typed
actuators, verify-or-rollback, LKG only after verification, full evidence,
approval gating by §21 role, ActionRequired surfacing. Flag-gated OFF.

| Deliverable | Evidence |
|---|---|
| §36 typed actuator registry (`actuators.py`, day-1 kinds over existing write-authorities) | `tests/unit/reconciled_control/test_executor.py` + actuator registry tests |
| §34 executor: guarded transitions, verify (technical + semantic), commit/rollback with LKG ref, LKG-after-verify | `executor.py` (909 lines), transition-legality + LKG-after-verify tests |
| Evidence records (§12.13), epistemic kinds (§12.15), approvals + ActionRequired (§12.14) rows | alembic `20260906_rcp_execution.py` (additive); backend `tests/managed_integrations/test_execution_records_repository.py` |
| Approval gating by §21 role (approval records ride Phase-3's review surface) | approvals repo + route tests |

## Phase 3 — Admission, discovery/mapping/source-authority, scheduler, simulation

**Delivered.** The loop closes from real integrations: §16 admission, §17
local-first discovery, §18 mapping candidates + §19 source authority (§8.1
review bands, §38 auto-promotion gates, fail-closed), §20 dry-run/digital
twin, §37 simulation/shadow (no-mutation), and the flag-gated §32/§35
scheduler.

| Deliverable | Evidence |
|---|---|
| Admission lifecycle engine + repo (durational states, suspension/revocation, no forced exit) | `admission.py` + `test_admission.py` (22 tests) |
| Simulation + shadow plane (`compare_paths`, ten axes, shadow never mutates canonical state) | `simulation.py` + `test_simulation.py` (18 tests) |
| Schema fingerprinting + §38 promotion gates (fail closed on missing gates) | `schema_mapping.py` + 36 unit + 12 backend tests |
| Source-authority rules + equivalence keys (longest-prefix, equal-specificity rejected) | `source_authority.py` + 29 tests |
| Scheduler pass (freshness window, only planned + automation_allowed executes) + maintenance-role worker spec | `scheduler.py` + `services/runtime/specs.py`/`roles.py` (single periodic loop, rides `maintenance`) |
| Operator review surface: approvals + action-required GETs | `routes.py` (6 GETs total) + `test_routes_review_surface.py` (7 tests) |

## Phase 4 — Progressive delivery + fleet upgrade controller + console vocabulary

**Delivered.** §40 universal rings as generic rollout infrastructure, the
§12.8 rollout engine with §12.9 health-gated canary (auto-pause/auto-rollback,
fail-closed on missing evidence), the §29 fleet upgrade planner over §28
channels + §30 platform-behavior policy, and the Kyber console capability
surfacing (closing the Phase-0 "no route-registry capability declaration"
caveat).

| Deliverable | Evidence |
|---|---|
| Rollout engine + durable `rollouts` rows (ring order is law: one ring at a time; percentage always tracks stage; paused/terminal columns are the durable §12.9 auto-pause + end state) | alembic `20260906_rcp_rollouts.py`; `rollout.py` + `test_rollout.py` (22 tests) + backend `test_rollout_repository.py` (13 tests) |
| §12.9 health-gate evaluation over `HealthSnapshotView` (numeric operators; missing evidence = `not_observable` violation; CP-12 availability pass-set) | `evaluate_health_gates` + gate-breach/rollback-condition tests |
| Fleet controller: tenant update policies (one per channel, §40 ring ceilings), composed `fleet_upgrade_plans` with deterministic 6-gate eligibility + execution path (`automatic`/`review`/`action`) | alembic `20260906_rcp_fleet_update.py`; `fleet_controller.py` + `test_fleet_controller.py` (33 tests) + backend repo tests (14 tests) |
| Channel semantics: `pinned` → nothing; `security_auto`/`patch_auto`/`compatible_auto`/`managed_stable` deliver exactly the classes their names promise; `latest` rejected on **every** channel; no-policy → review | `CHANNEL_ELIGIBLE_CLASSES` + `reject_latest` + policy-absence tests |
| §30 platform-behavior mapping (kind → key only where evidenced; unmapped kinds → review, never guessed) + host-mediated rows resolve to `action` (no hidden promise) | `_KIND_TO_PLATFORM` mapping table + behavior-routing tests |
| Console surfacing: `kyber.reconciled_control.read` capability (D4 evidence), rides `_READ_EVIDENCE` with `kyber.audit.read`, six `kyber_routes` declarations | `capabilities.py`/`roles.py`/`config/route_registry.yaml`; `tests/unit/reconciled_control/test_console_vocabulary.py` (4 tests) |
| Storage policies for the three Phase-4 tables | `config/storage_policies.yaml` (Phase-4 section) |

### Honest boundaries (Phases 0–4)

- **No production activation.** Everything ships flag-gated default OFF
  (`AETHER_RECONCILED_CONTROL_*`); the scheduler is idle until its master
  switch + kill-switch flip. The §41+ blueprint remainder was unavailable at
  Phase-0 planning time and governs day-1 production activation; no phase
  flips a production switch.
- **No autonomous tenant delivery.** §40 rings above 0% deliver to tenants
  only under tenant update policy + approvals (Phase-2 engine, §21); the fleet
  controller composes plans and never self-executes (its `automatic` plans
  still ride the governed executor path — exercised by tests only). No
  tenant-controlled binary is ever promised independently rewritable (§30).
- **No tenant console.** The `reconciled_control` domain carries no tenant
  grant (Phase-0 governance decision); the review/action surface is operator
  only. Tenant-facing self-service review remains reserved.
- **Console surfacing is declaration + vocabulary.** The capability/registry
  declarations engage denial only when the routes are mounted **and**
  `KYBER_BACKEND_AUTHZ_ENFORCED` is on (default OFF in local/dev; default ON
  for deploy targets — the §21-console path is live-ready but inert here).
- **Full gate pending.** Per the build directive the canonical gate
  (env-stripped `make ci-check` = 0) runs at the lane tip after the final
  commit; per-phase rows above are "targeted tests pass", not a gate claim.

## Lane status

Phase commits on this lane: Phase 0 `b0658b5d`, Phase 1 `7a3ae88f`, Phase 2
`71dcbce2`, Phase 3 `5eb58d93`, Phase 4 (pending commit at lane tip). The
post-gate remainder — release readiness, §41+ review, and the stack onto the
SDK-universal-ingestion PR program — is reserved.
