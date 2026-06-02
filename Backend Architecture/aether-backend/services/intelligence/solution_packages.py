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



PricingStatus = Literal["draft", "internal_ready", "sales_ready"]
PricingUnit = Literal["event", "entity", "graph_operation", "recommendation", "playbook_run", "action_dispatch", "outcome_observation", "audit_export", "integration", "deployment", "service_hour", "value_created"]
GTMMaterialType = Literal["one_pager", "sales_deck", "technical_brief", "security_brief", "audit_brief", "pricing_sheet", "roi_calculator", "procurement_faq", "pilot_proposal", "case_study_template", "objection_handling"]
GTMMarket = Literal["commercial", "enterprise", "regulated", "government_planning"]


class PricingDimension(BaseModel):
    dimension_key: str
    label: str
    description: str
    unit: PricingUnit
    metering_source: str
    included_in_tiers: list[str]
    billable: bool
    notes: str


class PricingModel(BaseModel):
    pricing_model_id: str
    name: str
    description: str
    base_platform_fee_notes: str
    usage_dimensions: list[PricingDimension]
    premium_modules: list[str]
    integration_pricing: list[str]
    deployment_pricing: list[str]
    services_pricing: list[str]
    value_based_pricing_notes: list[str]
    applicable_solution_packages: list[str]
    status: PricingStatus
    created_at: str
    updated_at: str


class GTMMaterial(BaseModel):
    material_id: str
    title: str
    material_type: GTMMaterialType
    solution_package_ids: list[str]
    buyer_personas: list[str]
    market: GTMMarket
    status: PricingStatus
    file_ref: str | None = None
    content_blocks: list[str]
    created_at: str
    updated_at: str


class BuyerPersona(BaseModel):
    persona_id: str
    title: str
    market: GTMMarket
    pains: list[str]
    desired_outcomes: list[str]
    objections: list[str]
    buying_triggers: list[str]
    relevant_solution_packages: list[str]
    recommended_collateral: list[str]
    pricing_sensitivity: str
    proof_needed: list[str]


class ROICalculatorDefinition(BaseModel):
    calculator_id: str
    solution_package_id: str
    inputs: list[str]
    formulas: list[str]
    outputs: list[str]
    assumptions: list[str]
    disclaimer: str
    status: PricingStatus


PRICING_DIMENSIONS: list[PricingDimension] = [
    PricingDimension(dimension_key="events_ingested", label="Events ingested", description="Tenant-scoped events accepted into Aether.", unit="event", metering_source="event ingestion ledger", included_in_tiers=["platform_access"], billable=True, notes="Base included allowance may vary by tier; no dollar amount is encoded."),
    PricingDimension(dimension_key="entities_resolved", label="Entities resolved", description="Identity, account, device, organization, or system entities resolved into graph context.", unit="entity", metering_source="identity/entity resolution logs", included_in_tiers=["platform_access"], billable=True, notes="Maps to base graph and Profile360 usage."),
    PricingDimension(dimension_key="graph_traversals", label="Graph traversals", description="Graph traversals and profile queries used by Kyber and tenant-facing Aether surfaces.", unit="graph_operation", metering_source="graph query audit", included_in_tiers=["platform_access"], billable=True, notes="Includes profile queries as graph/profile operations."),
    PricingDimension(dimension_key="recommendations_generated", label="Recommendations generated", description="Decision intelligence recommendations generated by OODA loops.", unit="recommendation", metering_source="recommendation repository", included_in_tiers=["premium_modules"], billable=True, notes="Requires human-in-the-loop governance where configured."),
    PricingDimension(dimension_key="playbook_runs", label="Playbook runs", description="Template or custom playbook executions.", unit="playbook_run", metering_source="playbook run ledger", included_in_tiers=["premium_modules"], billable=True, notes="Supports Playbook ROI without guaranteeing outcomes."),
    PricingDimension(dimension_key="action_dispatches", label="Action dispatches", description="Approved integration actions dispatched to external systems.", unit="action_dispatch", metering_source="action dispatch audit", included_in_tiers=["premium_modules"], billable=True, notes="Secrets are referenced, not exported."),
    PricingDimension(dimension_key="outcomes_observed", label="Outcomes observed", description="Observed outcome ledger records connected to decisions/actions.", unit="outcome_observation", metering_source="outcome ledger", included_in_tiers=["premium_modules"], billable=True, notes="Outcome values are estimates/observations, not guarantees."),
    PricingDimension(dimension_key="audit_exports_generated", label="Audit exports generated", description="Tenant-scoped JSON/CSV/PDF-summary audit exports.", unit="audit_export", metering_source="audit export registry", included_in_tiers=["enterprise_governance"], billable=True, notes="Does not imply external certification."),
    PricingDimension(dimension_key="integration_deliveries", label="Integration deliveries", description="Connector setup or ongoing delivery units.", unit="integration", metering_source="integration delivery tracker", included_in_tiers=["integration_pricing"], billable=True, notes="Custom connectors may require services."),
    PricingDimension(dimension_key="deployment_mode", label="Deployment mode", description="Standard SaaS, isolated tenant, regulated-cloud planning, government-ready planning, or future self-hosted packaging.", unit="deployment", metering_source="deployment readiness registry", included_in_tiers=["deployment_pricing"], billable=True, notes="Government and self-hosted entries are planning-only until implemented."),
]

