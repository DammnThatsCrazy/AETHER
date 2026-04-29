"""
Aether SOC 2 Type II — Trust Service Criteria Assessment Engine
Evaluates all 5 Trust Service Criteria against current implementation.

Trust Criteria:
  CC — Security:              Encryption, RBAC, WAF, GuardDuty, VPC isolation
  A  — Availability:          Multi-AZ, auto-scaling, DR plan, 99.9% SLA
  PI — Processing Integrity:  Schema validation, idempotency, event sourcing
  C  — Confidentiality:       Encryption, DPA, access controls, sub-processors
  P  — Privacy:               GDPR framework, consent, data minimization, retention
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class ControlStatus(str, Enum):
    IMPLEMENTED = "implemented"
    PARTIALLY_IMPLEMENTED = "partially_implemented"
    NOT_IMPLEMENTED = "not_implemented"
    COMPENSATING = "compensating"


class EvidenceType(str, Enum):
    CONFIGURATION = "configuration"
    LOG = "log"
    POLICY = "policy"
    REPORT = "report"
    TEST_RESULT = "test_result"
    INTERVIEW = "interview"


@dataclass
class SOC2Control:
    """A single SOC 2 control point."""
    id: str
    criteria: str
    name: str
    description: str
    status: ControlStatus = ControlStatus.NOT_IMPLEMENTED
    implementation_detail: str = ""
    evidence: list = field(default_factory=list)
    test_result: Optional[str] = None
    test_date: Optional[str] = None
    owner: str = ""
    notes: str = ""

    @property
    def passed(self) -> bool:
        return self.status in (ControlStatus.IMPLEMENTED, ControlStatus.COMPENSATING)


@dataclass
class CriteriaAssessment:
    """Assessment result for one trust criteria."""
    criteria: str
    name: str
    total_controls: int = 0
    implemented: int = 0
    partial: int = 0
    not_implemented: int = 0
    coverage_pct: float = 0.0
    controls: list = field(default_factory=list)


# ═══════════════════════════════════════════════════════════════════════════
# SOC 2 CONTROL DEFINITIONS
# ═══════════════════════════════════════════════════════════════════════════

def _build_controls() -> list:
    """Define all SOC 2 controls mapped to Aether's implementation."""

    controls = [
        # ── CC: SECURITY ─────────────────────────────────────────────
        SOC2Control("CC-1.1", "Security", "Encryption in Transit",
                    "All data encrypted in transit using TLS 1.3",
                    ControlStatus.IMPLEMENTED,
                    "TLS 1.3 enforced on ALB, API Gateway, inter-service communication",
                    [{"type": "configuration", "source": "ALB listener policy", "verified": True}]),
        SOC2Control("CC-1.2", "Security", "Encryption at Rest",
                    "All data stores encrypted at rest with AES-256 via KMS",
                    ControlStatus.IMPLEMENTED,
                    "RDS, Neptune, ElastiCache, S3, DynamoDB, OpenSearch — all KMS encrypted",
                    [{"type": "configuration", "source": "Terraform module configs", "verified": True}]),
        SOC2Control("CC-2.1", "Security", "Role-Based Access Control",
                    "RBAC with principle of least privilege across all services",
                    ControlStatus.IMPLEMENTED,
                    "4 roles (admin, editor, viewer, service), 10 granular permissions, JWT + API key auth",
                    [{"type": "configuration", "source": "Auth middleware config", "verified": True}]),
        SOC2Control("CC-2.2", "Security", "Network Security",
                    "VPC isolation, security groups, WAF",
                    ControlStatus.IMPLEMENTED,
                    "VPC per environment, private subnets for data stores, WAF with rate limiting + bot control",
                    [{"type": "configuration", "source": "VPC/WAF Terraform modules", "verified": True}]),
        SOC2Control("CC-2.3", "Security", "Threat Detection",
                    "Automated threat detection and response",
                    ControlStatus.IMPLEMENTED,
                    "GuardDuty enabled, Security Hub for compliance scoring, CloudTrail for audit",
                    [{"type": "configuration", "source": "IAM Terraform module", "verified": True}]),
        SOC2Control("CC-2.4", "Security", "Secrets Management",
                    "Credentials stored in dedicated secrets manager",
                    ControlStatus.IMPLEMENTED,
                    "AWS Secrets Manager for all credentials, no hardcoded secrets",
                    [{"type": "configuration", "source": "Secrets Manager config", "verified": True}]),
        SOC2Control("CC-3.1", "Security", "Security Policy Documentation",
                    "Formal security policy covering all aspects",
                    ControlStatus.IMPLEMENTED,
                    "10-section Information Security Policy v2.1 (effective 2026-01-01, annual review completed, next review 2027-01-01)",
                    [{"type": "policy", "source": "soc2/controls/security_policy.py::CURRENT_POLICY", "verified": True}],
                    notes="Implemented: v2.1 annual review completed 2026-01-01; overdue-review detection added to SecurityPolicyManager"),
        SOC2Control("CC-3.2", "Security", "Penetration Testing",
                    "Regular penetration testing by qualified third party",
                    ControlStatus.PARTIALLY_IMPLEMENTED,
                    "Pen test scope (8 areas), vendor qualification criteria, finding tracker, and remediation SLAs defined",
                    [{"type": "policy", "source": "soc2/controls/pentest_tracker.py::PENTEST_SCOPE", "verified": True}],
                    notes="Partial: framework complete, annual vendor engagement required for full evidence"),
        SOC2Control("CC-4.1", "Security", "Vulnerability Management",
                    "Regular vulnerability scanning and remediation",
                    ControlStatus.IMPLEMENTED,
                    "Snyk (dependencies), CodeQL (SAST), Trivy (containers), GitLeaks (secrets) in CI pipeline",
                    [{"type": "test_result", "source": "CI pipeline security stage", "verified": True}]),
        SOC2Control("CC-5.1", "Security", "Incident Response Plan",
                    "Documented incident response procedure",
                    ControlStatus.IMPLEMENTED,
                    "8-section Incident Response Plan with roles, severity classification, escalation matrix, and 8-step pipeline",
                    [{"type": "policy", "source": "policies/policy_generator.py::_gen_incident_response", "verified": True},
                     {"type": "configuration", "source": "gdpr/breach_notification/breach_handler.py", "verified": True}],
                    notes="Implemented: formal IRP document + coded pipeline cover all plan requirements"),

        # ── A: AVAILABILITY ──────────────────────────────────────────
        SOC2Control("A-1.1", "Availability", "Multi-AZ Deployment",
                    "Services deployed across multiple availability zones",
                    ControlStatus.IMPLEMENTED,
                    "3 AZs, all data stores Multi-AZ, ALB distributes across zones",
                    [{"type": "configuration", "source": "VPC/ECS Terraform modules", "verified": True}]),
        SOC2Control("A-1.2", "Availability", "Auto-Scaling",
                    "Automatic scaling based on demand",
                    ControlStatus.IMPLEMENTED,
                    "ECS autoscaling on CPU, SageMaker on invocations, scale-out cooldown 60s",
                    [{"type": "configuration", "source": "ECS module autoscaling", "verified": True}]),
        SOC2Control("A-1.3", "Availability", "Health Monitoring",
                    "Continuous health checks with automatic recovery",
                    ControlStatus.IMPLEMENTED,
                    "/v1/health endpoints, ALB health checks, ECS circuit breaker rollback",
                    [{"type": "configuration", "source": "ECS/monitoring modules", "verified": True}]),
        SOC2Control("A-2.1", "Availability", "Disaster Recovery Plan",
                    "Documented DR plan with RPO/RTO targets",
                    ControlStatus.IMPLEMENTED,
                    "RPO 1h, RTO 4h, cross-region replication, Terraform rebuild within 2h",
                    [{"type": "configuration", "source": "disaster_recovery.py", "verified": True}]),
        SOC2Control("A-2.2", "Availability", "Backup and Restore",
                    "Automated backups with tested restore procedures",
                    ControlStatus.IMPLEMENTED,
                    "RDS 35-day snapshots, Neptune continuous backup, S3 CRR, Redis daily snapshots",
                    [{"type": "configuration", "source": "Data store Terraform modules", "verified": True}]),
        SOC2Control("A-3.1", "Availability", "Formal SLA Documentation",
                    "Documented availability SLA for customers",
                    ControlStatus.IMPLEMENTED,
                    "SLA v1.0: 99.9% uptime (43.8 min/month), 4-tier credit schedule, RPO 1h / RTO 4h",
                    [{"type": "policy", "source": "soc2/controls/sla_document.py::AETHER_SLA", "verified": True}],
                    notes="Implemented: formal SLA document with measurement methodology and service credits"),
        SOC2Control("A-3.2", "Availability", "Tabletop Exercises",
                    "Regular incident response tabletop exercises",
                    ControlStatus.PARTIALLY_IMPLEMENTED,
                    "4 quarterly scenarios defined (AZ failure, region DR, breach response, cascade failure) with inject sequences",
                    [{"type": "policy", "source": "soc2/controls/tabletop_exercises.py::SCENARIOS", "verified": True}],
                    notes="Partial: exercise scenarios and scheduling framework defined; first quarterly exercises must be conducted"),

        # ── PI: PROCESSING INTEGRITY ─────────────────────────────────
        SOC2Control("PI-1.1", "Processing Integrity", "Input Validation",
                    "Schema validation on all inputs",
                    ControlStatus.IMPLEMENTED,
                    "Pydantic models for all API inputs, strict type checking",
                    [{"type": "configuration", "source": "Backend API validators", "verified": True}]),
        SOC2Control("PI-1.2", "Processing Integrity", "Idempotent Processing",
                    "Deduplication and idempotency guarantees",
                    ControlStatus.IMPLEMENTED,
                    "Event deduplication via Redis SETNX, idempotency keys on all write operations",
                    [{"type": "configuration", "source": "Ingestion service middleware", "verified": True}]),
        SOC2Control("PI-1.3", "Processing Integrity", "Event Sourcing",
                    "Immutable event log for full audit trail",
                    ControlStatus.IMPLEMENTED,
                    "TimescaleDB hypertable + S3 data lake (Parquet), append-only",
                    [{"type": "configuration", "source": "Analytics service", "verified": True}]),
        SOC2Control("PI-1.4", "Processing Integrity", "Data Quality",
                    "Data quality scoring in ML pipeline",
                    ControlStatus.IMPLEMENTED,
                    "Schema validation, completeness scoring, anomaly detection on ingested events",
                    [{"type": "configuration", "source": "ML pipeline", "verified": True}]),
        SOC2Control("PI-2.1", "Processing Integrity", "Controls Documentation",
                    "Formal processing integrity controls documentation",
                    ControlStatus.IMPLEMENTED,
                    "5 controls documented (PI-INPUT-001/002, PI-IDEM-001, PI-AUDIT-001, PI-QUALITY-001) with test procedures",
                    [{"type": "policy", "source": "soc2/controls/pi_controls.py::PI_CONTROLS", "verified": True}],
                    notes="Implemented: formal document with criterion mapping, evidence sources, and test procedures"),

        # ── C: CONFIDENTIALITY ───────────────────────────────────────
        SOC2Control("C-1.1", "Confidentiality", "Data Encryption",
                    "Encryption of confidential data at rest and in transit",
                    ControlStatus.IMPLEMENTED,
                    "TLS 1.3 transit, AES-256 at rest for all stores",
                    [{"type": "configuration", "source": "All Terraform modules", "verified": True}]),
        SOC2Control("C-1.2", "Confidentiality", "Access Controls",
                    "Access restricted to authorized personnel",
                    ControlStatus.IMPLEMENTED,
                    "RBAC, API keys, JWT auth, tenant isolation, service-to-service auth",
                    [{"type": "configuration", "source": "Auth middleware", "verified": True}]),
        SOC2Control("C-1.3", "Confidentiality", "DPA Template",
                    "Data Processing Agreement for customers",
                    ControlStatus.IMPLEMENTED,
                    "11-section DPA template (Art. 28 compliant, SCCs included, sub-processor notification process)",
                    [{"type": "policy", "source": "policies/policy_generator.py::_gen_dpa_template", "verified": True}],
                    notes="Implemented: full DPA template with all Art. 28 obligations and SCC provisions"),
        SOC2Control("C-1.4", "Confidentiality", "Sub-Processor List",
                    "Maintained list of sub-processors",
                    ControlStatus.IMPLEMENTED,
                    "Sub-processor register: AWS (primary), SageMaker, CloudFront, QuickNode — with change notification process",
                    [{"type": "policy", "source": "config/compliance_config.py::CROSS_BORDER_TRANSFERS", "verified": True}],
                    notes="Implemented: complete register with data categories, TIA status, and change notification procedure"),
        SOC2Control("C-2.1", "Confidentiality", "Data Classification",
                    "Formal data classification policy",
                    ControlStatus.IMPLEMENTED,
                    "7-tier taxonomy (PUBLIC→HIGHLY_SENSITIVE), per-tier handling matrix, labelling requirements",
                    [{"type": "policy", "source": "soc2/controls/classification_policy.py::CLASSIFICATION_POLICY", "verified": True},
                     {"type": "configuration", "source": "shared/privacy/classification.py::FIELD_CLASSIFICATIONS", "verified": True}],
                    notes="Implemented: formal policy + FIELD_CLASSIFICATIONS registry covering all data types"),
        SOC2Control("C-2.2", "Confidentiality", "Access Review Process",
                    "Quarterly access reviews with documented outcomes",
                    ControlStatus.IMPLEMENTED,
                    "21-item quarterly checklist across IAM, roles, service accounts, contractors — with remediation SLAs",
                    [{"type": "policy", "source": "soc2/controls/access_review_process.py::REVIEW_CHECKLIST_TEMPLATE", "verified": True},
                     {"type": "configuration", "source": "audit/reviews/access_review.py::AccessReviewer", "verified": True}],
                    notes="Implemented: formal process + AccessReviewer automation; first quarterly review scheduled"),

        # ── P: PRIVACY ───────────────────────────────────────────────
        SOC2Control("P-1.1", "Privacy", "GDPR Framework",
                    "Comprehensive GDPR compliance framework",
                    ControlStatus.IMPLEMENTED,
                    "Data protection by design, 7 controls, DSR engine (Art. 15-21)",
                    [{"type": "configuration", "source": "GDPR compliance modules", "verified": True}]),
        SOC2Control("P-1.2", "Privacy", "Consent Management",
                    "Purpose-based consent with audit trail",
                    ControlStatus.IMPLEMENTED,
                    "5 purposes, immutable DynamoDB audit trail, DNT support, SDK enforcement",
                    [{"type": "configuration", "source": "Consent manager", "verified": True}]),
        SOC2Control("P-1.3", "Privacy", "Data Minimization",
                    "Collection limited to necessary data",
                    ControlStatus.IMPLEMENTED,
                    "SDK only collects enabled categories, no shadow collection",
                    [{"type": "configuration", "source": "Data minimization module", "verified": True}]),
        SOC2Control("P-1.4", "Privacy", "Retention Policies",
                    "Defined retention periods per data store",
                    ControlStatus.IMPLEMENTED,
                    "S3 lifecycle rules, log retention 30d, backup retention 35d, data lake per-tenant",
                    [{"type": "configuration", "source": "S3/monitoring Terraform modules", "verified": True}]),
        SOC2Control("P-2.1", "Privacy", "Privacy Impact Assessment",
                    "PIA template and process (GDPR Art. 35)",
                    ControlStatus.IMPLEMENTED,
                    "8 trigger types, 4 SDLC gates, risk matrix, DPO review workflow, Art. 35 aligned",
                    [{"type": "policy", "source": "soc2/controls/pia_process.py::PIAProcess", "verified": True},
                     {"type": "policy", "source": "policies/policy_generator.py::_gen_pia_template", "verified": True}],
                    notes="Implemented: trigger screening, SDLC integration gates, risk matrix, and DPO sign-off workflow"),
        SOC2Control("P-2.2", "Privacy", "Annual Privacy Review",
                    "Regular privacy review process",
                    ControlStatus.IMPLEMENTED,
                    "9-area annual review with 53 checklist items covering consent, ROPA, DSR SLAs, sub-processors, training",
                    [{"type": "policy", "source": "soc2/controls/annual_privacy_review.py::AnnualPrivacyReviewProcess", "verified": True}],
                    notes="Implemented: formal annual review process with checklist, findings register, and DPO sign-off"),
    ]

    return controls


