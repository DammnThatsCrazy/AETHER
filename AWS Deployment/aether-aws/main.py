"""
Aether AWS Deployment Architecture — Demo Runner
Demonstrates the full multi-account, multi-AZ deployment with
all operational scripts: network, monitoring, cost, security,
capacity planning, and disaster recovery.

Run in stub mode:  python main.py --stub-aws
Run against live AWS: AETHER_STUB_AWS=0 python main.py --live-aws
"""

from __future__ import annotations

import argparse
import os
import sys

# Ensure imports work from package root
sys.path.insert(0, os.path.dirname(__file__))

from config.aws_config import (
    AWS_ACCOUNTS, AccountType, VPC_CONFIGS, DNS_DOMAINS,
    VPC_ENDPOINTS, COMPUTE_SPECS, DATA_STORES, MONITORING_STACK,
    SECRETS, COMPLIANCE_CONTROLS, BUDGET_CONFIGS,
    DR, DR_STRATEGIES, SERVICE_NAMES, ALL_ENVIRONMENTS,
)
from scripts.network.network_ops import run_full_network_check
from scripts.monitoring.monitoring_ops import run_full_monitoring_check
from scripts.cost.cost_ops import run_full_cost_report
from scripts.security.security_ops import run_full_security_audit
from scripts.capacity.capacity_ops import run_full_capacity_check
from scripts.dr.disaster_recovery import (
    execute_dr_failover, print_dr_runbook, run_dr_drill, FailoverScope,
)


def print_header(title: str) -> None:
    print(f"\n{'=' * 70}")
    print(f"  {title}")
    print(f"{'=' * 70}\n")


# =========================================================================
# ARCHITECTURE OVERVIEW
# =========================================================================

def show_account_structure() -> None:
    print_header("AWS ACCOUNT STRUCTURE (Multi-Account)")
    for acc_type, acc in AWS_ACCOUNTS.items():
        print(f"  {acc.name:22s} ({acc.account_id})  -> {acc.purpose}")
    print(f"\n  Total: {len(AWS_ACCOUNTS)} accounts")


def show_network_architecture() -> None:
    print_header("NETWORK ARCHITECTURE")
    for env, vpc in VPC_CONFIGS.items():
        print(f"  {env:12s} VPC {vpc.cidr} | {vpc.azs} AZs | "
              f"{vpc.public_subnets} public + {vpc.private_subnets} private subnets | "
              f"{vpc.nat_gateways} NAT GW(s)")

    print(f"\n  Public subnets:  ALB, NAT Gateways, bastion hosts")
    print(f"  Private subnets: ECS tasks, RDS, ElastiCache, Neptune, Lambda")
    print(f"  VPC Peering:     production <-> data (ML model access)")

    print(f"\n  DNS (Route 53):")
    for purpose, domain in DNS_DOMAINS.items():
        print(f"    {domain:35s} ({purpose})")

    print(f"\n  VPC Endpoints ({len(VPC_ENDPOINTS)}):")
    gw = sum(1 for ep in VPC_ENDPOINTS if ep.type == "Gateway")
    iface = sum(1 for ep in VPC_ENDPOINTS if ep.type == "Interface")
    print(f"    {gw} Gateway (free) + {iface} Interface (PrivateLink)")
    for ep in VPC_ENDPOINTS:
        print(f"    {ep.service:25s} [{ep.type:9s}]  {ep.reason}")

    print(f"\n  WAF: CloudFront + ALB -- DDoS, rate limiting, bot mitigation")


def show_compute_architecture() -> None:
    print_header("COMPUTE ARCHITECTURE")
    print(f"  {'Service':<15s} {'CPU':>5s} {'Mem':>6s} {'Min':>4s} {'Max':>4s} "
          f"{'CPU%':>5s} {'Spot':>5s} {'Port':>5s} {'Health':>12s}")
    print(f"  {'-'*15} {'-'*5} {'-'*6} {'-'*4} {'-'*4} {'-'*5} {'-'*5} {'-'*5} {'-'*12}")

    for svc, spec in COMPUTE_SPECS["production"].items():
        spot = "yes" if spec.spot else "-"
        print(f"  {svc:<15s} {spec.cpu:>5d} {spec.memory:>5d}M {spec.min_count:>4d} "
              f"{spec.max_count:>4d} {spec.target_cpu_pct:>4d}% {spot:>5s} "
              f"{spec.port:>5d} {spec.health_path}")

    print(f"\n  Platform: ECS Fargate (Agent workers on Fargate Spot)")
    print(f"  Scheduling: EventBridge + Lambda/ECS for ML retraining, data cleanup")
    print(f"  WebSocket: API Gateway WebSocket for real-time streaming")

    print(f"\n  Environment Scaling:")
    for env in ALL_ENVIRONMENTS:
        specs = COMPUTE_SPECS.get(env, {})
        total_min = sum(s.min_count for s in specs.values())
        total_max = sum(s.max_count for s in specs.values())
        print(f"    {env:12s} {len(specs)} services, {total_min}-{total_max} tasks")


