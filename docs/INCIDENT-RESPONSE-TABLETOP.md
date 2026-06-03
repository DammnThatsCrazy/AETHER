---
title: Incident Response Tabletop
slug: security/incident-response-tabletop
section: security
visibility: I
audience: [security, ops]
status: beta
since_version: "8.9.0"
canonical_owner: platform@aether
estimated_read_minutes: 4
---

# Incident Response Tabletop

A rehearsal framework for security/operational incidents, complementing the SRE
[Incident Response](INCIDENT-RESPONSE.md) and [SRE Runbooks](SRE-RUNBOOKS.md).

## Roles

Incident commander, comms lead, security lead, on-call SRE, scribe.

## Scenarios to rehearse

1. **Suspected secret leak** — rotate (`integration_security.rotate_secret`,
   `generate_secrets.py`), scan (`security:secrets`), audit blast radius.
2. **Tenant-isolation alarm** — contamination drift escalated to the audit
   ledger; quarantine + verify isolation.
3. **Operator-gate probe** — review access-control audit events; confirm
   fail-closed behavior.
4. **Connector webhook abuse** — invalid-signature spike; disable connector.
5. **Data subject request under deadline** — DSR workflow + retention.

## Per-scenario drill

Detect → triage/severity → contain → eradicate → recover → postmortem (record in
the reliability postmortem store). Capture timing + gaps as evidence for
[Compliance Evidence Inventory](COMPLIANCE-EVIDENCE-INVENTORY.md). Run quarterly.
