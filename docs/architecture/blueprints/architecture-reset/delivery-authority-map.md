---
title: Architecture Reset Delivery Authority Map
slug: blueprints/architecture-reset/delivery-authority-map
section: blueprints
visibility: I
audience: [dev-senior, architect, ops, security]
status: experimental
since_version: 0.1.0-alpha.0
---

# Delivery authority map

This is a code-derived ownership map for the architecture reset, inspected at
`17503aef9` on `codex/aether-architecture-reset`. It is a proposal for ordering
future changes, not evidence that a release or environment is ready. The target
uses three CI tiers—PR confidence, staging integration, and nightly depth—and
five environment names: local, preview, staging, pilot-prod, and production.
Those names must be mapped to the existing configuration and live state before
any old profile, workflow, or Terraform namespace is retired.

## Current and target ownership

| Concern | Current authority and evidence | Target owner and boundary |
| --- | --- | --- |
| Repository shape | Root `Makefile` and `scripts/repo_doctor.py` orchestrate consistency across `services/`, `frontend/`, `apps/`, `packages/`, `infra/`, `config/`, `contracts/`, `docs/`, and `tests/`. `config/impact_graph.json` registers components, contracts, and deployables. | Keep the root command surface and one registered impact graph. Prune or move a tree only after imports, build consumers, deployment paths, and the impact/ownership maps have moved with it. |
| Normal PR decision | `config/verification_policy.yaml` fixes `ready_for_review` as the finalization event and `verification / disposition` as the blocking status. `.github/workflows/repo-consistency.yml` classifies impact, runs universal and selected workers, verifies selected build artifacts, then publishes that one terminal decision. | PR confidence remains the single normal PR authority. Preserve the check name and fail-closed aggregation while simplifying how checks are selected and executed. Draft pushes stay in the accumulation phase. |
| Check selection and evidence | `config/verification_router.yaml` declares domains, lanes, checks, and path rules; `config/test_suites.yaml` owns suite commands; `config/impact_graph.json` declares component dependencies and deployables; `scripts/verification_execution_plan.py`, `scripts/suite_worker.py`, and `scripts/aggregate_verification_evidence.py` turn these into typed worker evidence. | One impact decision and one suite registry feed the PR disposition. Keep unresolved paths, global changes, timeouts, missing evidence, and risk escalation fail-closed; remove duplicated path classification only after parity tests show equal or wider selection. |
| Supplemental PR evidence | Eleven workflows have `pull_request: types: [ready_for_review]`, including infrastructure, SDK, identity, frontend, and production-equivalent checks. `config/required_release_checks.yaml` marks `verification-disposition` as the normal merge blocker and records specialized release checks separately. A focused R5 overlap audit on 2026-10-04 found no safe workflow or suite removal: similar commands do not establish equivalent selection or evidence. | Domain workflows may provide specialized evidence at finalization. Their status must not silently become another ordinary PR blocker, and release-specific checks must retain their release applicability. |
| Main and nightly checks | `.github/workflows/repo-health.yml` runs `Main integration authority` on main pushes and deeper backend/ML/TypeScript work on schedule or dispatch. `.github/workflows/production-equivalent-ci.yml` runs a real Postgres/Redis lane on final PRs, main, schedule, or dispatch. `make ci-check` and `make release-gate` are broad commands. | Staging integration uses a verified immutable candidate and an explicitly authorized staging rehearsal. Nightly depth absorbs broad regression and production-equivalent coverage. Neither tier substitutes for the normal PR disposition or for live staging evidence. |
| Application delivery | `.github/workflows/deploy.yml` builds an immutable release, requires a successful check for the exact SHA, and uses the deploy role and environment gate for ECS mutation. `scripts/artifact_builder.py`, `scripts/delivery_orchestrator.py`, and `scripts/staging_state_machine.py` define candidate and resumable evidence contracts. | GitHub Actions remains the application mutation path. A candidate is bound to commit, artifact digest, profile, and source run; promotion and rollback must reference that identity and produce observed results. |
| Infrastructure promotion | `config/delivery_workflow_authority.yaml` assigns infrastructure/promotion ownership. `.github/workflows/infrastructure.yml` plans; `.github/workflows/terraform-promote.yml` is dispatch-only and applies the reviewed, checksum-bound binary plan at its source commit using separate plan/apply roles and environment approval. `config/deployment_operator_surface.yaml` keeps Kyber read-only. | One reviewed Terraform plan/apply path remains authoritative. Keep plan expiry, checksum, exact commit, state isolation, IAM inspection, budget/shape policy, and Kyber's read-only boundary. |
| Environment shape | `config/deployment_profiles.yaml` owns profile policy, cost, and staging lane; `config/runtime_deployment.yaml` owns ECS services and staging awake/asleep multipliers; `config/deploy_profile.yaml` is a local/cloud capability matrix; `config/deployment_profile_compatibility.yaml` validates frontend endpoints. `scripts/release/check_profile_parity.py` joins profile-stating surfaces. | Expose a small named environment interface while retaining these distinct policy, topology, capability, and endpoint facets. Derive duplicated profile names and cross-facet assertions from the canonical profile registry; do not discard a facet that enforces a different invariant. |
| Staging lifecycle | `.github/workflows/staging-lifecycle.yml` dispatches reviewed Terraform promotion for wake/sleep, rehearses migrations, smoke, load and rollback, and has an `always()` sleep phase. `.github/workflows/staging-business-hours.yml` schedules transitions; `.github/workflows/staging-ttl-guard.yml` independently enforces the awake lease and checks live ECS state. | One lifecycle interface may coordinate these workflows, but the independent TTL and residual-task fail-safe must remain. A missing lease, AWS error, or skipped cleanup is not proof of sleep. Keep rollback rehearsal and release evidence tied to the same candidate. |
| Documentation and contracts | `docs/reference/source-of-truth/repo_consistency_ownership.json` declares source categories and required derived surfaces. `scripts/docs_extract/run_all.py` generates `docs/_generated/`; `scripts/sync_docs.py` owns `docs/REPO-INDEX.md` and `docs/AUTOMATION.md`; `scripts/docs_drift.py` checks source-linked pages. Shared runtime contracts originate in `packages/shared/contracts/*.json` and their generators. | The reset changes ownership metadata and authored pages together with source. Generate only derived surfaces, review each stale source-linked page against `source_files`, then refresh only reviewed hashes. Keep contract generation and tenant/security validation in the selected and release gates. |

