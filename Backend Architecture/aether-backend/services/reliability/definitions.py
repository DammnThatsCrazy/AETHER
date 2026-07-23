"""Static seed definitions for services, pipelines, queues, runbooks, and SLOs.

These describe the *shape* of the platform's reliability surface. Live values
(status, latency, error rate, etc.) are layered on top at read time. No external
SLA or certification is claimed here — SLO targets are internal objectives only.
"""
from __future__ import annotations

from services.reliability.models import (
    OperationalRunbook,
    ServiceLevelObjective,
    now_iso,
)

# ─────────────────────────────────────────────────────────────────────────────
# Services (Phase 2)
# ─────────────────────────────────────────────────────────────────────────────

SERVICE_DEFINITIONS: list[dict[str, str]] = [
    {"service_key": "ingestion", "label": "Event Ingestion"},
    {"service_key": "sdk_gateway", "label": "SDK Gateway"},
    {"service_key": "identity_resolution", "label": "Identity Resolution"},
    {"service_key": "profile360", "label": "Profile 360"},
    {"service_key": "graph_mutation", "label": "Graph Mutation"},
    {"service_key": "intelligence", "label": "Intelligence"},
    {"service_key": "recommendations", "label": "Recommendations"},
    {"service_key": "decisions", "label": "Decisions"},
    {"service_key": "actions", "label": "Actions"},
    {"service_key": "dispatches", "label": "Dispatches"},
    {"service_key": "outcomes", "label": "Outcomes"},
    {"service_key": "playbooks", "label": "Playbooks"},
    {"service_key": "audit_exports", "label": "Audit Exports"},
    {"service_key": "billing_metering", "label": "Billing Metering"},
    {"service_key": "security_audit", "label": "Security Audit"},
    {"service_key": "kyber_admin", "label": "Kyber Admin"},
    {"service_key": "aether_frontend", "label": "Aether Frontend"},
    {"service_key": "kyber_frontend", "label": "Kyber Frontend"},
    {"service_key": "semantic_intelligence", "label": "Semantic Intelligence"},
]

# ─────────────────────────────────────────────────────────────────────────────
# Pipelines (Phase 3)
# ─────────────────────────────────────────────────────────────────────────────

PIPELINE_DEFINITIONS: list[dict[str, str]] = [
    {"pipeline_key": "sdk_to_event_store", "label": "SDK event ingestion → event store", "source": "sdk_gateway", "destination": "ingestion"},
    {"pipeline_key": "event_store_to_identity", "label": "Event store → identity resolution", "source": "ingestion", "destination": "identity_resolution"},
    {"pipeline_key": "identity_to_graph", "label": "Identity resolution → graph mutation", "source": "identity_resolution", "destination": "graph_mutation"},
    {"pipeline_key": "graph_to_profile360", "label": "Graph mutation → Profile360", "source": "graph_mutation", "destination": "profile360"},
    {"pipeline_key": "profile360_to_recommendation", "label": "Profile360 → recommendation generation", "source": "profile360", "destination": "recommendations"},
    {"pipeline_key": "recommendation_to_decision", "label": "Recommendation → decision/action lifecycle", "source": "recommendations", "destination": "decisions"},
    {"pipeline_key": "action_to_dispatch", "label": "Action → dispatch", "source": "actions", "destination": "dispatches"},
    {"pipeline_key": "dispatch_to_outcome", "label": "Dispatch → outcome", "source": "dispatches", "destination": "outcomes"},
    {"pipeline_key": "outcome_to_confidence", "label": "Outcome → confidence update", "source": "outcomes", "destination": "intelligence"},
    {"pipeline_key": "outcome_to_ledger", "label": "Outcome → outcome ledger", "source": "outcomes", "destination": "outcomes"},
    {"pipeline_key": "usage_to_billing", "label": "Usage event → billing metering", "source": "ingestion", "destination": "billing_metering"},
    {"pipeline_key": "audit_to_ledger", "label": "Audit event → audit ledger", "source": "security_audit", "destination": "audit_exports"},
    {"pipeline_key": "event_to_semantic_classification", "label": "Validated event → semantic classification", "source": "ingestion", "destination": "semantic_intelligence"},
]

