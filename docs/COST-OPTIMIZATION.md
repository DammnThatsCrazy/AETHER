---
title: Cost Optimization
slug: operations/cost-optimization
section: operations
visibility: I
audience: [ops, architect, exec]
status: stable
since_version: "8.12.0"
source_files:
  - config/deployment_profiles.yaml
  - config/aws_price_book.yaml
  - config/cost_exceptions.yaml
  - config/runtime_deployment.yaml
  - config/terraform_resource_contracts.yaml
  - scripts/release/check_cost_model.py
  - scripts/release/check_cost_policy.py
  - scripts/release/check_cost_policy_terraform.py
  - scripts/release/check_terraform_plan_policy.py
  - AWS Deployment/aether-aws/terraform/profiles.tf
canonical_owner: platform@aether
estimated_read_minutes: 16
toc_depth: 3
---

# Cost Optimization

How Aether bounds its AWS bill, what the bill actually is, and which parts of
that answer are measured versus modelled.

Two kinds of enforcement live in this system and must never be conflated:

- **Shape** — which resource *classes* a profile may provision. Declared in
  `config/deployment_profiles.yaml` under `cost_policy`, mapped to Terraform
  addresses by `config/terraform_resource_contracts.yaml`, and asserted against
  a real plan by `scripts/release/check_terraform_plan_policy.py`.
- **Magnitude** — currency ceilings in USD/month. Declared under `budget` and
  enforced by `scripts/release/check_cost_model.py` against
  `config/aws_price_book.yaml`.

A plan can satisfy the shape policy and still blow the budget (an oversized
instance class inside an allowed resource type), so both gates are required.

## Cost targets

| Profile | Mode | Target | Hard ceiling | Basis |
|---|---|---|---|---|
| `production-lean` | fixed baseline, 730 h/month | USD 150.00 | USD 200.00 | `target_fixed_monthly` / `hard_fixed_monthly` |
| `staging` | wake/sleep, 40 awake h/month | USD 25.00 | USD 50.00 | `target_monthly_spend` / `hard_monthly_spend` |
| `production-scale` | none | — | — | `cost_capped: false` |
| `enterprise-isolated` | none | — | — | `cost_capped: false`; recovered contractually |

Exceeding the **target** emits a warning and the gate passes. Exceeding the
**hard ceiling** fails the release unless an active, unexpired, non-blanket
entry in `config/cost_exceptions.yaml` covers the overage.
`config/cost_exceptions.yaml` currently declares `exceptions: []`.

The two uncapped profiles carry no `budget` block at all. That is deliberate:
their spend is bounded by the traffic that justified the promotion, not by a
fixed number, so a numeric gate there would be theatre. The workflows detect
the absent `budget` and skip the numeric gate rather than erroring.

## Fixed versus usage-variable

The price book classifies every resource into exactly one of three classes,
and the distinction is load-bearing:

- **fixed** — accrues on the clock whether or not a request arrives. Fully
  determined by the Terraform plan, therefore gate-able. An unpriceable fixed
  resource is a hard error in the model, never a silent zero.
- **usage_variable** — driven by tenant traffic. Modelled and reported as a
  low/expected/high band, but never used as a pass/fail ceiling, because the
  plan cannot determine it.
- **zero** — genuinely free control-plane objects (IAM, security groups, ALB
  listeners, ECS task definitions). Enumerated explicitly in
  `zero_cost_types` so that an *unrecognised* type stays a hard failure instead
  of a $0 guess.

Only the fixed baseline is gated. The usage band is always reported alongside
it so nobody mistakes the baseline for the bill.

## Modelled production-lean cost

Produced by `scripts/release/check_cost_model.py --profile production-lean`
against the canonical inventory that
`scripts/release/check_terraform_plan_policy.py` emits. Result: **PASS with a
target warning.**

**Read the provenance of that inventory before quoting the number.** It is
derived from `tests/fixtures/terraform_plans/production-lean-valid.json`, a
committed fixture written by hand to match the shape this Terraform root
produces. It is **not** the output of a credentialed `terraform show -json`
against real state, because no such plan has ever been produced — this
repository has no AWS credentials and no state backend. The fixture is
representative, and it is checked against the module graph the plan tests
assert, but "representative" is not "observed". Every figure below inherits
that caveat.

### Fixed baseline — USD 187.13/month

