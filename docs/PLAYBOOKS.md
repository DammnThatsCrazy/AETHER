---
title: Playbooks
slug: ai/playbooks
section: ai
visibility: I
audience: [ai, architect, dev-senior, ops]
status: beta
since_version: "8.9.0"
source_files:
  - Backend Architecture/aether-backend/services/intelligence/routes.py
  - Backend Architecture/aether-backend/services/intelligence/decision_models.py
flags:
  - AETHER_PLAYBOOKS_ENABLED
  - AETHER_RECOMMENDATIONS_ENABLED
related:
  - ai/decision-outcome-intelligence
  - ai/outcome-ledger
canonical_owner: platform@aether
estimated_read_minutes: 5
toc_depth: 3
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

## Package ROI and audit exports

Playbook definitions, run history, generated recommendations, linked decisions/actions/outcomes, and ROI metrics are included in `playbook_run_audit` exports and in Kyber package readiness views.
