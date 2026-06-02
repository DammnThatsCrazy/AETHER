---
title: Solution Packages
slug: enterprise/solution-packages
section: enterprise
visibility: I
audience: [exec, buyer, ops]
status: stable
since_version: "8.9.0"
---

# Solution Packages

Aether packages existing graph-native OODA, Outcome Ledger, Recommendation Families, Investigations, Playbook ROI, Action Dispatch, and Kyber Strategic Observability into sellable bundles. These are not separate products and do not bypass tenant isolation, consent, governance, approvals, auditability, or human-in-the-loop controls.

## Implemented packages

- **Revenue Intelligence Graph** (`sales_ready`): enterprise/commercial package for retention, expansion, attribution optimization, journey optimization, and revenue outcome tracking.
- **Fraud & Risk Intelligence Graph** (`pilot_ready`): enterprise/regulated package for fraud cluster review, suspicious relationship detection, investigations, reward abuse prevention, and avoided-loss tracking.
- **Agent Governance Graph** (`government_planning`): enterprise/regulated/government-planning package for agent oversight, human approval routing, action auditability, failure detection, and outcomes.
- **Operational Decision Intelligence** (`sales_ready`): enterprise package for operational decisions, playbook ROI, action dispatch, outcome measurement, and stale-loop repair.
- **Program Integrity Graph** (`government_planning`): regulated/government-planning track for grants, claims, vendor review, anomalous relationship detection, case prioritization, decisions, and outcomes.
- **Critical Infrastructure Coordination Graph** (`government_planning`): regulated/enterprise/government-planning track for dependency mapping, incident coordination, vendor/system risk, actions/outcomes, and AI-enabled operational oversight.

Government/public-sector packages are planning/readiness tracks only. They are not certified offerings, compliance advice, authorization packages, FedRAMP claims, StateRAMP claims, or classified-workload claims.

## Package fields

Each package defines buyer personas, use cases, included modules, required feature flags, recommended integrations, required audit exports, pricing levers, deployment modes, and readiness status.

## Rollout notes

Kyber exposes package list/detail, readiness reports, deployment mode support, tenant-package fit, known gaps, and recommended next actions through `/v1/admin/kyber/solution-packages` and related readiness endpoints.


## GTM and pricing addendum
Solution packages now map to Kyber GTM materials, buyer personas, pricing dimensions, ROI calculator definitions, and sales readiness checks. Government-planning packages must remain planning-only and must not claim certifications or authorizations.
