---
title: Docs Review Backlog — Audit Snapshot
slug: audits/docs-review-backlog
section: operations
visibility: I
audience: [dev-senior, architect]
status: stable
since_version: 0.1.0
---

# Docs Review Backlog — Audit Snapshot (2026-07-30)

Where this list comes from: fixing `scripts/docs_drift.py`'s fail-open on
unresolvable stamps exposed 78 docs carrying phantom pre-squash stamps.
Translating those stamps across the squash kept drift *tracking* alive but
advanced the review *claim* mechanically — and the tool's
`doc_reviewed_after_sources` heuristic then treated any later doc edit
(including the restamp itself) as a review. Both holes are now closed:
restamp-only commits no longer count as review, and the resulting honest
debt is registered in `config/docs_review_backlog.yaml` — visible in every
gate run, shrink-only, and excluded from `--update` stamping.

**Clearing an entry** means reviewing the doc against
`git log <last real review>..HEAD -- <source_files>`, fixing contradicted
content, stamping, and deleting the registry entry. `--strict` fails on any
entry whose doc is no longer stale, so the registry cannot rot.

Docs are ranked by how many source commits landed since the last genuine
content review. `gate-visible` marks docs currently stale by stamp
comparison (registered in the YAML registry); the rest are older debt whose
stamps have since been legitimately re-reviewed or whose staleness window
closed.

