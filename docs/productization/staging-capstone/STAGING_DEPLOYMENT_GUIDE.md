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
  "config/deployment_profiles.yaml": "sha256:83715252d5052cd9ef78a33db51ea7f7f73c5b850821bdb37e35f47a9e8ced6b"
  "config/runtime_deployment.yaml": "sha256:7c6ebe1fafec7f7a2fae8e054cd09ffe0b0f78bd8c6694bdd4da1d517740d7d8"
  "scripts/lib/preflight_dynamodb.py": "sha256:412fa322a11832da710b26c2834a9d7f57a02e0b5451ea4336e7a599de1e41f9"
  "scripts/staging_preflight.py": "sha256:961ec8e350c05fdb548801e946c27a7385f376331fffec6d5de6d8ea14557c84"
---

# Staging Deployment Guide

Bringing up an AETHER staging environment safely. This guide sequences the
existing deployment and preflight machinery — it does not replace it. Deep
references: `docs/DEPLOYMENT-RUNBOOK.md`, `docs/PRODUCTION-DEPLOYMENT.md`,
`docs/AWS-DEPLOYMENT.md`, and `docs/runbooks/STAGING_PREFLIGHT.md`.

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

See also: `DISASTER_RECOVERY_GUIDE.md`, `docs/runbooks/STAGING_PREFLIGHT.md`.