# ─────────────────────────────────────────────────────────────────────────────
# Queues / workers (Phase 4)
# ─────────────────────────────────────────────────────────────────────────────

QUEUE_DEFINITIONS: list[dict[str, str]] = [
    {"queue_key": "graph_mutations", "label": "Graph mutation workers"},
    {"queue_key": "recommendation_generation", "label": "Recommendation generation workers"},
    {"queue_key": "action_dispatch", "label": "Action dispatch workers"},
    {"queue_key": "audit_export_generation", "label": "Audit export generation workers"},
    {"queue_key": "billing_metering", "label": "Billing metering workers"},
    {"queue_key": "customer_success_triggers", "label": "Customer success trigger workers"},
    {"queue_key": "governance_evidence_packs", "label": "Governance evidence pack workers"},
]

# ─────────────────────────────────────────────────────────────────────────────
# Runbooks (Phase 6)
# ─────────────────────────────────────────────────────────────────────────────

def _runbook(
    runbook_id: str,
    title: str,
    incident_type: str,
    severity_hint: str,
    detection_signals: list[str],
    diagnostic_steps: list[str],
    mitigation_steps: list[str],
    escalation_paths: list[str],
    postmortem_required: bool,
    customer_comms_template: str | None = None,
) -> OperationalRunbook:
    ts = now_iso()
    return OperationalRunbook(
        runbook_id=runbook_id,
        title=title,
        incident_type=incident_type,
        severity_hint=severity_hint,  # type: ignore[arg-type]
        detection_signals=detection_signals,
        diagnostic_steps=diagnostic_steps,
        mitigation_steps=mitigation_steps,
        escalation_paths=escalation_paths,
        customer_comms_template=customer_comms_template,
        postmortem_required=postmortem_required,
        created_at=ts,
        updated_at=ts,
    )