PREMIUM_MODULES = ["Decision & Outcome Intelligence", "Revenue Intelligence Graph", "Fraud & Risk Intelligence Graph", "Agent Governance Graph", "Operational Decision Intelligence", "Program Integrity Graph planning package", "Critical Infrastructure Coordination planning package"]
DEPLOYMENT_PRICING = ["standard SaaS", "enterprise isolated tenant", "regulated cloud", "government-ready planning", "self-hosted future"]
SERVICES_PRICING = ["onboarding", "implementation", "data mapping", "graph design", "custom playbooks", "custom integrations", "audit export configuration", "strategic advisory", "managed workflows"]
VALUE_BASED_NOTES = ["retained revenue", "expansion revenue", "avoided loss", "reduced campaign waste", "operational hours saved", "agent failure cost reduction"]

PRICING_MODELS: list[PricingModel] = [PricingModel(pricing_model_id="aether_solution_package_pricing_architecture", name="Aether Solution Package Pricing Architecture", description="Structure-first pricing architecture for platform access, usage, premium modules, deployments, services, and value-based context without exact dollar amounts.", base_platform_fee_notes="Platform access covers tenant access, SDK access, base graph, base Profile360, and base intelligence feed. Exact fees remain outside this contract unless an approved pricing config is introduced.", usage_dimensions=PRICING_DIMENSIONS, premium_modules=PREMIUM_MODULES, integration_pricing=["Integration pricing may account for connector count, delivery volume, and custom integration work."], deployment_pricing=DEPLOYMENT_PRICING, services_pricing=SERVICES_PRICING, value_based_pricing_notes=VALUE_BASED_NOTES, applicable_solution_packages=[p.package_id for p in SOLUTION_PACKAGES], status="internal_ready", created_at=STAMP, updated_at=STAMP)]

MATERIAL_SPECS = [
    ("master_aether_platform_one_pager", "Master Aether Platform One-Pager", "one_pager", [p.package_id for p in SOLUTION_PACKAGES], "enterprise", "sales_ready"),
    ("olympus_labs_company_one_pager", "Olympus Labs Company One-Pager", "one_pager", [p.package_id for p in SOLUTION_PACKAGES], "commercial", "sales_ready"),
    ("revenue_intelligence_graph_one_pager", "Revenue Intelligence Graph One-Pager", "one_pager", ["revenue_intelligence_graph"], "commercial", "sales_ready"),
    ("fraud_risk_intelligence_graph_one_pager", "Fraud & Risk Intelligence Graph One-Pager", "one_pager", ["fraud_risk_intelligence_graph"], "regulated", "internal_ready"),
    ("agent_governance_graph_one_pager", "Agent Governance Graph One-Pager", "one_pager", ["agent_governance_graph"], "regulated", "internal_ready"),
    ("operational_decision_intelligence_one_pager", "Operational Decision Intelligence One-Pager", "one_pager", ["operational_decision_intelligence"], "enterprise", "sales_ready"),
    ("program_integrity_graph_planning_brief", "Program Integrity Graph Planning Brief", "technical_brief", ["program_integrity_graph"], "government_planning", "internal_ready"),
    ("critical_infrastructure_coordination_planning_brief", "Critical Infrastructure Coordination Planning Brief", "technical_brief", ["critical_infrastructure_coordination_graph"], "government_planning", "internal_ready"),
    ("enterprise_technical_architecture_brief", "Enterprise Technical Architecture Brief", "technical_brief", [p.package_id for p in SOLUTION_PACKAGES], "enterprise", "internal_ready"),
    ("security_governance_brief", "Security & Governance Brief", "security_brief", [p.package_id for p in SOLUTION_PACKAGES], "regulated", "internal_ready"),
    ("audit_export_brief", "Audit Export Brief", "audit_brief", [p.package_id for p in SOLUTION_PACKAGES], "enterprise", "sales_ready"),
    ("pricing_architecture_sheet", "Pricing Architecture Sheet", "pricing_sheet", [p.package_id for p in SOLUTION_PACKAGES], "enterprise", "internal_ready"),
    ("roi_calculator", "ROI Calculator", "roi_calculator", ["revenue_intelligence_graph", "fraud_risk_intelligence_graph", "agent_governance_graph", "operational_decision_intelligence", "program_integrity_graph"], "enterprise", "internal_ready"),
    ("procurement_faq", "Procurement FAQ", "procurement_faq", [p.package_id for p in SOLUTION_PACKAGES], "enterprise", "internal_ready"),
    ("pilot_proposal_template", "Pilot Proposal Template", "pilot_proposal", [p.package_id for p in SOLUTION_PACKAGES], "enterprise", "internal_ready"),
    ("case_study_template", "Case Study Template", "case_study_template", [p.package_id for p in SOLUTION_PACKAGES], "commercial", "draft"),
    ("buyer_objection_handling_guide", "Buyer Objection Handling Guide", "objection_handling", [p.package_id for p in SOLUTION_PACKAGES], "enterprise", "internal_ready"),
]

