---
title: Aether Architecture Reset Proof Ledger
slug: blueprints/architecture-reset/proof-ledger
section: blueprints
visibility: I
audience: [architect, dev-senior, ops, security]
status: experimental
since_version: 0.1.0
---

# Architecture reset proof ledger

**Baseline:** `Development` commit `17503aef9fa3a9515a029471796f1ee3510a5b2c`.
This ledger starts with no baseline or target runtime proof. Repo paths and
tests in the authority maps are candidate evidence, not completed proof.

For each row, record a command or procedure, commit, environment, fixture or
tenant, result, evidence location, owner, and recovery/rollback. Keep local,
hosted PR, staging, provider-backed, and release evidence separate. A failed
or unavailable result stays visible.

| Proof path | Baseline at reset start | New-path evidence required | Status |
| --- | --- | --- | --- |
| Tenant provision, auth, roles, and billing/pilot access | Not replayed for this reset | Scoped tenant creation, authorized/denied reads, entitlement and billing fail-closed states | Pending |
| Source connect, credential, consent/rights, and health | Not replayed | Source-specific connection and data-rights admission, honest waiting/degraded/revoked states | Pending |
| SDK/provider/import event acceptance | Not replayed | Tenant/source-scoped idempotent acceptance, duplicate/corrupt rejection, source identity preserved | Pending |
| Raw evidence and replay identity | Not replayed | Durable evidence, provenance, version, event/ingestion time, retention and replay key | Pending |
| Normalization and classification | Not replayed | Canonical typed fact; source versus campaign distinct; missing/empty/zero and late-event semantics | Pending |
| Identity/entity decision | Not replayed | Merge, no-merge, review, cross-namespace collision, correction and audit evidence | Pending |
| Governed graph mutation/query | Not replayed | `MutationIntent` gateway, tenant isolation, idempotency, partial failure and history/diff | Pending |
| Journey, touchpoint, attribution, and value | Not replayed | Versioned computation with evidence, time window, correction, and distinct attribution credit | Pending |
| Profile, Journey, Graph, Lens, and Value views | Not replayed | Populated, empty, loading, error, partial/stale, denied, and explanation states | Pending |
| Governed action and measured outcome | Not replayed | Eligibility, confirmation/approval, audit, receipt, outcome and failure recovery | Pending |
| Quarantine, dead letter, replay, and backfill | Not replayed | Authorized tenant-scoped repair from retained evidence with before/after diff | Pending |
| Bronze/Silver rollback, source-tag audit, and evidence lifecycle | Not replayed; code review found hard-delete-by-tag paths without tenant predicates and a 10,000-row query cap | Same-tag cross-tenant isolation, exact affected-row accounting, actor/reason/correlation record, authorized audit scoping, and explicit erasure behavior | Tenant predicates, tenant-authenticated audit/import propagation, all-tier preflight, and fail-before-delete cap behavior are implemented in consolidated PR #734 and focused locally tested; durable correction/erasure lifecycle and audit receipts remain pending |
| Operator diagnosis and runbook | Not replayed | Kyber source/event/identity/graph/billing/readiness inspection without alternate write authority | Pending |
| Staging deploy, wake, smoke, and sleep | No verified snapshot recorded for this reset | Immutable release, plan/policy review, awake lease, smoke, rollback, and sleep evidence | Pending |
| Design-partner source proof | None recorded for this reset | One permitted real source and tenant traverses the proof path with recoverable failures | Pending |
| Normal PR authority | Not run during accumulation | `verification / disposition` terminal result after `ready_for_review` | Pending |
| Release claim | Not requested or run | Canonical release gate and `scripts/production_status.py` scorecard plus live operational evidence | Pending |

## Recorded local baseline evidence

| Date | Revision and environment | Command | Result | What it establishes | What remains unproved |
| --- | --- | --- | --- | --- | --- |
| 2026-10-04 | `Development` `17503aef9fa3a9515a029471796f1ee3510a5b2c`, detached local baseline checkout, project virtual environment | `PYTHONPATH=services/backend /Users/osazehunt/AETHER/.venv/bin/python -m pytest tests/unit/observation/test_golden_cross_path_fixture.py -q` | 1 passed in 2.84s | The existing fixture observes one SDK batch event, its Bronze replay, and the legacy event-alias path on the canonical bus with original event time and no second Bronze row on replay. | This uses local in-memory stores and a fake producer. It does not exercise a real provider, Silver/identity/graph, persistent retry, tenant authorization, staging, or a deployed UI. |
| 2026-10-04 | Same detached baseline and interpreter | `PYTHONPATH=services/backend /Users/osazehunt/AETHER/.venv/bin/python -m pytest services/backend/tests/identity/test_late_binding_end_to_end_proof.py services/backend/tests/ingestion/test_bronze_hash_chain.py -q` | 7 passed in 14.69s | Focused identity continuity and Bronze chain behavior pass at the baseline commit. | The tests do not join a real provider delivery to a customer-visible graph view. |
| 2026-10-04 | Same detached baseline and interpreter | `PYTHONPATH=services/backend /Users/osazehunt/AETHER/.venv/bin/python -m pytest tests/unit/graph_gateway/test_mutation_gateway.py -q` | 18 passed in 14.47s | Focused gateway mode, mutation, and ledger behavior passes at the baseline commit. | This does not establish that every live writer uses enforced mode or that a durable ledger/projector transaction survived failure. |

