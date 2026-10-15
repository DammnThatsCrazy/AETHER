---
title: AWS Lean Production
slug: operations/aws-lean-production
section: operations
visibility: I
audience: [ops, architect, dev-senior, security]
status: stable
since_version: "0.1.0"
source_files:
  - infra/aws/terraform/profiles.tf
  - infra/aws/terraform/main.tf
  - infra/aws/terraform/variables.tf
  - infra/aws/terraform/moved.tf
  - infra/aws/terraform/profiles/production.tfvars
  - infra/aws/terraform/tests/profile_plan.tftest.hcl
  - infra/aws/terraform/DECOMMISSION.md
  - config/runtime_deployment.yaml
  - config/deployment_profiles.yaml
  - config/terraform_resource_contracts.yaml
  - .github/workflows/terraform-promote.yml
  - .github/workflows/infrastructure.yml
canonical_owner: platform@aether
estimated_read_minutes: 20
toc_depth: 3
reviewed_source_commits:
  - commit: "609a3ad37"
    reason: "Reviewed the linked root main.tf change; it updates the Auth0 section comment only. The dedicated Native CLI client change does not alter lean AWS topology, deployment lane, or runtime settings described here."
source_hashes:
  ".github/workflows/infrastructure.yml": "sha256:e0ec1b2746f4f3d2d3fd28819cf288bec019a93ee3fd7f4ea74e75efe36899dc"
  ".github/workflows/terraform-promote.yml": "sha256:804e3b437274475d5125b4dbf6c3988ff9387909af73a5aeb5690713cf310adf"
  "config/deployment_profiles.yaml": "sha256:6d4535fd98bebf72519f2e03c5d2dfca190bfe7da63e76140073db051e3b6a66"
  "config/runtime_deployment.yaml": "sha256:cd65f4902ed9062c2526bd9b83b99e2c0ecc58f012a3fa1c90ba9660b874a332"
  "config/terraform_resource_contracts.yaml": "sha256:b1414be3c53b0309d484b8029aadf336618bd88d94d31de72ed0f54865493d59"
  "infra/aws/terraform/DECOMMISSION.md": "sha256:7d1aa3e9fd042bbb27d8173ea690f41747eee0ea91c5ddcab6c85a5edd688ea6"
  "infra/aws/terraform/main.tf": "sha256:3452bf10acf326ce6eea1267042b305d494bcd6844a66e87df3a3cad8d0d7626"
  "infra/aws/terraform/moved.tf": "sha256:3a816e2a5b402a98a89d949b1801bd6c3cd99242a26cc17039c6d140faa3a342"
  "infra/aws/terraform/profiles.tf": "sha256:da63e1f50e4030924713679445e3c365883a23821ac78df83bebe14436c67f60"
  "infra/aws/terraform/profiles/production.tfvars": "sha256:85f0417ff14534587c2210d4164adc3e9e775170f01495f62c2884c6f308c36c"
  "infra/aws/terraform/tests/profile_plan.tftest.hcl": "sha256:65c25850344e2b70121207e64f5883d48677feaab93d3a39d6f7aa474908d8d8"
  "infra/aws/terraform/variables.tf": "sha256:46f64fe05369a15910f3702ed7161da5be3c539f52908643570b60b18fecb8e1"
---

# AWS Lean Production

`production` is Aether's founding-tenant production profile: the smallest
AWS footprint that runs the whole platform for a first paying customer without
regressing delivery, isolation or observability.

This page is the concrete description of that deployment — what exists, what
deliberately does not, what it costs, what it trades away, and how to promote
into and out of it.

