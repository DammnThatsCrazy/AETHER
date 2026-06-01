"""Enterprise packaging, audit export, and deployment readiness contracts."""
from __future__ import annotations

import csv
import hashlib
import io
import json
import uuid
from datetime import timedelta
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from shared.common.common import utc_now

Market = Literal["enterprise", "government", "regulated", "commercial", "government_planning"]
ReadinessStatus = Literal["draft", "internal_ready", "pilot_ready", "sales_ready", "enterprise_ready", "government_planning"]
DeploymentName = Literal["standard_saas", "enterprise_isolated_tenant", "regulated_cloud", "government_ready_planning", "self_hosted_future"]
AuditFormat = Literal["json", "csv", "pdf_summary"]
AuditStatus = Literal["queued", "generated", "failed", "expired"]


class TimeWindow(BaseModel):
    start: str
    end: str


class SolutionPackage(BaseModel):
    package_id: str
    name: str
    market: Market | list[Market]
    description: str
    buyer_personas: list[str]
    use_cases: list[str]
    included_modules: list[str]
    required_feature_flags: list[str]
    recommended_integrations: list[str]
    required_audit_exports: list[str]
    pricing_levers: list[str]
    deployment_modes: list[DeploymentName]
    readiness_status: ReadinessStatus
    created_at: str
    updated_at: str


class PackageReadinessReport(BaseModel):
    package_id: str
    readiness_status: ReadinessStatus
    feature_completeness: str
    documentation_completeness: str
    test_coverage_status: str
    audit_export_support: str
    access_control_status: str
    integration_support_status: str
    deployment_support_status: str
    pricing_defined: bool
    sales_collateral_status: str
    known_gaps: list[str]
    recommended_next_actions: list[str]
    generated_at: str


class DeploymentMode(BaseModel):
    deployment_mode_id: str
    name: DeploymentName
    description: str
    required_controls: list[str]
    required_docs: list[str]
    supported_features: list[str]
    unsupported_features: list[str]
    readiness_status: ReadinessStatus
    known_gaps: list[str]


class AuditExportType(BaseModel):
    export_type: str
    label: str
    description: str
    included_records: list[str]
    supported_formats: list[AuditFormat]
    required_permissions: list[str]
    retention_policy_notes: str


class AuditExportRequest(BaseModel):
    export_type: str
    tenant_id: str | None = None
    time_window: TimeWindow
    entity_id: str | None = None
    recommendation_id: str | None = None
    playbook_id: str | None = None
    include_evidence: bool = True
    include_dispatch_receipts: bool = True
    include_confidence_deltas: bool = True
    format: AuditFormat = "json"

    @model_validator(mode="after")
    def pdf_is_summary_only(self) -> "AuditExportRequest":
        return self


class AuditExportRecord(BaseModel):
    export_id: str
    tenant_id: str
    export_type: str
    requested_by: str
    status: AuditStatus
    format: AuditFormat
    time_window: TimeWindow
    file_ref: str | None = None
    integrity_hash: str
    generated_at: str
    expires_at: str
    error_message: str | None = None
    payload: dict[str, Any] | list[dict[str, Any]] | str | None = Field(default=None, exclude=True)


STAMP = "2026-06-01T00:00:00Z"

