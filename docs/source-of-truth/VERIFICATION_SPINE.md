---
title: Verification and Release Spine
slug: source-of-truth/verification-spine
section: source-of-truth
visibility: I
audience: [dev, dev-senior, ops, architect]
status: active
since_version: "8.9.0"
source_files:
  - .github/workflows/repo-consistency.yml
  - config/verification_router.yaml
  - config/verification_policy.yaml
  - config/test_suites.yaml
  - config/ci_runtime_budgets.yaml
  - config/deployment_profile_compatibility.yaml
  - config/runtime_fallbacks.yaml
  - config/golden_journeys.yaml
  - contracts/delivery/change-plan.schema.json
  - contracts/delivery/release-candidate.schema.json
  - contracts/delivery/deployment-impact.schema.json
  - contracts/delivery/failure-envelope.schema.json
  - contracts/delivery/release-evidence-bundle.schema.json
  - contracts/delivery/migration-evidence.schema.json
  - contracts/delivery/staging-lifecycle-result.schema.json
  - contracts/delivery/staging-orchestration-state.schema.json
  - contracts/delivery/environment-resolution.schema.json
  - contracts/delivery/environment-capability-snapshot.schema.json
  - contracts/delivery/effective-iam-evidence.schema.json
  - contracts/delivery/effective-iam-comparison.schema.json
  - contracts/delivery/terraform-remote-inventory.schema.json
  - contracts/delivery/terraform-reconciliation.schema.json
  - contracts/delivery/hosted-adapter-request.schema.json
  - contracts/delivery/hosted-adapter-result.schema.json
  - contracts/delivery/artifact-closure.schema.json
  - contracts/delivery/profile-delivery-operation.schema.json
  - config/environment_requirements.yaml
  - config/staging_apply_iam_policy.yaml
  - config/terraform_resource_contracts.yaml
  - scripts/artifact_builder.py
  - scripts/delivery_contracts.py
  - scripts/change_plan.py
  - scripts/check_router.py
  - scripts/verification_disposition.py
  - scripts/lib/build_selection.py
  - scripts/lib/verification_router.py
  - scripts/lib/impact_graph.py
  - scripts/delivery_orchestrator.py
  - scripts/staging_state_machine.py
  - scripts/release/evidence_bundle.py
  - scripts/lib/test_suites.py
  - scripts/run_pytest_files.py
  - scripts/run_backend_tests.py
  - scripts/validate_makefile.py
  - tests/unit/test_repo_consistency_workflow_authority.py
  - tests/unit/test_verification_disposition.py
  - tests/unit/test_ci_runtime_budgets.py
  - scripts/validate_delivery_profiles.py
  - scripts/validate_delivery_registries.py
  - scripts/release/resolve_environment.py
  - scripts/release/discover_environment_capabilities.py
  - scripts/release/compare_effective_iam.py
  - scripts/release/terraform_reconciliation.py
  - scripts/release/hosted_delivery_adapters.py
  - scripts/release/artifact_closure.py
  - scripts/release/profile_delivery_contracts.py
  - scripts/release/check_hosted_delivery_contracts.py
  - scripts/release/release_candidate_adapter.py
  - scripts/release/check_environment_requirements.py
  - scripts/validate_verification_router.py
  - scripts/validate_verification_policy.py
  - scripts/validate_ci_runtime_budgets.py
  - scripts/release/check_deployment_operator_surface.py
  - config/delivery_workflow_authority.yaml
  - scripts/release/check_delivery_workflow_authority.py
  - tests/unit/test_staging_state_machine.py
  - config/impact_graph.json
  - config/telemetry_contracts.json
  - contracts/delivery/impact-graph-index.schema.json
  - contracts/delivery/telemetry-event.schema.json
  - scripts/impact_graph.py
  - scripts/lib/impact_graph.py
  - scripts/lib/telemetry.py
  - scripts/validate_impact_graph.py
  - scripts/validate_telemetry_contracts.py
  - tests/unit/test_impact_graph.py
  - tests/unit/test_telemetry_contracts.py
  - Backend Architecture/aether-backend/services/intelligence/routes.py
  - frontend/kyber/src/pages/deployment-readiness/deployment-readiness-page.tsx
  - Makefile
