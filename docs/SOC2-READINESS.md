---
title: SOC 2 Readiness
slug: compliance/soc2-readiness
section: compliance
visibility: I
audience: [security, compliance, exec]
status: beta
since_version: "8.9.0"
canonical_owner: platform@aether
estimated_read_minutes: 5
---

# SOC 2 Readiness

> **Aether is NOT SOC 2 certified.** This page maps existing controls to the
> SOC 2 Trust Services Criteria for **readiness / pre-positioning** only. A SOC 2
> report requires an independent auditor over a defined observation period. Not
> legal advice.

## Trust Services Criteria — readiness mapping

| Criterion | Control(s) | Readiness |
| --- | --- | --- |
| Security (CC6 access) | RBAC, tenant isolation, break-glass | implemented |
| Security (CC7 ops) | Reliability/SRE, incidents, SLOs | implemented |
| Audit (CC4/CC7) | Tamper-evident audit ledger + exports | implemented |
| Change mgmt (CC8) | CI gates, migrations, code review | implemented |
| Confidentiality | Secrets vault, no-secret exports, encryption-at-rest config | implemented |
| Availability | Healthchecks, SLOs, runbooks | implemented |
| Risk (CC3) | Threat model, vuln management, dependency audit | documented |
| Vendor mgmt | Provider gateway, connector governance | partial |

## To reach a SOC 2 report (external work)

Engage an auditor; select Type I/II + period; formalize policies (access review
cadence, change management, vendor management, incident response); collect
evidence over the observation window (see
[Compliance Evidence Inventory](COMPLIANCE-EVIDENCE-INVENTORY.md)); remediate
auditor findings.

See [Security Readiness](SECURITY-READINESS.md).
