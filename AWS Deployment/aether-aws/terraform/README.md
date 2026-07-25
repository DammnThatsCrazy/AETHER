# AETHER — Terraform Infrastructure

Production AWS infrastructure for the AETHER platform, managed with Terraform.

**This directory is the only live Terraform tree.** See
[Dead second Terraform tree](#dead-second-terraform-tree) before you go looking
for `environments/`.

## Deployment profiles

Nearly every cost-relevant decision in this root is made by one variable:

```hcl
deployment_profile = "staging" | "production-lean" | "production-scale" | "enterprise-isolated"
```

`profiles.tf` turns that into `enable_*` locals and backend selectors, and
`main.tf` wires those into module `count` and module inputs. A profile is not
documentation — a `production-lean` plan structurally cannot contain a
forbidden resource.

The canonical policy data lives in `config/deployment_profiles.yaml`;
`config/terraform_resource_contracts.yaml` maps each policy key to the module
address and cardinality a conforming plan must show.

| | staging | production-lean | production-scale | enterprise-isolated |
|---|---|---|---|---|
| Database | Aurora Serverless v2 | Aurora Serverless v2 | Aurora Serverless v2 | Aurora Serverless v2 |
| Cache | DynamoDB | DynamoDB | ElastiCache Redis | ElastiCache Redis |
| Events | SNS → SQS | SNS → SQS | MSK Kafka | MSK Kafka |
| Graph | Aurora Postgres | Aurora Postgres | Neptune | Neptune |
| Analytics | Postgres | Postgres | ClickHouse (selector only) | ClickHouse (selector only) |
| ML serving | inline in backend | inline in backend | dedicated ECS service | dedicated ECS service |
| Egress | `public_ip` (no NAT) | `public_ip` (no NAT) | `single_nat` | `ha_nat` (one per AZ) |
| Legacy RDS | never | never | never | never |
| Frontends | S3 static origins | S3 static origins | S3 static origins | S3 static origins |

Apply a profile with its checked-in variable file:

```bash
cd "AWS Deployment/aether-aws/terraform"
terraform plan -var-file=profiles/production-lean.tfvars -out=tfplan
```

### Network egress

`network_egress_mode` replaces the old `enable_nat_gateway_ha` bool, which
could only choose between one NAT Gateway and three and had no way to say "no
NAT at all" — the posture the cost-capped profiles actually want.

| Value | NAT Gateways | ECS task subnets | ECS task networking |
|---|---|---|---|
| `public_ip` | 0 | **public** | public IP on the task ENI, egress via the IGW |
| `single_nat` | 1 shared | private | no public IP, egress via NAT |
| `ha_nat` | 1 per AZ | private | no public IP, egress via NAT |
| `vpc_endpoints` | 0 | private | no egress — see the caveat below |
| `none` | 0 | private | no egress |

The subnet column is load-bearing, not incidental. With `public_ip` there is no
NAT Gateway, so `aws_route.private_nat` has count 0 and the private route
tables carry **no** `0.0.0.0/0` route at all. A task ENI placed there has no
path to ECR, Secrets Manager or CloudWatch, and `assign_public_ip` does not
rescue it — egress follows the *subnet's* route table, not the ENI. Tasks
therefore run in the public subnets, which have the IGW default route, and the
root derives that from `local.assign_public_ip` in one place
(`local.ecs_task_subnet_tier` in `main.tf`). `tests/profile_plan.tftest.hcl`
pins the resulting placement per profile.

Data stores are unaffected by all of this: they are in the isolated subnets in
every profile and never move.

`vpc_endpoints` and `none` both place tasks privately with no route out.
Neither is usable today — `modules/vpc_endpoints` exists but the root
instantiates no module block for it, so `vpc_endpoints` provisions no endpoints
and behaves exactly like `none`. No profile or workflow sets either value.

Omit the variable to take the profile default. `nat_gateway_unless_explicit` is
a forbidden resource for `production-lean`; **setting this variable to a NAT
mode on a cost-capped profile is that explicit opt-in**, and must be reviewed
as a cost-policy exception.

### Runtime roles and services

`config/runtime_deployment.yaml` is the canonical runtime matrix. Since schema
v2 the deployable unit is a **service**, not a role, and how roles map onto
services is a per-profile decision recorded as `execution_mode`:

| Profile | `execution_mode` | Non-`api` ECS services |
|---|---|---|
| `production-lean` | `consolidated` | **one** — `lean-worker`, whose single task hosts all eight worker roles |
| `staging` | `consolidated` | **one** — same shape, so staging rehearses lean's packing |
| `production-scale` | `dedicated` | **eight** — one service per worker role |
| `enterprise-isolated` | `dedicated` | **eight** — one service per worker role |

The `api` role is served by the `-backend` service in every profile; that is
the one naming exception in the matrix.

Consolidation moves the process boundary and nothing else. Inside a packed task
each role keeps its own SQS queue, consumer group, dead-letter queue and
metrics — which is why `modules/ecs` hands a service `SQS_ROLE_QUEUE_URLS` and
`SQS_ROLE_DLQ_URLS` (one entry per hosted role) rather than a single queue URL.
Roles are never collapsed into an *implicit* worker: every role in
`roles.py::WORKER_ROLES` is named by exactly one service's `roles:` list in
every profile, which `scripts/release/check_delivery_topology.py` enforces.
`local.runtime_execution_mode` reads the mode from the matrix rather than
inferring it from how many services happen to exist.

## Architecture

```
Internet
   │
   ├── S3 static origins (aether SPA, kyber SPA) ─── behind the CDN
   │
   └── ALB (public subnets, HTTPS with ACM cert)
          │
          ├── /v1/ml/*  ──► ECS aether-ml-serving  [production-scale / enterprise-isolated only]
          │                 (lean/staging: no rule, falls through to the backend, ML runs inline)
          │
          └── *  ─────────► ECS aether-backend  (api role)
                            ECS worker services — one `lean-worker` task
                            hosting all eight roles on lean/staging, or one
                            service per role on scale/enterprise (outbox-relay,
                            stream-worker, identity-worker, graph-writer,
                            measurement-worker, semantic-worker, materializer,
                            maintenance)
                                  │
                                  ├── Aurora Serverless v2   (isolated subnets)  — all profiles
                                  ├── DynamoDB cache table                        — all profiles
                                  ├── SNS fanout → per-role SQS queues + DLQs     — all profiles
                                  ├── ElastiCache Redis      (isolated subnets)  — scale / enterprise
                                  ├── MSK Kafka              (isolated subnets)  — scale / enterprise
                                  └── Neptune                (isolated subnets)  — scale / enterprise
```

All secrets are fetched at container start-up from Secrets Manager. No secret
values appear in task definitions. Aurora credentials use AWS-managed master
password rotation; Redis (when provisioned) uses a Terraform-generated token
stored only in Secrets Manager, and the `redis-auth-token` secret reference is
omitted entirely from the task definition on profiles without Redis.

## Module Summary

Modules marked **gated** are provisioned only for the profiles listed.

| Module | Resources | Gate |
|--------|-----------|------|
| `vpc` | VPC, 3-tier subnets (public/private/isolated), security groups, flow logs, NAT per `nat_mode` | always; NAT and the redis/msk/neptune SGs are gated |
| `ecr` | 4 private ECR repositories with lifecycle policies | always |
| `secrets` | Secrets Manager stubs (KMS-encrypted), rotation Lambda | always |
| `aurora` | Aurora Serverless v2 Postgres cluster + writer, KMS | always — database and graph of record |
| `dynamodb_cache` | DynamoDB cache table with read/write autoscaling | always |
| `sqs` | SNS fanout topic, shared + per-role SQS queues, DLQs | always |
| `alb` | Internet-facing ALB, HTTP→HTTPS redirect, backend target group | always; **gated** ML target group + `/v1/ml/*` rule |
| `ecs` | Fargate cluster, backend service, the profile's worker services (one consolidated or eight dedicated), IAM roles, autoscaling | always; **gated** dedicated ML service |
| `monitoring` | SNS alerts, CloudWatch alarms, dashboard, S3 log archive | always; per-backend alarms **gated** |
| `ml_drift_lambda` | Nightly PSI drift check → `Aether/MLDrift` namespace | always |
| `auth0` | SPA clients + API resource server | always |
| `elasticache` | Redis 7.x, TLS in transit, AUTH token, KMS at rest | **gated** — scale / enterprise |
| `msk` | 3-broker MSK Kafka, TLS, KMS, CloudWatch metrics | **gated** — scale / enterprise |
| `neptune` | Neptune cluster + instances, IAM auth, KMS | **gated** — scale / enterprise |
| `rds` | Legacy RDS Postgres 16 | **never** — superseded by Aurora; see `DECOMMISSION.md` |

`modules/s3` and `modules/vpc_endpoints` exist on disk but are not instantiated
by this root.

### Alarms follow the backend

A profile that swaps Redis for DynamoDB and Kafka for SQS must ship alarms for
DynamoDB and SQS, or the cost reduction has silently bought an observability
gap. `monitoring` therefore always creates `alb_5xx`, `aurora_max_acu`,
`ml_drift`, `dynamodb_cache_throttled`, `sqs_queue_depth`,
`sqs_oldest_message_age` and `sqs_dlq_depth`, and creates
`elasticache_memory`, `msk_offline_partitions` and `neptune_cpu` only when the
matching store exists. Alarms are never left pointing at a dimension that does
not exist — a permanent `INSUFFICIENT_DATA` alarm masks real alerts.

## Normalized connection locals

Gating a module with `count` turns its outputs into a list. Nothing in this
root reads a gated module's output directly; everything goes through the
normalized locals in `main.tf` section 4z (`local.redis_host`,
`local.kafka_bootstrap_servers`, `local.neptune_endpoint`, …), which resolve to
`""` when the backend is absent.

The idiom is `try(module.x[0].out, "")`, **not** `try(one(module.x[*].out), "")`.
`one([])` returns `null` and `try` only traps errors, so the `one()` form
yields `null` and feeds a null into a string input. Indexing the empty list
raises, so `try` actually fires.

Which backend the running task uses is passed explicitly
(`event_broker`, `cache_backend`, `graph_backend`, `analytics_backend`) rather
than inferred from whether a host string happens to be empty.

## State migrations

`moved.tf` covers every address change introduced by the profile gating: the
four root modules that gained a `count`, and the in-module dedicated-ML
resources in `modules/ecs` and `modules/alb`. Without those blocks an applied
`production-scale` workspace would plan a destroy-and-recreate of live MSK,
ElastiCache, Neptune and ML resources. Do not delete them until every workspace
has applied at least once.

## Prerequisites

- **AWS CLI** >= 2.x with credentials for the target account.
- **Terraform** 1.7 to 1.x, matching `versions.tf`'s `required_version = "~> 1.5"`.
  1.7 is the effective floor even though the pin permits 1.5: the test suite
  uses `mock_provider`, `mock_resource` and `override_module`, none of which
  exist before 1.7, so `terraform test` fails on 1.5 or 1.6 while `plan` and
  `apply` still work. Do not widen `versions.tf` to `>= 1.7` without checking
  every runner: `~> 1.5` also pins the major version, which is what stops a
  future 2.x from being picked up silently.
- An ACM certificate in the target region for your domain name.
- An S3 bucket + DynamoDB table for Terraform remote state.

## Initialization

```bash
cd "AWS Deployment/aether-aws/terraform"

cp terraform.tfvars.example terraform.tfvars
$EDITOR terraform.tfvars

terraform init

terraform plan -var-file=profiles/production-lean.tfvars -out=tfplan
terraform apply tfplan
```

`backend_image_digest` and `ml_image_digest` have no defaults: every plan must
pin the exact digests approved by the release manifest.

## Tests

```bash
terraform test -filter=tests/profile_plan.tftest.hcl
```

Four provider-mocked run blocks, one per profile, assert the planned graph:
module cardinality for each gated backend, NAT Gateway and EIP counts, the
dedicated-ML service and its ALB target group, the required lean resources, and
that the normalized locals collapse to `""` rather than `null`. No AWS
credentials are needed.

## Deployment Sequence

Terraform handles dependency ordering automatically. The high-level sequence:

1. **VPC** — subnets, security groups, NAT per `nat_mode`
2. **ECR** — container registries
3. **Secrets** — Secrets Manager stubs
4. **Data stores** — Aurora, DynamoDB and SQS/SNS always; ElastiCache, MSK and
   Neptune only when the profile enables them
5. **ALB** — load balancer and target groups
6. **ECS** — cluster, task definitions, backend + the profile's worker services
7. **Monitoring** — alarms, SNS, dashboard

## Post-Deploy Steps

### 1. Confirm SNS email subscription

AWS sends a confirmation email to `alert_email`. Click the confirmation link
before alarms will deliver notifications.

### 2. Inject secret values

The Secrets Manager stubs are created empty. Populate them:

```bash
aws secretsmanager put-secret-value \
  --secret-id aether/jwt-secret \
  --secret-string 'REPLACE_WITH_SECURE_RANDOM_256BIT_KEY'

aws secretsmanager put-secret-value \
  --secret-id aether/stripe-secret-key \
  --secret-string 'sk_live_...'

# BYOK encryption key, oracle signer, watermark key, canary seed
# (follow the same pattern for each secret in modules/secrets/main.tf)
```

> **Note:** Store raw secret strings, not JSON objects. ECS `valueFrom` ARNs
> inject the entire secret string into the container — a JSON wrapper would
> require a JSON-key suffix on the ARN and is error-prone.

`aether/db-password` is populated automatically by the Aurora module via
AWS-managed master password rotation and contains JSON with `host`, `port`,
`username`, `password`, `dbname`. `aether/redis-auth-token` is populated by the
ElastiCache module and exists only on profiles that provision Redis.

### 3. Build and push Docker images

```bash
AWS_ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
AWS_REGION=us-east-1

aws ecr get-login-password --region $AWS_REGION | \
  docker login --username AWS --password-stdin \
  "${AWS_ACCOUNT}.dkr.ecr.${AWS_REGION}.amazonaws.com"

docker build -t aether-backend ./backend
docker tag aether-backend:latest \
  "${AWS_ACCOUNT}.dkr.ecr.${AWS_REGION}.amazonaws.com/aether-backend:latest"
docker push \
  "${AWS_ACCOUNT}.dkr.ecr.${AWS_REGION}.amazonaws.com/aether-backend:latest"
```

The ML image is only needed on profiles that run the dedicated ML service.

### 4. Force ECS to pick up the new images

Task definitions pin an immutable digest, so a new digest is a new task
definition and deploys itself. To redeploy an unchanged digest:

```bash
aws ecs update-service \
  --cluster AETHER-production \
  --service AETHER-production-backend \
  --force-new-deployment
```

Repeat for each runtime-role service (see the `ecs_runtime_role_service_names`
output).

### 5. Run database migrations

Execute migrations from within the VPC (ECS Exec, a bastion, or a one-off
Fargate task):

```bash
aws ecs run-task \
  --cluster AETHER-production \
  --task-definition AETHER-production-backend \
  --launch-type FARGATE \
  --network-configuration "awsvpcConfiguration={subnets=[...],securityGroups=[...],assignPublicIp=DISABLED}" \
  --overrides '{"containerOverrides":[{"name":"aether-backend","command":["python","-m","alembic","upgrade","head"]}]}'
```

On a profile with `network_egress_mode = "public_ip"`, use the **public**
subnets and set `assignPublicIp=ENABLED`. Both halves are required: there is no
NAT to egress through, and a public IP in a private subnet still has no default
route. `terraform output public_subnet_ids` gives the right list.

## Outputs Reference

```bash
terraform output
terraform output -raw alb_dns
terraform output ecr_urls
```

| Output | Description |
|--------|-------------|
| `alb_dns` | ALB DNS name — create a CNAME alias in Route 53 |
| `backend_url` | HTTPS URL derived from `domain_name` |
| `ecr_urls` | Map of service → ECR URL |
| `sqs_events_queue_url` | SQS events queue URL |
| `sqs_fanout_topic_arn` | SNS fanout topic ARN |
| `dynamodb_cache_table_name` | DynamoDB cache table name |
| `ecs_runtime_role_service_names` | Service key → ECS service name (one key per declared service, so a consolidated profile has a single `lean-worker` entry hosting eight roles) |
| `redis_endpoint` | Redis `host:port`, or `""` on a DynamoDB-cache profile |
| `kafka_brokers` | MSK TLS broker list, or `""` on an SNS/SQS profile |
| `neptune_endpoint` | Neptune writer endpoint, or `""` on a Postgres-graph profile |
| `rds_endpoint` | Legacy RDS address — `""`, RDS is not provisioned by any profile |
| `secret_arns` | Map of secret name → ARN |
| `cloudwatch_dashboard_url` | Direct link to the CloudWatch dashboard |

## Tear-down

Removing applied infrastructure — including turning a backend off by changing
the deployment profile — goes through **[`DECOMMISSION.md`](./DECOMMISSION.md)**.
Flipping a profile toggle must never auto-destroy applied stateful
infrastructure. If a profile change plans a destroy on a data store, stop.

## Dead second Terraform tree

`AWS Deployment/aether-aws/terraform/environments/{dev,staging,production,demo}/`
and `AWS Deployment/main.tf` are a **second, dead Terraform tree**. They are not
the deployment path, nothing applies them, and `terraform init` fails there:
between them they reference seven modules that do not exist in this repository
— `cloudfront`, `opensearch`, `dynamodb`, `sagemaker`, `api_gateway`, `iam` and
`waf`.

Do not modify, extend or "fix" that tree, and do not copy patterns out of it.
It describes an architecture Aether does not run. The live root is this
directory, and the live variable surface is `variables.tf` plus
`profiles/*.tfvars`.

## Security Notes

- No secret values are stored in Terraform state or code.
- Data stores live in isolated subnets with no default route.
- ECS tasks use dedicated IAM roles with least-privilege policies scoped to the
  queues, tables and secrets the selected profile actually provisions.
- The ALB enforces TLS 1.3 minimum with `ELBSecurityPolicy-TLS13-1-2-2021-06`.
- VPC Flow Logs capture all traffic for audit purposes.
- On `public_ip` profiles, ECS tasks run in the public subnets and carry a
  public IP for egress. Inbound access is governed entirely by the task
  security group, which admits ports 8000 and 8080 from the ALB's security
  group and carries no CIDR ingress of any kind, so the public IP buys egress
  and nothing else. `tests/profile_plan.tftest.hcl` asserts that invariant on
  every profile that uses public placement — treat it as a gate, not a comment.
- Auth0 management credentials are **not** Terraform variables. `terraform show
  -json` reproduces every root variable in its top-level `variables` object
  regardless of `sensitive = true`, so a credential declared there is a
  credential in every plan artifact. The `auth0` provider reads `AUTH0_DOMAIN`,
  `AUTH0_CLIENT_ID` and `AUTH0_CLIENT_SECRET` from the runner's environment
  instead; `TF_VAR_auth0_*` names are no longer read by anything.