| Line item | Terraform address | Sizing | USD/mo |
|---|---|---|---|
| Fargate — `api` | `module.ecs.aws_ecs_service.backend` | 1 vCPU / 2 GiB × 1 task | 36.04 |
| Fargate — `lean-worker` | `module.ecs.aws_ecs_service.runtime_role["lean-worker"]` | 2 vCPU / 8 GiB × 1 task | 85.06 |
| Aurora Serverless v2 floor | `module.aurora.aws_rds_cluster.this` | 0.5 ACU × 730 h @ $0.12/ACU-h | 43.80 |
| Application Load Balancer | `module.alb.aws_lb.this` | 1 ALB × 730 h @ $0.0225/h | 16.43 |
| KMS customer-managed keys | `module.aurora`, `module.secrets`, `module.ecr` | 3 keys @ $1.00/key-mo | 3.00 |
| ECR repositories | `module.ecr` | 4 repos, 10 GiB storage @ $0.10/GiB-mo | 2.00 |
| Secrets Manager secrets | `module.secrets` | 2 secrets @ $0.40/secret-mo | 0.80 |
| **Total fixed** | | | **187.13** |

Priced at zero and accounted for explicitly rather than omitted: the
`db.serverless` Aurora writer instance (ACU consumption bills on the cluster),
all seven CloudWatch alarms and the single dashboard (inside the always-free
allowances of 10 alarms and 3 dashboards), and every entry in
`zero_cost_types`. Note the alarm count sits close to the free allowance:
adding four more alarms starts billing at USD 0.10 each, so an observability
change is also a cost change.

Fargate is **121.10** of the 187.13 — 66% of the fixed baseline. Aurora's floor
is 24%. Those two lines are the entire optimisation surface; everything else
sums to 22.23.

### Usage-variable band

| Scenario | Variable USD/mo | Total with fixed |
|---|---|---|
| low — single quiet pilot tenant | 15.25 | 202.38 |
| **expected — founding tenant at planned traffic** | **107.22** | **294.35** |
| high — 10× surprise | 955.40 | 1142.53 |

Largest expected variable contributors: CloudWatch Logs ingestion across 3 log
groups (33.60), DynamoDB on-demand (23.75), ALB LCU (17.52), internet egress
(13.50), S3 across 3 buckets (8.85), SQS across 4 queues (8.00), SNS across 2
topics (2.00).

Log ingestion being the single largest variable line is worth stating plainly:
a chatty debug logger can out-cost the load balancer. `log_retention_days` is
3 on both cost-capped profiles for this reason.

## The $150 target deviation — accepted

`production-lean` sits at **USD 187.13/month fixed, which is USD 37.13 over the
USD 150 target and USD 12.87 under the USD 200 hard ceiling.** The gate emits
`⚠ fixed cost USD 187.13/mo exceeds the target USD 150.00/mo (under the 200.00
ceiling)` and passes.

This deviation has been reviewed and **accepted**. The sizing is not being
changed and the target is not being moved.

| Field | Value |
|---|---|
| **Deviation** | Fixed baseline USD 187.13/mo against a USD 150.00/mo design target. Overage USD 37.13/mo (24.8%). |
| **Reason** | Both levers that would close the gap trade a bounded, known monthly cost for an unbounded, unmeasured availability risk on a live founding tenant. See the two rejected levers below. |
| **Cost impact** | +USD 37.13/month against target; +USD 409.56/year. Inside the USD 200 hard ceiling with USD 12.87/month of headroom. No `config/cost_exceptions.yaml` entry exists or is required, because the ceiling is not breached — the exception mechanism exists only for ceiling overages. |
| **Security impact** | None. No control, alarm, encryption key, secret, isolation boundary or retention setting is altered by this deviation. The shape policy is unaffected: the plan still provisions zero MSK, ElastiCache, Neptune, ClickHouse, dedicated-ML, frontend-ECS, legacy-RDS, NAT Gateway and Elastic IP resources. |
| **Operational impact** | Positive relative to the alternatives. Keeping the Aurora floor warm removes a cold-start class of latency incident; keeping `lean-worker` at 2 vCPU / 8 GiB keeps memory headroom on the one task that hosts all eight worker roles. The USD 15.87/month remaining headroom is thin: any new always-on fixed resource must be costed against it before it is added. |
| **Approved by** | `platform@aether` — repository owner decision, recorded 2026-07-25. |
| **Review date** | **2026-10-23**, or immediately on the first `COND-COST-RECONCILED` reconciliation of projected against observed spend, whichever is sooner. The deviation cannot be honestly re-argued until a real invoice exists, because the 187.13 figure is a modelled over-estimate (see *Estimation method*). |

