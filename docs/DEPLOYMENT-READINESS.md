---
title: Deployment Readiness
slug: enterprise/deployment-readiness
section: enterprise
visibility: I
audience: [exec, buyer, ops]
status: stable
since_version: "8.9.0"
---

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


## Sales readiness linkage
Kyber sales readiness uses deployment readiness to identify packages missing supportable deployment artifacts. Government-ready planning and self-hosted future remain planning language unless implementation and approvals are completed.

## Security & governance control plane
Deployment readiness now draws on the governance control plane for demonstrable
controls: centralized access control, a policy engine, a tamper-evident audit
ledger, the tenant isolation verifier, break-glass operator access, data retention
policies, audit-export governance, and integration security. Governance evidence
packs (`access_control`, `tenant_isolation`, `audit_logging`, `data_retention`,
`integration_security`, `ai_recommendation_governance`, `operator_access`)
package these for a buyer's security review. See
[SECURITY-GOVERNANCE-CONTROLS.md](./SECURITY-GOVERNANCE-CONTROLS.md). These are
security-review evidence only — **no certification or authorization is claimed**.
