---
title: AWS Deployment — Infrastructure Reference
slug: operations/aws-deployment
section: operations
visibility: I
audience: [ops, security, architect]
status: stable
since_version: "8.8.0"
source_files:
  - AWS Deployment/aether-aws/README.md
  - AWS Deployment/aether-aws/main.py
  - AWS Deployment/aether-aws/terraform/
  - AWS Deployment/aether-aws/config/
  - scripts/release/verify_terraform_state_role.py
  - .github/workflows/terraform-promote.yml
  - .github/workflows/staging-state-reconcile.yml
  - scripts/release/verify_effective_staging_apply_policy.py
  - config/staging_apply_iam_policy.yaml
canonical_owner: platform@aether
estimated_read_minutes: 18
toc_depth: 3
last_synced_commit: "beed2f70"
---

# AWS Deployment — Infrastructure Reference

Internal reference for Aether's AWS infrastructure as the Terraform in this
repository actually defines it.

Staging applies use a dedicated least-privilege role covering state locking,
staging-only tagging, KMS administration, and the explicit apply-role ARN;
cleanup remains bounded by the staging lifecycle guard. The apply contract also
checks ECR ownership before mutation: an existing repository that is not in
the reviewed Terraform state is a hard stop, so shared repositories are never
silently adopted or replaced, and that collision check runs before the
account-level ECS service-linked role bootstrap. Secrets, ECR, and Aurora CMKs carry the staging
environment tag; the Secrets Manager and regional CloudWatch Logs service
principals are constrained by ViaService, caller account, and encryption
context rather than broad key access. The pre-apply verifier compares the
attached policy statements with the reviewed staging manifest, including
resource coverage, conditions, and explicit Deny statements, before any
Terraform mutation.

The staging ECR repositories have one deliberate pre-existing exception:
`aether-backend` is an immutable AES-256 repository created by the release
pipeline before Terraform state ownership. Its encryption cannot be changed
after creation, so staging Terraform declares that exact shape and the
import-only reconciliation workflow adopts it without replacement. The other
three staging ECR repositories remain mutable and use the staging KMS key.
Before clearing a taint, reconciliation also verifies that the canonical
Terraform address stores the same repository name requested by the operator;
an address that points at a different repository, or is no longer tainted, is
refused before state is mutated. Duplicate-owner inspection tolerates
human-formatted Terraform state output spacing. The reconciliation workflow
snapshots the complete Terraform address list before performing membership
checks. This avoids `EPIPE` races caused by piping Terraform through an
early-exiting `grep -q` under `pipefail`, which could otherwise make an
already-managed staging resource look absent and trigger a false import or
taint-repair failure.

The reviewed Terraform promotion writes a secret-free `reviewed.api-host`
evidence file after an apply. This is the configured `domain_name` hostname
covered by the ACM certificate, not the raw `*.elb.amazonaws.com` ALB name.
Because the DNS edge is managed outside this Terraform root, promotion publishes
both values without making a completed apply fail while the operator-managed
hostname propagates to a new ALB. The staging lifecycle consumes both evidence
files and performs the fail-closed intersection check immediately before
readiness, the awake lease, and HTTPS rehearsal requests. The raw ALB name is
retained separately as diagnostic evidence, and neither value is a manually
maintained GitHub variable that can be required before the first load balancer
exists. The same lifecycle creates run-scoped rehearsal tenants and
API keys after wake, masks those keys in the runner, and deletes or deactivates
every marker-recorded tenant during its always-run cleanup. The only durable
rehearsal credential is the encrypted staging admin bootstrap key, which is
supplied out of band and never generated or echoed by CI.

## Scope — three different things live under `AWS Deployment/`

Read this section before anything else. Conflating these three is the single
most common way to end up describing infrastructure that does not exist.