### Rejected lever 1 — drop the Aurora floor to 0 ACU

Saving: **USD 43.80/month**, which would land the fixed baseline at USD 140.33
and clear the target outright.

Rejected. Aurora Serverless v2 has permitted a `min_capacity` of 0 since late
2024, and `profiles/staging.tfvars` already uses `aurora_min_acu = 0` — staging
is a correctness environment and a cold start there costs nothing but a slower
rehearsal. `production-lean` serves a live founding tenant. Scale-from-zero
resume is a latency event on the first request after an idle window, and a
founding tenant's traffic is exactly the shape (low volume, irregular, human-
driven) that maximises how often that window is hit. Paying USD 43.80/month for
a warm floor is buying away a recurring first-request latency incident, not
buying idle capacity.

This lever was considered and declined. It is not an open action item.

### Rejected lever 2 — halve `lean-worker` to 1 vCPU / 4 GiB

Saving: **approximately USD 42.50/month** (the task's cost scales linearly with
vCPU and GiB: 85.06 → 42.53), landing the fixed baseline at roughly USD 141.60.

Rejected. `lean-worker` is one task hosting eight logical roles —
`outbox-relay`, `stream-worker`, `identity-worker`, `graph-writer`,
`measurement-worker`, `semantic-worker`, `materializer`, `maintenance` — and it
replaces eight dedicated tasks that between them held 4096 CPU units and
8192 MiB. Memory, not CPU, is the binding constraint: eight roles' database
pools, SQS receive buffers and per-role consumer state now share one heap, and
because `production-lean` runs `remote_ml: false`, the semantic classifier runs
**in-process** in this task as a resident model rather than a request-scoped
allocation. 4 GiB fits the arithmetic and leaves nothing for it.

The blast radius argues the same way. Under consolidation a single OOM kill
takes all eight roles down simultaneously — ingestion relay, identity
resolution, graph writes, measurement, semantic classification, materialisation
and maintenance, at once. Headroom is cheaper than that incident.

This lever was considered and declined. It is not an open action item.

### What is *not* being claimed

The USD 187.13 figure is a modelled projection from a pinned price book against
a plan inventory. It is not an observed bill. No AWS invoice for this profile
exists. The `production-lean` readiness scorecard reports
`LEAN-COST-CEILING` as built-but-unproven for exactly this reason, and
`COND-COST-OBSERVED-7D` and `COND-COST-RECONCILED` remain unmet.

## Per-profile bill of materials

Shape only — what each profile is contracted to provision. Cardinalities are
the ones `config/terraform_resource_contracts.yaml` asserts against the plan.

| Resource class | staging | production-lean | production-scale | enterprise-isolated |
|---|---|---|---|---|
| S3 static SPA origins + SSM pointers | 8 | 8 | 8 | 8 |
| Application Load Balancer | ≥1 | ≥1 | ≥1 | ≥1 |
| ECS services | 2 | 2 | 9 | 9 |
| Aurora Serverless v2 cluster | ≥1 | ≥1 | ≥1 | ≥1 |
| SNS topic + SQS queues + DLQs | ≥1 | ≥1 | ≥1 | ≥1 |
| DynamoDB cache table | 1 | 1 | 1 | 1 |
| S3 log/object lake | ≥1 | ≥1 | ≥1 | ≥1 |
| KMS keys + Secrets Manager | ≥1 | ≥1 | ≥1 | ≥1 |
| CloudWatch alarms + dashboard | ≥1 | ≥1 | ≥1 | ≥1 |
| **NAT Gateways** | **0** | **0** | **1** | **3** |
| **Elastic IPs** | **0** | **0** | 1 | 3 |
| MSK Kafka | 0 | 0 | permitted | permitted |
| ElastiCache Redis | 0 | 0 | permitted | permitted |
| Neptune | 0 | 0 | permitted | permitted |
| ClickHouse | 0 | 0 | permitted (unimplemented) | permitted (unimplemented) |
| Dedicated ML ECS service | 0 | 0 | present | present |
| Frontend ECS services | **0** | **0** | **0** | **0** |
| Legacy RDS instance | **0** | **0** | **0** | **0** |
| Self-managed Prometheus/Grafana | **0** | **0** | **0** | **0** |

