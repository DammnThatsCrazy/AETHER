# Aether AWS Deployment v8.3.1

Multi-account AWS infrastructure for the Aether platform, provisioned with Terraform and operated via Python automation scripts. Spans six AWS accounts, five VPCs, nine ECS Fargate services, eight managed data stores, and a full security/compliance posture -- all orchestrated from a single configuration source.

---

## Table of Contents

- [Technology Stack](#technology-stack)
- [Architecture Overview](#architecture-overview)
- [Architecture Diagram](#architecture-diagram)
- [Project Structure](#project-structure)
- [Installation](#installation)
- [Quick Start](#quick-start)
- [Configuration Reference](#configuration-reference)
- [Terraform](#terraform)
- [Operational Scripts](#operational-scripts)
- [Shared Utilities](#shared-utilities)
- [Disaster Recovery](#disaster-recovery)
- [License](#license)

---

## Technology Stack

| Layer          | Technology                                                                 |
|----------------|---------------------------------------------------------------------------|
| Language       | Python >= 3.9                                                             |
| IaC            | Terraform >= 1.7, AWS Provider ~> 5.40                                    |
| AWS SDK        | boto3 >= 1.34                                                             |
| CLI Output     | Rich >= 13.0, PyYAML >= 6.0                                              |
| Testing        | pytest >= 8.0, moto >= 5.0, pytest-cov >= 5.0                            |
| Compute        | ECS Fargate, Lambda                                                       |
| Data           | RDS/TimescaleDB, Neptune, ElastiCache Redis, DynamoDB, S3, OpenSearch, MSK Kafka, SageMaker |
| Networking     | ALB, CloudFront CDN, API Gateway (HTTP + WebSocket), Route 53, WAF        |
| Security       | GuardDuty, Security Hub, Secrets Manager, KMS, IAM (least privilege)      |

---

## Architecture Overview

### AWS Accounts (6)

| Account              | ID             | Purpose                                                      |
|----------------------|----------------|--------------------------------------------------------------|
| `aether-dev`         | `111111111111` | Development and testing                                      |
| `aether-staging`     | `222222222222` | Pre-production validation (full replica at reduced scale)     |
| `aether-production`  | `333333333333` | Live customer traffic -- Multi-AZ, auto-scaling, full monitoring |
| `aether-data`        | `444444444444` | Data lake, ML training, SageMaker jobs, Athena queries        |
| `aether-security`    | `555555555555` | CloudTrail aggregation, GuardDuty, Security Hub               |
| `aether-demo`        | `666666666666` | Sales and BD demo environment -- pre-seeded data, single-AZ   |

### VPC Networking (5 VPCs)

Each VPC is deployed with 3 Availability Zones, public subnets (ALB, NAT Gateways, bastion hosts) and private subnets (ECS tasks, RDS, ElastiCache, Neptune, Lambda). The demo VPC uses a simplified single-AZ topology.

| VPC          | CIDR            | NAT Gateways | Flow Log Retention |
|--------------|-----------------|:------------:|:------------------:|
| dev          | `10.0.0.0/16`   | 1            | 7 days             |
| staging      | `10.1.0.0/16`   | 1            | 14 days            |
| production   | `10.2.0.0/16`   | 3 (HA)       | 30 days            |
| data         | `10.3.0.0/16`   | 1            | 30 days            |
| demo         | `10.3.0.0/16`   | 1            | 7 days             |

**VPC Peering:** production <-> data (ML model access)

**12 VPC Endpoints (PrivateLink):** 2 Gateway (S3, DynamoDB -- free) + 10 Interface (ECR API, ECR Docker, CloudWatch Logs, CloudWatch Monitoring, Secrets Manager, SageMaker Runtime, SQS, SNS, KMS, STS). Keeps traffic on the AWS backbone, reduces NAT costs, and improves security.

**DNS (Route 53):**

| Domain                     | Purpose    |
|----------------------------|------------|
| `api.aether.network`       | API        |
| `dashboard.aether.network` | Dashboard  |
| `ws.aether.network`        | WebSocket  |
| `cdn.aether.network`       | CDN        |

### Compute -- ECS Fargate (9 Services)

| Service        | CPU  | Memory | Min | Max | Target CPU% | Port | Health Check     |
|----------------|-----:|-------:|----:|----:|:-----------:|-----:|------------------|
| ingestion      |  512 | 1024M  |   2 |  20 |     60%     | 8001 | `/v1/health`     |
| identity       |  512 | 1024M  |   2 |  10 |     60%     | 8002 | `/v1/health`     |
| analytics      | 1024 | 2048M  |   2 |  15 |     70%     | 8003 | `/v1/health`     |
| ml-serving     | 1024 | 4096M  |   2 |  20 |     50%     | 8004 | `/v1/health`     |
| agent          |  512 | 2048M  |   1 |  10 |     70%     | 8005 | `/v1/health` (Spot) |
| campaign       |  256 |  512M  |   1 |   5 |     60%     | 8006 | `/v1/health`     |
| consent        |  256 |  512M  |   1 |   3 |     60%     | 8007 | `/v1/health`     |
| notification   |  256 |  512M  |   1 |   5 |     60%     | 8008 | `/v1/health`     |
| admin          |  256 |  512M  |   1 |   3 |     60%     | 8009 | `/v1/health`     |

*Production specs shown above. Staging runs at half scale (min_count=1). Dev and demo run at minimal resources (256 CPU, 512M, single instance).*

Additional compute: Lambda functions (EventBridge-triggered ML retraining, data cleanup), API Gateway WebSocket for real-time streaming.

### Data Stores (8)

| Store                      | Instance Type         | Configuration                                              |
|----------------------------|-----------------------|------------------------------------------------------------|
| Neptune (Graph DB)         | `db.r6g.xlarge`       | Multi-AZ, read replicas, PITR 35-day                       |
| RDS PostgreSQL+TimescaleDB | `db.r6g.xlarge`       | Multi-AZ, automated backups, performance insights           |
| ElastiCache Redis          | `cache.r6g.large`     | Cluster mode, 3 shards x 2 replicas, daily snapshots        |
| S3 + Athena (Event Store)  | Intelligent Tiering   | Parquet, partitioned by tenant/date, versioned              |
| OpenSearch (Vector Store)  | `r6g.large.search`    | 3 nodes, k-NN plugin, encrypted, TLS 1.2                   |
| DynamoDB (Config Store)    | On-demand             | Global tables for multi-region, PITR                        |
| SageMaker Feature Store    | Online + Offline      | Online + Offline stores, 9 ML models                        |
| MSK (Kafka)                | `kafka.m5.large`      | 3 brokers, 3 AZs, TLS, 168h retention                      |

All stores enforce encryption at rest (KMS) and encryption in transit (TLS).

### Networking and Edge

- **ALB** -- Application Load Balancer in public subnets, routes to ECS services
- **CloudFront CDN** -- 2 distributions: SDK (`cdn.aether.network`), Dashboard SPA
- **API Gateway** -- HTTP API (`api.aether.network`) + WebSocket API (`ws.aether.network`)
- **Route 53** -- DNS management with custom domains
- **WAF** -- Rate limiting, bot control, IP reputation, DDoS protection (Shield Standard)

### Security and Compliance (12 Controls)

- Encryption at rest (KMS) and in transit (TLS 1.2+)
- IAM least privilege with OIDC federation
- CloudTrail multi-region audit logging
- GuardDuty threat detection + Security Hub compliance scoring
- Secrets Manager with automatic rotation (Lambda rotator in production)
- VPC + Security Groups + NACLs network segmentation
- WAF + Shield Standard DDoS protection
- ECR container image scanning on push
- PrivateLink enforcement for AWS service access
- 9 managed secrets with KMS encryption and cross-region replication

### Disaster Recovery

| Parameter       | Value                              |
|-----------------|-------------------------------------|
| RPO             | 1 hour                              |
| RTO             | 4 hours                             |
| DR Region       | `us-west-2`                         |
| Terraform Rebuild | 2 hours                           |
| Drill Frequency | Every 90 days (quarterly)           |

Cross-region replication is configured for S3, DynamoDB (global tables), RDS (snapshots), and Secrets Manager. Neptune, ElastiCache, MSK, and OpenSearch use automated backups with point-in-time recovery. Full environment rebuild from Terraform is validated within 2 hours.

---

## Architecture Diagram

```
                            Internet
                               |
                        +------+------+
                        |  Route 53   |
                        +------+------+
                               |
              +----------------+----------------+
              |                                 |
       +------+------+                  +-------+-------+
       |  CloudFront |                  |  API Gateway  |
       |  (CDN/SPA)  |                  |  HTTP + WS    |
       +------+------+                  +-------+-------+
              |                                 |
       +------+------+                  +-------+-------+
       |     WAF     |                  |      ALB      |
       +-------------+                  +-------+-------+
                                                |
                 +------------------------------+------------------------------+
                 |          |          |         |         |         |          |
              ingestion  identity  analytics  ml-srv   agent    campaign   ...
              (ECS Fargate -- 9 services, private subnets, autoscaling)
                 |          |          |         |         |         |
     +-----------+----------+----+----+---------+---------+---------+----------+
     |           |               |              |                   |          |
  +--+--+   +---+---+   +-------+-------+   +--+--+          +-----+-----+   |
  | RDS |   |Neptune|   |ElastiCache    |   | MSK |          | OpenSearch|   |
  | PG  |   | Graph |   |Redis Cluster  |   |Kafka|          | (Vector)  |   |
  +-----+   +-------+   +---------------+   +-----+          +-----------+   |
                                                                              |
     +----------+----------+-----------+-------------------+                  |
     |          |          |           |                   |                  |
  +--+--+  +---+---+  +---+---+  +----+----+   +----------+---------+
  |  S3 |  |DynamoDB|  | Athena|  |SageMaker|   |  Security Account  |
  |     |  | Global |  |       |  | ML/FS   |   |  GuardDuty, Hub,   |
  +-----+  +--------+  +-------+  +---------+   |  CloudTrail        |
                                                 +--------------------+

  Accounts: dev (10.0/16) | staging (10.1/16) | production (10.2/16) | data (10.3/16) | demo (10.3/16) | security
  Regions:  us-east-1 (primary)  |  us-west-2 (DR -- cross-region replication)
```

---

## Project Structure

```
aether-aws/
  main.py                          # Demo runner -- supports explicit stub/live AWS selection
  pyproject.toml                   # Project metadata, dependencies, scripts
  config/
    aws_config.py                  # Central configuration (single source of truth)
  scripts/
    network/network_ops.py         # VPC health, route tables, peering, endpoints
    monitoring/monitoring_ops.py   # CloudWatch alarms, dashboards, X-Ray, metrics
    cost/cost_ops.py               # Cost Explorer, budgets, forecasting, tagging
    security/security_ops.py       # GuardDuty, Security Hub, IAM audit, compliance
    capacity/capacity_ops.py       # Autoscaling, utilization, rightsizing recommendations
    dr/disaster_recovery.py        # DR failover, runbook, drills, cross-region validation
  shared/
    runner.py                      # Unified command execution + structured logging
    aws_client.py                  # boto3 session factory with stub mode for demo/CI
    notifier.py                    # Notification dispatcher (Slack, PagerDuty, SNS)
  terraform/
    modules/                       # 17 reusable Terraform modules
      vpc/                         # VPC, subnets, NAT GWs, flow logs, peering
      ecs/                         # 9 Fargate services, ALB, autoscaling
      rds/                         # Aurora PostgreSQL + TimescaleDB
      neptune/                     # Graph DB, Multi-AZ, read replicas
      elasticache/                 # Redis cluster mode
      msk/                         # Managed Kafka
      opensearch/                  # Vector store, k-NN plugin
      dynamodb/                    # Global tables, PITR
      s3/                          # Data lake, CDN origin, ML artifacts
      cloudfront/                  # CDN + Dashboard SPA
      api_gateway/                 # HTTP + WebSocket APIs
      sagemaker/                   # Multi-model endpoint, feature store
      monitoring/                  # CloudWatch, X-Ray, Grafana, budgets
      waf/                         # Rate limiting, bot control
      iam/                         # CI/CD roles, cross-account, GuardDuty
      secrets/                     # Secrets Manager, KMS, Lambda rotator
      vpc_endpoints/               # 12 VPC endpoints (PrivateLink)
    environments/
      dev/main.tf                  # Dev composition (minimal resources)
      staging/main.tf              # Staging composition (half-scale)
      production/main.tf           # Production composition (full Multi-AZ)
      demo/main.tf                 # Demo composition (single-AZ, pre-seeded data, playground hosting)
      shared/                      # Shared variables and outputs
  tests/                           # pytest test suite (moto for AWS mocking)
```

---

## Installation

**Prerequisites:**

- Python >= 3.9
- Terraform >= 1.7
- AWS CLI (configured with appropriate credentials, or use stub mode)

**Install dependencies:**

```bash
pip install -e .
```

**Install dev dependencies (testing):**

```bash
pip install -e ".[dev]"
```

---

## Quick Start

Run the full architecture demo with stub mode (no AWS credentials required):

```bash
python3 main.py --stub-aws
```

This prints the complete deployment architecture and executes all six operational scripts with illustrative data:

1. Account structure and VPC networking
2. Compute specs (ECS Fargate, all 9 services across 3 environments)
3. Data store deployment details
4. Secrets management inventory
5. Monitoring and observability stack
6. Security and compliance audit
7. Budget configuration
8. Disaster recovery runbook and drill

To run against live AWS accounts, ensure valid credentials and use live mode explicitly:

```bash
AETHER_STUB_AWS=0 python3 main.py --live-aws
```

Or use the installed entry point:

```bash
aether-aws
```

---

## Configuration Reference

All infrastructure parameters are defined in `config/aws_config.py`. This file is the single source of truth referenced by both Python scripts and Terraform modules.

### Key Configuration Objects

| Object              | Description                                                        |
|---------------------|--------------------------------------------------------------------|
| `AWS_ACCOUNTS`      | 6 accounts (dev, staging, production, data, security, demo) with IDs and regions |
| `VPC_CONFIGS`       | CIDR blocks, AZ count, subnet layout, NAT gateway count per VPC   |
| `VPC_ENDPOINTS`     | 12 PrivateLink endpoint definitions with type and rationale        |
| `COMPUTE_SPECS`     | Per-service CPU, memory, scaling bounds for all 4 environments     |
| `DATA_STORES`       | Instance types, configurations, encryption settings                |
| `SECRETS`           | 9 managed secrets with rotation schedules                          |
| `MONITORING_STACK`  | 7 monitoring layers (metrics, logging, tracing, alerting, dashboards, cost, security) |
| `COMPLIANCE_CONTROLS` | 12 security/compliance controls with implementation status       |
| `DR` / `DR_STRATEGIES` | RPO/RTO targets and per-service recovery strategies             |
| `BUDGET_CONFIGS`    | Per-account monthly budgets with alert thresholds                  |
| `DNS_DOMAINS`       | Custom domain mappings for API, dashboard, WebSocket, CDN          |

### Environment Variables

| Variable                | Default       | Purpose                                           |
|-------------------------|---------------|---------------------------------------------------|
| `AETHER_STUB_AWS`       | `0`           | Set to `1` to run without AWS credentials (demo/CI) |
| `AWS_REGION`            | `us-east-1`   | Primary AWS region for boto3 client                |
| `AWS_PROFILE`           | (none)        | Named AWS CLI profile to use                       |
| `AETHER_SLACK_WEBHOOK`  | (none)        | Slack webhook URL for notifications                |
| `AETHER_PAGERDUTY_KEY`  | (none)        | PagerDuty integration key for alerts               |
| `AETHER_SNS_TOPIC_ARN`  | (none)        | SNS topic ARN for notification publishing          |

---

## Terraform

### Overview

17 Terraform modules compose the full infrastructure across 4 environment layers (dev, staging, production, demo). State is stored in S3 with DynamoDB locking (per-environment keys).

| Module           | Resources                                                           |
|------------------|---------------------------------------------------------------------|
| `vpc`            | VPC, subnets (public + private), NAT Gateways, flow logs, peering   |
| `ecs`            | 9 Fargate services, ALB, autoscaling, canary target groups           |
| `rds`            | Aurora PostgreSQL + TimescaleDB, Multi-AZ, automated backups         |
| `neptune`        | Graph database, Multi-AZ, read replicas, PITR                       |
| `elasticache`    | Redis cluster mode, 3 shards x 2 replicas                           |
| `msk`            | Managed Kafka, 3 brokers, 3 AZs, TLS, retention policies            |
| `opensearch`     | Vector store, k-NN plugin, 3 nodes, encrypted                       |
| `dynamodb`       | 5 tables, on-demand, global tables, PITR                            |
| `s3`             | Data lake, CDN origin, dashboard SPA, ML artifacts, Athena results   |
| `cloudfront`     | SDK CDN + Dashboard SPA, Origin Access Control, WAF integration      |
| `api_gateway`    | HTTP API + WebSocket API, custom domains, Route 53 records           |
| `sagemaker`      | Multi-model endpoint, autoscaling, feature store                     |
| `monitoring`     | CloudWatch alarms, X-Ray, Grafana, budgets, dashboards               |
| `waf`            | Rate limiting, bot control, IP reputation, managed rules             |
| `iam`            | CI/CD roles, cross-account access, CloudTrail, GuardDuty             |
| `secrets`        | Secrets Manager, KMS key rotation, Lambda secret rotator             |
| `vpc_endpoints`  | 12 VPC endpoints: S3, DynamoDB (Gateway) + 10 Interface (PrivateLink) |

### Environments

| Environment | State Key                        | Budget      | Scaling        |
|-------------|----------------------------------|-------------|----------------|
| dev         | `dev/terraform.tfstate`          | $2,000/mo   | Minimal (1 task per service) |
| staging     | `staging/terraform.tfstate`      | $3,000/mo   | Half-scale     |
| production  | `production/terraform.tfstate`   | $15,000/mo  | Full Multi-AZ  |
| demo        | `demo/terraform.tfstate`         | $2,500/mo   | Minimal, single-AZ, playground hosting |

### Usage

```bash
# Initialize (production example)
cd terraform/environments/production
terraform init

# Plan
terraform plan \
  -var="ecr_registry=333333333333.dkr.ecr.us-east-1.amazonaws.com" \
  -var="image_tag=v1.2.3" \
  -var="acm_cert_arn=arn:aws:acm:us-east-1:333333333333:certificate/xxx" \
  -var="hosted_zone_id=Z1234567890"

# Apply
terraform apply
```

**Required variables:**

| Variable            | Description                                            |
|---------------------|--------------------------------------------------------|
| `ecr_registry`      | ECR registry URL (`account_id.dkr.ecr.region.amazonaws.com`) |

**Optional variables:**

| Variable             | Default       | Description                                |
|----------------------|---------------|--------------------------------------------|
| `environment`        | `production`  | Environment name                           |
| `aws_region`         | `us-east-1`   | Primary AWS region                         |
| `image_tag`          | `latest`      | Docker image tag for ECS services          |
| `acm_cert_arn`       | (empty)       | ACM certificate ARN for HTTPS              |
| `hosted_zone_id`     | (empty)       | Route 53 hosted zone ID for DNS records    |
| `monthly_budget_usd` | `15000`       | Monthly budget in USD for cost alerts      |

---

## Operational Scripts

Six scripts cover the full operational surface. Each script imports configuration from `config/aws_config.py` and uses shared utilities for AWS access, command execution, and notifications.

| Script                         | Domain     | Capabilities                                                |
|--------------------------------|------------|-------------------------------------------------------------|
| `scripts/network/network_ops.py`     | Network    | VPC health, route tables, peering, endpoint verification     |
| `scripts/monitoring/monitoring_ops.py` | Monitoring | CloudWatch alarms, dashboards, X-Ray traces, metric checks  |
| `scripts/cost/cost_ops.py`           | Cost       | Cost Explorer analysis, budget tracking, forecasting         |
| `scripts/security/security_ops.py`   | Security   | GuardDuty findings, Security Hub scores, IAM audit           |
| `scripts/capacity/capacity_ops.py`   | Capacity   | Autoscaling analysis, utilization, rightsizing recommendations |
| `scripts/dr/disaster_recovery.py`    | DR         | Failover execution, runbook, drills (service + region scope) |

---

## Shared Utilities

Three shared modules eliminate duplication across all operational scripts.

### `shared/runner.py`

Unified command execution and structured logging. Provides `run_cmd()` (shell execution with timeout and structured result), `log()` (timestamped logging with configurable tags), `timed` (context manager for timing operations), and per-domain convenience loggers (`net_log`, `mon_log`, `cost_log`, `dr_log`, `sec_log`, `cap_log`).

### `shared/aws_client.py`

Centralized boto3 session factory. Provides lazy-initialized, cached clients per service with configurable region, profile, and retries. Falls back to stub mode (returns `None`) when `AETHER_STUB_AWS=1` is set or boto3 is unavailable, allowing scripts to run with illustrative data in demo and CI environments.

### `shared/notifier.py`

Fan-out notification dispatcher supporting Slack (webhooks), PagerDuty (incident creation), and SNS (topic publishing). Includes convenience methods for DR alerts, alarm notifications, cost warnings, and security findings. All channels are optional and configured via environment variables.

---

## Disaster Recovery

| Store          | Strategy                                                              |
|----------------|-----------------------------------------------------------------------|
| Neptune        | Automated continuous backups, PITR within 35-day window               |
| RDS            | Automated daily snapshots, cross-region replication for DR            |
| S3             | Cross-region replication to `us-west-2`, versioning enabled           |
| ElastiCache    | Daily snapshots, multi-AZ automatic failover                          |
| MSK (Kafka)    | Multi-AZ replication, topic-level retention policies                  |
| DynamoDB       | Global tables auto-replicate to DR region                             |
| OpenSearch     | Automated snapshots, cross-cluster replication available              |
| SageMaker      | Model artifacts in S3 (replicated), endpoint rebuild from config      |
| Infrastructure | Terraform state enables full environment rebuild in DR region within 2 hours |

DR drills are executed quarterly. The `scripts/dr/disaster_recovery.py` module supports both service-level and region-level failover scopes.

---

## License

Proprietary. All rights reserved.
