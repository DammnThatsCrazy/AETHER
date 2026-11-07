---
title: Execution State — Reconciled Control Plane (Phases 0–4)
slug: productization/reconciled-control-plane/execution-state
section: operations
visibility: I
audience: [architect, ops, buyer]
status: experimental
since_version: 0.1.0
canonical_owner: platform@aether
---

# Execution State — Reconciled Control Plane (Phases 0–4)

> **Delivery model:** the §0–40 build ships as one stacked lane
> (`feat/reconciled-control-plane`) on the SDK-universal-ingestion integration
> head (`ws/lane0-basefix` @ `1b616a62`) and is meant to ride the same merged
> program. Per the build directive, focused unit tests ran as each phase
> landed; the canonical full gate — env-stripped `make ci-check` = 0, docs
> drift strict clean, generated docs regenerated, `git status` empty — runs
> once at the **lane tip** after the final phase commit. **Result: the
> lane-tip gate passed — env-stripped `make ci-check` = 78 gates / 0 failed
> at `9f6158eb` (2026-09-06).** Two genuine leaf-gate regressions surfaced
> only after the push (outside the local gate's scope) and were fixed in code,
> never weakened: `ea912bef` (sdk-js coverage — TS twin test sibling for the
> 12 type guards + vocabularies) and `09cf26a7` (real-Postgres smoke — the
> `observation_equivalence_keys` `window` column renamed `equivalence_window`;
> `window` is a PostgreSQL reserved word that SQLite tolerates, so only the
> postgres:16-alpine alembic lane caught it). Re-gated at the final tip:
> env-stripped `make ci-check` = **78 gates / 0 failed at `8ecd55be`**
> (2026-09-06), and all PR #609 leaf checks green on that tip.

## Phase 0 — managed-integration abstraction + reconcile skeleton

**Delivered.** A reconciliation *skeleton* with durable state and a read-only
operator surface — flag-gated OFF, additive, fail-closed. Governing principles
and boundary: `docs/architecture/RECONCILED_CONTROL_PLANE.md`.

| Deliverable | Evidence |
|---|---|
| Contract-Spine twin extension (`packages/shared/managed-integrations.ts` ↔ `services/api/connectors/managed_integrations/contracts.py`) | `tests/contracts/test_managed_integrations_parity.py` (const-array + barrel parity) |
| Governance domain `reconciled_control` (twin + explicit operator grants, out of `ALL_DOMAINS`) | `tests/unit/test_security_governance_domain_twin.py::test_reconciled_control_domain_is_in_both_sides` |
| Desired-state + observed-state assembly from existing authorities | `desired_policy.py` / `sensors.py` (read-only, evidence-backed) |
| Reconcile classification (§32 steps 1–11) | `tests/unit/reconciled_control/` (match/actionable/blocked/unknown + CP-12 distinctness + flag-OFF parity) |
| Durable `managed_integrations` + `reconcile_runs` + direct-SQL repos | alembic `20260906_rcp_managed_integrations.py` (additive, migration-safety + temporal-integrity clean); `services/api/tests/managed_integrations/` |
| Read-only operator surface | `services/api/connectors/managed_integrations/routes.py` (2 GETs), mounted in `main.py` behind `reconciled_control.enabled AND kyber_route_enabled` (default OFF) |
| Registries + docs | `docs/reference/source-of-truth/repo_consistency_ownership.json` category `reconciled_control_plane`; architecture + phases + this page authored. `config/implementation_ledger.yaml` is reserved for founding-tenant/release-governance items (no prior lane — data-exchange, financial-normalization — adds lane rows); this lane follows that precedent and adds none. |

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
| Schema fingerprinting + §38 promotion gates (fail closed on missing gates) | Removed: the engine (`schema_mapping.py`) was never mounted or reached by any route or worker. The §38 gate vocabulary remains in `contracts.py` and its TS twin; the `schema_mapping_*` tables remain (additive migration) |
| Source-authority rules + equivalence keys (longest-prefix, equal-specificity rejected) | `source_authority.py` + 29 tests |
| Scheduler pass (freshness window, only planned + automation_allowed executes) + maintenance-role worker spec | `scheduler.py` + `services/api/workers/runtime/specs.py`/`roles.py` (single periodic loop, rides `maintenance`) |
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
| Fleet controller: tenant update policies (one per channel, §40 ring ceilings), composed `fleet_upgrade_plans` with deterministic 6-gate eligibility + execution path | Removed: `fleet_controller.py` and its repository were never mounted or reached by any route or worker. alembic `20260906_rcp_fleet_update.py` and the channel vocabulary remain; rebuild the planner when the fleet-update surface is wired |
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
- **Full gate passed at the lane tip.** The canonical gate (env-stripped
  `make ci-check` = 0) ran once at the lane tip after the final commit: **78
  gates / 0 failed** at `9f6158eb` (2026-09-06), docs drift strict clean,
  generated docs regenerated, `git status` clean. Per-phase rows above are
  targeted-test claims; the lane-tip gate is the full claim. After the push,
  GitHub leaf checks caught two genuine regressions outside the local gate's
  scope — sdk-js coverage (no TS tests for the §0–40 vocabularies/guards) and
  the real-Postgres alembic smoke (reserved-word `window` column, see header).
  Both fixed in code (`ea912bef`, `09cf26a7`), docs re-reviewed + restamped
  (`8ecd55be`), and the canonical gate re-run on the final tree: **78 gates /
  0 failed at `8ecd55be`**, all PR #609 leaf checks green.

## Post-734 Program A+B — authority reconciliation + durable activation

**Landing branch:** `t3/control-plane-day1-convergence-spec` (stacked on the
post-734 base). This slice does not turn the plane on; it makes the authority
explicit before runtime convergence.

| Deliverable | Evidence |
|---|---|
| Reconciled authority map: external/observed/no-interface/owned/forbidden areas, with a fail-closed integrity assertion | `services/api/connectors/managed_integrations/authority.py`; `tests/unit/reconciled_control/test_authority_map.py`; `GET /v1/admin/kyber/managed-integrations/authority` |
| Durable readiness-gated activation `shadow→detect→plan→r0→r1→r2→fully_managed` + `emergency_frozen` | `activation.py`, `activation_repository.py`, alembic `20261029_rcp_activation_authority.py`; `test_activation_authority.py` |
| Transitions `advance`/`freeze`/`resume`; one-step advance; freeze-from-anywhere; resume restores pre-freeze state; state+evidence commit atomically | same tests (39 targeted activation/authority/route cases) |
| Flags as hard kill switches over `effective_state`, never grants | `effective_state()` + `tests/unit/reconciled_control/test_activation_authority.py` |
| Read-only operator reads `GET /authority`, `GET /activation`, `GET /activation/transitions` | `routes.py`; `config/route_registry.yaml`; `test_routes_activation.py` |
| Honest readiness record: implementation declared, runtime convergence unsatisfied, productionization 50%, Programs C–G explicit | `config/readiness/features/reconciled-control-plane.yaml`; `validate_readiness_model.py --strict` |
| Spine row `pending` → `in_flight`; connection360 pending-authority declaration removed | `packages/shared/contracts/spine-registry.json`, `intelligence-projection-registry.json` |

**Boundary.** No write/transition route (Program E/F), no runtime convergence
in the A+B slice, no staging/production activation evidence (Programs F/G), and
no production-readiness claim.

---

## Post-734 Program C — scheduler runtime convergence + SDK request intake

**Landing branch:** `t3/control-plane-day1-convergence-spec` (stacked on the
Program A+B slice). The scheduler now reads the durable activation decision
instead of treating flags as operational authority; SDK manifest changes get
an asynchronous RCP request path instead of bypassing the plane.

| Deliverable | Evidence |
|---|---|
| Runtime capability law (`shadow` observe, `detect` reconcile, `plan` plan, `r0+` execute, `disabled`/`emergency_frozen` stop) | `activation.runtime_capabilities`; `test_activation_authority.py` |
| Tenant/environment scope narrows the global activation; missing tenant row inherits it; one decision cached per pass | `RuntimeActivationResolver`; resolver scope tests |
| Scheduler gates reconcile, plan and execute on the resolved decision; inactive rows are reported as `skipped_inactive` | `scheduler.py`; `test_scheduler.py` (shadow/detect/plan + default-flags-off cases) |
| Resolver failure fails closed per row and never fabricates a reconcile/plan/execute | `scheduler.py`; `test_scheduler.py` resolver-error case; pass `errors` summary |
| Flag ceiling still applies through `effective_state`; durable activation is the only grant | `activation.py`; existing flag-ceiling tests |
| Direct `PUT /v1/config/sdk/manifest` refuses while RCP is enabled; legacy behavior remains when RCP is off | `sdk_config/routes.py`; route tests in `test_sdk_manifest_requests.py` |
| `POST /v1/config/sdk/manifest/requests` records one planned `remote_manifest_change` ChangeSet + stage-zero `runtime_config` rollout, scoped to tenant-wide environment `all`; `GET .../requests/{id}` reads it | `sdk_config/rcp_requests.py`; `test_sdk_manifest_requests.py` |
| Request path checks the `plan` capability before writing; missing observed state, missing capability and idempotency-key reuse fail closed | `sdk_config/rcp_requests.py`; service tests |
| Request idempotency reuses one ChangeSet + rollout for the same `Idempotency-Key` and payload | `sdk_config/rcp_requests.py`; idempotency tests |

**Boundary.** The request is not a publish: `SDKConfigService` still owns the
actual manifest write and its `rollout_percentage`, request execution/rollout
projection remains open, and Provider Runtime changes are not converged.
Program C stays unsatisfied in the readiness record; no staging/production
activation is claimed.

---

## Consuming lane — SDK distribution layer (site installs)

**Delivered on `feat/sdk-distribution-layer`.** The SDK distribution layer
adopted the plane rather than extending it: a registered site becomes a
managed integration the plane can observe and admit. Nothing about the plane's
own state changed — see the boundary immediately below.

| Deliverable | Evidence |
|---|---|
| `observed_from_site_install` — install state → CP-12 availability, runtime-reported provenance, `failed` → `degraded` | `tests/unit/reconciled_control/test_sensors.py` (7 site-install cases: no record, `awaiting_first_signal`, `failed`, `live`, unrecognized state, reported age, drift-status agreement) |
| `sdk_distribution/control_plane.py` — `register_site_install` (register + §16 admission) and `site_install_observation` | `tests/unit/test_sdk_control_plane_integration.py` (12 cases: flag-OFF writes nothing, identity refused not guessed, channel honoured, re-registration is one row, store failure swallowed) |
| Registration wired at site creation, not first signal (a site that never installs has nothing to project) | `services/api/ingestion/sdk_distribution/routes.py` |
| `failed` recognized as reconcilable drift | `reconciler.py` `_UNHEALTHY_STATUSES` + the drift-agreement case in the sensor tests |
| Seam gate | `scripts/validate_sdk_control_plane_seam.py`, registered in `repo_doctor` (install-state vocabulary both directions, every field read off a described install, one version authority, plane mutation path unreached); 8/8 injection cases caught during authoring |

### Honest boundaries (this lane)

- **That lane did not move the spine row.** At its tip,
  `reconciled_control_plane` remained `implementationState: "pending"`,
  `ownsCanonicalTruth: false`, `graphMutationPolicy: "read_only"`, all 14
  conformance items `open`. This lane registered integrations through the
  plane's existing §16 admission; it did not close a conformance item. The
  Post-734 Program A+B slice later moves the row to `in_flight` with only the
  authority/non-ownership check verified.
- **Observe and register only (CP-08).** The distribution layer never
  reconciles, plans, or mutates. The seam gate fails if
  `control_plane.py` reaches `actuators`/`executor`/`change_planning`/
  `rollout`/`scheduler`/`simulation`, and a second clause fails if the plane
  itself imports `ingestion.sdk_distribution` — the dependency runs one way.
- **No production activation.** Every call is gated by
  `reconciled_control.enabled` (default OFF) and returns `None` when the plane
  is off. No readiness claim is made for the plane or for the distribution
  layer beyond what `scripts/production_status.py` supports.
- **No new production claim for the SDK area.** `scripts/production_status.py`
  carries no RCP area; SDKs remain `4/5 release-ready (minor gaps)`. This
  section records mechanism and boundary only.

## Lane status

Phase commits on this lane: Phase 0 `b0658b5d`, Phase 1 `7a3ae88f`, Phase 2
`71dcbce2`, Phase 3 `5eb58d93`, Phase 4 `e265a938`; gate prep: source-linked
doc review `2d6b1fd0` + `9f6158eb`, temporal-kernel delegation + generated-doc
sync `4b0d0476`; post-push leaf-gate fixes: sdk-js TS-twin coverage `ea912bef`,
PG reserved-word column rename `09cf26a7`, doc re-review restamp `8ecd55be`.
Lane-tip gate: env-stripped `make ci-check` = **78 gates / 0 failed** at
`9f6158eb` **and re-run 78 gates / 0 failed at the final tip `8ecd55be`**
(2026-09-06), all PR #609 leaf checks green. The post-gate remainder —
release readiness, §41+ review, and the stack onto the SDK-universal-ingestion
PR program — is reserved.