`frontend_ecs_services`, `legacy_rds` and `prometheus_grafana_servers` are zero
at *every* profile. Their Terraform gates are the literal `false`, not a
profile expression — SPAs are immutable S3 origins behind a CDN at every tier,
Aurora is the database of record at every tier, and observability is CloudWatch
native at every tier. `permitted_in: []` in the contracts file records that
these are architectural regressions rather than cost decisions.

`clickhouse` is declared as a contract rule with
`currently_unimplemented: true`: no ClickHouse resource exists in this root at
any profile. Scale and enterprise express the intent through
`local.analytics_backend` only. The rule exists so a future ClickHouse module
cannot appear in a lean plan unnoticed.

## Largest cost contributors, and why they are what they are

1. **Fargate, USD 121.10 (66% of fixed).** Two always-on tasks. The API is a
   single task, not two: the availability story is the ALB health check plus
   the ECS deployment circuit breaker, and `max_capacity: 4` on request count
   covers load. A permanently warm second task was paying full price for a
   failover that autoscaling already provides. The workers are one task, not
   eight — see *Rejected lever 2*. `lean-worker` is deliberately pinned to
   on-demand at every capacity (no `FARGATE_SPOT` even for surge) because it
   hosts `outbox-relay` and a Spot reclaim mid-flight on the at-least-once
   delivery path buys a two-minute interruption for a few cents.
2. **Aurora Serverless v2, USD 43.80 (24%).** The 0.5 ACU floor only. Burst
   capacity above the floor is usage-variable; Aurora storage and I/O are
   usage-variable. A 2 ACU floor would be ~USD 175/month on its own and would
   breach the ceiling — precisely the regression the magnitude gate exists to
   catch.
3. **ALB, USD 16.43 (9%).** Hourly charge only; LCU consumption is
   usage-variable and is reported at USD 17.52 in the expected scenario.
4. **Everything else, USD 2.80.** Two KMS keys and two Secrets Manager secrets.

### What was removed to get here

Not modelled as a saving in the table above, because the removed resources are
not in the plan — but they are the reason the plan looks like this:

- **NAT Gateways and Elastic IPs: zero.** `nat_mode = "none"`,
  `network_egress_mode = "public_ip"`. A single NAT Gateway is USD 32.85/month
  before USD 0.045/GB processing; two AZs of NAT is a third of the entire lean
  budget. Tasks reach the internet through a public IP on the task ENI;
  inbound is still governed entirely by the task security group, which accepts
  only ALB traffic.
- **MSK: absent.** A 3-broker `kafka.m5.large` cluster is ~USD 460/month before
  storage — more than twice the lean ceiling. MSK Serverless is ~USD 547/month
  base. This is the single most expensive thing a misconfigured plan can add.
- **ElastiCache, Neptune, dedicated ML serving, self-managed observability
  compute: absent.**
- **Eight worker ECS services collapsed into one.** ~USD 85/month for the two
  tasks that remain against ~USD 234/month for the ten they replace.

## Estimation method

`config/aws_price_book.yaml` is a pinned, region-scoped, manually transcribed
table — not a pricing API. This is deliberate: a cost gate must be
deterministic, so the same plan scores the same on every CI run and an upstream
price change arrives as a reviewed diff rather than a surprise red build.

The model reads a resource inventory derived from `terraform show -json`,
resolves each resource to a pricing rule, and produces a fixed total plus a
usage band. Pricing models: `flat`, `by_attribute`, `fargate`
(`(cpu/1024 × vcpu_hour + memory/1024 × gb_hour) × hours × desired_count`), and
`aurora_serverless_v2` (min-ACU floor only).

`desired_count` is priced as the fixed floor, not the peak. That is the honest
reading: you are committing to the floor; autoscaling above it is
usage-variable.

A resource whose only planned action is `delete` does not count — it is on its
way out. `no-op`, `update` and any replace (`delete`+`create`) all count,
because they all leave the resource existing and billing.

### Pricing region and assumptions

**Region: `us-east-1`.** Mandatory and checked — a profile whose `budget`
declares a different region fails the model rather than being priced against
the wrong table. Price book captured **2026-07-25** by manual transcription
from the AWS public on-demand price list pages, reviewed in PR.

