---
title: Deployment Profiles
slug: operations/deployment-profiles
section: operations
visibility: I
audience: [ops, architect]
status: stable
canonical_owner: platform@aether
estimated_read_minutes: 6
toc_depth: 3
---

# Deployment Profiles

Aether's architecture stays viable across ten deployment profiles, from a
zero-backend local mock to a fully isolated enterprise deployment. The canonical
matrix — including backend selectors and the production-lean cost policy — lives
in `config/deployment_profiles.yaml` and is validated by
`make validate-profile-config` and `make validate-cost-policy`.

## Profiles

| Profile | Class | Purpose |
|---|---|---|
| `local-mocked` | local | Frontend/product work without a backend (MSW mocks). |
| `local-live` | local | Normal backend development (Postgres + one backend + inline ML). |
| `local-full` | local | Full local integration (all local dependencies). |
| `demo-static` | demo | Zero/near-zero cost static demo. |
| `demo-live` | demo | Temporary live demo with a synthetic tenant + TTL cleanup. |
| `preview` | preview | PR-specific environment on shared foundation; auto-expires. |
| `staging` | staging | Release rehearsal; wakes for validation, sleeps after. |
| `production-lean` | production | First customer / early controlled production. |
| `production-scale` | production | Higher traffic once justified. |
| `enterprise-isolated` | enterprise | Contractual/regulatory customer isolation. |

## production-lean cost policy

`production-lean` is the founding-tenant target. It **must** provision
CloudFront/S3 static frontends, an ALB, a single ECS backend, Aurora Serverless
v2, SQS/SNS, DynamoDB, an S3 object lake, Secrets/KMS, CloudWatch alarms, inline
ML, and a Postgres graph.

It **must not** provision:

```
msk                          elasticache
neptune                      clickhouse
dedicated_ml_service         frontend_ecs_services
legacy_rds                   nat_gateway_unless_explicit
always_on_staging_compute    prometheus_grafana_servers
```

`make validate-cost-policy` asserts this forbidden set is declared in the
canonical policy data. `make validate-cost-policy-terraform` extends this to the
infrastructure layer — see [Terraform enforcement](#terraform-enforcement-deployment_profile)
below (ledger item `FT-9-TERRAFORM-PROFILES`).

### Cost posture (estimates only)

Relative to the heavy default stack, `production-lean` targets approximately
**75–90% lower** monthly infra cost; relative to a lean-ish stack, approximately
**50–70% lower**. These are estimates; the enforceable guarantee is the
forbidden-resource policy, not a dollar figure.

## Terraform enforcement (deployment_profile)

The infrastructure at `AWS Deployment/aether-aws/terraform/` selects a profile
through the `deployment_profile` variable (validated to one of `staging`,
`production-lean`, `production-scale`, `enterprise-isolated`; default
`production-lean`). Ready-made variable files live under `profiles/`:

```bash
terraform apply -var-file=profiles/production-lean.tfvars
terraform apply -var-file=profiles/production-scale.tfvars
```

`profiles.tf` derives a set of `enable_*` resource toggles from the profile. For
`production-lean` every toggle for a forbidden resource is false by derivation —
each is `local.scale || local.enterprise` (false when lean) or literal `false`:

| Forbidden resource | Terraform local |
|---|---|
| `msk` | `enable_msk` |
| `elasticache` | `enable_elasticache` |
| `neptune` | `enable_neptune` |
| `clickhouse` | `enable_clickhouse` |
| `dedicated_ml_service` | `enable_dedicated_ml` |
| `frontend_ecs_services` | `enable_frontend_ecs` |
| `legacy_rds` | `enable_legacy_rds` (literal `false`) |
| `nat_gateway_unless_explicit` | `enable_nat_gateway` |
| `prometheus_grafana_servers` | `enable_prometheus_grafana` |

`make validate-cost-policy-terraform`
(`scripts/release/check_cost_policy_terraform.py`) statically asserts that these
locals resolve to false for `production-lean`, that the `deployment_profile`
variable and its validation exist, and that each `profiles/*.tfvars` sets a valid
profile matching its filename. It runs in `release-gate` and
`founding-tenant-release-gate` (not in `ci-check`).

Wiring these locals into module `count`/configuration so the plan physically
omits the resources is deferred (see the `TODO(FT-9-TERRAFORM-PROFILES)` note in
`profiles.tf`); until then the static validator is the enforceable guarantee.

## Backend selectors

Each profile declares a selector for every backend dimension (`database`,
`cache`, `event`, `graph`, `analytics`, `object`, `ml`). Runtime enforcement of
these selectors (rejecting memory backends in production, explicit worker roles)
is tracked in the ledger as `FT-4-RUNTIME-ROLES`.