RUNBOOK_DEFINITIONS: list[OperationalRunbook] = [
    _runbook(
        "rb_sdk_ingestion_degraded", "SDK Ingestion Degraded", "ingestion", "sev2",
        ["ingestion error rate > 5%", "sdk heartbeat gaps", "elevated ingest latency"],
        ["Check SDK gateway service health", "Inspect ingestion pipeline freshness", "Review recent SDK releases"],
        ["Scale ingestion workers", "Roll back faulty SDK config", "Enable backpressure"],
        ["on-call SRE", "ingestion service owner"],
        True,
        "We are investigating delayed data ingestion. Your historical data is safe; new events may appear with a short delay.",
    ),
    _runbook(
        "rb_event_schema_validation_spike", "Event Schema Validation Spike", "ingestion", "sev3",
        ["validation failure rate spike", "dead-letter growth on sdk_to_event_store"],
        ["Identify offending schema/version", "Diff against last known-good schema"],
        ["Pin schema version", "Coordinate SDK hotfix", "Drain dead-letter after fix"],
        ["on-call SRE", "SDK platform owner"],
        False,
    ),
    _runbook(
        "rb_identity_resolution_failure", "Identity Resolution Failure", "identity_resolution", "sev2",
        ["resolution error rate elevated", "identity pipeline backlog"],
        ["Check identity_resolution service", "Inspect event_store_to_identity pipeline"],
        ["Restart resolution workers", "Replay backlog", "Disable expensive matchers temporarily"],
        ["on-call SRE", "identity team"],
        True,
    ),
    _runbook(
        "rb_graph_mutation_backlog", "Graph Mutation Backlog", "graph_mutation", "sev2",
        ["graph_mutations queue depth high", "oldest message age rising"],
        ["Check graph mutation workers", "Inspect identity_to_graph pipeline freshness"],
        ["Scale graph workers", "Throttle producers", "Drain backlog in priority order"],
        ["on-call SRE", "graph platform owner"],
        True,
    ),
    _runbook(
        "rb_recommendation_generation_failure", "Recommendation Generation Failure", "recommendations", "sev3",
        ["recommendation generation errors", "profile360_to_recommendation freshness lag"],
        ["Check recommendations service", "Validate model/feature availability"],
        ["Restart recommendation workers", "Fall back to last-good model"],
        ["on-call SRE", "intelligence team"],
        False,
    ),
    _runbook(
        "rb_decision_action_lifecycle_failure", "Decision/Action Lifecycle Failure", "decisions", "sev3",
        ["decision lifecycle errors", "recommendation_to_decision stalls"],
        ["Inspect decision/action services", "Check approval workflow state"],
        ["Replay stuck decisions", "Clear poisoned actions"],
        ["on-call SRE", "decision intelligence team"],
        False,
    ),
    _runbook(
        "rb_action_dispatch_failure", "Action Dispatch Failure", "dispatches", "sev2",
        ["dispatch delivery failures", "action_dispatch dead-letter growth"],
        ["Check dispatch workers", "Inspect downstream integration health"],
        ["Retry failed dispatches", "Disable failing integration", "Notify affected tenants"],
        ["on-call SRE", "integrations team"],
        True,
        "Some outbound actions to your connected tools were delayed. We are retrying delivery automatically.",
    ),
    _runbook(
        "rb_outcome_feedback_failure", "Outcome Feedback Failure", "outcomes", "sev3",
        ["outcome capture rate drop", "dispatch_to_outcome freshness lag"],
        ["Check outcomes service", "Validate outcome ledger writes"],
        ["Replay outcome events", "Backfill confidence updates"],
        ["on-call SRE", "outcome intelligence team"],
        False,
    ),
    _runbook(
        "rb_audit_export_failure", "Audit Export Failure", "audit_exports", "sev2",
        ["audit export generation errors", "audit_export_generation queue stalls"],
        ["Check audit export workers", "Validate storage availability"],
        ["Retry failed exports", "Escalate to compliance owner"],
        ["on-call SRE", "compliance owner"],
        True,
        "Generation of your requested audit export is delayed. We will notify you when it is ready.",
    ),
    _runbook(
        "rb_billing_metering_failure", "Billing Metering Failure", "billing_metering", "sev2",
        ["billing metering freshness lag", "usage_to_billing dead-letter growth"],
        ["Check billing metering workers", "Reconcile usage event counts"],
        ["Replay usage events", "Reconcile before invoice run"],
        ["on-call SRE", "revenue operations"],
        True,
    ),
    _runbook(
        "rb_security_audit_event_failure", "Security Audit Event Failure", "security_audit", "sev1",
        ["audit event write failures", "audit_to_ledger gaps"],
        ["Check security audit sink", "Validate audit ledger integrity"],
        ["Buffer and replay audit events", "Preserve chain of custody", "Escalate immediately"],
        ["on-call SRE", "security owner", "compliance owner"],
        True,
    ),
    _runbook(
        "rb_kyber_dashboard_degraded", "Kyber Dashboard Degraded", "kyber_frontend", "sev3",
        ["kyber frontend errors", "kyber admin api latency"],
        ["Check kyber_frontend + kyber_admin services", "Inspect CDN/auth"],
        ["Roll back frontend deploy", "Scale admin API"],
        ["on-call SRE", "frontend owner"],
        False,
    ),
    _runbook(
        "rb_aether_tenant_app_degraded", "Aether Tenant App Degraded", "aether_frontend", "sev2",
        ["aether frontend errors", "tenant api latency"],
        ["Check aether_frontend service", "Inspect tenant API + auth"],
        ["Roll back frontend deploy", "Scale tenant API", "Post status update"],
        ["on-call SRE", "frontend owner"],
        True,
        "We are aware of slowness in the Aether app and are working to restore full performance.",
    ),
    # Registers the existing authored runbook:
    # docs/runbooks/semantic-sentiment/semantic-sentiment-operations.md
    _runbook(
        "rb_semantic_classification_degraded", "Semantic Classification Degraded", "semantic_intelligence", "sev3",
        ["semantic abstention rate elevated", "semantic review queue growth", "semantic classify latency p95 elevated"],
        ["Check /v1/kyber/semantic/fleet-health (model versions, abstention rate)", "Inspect event_to_semantic_classification pipeline freshness", "Follow docs/runbooks/semantic-sentiment/semantic-sentiment-operations.md"],
        ["Keep classification abstaining (fail closed) — never fabricate sentiment", "Throttle deep analysis before core ingestion", "Reprocess bounded tenant/time windows via dry-run replay after recovery"],
        ["on-call SRE", "semantic intelligence owner"],
        False,
    ),
]