GTM_MATERIALS: list[GTMMaterial] = [GTMMaterial(material_id=i, title=t, material_type=mt, solution_package_ids=pkgs, buyer_personas=[], market=m, status=st, content_blocks=["Position Aether as the tenant-facing product and Kyber as Olympus Labs' internal GTM/revenue command system.", "Use safe claims only: package mapping, auditability, human approvals, tenant isolation, and planning language where applicable.", "Do not claim certifications, authorizations, guaranteed ROI, or implemented self-hosting unless separately evidenced."], created_at=STAMP, updated_at=STAMP) for i,t,mt,pkgs,m,st in MATERIAL_SPECS]

PERSONA_TITLES = ["CMO", "CRO", "VP Growth", "RevOps", "Head of Customer Success", "Head of Risk", "Trust & Safety Lead", "Fraud Operations Lead", "Compliance Lead", "CTO", "AI Platform Lead", "Security Lead", "COO", "Chief Strategy Officer", "Program Integrity Lead", "Public Sector Technology Lead", "Critical Infrastructure Operator"]


def _persona_packages(title: str) -> list[str]:
    if title in {"CMO", "CRO", "VP Growth", "RevOps", "Head of Customer Success"}:
        return ["revenue_intelligence_graph", "operational_decision_intelligence"]
    if title in {"Head of Risk", "Trust & Safety Lead", "Fraud Operations Lead", "Compliance Lead"}:
        return ["fraud_risk_intelligence_graph", "agent_governance_graph"]
    if title in {"CTO", "AI Platform Lead", "Security Lead"}:
        return ["agent_governance_graph", "operational_decision_intelligence"]
    if title in {"Program Integrity Lead", "Public Sector Technology Lead"}:
        return ["program_integrity_graph", "agent_governance_graph"]
    if title == "Critical Infrastructure Operator":
        return ["critical_infrastructure_coordination_graph", "operational_decision_intelligence"]
    return ["operational_decision_intelligence", "revenue_intelligence_graph"]


def _persona_market(title: str) -> GTMMarket:
    if title in {"Program Integrity Lead", "Public Sector Technology Lead", "Critical Infrastructure Operator"}:
        return "government_planning"
    if title in {"Head of Risk", "Trust & Safety Lead", "Fraud Operations Lead", "Compliance Lead", "Security Lead"}:
        return "regulated"
    if title in {"CMO", "CRO", "VP Growth"}:
        return "commercial"
    return "enterprise"

BUYER_PERSONAS: list[BuyerPersona] = [BuyerPersona(persona_id=title.lower().replace(" & ", "_").replace(" ", "_"), title=title, market=_persona_market(title), pains=["Fragmented decision evidence", "Manual workflows and slow approvals", "Difficulty proving measurable value"], desired_outcomes=["Clear package-to-outcome mapping", "Auditable decisions and actions", "Tenant-safe operational visibility"], objections=["Need proof without compliance overclaim", "Need integration effort clarity", "Need pricing levers before pilot"], buying_triggers=["Board or executive pressure to show measurable outcomes", "Operational incident, revenue leakage, fraud loss, or AI governance gap", "New enterprise, regulated, or planning-stage procurement motion"], relevant_solution_packages=_persona_packages(title), recommended_collateral=["master_aether_platform_one_pager", "pricing_architecture_sheet", "roi_calculator", "security_governance_brief"], pricing_sensitivity="value proof and deployment complexity sensitive", proof_needed=["Outcome ledger examples", "Audit export samples", "Deployment readiness checklist", "ROI assumptions with disclaimer"]) for title in PERSONA_TITLES]

