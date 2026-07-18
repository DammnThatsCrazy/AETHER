---
title: "Staging Deployment Guide"
slug: productization/staging-capstone/staging-deployment-guide
section: operations
visibility: I
audience: [ops, dev-senior]
status: stable
since_version: "8.12.0"
source_files:
  - scripts/staging_preflight.py
canonical_owner: platform@aether
estimated_read_minutes: 6
toc_depth: 2
---

# Staging Deployment Guide

Bringing up an AETHER staging environment safely. This guide sequences the
existing deployment and preflight machinery — it does not replace it. Deep
references: `docs/DEPLOYMENT-RUNBOOK.md`, `docs/PRODUCTION-DEPLOYMENT.md`,
`docs/AWS-DEPLOYMENT.md`, and `docs/runbooks/STAGING_PREFLIGHT.md`.

## Sequence

1. **Provision infrastructure.** Terraform stack (Postgres, Redis, Neptune,
   Kafka, ClickHouse, S3). Staging and production require real backends — the
   in-memory fallbacks are dev/test only and are refused in hosted modes.
2. **Load secrets.** `scripts/bootstrap_aws_secrets.py`; provider secrets per
   `CREDENTIAL_SECRET_REFERENCE.md`. Confirm the secret-scan gate is green.
3. **Set environment.** `AETHER_ENV=staging`. Keep every economic/agent rollout
   flag OFF initially (they default OFF); enable one subsystem at a time.
4. **Deploy.** Follow `docs/DEPLOYMENT-RUNBOOK.md`.
5. **Preflight.** Run `scripts/staging_preflight.py` and confirm `/v1/ready`
   passes per `docs/runbooks/STAGING_PREFLIGHT.md`. A failing preflight blocks
   traffic — do not override it.

## Enabling a subsystem

- Enable the master flag, then per-provider flags, one at a time.
- After each enable, validate one lifecycle end to end and capture pilot
  evidence (`PILOT_EVIDENCE_GUIDE.md`).
- Watch the SLO dashboards; roll back (flag off) on any SLO breach.

## What staging must prove before production is even discussed

- Recorded load baselines (`make load-baselines`, `docs/LOAD-BASELINES.md`).
- Neptune throughput/cost validated with a synthetic merge/traversal workload.
- ClickHouse/medallion compaction soaked.
- At least one live provider per enabled domain validated (`partner_live`).

None of these are done yet — they are the gap between credential-waiting and
production (`LIMITATIONS_AND_NON_GOALS.md`).

## Never do

- Never point staging at production data without tenant isolation verified.
- Never override a failing preflight to "just test".
- Never enable all providers at once — one subsystem, one validation, at a time.

See also: `DISASTER_RECOVERY_GUIDE.md`, `docs/runbooks/STAGING_PREFLIGHT.md`.