> **Nothing on this page has been applied.** No credentialed
> `terraform plan` or `terraform apply` for this profile has run. The
> `production` scorecard in `config/deployment_readiness.yaml` reads
> **45/100 code-complete, 0/100 externally-verified** against a gate of 92,
> and `deployment_ready: false`. See [What is proven](#what-is-proven).

## Selecting the profile

```bash
cd "infra/aws/terraform"
terraform plan -var-file=profiles/production.tfvars -out=tfplan
```

`profiles/production.tfvars` pins the lean runtime and the production web
cutover controls:

```hcl
deployment_profile  = "production"
network_egress_mode = "public_ip"   # zero NAT Gateways
aurora_min_acu      = 0.5           # always warm at a small floor
aurora_max_acu      = 4
log_retention_days  = 3             # short CloudWatch retention; bulk logs to S3
amplify_custom_domain_enabled  = true
amplify_domain_name             = "olympuslabsml.com"
# Squarespace remains authoritative; add the Amplify association CNAME targets
# there. Route 53 delegation is an explicit, separately reviewed DNS move.
squarespace_hosted_zone_enabled = false
status_api_url                  = "https://api.olympuslabsml.com/health"
enable_tfmcp_in_lean             = false
platform_operator_tenant_ids     = []
```

`backend_image_digest` and `ml_image_digest` have **no defaults**. Every plan
must pin the exact digests from an approved release manifest.

`platform_operator_tenant_ids` becomes `PLATFORM_OPERATOR_TENANT_IDS` on the API
task. Production has no first-admin bootstrap tenant, so while the list is empty
no Aether tenant reaches the operator-only `/v1/admin/**` and
`/v1/diagnostics/**` routes; set the reviewed operator tenant ids before
relying on operator tooling there. `make ops-readiness`, part of
`make release-gate`, fails while the list is empty.

`profiles.tf` derives every resource toggle from `var.deployment_profile`, and
`main.tf` wires those locals into module `count` and module inputs. The
selection is therefore structural, not documentary: a `production` plan
*cannot* contain a forbidden resource.

## Topology

```
                    Squarespace apex / Amplify custom domains
                          │
        ┌─────────────────┴──────────────────┐
        │                                    │
  Amplify public web apps              Application
  Olympus / Aether / docs /             Load Balancer
  app / status                          (internet-facing)
  S3 private artifacts
                                             │
                                    ┌────────┴─────────┐
                                    │  ECS Fargate     │
                                    │  cluster         │
                                    │                  │
                                    │  api             │  1 task
                                    │   1 vCPU / 2 GiB │
                                    │                  │
                                    │  lean-worker     │  1 task
                                    │   2 vCPU / 8 GiB │
                                    │   ├ outbox-relay │
                                    │   ├ stream-worker│
                                    │   ├ identity-worker
                                    │   ├ graph-writer │
                                    │   ├ measurement-worker
                                    │   ├ semantic-worker
                                    │   ├ materializer │
                                    │   └ maintenance  │
                                    └────────┬─────────┘
                                             │
         ┌──────────────┬──────────────┬─────┴─────┬──────────────┐
         │              │              │           │              │
   Aurora Serverless  DynamoDB      SNS → SQS     S3          Secrets
   v2 Postgres        cache table   + per-role    log archive  Manager
   (data + graph      (TTL-backed)  DLQs         + object lake + KMS
    + analytics)
```

Public Olympus, Aether, docs, app, and status pages are **Amplify-hosted
applications**, never ECS-hosted containers. The protected tenant release and
Kyber operator release are immutable encrypted S3 artifacts. Kyber remains
internal-only: it has no public DNS record unless the explicit internal DNS
control and target are supplied.

### Task counts

| Service | ECS service name | Roles hosted | Tasks | vCPU / MiB | Autoscaling | Capacity |
|---|---|---|---|---|---|---|
| `api` | `AETHER-production-backend` | `api` | 1 | 1024 / 2048 | 1 → 4 on ALB request count, target 800/task, 180 s cooldown | `FARGATE` base 1, `FARGATE` surge |
| `lean-worker` | `AETHER-production-lean-worker` | all eight worker roles | 1 | 2048 / 8192 | 1 → 4 on SQS queue depth, target 500/task, 300 s cooldown | `FARGATE` base 1, `FARGATE` surge |

**Two always-on tasks, down from ten.** The eight dedicated worker services
that a dedicated-mode deployment would run are collapsed into one consolidated task.

The `api` service is served by the Terraform-provisioned
`<project>-<env>-backend` ECS service (`aws_ecs_service.backend` in
`modules/ecs`), not `<project>-<env>-api`. That is the one load-bearing naming
exception in the runtime matrix; the deploy workflow special-cases it and
`scripts/release/check_delivery_topology.py` pins the mapping in both places.
Every other service key maps 1:1 to `<project>-<env>-<key>` and is passed
straight through to the container as `AETHER_ROLE`, which is why the
consolidated service is keyed `lean-worker` rather than `workers`.

Neither service may use `FARGATE_SPOT` at any capacity. `api` serves public
traffic; `lean-worker` hosts `outbox-relay`, and a Spot reclaim mid-flight on
the at-least-once delivery path buys a two-minute interruption for a few cents.
`check_delivery_topology.py::SPOT_FORBIDDEN_ROLES` enforces this.

### What consolidation does and does not change

Consolidation moves the **process boundary** and nothing else. Inside the
`lean-worker` task every member role keeps its own SQS queue, consumer group,
DLQ, retry policy, metrics label and restart behaviour — resolved in-process by
`services/api/workers/runtime/roles.py::roles_in` from the `AETHER_ROLE` token.

Terraform carries the role list for exactly one reason: a consolidated task
must bind one SQS queue per hosted role, which a single `SQS_QUEUE_URL` cannot
express.

The invariant, enforced by `check_delivery_topology.py`: every role in
`roles.py::WORKER_ROLES` is hosted by **exactly one** service in **every**
profile — never orphaned, never claimed twice. `all` is local/test only and is
never deployable. `api` never hosts a worker role or a consumer.

### Sizing rationale

`lean-worker` at 2 vCPU / 8 GiB is deliberately not sized like the single
512/1024 role it superficially resembles. It replaces eight tasks holding
4096 CPU units and 8192 MiB between them.

- **2 vCPU** because consolidation removes eight container and interpreter
  overheads, not eight workloads. The roles are I/O-bound and mostly poll-idle,
  so steady-state CPU sums to well under 4096 — but the burst tail is real and
  now lands on one task: `stream-worker`'s replay/polling loops (alone
  previously sized 1024) plus five consumer-attached roles draining SQS batches
  concurrently. 2 vCPU keeps the asyncio loop off the runnable queue during
  that tail.