def show_data_stores() -> None:
    print_header("DATA STORE DEPLOYMENT")
    print(f"  {'Store':<30s} {'AWS Service':<30s} Configuration")
    print(f"  {'-'*30} {'-'*30} {'-'*40}")
    for spec in DATA_STORES["production"]:
        enc = "E" if spec.encryption_at_rest else "-"
        tls = "T" if spec.encryption_in_transit else "-"
        print(f"  {spec.service:<30s} {spec.instance_type:<30s} "
              f"{spec.config} [{enc}{tls}]")

    print(f"\n  Encryption: [E] = at rest (KMS), [T] = in transit (TLS)")


def show_secrets_management() -> None:
    print_header("SECRETS MANAGEMENT")
    print(f"  {'Secret Name':<38s} {'Service':<14s} {'Rotation':>10s}")
    print(f"  {'-'*38} {'-'*14} {'-'*10}")
    for s in SECRETS:
        print(f"  {s.name:<38s} {s.service:<14s} {s.rotation_days:>7d} days")
    print(f"\n  Total: {len(SECRETS)} secrets managed via AWS Secrets Manager")
    print(f"  Encryption: KMS with automatic key rotation")
    print(f"  Replication: Cross-region to us-west-2 (production)")


def show_monitoring_stack() -> None:
    print_header("MONITORING & OBSERVABILITY")
    for spec in MONITORING_STACK:
        print(f"  {spec.concern:<18s} {spec.tool:<35s} {spec.config}")


def show_compliance() -> None:
    print_header("SECURITY & COMPLIANCE")
    implemented = sum(1 for c in COMPLIANCE_CONTROLS if c.status == "implemented")
    planned = sum(1 for c in COMPLIANCE_CONTROLS if c.status == "planned")

    for ctrl in COMPLIANCE_CONTROLS:
        icon = "\u2713" if ctrl.status == "implemented" else "\u25cb"
        print(f"  {icon} {ctrl.control:<35s} [{ctrl.category:<18s}] {ctrl.aws_service}")

    print(f"\n  {implemented} implemented, {planned} planned | "
          f"{len(COMPLIANCE_CONTROLS)} total controls")


def show_dr_config() -> None:
    print_header("DISASTER RECOVERY")
    print(f"  RPO: {DR.rpo_hours} hour(s)  |  RTO: {DR.rto_hours} hours  |  "
          f"DR Region: {DR.dr_region}")
    print(f"  Rebuild from Terraform: {DR.rebuild_target_hours} hours")
    print(f"  Drill frequency: every {DR.drill_frequency_days} days\n")
    for store, strategy in DR_STRATEGIES.items():
        print(f"  {store:<18s} -> {strategy}")


def show_budgets() -> None:
    print_header("BUDGET CONFIGURATION")
    for b in BUDGET_CONFIGS:
        thresholds = ", ".join(f"{t}%" for t in b.alert_thresholds)
        print(f"  {b.account:22s} ${b.monthly_usd:>8,.0f}/month  alerts at: {thresholds}")


def show_terraform_modules() -> None:
    print_header("TERRAFORM MODULES (17)")
    modules = [
        ("vpc",            "VPC, subnets, NAT GWs, flow logs, peering"),
        ("ecs",            "9 Fargate services, ALB, autoscaling, canary TGs"),
        ("rds",            "Aurora PostgreSQL + TimescaleDB, Multi-AZ, backups"),
        ("neptune",        "Graph DB, Multi-AZ, read replicas, PITR"),
        ("elasticache",    "Redis cluster mode, 3 shards x 2 replicas"),
        ("msk",            "Managed Kafka, 3 brokers, 3 AZs, retention policies"),
        ("opensearch",     "Vector store, k-NN plugin, 3 nodes"),
        ("dynamodb",       "5 tables, on-demand, global tables, PITR"),
        ("s3",             "Data lake, CDN origin, dashboard SPA, ML artifacts, Athena"),
        ("cloudfront",     "SDK CDN + dashboard SPA, OAC, WAF integration"),
        ("api_gateway",    "HTTP API + WebSocket API, custom domains, Route 53"),
        ("sagemaker",      "Multi-model endpoint, autoscaling, feature store"),
        ("monitoring",     "CloudWatch alarms, X-Ray, Grafana, budgets, dashboard"),
        ("waf",            "Rate limiting, bot control, IP reputation, managed rules"),
        ("iam",            "CI/CD roles, cross-account, CloudTrail, GuardDuty"),
        ("secrets",        "Secrets Manager, KMS key rotation, Lambda rotator (NEW)"),
        ("vpc_endpoints",  "12 VPC endpoints: S3, DynamoDB, ECR, logs, KMS... (NEW)"),
    ]
    for name, desc in modules:
        new_badge = " *" if "(NEW)" in desc else ""
        print(f"  {name:<14s} -> {desc}{new_badge}")

    print(f"\n  Environments: 3 compositions (dev, staging, production)")
    print(f"  State: per-environment S3 keys with DynamoDB locking")