AUDIT_EXPORT_TYPES: list[AuditExportType] = [
    AuditExportType(export_type="recommendation_audit", label="Recommendation audit", description="Recommendation lifecycle, evidence references, confidence, policy flags, freshness, and status.", included_records=["recommendations", "evidence_references", "confidence_breakdown", "policy_flags", "data_freshness", "status_lifecycle"], supported_formats=["json", "csv", "pdf_summary"], required_permissions=["read", "export"], retention_policy_notes="Generated records expire after 7 days; source records remain governed by tenant retention policy."),
    AuditExportType(export_type="decision_audit", label="Decision audit", description="Decision records with actors, selected/rejected actions, approvals, reasons, comments, and timestamps.", included_records=["decisions", "actor_id", "selected_actions", "rejected_actions", "approval_status", "reason", "comment", "created_at"], supported_formats=["json", "csv", "pdf_summary"], required_permissions=["read", "export"], retention_policy_notes="Generated records expire after 7 days."),
    AuditExportType(export_type="action_dispatch_audit", label="Action dispatch audit", description="Actions, dispatches, delivery receipts, authorization metadata presence, transitions, and idempotency keys.", included_records=["actions", "dispatches", "delivery_receipts", "authorization_metadata_presence", "status_transitions", "idempotency_keys"], supported_formats=["json", "csv", "pdf_summary"], required_permissions=["read", "export"], retention_policy_notes="Secrets and connector credentials are never included."),
    AuditExportType(export_type="outcome_audit", label="Outcome audit", description="Outcomes, values, labels, confidence deltas, and observed windows.", included_records=["outcomes", "values", "labels", "confidence_deltas", "observed_windows"], supported_formats=["json", "csv", "pdf_summary"], required_permissions=["read", "export"], retention_policy_notes="Generated records expire after 7 days."),
    AuditExportType(export_type="playbook_run_audit", label="Playbook run audit", description="Playbook definitions, run history, generated recommendations, linked decisions/actions/outcomes, and ROI metrics.", included_records=["playbook_definition", "run_history", "generated_recommendations", "linked_decisions", "linked_actions", "linked_outcomes", "roi_metrics"], supported_formats=["json", "pdf_summary"], required_permissions=["read", "export"], retention_policy_notes="Generated records expire after 7 days."),
    AuditExportType(export_type="agent_governance_audit", label="Agent governance audit", description="Agent-related recommendations, approvals, actions, dispatches, outcomes, policy flags, and governance notes.", included_records=["agent_recommendations", "approvals", "actions", "dispatches", "outcomes", "policy_flags", "governance_notes"], supported_formats=["json", "csv", "pdf_summary"], required_permissions=["read", "export"], retention_policy_notes="Generated records expire after 7 days."),
    AuditExportType(export_type="tenant_value_audit", label="Tenant value audit", description="Outcome ledger, playbook ROI, recommendation family performance, observed/pending value, and counts.", included_records=["outcome_ledger_summary", "playbook_roi", "recommendation_family_performance", "observed_value", "pending_value", "success_failure_neutral_counts"], supported_formats=["json", "pdf_summary"], required_permissions=["read", "export"], retention_policy_notes="Generated records expire after 7 days."),
    AuditExportType(export_type="package_readiness_audit", label="Package readiness audit", description="Commercial package readiness, deployment mode support, known gaps, and next actions.", included_records=["solution_packages", "readiness_reports", "deployment_modes", "known_gaps"], supported_formats=["json", "pdf_summary"], required_permissions=["admin", "export"], retention_policy_notes="Admin-only readiness snapshot."),
]