- **8 GiB** because memory, not CPU, is the binding constraint. Eight roles'
  database pools, SQS receive buffers and per-role consumer state share one
  heap, and with `remote_ml: false` the semantic classifier runs **in-process**
  as a resident model. 4 GiB fits the arithmetic and leaves nothing for it.

## Network

| Setting | Value |
|---|---|
| `network_egress_mode` | `public_ip` |
| `nat_mode` | `none` |
| NAT Gateways | **0** |
| Elastic IPs | **0** |
| Task egress | public IP on the task ENI (`assign_public_ip = true`) |
| Task ingress | task security group accepts ALB traffic only |

ECS tasks carry a public IP purely so they can reach the internet without a NAT
Gateway. Inbound access is still governed entirely by the security group. A
single NAT Gateway is ~USD 32.85/month before USD 0.045/GB processing; two AZs
of NAT would be a third of the entire lean budget.

Operational consequence: any `aws ecs run-task` (migrations, one-off jobs) must
pass `assignPublicIp=ENABLED`. There is no NAT to egress through.

`nat_gateway_unless_explicit` is a forbidden resource for this profile.
Setting `network_egress_mode` to `single_nat` or `ha_nat` **is** the explicit
opt-in the policy name refers to, and must be reviewed as a cost-policy
exception.

## Backends

Every backend dimension is selected explicitly and passed into `modules/ecs`,
so a running task never has to infer its backend from whether a host string is
empty.

| Dimension | Selection | Realised as | Terraform selector |
|---|---|---|---|
| Database | `aurora_postgres` | Aurora Serverless v2 Postgres, 0.5–4 ACU | always on (`enable_aurora = true`) |
| Cache | `dynamodb` | DynamoDB table with read/write autoscaling, TTL-backed; the shared durable-store path uses the same table | `local.cache_backend == "dynamodb"` |
| Event broker | `sns_sqs` | SNS fanout topic → per-role SQS queues + DLQs | `local.event_broker == "sns_sqs"` |
| Graph | `postgres` | stored in the same Aurora cluster; no separate graph resource | `local.graph_backend == "postgres"` |
| Analytics | `postgres` | stored in the same Aurora cluster | `local.analytics_backend == "postgres"` |
| Object storage | `s3` | log archive + ML drift reference data + SPA origins | always on |
| ML | `inline` | inference in-process inside the backend task | `enable_dedicated_ml = false`, `remote_ml: false` |
| Secrets | — | Secrets Manager stubs + rotation, customer-managed KMS key | always on |
| Observability | — | CloudWatch alarms + dashboard → SNS alert topic | always on |

The graph and analytics contracts are *absences plus a presence*: the graph
lives in Aurora because there is no Neptune cluster, and analytics lives in
Aurora because there is no ClickHouse. There is nothing separate to count, so
the contract pairs each with the corresponding forbidden rule.

Inline ML works the same way: the contract is exactly one
`aws_ecs_service.backend` combined with the **absence** of
`aws_ecs_service.ml`, its task definition, log group, autoscaling target and
policy, and the ALB target group and `/v1/ml/*` listener rule it would
register. With no dedicated ML service, `/v1/ml/*` falls through to the HTTPS
listener's default action and is served by the backend.

### Alarms

`production` provisions 9 CloudWatch objects: the dashboard plus
`alb_5xx`, `aurora_max_acu`, `ml_drift`, `dynamodb_cache_throttled`,
`sqs_queue_depth`, `sqs_oldest_message_age`, `sqs_dlq_depth`, and the alert SNS
topic.

