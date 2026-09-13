"""
Aether AWS Deployment — Central Configuration
Multi-account structure, sizing by environment, DR targets, and all resource specs.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

# ═══════════════════════════════════════════════════════════════════════════
# AWS ACCOUNTS (multi-account strategy)
# ═══════════════════════════════════════════════════════════════════════════

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


# ═══════════════════════════════════════════════════════════════════════════
# NETWORK ARCHITECTURE
# ═══════════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class VPCConfig:
    cidr: str
    azs: int = 3
    public_subnets: int = 3
    private_subnets: int = 3

VPC_CONFIGS = {
    "dev":        VPCConfig(cidr="10.0.0.0/16"),
    "staging":    VPCConfig(cidr="10.1.0.0/16"),
    "production": VPCConfig(cidr="10.2.0.0/16"),
    "data":       VPCConfig(cidr="10.3.0.0/16"),
}

DNS_DOMAINS = {
    "api":       "api.aether.network",
    "dashboard": "dashboard.aether.network",
    "websocket": "ws.aether.network",
    "cdn":       "cdn.aether.network",
}


# ═══════════════════════════════════════════════════════════════════════════
# COMPUTE — Service sizing per environment
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class ServiceSpec:
    cpu: int
    memory: int
    min_count: int
    max_count: int
    target_cpu_pct: int = 60
    spot: bool = False
    port: int = 8000

COMPUTE_SPECS = {
    "production": {
        "ingestion":    ServiceSpec(512,  1024, min_count=2,  max_count=20, target_cpu_pct=60, port=8001),
        "identity":     ServiceSpec(512,  1024, min_count=2,  max_count=10, target_cpu_pct=60, port=8002),
        "analytics":    ServiceSpec(1024, 2048, min_count=2,  max_count=15, target_cpu_pct=70, port=8003),
        "ml-serving":   ServiceSpec(1024, 4096, min_count=2,  max_count=20, target_cpu_pct=50, port=8004),
        "agent":        ServiceSpec(512,  2048, min_count=1,  max_count=10, target_cpu_pct=70, port=8005, spot=True),
        "campaign":     ServiceSpec(256,  512,  min_count=1,  max_count=5,  target_cpu_pct=60, port=8006),
        "consent":      ServiceSpec(256,  512,  min_count=1,  max_count=3,  target_cpu_pct=60, port=8007),
        "notification": ServiceSpec(256,  512,  min_count=1,  max_count=5,  target_cpu_pct=60, port=8008),
        "admin":        ServiceSpec(256,  512,  min_count=1,  max_count=3,  target_cpu_pct=60, port=8009),
    },
    "staging": {
        svc: ServiceSpec(spec.cpu, spec.memory, min_count=1, max_count=max(2, spec.max_count // 4),
                         target_cpu_pct=spec.target_cpu_pct, spot=spec.spot, port=spec.port)
        for svc, spec in {
            "ingestion":    ServiceSpec(256,  512, 1, 5, port=8001),
            "identity":     ServiceSpec(256,  512, 1, 3, port=8002),
            "analytics":    ServiceSpec(512,  1024, 1, 4, port=8003),
            "ml-serving":   ServiceSpec(512,  2048, 1, 5, port=8004),
            "agent":        ServiceSpec(256,  1024, 1, 3, port=8005, spot=True),
            "campaign":     ServiceSpec(256,  512, 1, 2, port=8006),
            "consent":      ServiceSpec(256,  512, 1, 2, port=8007),
            "notification": ServiceSpec(256,  512, 1, 2, port=8008),
            "admin":        ServiceSpec(256,  512, 1, 2, port=8009),
        }.items()
    },
}


# ═══════════════════════════════════════════════════════════════════════════
# DATA STORE DEPLOYMENT
# ═══════════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class DataStoreSpec:
    service: str
    instance_type: str
    config: str
    multi_az: bool = True

DATA_STORES = {
    "production": [
        DataStoreSpec("Neptune (Graph DB)",      "db.r6g.xlarge",       "Multi-AZ, read replicas"),
        DataStoreSpec("RDS PostgreSQL+Timescale", "db.r6g.xlarge",      "Multi-AZ, automated backups"),
        DataStoreSpec("ElastiCache Redis",        "cache.r6g.large",    "Cluster mode, 3 shards × 2 replicas"),
        DataStoreSpec("S3 + Athena (Event Store)", "Intelligent Tiering","Parquet format, partitioned by tenant/date"),
        DataStoreSpec("OpenSearch (Vector Store)", "r6g.large.search",  "3 nodes, k-NN plugin enabled"),
        DataStoreSpec("DynamoDB (Config Store)",   "On-demand",         "Global tables for multi-region"),
        DataStoreSpec("SageMaker Feature Store",   "Online + Offline",  "Online + Offline stores"),
        DataStoreSpec("MSK (Kafka)",               "kafka.m5.large",    "3 brokers, 3 AZs"),
    ],
}


# ═══════════════════════════════════════════════════════════════════════════
# MONITORING STACK
# ═══════════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class MonitoringSpec:
    concern: str
    tool: str
    config: str

MONITORING_STACK = [
    MonitoringSpec("Metrics",         "CloudWatch + Prometheus (on ECS)", "Custom metrics: event throughput, latency percentiles, error rates per service"),
    MonitoringSpec("Logging",         "CloudWatch Logs + OpenSearch",     "Structured JSON logs, 30-day retention, indexed for search"),
    MonitoringSpec("Tracing",         "AWS X-Ray",                        "Distributed tracing, 5% sampling (100% on errors)"),
    MonitoringSpec("Alerting",        "CloudWatch Alarms + PagerDuty",   "Error rate >1%, P99 >500ms, queue depth >10K, disk >80%"),
    MonitoringSpec("Dashboards",      "Grafana (on ECS)",                "Service health, business metrics, SLO tracking, cost dashboards"),
    MonitoringSpec("Cost Monitoring", "Cost Explorer + Budgets",          "Per-service cost allocation tags, monthly budget alerts"),
    MonitoringSpec("Security",        "GuardDuty + Security Hub",        "Threat detection, compliance scoring, vulnerability management"),
]


# ═══════════════════════════════════════════════════════════════════════════
# DISASTER RECOVERY
# ═══════════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class DRConfig:
    rpo_hours: int = 1          # Recovery Point Objective
    rto_hours: int = 4          # Recovery Time Objective
    dr_region: str = "us-west-2"
    rebuild_target_hours: int = 2  # Terraform full rebuild

DR_STRATEGIES = {
    "Neptune":      "Automated continuous backups, point-in-time recovery within 35-day window",
    "RDS":          "Automated daily snapshots, cross-region replication for DR",
    "S3":           "Cross-region replication to DR region, versioning enabled",
    "ElastiCache":  "Daily snapshots, multi-AZ automatic failover",
    "MSK (Kafka)":  "Multi-AZ replication, topic-level retention policies",
    "Infrastructure": "Terraform state enables full environment rebuild in DR region within 2 hours",
}

DR = DRConfig()
