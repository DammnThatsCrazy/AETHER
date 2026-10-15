---
title: "Staging Deployment Guide"
slug: productization/staging-capstone/staging-deployment-guide
section: operations
visibility: I
audience: [ops, dev-senior]
status: stable
since_version: "0.1.0"
source_files:
  - config/deployment_profiles.yaml
  - config/runtime_deployment.yaml
  - scripts/staging_preflight.py
  - scripts/lib/preflight_dynamodb.py
canonical_owner: platform@aether
estimated_read_minutes: 6
toc_depth: 2
source_hashes:
  "config/deployment_profiles.yaml": "sha256:6d4535fd98bebf72519f2e03c5d2dfca190bfe7da63e76140073db051e3b6a66"
  "config/runtime_deployment.yaml": "sha256:cd65f4902ed9062c2526bd9b83b99e2c0ecc58f012a3fa1c90ba9660b874a332"
  "scripts/lib/preflight_dynamodb.py": "sha256:fb2c96646af2b24fc6add4b9463ce3ed19a8ae7ff77161be41eb464cb61ffa15"
  "scripts/staging_preflight.py": "sha256:d18e7929deaedc6ad3ecf261d6cde3d3e59136f49515642dfc87b8e8f7026e28"
---

# Staging Deployment Guide

Bringing up an AETHER staging environment safely. This guide sequences the
existing deployment and preflight machinery — it does not replace it. Deep
references: `docs/operations/DEPLOYMENT-RUNBOOK.md`, `docs/operations/PRODUCTION-DEPLOYMENT.md`,
`docs/operations/AWS-DEPLOYMENT.md`, and `docs/operations/runbooks/STAGING_PREFLIGHT.md`.

## Sequence

1. **Provision infrastructure.** Apply the canonical staging profile: Aurora
   PostgreSQL, DynamoDB cache/durable stores, SNS/SQS event fanout and DLQs,
   PostgreSQL graph/analytics paths, S3, inline ML, the API, consolidated
   worker, ALB, and static frontends. Staging and production require real
   backends — in-memory fallbacks are dev/test only and are refused in hosted
   modes.
2. **Load secrets.** `scripts/bootstrap_aws_secrets.py`; provider secrets per
   `CREDENTIAL_SECRET_REFERENCE.md`. Confirm the secret-scan gate is green.
3. **Set environment.** `AETHER_ENV=staging`. Keep every economic/agent rollout
   flag OFF initially (they default OFF); enable one subsystem at a time.
4. **Deploy.** Follow `docs/operations/DEPLOYMENT-RUNBOOK.md`.
5. **Preflight.** Run `scripts/staging_preflight.py` and confirm `/v1/ready`
   passes per `docs/operations/runbooks/STAGING_PREFLIGHT.md`. A failing preflight blocks
   traffic — do not override it.

## Enabling a subsystem

- Enable the master flag, then per-provider flags, one at a time.
- After each enable, validate one lifecycle end to end and capture pilot
  evidence (`PILOT_EVIDENCE_GUIDE.md`).
- Watch the SLO dashboards; roll back (flag off) on any SLO breach.

## What staging must prove before production is even discussed

- Recorded load baselines (`make load-baselines`, `docs/operations/LOAD-BASELINES.md`).
- Staging's PostgreSQL graph/analytics paths and DynamoDB durable-store behavior
  validated with the synthetic merge/measurement workload. Neptune and
  ClickHouse are separate heavier-profile prerequisites, not staging defaults.
- At least one live provider per enabled domain validated (`partner_live`).

None of these are done yet — they are the gap between credential-waiting and
production (`LIMITATIONS_AND_NON_GOALS.md`).

## Never do

- Never point staging at production data without tenant isolation verified.
- Never override a failing preflight to "just test".
- Never enable all providers at once — one subsystem, one validation, at a time.

See also: `DISASTER_RECOVERY_GUIDE.md`, `docs/operations/runbooks/STAGING_PREFLIGHT.md`.
