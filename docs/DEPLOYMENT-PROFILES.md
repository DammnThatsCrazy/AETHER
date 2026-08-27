---
title: Deployment Profiles
slug: operations/deployment-profiles
section: operations
visibility: I
audience: [ops, architect]
status: stable
source_files:
  - config/deployment_profiles.yaml
  - config/runtime_deployment.yaml
  - config/terraform_resource_contracts.yaml
  - AWS Deployment/aether-aws/terraform/profiles.tf
  - AWS Deployment/aether-aws/terraform/main.tf
  - AWS Deployment/aether-aws/terraform/modules/alb/main.tf
  - AWS Deployment/aether-aws/terraform/variables.tf
  - scripts/release/check_profile_config.py
  - scripts/release/check_profile_parity.py
canonical_owner: platform@aether
estimated_read_minutes: 22
toc_depth: 3
last_synced_commit: "6433ef8b"
---

# Deployment Profiles

Staging uses inline ML and therefore does not require an ML image digest;
remote-ML profiles do. Its apply role is scoped to staging and is the only
profile-specific administrator named in staging KMS key policies.

Aether declares eight deployment profiles, from a zero-backend local mock to a
contractually isolated enterprise deployment. `config/deployment_profiles.yaml`
is the canonical matrix — backend selectors, cost policy and numeric budgets —
and `scripts/release/check_profile_config.py` validates it.

Four of the eight are **cloud profiles**: `staging`, `production-lean`,
`production-scale`, `enterprise-isolated`. Six of the eight are
Terraform-selectable through `var.deployment_profile` — the four cloud
profiles plus the two ephemeral-class profiles `demo` and `preview` — and all
six have a `profiles/*.tfvars` file, a plan test and a policy contract (the
parity checker pins the selectable set to cloud ∪ ephemeral). The remaining two
(`local`, `local-full`) are local-only and are never selectable in Terraform;
they are described honestly below, including where the automation does not
exist.

`scripts/release/check_profile_parity.py` enforces that every profile-count
statement in the docs stays in lockstep with the canonical matrix, so a ninth
profile added to `config/deployment_profiles.yaml` fails CI until the docs and
the Terraform layer are updated in the same change.

