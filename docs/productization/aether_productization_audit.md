---
title: AETHER Productization Audit
slug: operations/productization-audit
section: operations
visibility: I
audience: [architect, ops, exec]
status: stable
since_version: "8.9.0"
source_files:
  - scripts/production_status.py
canonical_owner: platform@aether
estimated_read_minutes: 15
toc_depth: 3
last_synced_commit: "00fdcbc"
---

# AETHER Productization Audit

**Audit date:** 2026-07-18 (platform v8.12.0)
**Live counterpart:** `make production-status` (`scripts/production_status.py`) is the
machine-checkable version of this audit. This document is the dated narrative
snapshot; the script is the routine. If they disagree, re-run the routine and
update both.

---

## 1. Executive Summary

AETHER is **pre-production: release-shaped, gated by a short list of known
blockers** — not an MVP, and not yet a system that should accept paying
production traffic.

What the June 2026 audit found:

- The platform's core surfaces — backend API (65+ routers), identity
  resolution, Profile 360, graph layer (Neptune + in-memory fallback),
  SDK fleet health/drift/remote-config, Kyber operator console, ingestion,
  consent/DSR, billing — are **implemented with real data paths and tests**,
  not stubs. The 14 formerly-stubbed Profile 360 intelligence endpoints were
  wired to Gold-tier repositories in v8.9.0 (PR #276).
- The repo's **guardrail system is unusually mature**: `repo-doctor`
  orchestrates version alignment, generated-doc regeneration, frontmatter
  validation, source-linked docs drift (strict), contract/event/consent
  cross-validation, SDK release alignment, npm build/test, and both Python
  test suites. CI enforces all of it plus JS coverage thresholds.
- The gaps are **operational and go-to-market, not architectural**: tenant
  onboarding UI, provisioned infrastructure + secrets, trained ML artifacts,
  external smart-contract audit, real (non-mocked) connector API calls, a
  governed Dune feeder pipeline, and load-test baselines.
- **Profile 360 is now 5/5** — credit-data access is enforced via a hard
  `'credit'` consent gate at the API route level (HTTP 403 on denial, not a
  soft empty-envelope fallback), and a dedicated 25-test unit suite covers
  aggregator dimensions, quality scoring, tenant isolation, pagination shape,
  and the consent gate itself.
- **Security / compliance is now 4/5** — `VM-dependency-audit` and
  `VM-secret-scan` are now CI-gated mandatory steps in the TypeScript job:
  `npm run security:secrets` (fail-closed, exits 1 on any high-confidence
  secret) and `npm run security:deps` (advisory — prints audit report, never
  blocks).  14/18 controls are now implemented; the remaining 4 (IR, PR, PT, TM)
  are documented-only and do not require code changes.

What this audit pass changed (June 2026):

- Fixed `make test` / bare `pytest` (conftest module collision between
  `tests/` and `ML Models/aether-ml/tests/`); suites now run separately
  everywhere, matching what CI and `repo_doctor.py` already did.
- Reviewed and fixed the 6 stale source-linked docs flagged by
  `docs_drift.py --strict`: documented the previously-undocumented Economic
  Value Service endpoints in `BACKEND-API.md` and
  `KYBER-ECONOMIC-OBSERVABILITY.md`, and recorded the economic-identity
  materialization fix in `X402_AUDIT_REPORT.md`.
- Added the **production status routine** (`scripts/production_status.py`,
  `make production-status`, `make release-gate`) and a 12-hour scheduled
  workflow (`.github/workflows/production-status.yml`, no secrets required).
- Added this audit as a repo artifact.

What the July 2026 staging-capstone pass changed (PRs 1–6):

- Added a **credentialless provider certification plane** (new scorecard area,
  4/5): a `CredentialReadiness` truth model (8 ranked states) plus a
  `ReadinessDimensions` record whose validators refuse to infer `production_ready`
  from structure. `build_capability_matrix()` resolves every provider's state
  **from source** into `docs/_generated/adapter-certification-matrix.json`, and
  `make credentialless-certification-strict` gates the floor. The plane is wired
  into `production_status.py` as a live consistency check.
- **All 19 first-release providers now resolve to `CREDENTIAL_WAITING`** —
  derivatives ×4, interop ×7, payments ×5, stablecoin-chain ×2, communications ×1 — code-complete +
  infra-defined + credential-gated, none `SCAFFOLDED` and none `PARTNER_LIVE`.
  This is an honest, evidence-backed advance from the earlier mix of
  `CREDENTIAL_GATED`/`SCAFFOLDED`, **not** a production claim. The economic domain
  scores are unchanged (stablecoin/derivatives/interop/payments at 3, card-linked
  at 2) — credential-waiting is pre-production, not release-ready.
- **Durable delivery/outbox + security correctness:** reward delivery runs on a
  durable outbox with SSRF-checked-before-enqueue and the "never delivered
  without a receipt" invariant (timeout→retry→dead-letter→redeliver).
- **Supervised agent real seam (PR6):** `commit_approved_mutations` /
  `rollback_mutation` enforce approval invariants, record partial failures loudly
  per-mutation, preserve graph-write errors as `failed_commit`, and mark a
  rollback that could not restore state `rollback_repair_required` (never a false
  clean undo). Stale runs are swept and replayable. `graph mutation safety` stays
  4/5 (hosted mode still needs durable storage).
- Added a **credentialless load/chaos/recovery suite** (`tests/chaos/`, 41 tests)
  that runs inside `pytest tests/`: provider rate-limit/timeout, duplicate-webhook
  storm, out-of-order, worker/consumer restart, Redis/ClickHouse interruption
  (mocked), graph write failure, RPC failure, chain reorg, WebSocket disconnect,
  cursor drift, reward-delivery timeout, agent stale run, partial mutation commit,
  and rollback failure. External-service legs are covered as in-process fault
  models and clearly marked; the live legs remain staging work.
- Added the **staging-capstone operating guide set** (`docs/productization/
  staging-capstone/`) and nine domain runbooks (payment-rails, card-linked,
  stablecoin-observer, derivatives-stream, interop-observer, reward-delivery,
  EVM/SVM deploy-emergency, agent-runtime-mutation-review). The EVM/SVM runbooks
  reference the existing audit packages rather than duplicating them.

What the 2026-07-23 semantic operational-hardening pass changed (PR8):

- Added a **semantic intelligence** scorecard area at an honest **2/5
  (partial/pilot)**. The pipeline is real — fail-closed provider abstraction
  (production mode without credentials abstains via `DisabledProvider`, never a
  keyword fallback), durable Silver/Gold fact store with in-memory fallback,
  idempotent shared write path, eligibility routing, consent fail-closed,
  dry-run replay, review queue, DSR erase/restrict — but no production model
  provider has been validated, the durable store has not run against real
  Postgres in staging, and no live traffic has flowed. Pilot-grade, not
  production.
- Registered the semantic pipeline on the reliability surface: a
  `semantic_intelligence` service definition, an
  `event_to_semantic_classification` pipeline, the existing
  `docs/runbooks/semantic-sentiment/semantic-sentiment-operations.md` runbook as
  `rb_semantic_classification_degraded`, and 3 SLOs (abstention rate ≤0.25,
  classify latency p95 ≤1s, review-queue depth ≤50) keyed to the Prometheus
  series emitted by `services/semantic_intelligence`
  (`aether_semantic_observations_{classified,abstained,quarantined}_total`,
  `aether_semantic_classify_latency_ms`, `aether_semantic_review_queue_open`,
  `aether_semantic_replay_jobs_active`).
- Added an `aether_semantic_health` Prometheus alert group and a
  `semantic-pipeline` Grafana dashboard, both pinned to the contracted metric
  names by `tests/unit/test_semantic_observability_assets.py` so alerts and
  panels can never drift onto series nothing emits.
- Extended `tests/chaos/` with `test_semantic_pipeline.py`: model-unavailable →
  fail-closed abstention (never fabricates), replay dry-run writes zero
  semantic facts, and durable-store restart round-trip with idempotent
  re-delivery.

## 2. Classified Findings

Classification legend: `release-blocker` | `pre-production-blocker` |
`scale-blocker` | `docs-drift` | `test-drift` | `nice-to-have`.

| # | Finding | Class | Status |
|---|---------|-------|--------|
| 1 | 6 source-linked docs stale after v8.9.0 merges (`BACKEND-API`, `KYBER-ECONOMIC-OBSERVABILITY`, `X402_AUDIT_REPORT`, `ECONOMIC-VALUE-FRAMING`, `COMMERCE-OPERATOR-RUNBOOK`, `AGENTIC_COMMERCE_BUILD_SPEC`) | docs-drift | **Fixed** — content reviewed/updated, stamped |
| 2 | `make test` and bare `pytest` broken: combined invocation of both suites hits `ImportPathMismatchError` | test-drift | **Fixed** — suites run separately; documented in `pyproject.toml` |
| 3 | No single production-status routine; readiness claims scattered across `PRODUCTION-READINESS.md`, `PRODUCTIZATION.md`, `PRODUCTIZATION-CHECKLIST.md`, `AGENT-LAYER-PRODUCTION.md`, `scripts/compliance/readiness.py` | nice-to-have (was drift risk) | **Fixed** — `scripts/production_status.py` is now canonical |
| 4 | Tenant self-serve onboarding UI missing (manual SQL + API calls) | release-blocker | **Fixed** — 3-step signup (email→OTP→API key reveal), plan selection, SSO, billing portal, API key mgmt, usage dashboard, implementation checklist all shipped in PR #288 |
| 5 | Smart contracts (EVM/Solana/NEAR/Cosmos rewards) have **no external security audit** | release-blocker | Open — do not deploy to mainnet with real funds |
| 6 | Production infrastructure not provisioned; production secrets not configured; ML artifacts not trained | release-blocker / pre-production-blocker | Open — external prerequisites per `PRODUCTION-READINESS.md` |
| 7 | Agent Layer hosted mode requires durable storage (in-memory fallback blocked in hosted modes) | release-blocker (agent GA only) | Open — per `AGENT-LAYER-PRODUCTION.md` |
| 8 | Connector provider pulls are credential-gated TODOs (framework real, API calls mocked) | pre-production-blocker | **Fixed (Wave 1)** — 14 production-shaped connectors with real API calls (Shopify, Stripe, HubSpot, Salesforce, Klaviyo, PostHog, GA4, Jira, Linear, Zendesk, Intercom) enabled when vault secret present; ConnectorService.sync() now writes pulled NormalizedEvent records to BronzeRepository('connector_events') — vault→pull→Bronze ingest path complete and E2E tested (test_connector_ingest.py). Slack outbound channel-map routing E2E tested (test_slack_notify_e2e.py). Minor gap: no staging validation with live provider credentials. |
| 14 | Agentic x402 lifecycle events + agent graph not productized across SDK/backend | pre-production-blocker | **Fixed** — 33 lifecycle events (14 x402 + 19 agent) added to shared types, web/Android/iOS SDKs, backend ingestion validator; tenant isolation enforced in 5 repository methods; 4 Kyber operator agentic endpoints added; production status area agentic_x402_productization scored 4/5. |
| 9 | Dune is a read-only provider, but no governed Bronze→Silver→Gold feeder with per-row provenance/freshness gates exists | pre-production-blocker | **Partially fixed** — DuneConnector added (real API via api.dune.com/api/v1, credential-gated, per-row provenance: query_id/execution_id/row_index). PromotionService gates Silver promotion on freshness, null-rate, required-field, and entity_id checks; each row gets quality_score + per-check failure reasons. POST /v1/lake/promote + GET /v1/admin/feeders Kyber route added. Remaining: staging validation + scheduled polling worker. |
| 10 | Graph-level drift/contamination scoring partial: data-quality module feature-flagged, operational-intelligence overlay scores are placeholders | pre-production-blocker | **Fixed** — graph_overlay() now computes real trust/risk/confidence IntelligenceScore objects per node using IntelligenceQualityService (cluster_community_drift, merge_rate, split_rate, orphan_rate). _build_overlays() populates IntelligenceDimension lists per overlay type (risk/trust/health/identity/attribution). traverse_graph() also uses real overlays. Placeholder summary replaced with live metric values. |
| 11 | No load baselines recorded; Locust harness exists but is not exercised in CI | scale-blocker | **Partially fixed** — locustfile extended with `/v1/batch` + `/sdk/identity/resolve` tasks and thresholds; `scripts/load_smoke.py` + `make load-smoke` added. Staging baselines not yet recorded. |
| 12 | Neptune capacity/cost and identity-merge throughput unvalidated at scale | scale-blocker | Open |
| 13 | Slack outbound notification channel-mapping/templates not productized (ingest connector + connection test are real) | nice-to-have | **Fixed** — per-tenant Slack channel mapping by severity (slack_channel_map), opt-in controls (operator_review_required, quiet_hours, rate limits), Slack OAuth, and real outbound (chat.postMessage + Block Kit + retries) all confirmed present in notification_intelligence. |
| 14 | A6 reward enablement: reward backend was in-memory (no durability, no tenant_id, no idempotency, no fraud/consent gating, only EVM rail) | feature | **Fixed** — full durable backend shipped (7-table PostgreSQL schema, 37-endpoint API, policy engine with 12 evaluation gates, 5 rail adapters + 5 beta stubs, EIP-712 proof hardening, oracle key safety, no-custody model enforced, 1,500+ line test suite, 5 source-of-truth docs, 6 frontend pages). PR #313. |

Findings that prior audits claimed and this audit **verified as resolved**:
infrastructure stubs replaced with real Redis/Postgres/Neptune/Kafka clients;
real crypto (secp256k1/keccak256); tenant isolation enforced at repository
level with dedicated tests; Kyber admin routes permission-guarded and never
mounted on tenant-facing routers; Slack correctly modeled as an
action/messaging connector and Dune as a read-only analytics provider (the
two taxonomies are not conflated).

## 3. Readiness Scorecard

Rubric: 0 absent · 1 stub/scaffold · 2 partial/pilot · 3 pre-production ·
4 release-ready with minor gaps · 5 production-ready and scale-ready.
(Canonical source: `scripts/production_status.py`; run
`make production-status` for the live version with evidence paths.)

| Area | Score |
|------|-------|
| backend/API | 4 |
| SDKs | 4 |
| identity resolution | 4 |
| Profile 360 | 5 |
| Neptune relationships (H2H/H2A/A2H/A2A) | 4 |
| graph mutation safety | 4 |
| graph health / drift detection | 4 |
| Kyber (operator console) | 4 |
| customer frontend (tenant app) | 5 |
| connectors (BYOK / source) | 4 |
| Slack / action notifications | 4 |
| Dune / data-lake feeders | 4 |
| smart contracts / proofs / rewards | 4 |
| security / compliance | 4 |
| agentic_x402_productization | 4 |
| measurement / attribution | 4 |
| measurement integrity plane | 4 |
| tenant import engine | 4 |
| campaign intelligence | 5 |
| CI / tests | 4 |
| docs | 4 |
| deployment / cloud readiness | 3 |
| scale readiness | 3 |
| provider certification plane | 4 |
| stablecoin intelligence | 3 |
| derivatives intelligence | 3 |
| interoperability intelligence | 3 |
| payment rail observability | 3 |
| semantic intelligence | 2 |
| card-linked payment rails | 2 |

**Overall: ~3.77/5 — pre-production** (canonical live figure from
`make production-status`; this table is a dated excerpt of the full scorecard).
A W3C trace-context seam (correlation-id + traceparent propagation across the
jobs platform, no-op unless `AETHER_OTEL_ENABLED`) landed with a matching
declared pre-production blocker: no OpenTelemetry SDK/exporter is integrated,
and the seam is explicitly not claimed as observability coverage.
The 2026-07-23 pass added **semantic intelligence at 2/5 (partial/pilot)** —
a real fail-closed pipeline with reliability/SLO/alerting surfaces registered,
held at 2 because no production model provider, staging durable-store run, or
live traffic exists — which moved the overall average down from ~3.83
(honest denominator growth, not a regression in any existing area).
Profile 360 and customer frontend are now 5/5. Security / compliance advanced to
4/5 with VM dependency-audit and secret-scan controls CI-gated. Customer
frontend reached 5/5 with Playwright E2E suite (5 scenarios, CI-gated via
e2e-tenant job). Dune feeder AETHER_ENV guard replaced with config-driven
DUNE_BACKEND flag. Two subsystems land this cycle at 4/5: the **Measurement
Integrity Plane** (immutable results with value_state so a metric is never a bare
0 on missing data, supersession-only mutation + restatement chain, in-code metric
registry, Wilson/bootstrap uncertainty, `/v1/measurement/*` read surfaces — held
at 4 pending an end-to-end Campaign360 threading and production traffic) and the
**Tenant Import Engine** (create → analyze → map → validate → approve → commit to
Bronze + graph with `import_commit_id` lineage on the durable jobs platform, with
reversible rollback/replay, a Kyber operator console, and an IMPORT_FAILURES
runbook — held at 4 pending a tenant UI, a Silver import projector, and
production traffic). Payment rail observability (3) and card-linked payment rails
(2) are wired and tested but flag-off with no live provider validated. All other
areas with minor gaps remain at 4 until they carry production traffic at scale.
The new **provider certification plane** (4/5) is the only score added this pass:
it is a real, tested, gate-enforced credentialless framework, but it certifies
readiness rather than conferring it — all 19 first-release providers it tracks are
`CREDENTIAL_WAITING`, so the economic domain scores did **not** move. No area was
promoted to production-ready or live-validated this pass; credential-waiting and
pilot-ready are deliberately distinguished from production-ready throughout.

## 4. Release Blockers (ordered)

1. ~~**Tenant onboarding UI**~~ — **Fixed in PR #288.** Full self-serve
   signup→OTP→billing flow shipped; implementation checklist wired to
   `/v1/onboarding/*`. ~~Remaining gap: no E2E tests for the critical path.~~
   **Playwright E2E suite added** (5 scenarios CI-gated via e2e-tenant job).
2. **Production infra + secrets** — high. Terraform exists but is not
   provisioned; run the stack + `scripts/bootstrap_aws_secrets.py`.
3. **External smart-contract audit** — high (blocks mainnet only). The
   contracts are tested but unaudited; checklist in
   `docs/` smart-contract materials must gate any real-funds deployment.
4. **Agent Layer durable storage** — high (blocks agent GA only). Hosted
   control-plane mode requires Redis or equivalent.
5. **ML artifacts** — medium. Training pipelines exist; artifacts are not
   trained/published for serving.
6. **Connector real API calls** — medium. Framework + vault secrets are
   real; per-provider pulls are mocked TODOs.

## 5. Scale Blockers

1. **No load baselines recorded yet** — `tests/load/locustfile` + `docs/LOAD-BASELINES.md`
   + `make load-baselines` exist; no baselines recorded against staging yet.
   Failure mode at scale: ingestion back-pressure and merge-queue growth
   discovered in production instead of staging.
2. **Neptune throughput/cost unvalidated** — graph code is
   backend-pluggable, but no synthetic merge/traversal workload has been
   replayed against a provisioned Neptune. Failure mode: hot-partition or
   cost blowup on first large tenant.
3. **ClickHouse/medallion compaction validated locally only** — retention
   and compaction settings need a staging soak.

## 6. Docs / Contract Drift Status

- **Stale docs found:** 6 (all economic/x402-adjacent, staled by the v8.9.0
  merge commits landing after their stamp). All 6 reviewed; 3 needed content
  fixes (missing Economic Value Service endpoints, missing economic-identity
  materialization note), 3 were content-correct and only needed re-stamping.
- **Contract drift found:** none — `validate_contracts.py` and
  `validate_sdk_release_alignment.py` pass; generated artifacts under
  `docs/_generated/` regenerate cleanly.
- **Remaining drift:** none at audit time. `repo-doctor` is green.

## 7. Recommended Next PR Sequence

1. **Tenant self-serve onboarding** — `frontend/aether` signup →
   tenant + API-key provisioning against existing `/v1/registration`.
   Accept: a new tenant can sign up, get keys, and send a first event
   without operator SQL. (Clears blocker #1.)
2. **Connector productization wave 1 (Slack outbound + 2 source
   connectors)** — wire real credential-gated API calls for the highest-value
   connectors; add per-tenant channel mapping + opt-in templates for Slack
   notifications. Accept: connector health visible in Kyber; no mocks outside
   local mode.
3. **Governed Dune feeder** — read-only feeder writing Bronze with per-row
   provenance, freshness checks, and quality gates before Silver promotion;
   no direct graph mutation. Accept: Dune rows traceable end-to-end with
   provenance; Kyber shows feeder health.
4. **Graph health scoring completion** — replace placeholder
   operational-intelligence overlay scores with real metrics (cluster churn,
   merge/split rates, orphan nodes, edge growth); surface in Kyber. Accept:
   drift tests for healthy vs contaminated fixtures pass.
5. **Load baseline + scale gate** — scheduled Locust smoke against staging,
   recorded baselines, thresholds in CI. Accept: documented RPS/latency
   baselines; regression gate active.
6. **Smart-contract audit engagement** — external audit + remediation PR.
   Accept: audit report committed; mainnet gate lifted or explicitly held.

## 8. Assumptions Made During This Audit

- The two unmerged sibling branches (`claude/admiring-darwin-*`,
  `claude/vigilant-archimedes-*`) contain overlapping docs-stamp work; this
  audit did not consume or modify them, and stamping here is idempotent with
  theirs.
- Score assignments treat "tested against in-memory/local fallbacks" as at
  most release-ready (4), never production-ready (5), regardless of code
  completeness.
- `--strict` in the production-status routine intentionally fails only on
  live consistency-check failures, not on declared blockers — failing CI on
  known, tracked work would make the gate permanently red.
- The Locust harness, Playwright E2E, and JS coverage thresholds were taken
  as evidence of test infrastructure without re-running the full JS matrix in
  this environment (Python suites were run: 800 core + 152 ML, green).