| Doc | Last real review | Source commits since | Gate-visible |
|---|---|---:|---|
| docs/architecture/PLATFORM-ARCHITECTURE.md | f44dceec5 | 72 | yes |
| docs/product/productization/economic-interoperability-intelligence/TARGET_ARCHITECTURE.md | f44dceec5 | 45 | yes |
| docs/operations/CONTRIBUTING.md | f44dceec5 | 41 | no |
| docs/operations/OPERATIONS-RUNBOOK.md | f44dceec5 | 25 | yes |
| docs/operations/internal/tooling/docs-pipeline.md | f44dceec5 | 25 | no |
| docs/product/productization/economic-interoperability-intelligence/DEPLOYMENT_PROFILE_MATRIX.md | f44dceec5 | 25 | yes |
| docs/architecture/DECISION-OUTCOME-INTELLIGENCE.md | f44dceec5 | 24 | yes |
| docs/product/comms/COMMS_RELEASE_READINESS.md | f44dceec5 | 24 | no |
| docs/reference/SDK-WEB.md | f44dceec5 | 20 | yes |
| docs/reference/SDK-ANDROID.md | f44dceec5 | 18 | yes |
| docs/reference/reports/SDK_PRODUCTION_READINESS_AUDIT.md | f44dceec5 | 18 | yes |
| docs/reference/SDK-IOS.md | f44dceec5 | 17 | yes |
| docs/reference/SDK-REACT-NATIVE.md | f44dceec5 | 15 | yes |
| docs/reference/audits/AGENTIC_OBSERVABILITY_AUDIT.md | f44dceec5 | 15 | no |
| docs/product/campaign/CAMPAIGN_SDK_ACQUISITION.md | f44dceec5 | 14 | yes |
| docs/product/comms/COMMS_TRUTH_MATRIX.md | f44dceec5 | 14 | no |
| docs/architecture/CAMPAIGN_360_ARCHITECTURE.md | f44dceec5 | 10 | no |
| docs/product/campaign/CAMPAIGN_KYBER_GUIDE.md | f44dceec5 | 10 | yes |
| docs/architecture/PROFILE-360-AGGREGATION.md | f44dceec5 | 9 | no |
| docs/product/comms/ADR_COMMUNICATIONS_INTELLIGENCE.md | f44dceec5 | 8 | no |
| docs/product/comms/COMMUNICATIONS_INTELLIGENCE_OVERVIEW.md | f44dceec5 | 8 | no |
| docs/product/productization/unified-canonical-journey/RELEASE_READINESS.md | f44dceec5 | 8 | yes |
| docs/architecture/CANONICAL-PATH-INTELLIGENCE.md | f44dceec5 | 7 | no |
| docs/operations/CICD.md | 8757b6ee7 | 7 | no |
| docs/architecture/FRONTEND-ARCHITECTURE.md | 41c7a801d | 7 | yes |
| docs/architecture/SUBSYSTEM-EVENTS.md | f44dceec5 | 7 | yes |
| docs/reference/audits/FRONTEND-DATA-TRUTH-INVENTORY.md | 41c7a801d | 7 | no |
| docs/operations/runbooks/CAMPAIGN-360-GRAPH-DISAGREES-WITH-TOTALS.md | f44dceec5 | 7 | no |
| docs/operations/runbooks/CAMPAIGN-360-STALE-SPEND.md | f44dceec5 | 7 | no |
| docs/reference/reports/ML-FULL-PRODUCTIONIZATION-REPORT.md | 190a52bc6 | 6 | no |
| docs/reference/reports/ML-PRODUCTIZATION-READINESS.md | f44dceec5 | 6 | no |
| docs/operations/runbooks/semantic-sentiment/semantic-sentiment-operations.md | f44dceec5 | 6 | no |
| docs/operations/OPERATIONAL-INTELLIGENCE-AUDIT.md | f44dceec5 | 5 | yes |
| docs/reference/X402_AUDIT_REPORT.md | f44dceec5 | 5 | no |
| docs/architecture/FRAUD-NETWORK-ARCHITECTURE.md | f44dceec5 | 5 | yes |
| docs/product/productization/economic-interoperability-intelligence/GOVERNANCE_AND_CONSENT.md | f44dceec5 | 5 | yes |
| docs/reference/reports/ML-SECURITY-THREAT-MODEL.md | f44dceec5 | 5 | no |
| docs/architecture/INTELLIGENCE-GRAPH.md | f44dceec5 | 4 | yes |
| docs/product/KYBER-REVENUE-INTELLIGENCE.md | f44dceec5 | 4 | yes |
| docs/architecture/OUTCOME-LEDGER.md | f44dceec5 | 4 | no |
| docs/product/frontend/PROFILE360_ARCHITECTURE.md | f44dceec5 | 4 | yes |
| docs/product/productization/economic-interoperability-intelligence/CANONICAL_EVENT_MODEL.md | f44dceec5 | 4 | no |
| docs/reference/reports/ML-MODEL-READINESS-MATRIX.md | f44dceec5 | 4 | no |
| docs/operations/runbooks/CAMPAIGN-360-ATTRIBUTION-RUN-FAILED.md | f44dceec5 | 4 | no |
| docs/operations/runbooks/IMPORT_FAILURES.md | f44dceec5 | 4 | yes |
| docs/operations/runbooks/MEASUREMENT_RESTATEMENT.md | f44dceec5 | 4 | no |
| docs/operations/runbooks/ML-INCIDENT-RUNBOOK.md | f44dceec5 | 4 | no |
| docs/architecture/FLOW-OF-FUNDS-TRACE.md | f44dceec5 | 3 | yes |
| docs/architecture/FRAUD-NETWORK-INTELLIGENCE.md | f44dceec5 | 3 | yes |
| docs/product/KYBER-FRAUD-INVESTIGATIONS.md | f44dceec5 | 3 | yes |
| docs/operations/STAGING-WAKE-SLEEP.md | e1fe80169 | 3 | no |
| docs/operations/internal/noesis.md | f44dceec5 | 3 | yes |
| docs/product/productization/unified-canonical-journey/TEST_EVIDENCE.md | f44dceec5 | 3 | no |
| docs/operations/runbooks/KYBER_WORKFORCE_OFFBOARDING.md | f5d6124db | 3 | no |
| docs/architecture/AGENTIC_COMMERCE_BUILD_SPEC.md | b30af062c | 2 | no |
| docs/architecture/BACKEND-EXECUTION-MODEL.md | 41c7a801d | 2 | yes |
| docs/product/ECONOMIC-VALUE-FRAMING.md | f44dceec5 | 2 | yes |
| docs/reference/KLAVIYO-CONNECTOR.md | f44dceec5 | 2 | no |
| docs/product/KYBER-ECONOMIC-OBSERVABILITY.md | f44dceec5 | 2 | yes |
| docs/operations/ML-TRAINING-GUIDE.md | f44dceec5 | 2 | yes |
| docs/operations/PIPELINE-HEALTH.md | f44dceec5 | 2 | yes |
| docs/operations/QUEUE-WORKER-HEALTH.md | f44dceec5 | 2 | yes |
| docs/operations/SRE-RUNBOOKS.md | f44dceec5 | 2 | yes |
| docs/reference/STRIPE-BILLING.md | f44dceec5 | 2 | yes |
| docs/architecture/SUBSYSTEM-DATABASE.md | f44dceec5 | 2 | yes |
| docs/product/campaign/CAMPAIGN_CONNECTORS.md | f44dceec5 | 2 | no |
| docs/product/comms/COMMS_BACKFILL_RUNBOOK.md | f44dceec5 | 2 | no |
| docs/product/productization/economic-interoperability-intelligence/PROFILE360_SURFACES.md | 255c5aed5 | 2 | no |
| docs/product/productization/economic-interoperability-intelligence/RELEASE_READINESS.md | 32f0ec3d7 | 2 | no |
| docs/product/productization/staging-capstone/PILOT_EVIDENCE_GUIDE.md | fdebe494a | 2 | no |
| docs/operations/AWS-LEAN-PRODUCTION.md | 190a52bc6 | 1 | no |
| docs/reference/BACKEND-API.md | 2b96614d8 | 1 | no |
| docs/operations/COST-OPTIMIZATION.md | 190a52bc6 | 1 | no |
| docs/operations/SECURITY-GOVERNANCE-CONTROLS.md | 592738039 | 1 | yes |
| docs/reference/api/FLOW-TRACE.md | f44dceec5 | 1 | yes |
| docs/reference/api/FRAUD-NETWORKS.md | f44dceec5 | 1 | yes |
| docs/product/campaign/CAMPAIGN_REGISTRY_ARCHITECTURE.md | e55fd16e2 | 1 | no |
| docs/architecture/decisions/ADR-011-observation-only-execution-invariant.md | f44dceec5 | 1 | no |
| docs/product/productization/aether_productization_audit.md | 4e944e7f1 | 1 | no |
| docs/product/productization/staging-capstone/CREDENTIAL_WAITING_PROMOTION_GUIDE.md | fdebe494a | 1 | no |
| docs/product/productization/staging-capstone/PROVIDER_CAPABILITY_MATRIX_GUIDE.md | fdebe494a | 1 | no |
| docs/product/productization/unified-canonical-journey/DEPLOYMENT_PROFILE_MATRIX.md | 5bac4b488 | 1 | no |
| docs/product/productization/unified-canonical-journey/EXECUTION_STATE.md | 5bac4b488 | 1 | no |
| docs/operations/runbooks/EVM_DEPLOY_EMERGENCY_RUNBOOK.md | fdebe494a | 1 | no |
| docs/operations/runbooks/KYBER_DEVICE_LOSS.md | f5d6124db | 1 | no |
| docs/operations/runbooks/KYBER_SCOPE_LEAK.md | f5d6124db | 1 | no |
| docs/product/semantic-sentiment/SEMANTIC-SENTIMENT-INTELLIGENCE.md | 2b5920e90 | 1 | no |
