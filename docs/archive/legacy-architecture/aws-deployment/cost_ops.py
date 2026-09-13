"""
Aether Cost Monitoring — Operational Scripts
Per-service cost allocation, budget alerts, Spot savings, optimization.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def _log(msg: str):
    print(f"  [COST] {msg}")


@dataclass
class ServiceCost:
    service: str
    monthly_usd: float
    category: str  # compute, storage, network, ml

@dataclass
class BudgetStatus:
    account: str
    budget_usd: float
    actual_usd: float
    forecast_usd: float

    @property
    def utilization_pct(self) -> float:
        return (self.actual_usd / self.budget_usd) * 100 if self.budget_usd else 0

    @property
    def over_budget(self) -> bool:
        return self.forecast_usd > self.budget_usd


def estimate_service_costs(environment: str = "production") -> list[ServiceCost]:
    """Estimate monthly costs per service (illustrative figures)."""
    _log(f"Cost breakdown for {environment}:")

    costs = [
        # Compute (ECS Fargate)
        ServiceCost("ECS — ingestion (2-20 tasks)",     450,  "compute"),
        ServiceCost("ECS — identity (2-10 tasks)",      280,  "compute"),
        ServiceCost("ECS — analytics (2-15 tasks)",     620,  "compute"),
        ServiceCost("ECS — ml-serving (2-20 tasks)",    890,  "compute"),
        ServiceCost("ECS — agent (1-10 tasks, Spot)",   180,  "compute"),
        ServiceCost("ECS — campaign (1-5 tasks)",       120,  "compute"),
        ServiceCost("ECS — consent (1-3 tasks)",        80,   "compute"),
        ServiceCost("ECS — notification (1-5 tasks)",   120,  "compute"),
        ServiceCost("ECS — admin (1-3 tasks)",          80,   "compute"),

        # Data stores
        ServiceCost("RDS Aurora PostgreSQL (Multi-AZ)",   1200, "storage"),
        ServiceCost("Neptune db.r6g.xlarge (Multi-AZ)",   950,  "storage"),
        ServiceCost("ElastiCache Redis (3×2 cluster)",    780,  "storage"),
        ServiceCost("MSK Kafka (3 brokers)",              650,  "storage"),
        ServiceCost("OpenSearch (3 r6g.large nodes)",     520,  "storage"),
        ServiceCost("DynamoDB (on-demand)",               200,  "storage"),
        ServiceCost("S3 (data lake + CDN + artifacts)",   350,  "storage"),

        # ML
        ServiceCost("SageMaker Endpoints (g4dn.xlarge)",  1400, "ml"),
        ServiceCost("SageMaker Feature Store",            180,  "ml"),

        # Network
        ServiceCost("CloudFront CDN",                     250,  "network"),
        ServiceCost("NAT Gateways (3)",                   300,  "network"),
        ServiceCost("ALB",                                50,   "network"),
        ServiceCost("API Gateway",                        120,  "network"),
        ServiceCost("Data transfer",                      400,  "network"),

        # Monitoring
        ServiceCost("CloudWatch (metrics + logs)",        280,  "monitoring"),
        ServiceCost("X-Ray tracing",                      80,   "monitoring"),
        ServiceCost("Grafana (ECS)",                      60,   "monitoring"),
    ]

    by_category: dict[str, float] = {}
    for c in costs:
        by_category[c.category] = by_category.get(c.category, 0) + c.monthly_usd

    for c in costs:
        _log(f"  ${c.monthly_usd:>7,.0f}  {c.service}")

    _log("\n  Category Totals:")
    total = 0
    for cat, amount in sorted(by_category.items()):
        _log(f"    {cat:12s} ${amount:>8,.0f}")
        total += amount
    _log(f"    {'TOTAL':12s} ${total:>8,.0f}/month")

    return costs


def check_budget_status() -> list[BudgetStatus]:
    """Check budget status across all accounts."""
    _log("Budget status by account:")

    budgets = [
        BudgetStatus("aether-dev",        2000,  1450,  1680),
        BudgetStatus("aether-staging",    3000,  2100,  2400),
        BudgetStatus("aether-production", 15000, 10200, 13800),
        BudgetStatus("aether-data",       5000,  3200,  3800),
        BudgetStatus("aether-security",   500,   320,   380),
    ]

    for b in budgets:
        icon = "⚠" if b.over_budget else "✓"
        _log(f"  {icon} {b.account:22s} ${b.actual_usd:>8,.0f} / ${b.budget_usd:>8,.0f}  ({b.utilization_pct:.0f}%)  forecast: ${b.forecast_usd:>8,.0f}")

    return budgets


def spot_savings_report():
    """Show Fargate Spot savings for agent workers."""
    _log("Fargate Spot Savings:")
    _log("  Agent workers configured for FARGATE_SPOT")
    _log("  On-demand equivalent: $450/month")
    _log("  Spot actual:          $180/month")
    _log("  Savings:              $270/month (60%)")


def optimization_recommendations():
    """Generate cost optimization recommendations."""
    _log("Optimization Recommendations:")
    recs = [
        "S3 Intelligent Tiering active — auto-transitions cold data to cheaper tiers",
        "DynamoDB on-demand — consider reserved capacity if usage stabilizes",
        "RDS Reserved Instances — 1-year RI would save ~30% ($360/month)",
        "ElastiCache Reserved Nodes — 1-year RI saves ~25%",
        "Consolidate dev + staging NAT Gateways to single NAT for cost reduction",
        "Review OpenSearch instance sizing — utilization at 45%, consider downsizing",
        "Consider Graviton (ARM) instances for ECS — 20% cost savings",
    ]
    for i, rec in enumerate(recs, 1):
        _log(f"  {i}. {rec}")


def run_full_cost_report(environment: str = "production"):
    """Full cost report."""
    print(f"\n{'═' * 60}")
    print(f"  COST REPORT — {environment}")
    print(f"{'═' * 60}\n")

    estimate_service_costs(environment)
    print()
    check_budget_status()
    print()
    spot_savings_report()
    print()
    optimization_recommendations()

    print(f"\n{'═' * 60}")
    print("  Cost report complete ✓")
    print(f"{'═' * 60}\n")