SOLUTION_PACKAGES: list[SolutionPackage] = [
    SolutionPackage(package_id="revenue_intelligence_graph", name="Revenue Intelligence Graph", market=["enterprise", "commercial"], description="Retention, expansion, attribution, journey optimization, and revenue outcome tracking packaged from graph-native OODA loops.", buyer_personas=["CMO", "CRO", "VP Growth", "RevOps", "Head of Customer Success"], use_cases=["retention", "expansion", "attribution optimization", "journey optimization", "revenue outcome tracking"], included_modules=["Recommendation Family Registry", "Outcome Ledger", "Playbook ROI", "Kyber Revenue Observability"], required_feature_flags=["decision_outcome", "outcome_ledger", "playbook_roi"], recommended_integrations=["CRM", "marketing automation", "support desk", "warehouse"], required_audit_exports=["recommendation_audit", "decision_audit", "outcome_audit", "tenant_value_audit"], pricing_levers=["tenant seats", "tracked entities", "recommendation volume", "observed revenue value"], deployment_modes=["standard_saas", "enterprise_isolated_tenant"], readiness_status="sales_ready", created_at=STAMP, updated_at=STAMP),
    SolutionPackage(package_id="fraud_risk_intelligence_graph", name="Fraud & Risk Intelligence Graph", market=["enterprise", "regulated"], description="Fraud cluster review, suspicious relationship detection, investigation workflows, reward abuse prevention, and avoided-loss tracking.", buyer_personas=["Head of Risk", "Trust & Safety", "Fraud Ops", "Compliance", "Security"], use_cases=["fraud cluster review", "suspicious relationship detection", "investigation workflows", "reward abuse prevention", "avoided-loss tracking"], included_modules=["Investigation Workspace", "Fraud Review Families", "Outcome Ledger", "Action Dispatch"], required_feature_flags=["investigations", "decision_outcome", "audit_exports"], recommended_integrations=["case management", "SIEM", "identity verification", "ticketing"], required_audit_exports=["recommendation_audit", "decision_audit", "action_dispatch_audit", "outcome_audit"], pricing_levers=["case volume", "entities monitored", "avoided loss bands", "premium connectors"], deployment_modes=["standard_saas", "enterprise_isolated_tenant", "regulated_cloud"], readiness_status="pilot_ready", created_at=STAMP, updated_at=STAMP),
    SolutionPackage(package_id="agent_governance_graph", name="Agent Governance Graph", market=["enterprise", "regulated", "government_planning"], description="Agent oversight, approval routing, action auditability, failure detection, and outcomes without claiming external certification.", buyer_personas=["CTO", "AI Platform Lead", "Security Lead", "Governance/Risk Lead", "COO"], use_cases=["agent oversight", "human approval routing", "action auditability", "agent failure detection", "outcome tracking"], included_modules=["Agent Governance Recommendations", "Approval Model", "Action Dispatch", "Outcome Ledger"], required_feature_flags=["agent_governance", "approvals", "action_dispatch", "audit_exports"], recommended_integrations=["agent runtime", "ticketing", "SIEM", "policy registry"], required_audit_exports=["agent_governance_audit", "action_dispatch_audit", "outcome_audit"], pricing_levers=["agents governed", "approval volume", "dispatch volume", "audit retention"], deployment_modes=["enterprise_isolated_tenant", "regulated_cloud", "government_ready_planning"], readiness_status="government_planning", created_at=STAMP, updated_at=STAMP),
    SolutionPackage(package_id="operational_decision_intelligence", name="Operational Decision Intelligence", market="enterprise", description="Operational decision tracking, playbook ROI, action dispatch, outcome measurement, and stale-loop repair.", buyer_personas=["COO", "Strategy", "VP Operations", "Transformation Lead"], use_cases=["operational decision tracking", "playbook ROI", "action dispatch", "outcome measurement", "stale loop repair"], included_modules=["Decision Records", "Playbook Templates", "Playbook ROI", "Action Dispatch", "Outcome Ledger"], required_feature_flags=["decision_outcome", "playbooks", "action_dispatch"], recommended_integrations=["project management", "ticketing", "warehouse", "BI"], required_audit_exports=["decision_audit", "action_dispatch_audit", "playbook_run_audit", "outcome_audit"], pricing_levers=["operator seats", "playbook runs", "dispatches", "measured value"], deployment_modes=["standard_saas", "enterprise_isolated_tenant"], readiness_status="sales_ready", created_at=STAMP, updated_at=STAMP),
    SolutionPackage(package_id="program_integrity_graph", name="Program Integrity Graph", market=["government_planning", "regulated"], description="Planning/readiness package for grants, claims, vendor review, anomalous relationship detection, prioritization, decisions, and outcomes; not certified government compliance.", buyer_personas=["Program Integrity Lead", "Inspector General staff", "Compliance", "Case Operations"], use_cases=["grants/claims/vendor review", "anomalous relationship detection", "case prioritization", "decision auditability", "outcome tracking"], included_modules=["Investigation Workspace", "Fraud/Risk Families", "Decision Audit", "Outcome Ledger"], required_feature_flags=["investigations", "decision_outcome", "audit_exports"], recommended_integrations=["case management", "identity data", "document registry", "data warehouse"], required_audit_exports=["recommendation_audit", "decision_audit", "outcome_audit", "package_readiness_audit"], pricing_levers=["case volume", "programs monitored", "audit exports", "isolated tenant controls"], deployment_modes=["government_ready_planning", "regulated_cloud"], readiness_status="government_planning", created_at=STAMP, updated_at=STAMP),
    SolutionPackage(package_id="critical_infrastructure_coordination_graph", name="Critical Infrastructure Coordination Graph", market=["government_planning", "regulated", "enterprise"], description="Planning/readiness package for dependency mapping, incident coordination, vendor/system risk, actions/outcomes, and AI-enabled operational oversight; not certified government compliance.", buyer_personas=["Critical Infrastructure Operator", "Emergency Operations", "Security Operations", "Public Sector Technology Lead"], use_cases=["dependency mapping", "incident coordination", "vendor/system risk", "action/outcome tracking", "AI-enabled operational oversight"], included_modules=["Operational Failure Families", "Action Dispatch", "Outcome Ledger", "Kyber Strategic Observability"], required_feature_flags=["operational_intelligence", "action_dispatch", "audit_exports"], recommended_integrations=["CMDB", "incident management", "SIEM", "vendor risk system"], required_audit_exports=["decision_audit", "action_dispatch_audit", "outcome_audit", "agent_governance_audit"], pricing_levers=["systems mapped", "incident volume", "operator seats", "readiness assessments"], deployment_modes=["enterprise_isolated_tenant", "regulated_cloud", "government_ready_planning"], readiness_status="government_planning", created_at=STAMP, updated_at=STAMP),
]