ROI_CALCULATORS: list[ROICalculatorDefinition] = [
    ROICalculatorDefinition(calculator_id="revenue_intelligence_roi", solution_package_id="revenue_intelligence_graph", inputs=["monthly revenue", "churn rate", "average order value", "customer lifetime value", "conversion rate", "campaign spend"], formulas=["retained revenue estimate = monthly revenue x churn improvement assumption", "expansion revenue estimate = customer lifetime value x conversion lift assumption", "campaign waste reduction estimate = campaign spend x waste reduction assumption"], outputs=["retained revenue estimate", "expansion revenue estimate", "campaign waste reduction estimate", "total estimated value"], assumptions=["Uses buyer-provided baselines", "Conservative lift assumptions must be documented"], disclaimer="ROI outputs are directional estimates for planning and are not guarantees.", status="internal_ready"),
    ROICalculatorDefinition(calculator_id="fraud_risk_roi", solution_package_id="fraud_risk_intelligence_graph", inputs=["monthly transaction volume", "estimated fraud loss", "manual review cost", "false positive rate", "reward abuse estimate"], formulas=["avoided loss = estimated fraud loss x detection improvement assumption", "review efficiency gain = manual review cost x automation/prioritization assumption", "false positive reduction value = transaction value x false positive improvement assumption"], outputs=["avoided loss", "review efficiency gain", "false positive reduction value", "total estimated value"], assumptions=["Requires customer loss and review baselines", "No prevented-fraud guarantee is implied"], disclaimer="Fraud and risk ROI is an estimate and not a guarantee of avoided loss.", status="internal_ready"),
    ROICalculatorDefinition(calculator_id="agent_governance_roi", solution_package_id="agent_governance_graph", inputs=["agent action volume", "failure rate", "average failure cost", "human review cost", "automation spend"], formulas=["failure cost reduction = agent action volume x failure rate x average failure cost x governance reduction assumption", "approval efficiency = reviewed actions x review cost reduction assumption", "governance value = failure reduction + approval efficiency"], outputs=["failure cost reduction", "approval efficiency", "governance value", "total estimated value"], assumptions=["Human approval controls remain configurable", "Agent incidents are buyer-provided estimates"], disclaimer="Governance ROI is directional and does not guarantee absence of agent failures.", status="internal_ready"),
    ROICalculatorDefinition(calculator_id="operational_decision_roi", solution_package_id="operational_decision_intelligence", inputs=["decision volume", "action completion rate", "average operational delay cost", "manual workflow hours", "playbook run volume"], formulas=["hours saved = manual workflow hours x automation/prioritization assumption", "delay cost reduction = decision volume x delay cost x completion improvement assumption", "outcome capture value = observed outcomes x attributable value assumption"], outputs=["hours saved", "delay cost reduction", "outcome capture value", "total estimated value"], assumptions=["Operational baselines come from customer data", "Outcome attribution must be reviewed"], disclaimer="Operational ROI estimates support planning and are not guaranteed results.", status="internal_ready"),
    ROICalculatorDefinition(calculator_id="program_integrity_planning_roi", solution_package_id="program_integrity_graph", inputs=["case volume", "improper payment estimate", "manual review cost", "review backlog"], formulas=["review prioritization value = case volume x prioritization improvement assumption", "avoided waste estimate = improper payment estimate x detection improvement assumption", "operational efficiency value = backlog x review cost reduction assumption"], outputs=["review prioritization value", "avoided waste estimate", "operational efficiency value"], assumptions=["Planning package only", "Requires agency/program validation before use in procurement"], disclaimer="Planning ROI is not a certification, authorization, or guaranteed savings claim.", status="internal_ready"),
]


def gtm_materials_for_package(package_id: str) -> list[GTMMaterial]:
    return [m for m in GTM_MATERIALS if package_id in m.solution_package_ids]


def personas_for_package(package_id: str) -> list[BuyerPersona]:
    return [p for p in BUYER_PERSONAS if package_id in p.relevant_solution_packages]


def roi_calculators_for_package(package_id: str) -> list[ROICalculatorDefinition]:
    return [c for c in ROI_CALCULATORS if c.solution_package_id == package_id]


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
