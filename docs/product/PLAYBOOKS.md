---
title: Playbooks
slug: ai/playbooks
section: architecture
visibility: I
audience: [architect, dev-senior, ops]
status: beta
since_version: 0.1.0
source_files: [services/api/intelligence/intelligence/routes.py, services/api/intelligence/intelligence/decision_models.py]
flags: [AETHER_PLAYBOOKS_ENABLED, AETHER_RECOMMENDATIONS_ENABLED]
related: [ai/decision-outcome-intelligence, ai/outcome-ledger]
canonical_owner: platform@aether
estimated_read_minutes: 5
toc_depth: 3
source_hashes:
  "services/api/intelligence/intelligence/decision_models.py": "sha256:fa7574a7f99bcebb21ff58d6cd61ffbb761a58b0022b5a247a13387c8c9853d8"
  "services/api/intelligence/intelligence/routes.py": "sha256:60d5307836ffcd38c784710b60689c803347d7a3dbb0f7608a64ba66ef150241"
---
# Playbooks

Playbooks convert repeated recommendation patterns into operational assets while preserving tenant control, graph-native records, and human-in-the-loop approvals.

## APIs

- `GET /v1/intelligence/playbooks/templates`
- `POST /v1/intelligence/playbooks/from-template`
- `GET /v1/intelligence/playbooks/{id}/performance`
- `GET /v1/intelligence/playbooks/{id}/runs`
- `POST /v1/intelligence/playbooks/{id}/evaluate`

## Templates

Initial templates include High-LTV churn save, Fraud cluster review, Campaign waste reduction, Agent failure review, Expansion signal routing, Reward trigger review, and Operational failure review.

## Lifecycle

A playbook defines trigger conditions, recommendation families, candidate actions, approval threshold, outcome mapping, expected value model, run history, ROI aggregation, and stale run detection. Execution remains approval-aware and auditable.

Playbook actions inherit the canonical dispatch safeguards: idempotency is
reserved per tenant/action before connector invocation, real external evidence
is required for a delivered receipt, and an unavailable adapter remains a
durable queued plan with no claimed external side effect. This keeps playbook
ROI and run history honest when execution is pending or failed. Journey360 and
Risk360 can include canonical provider delivery receipts and signature-verified
callbacks, but tenant-submitted outcome events remain `caller_asserted` and
neither evidence type establishes an independently verified external effect.
Their dispatch reads also require the persisted allowed `action.dispatch`
decision to match the exact dispatch context, including tenant, authenticated
principal, selected action, target, approval/elevation context, and association.

## Package ROI and audit exports

Playbook definitions, run history, generated recommendations, linked decisions/actions/outcomes, and ROI metrics are included in `playbook_run_audit` exports and in Kyber package readiness views.


## Customer success usage

Playbook adoption and ROI now contribute to account health, expansion readiness, renewal risk, EBR summaries, and playbook-underused triggers.

## Commerce lifecycle trace

`GET /v1/intelligence/commerce/lifecycle/{challenge_id}` — full lifecycle trace for one payment challenge (requirement → policy_decision → authorization → receipt → settlement → entitlement → grant → fulfillment). Requires `x402:read`. Used by Kyber Noesis and compliance audit.
