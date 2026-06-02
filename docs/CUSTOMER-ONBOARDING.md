# Customer Onboarding

Aether customer onboarding turns a signed tenant into a live implementation without creating a separate product layer. The lifecycle builds on tenant isolation, SDK ingestion, graph activation, OODA intelligence, outcome ledger, playbooks, integrations, audit exports, and Kyber strategic observability.

## Tenant Activation Lifecycle

Stages are: `prospect`, `signed`, `tenant_created`, `sdk_pending`, `sdk_live`, `event_mapping_in_progress`, `graph_building`, `graph_active`, `recommendations_enabled`, `playbooks_configured`, `integrations_connected`, `outcomes_capturing`, `value_proven`, and `expansion_ready`.

## Tenant vs Kyber Visibility

- Aether tenants see only their own plan, checklist, blockers, SDK instructions, event requirements, and go-live readiness through `/v1/onboarding/*`.
- Kyber operators use `/v1/admin/kyber/onboarding/*` and must have admin permission to manage all implementation plans, blockers, readiness, and customer success triggers.

## Feature Flags and Rollout Notes

Roll out behind the existing tenant/package enablement process. Create a plan from a package template after contract signature, confirm deployment mode, assign an Olympus owner, and then expose the tenant checklist.

## Known Gaps

Automated metrics should be connected to live SDK, graph job, recommendation, playbook, integration, and ledger telemetry as each deployment hardens.