The contract asserts both directions. Every backend the lean profile
**substitutes** must carry its own alarms, or cost reduction has silently
bought an observability gap — so `dynamodb_cache_throttled`, `sqs_queue_depth`,
`sqs_oldest_message_age` and `sqs_dlq_depth` are *required*. Alarms whose
dimensions would point at a resource the profile does not provision are
*forbidden* rather than left in `INSUFFICIENT_DATA`: `elasticache_memory`,
`msk_offline_partitions`, `neptune_cpu`.

## Resources explicitly absent

Every one of these is asserted at zero in a `production` plan by
`scripts/release/check_terraform_plan_policy.py`, and by
`length(module.<x>) == 0` assertions in `tests/profile_plan.tftest.hcl`.

| Absent | Terraform gate | Permitted in |
|---|---|---|
| MSK Kafka cluster, configuration, KMS key, broker logs | `enable_msk` | **nowhere** today — enabling needs a reviewed production variable change |
| ElastiCache Redis replication group, subnet/parameter groups, AUTH secret | `enable_elasticache` | **nowhere** today — enabling needs a reviewed production variable change |
| Neptune cluster, instances, subnet group | `enable_neptune` | **nowhere** today — enabling needs a reviewed production variable change |
| ClickHouse | `enable_clickhouse` | selector only — **no module exists at any profile** |
| Dedicated ML ECS service + ALB target group and listener rule | `enable_dedicated_ml` | **nowhere** today — enabling needs a reviewed production variable change |
| **Frontend ECS services** | `enable_frontend_ecs` (literal `false`) | **nowhere** |
| **Legacy RDS instance, parameter group, subnet group** | `enable_legacy_rds` (literal `false`) | **nowhere** |
| **NAT Gateways and Elastic IPs** | `enable_nat_gateway` / `network_egress_mode` | **nowhere** today (`public_ip` egress) |
| **Self-managed Prometheus/Grafana compute** | `enable_prometheus_grafana` (literal `false`) | **nowhere** |
| Always-on staging compute | not plan-checkable | — |

The three with literal-`false` gates are architectural positions, not cost
decisions: SPAs are immutable S3 origins at every tier, Aurora is the database
of record at every tier, and observability is CloudWatch native at every tier.
The contracts file records this as `permitted_in: []`.

`always_on_staging_compute` has nothing to count in a `production` plan —
a production plan provisions no staging resources at all. It is a lifecycle
property enforced by the staging wake/sleep automation and by
`scripts/release/check_cost_policy.py`.

`module.rds` is retained in code with a permanent `count = 0`. It exists only
so an already-applied RDS instance can be adopted and retired through
`DECOMMISSION.md` rather than destroyed by a profile flip.

## Cost

Modelled fixed baseline: **USD 188.93/month**, inside the USD 200 hard ceiling
and USD 38.93 over the USD 150 target. That deviation is reviewed and accepted;
the full breakdown, the two rejected sizing levers, the estimation method and
its assumptions are in [Cost Optimization](COST-OPTIMIZATION.md).

The optional customer Access Kit MCP service adds approximately USD 18.02 per
month for two continuously running 0.25-vCPU / 0.5-GiB Fargate tasks, plus
about USD 0.50/month for 5 GiB of ECR storage. At roughly USD 207.45/month
before variable ALB and CloudWatch charges, that option exceeds the fixed USD
200 hard ceiling. The existing Terraform cost gate rejects the production
plan unless an active, time-bounded cost exception authorizes the overage.
Access Kit MCP is currently constrained to the canonical `production`
state because that state owns the globally named ECR repository; this
production figure is a cost comparison, not an allowed deployment
profile. Optional delegated OAuth adds a Secrets Manager secret and its
associated variable charges beyond this base estimate. See the
[Access Kit MCP AWS deployment runbook](../../infra/aws/terraform/ACCESS_KIT_MCP_DEPLOYMENT.md).

| Scenario | Fixed | Variable | Total |
|---|---|---|---|
| low — quiet pilot tenant | 188.93 | 15.25 | **204.18** |
| expected — founding tenant | 188.93 | 107.22 | **296.15** |
| high — 10× surprise | 188.93 | 955.40 | **1144.33** |

**Operating range: roughly USD 200–300/month** at the traffic the commercial
plan assumes. These are modelled figures from a pinned price book, not an
observed bill.

## Availability tradeoffs

Lean buys its cost profile with specific, named risks. None of them is hidden.

