"""
Aether SOC 2 — Gap Analysis & Remediation Planning
Identifies all gaps between current implementation and certification requirements.
Generates prioritized remediation plan with owners, effort, and timelines.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum

from soc2.trust_criteria.trust_criteria_engine import (
    ControlStatus,
    TrustCriteriaEngine,
)


class Priority(str, Enum):
    CRITICAL = "P0"
    HIGH = "P1"
    MEDIUM = "P2"
    LOW = "P3"


class EffortLevel(str, Enum):
    SMALL = "small"
    MEDIUM = "medium"
    LARGE = "large"


@dataclass
class GapItem:
    """A single certification gap with remediation plan."""
    control_id: str
    criteria: str
    control_name: str
    gap_description: str
    priority: Priority
    effort: EffortLevel
    owner: str
    remediation_steps: list = field(default_factory=list)
    estimated_weeks: int = 0
    dependencies: list = field(default_factory=list)
    evidence_needed: list = field(default_factory=list)


# ═══════════════════════════════════════════════════════════════════════════
# GAP ANALYZER
# ═══════════════════════════════════════════════════════════════════════════

class GapAnalyzer:
    """Analyzes SOC 2 gaps and generates remediation plans."""

    def __init__(self, engine: TrustCriteriaEngine):
        self.engine = engine
        self._gaps: list = []

    def analyze(self) -> list:
        """
        Analyze remaining gaps and generate remediation items.

        After compliance remediation (soc2/controls/ modules), 9 previously
        NOT_IMPLEMENTED controls are now IMPLEMENTED or PARTIALLY_IMPLEMENTED.
        Only 2 controls remain partial (CC-3.2, A-3.2) — both require real-world
        execution (external pen test, conducted tabletop exercises) to close fully.
        Overall readiness: 97.1% (32 implemented + 2 partial / 34 total).
        """
        self._gaps = []

        gap_remediations = {
            "CC-3.1": GapItem(
                "CC-3.1", "Security", "Security Policy Documentation",
                "No formal written security policy document",
                Priority.CRITICAL, EffortLevel.MEDIUM, "Security Team",
                [
                    "Draft information security policy covering all AICPA trust criteria",
                    "Include sections: scope, roles, access management, incident response, change management",
                    "Include acceptable use policy and data handling procedures",
                    "Review with legal and executive leadership",
                    "Publish to internal wiki and obtain signed acknowledgments from all staff",
                    "Schedule annual review cycle",
                ],
                estimated_weeks=3,
                evidence_needed=["Signed security policy document", "Staff acknowledgment records"],
            ),
            "CC-3.2": GapItem(
                "CC-3.2", "Security", "Penetration Testing",
                "No penetration testing by qualified third party",
                Priority.CRITICAL, EffortLevel.MEDIUM, "Security Team",
                [
                    "Engage qualified third-party pen-test vendor (e.g., NCC Group, Bishop Fox)",
                    "Define scope: external API, internal services, AWS infrastructure",
                    "Execute test on staging environment first, then production",
                    "Remediate all critical and high findings",
                    "Obtain formal attestation report",
                    "Schedule annual pen-test cadence",
                ],
                estimated_weeks=4,
                evidence_needed=["Pen-test report", "Remediation tracker", "Vendor attestation"],
            ),
            "CC-5.1": GapItem(
                "CC-5.1", "Security", "Incident Response Plan",
                "Code-level implementation exists but formal plan document needed",
                Priority.HIGH, EffortLevel.SMALL, "Security Team",
                [
                    "Document formal incident response plan based on existing breach_handler.py",
                    "Define roles: incident commander, communications lead, technical lead",
                    "Create escalation matrix with contact information",
                    "Define severity classification criteria",
                    "Include communication templates for DPA and data subjects",
                    "Test plan with tabletop exercise",
                ],
                estimated_weeks=2,
                evidence_needed=["Incident response plan document", "Escalation matrix", "Tabletop exercise report"],
                dependencies=["CC-3.1"],
            ),
            "A-3.1": GapItem(
                "A-3.1", "Availability", "Formal SLA Documentation",
                "99.9% availability target exists but no formal SLA document",
                Priority.HIGH, EffortLevel.SMALL, "Product/Legal",
                [
                    "Draft customer-facing SLA with 99.9% uptime guarantee",
                    "Define measurement methodology (excluding planned maintenance)",
                    "Define service credits for SLA violations",
                    "Review with legal for contractual implications",
                    "Publish as part of terms of service",
                ],
                estimated_weeks=2,
                evidence_needed=["Published SLA document", "SLA measurement dashboard"],
            ),
            "A-3.2": GapItem(
                "A-3.2", "Availability", "Tabletop Exercises",
                "DR code exists but tabletop exercises not conducted",
                Priority.HIGH, EffortLevel.SMALL, "Engineering/Security",
                [
                    "Schedule quarterly DR tabletop exercises",
                    "Scenario 1: Single service failure with cascading impact",
                    "Scenario 2: AZ failure requiring cross-AZ failover",
                    "Scenario 3: Full region failure requiring DR region activation",
                    "Document findings and action items from each exercise",
                    "Update DR procedures based on lessons learned",
                ],
                estimated_weeks=1,
                evidence_needed=["Tabletop exercise reports", "Action item tracker", "Updated DR procedures"],
                dependencies=["A-3.1"],
            ),
            "PI-2.1": GapItem(
                "PI-2.1", "Processing Integrity", "Controls Documentation",
                "Processing integrity controls exist in code but not formally documented",
                Priority.MEDIUM, EffortLevel.SMALL, "Engineering",
                [
                    "Document all input validation schemas and rules",
                    "Document idempotency mechanisms per service",
                    "Document event sourcing architecture and guarantees",
                    "Document data quality scoring methodology",
                    "Create control testing procedures",
                ],
                estimated_weeks=2,
                evidence_needed=["Processing integrity controls document", "Control test results"],
            ),
            "C-1.3": GapItem(
                "C-1.3", "Confidentiality", "DPA Template",
                "DPA template drafted but not finalized",
                Priority.HIGH, EffortLevel.SMALL, "Legal",
                [
                    "Finalize DPA template with legal counsel",
                    "Ensure GDPR Article 28 compliance (processor obligations)",
                    "Include standard contractual clauses for international transfers",
                    "Include sub-processor notification procedures",
                    "Publish template for customer review and execution",
                ],
                estimated_weeks=2,
                evidence_needed=["Finalized DPA template", "Legal review sign-off"],
            ),
            "C-1.4": GapItem(
                "C-1.4", "Confidentiality", "Sub-Processor List",
                "Only AWS listed; need complete sub-processor register",
                Priority.MEDIUM, EffortLevel.SMALL, "Legal/Security",
                [
                    "Audit all third-party services processing customer data",
                    "Document each sub-processor: name, purpose, data categories, location",
                    "Assess sub-processor security posture",
                    "Create sub-processor change notification process",
                    "Publish list and update procedure",
                ],
                estimated_weeks=1,
                evidence_needed=["Sub-processor register", "Assessment records", "Change notification process"],
            ),
            "C-2.1": GapItem(
                "C-2.1", "Confidentiality", "Data Classification",
                "No formal data classification policy",
                Priority.CRITICAL, EffortLevel.MEDIUM, "Security/Legal",
                [
                    "Define classification levels: Public, Internal, Confidential, Restricted",
                    "Map all data types to classification levels",
                    "Define handling requirements per classification level",
                    "Label all data stores and fields with classification",
                    "Train staff on classification procedures",
                ],
                estimated_weeks=3,
                evidence_needed=["Data classification policy", "Data inventory with classifications", "Training records"],
            ),
            "C-2.2": GapItem(
                "C-2.2", "Confidentiality", "Access Review Process",
                "No quarterly access review process",
                Priority.CRITICAL, EffortLevel.MEDIUM, "Security",
                [
                    "Implement automated IAM permission report generation",
                    "Define quarterly review schedule and responsible reviewers",
                    "Create review checklist: least privilege, terminated users, service accounts",
                    "Document review outcomes and remediation actions",
                    "Automate alerting for permission drift between reviews",
                ],
                estimated_weeks=3,
                evidence_needed=["Access review reports (quarterly)", "Remediation records", "Automated IAM reports"],
                dependencies=["C-2.1"],
            ),
            "P-2.1": GapItem(
                "P-2.1", "Privacy", "Privacy Impact Assessment",
                "No PIA template for new features/data processing",
                Priority.HIGH, EffortLevel.SMALL, "Privacy/Legal",
                [
                    "Create PIA template aligned with GDPR Article 35",
                    "Define triggers: new data collection, new processing purpose, new sub-processor",
                    "Include risk assessment matrix",
                    "Integrate PIA into product development lifecycle",
                    "Conduct initial PIA for existing processing activities",
                ],
                estimated_weeks=2,
                evidence_needed=["PIA template", "Completed PIA for existing processing", "Process integration documentation"],
            ),
            "P-2.2": GapItem(
                "P-2.2", "Privacy", "Annual Privacy Review",
                "No regular privacy review process",
                Priority.MEDIUM, EffortLevel.SMALL, "Privacy/Legal",
                [
                    "Define annual privacy review checklist",
                    "Review all consent mechanisms and privacy notices",
                    "Verify data retention compliance",
                    "Audit DSR handling performance against SLAs",
                    "Review sub-processor privacy compliance",
                    "Document findings and action items",
                ],
                estimated_weeks=1,
                evidence_needed=["Annual privacy review report", "Action item tracker"],
                dependencies=["P-2.1"],
            ),
        }

        for control in self.engine.controls:
            if control.status != ControlStatus.IMPLEMENTED:
                gap = gap_remediations.get(control.id)
                if gap:
                    self._gaps.append(gap)

        self._gaps.sort(key=lambda g: (g.priority.value, g.estimated_weeks))
        return self._gaps

    def print_gap_report(self):
        """Print formatted gap analysis report."""
        gaps = self.analyze() if not self._gaps else self._gaps

        print(f"\n{'=' * 70}")
        print("  SOC 2 TYPE II — GAP ANALYSIS REPORT")
        print(f"  Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
        print(f"{'=' * 70}\n")

        readiness = self.engine.overall_readiness()
        print(f"  Overall Readiness: {readiness['readiness_score']}%")
        print(f"  Controls: {readiness['implemented']} implemented, "
              f"{readiness['partially_implemented']} partial, "
              f"{readiness['not_implemented']} missing")
        print(f"  Certification Ready: {'YES' if readiness['certification_ready'] else 'NO — gaps remain'}\n")

        by_priority: dict = {}
        for g in gaps:
            by_priority.setdefault(g.priority.value, []).append(g)

        total_weeks = 0
        for priority in ["P0", "P1", "P2", "P3"]:
            items = by_priority.get(priority, [])
            if not items:
                continue

            label = {"P0": "CRITICAL", "P1": "HIGH", "P2": "MEDIUM", "P3": "LOW"}[priority]
            print(f"  -- {priority} ({label}) {'—' * (50 - len(label))}\n")

            for g in items:
                print(f"  [{g.control_id}] {g.control_name}")
                print(f"    Criteria: {g.criteria}  |  Owner: {g.owner}  |  Effort: {g.effort.value} (~{g.estimated_weeks}w)")
                print(f"    Gap: {g.gap_description}")
                print("    Remediation steps:")
                for i, step in enumerate(g.remediation_steps, 1):
                    print(f"      {i}. {step}")
                if g.dependencies:
                    print(f"    Dependencies: {', '.join(g.dependencies)}")
                print(f"    Evidence needed: {', '.join(g.evidence_needed)}")
                print()
                total_weeks += g.estimated_weeks

        print(f"  {'=' * 66}")
        print(f"  Total gaps: {len(gaps)}  |  Estimated effort: ~{total_weeks} weeks")
        print(f"  Critical (P0): {len(by_priority.get('P0', []))}  |  High (P1): {len(by_priority.get('P1', []))}")
        print(f"{'=' * 70}\n")

    def remediation_timeline(self) -> list:
        """Generate a phased remediation timeline."""
        gaps = self.analyze() if not self._gaps else self._gaps

        phases = [
            {"phase": 1, "name": "Critical Gaps (Weeks 1-4)", "items": [], "weeks": "1-4"},
            {"phase": 2, "name": "High Priority (Weeks 3-8)", "items": [], "weeks": "3-8"},
            {"phase": 3, "name": "Medium Priority (Weeks 6-12)", "items": [], "weeks": "6-12"},
        ]

        for g in gaps:
            if g.priority == Priority.CRITICAL:
                phases[0]["items"].append(g.control_id)
            elif g.priority == Priority.HIGH:
                phases[1]["items"].append(g.control_id)
            else:
                phases[2]["items"].append(g.control_id)

        return phases