| Path | What it is |
|---|---|
| `AWS Deployment/aether-aws/terraform/` | **The live Terraform root.** One VPC, one account, profile-driven. Everything in this page's *Live infrastructure* sections describes this and only this. |
| `AWS Deployment/aether-aws/{README.md,main.py,config/aws_config.py}` and the `scripts/` package | A **reference/demo model**, not provisioning code. `main.py` is a demo runner that prints a six-account, five-VPC architecture from constants in `config/aws_config.py`. It does not wrap `terraform`, it has no `plan`/`apply` commands, and nothing it prints is provisioned by the live root. See [Reference model](#reference-model--described-not-provisioned). |
| `AWS Deployment/aether-aws/terraform/environments/{dev,staging,production,demo}/` and `AWS Deployment/main.tf` | A **dead second Terraform tree**. See [Dead second tree](#dead-second-terraform-tree). |

`AWS Deployment/aether-aws/main.py` does **not** deploy anything, and there is
no `dr_failover.py` anywhere in the repository.

---

## Live infrastructure

### Profile selection

Nearly every cost- and shape-relevant decision in the root is made by one
variable:

```hcl
deployment_profile = "staging" | "production-lean" | "production-scale" | "enterprise-isolated" | "demo" | "preview"
```

`profiles.tf` derives `enable_*` locals and backend selectors from it and
`main.tf` wires those into module `count` and module inputs, so a
`production-lean` plan structurally cannot contain a forbidden resource.
The four cloud-class profiles plus the two ephemeral-class profiles
(demo/preview) are Terraform-selectable from this root; the parity contract
pins the selectable set to cloud ∪ ephemeral.
Canonical policy data is `config/deployment_profiles.yaml`;
`config/terraform_resource_contracts.yaml` maps each policy key to the module
address and cardinality a conforming plan must show. The per-profile matrix,
including the four non-cloud profiles, is
[Deployment Profiles](DEPLOYMENT-PROFILES.md).

| | staging | production-lean | production-scale | enterprise-isolated |
|---|---|---|---|---|
| Database | Aurora Serverless v2 | Aurora Serverless v2 | Aurora Serverless v2 | Aurora Serverless v2 |
| Aurora ACU floor / ceiling | 0 / 2 | 0.5 / 4 | 1 / 8 | 2 / 16 |
| Cache | DynamoDB | DynamoDB | ElastiCache Redis | ElastiCache Redis |
| Events | SNS → SQS | SNS → SQS | MSK Kafka | MSK Kafka |
| Graph | Aurora Postgres | Aurora Postgres | Neptune | Neptune |
| Analytics | Postgres | Postgres | ClickHouse (selector only) | ClickHouse (selector only) |
| ML serving | inline in backend | inline in backend | dedicated ECS service | dedicated ECS service |
| Egress | `public_ip` — **0 NAT** | `public_ip` — **0 NAT** | `single_nat` — 1 NAT | `ha_nat` — 3 NAT |
| Legacy RDS | never | never | never | never |
| Frontends | S3 static origins | S3 static origins | S3 static origins | S3 static origins |
| Log retention | 3 days | 3 days | 7 days | 30 days |

Apply a profile with its checked-in variable file:

```bash
cd "AWS Deployment/aether-aws/terraform"
terraform plan -var-file=profiles/production-lean.tfvars -out=tfplan
```

`backend_image_digest` is always required and is validated against
`^sha256:[0-9a-f]{64}$`. `ml_image_digest` is required for the dedicated
production-scale and enterprise-isolated profiles; lean, staging, demo, and
preview profiles may leave it empty when `remote_ml` is disabled. Every digest
that is supplied is still pinned to the exact release-manifest value.

The apply preflight verifies the selected profile's exact Terraform state key
(`profiles/<profile>/terraform.tfstate`) against the assumed role. It does not
probe a synthetic object path or broaden access beyond the reviewed state
prefix.

### Account and environment topology

**One AWS account and one region per workspace.** `var.aws_region` defaults to
`us-east-1`, `var.project` to `AETHER`, and `var.environment` to `production`
(validated to `production | staging | dev | demo | preview`). Resource names
are built as `${var.project}-${var.environment}`.

Only `profiles/staging.tfvars` overrides `environment`. **The three
production-class profiles all inherit `production` and therefore generate
identical resource names** — ECS cluster, ALB, log groups, IAM roles, SQS
queues, S3 buckets. Separate Terraform state keys
(`profiles/<profile>/terraform.tfstate`) keep the *state* apart and do nothing
about the *names*. Two production-class profiles cannot be applied into the same
account and region; **they require separate AWS accounts.** This is a known,
unfixed constraint recorded in `DECOMMISSION.md`, and it is why a side-by-side
comparison of two production-class profiles is not currently possible.

Remote state is mandatory (`backend "s3" {}` with no inline configuration);
bucket, key, lock table and region are injected per profile at `init` time by
the workflows. Terraform `~> 1.5`, AWS provider `~> 5.0`, plus the `random`,
`auth0` and `archive` providers.

### Networking

**One VPC per workspace**, `var.vpc_cidr` default `10.0.0.0/16`, with three
subnet tiers computed as `/20`s across the region's availability zones:

| Tier | Purpose |
|---|---|
| public | ALB, and NAT gateways when the profile has any |
| private | ECS tasks |
| isolated | Aurora, and ElastiCache / MSK / Neptune where provisioned. No default route. |

Egress is chosen by `var.network_egress_mode`, which replaced the old
`enable_nat_gateway_ha` boolean because that could only choose between one NAT
and three and had no way to express "no NAT at all" — the posture the
cost-capped profiles actually want.

| Value | NAT gateways | Elastic IPs | ECS task networking |
|---|---|---|---|
| `public_ip` | 0 | 0 | public IP on the task ENI |
| `single_nat` | 1 shared | 1 | private, egress via NAT |
| `ha_nat` | 1 per AZ | 1 per AZ | private, egress via NAT |
| `vpc_endpoints` | 0 | 0 | private, no general egress |
| `none` | 0 | 0 | private, no egress |

Omit the variable to take the profile default. `nat_gateway_unless_explicit` is
a forbidden resource for `production-lean` and `staging`; **setting this
variable to a NAT mode on a cost-capped profile is that explicit opt-in** and
must be reviewed as a cost-policy exception.

The private default route is a standalone `aws_route.private_nat`, counted
independently, which is what makes a private route table with no egress path
expressible at all. VPC flow logs are enabled on the VPC.

### Compute — ECS Fargate

All application compute is ECS Fargate. There are no EC2 instances to manage,
and no self-managed Prometheus or Grafana servers at any profile.

The deployable unit is a **service**, not a role, and the service count depends
on the profile's `execution_mode` in `config/runtime_deployment.yaml`:

**`consolidated` — `staging`, `production-lean`, `demo` and `preview`: two always-on tasks.**

| Service | Roles hosted | vCPU / MiB (lean) | Desired | Max | Capacity |
|---|---|---|---|---|---|
| `api` (ECS service `AETHER-<env>-backend`) | `api` | 1024 / 2048 | 1 | 4 | FARGATE only |
| `lean-worker` | `outbox-relay`, `stream-worker`, `identity-worker`, `graph-writer`, `measurement-worker`, `semantic-worker`, `materializer`, `maintenance` | 2048 / 8192 | 1 | 4 | FARGATE only |

Staging, `demo` and `preview` run the same shape one size down (`lean-worker`
at 1024 / 4096, max 2).
`lean-worker` never uses Spot at any capacity because it hosts `outbox-relay`,
the at-least-once delivery path.

**`dedicated` — `production-scale` and `enterprise-isolated`: nine services.**

| Service | Desired | Max | vCPU / MiB | Surge capacity (scale) |
|---|---|---|---|---|
| `api` | 3 | 12 | 2048 / 4096 | FARGATE |
| `outbox-relay` | 2 | 6 | 1024 / 2048 | FARGATE |
| `stream-worker` | 3 | 12 | 2048 / 4096 | FARGATE_SPOT |
| `identity-worker` | 2 | 8 | 1024 / 2048 | FARGATE_SPOT |
| `graph-writer` | 2 | 8 | 1024 / 2048 | FARGATE_SPOT |
| `measurement-worker` | 2 | 8 | 1024 / 2048 | FARGATE_SPOT |
| `semantic-worker` | 2 | 8 | 1024 / 2048 | FARGATE_SPOT |
| `materializer` | 2 | 8 | 1024 / 2048 | FARGATE_SPOT |
| `maintenance` | 1 | 1 | 1024 / 2048 | FARGATE (no queue to drain) |

`enterprise-isolated` uses the same sizing with **no Spot anywhere**: a
reclaimed surge task is an availability event to explain, not a discount to
report. Spot is forbidden outright on `api` and on any service hosting
`outbox-relay`, enforced by
`scripts/release/check_delivery_topology.py::SPOT_FORBIDDEN_ROLES`.

Autoscaling is `alb-request-count-per-target` at 800 requests/target for `api`
and `sqs-queue-depth` for workers (500 messages/task on the delivery path, 1000
elsewhere), with 180 s / 300 s cooldowns. `min_capacity` equals the desired
count and is the always-on floor; `max_capacity` is the surge ceiling.

A dedicated `aether-ml-serving` service, its ALB target group and its
`/v1/ml/*` listener rule exist only on `production-scale` and
`enterprise-isolated`. On the cost-capped profiles there is no rule and ML runs
inline in the backend process.

`staging_state = "asleep"` multiplies every desired count, every autoscaling
floor and every capacity-provider base count by zero, so a sleeping staging
environment owns exactly the same services as an awake one. `max_capacity` is
deliberately not scaled.

### Data stores

| Store | Provisioned on | Notes |
|---|---|---|
| Aurora Serverless v2 Postgres + writer | **all profiles** | Database, graph and analytics of record. Isolated subnets, customer-managed KMS key, AWS-managed master password rotation into `aether/db-password`. |
| DynamoDB cache table | **all profiles** | Read/write autoscaling, TTL-backed. |
| SNS fanout topic → per-role SQS queues + DLQs | **all profiles** | One queue per role, so a consolidated task binds one queue per hosted role. |
| S3 object lake, log archive, SPA origins | **all profiles** | Public access blocked, SSE configured. |
| Secrets Manager + KMS | **all profiles** | Stubs created empty; rotation Lambda. |
| ElastiCache Redis 7.x | scale / enterprise | TLS in transit, AUTH token in Secrets Manager only, KMS at rest. `cache.t3.micro` default. |
| MSK Kafka | scale / enterprise | 3 brokers (`kafka.m5.large`, Kafka 3.5.1), TLS, KMS, CloudWatch metrics. |
| Neptune | scale / enterprise | `db.r6g.large`, cluster size 1 by default, IAM auth, KMS. |
| Legacy RDS Postgres | **never** | `enable_legacy_rds` is the literal `false`. Retained in code only as an importable rollback target — see `DECOMMISSION.md`. |

There is **no OpenSearch, no SageMaker, no Athena, no TimescaleDB and no
ClickHouse resource** in this root. `analytics: clickhouse` on the two uncapped
profiles is a *selector* that drives `local.analytics_backend`; no module
provisions ClickHouse at any profile.

Gating a module with `count` turns its outputs into a list, so nothing reads a
gated module's output directly — everything goes through normalized locals
(`local.redis_host`, `local.kafka_bootstrap_servers`, `local.neptune_endpoint`,
…) that resolve to `""` when the backend is absent. The idiom is
`try(module.x[0].out, "")`, deliberately not `try(one(module.x[*].out), "")`:
`one([])` returns `null` and `try` only traps errors, so the `one()` form feeds
a null into a string input.

Which backend a running task uses is passed explicitly (`event_broker`,
`cache_backend`, `graph_backend`, `analytics_backend`), never inferred from
whether a host string happens to be empty.

### Static frontends

The Aether and Kyber SPAs are immutable object-store origins at **every**
profile — `aws_s3_bucket.static_frontend` with public access blocked,
server-side encryption, and SSM parameters the deploy workflow resolves bucket
names from. `frontend_ecs_services` is a forbidden resource everywhere; the root
creates no frontend ECS service at any profile.

**The CDN distribution is provisioned outside this root.** The S3 origins and
their SSM pointers are the Terraform-owned half of the contract, as
`config/terraform_resource_contracts.yaml` states explicitly. There is no
CloudFront resource in the live tree.

### Terraform modules

Seventeen module directories exist under `terraform/modules/`. Modules marked
**gated** are provisioned only for the profiles listed.

| Module | Manages | Gate |
|---|---|---|
| `vpc` | VPC, three subnet tiers, security groups, flow logs, NAT per `nat_mode` | always; NAT and the redis/msk/neptune SGs gated |
| `ecr` | 4 private ECR repositories with lifecycle policies | always |
| `secrets` | Secrets Manager stubs (KMS-encrypted), rotation Lambda | always |
| `kms_credentials` | Customer-managed KMS CMK + alias for provider-credential envelope encryption (surfaced as `CREDENTIAL_KMS_KEY_ID`); least-privilege `Encrypt`/`Decrypt`/`GenerateDataKey` grant bound to the five-key encryption context, attached to the ECS task role. The apply role is **not** injected into the CMK key policy by default; the account-root statement remains the lockout-safe administrator. The reviewed staging identity policy permits key-rotation status and a separate 30-day key-deletion request, both constrained to staging-tagged keys. Supplying `kms_key_admin_role_arns` is an explicit, separately reviewed administrative grant; removing the role from the plan-time principal list therefore does not remove root authority or task-role cryptographic access. | always; disabled only by `enable_credential_kms = false`, which the throwaway `terraform test` apply run passes so its teardown can delete every created resource (the key carries `prevent_destroy`) |
| `aurora` | Aurora Serverless v2 cluster + writer, KMS | always |
| `dynamodb_cache` | DynamoDB cache table with read/write autoscaling | always |
| `sqs` | SNS fanout topic, shared + per-role SQS queues, DLQs | always |
| `alb` | Internet-facing ALB, HTTP→HTTPS redirect, backend target group | always; **gated** ML target group + `/v1/ml/*` rule |
| `ecs` | Fargate cluster, backend service, per-service task definitions, IAM roles, autoscaling | always; **gated** dedicated ML service |
| `monitoring` | SNS alerts, CloudWatch alarms, dashboard, S3 log archive | always; per-backend alarms **gated** |
| `ml_drift_lambda` | Nightly PSI drift check → `Aether/MLDrift` namespace | always |
| `auth0` | SPA clients + API resource server | always |
| `elasticache` | Redis 7.x, TLS in transit, AUTH token, KMS at rest | **gated** — scale / enterprise |
| `msk` | 3-broker MSK Kafka, TLS, KMS, CloudWatch metrics | **gated** — scale / enterprise |
| `neptune` | Neptune cluster + instances, IAM auth, KMS | **gated** — scale / enterprise |
| `rds` | Legacy RDS Postgres | **never** — superseded by Aurora |
| `s3` | — | **not instantiated by this root** |
| `vpc_endpoints` | — | **not instantiated by this root** |

### Observability

CloudWatch-native at every tier. `modules/monitoring` declares ten alarm
resources: seven always created — `alb_5xx`, `aurora_max_acu`, `ml_drift`,
`dynamodb_cache_throttled`, `sqs_queue_depth`, `sqs_oldest_message_age`,
`sqs_dlq_depth` — and three created only when the matching store exists:
`elasticache_memory`, `msk_offline_partitions`, `neptune_cpu`.

Alarms follow the backend by design. A profile that swaps Redis for DynamoDB and
Kafka for SQS must ship alarms for DynamoDB and SQS, or the cost reduction has
silently bought an observability gap; and an alarm pointing at a dimension that
does not exist sits permanently in `INSUFFICIENT_DATA` and masks real alerts.

Alarm wiring has never been observed firing and resolving in a deployed account.
`COND-OBSERVABILITY-LIVE` is unmet.

### Verification

```bash
make test-terraform-profiles          # terraform validate + terraform test
make validate-cost-policy-terraform   # static: profiles.tf locals encode the policy
make validate-terraform-profile-policy # a real plan JSON scored against the contracts
make validate-cost-model              # that inventory priced against the budget
```

`terraform validate` passes, and `terraform test -filter=tests/profile_plan.tftest.hcl`
passes for all six selectable profiles across the run blocks
(`staging`, `demo`, `preview`, `staging_asleep`, `production_lean`,
`production_scale`, `enterprise_isolated`, plus the applied-state and
egress-rejection blocks). Assertions read the **planned module graph** —
`length(module.msk) == 0`, `length(module.vpc.nat_gateway_ids) == 3`,
`module.vpc.nat_mode == "ha"` — not the locals that produced it, so a local that
stops being wired into a `count` is caught rather than passed over. They are
mutation-proven: forcing `count = 1` on MSK fails the lean run block with
`module.msk is tuple with 1 element`. No AWS credentials are required.

### Cost

`production-lean`'s fixed baseline measures **USD 187.13/month** — over the
USD 150 design target, under the USD 200 hard ceiling; the gate warns and
passes, and the deviation is reviewed and accepted. Staging is budgeted at
USD 25 target / USD 50 ceiling against 40 scheduled awake hours per month. The
two uncapped profiles carry no budget block by design. The full model, the
per-line breakdown, the usage-variable band and the deviation record are in
[Cost Optimization](COST-OPTIMIZATION.md); it is not restated here.

No AWS invoice exists for any profile. Every figure is a modelled projection
from a pinned price book against a plan inventory.

---

## Promotion and apply

`.github/workflows/infrastructure.yml` **plans and validates only; it never
applies.** The `apply-production-lean` job that once auto-applied on every push
to `main` has been deleted. On a push to `main` its
`require-production-credentials` job gates *promotability*, not an apply. When
the remote-plan credential set is absent, that job reports it is a NO-OP and
passes green — the commit is explicitly **not** promotable — and re-arms,
fail-closed, the moment the credentials are wired.

`.github/workflows/terraform-promote.yml` is the **sole apply path**:
`workflow_dispatch`-only, per-profile GitHub environment
(`staging-terraform`, `production-lean-terraform`,
`production-scale-terraform`, `enterprise-terraform`), and an apply that
consumes the exact reviewed binary plan and **never re-plans**. Before applying
it re-verifies the plan digest against the dispatched checksum, the profile, the
state key, the plan's own recorded commit (which it checks out rather than
trusting the dispatch ref), the Terraform version, the `.terraform.lock.hcl`
digest and the 24-hour expiry, and it re-runs the policy and cost validators at
the reviewed commit.

Operator procedure: [Deployment Runbook](DEPLOYMENT-RUNBOOK.md). Staging's
wake/validate/sleep cycle: [Staging Wake / Sleep](STAGING-WAKE-SLEEP.md).

### Staging apply prerequisites and collision safety

The staging apply role is deliberately narrower than a general administrator.
Its checked-in contract is `config/staging_apply_iam_policy.yaml`; the apply
workflow validates that manifest before assuming the role and re-validates the
resolved plan immediately before mutation. The staging promotion workflow also creates (or
waits for) the ECS service-linked role before capacity-provider operations and
verifies the Auth0 management token has every scope required by the reviewed
Auth0 resources. These checks fail closed; a missing external-provider scope
or service prerequisite is a blocked apply, not a partial deployment.

Terraform backend access is a separate reviewed contract in
`config/terraform_state_access_policy.yaml`. The confirmation-gated state
migration workflow and the apply role may read/write only profile state objects,
read the state-bucket metadata it needs, and lock the dedicated Terraform lock
table; the policy checker rejects wildcard actions or resources and derives the
bucket/table names from the canonical backend configuration. Before any apply
or state migration, the workflow also runs
`scripts/release/verify_terraform_state_role.py` through IAM policy simulation
against the assumed role, so a checked-in manifest cannot be mistaken for an
attached/effective permission. The verifier accepts the canonical backend pair
and the explicitly reviewed, account-qualified staging pair already in use;
both are still checked by IAM simulation against the assumed role. Plan-only
runs do not use this write policy.

Every selectable apply profile also bootstraps the account-level ECS
service-linked role before Terraform creates capacity providers. Each protected
profile apply role must therefore carry the reviewed, least-privilege
`CreateServiceLinkedRole` (restricted to `ecs.amazonaws.com`) and `GetRole`
permissions; a missing grant fails before any profile resource is changed.

The backend target group keeps the stable
`aether-staging-backend` identity used by the import-only reconciliation
workflow and remains at the stable state address
`module.alb.aws_lb_target_group.backend[0]`. If a workspace still has the
unindexed legacy address, the promotion plan fails closed; run the explicit,
confirmation-gated `terraform-state-migrate.yml` state-only workflow first.
Staging migrates to the indexed staging address, while production-class
profiles migrate to
`module.alb.aws_lb_target_group.backend_replacement[0]`. Staging intentionally disables
`create_before_destroy`: AWS cannot create a replacement with that deterministic
name while the old group exists, and the listener still points at the existing
group. A ForceNew staging change must
therefore use a separately reviewed listener-detach/replacement/reattach
transition; an ordinary apply fails closed instead of risking a listener
cutover or an in-use target-group deletion.

For an intentional ForceNew change, use three reviewed plans: first set
`staging_listener_target_group_arn` to an existing maintenance target group and
apply so the HTTPS listener is detached from the backend; then replace the
backend while that ARN remains selected; finally clear the variable and apply
again to reattach the listener. Before the destructive middle step, the
promotion workflow verifies the live HTTPS listener already points at that
validated maintenance target; otherwise it fails closed and asks for the
detach-only apply first. The normal promotion workflow never invents a
maintenance target group or performs this transition implicitly.
An interrupted run must use `staging-state-reconcile.yml` to import the
existing group or an exact reviewed ECR repository, and produce a fresh
reviewed plan. If a repository already exists in staging state at a legacy
Terraform address, the workflow adopts it only when exactly one staging owner
is found, moving that state entry to the reviewed canonical module address;
the complete digest, provider, and root-module input contract is validated
before that move, and every candidate is checked before any move begins. Tainted
or otherwise non-managed legacy instances fail closed instead of being carried
forward. An already-canonical healthy entry is a verified retry no-op, while
mismatched or ambiguous/cross-profile ownership still fails closed. If an
existing ECR repository is already at the canonical address but marked tainted
after an interrupted replacement, use the workflow's explicit
`untaint_ecr_repository_names` input instead. That input clears taint only after
the repository's live encryption and KMS key match both the reviewed staging
configuration and the Terraform-managed ECR KMS key in state; it uses
Terraform's top-level `untaint` command and never imports, deletes, or applies a
repository. Both import and untaint paths verify that the repository is not
owned by demo or preview state; staging is the intended owner for an untaint
repair and its canonical address is checked for duplicate staging owners before
any state mutation. Comma-separated targets are normalized and deduplicated,
and every requested untaint target is validated up front so a later invalid
entry cannot leave a partial repair. Both import and untaint mutations run under
the protected `AWS_TERRAFORM_APPLY_ROLE_ARN` state-write role; the read-only
plan role is never used to persist reconciliation changes. Comma-separated
targets are normalized and deduplicated before the mutation loop. ECR imports additionally require
matching the reviewed staging KMS key. The workflow validates
`config/terraform_state_access_policy.yaml` and simulates the assumed role's
effective bucket/table permissions before any state mutation. The import runner carries the same Auth0 provider environment
as a normal remote plan, because Terraform configures every root provider even
when importing a single AWS address. Aurora alarms and dashboard widgets are
likewise selected by a static profile flag rather than an unresolved cluster
output, keeping state-only imports graph-resolvable. This applies to both
Aurora and DynamoDB monitoring; table and cluster outputs are alarm dimensions,
not cardinality gates. One exit cleanup removes every temporary state snapshot
created by the import ownership checks. The apply workflow refuses to adopt an
unmanaged group or repository. The uncapped production profiles retain
replacement-before-destroy behavior for availability and use separate
accounts when their names would otherwise collide.

## Post-deploy steps

1. **Confirm the SNS email subscription.** AWS sends a confirmation to
   `alert_email`; alarms deliver nothing until the link is clicked.
2. **Inject secret values.** Secrets Manager stubs are created empty. Store raw
   secret strings, not JSON objects — ECS `valueFrom` injects the entire secret
   string, so a JSON wrapper needs a JSON-key suffix on the ARN and is
   error-prone. `aether/db-password` is populated automatically by Aurora's
   managed rotation; `aether/redis-auth-token` exists only on profiles that
   provision Redis.
3. **Push images.** Task definitions pin an immutable digest, so a new digest is
   a new task definition and deploys itself. The ML image is only needed on
   profiles that run the dedicated ML service.
4. **Run migrations** from inside the VPC (ECS Exec, bastion, or a one-off
   Fargate task). On a `public_ip` profile set `assignPublicIp=ENABLED` — there
   is no NAT to egress through.
5. **Verify `/v1/ready`**, which fails unless the database alembic revision
   equals the packaged head.

## Migration hazards and decommissioning

Removing applied infrastructure — including turning a backend off by changing
the deployment profile — goes through
`AWS Deployment/aether-aws/terraform/DECOMMISSION.md`. **A profile flip that
shows `Plan: … 1 to destroy` on a data store is a stop-the-line event**, not a
diff to skim.

- **Seven ECS services are destroyed** the first time a workspace moves from the
  per-role shape to the consolidated one. This is correct and intended, and it
  is deliberately *not* hidden behind `moved` blocks: it is a change of
  deployment unit, not a rename. Queues, DLQs, consumer groups and retry
  policies survive; in-flight messages stay in their queues and are drained once
  the consolidated task is stable.
- **The private default route migration is a maintenance window.** The route
  moved from an inline `route` attribute to a standalone `aws_route`, which
  `moved` cannot express — an inline block is an attribute, not an addressable
  resource. On the first apply against a NAT-carrying workspace Terraform
  performs two unordered operations on the live egress path. Apply it alone,
  expect brief egress unavailability, and verify afterwards that each private
  route table has exactly one `0.0.0.0/0` route to the intended gateway — in
  `ha` mode, the NAT in the same AZ. `nat_mode = "none"` workspaces are
  unaffected.
- **`moved.tf` covers fourteen addresses**: the four gated root modules (`rds`,
  `elasticache`, `msk`, `neptune`), five dedicated-ML resources inside
  `module.ecs`, two inside `module.alb`, and three VPC data-store security
  groups. Without them, adding `count` would rename state addresses and plan a
  destroy-and-recreate of live clusters. Do not delete them until every
  pre-existing workspace has applied at least once.
- **"Kept for rollback safety" must be time-bounded.** Every retained resource
  needs a named owner, an explicit expiry in `config/implementation_ledger.yaml`
  and a decommission ticket. An expired retention is unowned cost, and must be
  escalated rather than silently extended.

## Security posture

What the live root implements:

- No secret values in Terraform state or code; all secrets fetched from Secrets
  Manager at container start-up.
- Data stores in isolated subnets with no default route.
- Customer-managed KMS keys for Aurora and Secrets; per-store KMS on
  ElastiCache, MSK and Neptune where provisioned.
- ECS tasks use dedicated IAM roles with least-privilege policies scoped to the
  queues, tables and secrets the selected profile actually provisions.
- ALB enforces TLS 1.3 minimum (`ELBSecurityPolicy-TLS13-1-2-2021-06`).
- VPC flow logs capture all traffic.
- On `public_ip` profiles ECS tasks carry a public IP for egress; inbound access
  is governed entirely by the task security group, which accepts traffic only
  from the ALB.
- Fargate has no IMDS access, so IMDSv2 hardening is not applicable to it.

Not implemented by this root, and therefore not claimed: GuardDuty, Security
Hub, Inspector, Macie, an organisation CloudTrail, organisation-level SCPs,
cross-account log forwarding, or WAF. There is one account, not an
Organization. No compliance certification, external attestation or audit
coverage is claimed anywhere.

## Disaster recovery

**The live root provisions no DR posture.** There is no cross-region read
replica, no S3 Cross-Region Replication, no us-west-2 standby, no Route 53
health-check failover, and no `dr_failover.py` script. Aurora carries a
`backup_retention_days` default of 7 and `enterprise-isolated` sets
`db_multi_az = true`; that is the whole of the durability story in Terraform
today.

RPO/RTO targets, DR regions and drill cadences appear in the reference model
below. They are **aspirational targets, not implemented controls**, and no drill
has been run.

---

## Reference model — described, not provisioned

`AWS Deployment/aether-aws/README.md` and `config/aws_config.py` describe a
larger target architecture: six AWS accounts under one Organization
(dev/staging/production/data/security/demo), five VPCs, nine named ECS
services, eight managed data stores including SageMaker Serverless and Athena,
SCP guardrails, budget configurations, DR strategies and compliance controls.
`main.py --stub-aws` prints that model; the operational packages under
`scripts/{network,monitoring,cost,security,capacity,dr}` operate against it.

**None of it is provisioned by the live Terraform root**, and the account IDs in
it (`111111111111` … `666666666666`) are placeholders. Treat that material as a
design reference and a demo surface. Do not quote its cost estimates, account
topology, data-store inventory or DR posture as a description of Aether's
infrastructure.

## Dead second Terraform tree

`AWS Deployment/aether-aws/terraform/environments/{dev,staging,production,demo}/`
and `AWS Deployment/main.tf` are a second, dead Terraform tree. Between them they
reference seven modules that do not exist in this repository — `cloudfront`,
`opensearch`, `dynamodb`, `sagemaker`, `api_gateway`, `iam`, `waf` — so
`terraform init` fails there, and `environments/demo/main.tf` is not valid HCL.

They are not the deployment path, nothing applies them, and they describe an
architecture Aether does not run. Do not modify, extend, "fix" or copy patterns
out of that tree. The live root is
`AWS Deployment/aether-aws/terraform/`, and the live variable surface is
`variables.tf` plus `profiles/*.tfvars`.

## What is not claimed

- No environment has been applied, billed, load-tested or rolled back. No
  credentialed plan has been produced against real remote state.
- No multi-region, active-active or DR posture exists in Terraform.
- No compliance certification, external attestation or audit coverage.
- Readiness is reported as a code-complete column and an externally-verified
  column and is never merged into one number; `deployment_ready` is `false`.
  See [Release Evidence](RELEASE-EVIDENCE.md).

## See also

- [Deployment Profiles](DEPLOYMENT-PROFILES.md)
- [AWS Lean Production](AWS-LEAN-PRODUCTION.md)
- [Staging Wake / Sleep](STAGING-WAKE-SLEEP.md)
- [Cost Optimization](COST-OPTIMIZATION.md)
- [Deployment Runbook](DEPLOYMENT-RUNBOOK.md)
