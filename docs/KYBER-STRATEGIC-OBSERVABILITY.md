---
title: Kyber Strategic Observability
slug: kyber/strategic-observability
section: kyber
visibility: I
audience: [exec, ops, architect]
status: beta
since_version: "8.9.0"
source_files:
  - Backend Architecture/aether-backend/services/intelligence/routes.py
  - Backend Architecture/aether-backend/services/intelligence/outcome_ledger.py
flags:
  - KYBER_RECOMMENDATION_OBSERVABILITY_ENABLED
related:
  - ai/outcome-ledger
canonical_owner: platform@aether
estimated_read_minutes: 5
toc_depth: 3
---
# Kyber Strategic Observability

Kyber strategic observability uses backend aggregate endpoints to show Olympus Labs operators which tenants are receiving value, which loops are broken, and which recommendation families or playbooks are performing.

## APIs

- `GET /v1/admin/kyber/recommendation-health`
- `GET /v1/admin/kyber/tenant-value-health`
- `GET /v1/admin/kyber/outcome-capture-health`
- `GET /v1/admin/kyber/playbook-performance`
- `GET /v1/admin/kyber/model-confidence-drift`
- `GET /v1/admin/kyber/vertical-solution-signals`
- `GET /v1/admin/kyber/expansion-opportunities`

## Data boundaries

Kyber may show tenant-level account health to Olympus Labs operators with `admin` permission. Cross-tenant views must remain aggregate, anonymized, or internal operational diagnostics. Raw tenant-private evidence, graph intelligence, and tenant-specific investigation content are not exposed across tenants.

## Packaging command extensions

Kyber now includes enterprise/government packaging and deployment readiness command views: solution packages, package detail, package readiness, deployment modes, deployment readiness, audit export health, and tenant-package fit. Government entries are planning tracks only and do not claim certification.


## Customer Success command center

Kyber now includes Customer Success Automation for account health, expansion opportunities, renewal risks, EBR generation, and account plans. It preserves the strategic observability rule that cross-tenant views are aggregate/operator summaries, not raw tenant-private intelligence. See docs/CUSTOMER-SUCCESS-AUTOMATION.md.