DEPLOYMENT_MODES: list[DeploymentMode] = [
    DeploymentMode(deployment_mode_id="standard_saas", name="standard_saas", description="Shared SaaS control plane with strict tenant-scoped application access.", required_controls=["tenant-scoped auth", "role permissions", "audit exports", "secret redaction"], required_docs=["docs/AUDIT-EXPORTS.md", "docs/ENTERPRISE-PACKAGING.md"], supported_features=["recommendations", "decisions", "actions", "outcomes", "playbooks", "audit exports"], unsupported_features=["customer-managed keys", "air-gapped operation"], readiness_status="sales_ready", known_gaps=["formal SOC 2 report is not represented in this package layer"]),
    DeploymentMode(deployment_mode_id="enterprise_isolated_tenant", name="enterprise_isolated_tenant", description="Enterprise packaging for logically isolated tenants and tighter integration governance.", required_controls=["tenant isolation", "admin approvals", "export permission", "integration secret references"], required_docs=["docs/DEPLOYMENT-READINESS.md", "docs/ENTERPRISE-PACKAGING.md"], supported_features=["all SaaS intelligence modules", "Kyber readiness views", "audit exports"], unsupported_features=["self-hosting"], readiness_status="pilot_ready", known_gaps=["customer-specific isolation runbooks required before marking enterprise_ready"]),
    DeploymentMode(deployment_mode_id="regulated_cloud", name="regulated_cloud", description="Regulated-cloud planning track for stronger retention, incident, AI-risk, and documentation controls.", required_controls=["retention policy", "incident response docs", "AI risk management docs", "audit export review"], required_docs=["docs/DEPLOYMENT-READINESS.md", "docs/GOVERNMENT-READINESS-PLANNING.md"], supported_features=["tenant-scoped audit exports", "approval routing", "outcome ledger"], unsupported_features=["certified compliance claims", "classified workloads"], readiness_status="draft", known_gaps=["control evidence packets and deployment runbooks are not complete"]),
    DeploymentMode(deployment_mode_id="government_ready_planning", name="government_ready_planning", description="Future public-sector readiness planning only; no authorization, FedRAMP, StateRAMP, or procurement compliance is claimed.", required_controls=["government package disclaimers", "tenant isolation", "auditability", "human approvals", "data retention docs", "AI risk docs"], required_docs=["docs/GOVERNMENT-READINESS-PLANNING.md", "docs/DEPLOYMENT-READINESS.md"], supported_features=["readiness assessment", "package readiness audit", "tenant-safe export payloads"], unsupported_features=["certified government cloud", "classified data", "ATO claims"], readiness_status="government_planning", known_gaps=["no government certification or authorization package exists"]),
    DeploymentMode(deployment_mode_id="self_hosted_future", name="self_hosted_future", description="Future self-hosted mode for planning only.", required_controls=["deployment automation", "upgrade docs", "customer secrets boundary", "support model"], required_docs=["docs/DEPLOYMENT-READINESS.md"], supported_features=["planning checklist only"], unsupported_features=["current production deployment"], readiness_status="draft", known_gaps=["not implemented as a deployable mode"]),
]


def audit_export_type_map() -> dict[str, AuditExportType]:
    return {t.export_type: t for t in AUDIT_EXPORT_TYPES}


def redact_secrets(value: Any) -> Any:
    secret_keys = {"secret", "api_key", "auth_secret", "webhook_secret", "token", "password", "secret_ref"}
    if isinstance(value, dict):
        return {k: ("[redacted]" if k.lower() in secret_keys else redact_secrets(v)) for k, v in value.items()}
    if isinstance(value, list):
        return [redact_secrets(v) for v in value]
    return value


def integrity_hash(payload: Any) -> str:
    body = json.dumps(payload, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def to_csv_payload(rows: list[dict[str, Any]]) -> str:
    flattened = []
    for row in rows:
        flat = {k: (json.dumps(v, sort_keys=True, default=str) if isinstance(v, (dict, list)) else v) for k, v in row.items()}
        flattened.append(flat)
    if not flattened:
        return ""
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=sorted({k for r in flattened for k in r}))
    writer.writeheader()
    writer.writerows(flattened)
    return output.getvalue()


def pdf_summary_payload(export_type: str, payload: Any) -> dict[str, Any]:
    count = len(payload) if isinstance(payload, list) else len(payload.keys()) if isinstance(payload, dict) else 1
    return {"format": "pdf_summary", "pdf_generation": "future_work", "export_type": export_type, "record_count": count, "summary_generated_at": utc_now().isoformat()}


def make_export_record(*, tenant_id: str, requested_by: str, request: AuditExportRequest, payload: Any) -> AuditExportRecord:
    now = utc_now()
    return AuditExportRecord(export_id=str(uuid.uuid4()), tenant_id=tenant_id, export_type=request.export_type, requested_by=requested_by, status="generated", format=request.format, time_window=request.time_window, file_ref=None, integrity_hash=integrity_hash(payload), generated_at=now.isoformat(), expires_at=(now + timedelta(days=7)).isoformat(), payload=payload)
