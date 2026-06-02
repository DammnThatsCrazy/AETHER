# Deployment Readiness

Deployment readiness tracks supportable modes without overstating compliance. A mode is not marked ready unless required artifacts and controls exist.

## Modes

1. **Standard SaaS**: sales-ready shared SaaS control plane with tenant-scoped auth, role permissions, audit exports, and secret redaction.
2. **Enterprise Isolated Tenant**: pilot-ready logical isolation track requiring customer-specific isolation runbooks.
3. **Regulated Cloud**: draft track requiring retention, incident response, AI risk, audit review, and deployment evidence packets.
4. **Government-Ready Planning**: planning-only future public-sector track. No ATO, FedRAMP, StateRAMP, procurement, classified workload, or compliance certification claim is implemented.
5. **Self-Hosted Future**: planning-only mode; not a current deployable product.

## Checklist areas

Kyber tracks access controls, audit exports, logging, tenant isolation, integration security, incident response docs, data retention docs, AI risk management docs, deployment documentation, and known gaps.

## Customer Onboarding and Implementation Lifecycle

Customer onboarding now connects package selection to implementation execution. Each package can instantiate a tenant implementation plan with package-specific steps, success criteria, recommended playbooks, recommended integrations, and audit exports. Aether exposes only the tenant's own checklist and readiness state, while Kyber exposes cross-tenant implementation operations for Olympus admins.

Rollout should account for deployment mode, audit requirements, feature flags, human-in-the-loop approval controls, and known gaps in customer telemetry until SDK, graph, recommendation, playbook, integration, and outcome signals are fully connected.
