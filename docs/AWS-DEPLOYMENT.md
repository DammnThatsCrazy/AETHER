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
canonical_owner: platform@aether
estimated_read_minutes: 14
toc_depth: 3
last_synced_commit: faed118
---
# AWS Deployment — Infrastructure Reference

Internal reference for Aether's AWS infrastructure. All resources are managed
by Terraform (`AWS Deployment/aether-aws/terraform/`) and deployed via the
Python orchestrator (`AWS Deployment/aether-aws/main.py`).

## Account topology

Six isolated AWS accounts are used. Cross-account IAM roles enforce least-privilege
access between them.

| Account alias | Account ID | Primary workload |
|---------------|-----------|-----------------|
| `aether-dev` | `111111111111` | Developer sandboxes, ephemeral CI environments |
| `aether-staging` | `222222222222` | Pre-production services |
| `aether-production` | `333333333333` | Customer-facing production workloads |
| `aether-data` | `444444444444` | ClickHouse, S3 data lake, MSK, SageMaker |
| `aether-security` | `555555555555` | GuardDuty master, Security Hub, CloudTrail aggregation |
| `aether-demo` | `666666666666` | Stable demo environment |

All accounts sit inside a single AWS Organization. SCPs enforce guardrails such
as region restriction (us-east-1 primary, us-west-2 DR), mandatory encryption,
and blocking public S3 bucket creation.

## Networking

Five VPCs are provisioned. Each VPC uses a `/16` CIDR with public, private, and
data subnets across three availability zones.

| VPC | CIDR block | Account |
|-----|-----------|---------|
| `aether-dev-vpc` | `10.0.0.0/16` | dev |
| `aether-staging-vpc` | `10.1.0.0/16` | staging |
| `aether-production-vpc` | `10.2.0.0/16` | production |
| `aether-data-vpc` | `10.3.0.0/16` | data |
| `aether-demo-vpc` | `10.4.0.0/16` | demo |

Production and data VPCs are peered. All inter-account traffic travels over AWS
PrivateLink or VPC peering — never over the public internet.

## Compute — ECS Fargate

All application services run on ECS Fargate (no EC2 instances to manage).

| Service | CPU (vCPU) | Memory (GB) | Min tasks | Max tasks |
|---------|-----------|------------|-----------|-----------|
| Backend API | 1 | 2 | 2 | 20 |
| Ingestion Server | 1 | 2 | 2 | 30 |
| WebSocket Gateway | 0.5 | 1 | 2 | 10 |
| Kyber Service | 1 | 2 | 1 | 10 |
| Agent Controller | 2 | 4 | 1 | 5 |
| ML Inference | 2 | 8 | 1 | 10 |
| Consent Service | 0.5 | 1 | 2 | 10 |
| Notification Service | 0.5 | 1 | 1 | 5 |
| Scheduler | 0.25 | 0.5 | 1 | 1 |

Auto-scaling triggers are CPU ≥ 70% or ALB request count ≥ 1 000 per task
(ingestion) / 500 per task (other services). Scale-in cooldown is 300 seconds.

## Data stores

| Store | Service | Purpose |
|-------|---------|---------|
| Neptune (r6g.xlarge) | Amazon Neptune | Knowledge graph — identity resolution, entity relationships |
| TimescaleDB on RDS (r6g.2xlarge, Multi-AZ) | Amazon RDS | Time-series analytics, sensor streams |
| ElastiCache Redis (r6g.large, cluster mode) | Amazon ElastiCache | Session state, rate-limit counters, pub/sub |
| S3 + Athena | Amazon S3 / Athena | Raw event archive, ad-hoc analytics |
| OpenSearch (r6g.2xlarge, 3 nodes) | Amazon OpenSearch | Full-text search, log aggregation |
| DynamoDB (on-demand) | Amazon DynamoDB | Feature flags, consent records, API key store |
| SageMaker | Amazon SageMaker | ML model training and batch inference |
| MSK (kafka.m5.xlarge, 3 brokers) | Amazon MSK | Event streaming — ingestion fan-out |

All data stores use encryption at rest (AWS-managed keys in non-production,
customer-managed KMS keys in production). TLS 1.2+ enforced in transit.

## Terraform modules

The Terraform codebase is split into 16 reusable modules under
`AWS Deployment/aether-aws/terraform/modules/`:

| Module | Manages |
|--------|---------|
| `vpc` | VPC, subnets, route tables, NACLs |
| `vpc_endpoints` | VPC Interface and Gateway endpoints |
| `alb` | Application Load Balancer, listeners, target groups |
| `ecs` | ECS cluster, Fargate service, task definition |
| `ecr` | ECR repositories, lifecycle policies |
| `aurora` | Aurora PostgreSQL cluster, subnet group, parameter group |
| `rds` | RDS instance, subnet group, parameter group |
| `elasticache` | Redis cluster, subnet group |
| `msk` | MSK cluster, broker configuration |
| `neptune` | Neptune cluster, subnet group |
| `dynamodb_cache` | DynamoDB table used for caching (TTL-backed) |
| `sqs` | SQS queues, dead-letter queues |
| `auth0` | Auth0 API resource server and application config |
| `secrets` | Secrets Manager secrets, rotation schedule |
| `monitoring` | CloudWatch alarms, dashboards, metric filters |
| `ml_drift_lambda` | Lambda function for ML model drift detection |

## Environment cost estimates

| Environment | Monthly estimate | Notes |
|-------------|-----------------|-------|
| dev | ~$2 000 | Low-capacity; no Multi-AZ |
| staging | ~$3 000 | Production-like topology, reduced instance sizes |
| production | ~$15 000 | Full redundancy, Multi-AZ, Reserved Instances |
| demo | ~$2 500 | Stable, always-on; mirrors staging sizing |

Production Reserved Instances (1-year, no upfront) cover the baseline compute
and reduce on-demand cost by ~35%.

## Disaster recovery

| Metric | Target |
|--------|--------|
| RPO (Recovery Point Objective) | 1 hour |
| RTO (Recovery Time Objective) | 4 hours |
| DR region | us-west-2 |
| DR drill cadence | Quarterly |

DR is achieved through:
- RDS Multi-AZ with cross-region read replica in us-west-2
- S3 Cross-Region Replication to a us-west-2 bucket
- ECS task definitions and Terraform state replicated to us-west-2
- Route 53 health-check failover records pointing at the DR ALB
- Runbook: `AWS Deployment/aether-aws/scripts/dr_failover.py`

DR drills are scheduled quarterly and results recorded in the incident log.

## Deploying infrastructure changes

The standard workflow for any Terraform change:

```bash
cd "AWS Deployment/aether-aws"
python main.py plan --env staging      # review plan output
python main.py apply --env staging     # apply to staging first
# validate staging, then:
python main.py plan --env production
python main.py apply --env production
```

`main.py` wraps `terraform` with account-role assumption, state backend
configuration, and a dry-run gate that requires explicit `--apply` confirmation
for changes to production.

Changes to production infrastructure require a change-management ticket and a
second approver from `platform@aether` before `apply` is permitted.

## Security posture

- **IMDSv2 required** on all EC2 instances (Fargate is exempt; no IMDS access)
- **VPC Flow Logs** enabled on all VPCs, forwarded to the `aether-security` account
- **GuardDuty** enabled organisation-wide with automated finding notifications
- **Security Hub** aggregates findings from GuardDuty, Inspector, and Macie
- **CloudTrail** organisation trail with 7-year retention in the security account
- **S3 Block Public Access** enforced at the organisation level via SCP
- **No long-lived IAM users** in production; all access via IAM Roles with
  time-limited STS tokens