## Recorded local follow-up evidence

| Date | Revision and environment | Command | Result | What it establishes | What remains unproved |
| --- | --- | --- | --- | --- | --- |
| 2026-10-04 | Consolidated PR #734 at `ade877f47`; explicit local environment and project virtual environment | `AETHER_ENV=local PYTHONPATH=services/backend /Users/osazehunt/AETHER/.venv/bin/python -m pytest tests/unit/observation/test_ingest_replay.py -q -n0` | 14 passed | Hosted live publish is refused unless explicitly local and in-memory; process-local run IDs are tenant/request scoped and scope collisions or overlapping calls are rejected. | In-memory Bronze and fake producer only. No durable checkpoint, current-rights re-admission, crash recovery, multi-process idempotency, hosted publish, provider-backed path, or staging proof. |
| 2026-10-04 | Consolidated PR #734 at `ade877f47`; project Python environment | `PYTHONPATH=services/backend /Users/osazehunt/AETHER/.venv/bin/python -m pytest services/backend/tests/unit/test_lake_tenant_isolation.py services/backend/tests/integration/test_read_completeness.py services/backend/tests/identity/test_sdk_import_identity_candidates.py services/backend/tests/data_exchange/test_import_envelope.py -q -n0` | 65 passed | Focused lake, route/read, identity-candidate, and import-envelope behavior passes, including tenant scope propagation and same-tag cross-tenant isolation. | Local fixtures do not prove production database concurrency, durable correction/erasure receipts, governed erasure behavior, or hosted/staging operation. |
| 2026-10-04 | Same consolidated PR #734 revision and environment | `PYTHONPATH=services/backend /Users/osazehunt/AETHER/.venv/bin/python -m pytest tests/unit/test_import_commit.py tests/unit/test_dune_promotion.py -q -n0` | 22 passed | Import rollback preflight refuses an over-cap source tag before graph revocation or vertex cleanup; the existing Dune promotion tests pass. | No cross-tier database transaction/locking proof, durable lifecycle receipt, provider-backed test, hosted PR authority, or staging evidence. |
| 2026-10-04 | Same consolidated PR #734 revision; frontend workspace | `npm test --workspace=frontend/aether -- --run src/test/component/app-shell.test.tsx src/test/unit/activate-page-route-state.test.tsx src/test/unit/identity-activation-dashboard.test.tsx src/test/unit/identity-review-queue.test.tsx` and `npm run typecheck --workspace=frontend/aether` | 24 tests passed; typecheck passed | The updated Aether navigation and activation states pass their focused component/unit tests and typecheck. | No browser/device end-to-end, design-partner, or hosted deployment proof. |
| 2026-10-04 | Consolidated PR #734 at `956dc28d9` plus the final Web3 route-permission correction; project Python environment | `PYTHONPATH=services/backend /Users/osazehunt/AETHER/.venv/bin/python -m pytest services/backend/tests/web3/test_classifier_graph_gateway.py -q -n0`; `/Users/osazehunt/AETHER/.venv/bin/python -m pytest tests/unit/graph_gateway/test_mutation_gateway.py tests/unit/graph_gateway/test_graph_history_replay.py -q -n0`; `/Users/osazehunt/AETHER/.venv/bin/python scripts/validate_graph_write_paths.py` | 10 classifier gateway/route tests passed; 34 gateway/history tests passed; path validator reports three remaining direct writer call sites frozen in the allowlist | The Web3 observation and migration paths now submit tenant-scoped mutations through `GraphMutationGateway`; graph mutation routes enforce authenticated `write` permission, registry seeding enforces `admin`, and the validator prevents unreviewed direct-writer growth. | This does not make gateway enforcement universal: remaining direct writers, gateway mode configuration, provider-backed event identity, per-log Web3 identity, durable ledger/projector atomicity, and hosted/staging operation remain unproved or pending. |
| 2026-10-05 | Consolidated PR #734 local Chromium with route fixtures and built local SDK packages | `PLAYWRIGHT_OUTPUT_DIR=/tmp/aether-734-ui-evidence npm run e2e --workspace=frontend/aether -- --project=chromium --reporter=line src/test/e2e/identity-continuity.spec.ts`; `PLAYWRIGHT_OUTPUT_DIR=/tmp/aether-734-navigation-evidence npm run e2e --workspace=frontend/aether -- --project=chromium --reporter=line -g 'Data Exchange settings: capability summary'` | 5 identity continuity cases and 1 Aether navigation/Settings case passed; [navigation screenshot](evidence/aether-navigation-fixture.png) captured | The browser exercises authenticated tenant-facing identity routes and the Aether navigation, including disabled target destinations, against synthetic network fixtures. The repaired harness uses the authenticated fixture tenant as graph scope and the current capability endpoint. | Synthetic responses and a local test profile only; this is not a live backend, staging deployment, design-partner session, or full source-to-outcome proof. |
| 2026-10-05 | PR #734 `6f3df9013`, local in-memory backend, project Python environment | `PYTHONPATH=services/backend /Users/osazehunt/AETHER/.venv/bin/python -m pytest tests/unit/observation -q -n0` | 133 passed, 3 existing Pydantic field-name warnings | Replay occurrence bounds are compared as UTC instants, invalid or reversed bounds fail before publish, unknown original times are excluded from bounded runs, and the golden fixture exercises the explicit local/in-memory guard. | No hosted replay, durable checkpoint, current-rights re-admission, provider-backed input, or multi-process delivery identity. |
| 2026-10-05 | PR #734 `6f3df9013`, local graph and route fixtures | `cd services/backend && /Users/osazehunt/AETHER/.venv/bin/python -m pytest -q -o addopts='' tests/unit/test_onchain_action_recorder_gateway.py`; same interpreter and options for `tests/resolution/test_legacy_routes_fail_closed.py`; `/Users/osazehunt/AETHER/.venv/bin/python scripts/validate_graph_write_paths.py` | 9 on-chain and 3 legacy-route tests passed; validator reports one remaining direct writer | On-chain action intents carry tenant scope and stable action/source identity, rejected outcomes fail before event publication, and local graph reads are tenant scoped. The dead lake writer is removed; unsafe mounted legacy cluster/approval/batch routes return 503. | The remaining legacy repository is unsafe if reactivated; on-chain intents are not atomic as a group, bounded graph scans can return unavailable, historical unscoped on-chain data needs a live data audit, and no Neptune/Postgres or staging path was tested. |
| 2026-10-05 | PR #734 `6f3df9013` and generated-index follow-up `a41026ea5` | `make docs-generate GATE_PY=/Users/osazehunt/AETHER/.venv/bin/python`; `make docs-check GATE_PY=/Users/osazehunt/AETHER/.venv/bin/python`; `CI=1 GITHUB_BASE_REF=Development /Users/osazehunt/AETHER/.venv/bin/python scripts/validate_consistency_ownership.py` | Docs generation and final docs-only check passed (10/10); 687 source-linked docs clean; ownership passed for 84 changed files and 3 categories | The changed authored/API/source-linked pages and generated repository index match the committed source snapshot. | This is documentation/ownership consistency only, not the terminal `verification / disposition`, full CI, or a live runtime proof. |

