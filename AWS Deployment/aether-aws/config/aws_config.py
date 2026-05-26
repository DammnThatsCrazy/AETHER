"""
Aether AWS Deployment — Central Configuration
Multi-account structure, sizing by environment, DR targets, resource specs,
security policies, VPC endpoints, and compliance requirements.

Single source of truth — all scripts and Terraform reference this config.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

# =========================================================================
# AWS ACCOUNTS (multi-account strategy)
# =========================================================================

class AccountType(str, Enum):
    DEV = "dev"
    STAGING = "staging"
    PRODUCTION = "production"
    DATA = "data"
    SECURITY = "security"


@dataclass(frozen=True)
class AWSAccount:
    name: str
    account_id: str
    purpose: str
    region: str = "us-east-1"
    dr_region: str = "us-west-2"


AWS_ACCOUNTS = {
    AccountType.DEV:        AWSAccount("aether-dev",        "111111111111", "Development and testing"),
    AccountType.STAGING:    AWSAccount("aether-staging",    "222222222222", "Pre-production validation (full replica at reduced scale)"),
    AccountType.PRODUCTION: AWSAccount("aether-production", "333333333333", "Live customer traffic — Multi-AZ, auto-scaling, full monitoring"),
    AccountType.DATA:       AWSAccount("aether-data",       "444444444444", "Data lake, ML training, SageMaker jobs, Athena queries"),
    AccountType.SECURITY:   AWSAccount("aether-security",   "555555555555", "CloudTrail aggregation, GuardDuty, Security Hub"),
}


# =========================================================================
# NETWORK ARCHITECTURE
# =========================================================================

@dataclass(frozen=True)
class VPCConfig:
    cidr: str
    azs: int = 3
    public_subnets: int = 3
    private_subnets: int = 3
    nat_gateways: int = 3          # HA: one per AZ in production
    enable_flow_logs: bool = True
    flow_log_retention_days: int = 30


VPC_CONFIGS = {
    "dev":        VPCConfig(cidr="10.0.0.0/16", nat_gateways=1, flow_log_retention_days=7),
    "staging":    VPCConfig(cidr="10.1.0.0/16", nat_gateways=1, flow_log_retention_days=14),
    "production": VPCConfig(cidr="10.2.0.0/16", nat_gateways=3, flow_log_retention_days=30),
    "data":       VPCConfig(cidr="10.3.0.0/16", nat_gateways=1, flow_log_retention_days=30),
}

DNS_DOMAINS = {
    "api":       "api.aether.network",
    "dashboard": "dashboard.aether.network",
    "websocket": "ws.aether.network",
    "cdn":       "cdn.aether.network",
}


# ── VPC Endpoints (PrivateLink) ────────────────────────────────────────
# Services that should be accessed via VPC endpoints to avoid NAT costs
# and improve security (traffic stays on AWS backbone).

@dataclass(frozen=True)
class VPCEndpointSpec:
    service: str
    type: str            # "Gateway" or "Interface"
    reason: str

VPC_ENDPOINTS = [
    VPCEndpointSpec("s3",                   "Gateway",   "Data lake access without NAT — saves ~$100/mo transfer costs"),
    VPCEndpointSpec("dynamodb",             "Gateway",   "Config store access without NAT"),
    VPCEndpointSpec("ecr.api",              "Interface", "ECR image pulls stay on AWS backbone"),
    VPCEndpointSpec("ecr.dkr",              "Interface", "ECR Docker registry access"),
    VPCEndpointSpec("logs",                 "Interface", "CloudWatch Logs without NAT"),
    VPCEndpointSpec("monitoring",           "Interface", "CloudWatch Metrics without NAT"),
    VPCEndpointSpec("sagemaker.runtime",    "Interface", "ML inference calls stay internal"),
    VPCEndpointSpec("secretsmanager",       "Interface", "Secrets retrieval without NAT"),
    VPCEndpointSpec("sqs",                  "Interface", "Queue access without NAT"),
    VPCEndpointSpec("sns",                  "Interface", "Notification publishing without NAT"),
    VPCEndpointSpec("kms",                  "Interface", "Encryption operations without NAT"),
    VPCEndpointSpec("sts",                  "Interface", "IAM token exchange without NAT"),
]


# =========================================================================
# COMPUTE — Service sizing per environment
# =========================================================================

@dataclass
class ServiceSpec:
    cpu: int
    memory: int
    min_count: int
    max_count: int
    target_cpu_pct: int = 60
    spot: bool = False
    port: int = 8000
    health_path: str = "/v1/health"
    grace_period_sec: int = 60

    @property
    def memory_mb(self) -> str:
        return f"{self.memory}M"


# ── Production specs ───────────────────────────────────────────────────
# E2: Single Fargate Spot service — all FastAPI routers in-process.
#   aether-app  — backend + ML predict routes (ML_SERVING_INLINE=true)
# aether-ml is kept in Terraform at desired_count=0 for rollback;
# flip ml_serving_inline=false in the ECS module to restore it instantly.

_PRODUCTION_SPECS = {
    "aether-app": ServiceSpec(512, 1024, min_count=1, max_count=6, target_cpu_pct=60, port=8000, spot=True),
    # desired_count=0 in Terraform when ml_serving_inline=true (E2). Kept here for rollback reference.
    "aether-ml":  ServiceSpec(512, 1024, min_count=0, max_count=6, target_cpu_pct=60, port=8080, spot=True),
}


def _derive_staging(prod: dict[str, ServiceSpec]) -> dict[str, ServiceSpec]:
    """Derive staging specs: same ports, half scale, min_count=1."""
    return {
        svc: ServiceSpec(
            cpu=max(256, spec.cpu // 2),
            memory=max(512, spec.memory // 2),
            min_count=1,
            max_count=max(2, spec.max_count // 4),
            target_cpu_pct=spec.target_cpu_pct,
            spot=spec.spot,
            port=spec.port,
            health_path=spec.health_path,
        )
        for svc, spec in prod.items()
    }


def _derive_dev(prod: dict[str, ServiceSpec]) -> dict[str, ServiceSpec]:
    """Derive dev specs: minimal resources, single instance."""
    return {
        svc: ServiceSpec(
            cpu=256, memory=512,
            min_count=1, max_count=1,
            target_cpu_pct=80,
            spot=False,
            port=spec.port,
            health_path=spec.health_path,
        )
        for svc, spec in prod.items()
    }


COMPUTE_SPECS = {
    "production": _PRODUCTION_SPECS,
    "staging":    _derive_staging(_PRODUCTION_SPECS),
    "dev":        _derive_dev(_PRODUCTION_SPECS),
}

SERVICE_NAMES = list(_PRODUCTION_SPECS.keys())


# =========================================================================
# DATA STORE DEPLOYMENT
# =========================================================================

@dataclass(frozen=True)
class DataStoreSpec:
    service: str
    instance_type: str
    config: str
    multi_az: bool = True
    encryption_at_rest: bool = True
    encryption_in_transit: bool = True
    backup_retention_days: int = 35


# E1/E3: Active stack after cost-reduction epics.
# Decommission markers show what was replaced and when it is safe to remove.
DATA_STORES = {
    "production": [
        # ── Active (E3) ──────────────────────────────────────────────────
        DataStoreSpec("Aurora Serverless v2",      "0.5–4 ACU",         "Active primary DB (E3); min 0.5 ACU warm, max 4 ACU, PITR 7-day",
                      multi_az=False, backup_retention_days=7),
        DataStoreSpec("Neptune (Graph DB)",        "db.r6g.large",      "Identity graph; Multi-AZ, PITR 35-day"),
        DataStoreSpec("DynamoDB On-Demand",        "On-demand",         "Cache + quota counters + idempotency keys (E1); PITR enabled"),
        DataStoreSpec("SQS Standard + SNS",        "Managed",           "Event streaming (E1, replaces MSK); per-message fanout via SNS",
                      multi_az=False, backup_retention_days=0),
        DataStoreSpec("S3 + Athena (Event Store)", "Intelligent Tiering","Parquet, partitioned by tenant/date, versioned; logs via Vector"),
        DataStoreSpec("SageMaker Serverless",      "1 GB / 5 concurrent","Inference for M4 (identity), M5 (journey), M8-AE (anomaly)",
                      multi_az=False, backup_retention_days=0),
        # ── Decommission after 72 h clean prod metrics ───────────────────
        DataStoreSpec("RDS PostgreSQL (rollback)", "db.t3.medium",      "Kept for rollback; decommission after Aurora v2 validation"),
        DataStoreSpec("ElastiCache Redis (rollback)", "cache.t3.micro", "Kept for rollback; decommission after DynamoDB cache validation"),
        DataStoreSpec("MSK Kafka (rollback)",      "kafka.m5.large",    "Kept for rollback; decommission after SQS migration validation"),
    ],
}


# =========================================================================
# SECRETS MANAGEMENT
# =========================================================================

@dataclass(frozen=True)
class SecretSpec:
    name: str
    service: str
    rotation_days: int = 30
    description: str = ""

SECRETS = [
    # Active after E1/E3
    SecretSpec("aether/aurora/master",       "Aurora",      30,  "Aurora Serverless v2 master credentials (managed by Secrets Manager)"),
    SecretSpec("aether/neptune/master",      "Neptune",     30,  "Neptune IAM auth token"),
    SecretSpec("aether/api/jwt-secret",      "API",         90,  "JWT signing secret for auth service"),
    SecretSpec("aether/api/encryption-key",  "API",         180, "AES-256 encryption key for PII"),
    SecretSpec("aether/pagerduty/api-key",   "Monitoring",  365, "PagerDuty integration key"),
    SecretSpec("aether/slack/webhook-url",   "Monitoring",  365, "Slack webhook for alerts"),
    SecretSpec("aether/sagemaker/api-key",   "ML",          90,  "SageMaker Serverless endpoint auth"),
    # Rollback — decommission after 72 h clean prod metrics
    SecretSpec("aether/rds/master",          "RDS",         30,  "RDS rollback credentials (decommission after Aurora validation)"),
    SecretSpec("aether/redis/auth",          "ElastiCache", 90,  "Redis AUTH token (decommission after DynamoDB cache validation)"),
]


# =========================================================================
# MONITORING STACK
# =========================================================================

@dataclass(frozen=True)
class MonitoringSpec:
    concern: str
    tool: str
    config: str


MONITORING_STACK = [
    # E6: consolidated to CloudWatch-native stack; OpenSearch and Grafana removed.
    MonitoringSpec("Metrics",         "CloudWatch",                       "Custom metrics: event throughput, latency percentiles, error rates, Aurora ACU, ML PSI drift"),
    MonitoringSpec("Logging",         "CloudWatch Logs (WARN+) + S3/Athena", "WARN+ in CW (3-day retention); INFO/DEBUG via Vector → S3 Parquet → Athena ad-hoc"),
    MonitoringSpec("Tracing",         "AWS X-Ray",                        "Distributed tracing, 5% sampling (100% on errors)"),
    MonitoringSpec("Alerting",        "CloudWatch Alarms + SNS",         "3 alarms: 5xx spike, Aurora max-ACU sustained, ML PSI drift >0.2"),
    MonitoringSpec("Dashboards",      "CloudWatch Dashboard (aether-prod)", "Single dashboard: request rate, p99 latency, model prediction latency, Aurora ACU, SQS lag"),
    MonitoringSpec("Cost Monitoring", "Cost Explorer + Budgets",          "Per-service cost allocation tags, $750/mo budget alert at 80%/100%"),
    MonitoringSpec("Security",        "GuardDuty + Security Hub",        "Threat detection, compliance scoring, vulnerability management"),
    MonitoringSpec("ML Drift",        "EventBridge nightly Lambda",       "PSI scores for all 11 models published to Aether/MLDrift namespace"),
]


# =========================================================================
# SECURITY & COMPLIANCE
# =========================================================================

@dataclass(frozen=True)
class ComplianceRequirement:
    control: str
    category: str
    aws_service: str
    status: str  # "implemented", "planned"


COMPLIANCE_CONTROLS = [
    ComplianceRequirement("Encryption at rest",          "Data Protection",    "KMS + service-native encryption",  "implemented"),
    ComplianceRequirement("Encryption in transit",       "Data Protection",    "TLS 1.2+ enforced",               "implemented"),
    ComplianceRequirement("IAM least privilege",         "Access Control",     "IAM policies + OIDC federation",   "implemented"),
    ComplianceRequirement("Audit logging",               "Monitoring",         "CloudTrail multi-region",          "implemented"),
    ComplianceRequirement("Threat detection",            "Security",           "GuardDuty + Security Hub",         "implemented"),
    ComplianceRequirement("Secrets rotation",            "Data Protection",    "Secrets Manager auto-rotation",    "implemented"),
    ComplianceRequirement("Network segmentation",        "Network Security",   "VPC + Security Groups + NACLs",    "implemented"),
    ComplianceRequirement("DDoS protection",             "Network Security",   "WAF + Shield Standard",            "implemented"),
    ComplianceRequirement("Backup & recovery",           "Resilience",         "Automated backups + cross-region", "implemented"),
    ComplianceRequirement("Container image scanning",    "Security",           "ECR image scanning on push",       "implemented"),
    ComplianceRequirement("VPC endpoint enforcement",    "Network Security",   "PrivateLink for AWS services",     "implemented"),
    ComplianceRequirement("GDPR data residency",         "Compliance",         "us-east-1 primary, us-west-2 DR",  "planned"),
]


# =========================================================================
# DISASTER RECOVERY
# =========================================================================

@dataclass(frozen=True)
class DRConfig:
    rpo_hours: int = 1
    rto_hours: int = 4
    dr_region: str = "us-west-2"
    rebuild_target_hours: int = 2
    drill_frequency_days: int = 90    # Quarterly DR drills


DR_STRATEGIES = {
    # E3: Aurora Serverless v2 is the active DB; weekly snapshot to S3 for DR.
    "Aurora Serverless v2": "Continuous storage replication within region; weekly snapshot to S3 for cross-region DR",
    "Neptune":              "Automated continuous backups, point-in-time recovery within 35-day window",
    "DynamoDB":             "On-Demand tables with PITR; data replication is handled by Aurora for relational data",
    "SQS":                  "Managed service; DR is queue recreation from Terraform (seconds); messages retained 4 days",
    "S3":                   "Versioning enabled on all buckets; event archive and model artifacts cross-region replicated",
    "SageMaker Serverless": "Model artifacts in S3 (replicated); endpoint rebuild from Terraform in ~5 min",
    "Infrastructure":       "Terraform split into aether-data + aether-compute stacks; compute plane rebuilds in ~3.5 min",
    # Rollback entries — remove after decommission
    "RDS (rollback)":       "Automated daily snapshots; cross-region replication for DR",
    "ElastiCache (rollback)": "Daily snapshots; remove after DynamoDB cache validation",
    "MSK (rollback)":       "Multi-AZ replication; remove after SQS migration validation",
}

DR = DRConfig()


# =========================================================================
# COST MANAGEMENT
# =========================================================================

@dataclass(frozen=True)
class BudgetConfig:
    account: str
    monthly_usd: float
    alert_thresholds: list[int] = field(default_factory=lambda: [50, 80, 100])


# E1–E7 target: total opex ≤ $750/mo across all environments.
# Prod ≈$450, staging ≈$150, dev ≈$30, data ≈$80, security ≈$40.
BUDGET_CONFIGS = [
    BudgetConfig("aether-dev",        100,   [80, 100]),
    BudgetConfig("aether-staging",    200,   [80, 100]),
    BudgetConfig("aether-production", 500,   [50, 80, 100]),
    BudgetConfig("aether-data",       100,   [80, 100]),
    BudgetConfig("aether-security",   50,    [80, 100]),
]


# =========================================================================
# CONVENIENCE — Flat lists of all service names
# =========================================================================

ALL_ENVIRONMENTS = ["dev", "staging", "production"]

ALL_DATA_STORE_NAMES = [ds.service for ds in DATA_STORES.get("production", [])]
