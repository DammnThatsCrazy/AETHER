---
title: Customer Success Automation
slug: kyber/customer-success-automation
section: kyber
visibility: I
audience: [exec, ops, architect]
status: stable
since_version: "8.9.0"
---

# Customer Success Automation

Customer Success Automation turns Aether usage, OODA loops, outcome ledger evidence, playbook ROI, package fit, and integration health into Kyber account health, expansion, renewal, EBR, and next-action workflows.

## Visibility and isolation

- Tenant-facing routes (`/v1/value-review*`) only read the authenticated tenant context and return that tenant's value review.
- Kyber routes (`/v1/admin/kyber/customer-success*`) require admin permission and expose account-level aggregates for Olympus Labs operators.
- Cross-tenant command-center views use scores, totals, status, and recommended motions. They do not expose raw tenant-private evidence payloads, secrets, or graph intelligence.

## Scoring methodology

Health score combines recommendation view rate, decision rate, outcome capture, success rate, playbook adoption, integration adoption, and penalties for stale loops, incomplete loops, failed integrations, and blockers.

Lifecycle recommendations move accounts from signed/activated/adopting into value_proven when observed outcomes and capture rates prove value, or at_risk when blockers and loop gaps dominate.

## Trigger generation

Triggers are generated for value proof, expansion readiness, renewal risk, playbook underuse, integration gaps, outcome gaps, executive proof readiness, package fit, and implementation intervention. Duplicate open triggers for the same tenant/type are suppressed unless the existing trigger is resolved or dismissed.

## Rollout notes and known gaps

Current scoring is deterministic and explainable. Future work can add weighted historical trend models, CRM synchronization, and richer onboarding completion signals while preserving tenant-scoped data boundaries.