canonical_owner: platform@aether
estimated_read_minutes: 8
toc_depth: 3
---

# Verification and Release Spine

## Purpose

Aether uses a change-aware verification spine so ordinary work executes the
smallest check set justified by its affected domains. Normal pull requests have
one blocking authority, `verification / disposition`: the Impact Graph selects
the affected checks and BuildSelection artifacts after the universal-fast lane.
The legacy full `make ci-check` remains available for trusted-main, nightly, and
release evidence, but it is not a second blocking PR authority or a PR job.
Local or PR evidence proves only the selected lane; it never establishes
staging or production readiness.

The repository remains authoritative for test commands in
`config/test_suites.yaml`, routing policy in `config/verification_router.yaml`,
delivery contracts under `contracts/delivery/`, and stable developer commands
in the root `Makefile`.

The canonical backend suite uses `scripts/run_backend_tests.py`: ordinary
backend tests remain xdist-parallel, while the wall-clock performance
guardrails run in a serial pass after the behavioral tree. This keeps the full
tree covered without treating worker-scheduler contention as a product
latency regression.

## Workflow

1. Run `make doctor` before editing. It performs the dependency preflight
   before consistency work and rejects duplicate concrete Make targets.
2. Create a plan with
   `make change-plan CHANGE_ID=<id> TITLE='<title>' OWNER=<owner>`.
3. Run `make test-fast BASE=<git-ref>` for bounded local feedback.
4. Run `make test-pr BASE=<git-ref>` for the merge-safety selection.
5. Run `make docs-generate`, review source-linked drift, update only reviewed
   pages with `make docs-generate-changed`, prove idempotence, and run
   `make ci-check`
   before claiming repository completion.
6. Treat integration, regression, and release as progressively stronger lanes;
   none may be substituted for profile-specific deployment evidence.

Pull-request automation separates the implementation stages of one authority:
`classify-change` owns the deterministic impact decision, `build-artifact` owns
the selected build outputs, `selected-verification` executes the routed checks,
and `publish-evidence` publishes the single blocking disposition. The legacy
full-gate PR job was retired after representative hosted observation; the broad
`make ci-check` command remains available outside ordinary PR mergeability.
Publication runs even after an upstream failure so evidence is retained, but
fails closed unless all blocking stages succeeded.

Every router invocation emits JSON containing changed files, affected domains,
the minimum lane, the selected lane, and exact commands. Passing `--output`
persists that classification as evidence; `--execute` runs it. Selection does
not mutate the worktree. A developer may always request `fast` for bounded
local feedback; when the change requires a stronger merge lane the result sets
`followup_required: true` and retains that stronger `minimum_lane`. PR,
integration, regression, and release lanes cannot be downgraded.

The same result includes an immutable impact record with whether a global path
triggered, the inventory tests whose declared source or dependencies changed,
and the selected check ids. Suite selection is conservative at the registered
suite boundary: it selects whole canonical commands, not individual test
functions, and remains governed by the registry and full completion gate.

The Impact Graph v2 index extends that route result with registered components,
owned contracts, transitive consumers, deployable surfaces, and unresolved
paths. `scripts/impact_graph.py` emits a deterministic index and can compare
targeted nodes with a legacy broad scope. Hosted PR verification runs the index
with `--fail-on-unresolved` and emits validated local telemetry alongside it;
unresolved paths therefore block the workflow instead of silently reducing
verification. Telemetry remains operational metadata and is not a hosted
production exporter.

An unregistered changed path is an explicit `unknown_component` impact. The
router escalates such a change to the `integration` lane until a component,
contract, and deployable registration exists; uncertainty therefore cannot
silently reduce verification.

## Lane semantics

| Lane | Purpose | Typical scope |
| --- | --- | --- |
| `fast` | Warm local feedback | toolchain, metadata, directly affected suites |
| `pr` | Merge safety | fast plus affected contracts and registered suites |
| `integration` | Durable-system interaction | PR plus production-shaped dependencies |
| `regression` | Broad regression | integration plus the complete Python estate |
| `release` | Candidate disposition | regression plus the canonical release gate |