# =========================================================================
# MAIN
# =========================================================================

def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Aether AWS deployment demo runner")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--stub-aws",
        action="store_true",
        help="Force stub mode for demo/CI execution without AWS credentials",
    )
    mode.add_argument(
        "--live-aws",
        action="store_true",
        help="Require live AWS execution and fail fast if AETHER_STUB_AWS=1",
    )
    return parser.parse_args(argv)


def configure_stub_mode(args: argparse.Namespace) -> bool:
    if args.stub_aws:
        os.environ["AETHER_STUB_AWS"] = "1"
        return True
    if args.live_aws:
        os.environ["AETHER_STUB_AWS"] = "0"
        return False
    return os.environ.get("AETHER_STUB_AWS", "0") == "1"


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    stub_mode = configure_stub_mode(args)

    print_header("AETHER AWS DEPLOYMENT ARCHITECTURE -- FULL DEMO")
    print(f"  AWS mode: {'stub/demo' if stub_mode else 'live'}")
    if not stub_mode:
        print("  Live AWS mode selected -- ensure credentials and target account access are configured.")
    print()

    # ── Architecture overview ──────────────────────────────────────────
    show_account_structure()
    show_network_architecture()
    show_compute_architecture()
    show_data_stores()
    show_secrets_management()
    show_monitoring_stack()
    show_compliance()
    show_budgets()
    show_dr_config()
    show_terraform_modules()

    # ── Operational scripts ────────────────────────────────────────────
    run_full_network_check("production")
    run_full_monitoring_check("production")
    run_full_cost_report("production")
    run_full_security_audit("production")
    run_full_capacity_check("production")

    # ── DR ─────────────────────────────────────────────────────────────
    print_dr_runbook()
    run_dr_drill(FailoverScope.SERVICE)
    execute_dr_failover(FailoverScope.REGION)

    # ── Final summary ──────────────────────────────────────────────────
    print_header("DEPLOYMENT ARCHITECTURE SUMMARY")
    summary = [
        f"  \u2713 {len(AWS_ACCOUNTS)} AWS Accounts      -- dev, staging, production, data, security",
        f"  \u2713 {len(VPC_CONFIGS)} VPCs              -- /16 CIDR, 3 AZs, public + private subnets",
        f"  \u2713 {len(SERVICE_NAMES)} ECS Services      -- Fargate (agent on Spot), autoscaling, canary TGs",
        f"  \u2713 {len(DATA_STORES.get('production', []))} Data Stores       -- Neptune, RDS, Redis, MSK, OpenSearch, DynamoDB, S3, SageMaker FS",
        f"  \u2713 {len(VPC_ENDPOINTS)} VPC Endpoints     -- S3, DynamoDB (Gateway) + 10 Interface (PrivateLink)",
        f"  \u2713 {len(SECRETS)} Managed Secrets   -- Secrets Manager, KMS rotation, cross-region replication",
        f"  \u2713 2 CDN Distributions -- SDK (cdn.aether.network), Dashboard SPA",
        f"  \u2713 2 API Gateways      -- HTTP (api.aether.network), WebSocket (ws.aether.network)",
        f"  \u2713 WAF                 -- Rate limiting, bot control, DDoS protection",
        f"  \u2713 ML Serving          -- SageMaker multi-model endpoint, autoscaling, feature store",
        f"  \u2713 {len(MONITORING_STACK)} Monitoring Layers -- Metrics, logs, tracing, alerting, dashboards, cost, security",
        f"  \u2713 {len(COMPLIANCE_CONTROLS)} Compliance Controls -- Encryption, IAM, audit, network, backup",
        f"  \u2713 DR                  -- RPO {DR.rpo_hours}h, RTO {DR.rto_hours}h, cross-region replication, Terraform rebuild",
        f"  \u2713 17 Terraform Modules -- Full IaC, 3 environment compositions",
        f"  \u2713 6 Operational Scripts -- Network, monitoring, cost, security, capacity, DR",
    ]
    for line in summary:
        print(line)
    print()


if __name__ == "__main__":
    main()
