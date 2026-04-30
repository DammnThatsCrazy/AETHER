"""
Aether AWS Deployment Architecture — Demo Runner
Demonstrates the full multi-account, multi-AZ deployment.

Run:  python main.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from config.aws_config import (
    AWS_ACCOUNTS,
    COMPUTE_SPECS,
    DATA_STORES,
    DNS_DOMAINS,
    DR,
    DR_STRATEGIES,
    MONITORING_STACK,
    VPC_CONFIGS,
)
from scripts.cost.cost_ops import run_full_cost_report
from scripts.dr.disaster_recovery import FailoverScope, execute_dr_failover, print_dr_runbook
from scripts.monitoring.monitoring_ops import run_full_monitoring_check
from scripts.network.network_ops import run_full_network_check


def print_header(title: str):
    print(f"\n{'═' * 70}")
    print(f"  {title}")
    print(f"{'═' * 70}\n")


def show_account_structure():
    print_header("AWS ACCOUNT STRUCTURE (Multi-Account)")
    for acc_type, acc in AWS_ACCOUNTS.items():
        print(f"  {acc.name:22s} ({acc.account_id})  → {acc.purpose}")
    print(f"\n  Total: {len(AWS_ACCOUNTS)} accounts")


def show_network_architecture():
    print_header("NETWORK ARCHITECTURE")
    for env, vpc in VPC_CONFIGS.items():
        nat = 3 if env == "production" else 1
        print(f"  {env:12s} VPC {vpc.cidr} | {vpc.azs} AZs | {vpc.public_subnets} public + {vpc.private_subnets} private subnets | {nat} NAT GW(s)")

    print("\n  Public subnets:  ALB, NAT Gateways, bastion hosts")
    print("  Private subnets: ECS tasks, RDS, ElastiCache, Neptune, Lambda")
    print("  VPC Peering:     production ↔ data (ML model access)")

    print("\n  DNS (Route 53):")
    for purpose, domain in DNS_DOMAINS.items():
        print(f"    {domain:35s} ({purpose})")

    print("\n  WAF: CloudFront + ALB — DDoS, rate limiting, bot mitigation")


def show_compute_architecture():
    print_header("COMPUTE ARCHITECTURE")
    print(f"  {'Service':<15s} {'CPU':>5s} {'Mem':>6s} {'Min':>4s} {'Max':>4s} {'CPU%':>5s} {'Spot':>5s} {'Port':>5s}")
    print(f"  {'─'*15} {'─'*5} {'─'*6} {'─'*4} {'─'*4} {'─'*5} {'─'*5} {'─'*5}")

    for svc, spec in COMPUTE_SPECS["production"].items():
        spot = "yes" if spec.spot else "—"
        print(f"  {svc:<15s} {spec.cpu:>5d} {spec.memory:>5d}M {spec.min_count:>4d} {spec.max_count:>4d} {spec.target_cpu_pct:>4d}% {spot:>5s} {spec.port:>5d}")

    print("\n  Platform: ECS Fargate (Agent workers on Fargate Spot)")
    print("  Scheduling: EventBridge + Lambda/ECS for ML retraining, data cleanup")
    print("  WebSocket: API Gateway WebSocket for real-time streaming")


def show_data_stores():
    print_header("DATA STORE DEPLOYMENT")
    print(f"  {'Store':<30s} {'AWS Service':<30s} Configuration")
    print(f"  {'─'*30} {'─'*30} {'─'*40}")
    for spec in DATA_STORES["production"]:
        print(f"  {spec.service:<30s} {spec.instance_type:<30s} {spec.config}")


def show_monitoring_stack():
    print_header("MONITORING & OBSERVABILITY")
    for spec in MONITORING_STACK:
        print(f"  {spec.concern:<18s} {spec.tool:<35s} {spec.config}")


def show_dr_config():
    print_header("DISASTER RECOVERY")
    print(f"  RPO: {DR.rpo_hours} hour(s)  |  RTO: {DR.rto_hours} hours  |  DR Region: {DR.dr_region}")
    print(f"  Rebuild from Terraform: {DR.rebuild_target_hours} hours\n")
    for store, strategy in DR_STRATEGIES.items():
        print(f"  {store:<18s} → {strategy}")


def show_terraform_modules():
    print_header("TERRAFORM MODULES (15)")
    modules = [
        ("vpc",         "VPC, subnets, NAT GWs, flow logs, peering"),
        ("ecs",         "9 Fargate services, ALB, autoscaling, canary TGs"),
        ("rds",         "Aurora PostgreSQL + TimescaleDB, Multi-AZ, backups"),
        ("neptune",     "Graph DB, Multi-AZ, read replicas, PITR"),
        ("elasticache", "Redis cluster mode, 3 shards × 2 replicas"),
        ("msk",         "Managed Kafka, 3 brokers, 3 AZs, retention policies"),
        ("opensearch",  "Vector store, k-NN plugin, 3 nodes"),
        ("dynamodb",    "5 tables, on-demand, global tables, PITR"),
        ("s3",          "Data lake, CDN origin, dashboard SPA, ML artifacts, Athena"),
        ("cloudfront",  "SDK CDN + dashboard SPA, OAC, WAF integration"),
        ("api_gateway", "HTTP API + WebSocket API, custom domains, Route 53"),
        ("sagemaker",   "Multi-model endpoint, autoscaling, feature store"),
        ("monitoring",  "CloudWatch alarms, X-Ray, Grafana, budgets, dashboard"),
        ("waf",         "Rate limiting, bot control, IP reputation, managed rules"),
        ("iam",         "CI/CD roles, cross-account, CloudTrail, GuardDuty"),
    ]
    for name, desc in modules:
        print(f"  {name:<14s} → {desc}")


def main():
    print_header("Aether AWS DEPLOYMENT ARCHITECTURE — FULL DEMO")

    # Architecture overview
    show_account_structure()
    show_network_architecture()
    show_compute_architecture()
    show_data_stores()
    show_monitoring_stack()
    show_dr_config()
    show_terraform_modules()

    # Operational scripts
    run_full_network_check("production")
    run_full_monitoring_check("production")
    run_full_cost_report("production")

    # DR simulation
    print_dr_runbook()
    execute_dr_failover(FailoverScope.REGION)

    # Final summary
    print_header("DEPLOYMENT ARCHITECTURE SUMMARY")
    print("  ✓ 5 AWS Accounts      — dev, staging, production, data, security")
    print("  ✓ 4 VPCs              — /16 CIDR, 3 AZs, public + private subnets")
    print("  ✓ 9 ECS Services      — Fargate (agent on Spot), autoscaling, canary TGs")
    print("  ✓ 8 Data Stores       — Neptune, RDS, Redis, MSK, OpenSearch, DynamoDB, S3, SageMaker FS")
    print("  ✓ 2 CDN Distributions — SDK (cdn.aether.network), Dashboard SPA")
    print("  ✓ 2 API Gateways      — HTTP (api.aether.network), WebSocket (ws.aether.network)")
    print("  ✓ WAF                 — Rate limiting, bot control, DDoS protection")
    print("  ✓ ML Serving          — SageMaker multi-model endpoint, autoscaling, feature store")
    print("  ✓ 7 Monitoring Layers — Metrics, logs, tracing, alerting, dashboards, cost, security")
    print("  ✓ DR                  — RPO 1h, RTO 4h, cross-region replication, Terraform rebuild")
    print("  ✓ 15 Terraform Modules — Full IaC, 3 environment compositions")
    print("  ✓ Operational Scripts — Network, monitoring, cost, disaster recovery")
    print()


if __name__ == "__main__":
    main()
