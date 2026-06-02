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

## Customer Onboarding and Implementation Lifecycle

Customer onboarding now connects package selection to implementation execution. Each package can instantiate a tenant implementation plan with package-specific steps, success criteria, recommended playbooks, recommended integrations, and audit exports. Aether exposes only the tenant's own checklist and readiness state, while Kyber exposes cross-tenant implementation operations for Olympus admins.

Rollout should account for deployment mode, audit requirements, feature flags, human-in-the-loop approval controls, and known gaps in customer telemetry until SDK, graph, recommendation, playbook, integration, and outcome signals are fully connected.