The model does **not** account for:

- Savings Plans, Reserved Instances, Compute Savings Plans, or Spot pricing.
- Free-tier allowances beyond the always-free ones explicitly encoded as
  `free_allowance` (10 CloudWatch alarms, 3 dashboards). Every other rate is
  the post-free-tier on-demand rate, so the model **over-estimates a new
  account**.
- Tiered volume discounts. S3, CloudFront and data transfer all step down with
  volume; the rates used are the first, most expensive tier.
- Cross-AZ or cross-region data transfer, which depends on runtime traffic
  shape rather than plan shape.
- Marketplace charges, support plans, or taxes.
- ARM/Graviton Fargate, which is ~20% cheaper than the x86 rates used.
- Multi-AZ RDS (roughly doubles the single-AZ rate and is not detected).
- High-resolution CloudWatch alarms (3× standard and not detected).
- Multi-AZ interface VPC endpoints — priced for one AZ only and flagged
  `approximate: true`.

Every deliberate approximation carries `approximate: true` and an inline note.
**Over-estimating is the safe direction for a ceiling**, and every unmodelled
factor above pushes the same way, so the real bill should come in at or below
USD 187.13 — but that is an argument, not a measurement.

This is an order-of-magnitude release gate. It answers "is this roughly a $120
plan or roughly a $900 plan", which is the only question that matters when the
ceiling is $200. It is not accurate to the cent, it is not a billing forecast,
and it is not authoritative for finance. The generated report says so on every
run.

### Infracost

Infracost is the natural credentialed second opinion and is **not** the gate.
It requires an API key and network egress, so it can only ever run as a
credential-gated advisory job. No Infracost run has been performed; that
reconciliation is externally blocked.

## Cost exceptions

`config/cost_exceptions.yaml` is the only mechanism by which a profile may
exceed its **hard ceiling**. It is currently empty by design, and nothing in
this document requires an entry.

The schema is built so exceptions cannot rot:

1. `expires` is required and must be a real future date. An expired exception
   does not quietly stop applying — it **fails the build** the day the clock
   runs out.
2. There is no "permanent", "indefinite" or "until further notice" state. The
   schema has no field for it.
3. `max_duration_days` caps a single grant: 90 days by default, **30 days for
   `production-lean`**.
4. A `production-lean` exception may not be blanket-scoped. It must name the
   resources it covers and put a number on the overage. An entry with
   `affected_resources: [all]` (or `*`, `any`, `everything`, `all_resources`,
   or empty) is rejected outright.
5. `max_estimated_amount` bounds the grant: USD 500 by default, **USD 100 for
   `production-lean`**.
6. `owner` and `approver` must be different people — no self-approval.

A grant raises the effective ceiling by `estimated_amount` and *only* by that
amount. It does not disable the gate: if modelled cost exceeds
ceiling + estimated_amount, the build still fails, so an under-stated estimate
buys nothing.

All six rules are enforced in `scripts/release/check_cost_model.py`, not by
review convention.

## Budget alerts

**There are no AWS Budgets resources and no cost-anomaly detection in the
Terraform root today.** Cost enforcement in this repository is entirely
pre-deployment: the plan-time model above, run in
`.github/workflows/infrastructure.yml` (remote-plan job),
`.github/workflows/terraform-promote.yml` (both plan and apply), and
`.github/workflows/staging-lifecycle.yml` (wake validation and rehearsal
evidence).

Post-deployment cost observation is externally blocked and is tracked as
`COND-COST-OBSERVED-7D` and `COND-COST-RECONCILED` in
`config/deployment_readiness.yaml`, with the standing exception
`DR-EX-NO-BILLING-HISTORY`. Provisioning an AWS Budget with an alert threshold
should be part of the same change that first applies `production-lean`; it
cannot be validated from here.

The operational alarms that *do* exist are correctness alarms with cost
side-effects, not budget alarms: `aurora_max_acu` (Aurora at ceiling ACU for
>10 min), `sqs_queue_depth`, `sqs_oldest_message_age`, `sqs_dlq_depth`,
`dynamodb_cache_throttled`, `alb_5xx`, `ml_drift`.

## Review cadence

