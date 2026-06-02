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

## Reliability & Operational Resilience

Reliability, SRE, incident response, SLOs, runbooks, and tenant-safe system
status are documented in [Reliability Operations](RELIABILITY-OPERATIONS.md) and
related docs ([Incident Response](INCIDENT-RESPONSE.md),
[SLO Tracking](SLO-TRACKING.md), [SRE Runbooks](SRE-RUNBOOKS.md),
[Tenant System Status](TENANT-STATUS.md), [Pipeline Health](PIPELINE-HEALTH.md),
[Queue & Worker Health](QUEUE-WORKER-HEALTH.md), [Postmortems](POSTMORTEMS.md)).
These controls are additive and do not weaken tenant isolation, governance,
auditability, or security. No external SLA or certification is claimed.