## Environment-name translation

| Target name | Existing repository expression | Transition rule |
| --- | --- | --- |
| `local` | `local` and `local-full` in `config/deployment_profiles.yaml`; Compose capability mapping in `config/deploy_profile.yaml`. | Keep both development depths until the local/full capability difference is expressed in one interface. |
| `preview` | `preview` is an ephemeral, cost-capped profile with TTL cleanup; `demo` is a separate seeded temporary profile. | Preserve explicit preview opt-in, tenant cleanup, and budget limits. Decide demo's product purpose separately; do not merge it into preview by spelling alone. |
| `staging` | `staging` is the Terraform/state profile. Its `full` and `pilot` deployment lanes share `state_namespace: staging`; `config/runtime_deployment.yaml` defines `awake` and `asleep`. | Preserve the full rehearsal and pilot staging overlay while delivery and state contracts are reviewed. |
| `pilot-prod` | No profile or Terraform state namespace with this name was found. The existing `staging.deployment_lanes.pilot` is customer-pilot staging; `production-lean` is the first-customer production profile. | Define pilot-prod tenancy, approval, artifact promotion, cost, rollback, and state identity explicitly. Determine whether it is a governed posture of `production-lean` or a separate profile only after reviewing Terraform state and live deployment. Never rename the staging `pilot` overlay into production. |
| `production` | `production-lean`, `production-scale`, and `enterprise-isolated` are distinct current profiles with different resource and isolation policy. `.github/workflows/deploy.yml` exposes `environment: production`. | Keep the profile distinctions behind the target production environment interface. Any alias must preserve security/isolation and cost rules and require exact candidate promotion. |

## Consolidation candidates and boundaries