| Choice | What you give up | What covers it |
|---|---|---|
| **1 API task** | No warm second task for instant failover; a task replacement is a brief capacity dip | ALB health check + ECS deployment circuit breaker + autoscaling to 4 on sustained request count. A permanently warm second task paid full price for a failover autoscaling already provides. |
| **8 roles in 1 task** | One OOM, crash-loop or bad deploy takes all eight roles down together. No per-role blast-radius isolation. | 8 GiB of memory headroom; per-role queues, DLQs and retry policies survive the process boundary; autoscaling to 4 tasks on queue depth. Growing production beyond this shape (dedicated mode) is the answer to real isolation. |
| **No Spot anywhere** | Forgoes the Spot discount on surge capacity | Deliberate. `api` is public traffic and `lean-worker` hosts `outbox-relay`. |
| **`public_ip` egress** | Tasks hold public IPv4 addresses; no private-subnet posture | Task SG accepts ALB traffic only. Promote to `single_nat`/`ha_nat` when a compliance or customer requirement demands private subnets. |
| **Aurora 0.5–4 ACU** | Ceiling is 4 ACU; sustained saturation is a real limit | `aurora_max_acu` alarm fires after >10 min at ceiling. Raise the ceiling first; sustained saturation after that is a scale signal. |
| **DynamoDB instead of Redis** | No pub/sub, no Redis data structures | Only the cache dimension uses it; `dynamodb_cache_throttled` alarms on throttling. |
| **Inline ML** | Inference competes with request handling for the backend task's CPU | Sized accordingly; `ml_drift` alarm. Promote to `remote_ml: true` at scale. |
| **`log_retention_days = 3`** | Only 3 days of CloudWatch history | Bulk logs ship to the S3 log archive. Log ingestion is the largest variable cost line. |
| **Single region, single account** | No DR region, no multi-AZ database failover story documented here | Not claimed. See [What is *not* claimed](#what-is-not-claimed). |

## Promotion

`.github/workflows/terraform-promote.yml` is the **only** path that applies
Terraform. It is `workflow_dispatch`-only: no push, tag, schedule or path
trigger can reach an apply.

The job that used to auto-apply `production` on every push to `main`
(`apply-production` in `infrastructure.yml`) has been **deleted**.
`infrastructure.yml` is now plan-and-validate only, and says so at the top of
the file.
It runs its path-scoped provider-mocked plan on PR finalization
(`ready_for_review`), on matching pushes to `main`, or by explicit dispatch;
draft PR pushes do not start the workflow.

### Plan

```bash
gh workflow run terraform-promote.yml \
  -f profile=production \
  -f action=plan \
  -f backend_image_digest=sha256:<64hex> \
  -f ml_image_digest=sha256:<64hex>
```

The plan job fails closed on an incomplete remote-plan credential set. That
shared set includes `TF_AMPLIFY_GITHUB_ACCESS_TOKEN` because AWS Amplify
requires a repository access token for public and private GitHub repositories.
`TF_ML_IMAGE_DIGEST` is not part of the shared set: staging and
`production` run inline ML. A dedicated-ML deployment would require that
secret and an immutable digest at its own plan step.
The historical placeholder value `-` and values containing whitespace are
rejected before AWS credentials are assumed. The job then produces an
**immutable reviewed plan** consisting of 16 artifacts:

| Artifact | Records |
|---|---|
| `reviewed.tfplan` | the binary plan itself |
| `reviewed.tfplan.json` / `.txt` | machine- and human-readable renderings |
| `reviewed.tfplan.sha256` | plan checksum |
| `reviewed.commit` | the 40-char commit the plan was built from |
| `reviewed.profile` | the profile it was reviewed for |
| `reviewed.state-key` | `profiles/<profile>/terraform.tfstate` |
| `reviewed.state-bucket` | the exact S3 backend bucket used to produce the plan |
| `reviewed.state-lock-table` | the exact DynamoDB lock table used to produce the plan |
| `reviewed.terraform-version` | the concrete Terraform version |
| `reviewed.lock.sha256` | `.terraform.lock.hcl` digest, captured **before** init |
| `reviewed.created-utc` / `reviewed.expires-utc` | 24-hour validity window |
| `reviewed.resources.json` | the canonical resource inventory |
| `reviewed.policy.txt` | plan-policy report |
| `reviewed.cost.txt` | cost-model report |

The plan identity table is written to the job summary for the reviewer.

The reviewed plan supplies the API and Kyber application origins separately to
the ECS module. Kyber's Google workforce client ID and secret remain mounted
from Secrets Manager, while the Google callback is fixed to the API origin
(`https://<api-domain>/v1/kyber/auth/callback`) and WebAuthn remains bound to
the Kyber application origin. This keeps the operator browser surface and the
backend identity exchange on their intended trust boundaries.

The shared Terraform root also contains a pilot-only staging first-admin
overlay. It is not part of `production`: outside the `pilot` deployment
lane the bootstrap route is explicitly disabled and its approved email is
empty, so production receives no staging bootstrap behavior.

Pilot wake/sleep keeps each ECS capacity-provider strategy stable (FARGATE
base 0, weight 100) and changes desired task counts plus both autoscaling
bounds. Asleep services use a `0..0` scaling range so target-tracking policies
cannot revive them; the reviewed wake plan restores the declared range.
This avoids replacement-only ECS service changes during a lifecycle transition.
The exact plan is rejected before apply if it replaces an ECS service or
scaling target, removes workflow-managed Application Auto Scaling tags, deletes
an Aether Auth0 resource, or mutates deferred Kyber/Auth0 resources. Fargate
spend is estimated from desired tasks, not the provider placement base.

### Apply

```bash
gh workflow run terraform-promote.yml \
  -f profile=production \
  -f action=apply \
  -f plan_run_id=<plan run id> \
  -f plan_checksum=<reviewed.tfplan sha256>
```

The workflow names a **per-profile GitHub environment**, so the intended
configuration gives each profile its own reviewers and protection rules and
prevents borrowed approvals. In the current repository only `staging` and
`staging-terraform` exist, and neither has a protection rule; the four
production environments and their credential sets are not provisioned yet.
Their plan/apply jobs therefore fail closed on missing credentials rather than
constituting a production-ready path:

| Profile | Environment |
|---|---|
| `staging` | `staging-terraform` |
| `production` | `production-lean-terraform` |

Before any non-staging promotion, create and protect the named environment,
populate its profile-specific OIDC role and Terraform inputs, and prove the
credentialed remote plan. Do not treat an automatically created, empty GitHub
environment as approval or as evidence that the profile is configured.

Before applying anything it verifies, in order: all 16 artifacts present and
non-empty; the reviewed profile matches the dispatched one; the recorded state
key is this profile's; the recorded state bucket and lock table match the
apply backend; the commit is a 40-char SHA; the Terraform version is concrete;
expiry is after creation, the window is ≤ 24 hours, and it has not passed.

It then **checks out the plan's own recorded commit**, not the dispatch ref —
the ref may have moved since review, and `github.sha` says nothing about which
code the reviewed plan was built from — and asserts `git rev-parse HEAD` equals
it. Terraform is installed at the exact reviewed version.

The plan-policy and cost-model validators are **re-run at the reviewed
commit**. The reports in the artifact are evidence, not proof.

Immediately before applying:

```bash
test "$(cat reviewed.profile)"   = "$PROFILE"
test "$(cat reviewed.commit)"    = "$REVIEWED_COMMIT"
test "$(cat reviewed.commit)"    = "$(git rev-parse HEAD)"
test "$(cat reviewed.state-key)" = "profiles/${PROFILE}/terraform.tfstate"
test "$(cat reviewed.state-bucket)" = "$TF_STATE_BUCKET"
test "$(cat reviewed.state-lock-table)" = "$TF_LOCK_TABLE"
test "$(sha256sum reviewed.tfplan | cut -d' ' -f1)" = "$PLAN_CHECKSUM"
sha256sum --check --status reviewed.tfplan.sha256
test "$(cat reviewed.lock.sha256)"      = "$(sha256sum .terraform.lock.hcl | cut -d' ' -f1)"
test "$(cat reviewed.terraform-version)" = "$(terraform version -json | jq -r '.terraform_version')"
test "$(date -u +%s)" -lt "$(date -u -d "$(cat reviewed.expires-utc)" +%s)"
terraform apply -input=false reviewed.tfplan
```

**Apply never re-plans.** It consumes the exact binary plan that was reviewed.

### Promotability gate

`infrastructure.yml`'s `require-production-credentials` job was retained after
the auto-apply was deleted, and its meaning changed: it no longer gates an
apply, it gates **promotability**. A commit can only be dispatched for
promotion if its `main`-branch run proved that the complete remote-plan
credential set exists and that all four profiles produced credentialed, policy-
and cost-validated remote plans. Without it a commit could land on `main` with
every remote plan silently skipped and still be promoted. When the credential
set is absent the job reports it is a NO-OP — the commit is explicitly **not**
promotable — and passes green, re-arming fail-closed the moment the credentials
are wired.

## Rollback

### Application rollback

Promote the previous verified release manifest through
`.github/workflows/deploy.yml`. The workflow re-verifies the manifest and every
artifact digest before registering task revisions and static bundles. Mutable
tags are never rollback inputs. See
[Deployment Runbook](DEPLOYMENT-RUNBOOK.md).

### Infrastructure rollback

There is no "undo apply". Roll back by producing and applying a **new reviewed
plan** from the previous commit:

1. `gh workflow run terraform-promote.yml -f profile=production -f action=plan ...`
   from the last-known-good commit, with the digests that commit's release
   manifest approved.
2. Review the plan. **Read the destroy list.** A rollback plan can destroy
   resources the forward apply created.
3. Apply with that plan's run ID and checksum.

If the rollback plan would destroy a **stateful** resource — Aurora, DynamoDB,
SQS holding messages, S3, KMS keys, Secrets Manager secrets — stop. Follow
`infra/aws/terraform/DECOMMISSION.md` instead. A profile flip
showing `Plan: … 1 to destroy` on a data store is a stop-the-line event.

### Migration rollback

Apply the documented Alembic down-revision and restore from backup if data
changed. See [Backup & Restore](BACKUP-RESTORE.md) and
[Data Migrations](DATA-MIGRATIONS.md).

## Migration risks

Three real hazards apply to the first application of this profile shape. All
three are correct and intended; none is a bug to fix, and each needs to be
planned for.

### Seven ECS services are destroyed

Collapsing eight dedicated worker services into one `lean-worker` service is a
genuine **destroy of seven ECS services** — `outbox-relay`, `stream-worker`,
`identity-worker`, `graph-writer`, `measurement-worker`, `semantic-worker`,
`materializer` — on any workspace that already applied the per-role shape.

This is correct and intended. `moved` blocks are *not* appropriate here: this
is not a rename, it is a genuine change of deployment unit. The seven services
and their task definitions go away and one differently-sized service takes over
their eight roles.

What survives: every SQS queue, DLQ, consumer group and retry policy. The roles
are re-hosted, not removed. In-flight messages are not lost — they remain in
their queues and are drained by the consolidated task once it is stable.

Plan for a gap between the old services draining and the new task becoming
healthy. Do this in a maintenance window on a workspace with live traffic.

### The private default route is a maintenance window

The NAT default route used to be an inline `route` block inside
`aws_route_table.private`. It is now a standalone `aws_route.private_nat`,
counted independently — which is exactly what makes `nat_mode = "none"`
expressible.

`moved` **cannot** express this. An inline route block is an attribute, not an
addressable resource, so there is nothing to move *from*.

On the first apply against a workspace that already carries NAT
(none today; any future deployment that adds one), Terraform performs two separate
operations on the live egress path with no guaranteed ordering: an in-place
update of the route table to drop the inline route, and a create of the new
`aws_route`. Treat it as a **maintenance window**:

1. Apply it on its own, not batched with other changes.
2. Expect a brief window where private-subnet egress may be unavailable.
3. Afterwards verify each private route table has exactly one `0.0.0.0/0` route
   to the intended NAT Gateway — in `ha` mode, the NAT in the **same AZ**.
4. `nat_mode = "none"` workspaces (`staging`, `production`) are
   unaffected: there is no NAT and no private default route to migrate.

The mirror-image hazard — adding `count` to a module changing its state address
from `module.x` to `module.x[0]`, which without intervention plans a
destroy-and-recreate of a live cluster — is covered by **14 `moved` blocks** in
`moved.tf`: the four gated root modules (`rds`, `elasticache`, `msk`,
`neptune`), five dedicated-ML resources in `module.ecs`, two in `module.alb`,
and three VPC data-store security groups. Do not delete those blocks until
every workspace that predates the profile-gating commit has applied at least
once.

### Profile name collision

**The three production-class profiles collide on resource names and need
separate AWS accounts.**

`var.environment` defaults to `production` and is validated to
`production | staging | dev`. Only `profiles/staging.tfvars` overrides it.

| tfvars | `deployment_profile` | effective `environment` |
|---|---|---|
| `staging.tfvars` | `staging` | `staging` (explicit) |
| `production.tfvars` | `production` | **`production`** |

Resource names are built as `${var.project}-${var.environment}` —
`AETHER-production-*` for production and `AETHER-staging-*` for staging, so the
two profiles never collide on names even in one account. Separate Terraform
state keys (`profiles/<profile>/terraform.tfstate`) keep the *state* apart.

A dedicated customer deployment (the old `enterprise-isolated` idea) would
reuse the production names and therefore needs its own AWS account; see
"Dedicated customer deployments" in
[Deployment Profiles](../architecture/DEPLOYMENT-PROFILES.md).

## Scale-up criteria

Grow production (by variables, not a new profile) on observed, sustained conditions — not projected
ones. The full trigger table is in
[Cost Optimization](COST-OPTIMIZATION.md#scale-promotion-triggers). In short:

- `api` sustained at `max_capacity: 4` above the 800-request target.
- `lean-worker` sustained at `max_capacity: 4` above the 500-per-task queue
  depth target, or `sqs_oldest_message_age` alarming.
- **Per-role contention inside the shared task** — one role's consumer lag
  growing while the others stay flat. This is the strongest signal, because no
  amount of scaling `lean-worker` fixes it.
- `aurora_max_acu` alarming repeatedly after the ceiling has already been
  raised.
- Graph or analytics workload dominating database load (Neptune / ClickHouse).
- A compliance or customer requirement for private task subnets.

What growing production buys: one dedicated ECS service per role (9 services,
`execution_mode: dedicated`), `FARGATE_SPOT` on surge capacity for the
interruption-tolerant consumers, ElastiCache, MSK, Neptune, dedicated ML
serving, `single_nat` egress with private task subnets, and no cost ceiling.
What it never regresses: the same required baseline, the same delivery,
isolation and observability shape. `legacy_rds`, `prometheus_grafana_servers`
and `frontend_ecs_services` stay forbidden at every tier.

## What is proven

Verified in this repository, reproducibly:

- `terraform validate` **passes** for the root module.
- `terraform test -filter=tests/profile_plan.tftest.hcl` **passes** — the
  run blocks for `staging`, `staging_asleep` and `production_profile_plan`
  (plus the applied-state and egress-rejection blocks). Assertions read the **planned module graph**
  (`length(module.msk) == 0` and friends), not the locals that produced it, so
  a local that stops being wired into `count` is caught rather than passed. The
  assertions were mutation-checked by hand during development — forcing
  `count = 1` on `module.msk` fails with `module.msk is tuple with 1 element` —
  so they are known not to be tautological. There is no automated mutation
  harness in the repo; that check is a development-time discipline, not a
  standing gate.
- `scripts/release/check_cost_policy_terraform.py` statically evaluates the
  `profiles.tf` locals and proves each forbidden toggle resolves to `false` for
  `production`.
- `scripts/release/check_terraform_plan_policy.py` scores a real plan inventory
  against the contracts and passes.
- `scripts/release/check_cost_model.py` prices that inventory at
  USD 188.93/month fixed and passes with a target warning.

## What is externally blocked

None of the following can be produced from this repository, and every one is
recorded as blocked rather than counted as done:

- A **credentialed** `terraform plan` against the real backend and state key
  (`COND-LEAN-PLAN-CREDENTIALED`).
- A credentialed `terraform apply` with intact promotion provenance
  (`COND-PROMOTION-INTEGRITY`).
- Seven consecutive days of observed AWS billing (`COND-COST-OBSERVED-7D`) and
  the projected-vs-actual reconciliation within the 25% tolerance
  (`COND-COST-RECONCILED`).
- Infracost's credentialed second opinion on the cost model.
- Sustained load observation against a deployed environment.
- An executed rollback with a recovery timestamp
  (`COND-ROLLBACK-VALIDATED`).
- Alarms observed firing **and resolving** in a deployed account
  (`COND-OBSERVABILITY-LIVE`). An alarm that has never fired is untested
  wiring.
- DNS and TLS certificate confirmation against real hostnames.
- A published, checksummed `release-evidence/` bundle
  (`COND-BUNDLE-CHECKSUM`).

## What is *not* claimed

- Not applied. Not deployed. Not billed. Not load-tested.
- No multi-region, active-active or DR-region posture.
- No compliance certification, external attestation or audit coverage.
- The `100/100` figure in the `production` scorecard is the
  **code-complete** column and must never be quoted as "the score". The
  externally-verified column is `0/100` against a gate of `92`, and
  `deployment_ready` is `false`.

## See also

- [Cost Optimization](COST-OPTIMIZATION.md)
- [Staging Wake/Sleep](STAGING-WAKE-SLEEP.md)
- [Deployment Profiles](../architecture/DEPLOYMENT-PROFILES.md)
- [AWS Deployment — Infrastructure Reference](AWS-DEPLOYMENT.md)
- [Backend Execution Model](../architecture/BACKEND-EXECUTION-MODEL.md)
- `infra/aws/terraform/README.md`
- `infra/aws/terraform/DECOMMISSION.md`