`deployment_profile` is not documentation. It drives module `count` and module
inputs in the Terraform root, so a `production-lean` plan structurally cannot
contain a forbidden resource. See
[Terraform enforcement](#terraform-enforcement) for exactly how that is proven.

### Provider-credential KMS (`kms_credentials`)

Every cloud profile provisions a dedicated customer-managed CMK — `credential_kms`
in its `cost_policy.required_resources` — for the durable, envelope-encrypted
provider credential authority (`modules/kms_credentials` in the Terraform root).
It is deliberately separate from the Secrets Manager CMK (`secrets_kms`): that
key encrypts static secret stubs, this one is the root of trust for every
per-tenant provider credential the `AwsKmsEnvelopeCredentialCipher` writes, and
the two carry different rotation, access and blast-radius profiles.

The wiring is enforced at four layers:

1. **Policy** — `credential_kms` is a required resource in all four cloud
   profiles' `cost_policy`, and `config/terraform_resource_contracts.yaml`
   contracts it as `exactly:2` resources (`aws_kms_key` + `aws_kms_alias`)
   under `module.kms_credentials`.
2. **Plan** — `profiles.tf` sets `enable_credential_kms = true`, the root
   instantiates the module behind that count, and the provider-mocked
   `profile_plan.tftest.hcl` asserts `length(module.kms_credentials) == 1` for
   every cloud profile.
3. **Task definition** — the key id is injected into both the api and every
   runtime-service task as `CREDENTIAL_KMS_KEY_ID`, so the backend's cipher
   resolves its key at boot (staging/production run `CREDENTIAL_CIPHER=aws_kms`).
4. **Authorization** — the module's `iam_policy_json` is attached to the ECS
   task role via `aws_iam_role_policy`, constraining the task to the four
   envelope-crypto actions under exactly the five-key
   `{tenant_id, provider, environment, slot_name, credential_version}`
   encryption context.

The `aws_iam_role_policy` attachment is the binding grant (rather than the
module's `task_role_arns` input) to avoid a module dependency cycle: the ECS
task role lives inside `module.ecs`, and `module.ecs` consumes this module's
key id for `CREDENTIAL_KMS_KEY_ID`.

## Profile summary

| Profile | Class | Selectable in Terraform | Cost-capped | Runtime execution mode | NAT gateways |
|---|---|---|---|---|---|
| `local` | local | no | n/a | single process | n/a |
| `local-full` | local | no | n/a | compose per-role | n/a |
| `demo` | demo | **yes** | yes (USD 150 / 220) | `consolidated` — 2 tasks | **0** |
| `preview` | preview | **yes** | yes (USD 150 / 220) | `consolidated` — 2 tasks | **0** |
| `staging` | staging | **yes** | yes (USD 25 / 50) | `consolidated` — 2 tasks | **0** |
| `production-lean` | production | **yes** | yes (USD 150 / 200) | `consolidated` — 2 tasks | **0** |
| `production-scale` | production | **yes** | no | `dedicated` — 9 services | 1 (`single`) |
| `enterprise-isolated` | enterprise | **yes** | no | `dedicated` — 9 services | 3 (`ha`) |

### Immutable release digest requirements

Every selectable profile requires an immutable `backend_image_digest` from the
approved release manifest. `ml_image_digest` is required for the dedicated
`production-scale` and `enterprise-isolated` profiles. The lean, staging, demo,
and preview profiles may leave the ML digest empty when `remote_ml` is disabled,
because those profiles run inline ML and do not start a dedicated ML service.
The Terraform promotion workflow enforces this distinction and rejects an empty
ML digest for profiles that declare dedicated remote ML.

---

## `local`

| | |
|---|---|
| **Purpose** | Normal backend development. |
| **Selection** | `docker-compose up` with the default services (Postgres + one backend process). |
| **Resource inventory** | Postgres, one backend process, inline ML, local frontends. Optional: LocalStack, ClickHouse, legacy Redis, observability. |
| **Runtime topology** | One process. The `all` role is a local/test convenience token and is **never deployable** — `scripts/release/check_delivery_topology.py` enforces that. |
| **Data behaviour** | `database: postgres`, `graph: postgres`, `analytics: postgres`, `cache: memory`, `event: memory`, `object: memory`, `ml: inline`. Normal startup never seeds records. |
| **Network behaviour** | Localhost only. |
| **Cost posture** | Zero. |
| **TTL / lifecycle** | None. |
| **Security posture** | Trust-plane flags default **off** in `local`/`dev`, preserving legacy API-key responses — see [Founding-Tenant Production](FOUNDING-TENANT-PRODUCTION.md). Do not use local defaults as a model for a deployed environment. |
| **Validation** | `pytest`, `npm test`, `make ci-check`. |
| **Limitations** | Memory cache and memory event bus are **forbidden in any deployed profile**. Behaviour that depends on them does not transfer. |
| **Promotion path** | → `local-full` for integration behaviour, → `staging` for release rehearsal. |

## `local-full`

| | |
|---|---|
| **Purpose** | Full local integration — every dependency running locally. |
| **Selection** | `docker-compose --profile full up`, or the narrower `workers` / `streaming` / `analytics` / `integration` compose profiles. |
| **Resource inventory** | Postgres, Redis, LocalStack (S3/SNS/SQS), ClickHouse, Kafka + ZooKeeper, MLflow, backend, and one container per worker role. |
| **Runtime topology** | One container per role, mirroring the `dedicated` cloud shape. This is the only local profile that exercises per-role process isolation. |
| **Data behaviour** | `cache: redis`, `event: localstack`, `analytics: clickhouse`, `object: localstack-s3`, `ml: inline`. |
| **Network behaviour** | Docker bridge network; no cloud endpoints. |
| **Cost posture** | Zero (local compute). |
| **TTL / lifecycle** | None. |
| **Security posture** | LocalStack credentials are fake by construction. No real AWS principal is reachable. |
| **Validation** | `make integration-durable` and `make integration-faults` (both require Docker and must not be silently skipped for a release verdict). |
| **Limitations** | LocalStack is not SQS/SNS. Consumer-group and DLQ behaviour is representative, not authoritative. |
| **Promotion path** | → `staging`. |

## `demo`

| | |
|---|---|
| **Purpose** | Temporary live demo against a shared non-production backend. |
| **Selection** | Terraform-selectable via the same root (`AWS Deployment/aether-aws/terraform/profiles/demo.tfvars`); `variables.tf` accepts `demo`, `terraform-promote.yml` can target it. Same-root shared foundation, not dedicated infrastructure. |
| **Resource inventory** | Shared non-production Postgres, DynamoDB cache, SNS/SQS, S3, inline ML, synthetic tenant. No MSK, ElastiCache, Neptune, ClickHouse or dedicated ML service (`cost_policy` forbids them). |
| **Runtime topology** | Consolidated `config/runtime_deployment.yaml` entry (api + lean-worker hosting the eight worker roles, both autoscaling) — the same footprint shape as staging, one step down. |
| **Data behaviour** | Versioned backend-seeded synthetic tenant only. Never real customer data; normal startup remains empty. |
| **Network behaviour** | Shared non-production network, `network_egress_mode = public_ip` — no NAT Gateway. |
| **Cost posture** | `cost_capped: true`; FIXED budget target 150 / hard 220 USD/mo, validated by `validate-ephemeral-budget` against the committed demo-valid fixture (~USD 145.60/mo fixed baseline). |
| **TTL / lifecycle** | `ttl_cleanup_required: true`. Enforced by the ephemeral TTL guard: an SSM lease at `/aether/demo/demo/lifecycle/expires-at` written by `ephemeral_env.py provision`, checked hourly by `.github/workflows/ephemeral-ttl-guard.yml` (fail-closed — missing/expired lease ends the run red), and torn down by `ephemeral_env.py teardown` (scale-to-zero + floor-zeroing + lease removal). Not armed without `AWS_EPHEMERAL_LIFECYCLE_ROLE_ARN` — it then has no credential to read the lease or trip the TTL, reports it is a NO-OP and passes green, which is **not** a claim that demo is asleep; it re-arms fail-closed the moment the role is wired. |
| **Security posture** | Would inherit the shared non-production account's posture. Seed/reset additionally require an explicit staging demo policy and tenant allowlist. Unproven. |
| **Validation** | `make validate-profile-config validate-cost-policy validate-cost-policy-terraform validate-profile-parity validate-ephemeral-budget test-ephemeral-lifecycle` + profile-doctor. |
| **Limitations** | The TTL guard is the tripwire; enforcement (scale-to-zero) is the operator-run `ephemeral_env.py teardown` — it is not an automatic destroy. |
| **Promotion path** | None. A demo is never promoted; a release is rehearsed in `staging`. |

## `preview`

| | |
|---|---|
| **Purpose** | PR-specific live environment, created only when explicitly requested. |
| **Selection** | Terraform-selectable via the same root (`AWS Deployment/aether-aws/terraform/profiles/preview.tfvars`); `variables.tf` accepts `preview`, `terraform-promote.yml` can target it. Same-root shared foundation, not dedicated infrastructure. |
| **Resource inventory** | Shared foundation Postgres, DynamoDB cache, SNS/SQS, S3, inline ML, with a temporary tenant schema/prefix route. No MSK, ElastiCache, Neptune, ClickHouse or dedicated ML service. |
| **Runtime topology** | Consolidated `config/runtime_deployment.yaml` entry (api + lean-worker hosting the eight worker roles, both autoscaling). |
| **Data behaviour** | Temporary tenant on the shared foundation; auto-expiring. |
| **Network behaviour** | Shared foundation network, `network_egress_mode = public_ip` — no NAT Gateway. `cost_policy` and `forbids` keep it off a dedicated VPC, dedicated ALB, dedicated Aurora or dedicated Neptune. |
| **Cost posture** | `cost_capped: true`; FIXED budget target 150 / hard 220 USD/mo, validated by `validate-ephemeral-budget` against the committed preview-valid fixture (~USD 145.60/mo fixed baseline — same cloned footprint as demo). |
| **TTL / lifecycle** | `ttl_cleanup_required: true` and `auto-expire` enforced. The ephemeral TTL guard runs hourly over the demo/preview matrix: SSM lease at `/aether/preview/preview/lifecycle/expires-at`, fail-closed (missing/expired lease ends the run red), torn down by `ephemeral_env.py teardown`. `run-forever` is forbidden and the guard makes it unachievable. |
| **Security posture** | Would share a foundation database with other previews; isolation would rest entirely on the tenant schema prefix. Unproven. |
| **Validation** | `make validate-profile-config validate-cost-policy validate-cost-policy-terraform validate-profile-parity validate-ephemeral-budget test-ephemeral-lifecycle` + profile-doctor. |
| **Limitations** | The TTL guard is the tripwire; enforcement (scale-to-zero) is the operator-run `ephemeral_env.py teardown`. |
| **Promotion path** | None. Preview environments are discarded, not promoted. |

## `staging`

### Apply contract

Staging applies consume the exact reviewed Terraform plan; they do not
re-plan on the apply runner. The apply job must receive the dedicated staging
AWS role and, when Auth0 resources are present, the three Auth0 provider
credentials as process environment variables. Static SPA origins use
S3-safe, lowercase hyphenated tag values, and runtime log metric filters with
dimensions omit a CloudWatch default value. These details are part of the
staging profile's apply contract and are covered by the provider-input and
Terraform profile checks before a wake is authorized.

| | |
|---|---|
| **Purpose** | Release rehearsal. Wakes for validation, proves a release, returns to zero. |
| **Selection** | `terraform plan -var-file=profiles/staging.tfvars`, or `.github/workflows/staging-lifecycle.yml`, which dispatches `terraform-promote.yml` for every mutation. `environment = "staging"` is set explicitly; the root default is `production`. |
| **Resource inventory** | Aurora Serverless v2 (`aurora_min_acu = 0`, max 2), DynamoDB cache, SNS → per-role SQS queues + DLQs, S3 object lake, S3 SPA origins + SSM pointers, ALB, Secrets/KMS, CloudWatch alarms, inline ML, Postgres graph. **Zero** MSK, ElastiCache, Neptune, ClickHouse, dedicated ML, frontend ECS, legacy RDS, NAT gateways, Elastic IPs and self-managed Prometheus/Grafana. |
| **Runtime topology** | `execution_mode: consolidated`. Two always-on tasks when awake: `api` (1 vCPU / 2 GiB, max 2) and `lean-worker` (1 vCPU / 4 GiB, max 2) hosting all eight worker roles. `staging_state: asleep` drives every desired count **and every autoscaling floor** to zero. |
| **Data behaviour** | `database`/`graph`/`analytics: aurora_postgres`/`postgres`, `cache: dynamodb`, `event: sns_sqs`, `object: s3`, `ml: inline`. Aurora auto-pauses at 0 ACU while asleep. |
| **Network behaviour** | `network_egress_mode = "public_ip"` → `nat_mode = "none"`. Tasks carry a public IP on the task ENI for egress; inbound is governed entirely by the task security group, which accepts traffic only from the ALB. |
| **Cost posture** | Target USD 25/month, hard ceiling USD 50/month, against a declared `maximum_scheduled_awake_hours_per_month: 40`. Hourly resources are prorated by awake hours; per-month charges (KMS keys, secrets, alarms) accrue regardless of sleep. See [Cost Optimization](COST-OPTIMIZATION.md). |
| **TTL / lifecycle** | An awake lease is written to SSM at wake (1–8 h, default 4). `.github/workflows/staging-ttl-guard.yml` runs hourly, treats a missing or unparseable lease as **expired**, scales services to zero and drops autoscaling floors, then fails the run so the lapse is visible. Not armed without `AWS_STAGING_LIFECYCLE_ROLE_ARN` — it then has no credential to read the lease or enforce the TTL, reports it is a NO-OP and passes green, which is **not** a claim that staging is asleep; it re-arms fail-closed the moment the role is wired. Full procedure: [Staging Wake / Sleep](STAGING-WAKE-SLEEP.md). |
| **Security posture** | Same isolation shape as production-lean. The rehearsal itself probes cross-tenant reads, unauthenticated access and empty-state behaviour with two distinct tenants. |
| **Validation** | `make test-staging-lifecycle`, `make test-terraform-profiles` (run blocks `staging_profile_plan` and `staging_asleep_profile_plan`), `make deployment-profile-gate`. |
| **Limitations** | No rehearsal has been executed against real AWS. Every lifecycle control is code-complete and externally unverified — see [Readiness](#readiness-and-what-is-externally-blocked). |
| **Promotion path** | Staging is not promoted. It rehearses the artifact that `production-lean` will receive. |

## `production-lean`

| | |
|---|---|
| **Purpose** | Founding tenant and early controlled production — the smallest footprint that runs the whole platform for a first paying customer. |
| **Selection** | `terraform plan -var-file=profiles/production-lean.tfvars`. It is also the root default for `var.deployment_profile`. |
| **Resource inventory** | Identical class list to `staging`, sized for production: Aurora Serverless v2 (`aurora_min_acu = 0.5`, max 4), DynamoDB cache, SNS/SQS + DLQs, S3 object lake, S3 SPA origins + SSM pointers, ALB, Secrets/KMS, CloudWatch alarms, inline ML, Postgres graph. **Zero** MSK, ElastiCache, Neptune, ClickHouse, dedicated ML, frontend ECS, legacy RDS, NAT gateways, Elastic IPs, Prometheus/Grafana. |
| **Runtime topology** | `execution_mode: consolidated`. Two always-on tasks: `api` (1 vCPU / 2 GiB, max 4) and `lean-worker` (2 vCPU / 8 GiB, max 4) hosting all eight worker roles. No Spot at any capacity, because the task hosts `outbox-relay`. |
| **Data behaviour** | Aurora Postgres is the database, graph and analytics of record. DynamoDB is the cache. SNS/SQS is the event substrate. ML runs in-process (`remote_ml: false`), so the semantic classifier is a resident model in the `lean-worker` task. |
| **Network behaviour** | `network_egress_mode = "public_ip"` → `nat_mode = "none"`. NAT is *forbidden unless explicit*: setting this variable to a NAT mode is the explicit opt-in and must be reviewed as a cost-policy exception. |
| **Cost posture** | Fixed baseline measures **USD 187.13/month** — USD 37.13 over the USD 150 target and USD 12.87 under the USD 200 hard ceiling. The gate warns and passes. The deviation is reviewed and **accepted**, with both closing levers examined and declined; the full analysis and approval record is in [Cost Optimization](COST-OPTIMIZATION.md). Expected usage-variable cost is a further USD 107.22/month and is not bounded by the ceiling. |
| **TTL / lifecycle** | None. This profile runs continuously; 730 h/month is the pricing basis. |
| **Security posture** | Data stores in isolated subnets with no default route. Secrets fetched at container start from Secrets Manager; no secret values in task definitions or state. ALB enforces TLS 1.3 minimum. VPC flow logs on. Tasks carry a public IP for egress; inbound is ALB-only via the security group. |
| **Validation** | `make deployment-profile-gate` runs the whole no-credentials chain. `make test-terraform-profiles` proves the planned module cardinality; `make validate-terraform-profile-policy` and `make validate-cost-model` score a plan inventory. |
| **Limitations** | Never applied, never billed, never load-tested. First application of the consolidated shape **destroys seven ECS services** — see [Migration hazards](#migration-hazards). Shares `environment = "production"` with the other two production-class profiles and therefore needs its own AWS account. |
| **Promotion path** | → `production-scale` on observed, sustained load. Trigger table in [AWS Lean Production](AWS-LEAN-PRODUCTION.md). |

## `production-scale`

| | |
|---|---|
| **Purpose** | Higher traffic, once the load that justifies it has been observed. |
| **Selection** | `terraform plan -var-file=profiles/production-scale.tfvars`. |
| **Resource inventory** | Everything `production-lean` provisions, **plus** ElastiCache Redis, MSK Kafka (3 brokers), Neptune, the dedicated ML ECS service with its ALB target group and `/v1/ml/*` listener rule, and one NAT gateway. Aurora `min_acu = 1`, max 8. Legacy RDS, self-managed Prometheus/Grafana and frontend ECS services remain forbidden — those are architectural regressions, not cost decisions. |
| **Runtime topology** | `execution_mode: dedicated`. Nine services, one per role: `api` (×3), `outbox-relay` (×2), `stream-worker` (×3), `identity-worker`, `graph-writer`, `measurement-worker`, `semantic-worker`, `materializer` (×2 each), `maintenance` (×1). Baselines run on-demand; surge above the baseline runs on `FARGATE_SPOT` for the queue-draining roles only — never for `api` or `outbox-relay`. |
| **Data behaviour** | `cache: redis`, `event: kafka`, `graph: neptune`, `analytics: clickhouse` (selector only — this root provisions no ClickHouse resource), `ml: dedicated`. Aurora remains the database of record. |
| **Network behaviour** | `network_egress_mode = "single_nat"` → `nat_mode = "single"`. Private task subnets, egress through one shared NAT gateway and one Elastic IP. |
| **Cost posture** | `cost_capped: false` and **no `budget` block**. Spend is bounded by the traffic that justified the promotion; the workflows detect the absent budget and skip the numeric gate rather than erroring. The shape policy still applies. |
| **TTL / lifecycle** | None. |
| **Security posture** | Adds three data stores in isolated subnets, each with its own KMS key and security group. Redis uses TLS in transit and an AUTH token stored only in Secrets Manager. Alarms follow the backend: `elasticache_memory`, `msk_offline_partitions` and `neptune_cpu` are created only when the matching store exists, so no alarm is left permanently in `INSUFFICIENT_DATA`. |
| **Validation** | `make test-terraform-profiles` run block `production_scale_profile_plan` asserts `length(module.msk) == 1`, `length(module.elasticache) == 1`, `length(module.neptune) == 1`, `length(module.rds) == 0`, one NAT gateway and one NAT EIP. |
| **Limitations** | ClickHouse is a selector with no module behind it. `analytics: clickhouse` currently resolves to a declared intent, not provisioned infrastructure. Collides on resource names with the other two production-class profiles. |
| **Promotion path** | ← from `production-lean`; → `enterprise-isolated` when a customer contract requires isolation. |

## `enterprise-isolated`

| | |
|---|---|
| **Purpose** | Customer isolation required by contract or regulation. |
| **Selection** | `terraform plan -var-file=profiles/enterprise-isolated.tfvars`. |
| **Resource inventory** | The `production-scale` inventory with larger capacity: Aurora `min_acu = 2`, max 16, `db_multi_az = true`, `log_retention_days = 30`, and three NAT gateways with three Elastic IPs (one per AZ). |
| **Runtime topology** | `execution_mode: dedicated`, same nine services and same sizing as `production-scale`, with one deliberate difference: **no Spot anywhere**. A reclaimed surge task is an availability event to explain, not a discount to report. |
| **Data behaviour** | Same selectors as `production-scale`. `customer_specific_retention` and `region_specific_deployment` are declared as permitted, and are configured per deployment rather than provisioned by a toggle. |
| **Network behaviour** | `network_egress_mode = "ha_nat"` → `nat_mode = "ha"`: one NAT gateway per availability zone, private task subnets. |
| **Cost posture** | `cost_capped: false`, no budget block; spend is recovered contractually per customer. |
| **TTL / lifecycle** | None. |
| **Security posture — what is technically implemented** | A dedicated VPC with three-tier subnets; data stores in isolated subnets with no default route; dedicated Aurora, queues, cache, graph and S3/KMS for the deployment; per-deployment customer-managed KMS keys; Multi-AZ database; 30-day log retention; VPC flow logs; TLS 1.3 minimum at the ALB; least-privilege task IAM scoped to the queues, tables and secrets the profile actually provisions. |
| **Security posture — what is *not* claimed** | No FedRAMP authorization, no government accreditation, no contractual isolation guarantee, no dedicated-account isolation and no regional data-sovereignty claim. `may_enable: dedicated_aws_account` is a permitted *option*, and **no dedicated account has been provisioned** — every control that depends on one is externally unverified. Isolation today is VPC-, key- and state-level within whatever account the profile is applied to. |
| **Validation** | `make test-terraform-profiles` run block `enterprise_isolated_profile_plan` asserts three NAT gateways, three NAT EIPs, `nat_mode == "ha"`, and the same gated-module cardinalities as `production-scale`. |
| **Limitations** | Inherits `environment = "production"`, so it collides on resource names with both other production-class profiles and cannot share their account or region. Provisioning a dedicated account is external work. |
| **Promotion path** | Terminal. `max_supported_profile: enterprise-isolated`; Aether claims nothing beyond it. |

---

## Runtime topology — schema v2

`config/runtime_deployment.yaml` is the canonical deployable topology, and its
unit is the **ECS service, not the logical role**. Schema v1's flat `roles:` map
was replaced because the deployable unit changed.

A `services:` entry is one ECS service and one task definition. Its `roles:`
list names the logical roles that one process hosts. `execution_mode` names the
packing strategy:

- **`consolidated`** — one task hosts several logical roles through an execution
  group token (`services/runtime/roles.py::EXECUTION_GROUPS`).
  `production-lean` and `staging` run **2 always-on tasks, not 10**: `api`, plus
  one `lean-worker` whose task hosts all eight worker roles —
  `outbox-relay`, `stream-worker`, `identity-worker`, `graph-writer`,
  `measurement-worker`, `semantic-worker`, `materializer`, `maintenance`.
- **`dedicated`** — one task per logical role. `production-scale` and
  `enterprise-isolated`, where per-role scaling and per-role blast radius are
  worth eight extra task definitions.

**Consolidation moves the process boundary and nothing else.** Inside a
consolidated task every member role keeps its own queue, consumer group, DLQ,
retry policy, backpressure budget, metrics label and restart behaviour, resolved
in-process by `services/runtime/roles.py::roles_in` and
`services/runtime/consumer_specs.py`. Terraform carries the role list for one
reason only: a consolidated task must bind one SQS queue per hosted role, which
a single `SQS_QUEUE_URL` cannot express.

Two invariants are enforced by `scripts/release/check_delivery_topology.py`:

- Every role in `roles.py::WORKER_ROLES` is hosted by **exactly one** service in
  **every** profile — never orphaned, never claimed twice. `api` never hosts a
  worker role or a consumer, and the local/test role `all` is never deployable.
- Spot is forbidden outright on `api` and on any service hosting
  `outbox-relay`, so a Spot reclaim can never interrupt public traffic or the
  at-least-once delivery path.

The service key **is** the `AETHER_ROLE` token the container boots with, which
is why the consolidated service is keyed `lean-worker` and not `workers`. A
service key maps 1:1 to `"<project>-<env>-<key>"` with one load-bearing
exception: `api` is served by the Terraform-provisioned
`"<project>-<env>-backend"` service. `deploy.yml` special-cases that mapping and
`check_delivery_topology.py` pins it in both places.

### `staging_state`

`staging` declares a `staging_state` block with `awake` (multiplier 1) and
`asleep` (multiplier 0). The multiplier is applied in `profiles.tf` to three
values, and all three are load-bearing:

| Scaled | Why |
|---|---|
| `desired_count` | The obvious one, and on its own not enough. |
| autoscaling `min_capacity` | Application Auto Scaling clamps a service back up to its floor. A floor of 1 against a desired count of 0 revives the task within a cooldown, so staging never sleeps while appearing to. |
| capacity provider `base_count` | A guaranteed on-demand floor under a desired count of 0 is what `check_delivery_topology.py` rejects as `CAPACITY_BASE_EXCEEDS_DESIRED`. |

`max_capacity` is deliberately **not** scaled: the ceiling is a static safety
bound on the shape, and collapsing it would erase the reviewed envelope from a
sleeping plan. An asleep environment therefore owns exactly the same services as
an awake one and wakes by flipping one input, not by planning a different shape.

`staging_state` is a **plan-time input** to `terraform-promote.yml`. An apply
consumes the stored plan and cannot reshape it. Profiles with no `staging_state`
block are always at full capacity, and the three production-class profiles
ignore the input entirely.

Validate with `make test-runtime-topology` and `make validate-delivery-topology`.

---

## Terraform enforcement

The Terraform root at `AWS Deployment/aether-aws/terraform/` selects a profile
through `var.deployment_profile`, validated to one of `staging`,
`production-lean`, `production-scale`, `enterprise-isolated` (default
`production-lean`). `profiles.tf` derives `enable_*` locals from it, and
`main.tf` wires those into module `count` and module inputs.

Enforcement is proven at three distinct layers. They check different things and
none of them substitutes for another.

### 1. Static tripwire — locals resolve to false

`make validate-cost-policy-terraform`
(`scripts/release/check_cost_policy_terraform.py`) reads `profiles.tf` as text
and statically evaluates each toggle. Every forbidden-for-lean toggle is a
closed boolean expression over the four profiles, or the literal `false`:

| Forbidden resource | Terraform local | Derivation |
|---|---|---|
| `msk` | `enable_msk` | `local.scale \|\| local.enterprise` |
| `elasticache` | `enable_elasticache` | `local.scale \|\| local.enterprise` |
| `neptune` | `enable_neptune` | `local.scale \|\| local.enterprise` |
| `clickhouse` | `enable_clickhouse` | `local.scale \|\| local.enterprise` (selector only) |
| `dedicated_ml_service` | `enable_dedicated_ml` | `local.scale \|\| local.enterprise` |
| `nat_gateway_unless_explicit` | `enable_nat_gateway` | `local.scale \|\| local.enterprise` |
| `frontend_ecs_services` | `enable_frontend_ecs` | literal `false` — no profile |
| `legacy_rds` | `enable_legacy_rds` | literal `false` — no profile |
| `prometheus_grafana_servers` | `enable_prometheus_grafana` | literal `false` — no profile |

The validator also asserts that the `deployment_profile` variable and its
validation exist, and that each `profiles/*.tfvars` sets a profile matching its
filename. It needs no plan and no credentials, so it catches a regression the
moment it is written. It runs in `release-gate` and
`founding-tenant-release-gate`, not in `ci-check`.

### 2. Config-plan tests — planned module cardinality

`make test-terraform-profiles` runs `terraform validate` and then
`terraform test -filter=tests/profile_plan.tftest.hcl`. **`terraform validate`
passes, and `terraform test` passes for all six selectable profiles.** Ten
provider-mocked run blocks — `staging_profile_plan`, `demo_profile_plan`,
`preview_profile_plan`, `staging_asleep_profile_plan`,
`production_lean_profile_plan`, `production_scale_profile_plan`,
`enterprise_isolated_profile_plan`, plus the applied-state and egress-rejection
blocks — assert against the **planned module graph**, not against the locals
that produced it:

```hcl
length(module.msk)              == 0    # production-lean
length(module.vpc.nat_gateway_ids) == 0
module.vpc.nat_mode             == "none"

length(module.msk)              == 1    # production-scale
length(module.vpc.nat_gateway_ids) == 1

length(module.vpc.nat_gateway_ids) == 3 # enterprise-isolated
module.vpc.nat_mode             == "ha"
```

Reading the graph rather than the locals is the point: a local that stops being
wired into a `count` is caught rather than passed over. The assertions are
**mutation-proven** — forcing `count = 1` on MSK fails the lean run block with
`module.msk is tuple with 1 element`. No AWS credentials are required.

### 3. Plan policy — a real plan JSON, scored against contracts

`scripts/release/check_terraform_plan_policy.py` reads an actual
`terraform show -json` plan, derives a canonical resource inventory
(`artifacts/profile-resource-inventory.json`) and scores it against
`config/terraform_resource_contracts.yaml`, which maps every policy key to the
module address and cardinality a conforming plan must show. This is the layer
that catches a resource the locals never modelled.

```bash
make validate-terraform-profile-policy   # defaults to the committed lean fixture
make validate-cost-model                 # prices that inventory against the budget
make test-plan-policy                    # validator against pass/fail fixtures
```

`PLAN_JSON` defaults to `tests/fixtures/terraform_plans/production-lean-valid.json`
so the gate is runnable without credentials. CI overrides it with a real plan.
Both `infrastructure.yml` and `terraform-promote.yml` run the validator against
plan JSON they produced, and the cost model against the inventory it emitted.

### What the enforcement does *not* prove

A configuration plan is not an applied environment. Neither the mocked run
blocks nor the fixture-scored policy result demonstrates that a plan was
produced with credentials against the real remote state, and none of them
demonstrates that anything was applied. Reviewers must distinguish
configuration-plan evidence from environment-authoritative remote-plan
evidence, and must read the latter before promotion. `always_on_staging_compute`
in particular has nothing to count in a production plan — it is a lifecycle
property enforced by the staging automation, not a plan assertion.

---

## Promotion and the apply path

`.github/workflows/infrastructure.yml` is **plan-and-validate only and never
applies Terraform.** The `apply-production-lean` job that auto-applied on every
push to `main` has been **deleted**. What remains there:

- a provider-mocked configuration plan for each of the six selectable profiles
  on every PR, publishing an immutable `terraform-configuration-plan-*` artifact
  (the two ephemeral-class profiles are included here and deliberately excluded
  from remote-plan);
- an OIDC remote plan per cloud profile when the complete credential set is
  present, publishing `terraform-remote-plan-*` plus the policy and cost reports;
- `require-production-credentials`, which on a push to `main` gates
  **promotability**, not an apply: a commit is only dispatchable for promotion
  if its main-branch run proved the credential set exists and all four profiles
  produced a credentialed, policy- and cost-validated remote plan. When the
  credential set is absent the job reports it is a NO-OP — the commit is
  explicitly **not** promotable — and passes green, re-arming fail-closed the
  moment the credentials are wired.

`.github/workflows/terraform-promote.yml` is the **sole apply path**. It is
`workflow_dispatch`-only — no push, tag, schedule or path trigger can reach an
apply — and the apply job consumes the exact binary plan the plan job produced.
**Apply never re-plans.** Before it runs it verifies:

| Bound | Check |
|---|---|
| Plan identity | `reviewed.tfplan` digest equals the dispatched `plan_checksum`, and `sha256sum --check` passes on the recorded manifest |
| Profile | `reviewed.profile` equals the dispatched profile |
| State key | `reviewed.state-key` equals `profiles/<profile>/terraform.tfstate` |
| Commit | apply checks out the plan's **own recorded commit**, not the dispatch ref, and verifies `HEAD` matches |
| Terraform version | the installed version equals `reviewed.terraform-version` |
| Lockfile | `sha256(.terraform.lock.hcl)` equals `reviewed.lock.sha256`, captured before `init` |
| Expiry | the plan is **valid for 24 hours**; a longer claimed window, an inverted window or an expired plan all fail |
| Policy and cost | `check_terraform_plan_policy.py` and `check_cost_model.py` are re-run at the reviewed commit — the artifact reports are evidence, not proof |

Approval is per profile. The apply job binds to a distinct GitHub environment —
`staging-terraform`, `production-lean-terraform`, `production-scale-terraform`,
`enterprise-terraform` — so staging cannot borrow production's reviewers and
production cannot be applied behind staging's.

`staging_state` (`awake` | `asleep`) is a plan-time input recorded alongside the
plan as `reviewed.staging-state`, so a reviewer can see which shape was
approved. The three production-class profiles ignore it.

`.github/workflows/staging-lifecycle.yml` never runs `terraform apply` itself;
every mutation is a dispatch of `terraform-promote.yml`, and it independently
re-verifies the reviewed plan (including asserting the planned ECS desired
counts and autoscaling floors match the pinned `awake`/`asleep` shape) before
dispatching. `.github/workflows/staging-ttl-guard.yml` deliberately runs no
Terraform at all: its only enforcement action is an ECS scale-to-zero, which can
only reduce running compute.

---

## Migration hazards

Three hazards apply to the first application of the current profile shape. All
three are correct and intended; each needs planning.

- **Seven ECS services are destroyed.** Collapsing eight dedicated worker
  services into one `lean-worker` is a genuine **destroy of seven ECS
  services** on any workspace that already applied the per-role shape. This is
  not hidden behind `moved` blocks and must not be: it is a change of
  deployment unit, not a rename. Queues, DLQs, consumer groups and retry
  policies all survive; the roles are re-hosted, not removed. Plan for a gap
  between the old services draining and the new task becoming healthy.
- **The private default route is a maintenance window.** The NAT default route
  moved from an inline `route` attribute inside `aws_route_table.private` to a
  standalone `aws_route.private_nat`. `moved` **cannot** express this — an
  inline route block is an attribute, not an addressable resource, so there is
  nothing to move from. On the first apply against a NAT-carrying workspace
  (`production-scale`, `enterprise-isolated`) Terraform performs two unordered
  operations on the live egress path. Apply it alone, expect a brief egress
  outage, and afterwards verify each private route table has exactly one
  `0.0.0.0/0` route to the intended gateway — in `ha` mode, the NAT in the same
  AZ. `nat_mode = "none"` workspaces are unaffected.
- **The three production-class profiles collide on resource names.**
  `production-lean`, `production-scale` and `enterprise-isolated` all inherit
  the root default `environment = "production"`; only `staging.tfvars` overrides
  it. Resource names are `${var.project}-${var.environment}`, so all three
  generate identical ECS cluster, ALB, log group, IAM, queue and bucket names.
  Separate state keys keep the *state* apart and do nothing about the *names*.
  **They require separate AWS accounts**, not just separate state keys.

The mirror-image hazard — adding `count` to a module renaming its state address
from `module.x` to `module.x[0]`, which would otherwise plan a
destroy-and-recreate of a live cluster — is covered by 14 `moved` blocks in
`moved.tf`. Do not delete them until every pre-existing workspace has applied at
least once. Intentional removal of any data store goes through
`AWS Deployment/aether-aws/terraform/DECOMMISSION.md`, never through a profile
toggle.

### Dead second Terraform tree

`AWS Deployment/aether-aws/terraform/environments/{dev,staging,production,demo}/`
and `AWS Deployment/main.tf` are a second, **dead** Terraform tree. Between them
they reference seven modules that do not exist in this repository —
`cloudfront`, `opensearch`, `dynamodb`, `sagemaker`, `api_gateway`, `iam`,
`waf` — so `terraform init` fails there, and `environments/demo/main.tf` is not
valid HCL. It is not the deployment path and nothing applies it. Do not modify,
extend, "fix" or copy patterns out of it.

---

## Readiness, and what is externally blocked

Readiness is reported as three numbers by
`make deployment-readiness-score` (`scripts/release/check_deployment_readiness.py`)
against `config/deployment_readiness.yaml`. **They are never merged into one
number**, and the code-complete column must never be quoted as "the score".

| Scorecard | Code-complete | Externally verified | Gate (on externally verified) |
|---|---|---|---|
| overall | 100 / 100 | **20 / 100** | 90 |
| `production-lean` | 100 / 100 † | **20 / 100** | 92 |
| `staging` | 75 / 100 | **0 / 100** | 95 |

† 80 / 100 in a clean checkout. `LEAN-COST-CEILING` requires
`reports/cost/cost-report.json`, which is generated and gitignored; it reaches
100 only after `make validate-cost-model` has written it, as
`make deployment-profile-gate` does before scoring.

**1 of 17 hard gate conditions is met** (`COND-NO-EXPIRED-EXCEPTIONS`), and
`deployment_ready` is `false`.

Externally blocked — recorded as blocked, never counted as done:

- credentialed `terraform plan` and `terraform apply` against the real backend
  and state key;
- a real staging wake → validate → sleep rehearsal, and the **two consecutive**
  complete rehearsals the 100% gate requires;
- Infracost's credentialed second opinion on the cost model;
- seven days of observed AWS billing plus projected-vs-actual reconciliation;
- sustained load observation against a deployed environment;
- DNS and TLS certificate confirmation against real hostnames;
- enterprise dedicated-account provisioning.

## Validation commands

```bash
make deployment-profile-gate          # every profile gate that runs without AWS credentials
make validate-profile-config          # profile matrix + posture schema
make validate-cost-policy             # forbidden/required resource declarations
make validate-cost-policy-terraform   # Terraform locals statically encode the policy
make validate-profile-parity          # cross-source profile-set agreement (selectable = cloud ∪ ephemeral)
make validate-delivery-topology       # every worker role owned by exactly one service
make validate-terraform-profile-policy # score a real plan JSON against the contracts
make validate-cost-model              # price the inventory against the numeric budget
make validate-staging-budget          # staging awake/asleep budget (plan-policy + cost model)
make validate-ephemeral-budget        # demo/preview budget off their committed fixtures
make test-terraform-profiles          # provider-mocked per-profile plan tests
make test-runtime-topology            # execution-group topology
make test-plan-policy                 # plan-policy validator against fixtures
make test-workflow-controls           # no automatic apply, reviewed-plan integrity
make test-cost-model                  # ceilings, fail-closed pricing, exception expiry
make test-staging-lifecycle           # wake/sleep + TTL guard structural controls
make test-ephemeral-lifecycle         # demo/preview TTL guard + provision/teardown ops
make deployment-readiness-score       # the three-column scorecard
make collect-deployment-evidence      # materialise release-evidence/ with its checksum
```

## See also

### Staging state reconciliation

If a staging resource exists in AWS but is absent from the reviewed Terraform
state, reconcile state before generating a replacement plan. The guarded
`Reconcile staging Terraform state` workflow accepts only the exact
`aether-staging-backend` target-group ARN, imports only
`module.alb.aws_lb_target_group.backend[0]`, and refuses deletes or replacements.
After an import, discard the old binary plan and produce a fresh staging plan
and checksum before any apply.

If state still contains the pre-split, unindexed address
`module.alb.aws_lb_target_group.backend`, do not use the reconciliation workflow
first. Dispatch the confirmation-gated
`.github/workflows/terraform-state-migrate.yml` workflow with the affected
profile and `MIGRATE-TARGET-GROUP`. That workflow performs only the reviewed
state-address move (staging to `backend[0]`, production-class profiles to
`backend_replacement[0]`) and shares the promotion concurrency group so it
cannot race a plan or apply. Once it succeeds, discard any prior plan and run a
new plan-only promotion to regenerate the reviewed plan, inventory, checksum,
and expiry before applying.

- [AWS Lean Production](AWS-LEAN-PRODUCTION.md) — the `production-lean` profile in depth
- [Staging Wake / Sleep](STAGING-WAKE-SLEEP.md) — the staging lifecycle procedure
- [Cost Optimization](COST-OPTIMIZATION.md) — cost model, budgets and the accepted deviation
- [AWS Deployment — Infrastructure Reference](AWS-DEPLOYMENT.md) — what the Terraform root actually provisions
- [Deployment Runbook](DEPLOYMENT-RUNBOOK.md) — operator procedure
- [Release Evidence](RELEASE-EVIDENCE.md) — the evidence bundle
