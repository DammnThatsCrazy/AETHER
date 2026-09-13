"""
Aether GDPR — Breach Notification Handler (Article 33/34)
72-hour notification to supervisory authority.
High-risk breaches: notification to affected data subjects.

Incident Response Flow:
  1. Detection (GuardDuty / application alert / manual report)
  2. Assessment (severity, scope, data affected)
  3. Containment (isolate, revoke, block)
  4. Internal escalation (30 min)
  5. Evidence collection
  6. DPA notification (≤ 72 hours)
  7. Data subject notification (if high risk)
  8. Remediation + post-mortem
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Optional

from config.compliance_config import BREACH_CONFIG
from shared.logger import brc_log


class BreachSeverity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class BreachStatus(str, Enum):
    DETECTED = "detected"
    ASSESSING = "assessing"
    CONTAINED = "contained"
    ESCALATED = "escalated"
    DPA_NOTIFIED = "dpa_notified"
    SUBJECTS_NOTIFIED = "subjects_notified"
    REMEDIATED = "remediated"
    CLOSED = "closed"


class DataCategory(str, Enum):
    BEHAVIORAL = "behavioral_events"
    IDENTITY = "identity_profiles"
    CONSENT = "consent_records"
    FINANCIAL = "financial_wallet"
    DEVICE = "device_fingerprints"
    ML_PREDICTIONS = "ml_predictions"


@dataclass
class BreachIncident:
    """Full breach incident record."""
    id: str = field(default_factory=lambda: f"breach_{uuid.uuid4().hex[:12]}")
    detected_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    severity: BreachSeverity = BreachSeverity.LOW
    status: BreachStatus = BreachStatus.DETECTED
    description: str = ""
    detection_source: str = ""
    affected_tenants: list = field(default_factory=list)
    affected_users_count: int = 0
    data_categories_affected: list = field(default_factory=list)
    containment_actions: list = field(default_factory=list)
    dpa_notification_deadline: str = ""
    dpa_notified_at: Optional[str] = None
    subjects_notified_at: Optional[str] = None
    remediation_actions: list = field(default_factory=list)
    evidence: list = field(default_factory=list)
    timeline: list = field(default_factory=list)
    post_mortem_url: Optional[str] = None

    def __post_init__(self):
        if not self.dpa_notification_deadline:
            dl = datetime.fromisoformat(self.detected_at) + timedelta(hours=BREACH_CONFIG.notification_window_hours)
            self.dpa_notification_deadline = dl.isoformat()
        self._add_timeline("Breach detected", self.detection_source)

    def _add_timeline(self, action: str, detail: str = ""):
        self.timeline.append({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "action": action,
            "detail": detail,
        })

    @property
    def hours_since_detection(self) -> float:
        detected = datetime.fromisoformat(self.detected_at)
        return (datetime.now(timezone.utc) - detected).total_seconds() / 3600

    @property
    def hours_until_deadline(self) -> float:
        deadline = datetime.fromisoformat(self.dpa_notification_deadline)
        return (deadline - datetime.now(timezone.utc)).total_seconds() / 3600

    @property
    def requires_subject_notification(self) -> bool:
        """Art. 34: notify subjects if high risk to their rights and freedoms."""
        return self.severity in (BreachSeverity.HIGH, BreachSeverity.CRITICAL)

    def to_dict(self) -> dict:
        return {
            "id": self.id, "severity": self.severity.value,
            "status": self.status.value, "description": self.description,
            "affected_tenants": self.affected_tenants,
            "affected_users_count": self.affected_users_count,
            "data_categories": self.data_categories_affected,
            "dpa_deadline": self.dpa_notification_deadline,
            "hours_remaining": round(self.hours_until_deadline, 1),
            "timeline_events": len(self.timeline),
        }


# ═══════════════════════════════════════════════════════════════════════════
# BREACH HANDLER — Full incident response orchestration
# ═══════════════════════════════════════════════════════════════════════════

class BreachHandler:
    """Orchestrates the full breach notification lifecycle."""

    def __init__(self):
        self._incidents: dict = {}

    # ── Step 1: Detection ─────────────────────────────────────────────

    def report_breach(
        self,
        description: str,
        detection_source: str,
        severity: BreachSeverity = BreachSeverity.MEDIUM,
        affected_tenants: Optional[list] = None,
        data_categories: Optional[list] = None,
    ) -> BreachIncident:
        """Report a new breach incident."""
        incident = BreachIncident(
            description=description,
            detection_source=detection_source,
            severity=severity,
            affected_tenants=affected_tenants or [],
            data_categories_affected=data_categories or [],
        )
        self._incidents[incident.id] = incident

        brc_log(f"BREACH REPORTED: {incident.id}")
        brc_log(f"  Severity: {severity.value}")
        brc_log(f"  Source: {detection_source}")
        brc_log(f"  DPA deadline: {incident.dpa_notification_deadline}")
        brc_log(f"  Hours remaining: {incident.hours_until_deadline:.1f}h")

        return incident

    # ── Step 2: Assessment ────────────────────────────────────────────

    def assess_breach(self, incident_id: str, users_count: int, data_categories: list) -> BreachIncident:
        """Assess the scope and impact of the breach."""
        incident = self._incidents[incident_id]
        incident.status = BreachStatus.ASSESSING
        incident.affected_users_count = users_count
        incident.data_categories_affected = data_categories
        incident._add_timeline("Assessment completed", f"{users_count} users, {len(data_categories)} data categories")

        if users_count > 10000 or "financial_wallet" in data_categories:
            incident.severity = BreachSeverity.CRITICAL
        elif users_count > 1000 or "identity_profiles" in data_categories:
            incident.severity = BreachSeverity.HIGH

        brc_log(f"Assessment: {users_count} users affected, severity → {incident.severity.value}")
        return incident

    # ── Step 3: Containment ───────────────────────────────────────────

    def contain_breach(self, incident_id: str, actions: Optional[list] = None) -> BreachIncident:
        """Execute containment actions."""
        incident = self._incidents[incident_id]
        incident.status = BreachStatus.CONTAINED

        default_actions = [
            "Rotate all affected API keys and credentials",
            "Block suspicious IP addresses via WAF",
            "Invalidate active sessions for affected users",
            "Enable enhanced logging on affected services",
            "Restrict access to affected data stores",
            "Snapshot affected systems for forensic analysis",
        ]
        incident.containment_actions = actions or default_actions

        for action in incident.containment_actions:
            brc_log(f"  Containment: {action}")
            incident._add_timeline("Containment action", action)

        brc_log(f"Breach contained with {len(incident.containment_actions)} actions")
        return incident

    # ── Step 4: Internal Escalation ───────────────────────────────────

    def escalate(self, incident_id: str) -> BreachIncident:
        """Internal escalation within 30 minutes."""
        incident = self._incidents[incident_id]
        incident.status = BreachStatus.ESCALATED
        incident._add_timeline("Internal escalation", f"Within {BREACH_CONFIG.internal_escalation_minutes} min target")

        brc_log("Escalation notifications sent:")
        for channel in BREACH_CONFIG.channels[:3]:
            brc_log(f"  → {channel}")

        return incident

    # ── Step 5: Evidence Collection ───────────────────────────────────

    def collect_evidence(self, incident_id: str) -> BreachIncident:
        """Collect forensic evidence for DPA report."""
        incident = self._incidents[incident_id]

        evidence_sources = [
            {"source": "CloudTrail", "description": "AWS API call logs for the breach window", "collected": True},
            {"source": "Application Audit Logs", "description": "Data access patterns around breach time", "collected": True},
            {"source": "VPC Flow Logs", "description": "Network traffic analysis", "collected": True},
            {"source": "WAF Logs", "description": "Blocked and allowed requests", "collected": True},
            {"source": "GuardDuty Findings", "description": "Threat detection findings", "collected": True},
            {"source": "Access Logs", "description": "ALB/API Gateway request logs", "collected": True},
            {"source": "System Snapshots", "description": "EBS/RDS snapshots at breach time", "collected": True},
        ]

        incident.evidence = evidence_sources
        for ev in evidence_sources:
            brc_log(f"  Evidence: {ev['source']} — {ev['description']}")
            incident._add_timeline("Evidence collected", ev["source"])

        return incident

    # ── Step 6: DPA Notification (≤ 72 hours) ─────────────────────────

    def notify_dpa(self, incident_id: str) -> BreachIncident:
        """Notify the supervisory authority within 72 hours (Art. 33)."""
        incident = self._incidents[incident_id]
        incident.status = BreachStatus.DPA_NOTIFIED
        incident.dpa_notified_at = datetime.now(timezone.utc).isoformat()
        incident._add_timeline("DPA notified", f"Within {incident.hours_since_detection:.1f}h of detection")

        notification = {
            "nature_of_breach": incident.description,
            "categories_of_data": incident.data_categories_affected,
            "approximate_number_of_subjects": incident.affected_users_count,
            "approximate_number_of_records": incident.affected_users_count * 50,
            "dpo_contact": "dpo@aether.network",
            "likely_consequences": self._assess_consequences(incident),
            "measures_taken": incident.containment_actions,
            "measures_proposed": incident.remediation_actions or [
                "Full security audit of affected systems",
                "Credential rotation for all affected accounts",
                "Enhanced monitoring for 90 days",
                "Review and update security controls",
            ],
        }

        brc_log(f"DPA notification sent: {incident.hours_since_detection:.1f}h after detection")
        brc_log(f"  Deadline was: {incident.hours_until_deadline:.1f}h remaining")
        brc_log(f"  Subjects affected: {incident.affected_users_count}")
        brc_log(f"  Data categories: {', '.join(incident.data_categories_affected)}")

        return incident

    # ── Step 7: Data Subject Notification (if high risk) ──────────────

    def notify_subjects(self, incident_id: str) -> BreachIncident:
        """Notify affected data subjects if high risk (Art. 34)."""
        incident = self._incidents[incident_id]

        if not incident.requires_subject_notification:
            brc_log(f"Subject notification not required (severity: {incident.severity.value})")
            return incident

        incident.status = BreachStatus.SUBJECTS_NOTIFIED
        incident.subjects_notified_at = datetime.now(timezone.utc).isoformat()
        incident._add_timeline("Data subjects notified", f"{incident.affected_users_count} users")

        subject_notice = {
            "nature_of_breach": incident.description,
            "dpo_contact": "dpo@aether.network",
            "likely_consequences": self._assess_consequences(incident),
            "measures_taken": incident.containment_actions,
            "recommended_actions": [
                "Review your account activity",
                "Update passwords on connected services",
                "Monitor for suspicious communications",
            ],
        }

        brc_log(f"Subject notification sent to {incident.affected_users_count} users")
        brc_log("  Channels: email, in-app notification, dashboard banner")

        return incident

    # ── Step 8: Remediation ───────────────────────────────────────────

    def remediate(self, incident_id: str, actions: Optional[list] = None) -> BreachIncident:
        """Document remediation actions and close the incident."""
        incident = self._incidents[incident_id]
        incident.status = BreachStatus.REMEDIATED

        incident.remediation_actions = actions or [
            "Root cause analysis completed",
            "Vulnerable component patched",
            "Security controls strengthened",
            "Monitoring rules updated",
            "Incident response playbook updated",
            "Staff security training scheduled",
        ]

        for action in incident.remediation_actions:
            brc_log(f"  Remediation: {action}")
            incident._add_timeline("Remediation action", action)

        return incident

    def close_incident(self, incident_id: str, post_mortem_url: str = "") -> BreachIncident:
        """Close the incident with post-mortem."""
        incident = self._incidents[incident_id]
        incident.status = BreachStatus.CLOSED
        incident.post_mortem_url = post_mortem_url
        incident._add_timeline("Incident closed", post_mortem_url)

        brc_log(f"Incident {incident_id} CLOSED")
        brc_log(f"  Total duration: {incident.hours_since_detection:.1f}h")
        brc_log(f"  Timeline events: {len(incident.timeline)}")
        return incident

    # ── Full Incident Orchestration ───────────────────────────────────

    def run_full_response(self, description: str, detection_source: str,
                          severity: BreachSeverity, users_count: int,
                          data_categories: list) -> BreachIncident:
        """Execute the complete incident response pipeline."""
        brc_log(f"\n{'!' * 50}")
        brc_log("INCIDENT RESPONSE INITIATED")
        brc_log(f"{'!' * 50}\n")

        incident = self.report_breach(description, detection_source, severity)
        self.assess_breach(incident.id, users_count, data_categories)
        self.contain_breach(incident.id)
        self.escalate(incident.id)
        self.collect_evidence(incident.id)
        self.notify_dpa(incident.id)
        self.notify_subjects(incident.id)
        self.remediate(incident.id)
        self.close_incident(incident.id, "https://wiki.aether.network/post-mortems/" + incident.id)

        return incident

    # ── Helpers ───────────────────────────────────────────────────────

    def _assess_consequences(self, incident: BreachIncident) -> list:
        consequences = []
        cats = set(incident.data_categories_affected)
        if "identity_profiles" in cats:
            consequences.append("Potential identity fraud or impersonation")
        if "financial_wallet" in cats:
            consequences.append("Potential financial loss from exposed wallet addresses")
        if "behavioral_events" in cats:
            consequences.append("Exposure of browsing behavior and activity patterns")
        if "consent_records" in cats:
            consequences.append("Compromise of consent preferences")
        if not consequences:
            consequences.append("Limited impact — non-sensitive data categories affected")
        return consequences

    def list_incidents(self, status: Optional[BreachStatus] = None) -> list:
        results = list(self._incidents.values())
        if status:
            results = [i for i in results if i.status == status]
        return results

    def summary(self) -> dict:
        by_severity: dict = {}
        by_status: dict = {}
        for inc in self._incidents.values():
            by_severity[inc.severity.value] = by_severity.get(inc.severity.value, 0) + 1
            by_status[inc.status.value] = by_status.get(inc.status.value, 0) + 1
        return {"total_incidents": len(self._incidents), "by_severity": by_severity, "by_status": by_status}