Except for explicitly bounded local `fast` evidence, the router refuses a
requested lane below a domain's declared minimum. Shared lockfiles and root
manifests are global paths and deliberately expand selection to every
registered domain.

## Delivery objects

`ChangePlan` records declared scope, contracts, risks, migrations, security and
deployment impact, required/deferred checks, and rollback notes. The creation
command supplies conservative defaults; the author must review and edit the
result before using it as PR evidence.

`ReleaseEvidenceBundle` is the canonical interoperable envelope for a release
candidate. Individual check states are `PASS`, `PASS_WITH_DEGRADATION`,
`BLOCKED`, `FAILED`, or `NOT_APPLICABLE`. A bundle cannot be treated as ready
when any blocking result remains. Artifact digests are mandatory SHA-256
identities so staging and promotion can refer to the exact same build. A
`ReleaseCandidate` also carries per-lockfile digests and a typed
`DeploymentImpact`, which makes the artifact closure explicit: consumers can
re-check the exact component files, dependency locks, commit, profile, and
rollback/approval implications before execution.

Candidate validation is relational as well as structural: the aggregate
artifact and lock digests must match their named maps, the deployment impact
must match the candidate's profile/domains/components, and migration impact
must agree with the migration version. A candidate that only has a valid JSON
shape but mismatched identity fields is blocked before staging.

Blocked or failed staging execution emits a typed `FailureEnvelope` alongside
the lifecycle result. It records the operation, stage, stable failure code,
retryability, and evidence reference while bounding and redacting command
detail. A missing candidate, incompatible profile, absent cloud identity, or
failed command therefore remains a first-class blocked/failed outcome instead
of an unexplained generic error.

When a workflow or operator supplies `STATE=<checkpoint.json>` to
`make deploy-staging`, `scripts/staging_state_machine.py` persists an atomic
checkpoint after each passing stage. Every resume revalidates the checkpoint
against the complete candidate identity (candidate id, commit, artifact
digest, and profile) and, when `ENVIRONMENT_RESOLUTION=<json>` is supplied,
the pre-mutation environment-resolution decision. It continues at the first
incomplete stage. Dry runs never mark stages complete and never create or
modify a checkpoint; non-dry execution verifies exact component files and
lockfiles immediately before the first staging command. Pure
promotion and rollback verifiers apply the same equality rule to both sides of
the transition; they do not apply infrastructure or imply cloud evidence.
Ephemeral demo/preview runs can also validate their cleanup policy, workflow
matrix coverage, canonical lease path, and injected TTL offline. Missing or
expired leases remain blocked, matching the fail-closed TTL guard.

`make build-artifact CANDIDATE_ID=<id> PROFILE=<profile>
COMPONENTS='backend=path frontend=path' LOCKFILES='package-lock.json'` records
digests for already-built component files; it does not itself compile, sign,
upload, or deploy those files. `make validate-delivery-profile
MANIFEST=<json>` validates deployable frontend identity/endpoint metadata and
any `ACTIVE_FALLBACKS`. `make validate-release-evidence
EVIDENCE_BUNDLE=<json>` validates disposition consistency and can write the
presentation-only Kyber projection when `KYBER_OUTPUT` is supplied. These
commands provide repository contracts and evidence validation, not evidence
that AWS or a product journey actually ran.

`make deploy-staging` (optionally with `STATE=<checkpoint.json>`),
`make staging-migrate`, and
`make test-golden-journeys` provide the repository-side orchestration boundary.
They emit structured evidence, preserve `DRY_RUN` as a distinct non-deployment
state, and fail closed when candidate compatibility, AWS identity, database
credentials, commands, or executable journeys are absent. They do not turn a
blocked local invocation into staging evidence.