1. **Path selection:** `config/verification_router.yaml` and `config/impact_graph.json` both enumerate broad source ownership. Make the Impact Graph the source of component/dependency/path facts and let the router retain lane/risk policy. Compare old and new selections over representative paths, global lockfiles, unknown paths, and contract consumers before removing either list.
2. **Authority declarations:** `config/verification_policy.yaml`, `config/required_release_checks.yaml`, `config/delivery_workflow_authority.yaml`, and `config/deployment_operator_surface.yaml` repeat some workflow/check names. Share stable authority identifiers and validate their references, while retaining distinct merge, release, mutation, and Kyber read-only policies. Keep `verification / disposition` stable for existing rulesets.
3. **Supplemental workflow selection:** finalized PR workflows repeat checkout/bootstrap and some tests already selected by `repo-consistency.yml`. The 2026-10-04 R5 audit found that the apparent Hardhat overlap is not safe to remove: direct contract-path selection through the canonical disposition is unproven, while the supplemental workflow also supplies Slither/SARIF evidence. SDK reruns add coverage thresholds and release checks; Aether/Kyber jobs cover different type, integration, or browser behavior. First prove `contracts/smart-contracts/**` selection end to end in the canonical plan; only then reconsider the repeated Hardhat command, keeping unique security evidence. Move common suite execution to `config/test_suites.yaml` workers only where runner, selection, and coverage parity are demonstrated.
4. **Profile vocabulary:** several profile YAML files and workflow inputs repeat profile names. Give `config/deployment_profiles.yaml` one canonical profile and environment mapping, then make compatibility, topology, capability, cost, and workflow validators check against it. `config/runtime_deployment.yaml` and Terraform still own deployable shape; a shared name registry must not flatten different resource or isolation policies.
5. **Staging shell logic:** `staging-lifecycle.yml` and `staging-ttl-guard.yml` each inspect ECS services and lease state, and the lifecycle workflow contains long inline AWS scripts. Extract shared, narrowly tested read/plan/verify helpers before shortening YAML. Keep TTL enforcement independent from the rehearsal's `always()` sleep path, and keep Terraform apply centralized in `terraform-promote.yml`.
6. **Authored CI docs:** `docs/reference/source-of-truth/VERIFICATION_SPINE.md` still describes old `build-artifact` and `selected-verification` job names and recommends `make ci-check` in its workflow narrative, while the current PR DAG names `plan-build`, `build-node`, `build-backend-image`, `candidate-verification`, and `publish-evidence`. Review that page and `docs/operations/CICD.md` when CI code changes; generated indexes and source hashes alone cannot correct the narrative.

## Controls that must survive the reset

- **PR and release truth:** one normal PR blocker; selected-suite evidence includes unresolved-path escalation, strict upstream result handling, typed aggregation, and immutable candidate verification. `make ci-check` stays broad evidence for trusted main, nightly, or explicit diagnostics; `make release-gate` and `scripts/production_status.py` remain required before production-readiness claims.
- **Security and tenancy:** do not weaken auth, RBAC, tenant isolation, consent, PII handling, secret boundaries, audit logs, schema/contract parity, or trust-boundary checks while moving a validator between tiers. `packages/shared/contracts/` stays the source of generated runtime twins; `config/test_suites.yaml` must retain the actual covering suites.
- **Delivery and cost:** GitHub Actions is the mutation operator; Kyber only reads readiness. Require environment approval, exact release checksum/SHA and image digest, reviewed plan checksum, separate IAM roles, profile shape and cost checks, migration/smoke evidence, and exact rollback identity. A policy-only or credentialless pass is not live deployment evidence.
- **Staging cleanup:** preserve the staging awake lease, zero desired count *and* autoscaling bounds for asleep, fail-safe sleep after rehearsal failures, the scheduled transition, independent TTL guard, live residual-task inspection, and actionable reporting when credentials or AWS reads are unavailable.
- **Documentation:** `docs/_generated/`, `docs/REPO-INDEX.md`, and `docs/AUTOMATION.md` have generators. Review source-linked docs before `make docs-generate-changed`; keep reviewed hashes scoped. Do not hand-edit generated output or restamp an unrelated backlog.

## Dependency order and concrete code changes

These are implementation slices for the orchestrator to integrate; none is
performed by this document. Preserve a draft PR through accumulation and use
focused checks within each slice. Finalization of the completed blueprint is
the point to regenerate/review docs and start the one normal PR authority.
The coordinating integration should also review PR #733's connector and
deployment guidance against these owners before updating any source-linked
page or finalizing the branch targeting `Development`.