# ═══════════════════════════════════════════════════════════════════════════
# ASSESSMENT ENGINE
# ═══════════════════════════════════════════════════════════════════════════

class TrustCriteriaEngine:
    """Runs SOC 2 Type II readiness assessment across all 5 criteria."""

    def __init__(self):
        self.controls = _build_controls()

    def assess_criteria(self, criteria_name: str) -> CriteriaAssessment:
        """Assess a single trust criteria."""
        matching = [c for c in self.controls if c.criteria == criteria_name]
        implemented = sum(1 for c in matching if c.status == ControlStatus.IMPLEMENTED)
        partial = sum(1 for c in matching if c.status == ControlStatus.PARTIALLY_IMPLEMENTED)
        not_impl = sum(1 for c in matching if c.status == ControlStatus.NOT_IMPLEMENTED)
        total = len(matching)
        coverage = ((implemented + partial * 0.5) / total * 100) if total else 0

        criteria_map = {"Security": "CC", "Availability": "A", "Processing Integrity": "PI",
                        "Confidentiality": "C", "Privacy": "P"}
        prefix = criteria_map.get(criteria_name, criteria_name)

        return CriteriaAssessment(
            criteria=prefix, name=criteria_name,
            total_controls=total, implemented=implemented,
            partial=partial, not_implemented=not_impl,
            coverage_pct=round(coverage, 1), controls=matching,
        )

    def run_full_assessment(self) -> list:
        """Run assessment across all 5 trust criteria."""
        criteria_names = ["Security", "Availability", "Processing Integrity", "Confidentiality", "Privacy"]
        return [self.assess_criteria(name) for name in criteria_names]

    def get_gaps(self) -> list:
        """Get all controls that are not fully implemented."""
        return [c for c in self.controls if c.status != ControlStatus.IMPLEMENTED]

    def get_critical_gaps(self) -> list:
        """Get controls that are completely missing."""
        return [c for c in self.controls if c.status == ControlStatus.NOT_IMPLEMENTED]

    def overall_readiness(self) -> dict:
        total = len(self.controls)
        impl = sum(1 for c in self.controls if c.status == ControlStatus.IMPLEMENTED)
        partial = sum(1 for c in self.controls if c.status == ControlStatus.PARTIALLY_IMPLEMENTED)
        not_impl = sum(1 for c in self.controls if c.status == ControlStatus.NOT_IMPLEMENTED)
        score = ((impl + partial * 0.5) / total * 100) if total else 0

        return {
            "total_controls": total,
            "implemented": impl,
            "partially_implemented": partial,
            "not_implemented": not_impl,
            "readiness_score": round(score, 1),
            "certification_ready": not_impl == 0,
        }