Environment resolution is a separate pre-mutation authority. The canonical
requirements in `config/environment_requirements.yaml` are resolved against a
workflow-supplied capability record by `scripts/release/resolve_environment.py`.
Missing capabilities remain `UNKNOWN`; dependencies are closed before a
decision; and only explicitly degradable staging capabilities may produce
`PASS_WITH_DEGRADATION`. A degraded profile is named explicitly (for example,
`staging-degraded`) and never reports production equivalence. The resolver is
read-only with respect to AWS and Terraform, so its output can safely gate
planning or application delivery without fabricating cloud evidence. Use
`make resolve-environment PROFILE=staging CAPABILITIES='vpc=PASS ...'` for a
local decision/evidence record. The staging consumer recomputes the submitted
decision against this resolver and rejects contradictory capability statuses,
omissions, profiles, or equivalence claims.

The companion capability snapshot tool keeps discovery credential-safe:
offline fixtures are the default, Terraform plan shape is reported as
`UNKNOWN` rather than remote readiness, and live discovery requires both an
explicit credential source and an injected read-only adapter. Effective IAM
requirements can be compared with `scripts/release/compare_effective_iam.py`
against captured policy evidence without invoking AWS. Finally,
`scripts/release/terraform_reconciliation.py` compares desired plan entries,
Terraform state, and a complete remote inventory in a dry-run only; missing or
ambiguous ownership, identity drift, and plaintext secret material are
blocking outcomes. A deterministic Terraform-owned remote object that is
absent from state is classified as `UNMANAGED_ADOPTABLE` and produces
`RECONCILIATION_REQUIRED` with an explicit `import` action; it is never
recreated implicitly. These tools produce evidence for review, not live AWS
verification or mutation authority.

Hosted integration has one repository-owned adapter boundary. A GitHub
workflow may inject a short-lived OIDC/profile reference and return typed
capability, IAM, state, artifact, or runtime observations through
`scripts/release/hosted_delivery_adapters.py`; the contract rejects plaintext
secrets, mismatched operation/profile/candidate identities, and mutation from
read-only requests. Offline fixtures are deliberately unable to claim a live
hosted PASS. Artifact closure validation checks the exact candidate component
bytes and required archive entries, while provenance remains
`UNSIGNED_OR_UNVERIFIED` until a hosted registry/signature is supplied.

Profile-aware operation contracts cover preview, demo, staging, promotion,
rollback, and cleanup requests. Ephemeral profiles require a bounded TTL and
passing cleanup evidence; promotion requires exact staging evidence; dry-run
results cannot claim mutation. The operation telemetry event records queue,
setup, execution, cache, retry, and failure-category metadata without
credentials. These are the safe handoff contracts; they do not execute AWS,
GitHub, Terraform, tenant journeys, or production promotion locally.

PR CI compiles workspace packages once, archives the resulting `dist`
directories, and creates `release-candidate.json` bound to that archive, the
commit SHA, and dependency locks. The hosted release manifest is adapted to
the same candidate contract by `scripts/release/release_candidate_adapter.py`;
build, approved-release, deploy, and staging consumers reverify the candidate
and exact files before mutation. GitHub's workflow artifact is transport
between PR jobs, not a production registry, signature, or release promotion
claim.

## Intentional boundaries and remaining phases

The initial normalization does not relocate the existing test estate and does
not delete tests. The suite registry remains its inventory until per-test
runtime/flakiness data supports consolidation. Live integration and release
commands remain fail-closed on their declared dependencies. Profile preflight,
immutable artifact construction, migration rehearsal, five golden journeys,
and Kyber rendering should consume these contracts incrementally rather than
introducing another parallel readiness vocabulary.

The root Python suite executes every test file in an isolated process because
its Kyber and capability modules use process-global repositories. A bounded
worker pool parallelizes files without permitting cross-file state leakage.
This is an explicit deterministic constraint, not a silent retry.

## Blueprint completion backlog

The verification router is the control-plane foundation, not completion of the
full release-spine blueprint. The following work remains explicitly open:

