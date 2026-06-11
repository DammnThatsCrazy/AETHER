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
last_synced_commit: 2661f1b
---

# AETHER Productization Audit

**Audit date:** 2026-06-10 (platform v8.9.0)
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
| 8 | Connector provider pulls are credential-gated TODOs (framework real, API calls mocked) | pre-production-blocker | **Partially fixed** — 14 production-shaped connectors with real API calls (Shopify, Stripe, HubSpot, Salesforce, Klaviyo, PostHog, GA4, Jira, Linear, Zendesk, Intercom) enabled when vault secret present; per-connector error tracking (error_count, last_error_at, last_error_message) added; Kyber per-tenant health drill-down wired. Remaining gap: staging validation with live credentials. |
| 9 | Dune is a read-only provider, but no governed Bronze→Silver→Gold feeder with per-row provenance/freshness gates exists | pre-production-blocker | Open |
| 10 | Graph-level drift/contamination scoring partial: data-quality module feature-flagged, operational-intelligence overlay scores are placeholders | pre-production-blocker | Open (SDK-level drift detection is real) |
| 11 | No load baselines recorded; Locust harness exists but is not exercised in CI | scale-blocker | **Partially fixed** — locustfile extended with `/v1/batch` + `/sdk/identity/resolve` tasks and thresholds; `scripts/load_smoke.py` + `make load-smoke` added. Staging baselines not yet recorded. |
| 12 | Neptune capacity/cost and identity-merge throughput unvalidated at scale | scale-blocker | Open |
| 13 | Slack outbound notification channel-mapping/templates not productized (ingest connector + connection test are real) | nice-to-have | **Fixed** — per-tenant Slack channel mapping by severity (slack_channel_map), opt-in controls (operator_review_required, quiet_hours, rate limits), Slack OAuth, and real outbound (chat.postMessage + Block Kit + retries) all confirmed present in notification_intelligence. |

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
| Profile 360 | 4 |
| Neptune relationships (H2H/H2A/A2H/A2A) | 3 |
| graph mutation safety | 4 |
| graph health / drift detection | 3 |
| Kyber (operator console) | 4 |
| customer frontend (tenant app) | 4 |
| connectors (BYOK / source) | 3 |
| Slack / action notifications | 4 |
| Dune / data-lake feeders | 2 |
| smart contracts / proofs / rewards | 3 |
| security / compliance | 3 |
| CI / tests | 4 |
| docs | 4 |
| deployment / cloud readiness | 3 |
| scale readiness | 3 |

**Overall: ~3.6/5 — pre-production.** The 4-rated areas are genuinely
release-shaped; nothing scores 5 because nothing has carried production
traffic at scale yet, and claiming otherwise would be a false readiness claim.

## 4. Release Blockers (ordered)

1. ~~**Tenant onboarding UI**~~ — **Fixed in PR #288.** Full self-serve
   signup→OTP→billing flow shipped; implementation checklist wired to
   `/v1/onboarding/*`. Remaining gap: no E2E tests for the critical path.
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

1. **No load baselines** — `tests/load/locustfile` exists; nothing records
   RPS/latency baselines for `/v1/batch` and identity resolve. Failure mode
   at scale: ingestion back-pressure and merge-queue growth discovered in
   production instead of staging.
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
