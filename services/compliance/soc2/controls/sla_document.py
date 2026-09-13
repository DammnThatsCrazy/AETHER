"""
A-3.1 — Formal Availability SLA Documentation
Customer-facing Service Level Agreement with 99.9% uptime guarantee,
measurement methodology, exclusions, and service credit schedule.

Satisfies SOC 2 Availability criteria requirement for documented SLA.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ServiceCredit:
    """Credit issued to customer when SLA is breached."""
    monthly_uptime_pct: float
    credit_pct_of_monthly_fee: float
    description: str


@dataclass
class ServiceLevelAgreement:
    """Formal availability SLA document."""
    version: str
    effective_date: str
    uptime_target_pct: float
    measurement_window: str
    measurement_method: str
    exclusions: list
    service_credits: list
    support_tiers: list
    rpo_hours: float
    rto_hours: float


# Credit schedule aligned with 99.9% target
CREDIT_SCHEDULE = [
    ServiceCredit(99.9, 0.0,  "At or above SLA target — no credit"),
    ServiceCredit(99.0, 10.0, "99.0–99.9% — 10% monthly fee credit"),
    ServiceCredit(95.0, 25.0, "95.0–99.0% — 25% monthly fee credit"),
    ServiceCredit(0.0,  50.0, "Below 95.0% — 50% monthly fee credit"),
]

SLA_EXCLUSIONS = [
    "Scheduled maintenance windows (notified 48h in advance)",
    "Force majeure events beyond Aether's reasonable control",
    "Customer-caused outages (misconfigured SDK, invalid API keys)",
    "Third-party provider outages (AWS region-wide events)",
    "Beta or preview features explicitly marked as such",
    "Free tier or trial accounts",
]

SUPPORT_TIERS = [
    {"tier": "Standard",    "response_sla": "Next business day", "channels": ["Email"]},
    {"tier": "Professional","response_sla": "4 business hours",  "channels": ["Email", "Slack"]},
    {"tier": "Enterprise",  "response_sla": "1 hour (24/7)",     "channels": ["Email", "Slack", "Phone", "Dedicated CSM"]},
]

AETHER_SLA = ServiceLevelAgreement(
    version="1.0",
    effective_date="2025-01-01",
    uptime_target_pct=99.9,
    measurement_window="Rolling 30-day calendar month",
    measurement_method=(
        "Uptime = (total minutes − downtime minutes) / total minutes × 100. "
        "Downtime is defined as API error rate >5% sustained for ≥5 minutes as "
        "measured by Aether's synthetic monitoring from at least 3 AWS regions. "
        "Measurement excludes scheduled maintenance windows."
    ),
    exclusions=SLA_EXCLUSIONS,
    service_credits=CREDIT_SCHEDULE,
    support_tiers=SUPPORT_TIERS,
    rpo_hours=1.0,
    rto_hours=4.0,
)


class SLADocumentManager:
    """Manages and presents the formal SLA document."""

    def __init__(self):
        self.sla = AETHER_SLA

    def uptime_target_minutes_per_month(self) -> float:
        """Maximum downtime minutes allowed per month at 99.9% SLA."""
        return (1.0 - self.sla.uptime_target_pct / 100.0) * 30 * 24 * 60

    def calculate_credit(self, actual_uptime_pct: float) -> ServiceCredit:
        for credit in sorted(self.sla.service_credits, key=lambda c: c.monthly_uptime_pct, reverse=True):
            if actual_uptime_pct >= credit.monthly_uptime_pct:
                return credit
        return self.sla.service_credits[-1]

    def generate_evidence(self) -> dict:
        return {
            "control": "A-3.1",
            "artifact": "Service Level Agreement",
            "version": self.sla.version,
            "effective_date": self.sla.effective_date,
            "uptime_target": f"{self.sla.uptime_target_pct}%",
            "max_downtime_minutes_monthly": round(self.uptime_target_minutes_per_month(), 1),
            "rpo_hours": self.sla.rpo_hours,
            "rto_hours": self.sla.rto_hours,
            "credit_tiers": len(self.sla.service_credits),
            "support_tiers": len(self.sla.support_tiers),
            "status": "IMPLEMENTED",
            "evidence_type": "policy_document",
        }

    def print_sla(self) -> None:
        s = self.sla
        allowed = self.uptime_target_minutes_per_month()
        print(f"\n  Service Level Agreement v{s.version} (effective {s.effective_date})")
        print(f"  Uptime target: {s.uptime_target_pct}%  ({allowed:.1f} min/month allowed downtime)")
        print(f"  RPO: {s.rpo_hours}h  |  RTO: {s.rto_hours}h")
        print(f"  Measurement: {s.measurement_window}")
        print("\n  Service Credits:")
        for c in s.service_credits:
            pct = f"{c.credit_pct_of_monthly_fee:.0f}%"
            print(f"    {c.description} → Credit: {pct}")
        print("\n  Support Tiers:")
        for t in s.support_tiers:
            print(f"    {t['tier']:14s}: {t['response_sla']}")