| Order | Priority | Concrete change and dependency | Focused evidence before the next slice |
| --- | --- | --- | --- |
| 1 | P0 | Freeze current authority behavior in `tests/unit/test_verification_disposition.py`, `tests/unit/test_repo_consistency_workflow_authority.py`, `tests/unit/test_impact_graph.py`, and `tests/unit/test_delivery_workflow_authority.py`. Cover unknown paths, failed/missing worker artifacts, candidate mismatch, `ready_for_review`, dispatch-only apply, and a single blocking status. | Run the named unit tests, `scripts/validate_verification_policy.py`, `scripts/validate_impact_graph.py`, and `scripts/release/check_delivery_workflow_authority.py` with the project interpreter. |
| 2 | P0 | Add the target CI-tier vocabulary as a mapping over `config/verification_policy.yaml`, `config/verification_router.yaml`, and `config/test_suites.yaml`; keep the existing lane names and `verification / disposition` check until callers and ruleset evidence agree. `repo-consistency.yml` remains PR confidence; `repo-health.yml` and `production-equivalent-ci.yml` own main/nightly depth; staging integration is an explicitly invoked candidate rehearsal. | Validate execution-plan/schema and suite routing for backend, frontend, SDK, docs, lockfile, infrastructure, and unknown-file examples. Do not run the terminal disposition during accumulation. |
| 3 | P0 | Introduce an explicit environment-name mapping in `config/deployment_profiles.yaml` and its validator, without changing the existing Terraform profile/state keys. Make `check_profile_parity.py`, `check_staging_lane_contract.py`, delivery inputs, and docs distinguish staging `pilot` from proposed `pilot-prod`. Define pilot-prod approvals and rollback source before any production wiring. | Run profile parity, staging lane, topology, cost-policy, and plan-policy fixture checks. Require an inspected Terraform state/plan before any profile migration or apply. |
| 4 | P0 | Preserve current `deploy.yml` and `terraform-promote.yml` guards while extracting shared candidate identity and staging read/verify logic into `scripts/release/` or the existing `staging_state_machine.py`. Keep workflows as the execution adapters. | Run targeted candidate/state-machine, workflow-authority, lifecycle-policy, TTL, rollback, and plan-checksum tests, including failure and unavailable-credential cases. |
| 5 | P1 | Derive router component paths and authority references from the canonical registries, then remove verified duplicate declarations. Migrate supplementary workflow suites only after unique evidence and runner requirements are documented. | Compare pre/post impact and suite selections, validate execution contracts, and inspect workflow event/job names. |
| 6 | P1 | Shorten the staging workflows using shared helpers and review profile-facing docs. Update `docs/reference/source-of-truth/repo_consistency_ownership.json` when changed categories gain derived surfaces; regenerate generated/sync-managed docs, review every stale source-linked page, and refresh only reviewed hashes. | Run targeted lifecycle and documentation validators, `make docs-generate`, then `make docs-verify-idempotent` after reviewed source changes. The orchestrator performs the terminal authority after integration and review. |

With the project virtual environment installed, the first focused command set is:

```bash
.venv/bin/python -m pytest tests/unit/test_verification_disposition.py tests/unit/test_repo_consistency_workflow_authority.py tests/unit/test_impact_graph.py tests/unit/test_delivery_workflow_authority.py -q
.venv/bin/python scripts/validate_verification_policy.py
.venv/bin/python scripts/validate_impact_graph.py
.venv/bin/python scripts/validate_ci_execution_contracts.py
.venv/bin/python scripts/release/check_delivery_workflow_authority.py
.venv/bin/python scripts/release/check_deployment_operator_surface.py
```

For the environment/lifecycle slice, use the following focused checks against
fixtures and repository contracts before any credentialed plan or rehearsal:

```bash
.venv/bin/python -m pytest tests/unit/test_staging_state_machine.py tests/unit/test_staging_lifecycle_controls.py tests/unit/test_staging_lifecycle_delivery_evidence.py -q
.venv/bin/python scripts/release/check_profile_parity.py
.venv/bin/python scripts/release/check_staging_lane_contract.py --profile staging --deployment-lane pilot --check-runtime-wiring
.venv/bin/python scripts/release/check_delivery_topology.py
```

No current live AWS, hosted CI, Terraform state, or production rollback was
verified for this map. The table describes repository wiring and proposed
ownership; it makes no staging, merge, or production readiness claim.