# ─────────────────────────────────────────────────────────────────────────────
# SLOs (Phase 7) — internal objectives only, NOT external SLA commitments
# ─────────────────────────────────────────────────────────────────────────────

def _slo(slo_id: str, service_key: str, metric_key: str, target: float, window: str) -> ServiceLevelObjective:
    ts = now_iso()
    return ServiceLevelObjective(
        slo_id=slo_id,
        service_key=service_key,
        metric_key=metric_key,
        target=target,
        window=window,  # type: ignore[arg-type]
        created_at=ts,
        updated_at=ts,
    )


SLO_DEFINITIONS: list[ServiceLevelObjective] = [
    _slo("slo_api_availability", "kyber_admin", "availability_ratio", 0.999, "30d"),
    _slo("slo_sdk_ingestion_latency", "ingestion", "ingestion_latency_ms_p95", 500.0, "24h"),
    _slo("slo_event_to_graph_latency", "graph_mutation", "event_to_graph_latency_ms_p95", 2000.0, "24h"),
    _slo("slo_recommendation_latency", "recommendations", "generation_latency_ms_p95", 5000.0, "24h"),
    _slo("slo_action_dispatch_latency", "dispatches", "dispatch_delivery_latency_ms_p95", 10000.0, "24h"),
    _slo("slo_outcome_ledger_freshness", "outcomes", "ledger_freshness_seconds", 3600.0, "24h"),
    _slo("slo_audit_export_generation", "audit_exports", "export_generation_seconds_p95", 300.0, "7d"),
    _slo("slo_billing_metering_freshness", "billing_metering", "metering_freshness_seconds", 3600.0, "24h"),
    _slo("slo_kyber_dashboard_freshness", "kyber_frontend", "dashboard_freshness_seconds", 120.0, "1h"),
    # Semantic pipeline SLOs — sourced from the Prometheus series emitted by
    # services/semantic_intelligence:
    #   abstention_rate        ← aether_semantic_observations_abstained_total /
    #                            (…_classified_total + …_abstained_total)
    #   classify_latency_ms_p95← aether_semantic_classify_latency_ms histogram
    #   review_queue_depth     ← aether_semantic_review_queue_open gauge
    _slo("slo_semantic_abstention_rate", "semantic_intelligence", "abstention_rate", 0.25, "24h"),
    _slo("slo_semantic_classify_latency", "semantic_intelligence", "classify_latency_ms_p95", 1000.0, "24h"),
    _slo("slo_semantic_review_queue_depth", "semantic_intelligence", "review_queue_depth", 50.0, "24h"),
]

# Metrics where a LOWER value is better (latency/freshness/age/abstention/backlog).
# Availability and ratio metrics are "higher is better".
LOWER_IS_BETTER_SUFFIXES = ("latency_ms_p95", "_seconds", "_seconds_p95", "latency_ms", "_age", "_rate", "_depth")