This baseline test supplies a comparison point for a later path cutover. A
single local fixture is not an old/new equivalence decision. Record the target
revision and repeat the same fixture plus durable and adverse-path evidence
before retiring any intake or replay authority.
The backend and root `tests/` trees have conflicting `tests.conftest` import
names when collected in one invocation in this checkout, so the latter two
baseline commands were run separately. The combined invocation failed during
collection and is not counted as a test result.

## Cutover decision record

Before retiring an old path, fill in a dated row with the old owner, new owner,
consumer list, compatibility alias, data migration, old/new comparison,
rollback action, and evidence link. A directory move without that record is
not a completed authority migration.

| Date | Path or authority | Old owner | New owner | Compatibility and data handling | Evidence | Rollback | Decision |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Pending | No cutover approved | — | — | — | — | — | Pending |
| 2026-10-05 | Unused lake graph mutation module | Unregistered `services/backend/services/lake/graph_mutations.py` | Existing active graph projectors and gateway paths, without a replacement for the removed wallet/social/governance job | Exact-symbol/runtime search found no caller or job registration; no data migration was performed. The old module read Silver with `tenant_id=None` and wrote directly to graph. | PR #734 `6f3df9013`; graph path validator reports one direct writer | Restore only after a tenant-scoped gateway implementation and consumer/equivalence review; do not re-enable the old unscoped module | Code deletion accepted; lake-to-graph wallet/social/governance rebuild remains unavailable |
| 2026-10-05 | On-chain action recorder | Direct `GraphClient` writes with unscoped IDs and process-local action list | Tenant-qualified `ActionRecorder` intents through `GraphMutationGateway` and scoped graph reads | Existing route paths remain; `chain_id` is an optional contract-read selector. A stable `action_id` or transaction hash is now required. Historical unscoped graph records are not migrated by this code. | PR #734 `6f3df9013`; 9 focused tests, including real local GraphClient projection | Keep `IG_ONCHAIN_LAYER` disabled if historical data or graph-mode behavior is unverified; restore an earlier revision only with tenant-isolation review | Code path migrated; live data and deployment cutover pending |
| 2026-10-05 | Legacy resolution graph routes | Mounted cluster, approval, and batch paths over unscoped graph repository | Fail-closed HTTP 503 while the separate canonical tenant-scoped identity path remains active | URLs remain mounted. Pending, audit, reject, and config routes continue; old consumer and batch job are not registered in runtime. | PR #734 `6f3df9013`; 3 focused route tests and runtime-caller audit | Do not restore old graph routes without tenant-qualified lookup/write migration and cross-tenant tests | Temporary route shutdown accepted; tenant-safe compatibility implementation pending |
