# ClickHouse Provisioning Contract

The production-scale and enterprise-isolated deployment profiles declare
`analytics: clickhouse` (see `config/deployment_profiles.yaml` and
`AWS Deployment/aether-aws/terraform/profiles.tf`). This file is the contract
for turning that declaration into a running analytics backend.

AWS has no managed ClickHouse service, so the appliance is **self-managed on
EC2 + a dedicated EBS volume**. There is deliberately no separate Terraform
module directory under `deploy/terraform/clickhouse/`: the provisioning module
lives with the rest of the infrastructure at:

    AWS Deployment/aether-aws/terraform/modules/clickhouse/

and is wired into the root `main.tf` (count-gated on
`local.enable_clickhouse`, which is true for exactly production-scale and
enterprise-isolated). Keep the module and the profile selector in sync here.

## Provisioning summary

| Piece | Where | Notes |
|---|---|---|
| EC2 appliance (`m6i.large` default) | `modules/clickhouse` | Amazon Linux 2023, `ami_id` required (root defaults `var.clickhouse_ami_id` per region) |
| Dedicated data volume (100 GiB gp3 default) | `modules/clickhouse` | `aws_ebs_volume clickhouse_data`, `lifecycle.prevent_destroy` |
| Mount at `/var/lib/clickhouse` | `locals.user_data` in the module | Idempotent bootstrap; installs ClickHouse from the official RPM repo |
| CloudWatch log group | `modules/clickhouse` | `/aether/{project}-{environment}/clickhouse`, retention `var.log_retention_days` |
| Security group | `modules/clickhouse` | Native TCP **9000** and HTTP **8123** ingress from the ECS task SG only |

The module is reachable only from the ECS task security group; it carries
`lifecycle.prevent_destroy` on both the instance and the disk, so toggling the
profile off ClickHouse fails closed instead of auto-destroying analytics state.

## Runtime endpoints

- Native protocol (the protocol the runtime uses): `CLICKHOUSE_HOST:9000`
- HTTP interface: `CLICKHOUSE_HOST:8123`

`CLICKHOUSE_HOST` is injected by `modules/ecs` into both the API and worker
task definitions, gated on `analytics_backend == "clickhouse"` (it stays absent
for every postgres-analytics profile). `shared/cis/clickhouse.py` reads it via
`CLICKHOUSE_HOST` / `CLICKHOUSE_PORT`; `scripts/validate_infra.py` requires
`CLICKHOUSE_HOST` to be set exactly when a profile declares `analytics:
clickhouse`, so a postgres profile must never receive the host and a clickhouse
profile must always receive it.

## Schema / DDL application

The appliance boots with no schema. The analytics schema is owned by the DDL
files under:

    deploy/clickhouse/schemas/001_cis_retrieval_traces.sql ... 008_measurement_gold.sql

Applied in numeric order against the native endpoint by the release pipeline as
part of provisioning (a migration job, not part of the Terraform module). The
DDL is idempotent (`CREATE TABLE IF NOT EXISTS`). A new schema file must be
numbered after the current highest and applied by the same ordered job; the
numbering is the ordering — do not rename existing files.

## Environment contract (infra variables)

| Variable | Meaning | Required for clickhouse profiles |
|---|---|---|
| `clickhouse_ami_id` | AL2023 AMI (region-pinned; override per region) | yes (has a us-east-1 default) |
| `clickhouse_instance_type` | Appliance instance type | no (default `m6i.large`) |
| `clickhouse_data_volume_size` | Data volume GiB | no (default 100) |

## Apply-time wiring that must exist

- `module.clickhouse` in root `main.tf`, count = `local.enable_clickhouse`
- `clickhouse_host = try(module.clickhouse[0].hostname, "")` in the section-4z
  normalized locals (empty for postgres profiles)
- `clickhouse_host = local.clickhouse_host` passed into `module.ecs`
- `CLICKHOUSE_HOST` / `CLICKHOUSE_PORT=9000` in the ECS API and worker task env
  (gated on `analytics_backend == "clickhouse"`)

The plan test `tests/profile_plan.tftest.hcl` asserts `length(module.clickhouse)
== 0` for the four cost-capped profiles and `== 1` for scale and enterprise, so
the count wiring is verified offline by `terraform test`.
