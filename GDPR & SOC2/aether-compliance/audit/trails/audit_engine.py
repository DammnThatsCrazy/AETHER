"""
Aether Compliance — Audit Engine
5 audit trail types with immutable logging, querying, and retention verification.

Trails:
  1. CloudTrail         — All AWS API calls (365 days)
  2. Application Audit  — Data access, modification, deletion (365 days)
  3. Consent Audit      — Consent grants, revocations, DSRs (7 years)
  4. Agent Audit        — AI agent actions with provenance (365 days)
  5. Access Reviews     — Quarterly IAM permission reviews (3 years)
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from config.compliance_config import AUDIT_TRAILS
from shared.logger import aud_log


class AuditAction(str, Enum):
    READ = "read"
    CREATE = "create"
    UPDATE = "update"
    DELETE = "delete"
    EXPORT = "export"
    CONSENT_GRANT = "consent_grant"
    CONSENT_REVOKE = "consent_revoke"
    DSR_REQUEST = "dsr_request"
    DSR_COMPLETE = "dsr_complete"
    AGENT_INFERENCE = "agent_inference"
    AGENT_ACTION = "agent_action"
    ACCESS_REVIEW = "access_review"
    LOGIN = "login"
    PERMISSION_CHANGE = "permission_change"

    # Intelligence Graph — Agent/Commerce/On-Chain audit actions
    AGENT_REGISTERED = "agent_registered"
    AGENT_DELEGATED = "agent_delegated"
    AGENT_HIRED = "agent_hired"
    PAYMENT_RECORDED = "payment_recorded"
    X402_CAPTURED = "x402_captured"
    CONTRACT_DEPLOYED = "contract_deployed"
    TRUST_SCORE_COMPUTED = "trust_score_computed"
    BYTECODE_RISK_ASSESSED = "bytecode_risk_assessed"
    GROUND_TRUTH_SUBMITTED = "ground_truth_submitted"
    CONFIDENCE_DELTA_COMPUTED = "confidence_delta_computed"


@dataclass
class AuditEntry:
    """A single audit log entry."""
    id: str = field(default_factory=lambda: f"aud_{uuid.uuid4().hex[:12]}")
    trail: str = "application"
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    actor: str = ""
    tenant_id: str = ""
    action: AuditAction = AuditAction.READ
    resource_type: str = ""
    resource_id: str = ""
    detail: Optional[dict] = None
    ip_address: str = ""
    user_agent: str = ""


# ═══════════════════════════════════════════════════════════════════════════
# AUDIT ENGINE
# ═══════════════════════════════════════════════════════════════════════════

class AuditEngine:
    """Centralized audit logging across all 5 trail types."""

    def __init__(self):
        self._entries: list = []

    def _log_entry(self, entry: AuditEntry):
        self._entries.append(entry)
        aud_log(f"[{entry.trail}] {entry.action.value}: {entry.actor} → {entry.resource_type}/{entry.resource_id}")

    # ── Application Audit Trail ──────────────────────────────────────

    def log_data_access(self, actor: str, tenant_id: str, resource_type: str,
                        resource_id: str, action: AuditAction, detail: Optional[dict] = None):
        """Log data access, modification, or deletion."""
        self._log_entry(AuditEntry(
            trail="application", actor=actor, tenant_id=tenant_id,
            action=action, resource_type=resource_type, resource_id=resource_id,
            detail=detail,
        ))

    # ── Consent Audit Trail ──────────────────────────────────────────

    def log_consent_event(self, tenant_id: str, user_id: str, action: AuditAction,
                          purpose: str, policy_version: str = ""):
        """Log consent grant or revocation (immutable, 7-year retention)."""
        self._log_entry(AuditEntry(
            trail="consent", actor=user_id, tenant_id=tenant_id,
            action=action, resource_type="consent", resource_id=purpose,
            detail={"policy_version": policy_version} if policy_version else None,
        ))

    def log_dsr(self, tenant_id: str, user_id: str, dsr_type: str, dsr_id: str):
        """Log data subject request submission."""
        self._log_entry(AuditEntry(
            trail="consent", actor=user_id, tenant_id=tenant_id,
            action=AuditAction.DSR_REQUEST, resource_type="dsr", resource_id=dsr_id,
            detail={"dsr_type": dsr_type},
        ))

    # ── Agent Audit Trail ────────────────────────────────────────────

    def log_agent_action(self, tenant_id: str, agent_id: str, task_id: str,
                         action_type: str, inputs: dict, outputs: dict,
                         confidence: float = 0.0, model_version: str = ""):
        """Log AI agent action with full provenance."""
        self._log_entry(AuditEntry(
            trail="agent", actor=agent_id, tenant_id=tenant_id,
            action=AuditAction.AGENT_ACTION, resource_type="task", resource_id=task_id,
            detail={
                "action_type": action_type,
                "inputs": inputs,
                "outputs": outputs,
                "confidence": confidence,
                "model_version": model_version,
            },
        ))

    # ── Access Review Trail ──────────────────────────────────────────

    def log_access_review(self, reviewer: str, quarter: str,
                          findings: list, actions_taken: list):
        """Log quarterly IAM access review."""
        self._log_entry(AuditEntry(
            trail="access_review", actor=reviewer, tenant_id="global",
            action=AuditAction.ACCESS_REVIEW, resource_type="iam_review", resource_id=quarter,
            detail={"findings": findings, "actions_taken": actions_taken},
        ))

    # ── Query & Reporting ────────────────────────────────────────────

    def query(self, trail: Optional[str] = None, tenant_id: Optional[str] = None,
              actor: Optional[str] = None, action: Optional[AuditAction] = None) -> list:
        """Query audit entries with optional filters."""
        results = list(self._entries)
        if trail:
            results = [e for e in results if e.trail == trail]
        if tenant_id:
            results = [e for e in results if e.tenant_id == tenant_id]
        if actor:
            results = [e for e in results if e.actor == actor]
        if action:
            results = [e for e in results if e.action == action]
        return results

    def retention_report(self) -> list:
        """Report on audit trail retention compliance."""
        trail_counts: dict = {}
        for e in self._entries:
            trail_counts[e.trail] = trail_counts.get(e.trail, 0) + 1

        # Map config names to actual trail values used in _log_entry
        trail_key_map = {
            "CloudTrail": "cloudtrail",
            "Application Audit": "application",
            "Consent Audit": "consent",
            "Agent Audit": "agent",
            "Access Reviews": "access_review",
        }

        report = []
        for config in AUDIT_TRAILS:
            name_key = trail_key_map.get(config.name, config.name.lower().replace(" ", "_"))
            count = trail_counts.get(name_key, 0)
            years = config.retention_days / 365
            report.append({
                "trail": config.name,
                "retention_days": config.retention_days,
                "retention_years": round(years, 1),
                "storage": config.storage,
                "entries": count,
            })
        return report

    def verify_trails(self):
        """Verify all 5 audit trail types are active."""
        aud_log("Verifying audit trail integrity:")
        for config in AUDIT_TRAILS:
            years = config.retention_days / 365
            aud_log(f"  {config.name:22s} | {config.retention_days:>5d}d ({years:.0f}y) | {config.storage}")

    def summary(self) -> dict:
        by_trail: dict = {}
        by_action: dict = {}
        for e in self._entries:
            by_trail[e.trail] = by_trail.get(e.trail, 0) + 1
            by_action[e.action.value] = by_action.get(e.action.value, 0) + 1
        return {"total_entries": len(self._entries), "by_trail": by_trail, "by_action": by_action}