| Trigger | Action | Owner |
|---|---|---|
| Every PR touching `AWS Deployment/**` | Provider-mocked configuration plan for all four profiles; `terraform validate` and `terraform test` | CI, `infrastructure.yml` |
| Every credentialed remote plan | `check_terraform_plan_policy.py` + `check_cost_model.py`, immutable artifact retained 30 days | CI |
| Every reviewed promotion (plan *and* apply) | Both validators re-run at the reviewed commit; apply never trusts the plan-time report | CI, `terraform-promote.yml` |
| Price book `captured` date older than 90 days | Re-transcribe from the AWS price list pages, bump `captured`, diff the reference `cost-report.json` before merging | `platform@aether` |
| **2026-10-23** | Re-review the accepted $150 target deviation above | `platform@aether` |
| First 7 consecutive days of observed spend | Export Cost Explorer daily totals to `release-evidence/cost/observed-cost.json`; reconcile against the modelled report within the declared 25% tolerance | `platform@aether`, `finance@aether` |
| Any new always-on fixed resource | Cost it against the USD 15.87/month of remaining ceiling headroom **before** merging | change author |

## Scale-promotion triggers

`production-scale` is `cost_capped: false`. Promotion buys capacity, so the
question is never "is this cheaper" — it is "has the traffic that justifies
this arrived". Promote when the founding-tenant deployment shows a sustained,
observed condition, not a projected one:

| Signal | Threshold | What it means |
|---|---|---|
| `api` autoscaling | Sustained at `max_capacity: 4` with ALB request count above the 800/target threshold | One API task and a 4× surge ceiling no longer cover peak. |
| `lean-worker` autoscaling | Sustained at `max_capacity: 4` with SQS queue depth above the 500/task target, or `sqs_oldest_message_age` alarming | Consolidated workers cannot drain the backlog; per-role scaling is now worth eight task definitions. |
| Per-role contention | One role starving the others inside the shared task — visible as one role's consumer lag growing while the others stay flat | The consolidation boundary itself is the constraint. This is the strongest signal, because no amount of scaling `lean-worker` fixes it. |
| `aurora_max_acu` | Alarming — at the 4 ACU ceiling for >10 min repeatedly | Raise `aurora_max_acu` first; sustained saturation after that is a scale signal. |
| Graph workload | Aurora Postgres graph queries dominating database load | Neptune (`graph_backend`) becomes justified. |
| Analytics workload | Aggregate queries dominating database load | ClickHouse becomes justified — note it is a selector only today and no module exists. |
| Egress posture | A compliance or customer requirement for private task subnets | `network_egress_mode = single_nat` or `ha_nat`. On a cost-capped profile this is the explicit opt-in the `nat_gateway_unless_explicit` policy requires and must be reviewed as a cost-policy exception. |

Promotion is a Terraform profile change and goes through
`.github/workflows/terraform-promote.yml` like any other. Note that
`production-lean`, `production-scale` and `enterprise-isolated` all inherit
`environment = "production"` and collide on resource names — see
[AWS Lean Production](AWS-LEAN-PRODUCTION.md#profile-name-collision) before
planning any promotion. They need separate AWS accounts, not just separate
state keys.

## Running the gates

```bash
# Shape — canonical policy data is well-formed
make validate-cost-policy

# Shape — Terraform locals statically encode the policy
make validate-cost-policy-terraform

# Shape — a real plan realises it (emits artifacts/profile-resource-inventory.json)
python scripts/release/check_terraform_plan_policy.py \
  --profile production-lean --plan-json plan.json

# Magnitude — price the inventory against the budget
python scripts/release/check_cost_model.py \
  --profile production-lean \
  --inventory artifacts/profile-resource-inventory.json \
  --out-dir artifacts/cost-production-lean

# Magnitude — treat a target breach as fatal instead of a warning
python scripts/release/check_cost_model.py --profile production-lean \
  --inventory artifacts/profile-resource-inventory.json --fail-on-target
```

`--fail-on-target` is available and is **not** used in CI: with the accepted
deviation above in force, it would fail every run.

## See also

- [AWS Lean Production](AWS-LEAN-PRODUCTION.md) — the topology these numbers price
- [Staging Wake/Sleep](STAGING-WAKE-SLEEP.md) — the 40-awake-hours budget model
- [Deployment Profiles](DEPLOYMENT-PROFILES.md) — the full eight-profile matrix
- [Release Evidence](RELEASE-EVIDENCE.md) — where cost evidence lands in the bundle