| Blueprint capability | Current evidence | Remaining implementation |
| --- | --- | --- |
| Strictly read-only doctor | `--check` runs generators in a temporary Git mirror | Extend mutation regression coverage as new generators are registered; keep fixes explicit. |
| Per-test inventory | `config/test_inventory.yaml` and its validator establish ownership/dependency/quarantine metadata | Complete inventory coverage and collect measured runtime/flakiness/meaningful-failure history. |
| Changed-test selection | Paths and directly changed contract nodes select registered suites; contract consumers are named in the Impact Graph | Extend the contract-consumer map as new providers and consumers are added; keep selection-completeness tests current. |
| PR workflow authority | Enforced one-owner GitHub authority map validates workflow ownership and required command wiring; CI has explicit impact, affected-build, verification-disposition, and fail-closed publication stages | Branch protection requires only the stable `verification / disposition` check; the legacy full gate is retired from the PR path. |
| Immutable artifact | PR and hosted delivery paths share the adapter-backed candidate identity and verify exact files before staging/promotion | Add provenance/signing, durable registry upload, and external registry attestation. |
| Profile compatibility | Repository gate validates required frontend identity/endpoint fields and rejects insecure/placeholders for deployable profiles | Generate the manifest from real builds and bind it to the candidate digest and staging preflight. |
| Fallback governance | Audited profile-aware registry binds major fallback classes to implementation paths and blocks registered local fallbacks in staging/production | Resolve remaining candidate entrypoints with their owners, enforce selection at runtime across every deployable surface, and expose typed degradation in readiness. |
| Staging preflight and lifecycle | Orchestrator verifies candidate files, preserves non-mutating dry runs, validates environment decisions, and resumes only identity-bound checkpoints | Bind all ordered stage commands to credentialed disposable staging and exercise wake/sleep against AWS. |
| Migration contract | Versioned schema and orchestrator validate metadata, require `DATABASE_URL`, execute migration then validation, and emit fail-closed evidence | Run it against a real previous-schema staging baseline and add backfill/read-write/repair observations. |
| Golden journeys | Registry requires the five named, owned journeys and assertion metadata | Implement and execute those journeys against a clean baseline; the registry gate is not journey execution evidence. |
| Canonical evidence bundle | Validator enforces required checks and forbids READY with blockers/degradation; hosted candidate evidence is identity-bound | Aggregate real lane/deployment results, retain logs/traces, sign/publish bundles, and ingest them in Kyber. |
| Kyber readiness authority | Read-only endpoint projects a mounted, identity-bearing GitHub evidence record and reports `UNAVAILABLE` when none is mounted | Mount the signed aggregate bundle and add approval, deploy-health, rollback, and reconciliation fields without recomputing evidence client-side. |
| Debt removal and performance | Runtime-aware suite metadata, hard budgets, deterministic local JSON/JSONL p50/p95 reporting, and bounded parallel disposition runner are implemented | Persist hosted history, classify meaningful failures and flakes, subdivide broad suites, and tune caches/setup against measured critical-path data. |

## Expected testing impact

The lane interface changes *when* the whole repository is required, not whether
the full safety net exists:

* During an edit, `make test-fast BASE=<ref>` runs only toolchain and command
  metadata checks. It reports the stronger follow-up lane instead of expanding
  silently, so local feedback remains bounded.
* Before a PR, `make verification-disposition BASE=<ref> EXECUTE=1` runs the
  universal-fast checks and the suites registered for affected domains plus
  shared contract checks. A frontend-only change therefore avoids ML and
  infrastructure suites; an SDK/shared-contract change expands to its
  registered consumers. `make test-pr` remains the lower-level router command.
* Infrastructure changes require integration before merge. Regression remains
  broad and is intended for scheduled or explicitly requested execution.
* `make ci-check` remains the repository's broad consistency/regression gate,
  but it is no longer the normal PR disposition. The PR shadow was retired
  after representative hosted observation; trusted-main, nightly, and release
  workflows retain broad coverage.
* Release testing is not reduced: it adds profile preflight, exact-artifact
  deployment, migrations, activation, journeys, adversarial checks, and repair
  or rollback evidence. Local or PR success never implies deployment readiness.

Consequently, the immediate reduction is developer feedback scope and duplicate
manual command selection. The later PR-duration reduction depends on completing
the backlog rather than deleting coverage or weakening the canonical gate.
