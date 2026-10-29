# DO NOT EDIT — generated from packages/shared/contracts/intelligence-projection-registry.json
# Run: python scripts/generate_platform_contracts.py
"""Generated intelligence-projection registry (360 projection plane)."""

from __future__ import annotations

INTELLIGENCE_PROJECTIONS_CONTRACT_VERSION = "1.0.0"

# Registered intelligence projections (sorted).
INTELLIGENCE_PROJECTION_IDS: tuple[str, ...] = (
    "agent360",
    "campaign360",
    "cluster360",
    "commerce360",
    "communication360",
    "connection360",
    "economic360",
    "episode360",
    "execution360",
    "fraud360",
    "geographic360",
    "infrastructure360",
    "memory360",
    "outcome360",
    "population360",
    "profile360",
    "relationship360",
    "risk360",
    "signals360",
    "social360",
    "source360",
    "support360",
    "temporal360",
    "workflow360",
)

# Projection kinds a 360 may be.
PROJECTION_KINDS: tuple[str, ...] = (
    "agentic_360",
    "context_360",
    "entity_360",
    "infrastructure_360",
    "measurement_360",
    "operational_workbench",
    "relationship_360",
    "risk_360",
    "sequence_360",
)

# Implementation states — repo metadata, NOT readiness.
PROJECTION_IMPLEMENTATION_STATES: tuple[str, ...] = (
    "deprecated",
    "implemented",
    "in_flight",
    "registered",
)

# Section states a projection result section may carry.
PROJECTION_SECTION_STATES: tuple[str, ...] = (
    "available",
    "degraded",
    "empty",
    "missing",
    "not_applicable",
    "stale",
    "suppressed",
    "unknown",
)

# Graph-mutation policies a projection may declare.
GRAPH_MUTATION_POLICIES: tuple[str, ...] = ("canonical_gateway_only", "read_only")

# Subject kinds a projection may be asked about.
PROJECTION_SUBJECT_KINDS: tuple[str, ...] = (
    "account",
    "account_member",
    "activity_window",
    "agent",
    "anonymous_subject",
    "automation",
    "callback",
    "campaign",
    "card",
    "checkout",
    "cluster",
    "commerce",
    "community",
    "connection",
    "contagion_path",
    "conversation",
    "conversion",
    "deployment",
    "entity",
    "episode",
    "event",
    "execution",
    "geohash",
    "infrastructure",
    "journey",
    "location",
    "memory",
    "message",
    "observation",
    "offer",
    "place",
    "population",
    "product",
    "profile",
    "region",
    "relationship",
    "risk",
    "run",
    "semantic_entity",
    "session",
    "signal",
    "sku",
    "source",
    "stream",
    "support_case",
    "syndicate",
    "thread",
    "ticket",
    "timezone",
    "topic",
    "trigger",
    "value",
    "workflow",
    "workflow_run",
    "workspace",
)

# Full projection definitions (sorted by projection id).
INTELLIGENCE_PROJECTION_DEFINITIONS: dict[str, dict] = {
    "agent360": {
        "id": "agent360",
        "displayName": "Agent 360",
        "projectionKind": "agentic_360",
        "implementationState": "in_flight",
        "implementationBlueprint": "docs/blueprints/agent360.md",
        "ownsCanonicalTruth": False,
        "subjectKinds": ("agent", "entity"),
        "canonicalAuthorities": ("agent_access", "agent_entities", "agent_entity", "agent_executions", "delegations", "economic_facts", "entities", "evidence", "graph", "identity", "observations", "outcome_facts", "social_observations", "source_provenance", "tools"),
        "hardDependencies": ("agentic_runtime_access", "contract_spine", "identity_resolution", "temporal_kernel"),
        "projectionDependencies": ("profile360",),
        "optionalProjectionDependencies": ("economic360", "outcome360"),
        "inputRefs": ("EntityRef", "EvidenceRef", "GraphResult", "PageRequest", "TimeRangeFilter"),
        "outputSections": ("evidence", "interactions", "outcomes", "policy_boundary", "state", "summary", "timeline"),
        "supportedTemporalModes": ("as_of", "relative", "window"),
        "surfaceIds": ("profile360",),
        "capabilityKeys": ("agent360.explore", "agent360.read"),
        "metricRefs": [],
        "graphMutationPolicy": "read_only",
        "requiresEvidence": True,
        "requiresDimensionState": True,
        "requiresFreshness": True,
        "requiresLimitations": True,
        "tenantScoped": True,
        "policyScoped": True,
        "readinessRequirements": {
            "requiresImplementation": True,
            "requiresDependencies": True,
            "requiresTenantEntitlement": True,
            "requiresProviderReadiness": False,
            "requiresEvidenceHealth": True
        },
        "security": {
            "tenantScoped": True,
            "requiresAuthorization": True,
            "requiresHistoricalConsentEvaluation": True,
            "exportClass": "governed",
            "distillationRisk": "moderate"
        },
        "costProfile": {
            "class": "moderate",
            "supportsAsync": False
        },
        "commercialClassification": {
            "sellableCapability": True,
            "meterRefs": [],
            "costClassRefs": []
        },
        "legacyBindings": {
            "routes": ("/v1/agent", "/v1/agents", "/v1/profile360"),
            "surfaceIds": ("profile360",),
            "services": ("services/api/actions/agent",),
            "migrationMode": "adapter",
            "migrationBlueprint": "docs/blueprints/agent360.md"
        },
        "deprecatedReason": None,
        "successorId": None,
        "pendingAuthority": [],
        "pendingReference": []
    },
    "campaign360": {
        "id": "campaign360",
        "displayName": "Campaign 360",
        "projectionKind": "measurement_360",
        "implementationState": "in_flight",
        "implementationBlueprint": "docs/blueprints/campaign360.md",
        "ownsCanonicalTruth": False,
        "subjectKinds": ("campaign", "episode", "population", "source"),
        "canonicalAuthorities": ("attribution_credits", "campaign_facts", "campaign_population_link_events", "campaign_touchpoints", "canonical_conversions", "cluster_definitions", "cluster_membership", "cohort_membership", "communication", "economic", "events", "evidence", "journeys", "observations", "outcomes", "population", "population_definitions", "relationship_facts", "risk_outputs", "source_facts", "source_provenance", "spend_records", "targeting_leakage_findings", "touchpoints"),
        "hardDependencies": ("attribution_architecture", "contract_spine", "measurement_outcome_contract"),
        "projectionDependencies": ("communication360", "economic360", "episode360", "outcome360", "population360"),
        "optionalProjectionDependencies": [],
        "inputRefs": ("EntityRef", "EvidenceRef", "FilterExpression", "GraphResult", "PageRequest", "TimeRangeFilter"),
        "outputSections": ("anomalies", "evidence", "findings", "outcomes", "state", "summary"),
        "supportedTemporalModes": ("compare", "relative", "window"),
        "surfaceIds": ("campaign360", "comparison_workbench"),
        "capabilityKeys": ("campaign360.explore", "campaign360.read"),
        "metricRefs": ("attributed_conversions", "conversion_rate", "revenue", "touchpoints"),
        "graphMutationPolicy": "canonical_gateway_only",
        "requiresEvidence": True,
        "requiresDimensionState": True,
        "requiresFreshness": True,
        "requiresLimitations": True,
        "tenantScoped": True,
        "policyScoped": True,
        "readinessRequirements": {
            "requiresImplementation": True,
            "requiresDependencies": True,
            "requiresTenantEntitlement": True,
            "requiresProviderReadiness": False,
            "requiresEvidenceHealth": True
        },
        "security": {
            "tenantScoped": True,
            "requiresAuthorization": True,
            "requiresHistoricalConsentEvaluation": False,
            "exportClass": "governed",
            "distillationRisk": "high"
        },
        "costProfile": {
            "class": "heavy",
            "supportsAsync": True
        },
        "commercialClassification": {
            "sellableCapability": True,
            "meterRefs": [],
            "costClassRefs": []
        },
        "legacyBindings": {
            "routes": ("/v1/campaign-quality", "/v1/campaign-sources", "/v1/campaigns", "/v1/mapping-review"),
            "surfaceIds": ("campaign360", "comparison_workbench"),
            "services": ("services/api/journeys/campaign",),
            "migrationMode": "adapter",
            "migrationBlueprint": "docs/blueprints/campaign360.md"
        },
        "deprecatedReason": None,
        "successorId": None,
        "pendingAuthority": [],
        "pendingReference": []
    },
    "cluster360": {
        "id": "cluster360",
        "displayName": "Cluster 360",
        "projectionKind": "operational_workbench",
        "implementationState": "in_flight",
        "implementationBlueprint": "docs/blueprints/cluster360.md",
        "ownsCanonicalTruth": False,
        "subjectKinds": ("cluster", "entity", "population"),
        "canonicalAuthorities": ("cluster_definitions", "cluster_membership", "computation", "graph", "population"),
        "hardDependencies": ("computation_substrate", "exploration_fabric"),
        "projectionDependencies": ("population360",),
        "optionalProjectionDependencies": [],
        "inputRefs": ("EntityRef", "FilterExpression", "GraphResult", "PageRequest", "TimeRangeFilter"),
        "outputSections": ("evidence", "findings", "health", "state", "summary"),
        "supportedTemporalModes": ("as_of", "window"),
        "surfaceIds": ("cluster360", "graph"),
        "capabilityKeys": ("cluster360.explore", "cluster360.read"),
        "metricRefs": [],
        "graphMutationPolicy": "read_only",
        "requiresEvidence": True,
        "requiresDimensionState": True,
        "requiresFreshness": True,
        "requiresLimitations": True,
        "tenantScoped": True,
        "policyScoped": True,
        "readinessRequirements": {
            "requiresImplementation": True,
            "requiresDependencies": True,
            "requiresTenantEntitlement": True,
            "requiresProviderReadiness": False,
            "requiresEvidenceHealth": True
        },
        "security": {
            "tenantScoped": True,
            "requiresAuthorization": True,
            "requiresHistoricalConsentEvaluation": False,
            "exportClass": "governed",
            "distillationRisk": "moderate"
        },
        "costProfile": {
            "class": "heavy",
            "supportsAsync": True
        },
        "commercialClassification": {
            "sellableCapability": True,
            "meterRefs": [],
            "costClassRefs": []
        },
        "legacyBindings": {
            "routes": ("/v1/clusters",),
            "surfaceIds": ("cluster360", "graph"),
            "services": ("services/api/graph/cluster",),
            "migrationMode": "adapter",
            "migrationBlueprint": "docs/blueprints/cluster360.md"
        },
        "deprecatedReason": None,
        "successorId": None,
        "pendingAuthority": [],
        "pendingReference": []
    },
    "commerce360": {
        "id": "commerce360",
        "displayName": "Commerce 360",
        "projectionKind": "context_360",
        "implementationState": "in_flight",
        "implementationBlueprint": "docs/reference/source-of-truth/AETHER_360_BACKEND_SINGLE_SOURCE_OF_TRUTH.md",
        "ownsCanonicalTruth": False,
        "subjectKinds": ("campaign", "checkout", "commerce", "entity", "journey", "offer", "product", "sku"),
        "canonicalAuthorities": ("campaign_facts", "commerce", "commerce_intent_authority", "commerce_product_offer_graph", "payments", "risk_outputs", "silver_commerce_flow_facts", "silver_exposure_facts", "source_provenance"),
        "hardDependencies": ("contract_spine",),
        "projectionDependencies": [],
        "optionalProjectionDependencies": [],
        "inputRefs": ("EntityRef", "EvidenceRef", "PageRequest", "TimeRangeFilter"),
        "outputSections": ("availability_price", "campaign_links", "cart_checkout", "catalog_links", "evidence_trace", "exposures", "intent", "product_offer_summary", "purchase", "risk", "value"),
        "supportedTemporalModes": ("window",),
        "surfaceIds": ("product_intelligence",),
        "capabilityKeys": ("commerce360.read",),
        "metricRefs": [],
        "graphMutationPolicy": "read_only",
        "requiresEvidence": True,
        "requiresDimensionState": True,
        "requiresFreshness": True,
        "requiresLimitations": True,
        "tenantScoped": True,
        "policyScoped": True,
        "readinessRequirements": {
            "requiresImplementation": True,
            "requiresDependencies": True,
            "requiresTenantEntitlement": True,
            "requiresProviderReadiness": False,
            "requiresEvidenceHealth": True
        },
        "security": {
            "tenantScoped": True,
            "requiresAuthorization": True,
            "requiresHistoricalConsentEvaluation": True,
            "exportClass": "governed",
            "distillationRisk": "moderate"
        },
        "costProfile": {
            "class": "moderate",
            "supportsAsync": False
        },
        "commercialClassification": {
            "sellableCapability": False,
            "meterRefs": [],
            "costClassRefs": []
        },
        "legacyBindings": {
            "routes": ("/v1/experience360/frames",),
            "surfaceIds": ("product_intelligence",),
            "services": ("services/api/value/commerce",),
            "migrationMode": "adapter",
            "migrationBlueprint": "docs/reference/source-of-truth/AETHER_360_BACKEND_SINGLE_SOURCE_OF_TRUTH.md"
        },
        "deprecatedReason": None,
        "successorId": None,
        "pendingAuthority": [],
        "pendingReference": []
    },
    "communication360": {
        "id": "communication360",
        "displayName": "Communication 360",
        "projectionKind": "sequence_360",
        "implementationState": "implemented",
        "implementationBlueprint": "docs/architecture/blueprints/communication360.md",
        "ownsCanonicalTruth": False,
        "subjectKinds": ("agent", "campaign", "entity", "episode", "journey", "source"),
        "canonicalAuthorities": ("campaign_touchpoints", "communication", "communication_facts", "consent_policy_decisions", "delegations", "entities", "entity_registry", "evidence", "identity", "journeys", "outcomes", "risk_assessments", "risk_outputs", "risk_signals"),
        "hardDependencies": ("contract_spine", "temporal_kernel"),
        "projectionDependencies": ("episode360", "outcome360", "profile360", "relationship360"),
        "optionalProjectionDependencies": [],
        "inputRefs": ("EntityRef", "EvidenceRef", "GraphSnapshotRef", "PageRequest", "RelationshipRef", "TimeRangeFilter"),
        "outputSections": ("evidence", "interactions", "outcomes", "state", "summary", "timeline"),
        "supportedTemporalModes": ("as_of", "relative", "window"),
        "surfaceIds": ("profile360", "timeline"),
        "capabilityKeys": ("communication360.explore", "communication360.read"),
        "metricRefs": ("citation_retention_rate", "claim_retention_rate", "contradiction_rate", "email_click_rate", "email_open_rate", "email_reply_rate", "evidence_retention_rate", "omission_rate", "semantic_drift", "unsupported_addition_rate"),
        "graphMutationPolicy": "read_only",
        "requiresEvidence": True,
        "requiresDimensionState": True,
        "requiresFreshness": True,
        "requiresLimitations": True,
        "tenantScoped": True,
        "policyScoped": True,
        "readinessRequirements": {
            "requiresImplementation": True,
            "requiresDependencies": True,
            "requiresTenantEntitlement": True,
            "requiresProviderReadiness": False,
            "requiresEvidenceHealth": True
        },
        "security": {
            "tenantScoped": True,
            "requiresAuthorization": True,
            "requiresHistoricalConsentEvaluation": True,
            "exportClass": "governed",
            "distillationRisk": "moderate"
        },
        "costProfile": {
            "class": "moderate",
            "supportsAsync": False
        },
        "commercialClassification": {
            "sellableCapability": True,
            "meterRefs": [],
            "costClassRefs": []
        },
        "legacyBindings": {
            "routes": ("/v1/comms", "/v1/contact", "/v1/delivery", "/v1/notifications"),
            "surfaceIds": ("profile360", "timeline"),
            "services": ("services/api/journeys/comms",),
            "migrationMode": "converged",
            "migrationBlueprint": "docs/architecture/blueprints/communication360.md"
        },
        "deprecatedReason": None,
        "successorId": None,
        "pendingAuthority": [],
        "pendingReference": []
    },
    "connection360": {
        "id": "connection360",
        "displayName": "Connection 360",
        "projectionKind": "operational_workbench",
        "implementationState": "in_flight",
        "implementationBlueprint": "docs/blueprints/connection360.md",
        "ownsCanonicalTruth": False,
        "subjectKinds": ("connection", "source"),
        "canonicalAuthorities": ("connection_config", "connection_permissions", "credential_readiness", "managed_integration_lifecycle", "provider_health", "source_coverage", "sync_state"),
        "hardDependencies": ("reconciled_control_plane", "upr"),
        "projectionDependencies": ("source360",),
        "optionalProjectionDependencies": [],
        "inputRefs": ("EntityRef", "EvidenceRef", "MutationIntent", "PageRequest", "TimeRangeFilter"),
        "outputSections": ("coverage", "evidence", "health", "state", "summary"),
        "supportedTemporalModes": ("as_of", "relative", "window"),
        "surfaceIds": ("connection360",),
        "capabilityKeys": ("connection360.explore", "connection360.read"),
        "metricRefs": [],
        "graphMutationPolicy": "canonical_gateway_only",
        "requiresEvidence": True,
        "requiresDimensionState": True,
        "requiresFreshness": True,
        "requiresLimitations": True,
        "tenantScoped": True,
        "policyScoped": True,
        "readinessRequirements": {
            "requiresImplementation": True,
            "requiresDependencies": True,
            "requiresTenantEntitlement": True,
            "requiresProviderReadiness": False,
            "requiresEvidenceHealth": True
        },
        "security": {
            "tenantScoped": True,
            "requiresAuthorization": True,
            "requiresHistoricalConsentEvaluation": False,
            "exportClass": "governed",
            "distillationRisk": "moderate"
        },
        "costProfile": {
            "class": "moderate",
            "supportsAsync": False
        },
        "commercialClassification": {
            "sellableCapability": True,
            "meterRefs": [],
            "costClassRefs": []
        },
        "legacyBindings": {
            "routes": ("/v1/client-sync", "/v1/integrations", "/v1/provider-connections"),
            "surfaceIds": ("connection360",),
            "services": ("services/api/connectors/provider_runtime",),
            "migrationMode": "adapter",
            "migrationBlueprint": "docs/blueprints/connection360.md"
        },
        "deprecatedReason": None,
        "successorId": None,
        "pendingAuthority": [
            {
                "id": "reconciled_control_plane",
                "kind": "spine",
                "reason": "harness control-plane rollup (PR #529) merged; reconciled control-plane spine not yet formalized as a projection-plane authority",
                "resolvesInProjection": "connection360"
            }
        ],
        "pendingReference": []
    },
    "economic360": {
        "id": "economic360",
        "displayName": "Value 360",
        "projectionKind": "measurement_360",
        "implementationState": "implemented",
        "implementationBlueprint": "docs/architecture/blueprints/economic360.md",
        "ownsCanonicalTruth": False,
        "subjectKinds": ("account", "agent", "campaign", "cluster", "conversion", "entity", "episode", "journey", "profile", "source"),
        "canonicalAuthorities": ("ai_execution_facts", "attribution_credits", "attribution_runs", "campaign_touchpoints", "canonical_activity", "canonical_conversions", "commerce", "commerce_order_payment_ledger", "currency_value_normalization", "economic_facts", "entity_registry", "evidence", "graph", "identity_clusters_v2", "journey_steps", "outcome_facts", "payments", "revenue_adjustments"),
        "hardDependencies": ("measurement_outcome_contract", "temporal_kernel"),
        "projectionDependencies": ("outcome360", "profile360", "relationship360"),
        "optionalProjectionDependencies": [],
        "inputRefs": ("EntityRef", "EvidenceRef", "FilterExpression", "GraphResult", "PageRequest", "TimeRangeFilter"),
        "outputSections": ("evidence", "findings", "outcomes", "state", "summary"),
        "supportedTemporalModes": ("compare", "relative", "window"),
        "surfaceIds": ("campaign360", "economic360", "product_intelligence"),
        "capabilityKeys": ("economic360.explore", "economic360.read"),
        "metricRefs": ("agent_execution_cost", "ai_execution_cost", "campaign_cac", "campaign_ltv", "campaign_roas", "campaign_spend", "entity_execution_cost", "revenue"),
        "graphMutationPolicy": "read_only",
        "requiresEvidence": True,
        "requiresDimensionState": True,
        "requiresFreshness": True,
        "requiresLimitations": True,
        "tenantScoped": True,
        "policyScoped": True,
        "readinessRequirements": {
            "requiresImplementation": True,
            "requiresDependencies": True,
            "requiresTenantEntitlement": True,
            "requiresProviderReadiness": False,
            "requiresEvidenceHealth": True
        },
        "security": {
            "tenantScoped": True,
            "requiresAuthorization": True,
            "requiresHistoricalConsentEvaluation": True,
            "exportClass": "governed",
            "distillationRisk": "high"
        },
        "costProfile": {
            "class": "heavy",
            "supportsAsync": True
        },
        "commercialClassification": {
            "sellableCapability": True,
            "meterRefs": [],
            "costClassRefs": []
        },
        "legacyBindings": {
            "routes": ("/v1/economic", "/v1/profile"),
            "surfaceIds": ("campaign360", "economic360", "product_intelligence"),
            "services": ("services/api/value/economic",),
            "migrationMode": "converged",
            "migrationBlueprint": "docs/architecture/blueprints/economic360.md"
        },
        "deprecatedReason": None,
        "successorId": None,
        "pendingAuthority": [],
        "pendingReference": []
    },
    "episode360": {
        "id": "episode360",
        "displayName": "Episode 360",
        "projectionKind": "sequence_360",
        "implementationState": "in_flight",
        "implementationBlueprint": "docs/blueprints/episode360.md",
        "ownsCanonicalTruth": False,
        "subjectKinds": ("campaign", "entity", "episode", "journey"),
        "canonicalAuthorities": ("agent_executions", "attribution_credits", "attribution_runs", "campaign_touchpoints", "canonical_conversions", "delegations", "episode_facts", "episode_journey_authority_records", "events", "evidence", "graph", "journeys", "outcome_facts", "risk_signals", "silver_semantic_observations", "temporal", "touchpoints"),
        "hardDependencies": ("contract_spine", "journey_continuity", "temporal_kernel"),
        "projectionDependencies": ("profile360", "relationship360"),
        "optionalProjectionDependencies": [],
        "inputRefs": ("EntityRef", "EvidenceRef", "GraphSnapshotRef", "PageRequest", "RelationshipRef", "TimeRangeFilter"),
        "outputSections": ("episode_context", "evidence", "interactions", "journey_attribution", "outcomes", "risk_flags", "stages", "state", "summary", "timeline"),
        "supportedTemporalModes": ("relative", "window"),
        "surfaceIds": ("journeys", "timeline"),
        "capabilityKeys": ("episode360.explore", "episode360.read"),
        "metricRefs": [],
        "graphMutationPolicy": "read_only",
        "requiresEvidence": True,
        "requiresDimensionState": True,
        "requiresFreshness": True,
        "requiresLimitations": True,
        "tenantScoped": True,
        "policyScoped": True,
        "readinessRequirements": {
            "requiresImplementation": True,
            "requiresDependencies": True,
            "requiresTenantEntitlement": True,
            "requiresProviderReadiness": False,
            "requiresEvidenceHealth": True
        },
        "security": {
            "tenantScoped": True,
            "requiresAuthorization": True,
            "requiresHistoricalConsentEvaluation": False,
            "exportClass": "governed",
            "distillationRisk": "moderate"
        },
        "costProfile": {
            "class": "moderate",
            "supportsAsync": False
        },
        "commercialClassification": {
            "sellableCapability": True,
            "meterRefs": [],
            "costClassRefs": []
        },
        "legacyBindings": {
            "routes": ("/v1/events", "/v1/journeys"),
            "surfaceIds": ("journeys", "timeline"),
            "services": ("services/api/ingestion/events", "services/api/journeys/journeys"),
            "migrationMode": "adapter",
            "migrationBlueprint": "docs/blueprints/episode360.md"
        },
        "deprecatedReason": None,
        "successorId": None,
        "pendingAuthority": [
            {
                "id": "journey_continuity",
                "kind": "spine",
                "reason": "journey continuity plane not yet formalized",
                "resolvesInProjection": "episode360"
            }
        ],
        "pendingReference": []
    },
    "execution360": {
        "id": "execution360",
        "displayName": "Execution 360",
        "projectionKind": "sequence_360",
        "implementationState": "in_flight",
        "implementationBlueprint": "docs/blueprints/execution360.md",
        "ownsCanonicalTruth": False,
        "subjectKinds": ("agent", "entity", "episode", "execution", "workflow_run"),
        "canonicalAuthorities": ("actions", "agent_access", "agent_entities", "agent_executions", "ai_execution_facts", "commerce", "economic_facts", "entity_registry", "episode_facts", "events", "evidence", "execution_facts", "graph", "identity", "outcome_facts", "resources", "risk_assessments", "risk_signals", "source_provenance", "temporal_kernel", "tools"),
        "hardDependencies": ("agentic_runtime_access", "temporal_kernel"),
        "projectionDependencies": ("agent360", "episode360", "outcome360", "temporal360"),
        "optionalProjectionDependencies": [],
        "inputRefs": ("EntityRef", "EvidenceRef", "GraphSnapshotRef", "PageRequest", "RelationshipRef", "TimeRangeFilter"),
        "outputSections": ("episode_context", "evidence", "interactions", "outcomes", "state", "summary", "timeline"),
        "supportedTemporalModes": ("as_of", "relative", "window"),
        "surfaceIds": ("timeline",),
        "capabilityKeys": ("execution360.explore", "execution360.read"),
        "metricRefs": [],
        "graphMutationPolicy": "read_only",
        "requiresEvidence": True,
        "requiresDimensionState": True,
        "requiresFreshness": True,
        "requiresLimitations": True,
        "tenantScoped": True,
        "policyScoped": True,
        "readinessRequirements": {
            "requiresImplementation": True,
            "requiresDependencies": True,
            "requiresTenantEntitlement": True,
            "requiresProviderReadiness": False,
            "requiresEvidenceHealth": True
        },
        "security": {
            "tenantScoped": True,
            "requiresAuthorization": True,
            "requiresHistoricalConsentEvaluation": False,
            "exportClass": "governed",
            "distillationRisk": "moderate"
        },
        "costProfile": {
            "class": "heavy",
            "supportsAsync": True
        },
        "commercialClassification": {
            "sellableCapability": True,
            "meterRefs": [],
            "costClassRefs": []
        },
        "legacyBindings": {
            "routes": ("/v1/agent", "/v1/agents", "/v1/computations", "/v1/flows", "/v1/jobs"),
            "surfaceIds": ("timeline",),
            "services": ("services/api/actions/agent", "services/api/value/flows", "services/api/workers/jobs"),
            "migrationMode": "adapter",
            "migrationBlueprint": "docs/blueprints/execution360.md"
        },
        "deprecatedReason": None,
        "successorId": None,
        "pendingAuthority": [],
        "pendingReference": []
    },
    "fraud360": {
        "id": "fraud360",
        "displayName": "Fraud 360",
        "projectionKind": "risk_360",
        "implementationState": "implemented",
        "implementationBlueprint": "docs/architecture/blueprints/fraud360.md",
        "ownsCanonicalTruth": False,
        "subjectKinds": ("agent", "entity", "relationship"),
        "canonicalAuthorities": ("economic_facts", "evidence", "execution_facts", "fraud_synthesis", "graph_motifs", "identity", "relationship_facts", "risk_outputs", "social_observations"),
        "hardDependencies": ("evidence_provenance", "model_governance"),
        "projectionDependencies": ("profile360", "risk360"),
        "optionalProjectionDependencies": [],
        "inputRefs": ("EntityRef", "EvidenceRef", "FilterExpression", "GraphSnapshotRef", "PageRequest", "RelationshipRef", "TimeRangeFilter"),
        "outputSections": ("evidence", "findings", "health", "state", "summary"),
        "supportedTemporalModes": ("as_of", "relative", "window"),
        "surfaceIds": ("fraud360", "graph"),
        "capabilityKeys": ("fraud360.explore", "fraud360.read"),
        "metricRefs": [],
        "graphMutationPolicy": "read_only",
        "requiresEvidence": True,
        "requiresDimensionState": True,
        "requiresFreshness": True,
        "requiresLimitations": True,
        "tenantScoped": True,
        "policyScoped": True,
        "readinessRequirements": {
            "requiresImplementation": True,
            "requiresDependencies": True,
            "requiresTenantEntitlement": True,
            "requiresProviderReadiness": False,
            "requiresEvidenceHealth": True
        },
        "security": {
            "tenantScoped": True,
            "requiresAuthorization": True,
            "requiresHistoricalConsentEvaluation": True,
            "exportClass": "governed",
            "distillationRisk": "high"
        },
        "costProfile": {
            "class": "heavy",
            "supportsAsync": True
        },
        "commercialClassification": {
            "sellableCapability": True,
            "meterRefs": [],
            "costClassRefs": []
        },
        "legacyBindings": {
            "routes": ("/v1/fraud",),
            "surfaceIds": ("fraud360", "graph"),
            "services": ("services/api/intelligence/fraud",),
            "migrationMode": "converged",
            "migrationBlueprint": "docs/architecture/blueprints/fraud360.md"
        },
        "deprecatedReason": None,
        "successorId": None,
        "pendingAuthority": [],
        "pendingReference": []
    },
    "geographic360": {
        "id": "geographic360",
        "displayName": "Geographic 360",
        "projectionKind": "context_360",
        "implementationState": "implemented",
        "implementationBlueprint": "docs/architecture/blueprints/geographic360.md",
        "ownsCanonicalTruth": False,
        "subjectKinds": ("entity", "population", "source"),
        "canonicalAuthorities": ("campaign_facts", "context_capsules", "economic_facts", "entity_graph", "geo_observations", "geo_temporal_timezone_assertions", "gold_temporal_heatmap", "identity", "journeys", "locations", "risk_outputs", "risk_signals", "temporal"),
        "hardDependencies": ("context_capsule_semantics", "temporal_kernel"),
        "projectionDependencies": ("profile360", "temporal360"),
        "optionalProjectionDependencies": [],
        "inputRefs": ("EntityRef", "GraphSnapshotRef", "PageRequest", "TimeRangeFilter"),
        "outputSections": ("evidence", "findings", "normalization", "state", "summary", "timeline"),
        "supportedTemporalModes": ("compare", "relative", "window"),
        "surfaceIds": ("geographic360",),
        "capabilityKeys": ("geographic360.explore", "geographic360.read"),
        "metricRefs": [],
        "graphMutationPolicy": "read_only",
        "requiresEvidence": True,
        "requiresDimensionState": True,
        "requiresFreshness": True,
        "requiresLimitations": True,
        "tenantScoped": True,
        "policyScoped": True,
        "readinessRequirements": {
            "requiresImplementation": True,
            "requiresDependencies": True,
            "requiresTenantEntitlement": True,
            "requiresProviderReadiness": False,
            "requiresEvidenceHealth": True
        },
        "security": {
            "tenantScoped": True,
            "requiresAuthorization": True,
            "requiresHistoricalConsentEvaluation": False,
            "exportClass": "governed",
            "distillationRisk": "moderate"
        },
        "costProfile": {
            "class": "moderate",
            "supportsAsync": False
        },
        "commercialClassification": {
            "sellableCapability": True,
            "meterRefs": [],
            "costClassRefs": []
        },
        "legacyBindings": {
            "routes": ("/v1/geo",),
            "surfaceIds": ("geographic360",),
            "services": ("services/api/graph/geo",),
            "migrationMode": "converged",
            "migrationBlueprint": "docs/architecture/blueprints/geographic360.md"
        },
        "deprecatedReason": None,
        "successorId": None,
        "pendingAuthority": [],
        "pendingReference": []
    },
    "infrastructure360": {
        "id": "infrastructure360",
        "displayName": "Infrastructure 360",
        "projectionKind": "infrastructure_360",
        "implementationState": "implemented",
        "implementationBlueprint": "docs/architecture/blueprints/infrastructure360.md",
        "ownsCanonicalTruth": False,
        "subjectKinds": ("deployment", "infrastructure"),
        "canonicalAuthorities": ("deployments", "infrastructure_facts", "infrastructure_state"),
        "hardDependencies": ("contract_spine", "infrastructure_model", "temporal_kernel"),
        "projectionDependencies": [],
        "optionalProjectionDependencies": [],
        "inputRefs": ("EntityRef", "EvidenceRef", "PageRequest", "TimeRangeFilter"),
        "outputSections": ("deployments", "evidence", "findings", "state", "summary"),
        "supportedTemporalModes": ("as_of", "compare", "relative", "window"),
        "surfaceIds": ("infrastructure360",),
        "capabilityKeys": ("infrastructure360.explore", "infrastructure360.read"),
        "metricRefs": [],
        "graphMutationPolicy": "read_only",
        "requiresEvidence": True,
        "requiresDimensionState": True,
        "requiresFreshness": True,
        "requiresLimitations": True,
        "tenantScoped": True,
        "policyScoped": True,
        "readinessRequirements": {
            "requiresImplementation": True,
            "requiresDependencies": True,
            "requiresTenantEntitlement": True,
            "requiresProviderReadiness": False,
            "requiresEvidenceHealth": True
        },
        "security": {
            "tenantScoped": True,
            "requiresAuthorization": True,
            "requiresHistoricalConsentEvaluation": False,
            "exportClass": "governed",
            "distillationRisk": "moderate"
        },
        "costProfile": {
            "class": "moderate",
            "supportsAsync": False
        },
        "commercialClassification": {
            "sellableCapability": True,
            "meterRefs": [],
            "costClassRefs": []
        },
        "legacyBindings": {
            "routes": ("/v1/infrastructure",),
            "surfaceIds": ("infrastructure360",),
            "services": ("services/api/graph/infrastructure",),
            "migrationMode": "converged",
            "migrationBlueprint": "docs/architecture/blueprints/infrastructure360.md"
        },
        "deprecatedReason": None,
        "successorId": None,
        "pendingAuthority": [],
        "pendingReference": []
    },
    "memory360": {
        "id": "memory360",
        "displayName": "Memory 360",
        "projectionKind": "context_360",
        "implementationState": "in_flight",
        "implementationBlueprint": "docs/reference/source-of-truth/AETHER_360_BACKEND_SINGLE_SOURCE_OF_TRUTH.md",
        "ownsCanonicalTruth": False,
        "subjectKinds": ("card", "entity", "memory", "semantic_entity", "topic"),
        "canonicalAuthorities": ("consent_policy_decisions", "evidence", "semantic_context_cards", "semantic_embedding_metadata", "semantic_memory_graph", "semantic_memory_records", "silver_semantic_observations", "source_provenance"),
        "hardDependencies": ("contract_spine",),
        "projectionDependencies": [],
        "optionalProjectionDependencies": [],
        "inputRefs": ("EntityRef", "EvidenceRef", "PageRequest", "TimeRangeFilter"),
        "outputSections": ("cards", "conflicts", "decay", "embeddings_meta", "evidence_trace", "memories", "policy_state", "semantic_summary", "source_links", "topics"),
        "supportedTemporalModes": ("window",),
        "surfaceIds": ("profile360",),
        "capabilityKeys": ("memory360.read",),
        "metricRefs": [],
        "graphMutationPolicy": "read_only",
        "requiresEvidence": True,
        "requiresDimensionState": True,
        "requiresFreshness": True,
        "requiresLimitations": True,
        "tenantScoped": True,
        "policyScoped": True,
        "readinessRequirements": {
            "requiresImplementation": True,
            "requiresDependencies": True,
            "requiresTenantEntitlement": True,
            "requiresProviderReadiness": False,
            "requiresEvidenceHealth": True
        },
        "security": {
            "tenantScoped": True,
            "requiresAuthorization": True,
            "requiresHistoricalConsentEvaluation": True,
            "exportClass": "governed",
            "distillationRisk": "moderate"
        },
        "costProfile": {
            "class": "moderate",
            "supportsAsync": False
        },
        "commercialClassification": {
            "sellableCapability": False,
            "meterRefs": [],
            "costClassRefs": []
        },
        "legacyBindings": {
            "routes": ("/v1/experience360/frames",),
            "surfaceIds": ("profile360",),
            "services": ("services/api/intelligence/semantic_intelligence",),
            "migrationMode": "adapter",
            "migrationBlueprint": "docs/reference/source-of-truth/AETHER_360_BACKEND_SINGLE_SOURCE_OF_TRUTH.md"
        },
        "deprecatedReason": None,
        "successorId": None,
        "pendingAuthority": [],
        "pendingReference": []
    },
    "outcome360": {
        "id": "outcome360",
        "displayName": "Outcome 360",
        "projectionKind": "measurement_360",
        "implementationState": "implemented",
        "implementationBlueprint": "docs/architecture/blueprints/outcome360.md",
        "ownsCanonicalTruth": False,
        "subjectKinds": ("agent", "campaign", "episode", "journey", "population"),
        "canonicalAuthorities": ("evidence", "graph", "measurement_contract", "outcome_facts"),
        "hardDependencies": ("measurement_outcome_contract", "temporal_kernel"),
        "projectionDependencies": ("temporal360",),
        "optionalProjectionDependencies": [],
        "inputRefs": ("EntityRef", "EvidenceRef", "FilterExpression", "GraphResult", "PageRequest", "TimeRangeFilter"),
        "outputSections": ("evidence", "findings", "outcomes", "state", "summary"),
        "supportedTemporalModes": ("compare", "relative", "window"),
        "surfaceIds": ("campaign360", "outcome360"),
        "capabilityKeys": ("outcome360.explore", "outcome360.read"),
        "metricRefs": ("journey_completion_rate",),
        "graphMutationPolicy": "read_only",
        "requiresEvidence": True,
        "requiresDimensionState": True,
        "requiresFreshness": True,
        "requiresLimitations": True,
        "tenantScoped": True,
        "policyScoped": True,
        "readinessRequirements": {
            "requiresImplementation": True,
            "requiresDependencies": True,
            "requiresTenantEntitlement": True,
            "requiresProviderReadiness": False,
            "requiresEvidenceHealth": True
        },
        "security": {
            "tenantScoped": True,
            "requiresAuthorization": True,
            "requiresHistoricalConsentEvaluation": False,
            "exportClass": "governed",
            "distillationRisk": "high"
        },
        "costProfile": {
            "class": "heavy",
            "supportsAsync": True
        },
        "commercialClassification": {
            "sellableCapability": True,
            "meterRefs": [],
            "costClassRefs": []
        },
        "legacyBindings": {
            "routes": ("/v1/attribution", "/v1/conversions", "/v1/journeys", "/v1/measurement", "/v1/spend"),
            "surfaceIds": ("campaign360", "outcome360"),
            "services": ("services/api/journeys/measurement",),
            "migrationMode": "converged",
            "migrationBlueprint": "docs/architecture/blueprints/outcome360.md"
        },
        "deprecatedReason": None,
        "successorId": None,
        "pendingAuthority": [],
        "pendingReference": []
    },
    "population360": {
        "id": "population360",
        "displayName": "Population 360",
        "projectionKind": "context_360",
        "implementationState": "implemented",
        "implementationBlueprint": "docs/architecture/blueprints/population360.md",
        "ownsCanonicalTruth": False,
        "subjectKinds": ("cluster", "entity", "population"),
        "canonicalAuthorities": ("cluster_definitions", "cohort_membership", "entities", "evidence", "population_definitions", "temporal"),
        "hardDependencies": ("contract_spine", "grouping_membership"),
        "projectionDependencies": ("profile360", "relationship360", "temporal360"),
        "optionalProjectionDependencies": [],
        "inputRefs": ("EntityRef", "GraphResult", "GraphSnapshotRef", "PageRequest", "TimeRangeFilter"),
        "outputSections": ("evidence", "findings", "state", "summary", "timeline"),
        "supportedTemporalModes": ("relative", "window"),
        "surfaceIds": ("population360",),
        "capabilityKeys": ("population360.explore", "population360.read"),
        "metricRefs": [],
        "graphMutationPolicy": "read_only",
        "requiresEvidence": True,
        "requiresDimensionState": True,
        "requiresFreshness": True,
        "requiresLimitations": True,
        "tenantScoped": True,
        "policyScoped": True,
        "readinessRequirements": {
            "requiresImplementation": True,
            "requiresDependencies": True,
            "requiresTenantEntitlement": True,
            "requiresProviderReadiness": False,
            "requiresEvidenceHealth": True
        },
        "security": {
            "tenantScoped": True,
            "requiresAuthorization": True,
            "requiresHistoricalConsentEvaluation": False,
            "exportClass": "governed",
            "distillationRisk": "moderate"
        },
        "costProfile": {
            "class": "moderate",
            "supportsAsync": False
        },
        "commercialClassification": {
            "sellableCapability": True,
            "meterRefs": [],
            "costClassRefs": []
        },
        "legacyBindings": {
            "routes": ("/v1/population",),
            "surfaceIds": ("population360",),
            "services": ("services/api/identity/population",),
            "migrationMode": "converged",
            "migrationBlueprint": "docs/architecture/blueprints/population360.md"
        },
        "deprecatedReason": None,
        "successorId": None,
        "pendingAuthority": [],
        "pendingReference": []
    },
    "profile360": {
        "id": "profile360",
        "displayName": "Profile 360",
        "projectionKind": "entity_360",
        "implementationState": "in_flight",
        "implementationBlueprint": "docs/blueprints/profile360.md",
        "ownsCanonicalTruth": False,
        "subjectKinds": ("agent", "entity", "episode", "journey"),
        "canonicalAuthorities": ("agent_access", "agent_executions", "analytics_events", "cohort_membership", "communication_facts", "consent_policy_decisions", "entity_registry", "episode_facts", "evidence", "graph", "identity", "identity_source_identities", "journeys", "model_artifact_registry", "observations", "population_definitions", "profile_prediction_outputs", "relationship_facts", "temporal"),
        "hardDependencies": ("contract_spine", "evidence_provenance", "identity_resolution", "temporal_kernel"),
        "projectionDependencies": [],
        "optionalProjectionDependencies": ("relationship360", "risk360"),
        "inputRefs": ("EntityRef", "EvidenceRef", "GraphSnapshotRef", "PageRequest", "TimeRangeFilter"),
        "outputSections": ("agent_delegations", "evidence", "findings", "interactions", "journeys", "likely_next_states", "relationships", "sessions", "state", "summary", "syndicates", "timeline"),
        "supportedTemporalModes": ("as_of", "relative", "window"),
        "surfaceIds": ("profile360",),
        "capabilityKeys": ("profile360.explore", "profile360.read"),
        "metricRefs": [],
        "graphMutationPolicy": "read_only",
        "requiresEvidence": True,
        "requiresDimensionState": True,
        "requiresFreshness": True,
        "requiresLimitations": True,
        "tenantScoped": True,
        "policyScoped": True,
        "readinessRequirements": {
            "requiresImplementation": True,
            "requiresDependencies": True,
            "requiresTenantEntitlement": True,
            "requiresProviderReadiness": False,
            "requiresEvidenceHealth": True
        },
        "security": {
            "tenantScoped": True,
            "requiresAuthorization": True,
            "requiresHistoricalConsentEvaluation": True,
            "exportClass": "governed",
            "distillationRisk": "moderate"
        },
        "costProfile": {
            "class": "moderate",
            "supportsAsync": False
        },
        "commercialClassification": {
            "sellableCapability": True,
            "meterRefs": [],
            "costClassRefs": []
        },
        "legacyBindings": {
            "routes": ("/v1/profile", "/v1/profile360"),
            "surfaceIds": ("profile360",),
            "services": ("services/api/identity/profile",),
            "migrationMode": "adapter",
            "migrationBlueprint": "docs/blueprints/profile360.md"
        },
        "deprecatedReason": None,
        "successorId": None,
        "pendingAuthority": [],
        "pendingReference": []
    },
    "relationship360": {
        "id": "relationship360",
        "displayName": "Relationship 360",
        "projectionKind": "relationship_360",
        "implementationState": "in_flight",
        "implementationBlueprint": "docs/blueprints/relationship360.md",
        "ownsCanonicalTruth": False,
        "subjectKinds": ("agent", "entity", "episode", "population", "relationship", "source"),
        "canonicalAuthorities": ("cohort_membership", "evidence", "graph", "identity", "relationship_facts", "temporal"),
        "hardDependencies": ("identity_resolution", "relationship_fidelity", "temporal_kernel"),
        "projectionDependencies": ("profile360", "temporal360"),
        "optionalProjectionDependencies": ("communication360", "economic360", "risk360", "social360"),
        "inputRefs": ("EntityRef", "EvidenceRef", "GraphSnapshotRef", "PageRequest", "RelationshipRef", "TimeRangeFilter"),
        "outputSections": ("agent_spawned_agents", "evidence", "findings", "interactions", "state", "summary", "timeline"),
        "supportedTemporalModes": ("as_of", "relative", "window"),
        "surfaceIds": ("graph", "profile360"),
        "capabilityKeys": ("relationship360.explore", "relationship360.read"),
        "metricRefs": [],
        "graphMutationPolicy": "read_only",
        "requiresEvidence": True,
        "requiresDimensionState": True,
        "requiresFreshness": True,
        "requiresLimitations": True,
        "tenantScoped": True,
        "policyScoped": True,
        "readinessRequirements": {
            "requiresImplementation": True,
            "requiresDependencies": True,
            "requiresTenantEntitlement": True,
            "requiresProviderReadiness": False,
            "requiresEvidenceHealth": True
        },
        "security": {
            "tenantScoped": True,
            "requiresAuthorization": True,
            "requiresHistoricalConsentEvaluation": True,
            "exportClass": "governed",
            "distillationRisk": "moderate"
        },
        "costProfile": {
            "class": "moderate",
            "supportsAsync": False
        },
        "commercialClassification": {
            "sellableCapability": True,
            "meterRefs": [],
            "costClassRefs": []
        },
        "legacyBindings": {
            "routes": ("/v1/entities", "/v1/graph", "/v1/semantic"),
            "surfaceIds": ("graph", "profile360"),
            "services": ("services/api/graph/operational_intelligence", "services/api/intelligence/semantic_intelligence"),
            "migrationMode": "adapter",
            "migrationBlueprint": "docs/blueprints/relationship360.md"
        },
        "deprecatedReason": None,
        "successorId": None,
        "pendingAuthority": [],
        "pendingReference": []
    },
    "risk360": {
        "id": "risk360",
        "displayName": "Risk 360",
        "projectionKind": "risk_360",
        "implementationState": "implemented",
        "implementationBlueprint": "docs/architecture/blueprints/risk360.md",
        "ownsCanonicalTruth": False,
        "subjectKinds": ("agent", "cluster", "contagion_path", "entity", "population", "relationship", "source", "support_case"),
        "canonicalAuthorities": ("bronze_sdk_events", "cluster_membership", "computation", "consent_policy_decisions", "economic_facts", "entity_graph", "evidence", "flow_trace_paths", "flow_traces", "graph", "model_governance", "observations", "relationship_facts", "risk_assessments", "risk_intervention_records", "risk_outputs", "risk_signals", "social_relationship_evidence_events", "source_provenance", "support_cases", "transfers"),
        "hardDependencies": ("computation_substrate", "evidence_provenance", "model_governance"),
        "projectionDependencies": ("cluster360", "economic360", "profile360"),
        "optionalProjectionDependencies": [],
        "inputRefs": ("EntityRef", "EvidenceRef", "FilterExpression", "GraphSnapshotRef", "PageRequest", "RelationshipRef", "TimeRangeFilter"),
        "outputSections": ("evidence", "financial_risk", "findings", "health", "state", "summary"),
        "supportedTemporalModes": ("as_of", "relative", "window"),
        "surfaceIds": ("comparison_workbench", "graph", "risk360"),
        "capabilityKeys": ("risk360.explore", "risk360.read"),
        "metricRefs": [],
        "graphMutationPolicy": "read_only",
        "requiresEvidence": True,
        "requiresDimensionState": True,
        "requiresFreshness": True,
        "requiresLimitations": True,
        "tenantScoped": True,
        "policyScoped": True,
        "readinessRequirements": {
            "requiresImplementation": True,
            "requiresDependencies": True,
            "requiresTenantEntitlement": True,
            "requiresProviderReadiness": False,
            "requiresEvidenceHealth": True
        },
        "security": {
            "tenantScoped": True,
            "requiresAuthorization": True,
            "requiresHistoricalConsentEvaluation": True,
            "exportClass": "governed",
            "distillationRisk": "high"
        },
        "costProfile": {
            "class": "heavy",
            "supportsAsync": True
        },
        "commercialClassification": {
            "sellableCapability": True,
            "meterRefs": [],
            "costClassRefs": []
        },
        "legacyBindings": {
            "routes": ("/v1/capability-risk", "/v1/risk-overlays"),
            "surfaceIds": ("comparison_workbench", "graph", "risk360"),
            "services": ("services/api/graph/risk_overlay",),
            "migrationMode": "converged",
            "migrationBlueprint": "docs/architecture/blueprints/risk360.md"
        },
        "deprecatedReason": None,
        "successorId": None,
        "pendingAuthority": [],
        "pendingReference": []
    },
    "signals360": {
        "id": "signals360",
        "displayName": "Signals 360",
        "projectionKind": "context_360",
        "implementationState": "in_flight",
        "implementationBlueprint": "docs/reference/source-of-truth/AETHER_360_BACKEND_SINGLE_SOURCE_OF_TRUTH.md",
        "ownsCanonicalTruth": False,
        "subjectKinds": ("entity", "event", "observation", "signal", "source", "stream"),
        "canonicalAuthorities": ("behavioral_signals", "campaign_facts", "campaign_touchpoints", "events", "identity", "ingestion_health", "observations", "risk_outputs", "silver_semantic_observations", "source_facts", "source_provenance", "source_schema"),
        "hardDependencies": ("contract_spine",),
        "projectionDependencies": [],
        "optionalProjectionDependencies": [],
        "inputRefs": ("EntityRef", "EvidenceRef", "PageRequest", "TimeRangeFilter"),
        "outputSections": ("campaign_links", "classification", "evidence_trace", "freshness", "linked_entities", "normalization", "quality", "risk_flags", "signal_summary", "source_inventory"),
        "supportedTemporalModes": ("window",),
        "surfaceIds": ("profile360",),
        "capabilityKeys": ("signals360.read",),
        "metricRefs": [],
        "graphMutationPolicy": "read_only",
        "requiresEvidence": True,
        "requiresDimensionState": True,
        "requiresFreshness": True,
        "requiresLimitations": True,
        "tenantScoped": True,
        "policyScoped": True,
        "readinessRequirements": {
            "requiresImplementation": True,
            "requiresDependencies": True,
            "requiresTenantEntitlement": True,
            "requiresProviderReadiness": False,
            "requiresEvidenceHealth": True
        },
        "security": {
            "tenantScoped": True,
            "requiresAuthorization": True,
            "requiresHistoricalConsentEvaluation": True,
            "exportClass": "governed",
            "distillationRisk": "moderate"
        },
        "costProfile": {
            "class": "moderate",
            "supportsAsync": False
        },
        "commercialClassification": {
            "sellableCapability": False,
            "meterRefs": [],
            "costClassRefs": []
        },
        "legacyBindings": {
            "routes": ("/v1/experience360/frames",),
            "surfaceIds": ("profile360",),
            "services": ("services/api/intelligence/signals",),
            "migrationMode": "adapter",
            "migrationBlueprint": "docs/reference/source-of-truth/AETHER_360_BACKEND_SINGLE_SOURCE_OF_TRUTH.md"
        },
        "deprecatedReason": None,
        "successorId": None,
        "pendingAuthority": [],
        "pendingReference": []
    },
    "social360": {
        "id": "social360",
        "displayName": "Social 360",
        "projectionKind": "relationship_360",
        "implementationState": "in_flight",
        "implementationBlueprint": "docs/architecture/blueprints/social360.md",
        "ownsCanonicalTruth": False,
        "subjectKinds": ("agent", "entity", "population", "relationship", "source"),
        "canonicalAuthorities": ("agent_entities", "authenticated_tenant_permission", "cohort_membership", "computation", "entity_identity", "evidence", "graph", "identity", "influence_propagation", "population_definitions", "relationship_facts", "relationship_fidelity", "relationship_predicate_registry", "risk_outputs", "risk_signals", "social_observations", "social_relationship_evidence_events", "source_facts", "source_provenance"),
        "hardDependencies": ("relationship_fidelity", "temporal_kernel", "upr"),
        "projectionDependencies": ("profile360", "relationship360"),
        "optionalProjectionDependencies": [],
        "inputRefs": ("EntityRef", "EvidenceRef", "GraphSnapshotRef", "PageRequest", "RelationshipRef", "TimeRangeFilter"),
        "outputSections": ("evidence", "findings", "influence", "interactions", "paths", "propagation", "risk_edges", "social_contagion", "state", "summary", "syndicates", "timeline", "trust_edges"),
        "supportedTemporalModes": ("as_of", "relative", "window"),
        "surfaceIds": ("profile360", "social360"),
        "capabilityKeys": ("social360.explore", "social360.read"),
        "metricRefs": [],
        "graphMutationPolicy": "read_only",
        "requiresEvidence": True,
        "requiresDimensionState": True,
        "requiresFreshness": True,
        "requiresLimitations": True,
        "tenantScoped": True,
        "policyScoped": True,
        "readinessRequirements": {
            "requiresImplementation": True,
            "requiresDependencies": True,
            "requiresTenantEntitlement": True,
            "requiresProviderReadiness": False,
            "requiresEvidenceHealth": True
        },
        "security": {
            "tenantScoped": True,
            "requiresAuthorization": True,
            "requiresHistoricalConsentEvaluation": True,
            "exportClass": "governed",
            "distillationRisk": "moderate"
        },
        "costProfile": {
            "class": "moderate",
            "supportsAsync": False
        },
        "commercialClassification": {
            "sellableCapability": True,
            "meterRefs": [],
            "costClassRefs": []
        },
        "legacyBindings": {
            "routes": ("/v1/profile",),
            "surfaceIds": ("profile360", "social360"),
            "services": ("services/api/identity/profile",),
            "migrationMode": "adapter",
            "migrationBlueprint": "docs/architecture/blueprints/social360.md"
        },
        "deprecatedReason": None,
        "successorId": None,
        "pendingAuthority": [],
        "pendingReference": []
    },
    "source360": {
        "id": "source360",
        "displayName": "Source 360",
        "projectionKind": "operational_workbench",
        "implementationState": "in_flight",
        "implementationBlueprint": "docs/blueprints/source360.md",
        "ownsCanonicalTruth": False,
        "subjectKinds": ("agent", "connection", "entity", "source"),
        "canonicalAuthorities": ("evidence", "ingestion_health", "provider_registry", "source_coverage", "source_provenance", "source_schema"),
        "hardDependencies": ("upr",),
        "projectionDependencies": [],
        "optionalProjectionDependencies": [],
        "inputRefs": ("EntityRef", "EvidenceRef", "PageRequest", "TimeRangeFilter"),
        "outputSections": ("coverage", "evidence", "health", "state", "summary"),
        "supportedTemporalModes": ("relative", "window"),
        "surfaceIds": ("campaign360",),
        "capabilityKeys": ("source360.explore", "source360.read"),
        "metricRefs": [],
        "graphMutationPolicy": "read_only",
        "requiresEvidence": True,
        "requiresDimensionState": True,
        "requiresFreshness": True,
        "requiresLimitations": True,
        "tenantScoped": True,
        "policyScoped": True,
        "readinessRequirements": {
            "requiresImplementation": True,
            "requiresDependencies": True,
            "requiresTenantEntitlement": True,
            "requiresProviderReadiness": False,
            "requiresEvidenceHealth": True
        },
        "security": {
            "tenantScoped": True,
            "requiresAuthorization": True,
            "requiresHistoricalConsentEvaluation": False,
            "exportClass": "governed",
            "distillationRisk": "moderate"
        },
        "costProfile": {
            "class": "moderate",
            "supportsAsync": False
        },
        "commercialClassification": {
            "sellableCapability": True,
            "meterRefs": [],
            "costClassRefs": []
        },
        "legacyBindings": {
            "routes": ("/v1/imports", "/v1/kyber", "/v1/providers"),
            "surfaceIds": ("campaign360",),
            "services": ("services/api/ingestion/imports",),
            "migrationMode": "adapter",
            "migrationBlueprint": "docs/blueprints/source360.md"
        },
        "deprecatedReason": None,
        "successorId": None,
        "pendingAuthority": [],
        "pendingReference": []
    },
    "support360": {
        "id": "support360",
        "displayName": "Support 360",
        "projectionKind": "context_360",
        "implementationState": "in_flight",
        "implementationBlueprint": "docs/architecture/blueprints/support360.md",
        "ownsCanonicalTruth": False,
        "subjectKinds": ("callback", "entity", "support_case"),
        "canonicalAuthorities": ("agent_entities", "communication_facts", "episode_facts", "evidence", "identity", "journeys", "measurement_contract", "provider_connections", "support_callback_events", "support_callbacks", "support_case_agent_assignment_events", "support_case_context_events", "support_case_events", "support_cases"),
        "hardDependencies": ("contract_spine", "temporal_kernel"),
        "projectionDependencies": [],
        "optionalProjectionDependencies": [],
        "inputRefs": ("EntityRef", "EvidenceRef", "PageRequest", "TimeRangeFilter"),
        "outputSections": ("evidence", "interactions", "outcomes", "state", "summary", "timeline"),
        "supportedTemporalModes": ("window",),
        "surfaceIds": ("support360",),
        "capabilityKeys": ("support360.explore", "support360.read"),
        "metricRefs": [],
        "graphMutationPolicy": "read_only",
        "requiresEvidence": True,
        "requiresDimensionState": True,
        "requiresFreshness": True,
        "requiresLimitations": True,
        "tenantScoped": True,
        "policyScoped": True,
        "readinessRequirements": {
            "requiresImplementation": True,
            "requiresDependencies": True,
            "requiresTenantEntitlement": True,
            "requiresProviderReadiness": False,
            "requiresEvidenceHealth": True
        },
        "security": {
            "tenantScoped": True,
            "requiresAuthorization": True,
            "requiresHistoricalConsentEvaluation": True,
            "exportClass": "governed",
            "distillationRisk": "high"
        },
        "costProfile": {
            "class": "moderate",
            "supportsAsync": False
        },
        "commercialClassification": {
            "sellableCapability": True,
            "meterRefs": [],
            "costClassRefs": []
        },
        "legacyBindings": {
            "routes": ("/v1/experience360/frames",),
            "surfaceIds": ("support360",),
            "services": ("services/api/journeys/support360",),
            "migrationMode": "adapter",
            "migrationBlueprint": "docs/architecture/blueprints/support360.md"
        },
        "deprecatedReason": None,
        "successorId": None,
        "pendingAuthority": [],
        "pendingReference": []
    },
    "temporal360": {
        "id": "temporal360",
        "displayName": "Temporal 360",
        "projectionKind": "context_360",
        "implementationState": "implemented",
        "implementationBlueprint": "docs/architecture/blueprints/temporal360.md",
        "ownsCanonicalTruth": False,
        "subjectKinds": ("entity", "relationship"),
        "canonicalAuthorities": ("graph_snapshots", "mutation_history", "temporal_kernel", "validity_state"),
        "hardDependencies": ("contract_spine", "graph_history_replay"),
        "projectionDependencies": [],
        "optionalProjectionDependencies": [],
        "inputRefs": ("GraphResult", "GraphSnapshotRef", "PageRequest", "TimeRangeFilter"),
        "outputSections": ("evidence", "findings", "state", "summary", "timeline"),
        "supportedTemporalModes": ("as_of", "compare", "relative", "window"),
        "surfaceIds": ("temporal360",),
        "capabilityKeys": ("temporal360.explore", "temporal360.read"),
        "metricRefs": [],
        "graphMutationPolicy": "read_only",
        "requiresEvidence": True,
        "requiresDimensionState": True,
        "requiresFreshness": True,
        "requiresLimitations": True,
        "tenantScoped": True,
        "policyScoped": True,
        "readinessRequirements": {
            "requiresImplementation": True,
            "requiresDependencies": True,
            "requiresTenantEntitlement": True,
            "requiresProviderReadiness": False,
            "requiresEvidenceHealth": True
        },
        "security": {
            "tenantScoped": True,
            "requiresAuthorization": True,
            "requiresHistoricalConsentEvaluation": False,
            "exportClass": "governed",
            "distillationRisk": "moderate"
        },
        "costProfile": {
            "class": "moderate",
            "supportsAsync": False
        },
        "commercialClassification": {
            "sellableCapability": True,
            "meterRefs": [],
            "costClassRefs": []
        },
        "legacyBindings": {
            "routes": ("/v1/graph", "/v1/preferences"),
            "surfaceIds": ("temporal360",),
            "services": ("services/api/shared/temporal",),
            "migrationMode": "converged",
            "migrationBlueprint": "docs/architecture/blueprints/temporal360.md"
        },
        "deprecatedReason": None,
        "successorId": None,
        "pendingAuthority": [],
        "pendingReference": []
    },
    "workflow360": {
        "id": "workflow360",
        "displayName": "Workflow 360",
        "projectionKind": "context_360",
        "implementationState": "in_flight",
        "implementationBlueprint": "docs/reference/source-of-truth/AETHER_360_BACKEND_SINGLE_SOURCE_OF_TRUTH.md",
        "ownsCanonicalTruth": False,
        "subjectKinds": ("automation", "run", "trigger", "workflow", "workflow_run"),
        "canonicalAuthorities": ("agent_access", "agent_entities", "agent_executions", "ai_execution_facts", "commerce", "events", "evidence", "execution_facts", "graph_edges", "identity", "outcome_facts", "risk_assessments", "tools", "workflow_definition_revisions"),
        "hardDependencies": ("contract_spine",),
        "projectionDependencies": [],
        "optionalProjectionDependencies": [],
        "inputRefs": ("EntityRef", "EvidenceRef", "PageRequest", "TimeRangeFilter"),
        "outputSections": ("actions", "actors", "agent_steps", "approvals", "evidence_trace", "failures", "outcomes", "risk", "runs", "triggers", "workflow_summary"),
        "supportedTemporalModes": ("window",),
        "surfaceIds": ("timeline",),
        "capabilityKeys": ("workflow360.read",),
        "metricRefs": [],
        "graphMutationPolicy": "read_only",
        "requiresEvidence": True,
        "requiresDimensionState": True,
        "requiresFreshness": True,
        "requiresLimitations": True,
        "tenantScoped": True,
        "policyScoped": True,
        "readinessRequirements": {
            "requiresImplementation": True,
            "requiresDependencies": True,
            "requiresTenantEntitlement": True,
            "requiresProviderReadiness": False,
            "requiresEvidenceHealth": True
        },
        "security": {
            "tenantScoped": True,
            "requiresAuthorization": True,
            "requiresHistoricalConsentEvaluation": True,
            "exportClass": "governed",
            "distillationRisk": "moderate"
        },
        "costProfile": {
            "class": "moderate",
            "supportsAsync": False
        },
        "commercialClassification": {
            "sellableCapability": False,
            "meterRefs": [],
            "costClassRefs": []
        },
        "legacyBindings": {
            "routes": ("/v1/experience360/frames",),
            "surfaceIds": ("timeline",),
            "services": ("services/api/intelligence/workflow",),
            "migrationMode": "adapter",
            "migrationBlueprint": "docs/reference/source-of-truth/AETHER_360_BACKEND_SINGLE_SOURCE_OF_TRUTH.md"
        },
        "deprecatedReason": None,
        "successorId": None,
        "pendingAuthority": [],
        "pendingReference": []
    },
}

# Required/optional projection dependencies (sorted by projection id).
PROJECTION_DEPENDENCY_GRAPH: dict[str, dict] = {
    "agent360": {"required": ("profile360",), "optional": ("economic360", "outcome360")},
    "campaign360": {"required": ("communication360", "economic360", "episode360", "outcome360", "population360"), "optional": ()},
    "cluster360": {"required": ("population360",), "optional": ()},
    "commerce360": {"required": (), "optional": ()},
    "communication360": {"required": ("episode360", "outcome360", "profile360", "relationship360"), "optional": ()},
    "connection360": {"required": ("source360",), "optional": ()},
    "economic360": {"required": ("outcome360", "profile360", "relationship360"), "optional": ()},
    "episode360": {"required": ("profile360", "relationship360"), "optional": ()},
    "execution360": {"required": ("agent360", "episode360", "outcome360", "temporal360"), "optional": ()},
    "fraud360": {"required": ("profile360", "risk360"), "optional": ()},
    "geographic360": {"required": ("profile360", "temporal360"), "optional": ()},
    "infrastructure360": {"required": (), "optional": ()},
    "memory360": {"required": (), "optional": ()},
    "outcome360": {"required": ("temporal360",), "optional": ()},
    "population360": {"required": ("profile360", "relationship360", "temporal360"), "optional": ()},
    "profile360": {"required": (), "optional": ("relationship360", "risk360")},
    "relationship360": {"required": ("profile360", "temporal360"), "optional": ("communication360", "economic360", "risk360", "social360")},
    "risk360": {"required": ("cluster360", "economic360", "profile360"), "optional": ()},
    "signals360": {"required": (), "optional": ()},
    "social360": {"required": ("profile360", "relationship360"), "optional": ()},
    "source360": {"required": (), "optional": ()},
    "support360": {"required": (), "optional": ()},
    "temporal360": {"required": (), "optional": ()},
    "workflow360": {"required": (), "optional": ()},
}

# projection id -> registered surfaces (sorted).
PROJECTION_SURFACE_MAP: dict[str, tuple] = {
    "agent360": ("profile360",),
    "campaign360": ("campaign360", "comparison_workbench"),
    "cluster360": ("cluster360", "graph"),
    "commerce360": ("product_intelligence",),
    "communication360": ("profile360", "timeline"),
    "connection360": ("connection360",),
    "economic360": ("campaign360", "economic360", "product_intelligence"),
    "episode360": ("journeys", "timeline"),
    "execution360": ("timeline",),
    "fraud360": ("fraud360", "graph"),
    "geographic360": ("geographic360",),
    "infrastructure360": ("infrastructure360",),
    "memory360": ("profile360",),
    "outcome360": ("campaign360", "outcome360"),
    "population360": ("population360",),
    "profile360": ("profile360",),
    "relationship360": ("graph", "profile360"),
    "risk360": ("comparison_workbench", "graph", "risk360"),
    "signals360": ("profile360",),
    "social360": ("profile360", "social360"),
    "source360": ("campaign360",),
    "support360": ("support360",),
    "temporal360": ("temporal360",),
    "workflow360": ("timeline",),
}

# projection id -> capability keys (sorted).
PROJECTION_CAPABILITY_MAP: dict[str, tuple] = {
    "agent360": ("agent360.explore", "agent360.read"),
    "campaign360": ("campaign360.explore", "campaign360.read"),
    "cluster360": ("cluster360.explore", "cluster360.read"),
    "commerce360": ("commerce360.read",),
    "communication360": ("communication360.explore", "communication360.read"),
    "connection360": ("connection360.explore", "connection360.read"),
    "economic360": ("economic360.explore", "economic360.read"),
    "episode360": ("episode360.explore", "episode360.read"),
    "execution360": ("execution360.explore", "execution360.read"),
    "fraud360": ("fraud360.explore", "fraud360.read"),
    "geographic360": ("geographic360.explore", "geographic360.read"),
    "infrastructure360": ("infrastructure360.explore", "infrastructure360.read"),
    "memory360": ("memory360.read",),
    "outcome360": ("outcome360.explore", "outcome360.read"),
    "population360": ("population360.explore", "population360.read"),
    "profile360": ("profile360.explore", "profile360.read"),
    "relationship360": ("relationship360.explore", "relationship360.read"),
    "risk360": ("risk360.explore", "risk360.read"),
    "signals360": ("signals360.read",),
    "social360": ("social360.explore", "social360.read"),
    "source360": ("source360.explore", "source360.read"),
    "support360": ("support360.explore", "support360.read"),
    "temporal360": ("temporal360.explore", "temporal360.read"),
    "workflow360": ("workflow360.read",),
}

PRODUCT_360_SURFACE_CATALOG_VERSION = "0.2.0"
# Productized 360 surfaces; distinct from the technical projection provider registry.
PRODUCT_360_SURFACE_IDS: tuple[str, ...] = (
    "account360",
    "agent360",
    "campaign360",
    "commerce360",
    "communications360",
    "episode360",
    "execution360",
    "identity360",
    "journey360",
    "location360",
    "memory360",
    "profile360",
    "risk360",
    "signals360",
    "social360",
    "support360",
    "value360",
    "workflow360",
)

# Aggregate 360 frame states; projection section states remain separate.
EXPERIENCE_360_FRAME_STATES: tuple[str, ...] = (
    "conflicted",
    "degraded",
    "empty",
    "missing",
    "partial",
    "ready",
    "stale",
    "suppressed",
    "unavailable",
    "unknown",
)

# Product surface contracts and explicit slot-to-projection section bindings.
PRODUCT_360_SURFACE_DEFINITIONS: dict[str, dict] = {
    "account360": {
        "backendCapabilities": {
            "required": ("experience360.evidence.provenance", "experience360.frame.compose", "experience360.freshness.evaluate", "experience360.policy.evaluate", "experience360.tenant_scope.enforce"),
            "projectionCapabilityKeys": ("communication360.explore", "communication360.read", "economic360.explore", "economic360.read", "profile360.explore", "profile360.read", "relationship360.explore", "relationship360.read"),
            "providerCapabilityStatus": "registry_requirements_not_route_attestation"
        },
        "blueprintContract": {
            "canonicalOwner": "account_organization_graph",
            "priority": "P1",
            "purpose": "Aggregates organization/account-level state across members, profiles, journeys, communications, agents, value, and risk.",
            "requiredLensIds": ("account", "communications", "identity", "journey", "policy", "relationship", "risk", "value"),
            "requiredSlotIds": ("account_summary", "agents", "communications", "contracts", "evidence_trace", "journeys", "members", "profiles", "relationships", "risk", "value"),
            "sourceSection": "11.13",
            "subjectIdentifiers": ("account_id", "organization_id", "tenant_customer_id", "workspace_id")
        },
        "contractStatus": "source_aligned",
        "description": "Governed account-level view composed from canonical entity, relationship, economic, and evidence authorities.",
        "directProviderBindings": [
            {
                "bindingStatus": "runtime_wired",
                "canonicalAuthorityRefs": ("commerce", "entities", "entity_registry", "graph", "identity", "journeys", "risk_outputs", "tenant_contract_profiles"),
                "domainSlotIds": ("account_summary", "agents", "contracts", "journeys", "members", "profiles", "risk"),
                "implementationRef": "services/api/identity/account360_provider.py",
                "providerClass": "Account360Provider",
                "providerKind": "surface_frame_provider",
                "runtimeBindingRef": "services/api/shared/intelligence_projections/frame_runtime.py",
                "subjectKinds": ("entity",)
            }
        ],
        "displayName": "Account 360",
        "domainSlots": [
            {
                "id": "account_identity_and_state",
                "requirement": "optional",
                "description": "Resolved account identity and state.",
                "canonicalAuthorityRefs": ("entity_registry", "identity"),
                "projectionBindings": [
                    {
                        "projectionId": "profile360",
                        "role": "primary",
                        "subjectKinds": ("entity",),
                        "sectionIds": ("state", "summary")
                    }
                ]
            },
            {
                "id": "account_relationships",
                "requirement": "optional",
                "description": "Relationships associated with the account.",
                "canonicalAuthorityRefs": ("graph", "relationship_facts"),
                "projectionBindings": [
                    {
                        "projectionId": "relationship360",
                        "role": "primary",
                        "subjectKinds": ("entity",),
                        "sectionIds": ("evidence", "interactions", "summary")
                    }
                ]
            },
            {
                "id": "account_summary",
                "requirement": "required",
                "description": "Exact tenant organization or account identity; lifecycle coverage remains unknown.",
                "canonicalAuthorityRefs": ("entities", "entity_registry"),
                "projectionBindings": []
            },
            {
                "id": "agents",
                "requirement": "required",
                "description": "Observed canonical agent members of the account; authority and delegation are evaluated in their owning subsystems.",
                "canonicalAuthorityRefs": ("entity_registry", "graph"),
                "projectionBindings": []
            },
            {
                "canonicalAuthorityRefs": ("communication_facts",),
                "description": "Account communications linked to exact tenant-owned entity participants under governing frame policy, without member fanout.",
                "id": "communications",
                "partialImplementationReason": "Only exact tenant-owned entity subjects are joined; account/workspace aliases and member fanout are unavailable. Communication360 preserves source timestamps but does not evaluate freshness; policy and historical consent remain frame-runtime responsibilities.",
                "projectionBindings": [
                    {
                        "projectionId": "communication360",
                        "role": "primary",
                        "subjectKinds": ("entity",),
                        "sectionIds": ("evidence", "interactions", "timeline")
                    }
                ],
                "requirement": "required"
            },
            {
                "canonicalAuthorityRefs": ("commerce", "tenant_contract_profiles"),
                "description": "Exact tenant and canonical account-id contract profiles from the commerce billing authority; tenant defaults do not imply account contracts.",
                "id": "contracts",
                "partialImplementationReason": "Tenant contract profiles are exact current account-linked records; obligation execution, upstream contract completeness, historical replay, and freshness SLA remain unknown.",
                "projectionBindings": [],
                "requirement": "required"
            },
            {
                "id": "economic_context",
                "requirement": "optional",
                "description": "Economic facts associated with the account.",
                "canonicalAuthorityRefs": ("ai_execution_facts", "economic_facts"),
                "projectionBindings": [
                    {
                        "projectionId": "economic360",
                        "role": "primary",
                        "subjectKinds": ("entity",),
                        "sectionIds": ("evidence", "outcomes", "summary")
                    }
                ]
            },
            {
                "id": "evidence_and_limitations",
                "requirement": "optional",
                "description": "Evidence and coverage for account context.",
                "canonicalAuthorityRefs": ("evidence",),
                "projectionBindings": [
                    {
                        "projectionId": "profile360",
                        "role": "primary",
                        "subjectKinds": ("entity",),
                        "sectionIds": ("evidence", "findings")
                    }
                ]
            },
            {
                "id": "evidence_trace",
                "requirement": "required",
                "description": "Evidence and limits for the account entity only, not a complete member aggregate.",
                "canonicalAuthorityRefs": ("evidence",),
                "projectionBindings": [
                    {
                        "projectionId": "profile360",
                        "role": "primary",
                        "subjectKinds": ("entity",),
                        "sectionIds": ("evidence", "findings")
                    }
                ]
            },
            {
                "canonicalAuthorityRefs": ("entity_registry", "graph", "journeys"),
                "description": "Current human member journey participation joined through exact MEMBER_OF graph evidence and independently policy-approved Profile360 journey slots.",
                "id": "journeys",
                "partialImplementationReason": "Current journey participation is joined through exact observed human membership and per-member Profile360 policy; historical membership, roster completeness, direct account journey ownership, and a freshness SLA remain unknown.",
                "projectionBindings": [],
                "requirement": "required"
            },
            {
                "canonicalAuthorityRefs": ("entity_registry", "graph"),
                "description": "Current tenant MEMBER_OF graph edges are candidates only; each positive membership requires an exact live graph mutation-ledger aggregate and canonical member entity.",
                "id": "members",
                "partialImplementationReason": "Positive current membership requires a live tenant-scoped MEMBER_OF edge whose exact aggregate replay agrees with the graph candidate and whose member resolves to a tenant entity; the bounded ledger and graph scans do not establish complete roster coverage, historical membership, or freshness.",
                "projectionBindings": [],
                "requirement": "required"
            },
            {
                "canonicalAuthorityRefs": ("entity_registry", "graph", "identity"),
                "description": "Profile views for validated account members with each profile policy independently applied.",
                "id": "profiles",
                "partialImplementationReason": "Bounded exact-member Profile360 frames now run under per-member policy; roster completeness and a profile freshness SLA remain unknown.",
                "projectionBindings": [],
                "requirement": "required"
            },
            {
                "id": "relationships",
                "requirement": "required",
                "description": "Entity scoped relationship evidence for the exact account identity.",
                "canonicalAuthorityRefs": ("graph", "relationship_facts"),
                "projectionBindings": [
                    {
                        "projectionId": "relationship360",
                        "role": "primary",
                        "subjectKinds": ("entity",),
                        "sectionIds": ("evidence", "interactions", "summary")
                    }
                ]
            },
            {
                "canonicalAuthorityRefs": ("entity_registry", "graph", "risk_outputs"),
                "description": "Direct account-entity risk plus bounded evidence-backed risk frames for exact tenant-scoped members; roster and risk coverage remain partial.",
                "id": "risk",
                "partialImplementationReason": "Direct account risk remains separate; bounded exact MEMBER_OF member contexts are included only after the account risk slot and each member Risk360 risk_summary policy allow. Roster completeness, related-account aggregation, temporal member-risk reads, and freshness remain unknown.",
                "projectionBindings": [],
                "requirement": "required"
            },
            {
                "id": "value",
                "requirement": "required",
                "description": "Direct entity-scoped economic value for the canonical account profile, without member or execution-cost aggregation.",
                "canonicalAuthorityRefs": ("ai_execution_facts", "economic_facts"),
                "projectionBindings": [
                    {
                        "projectionId": "economic360",
                        "role": "primary",
                        "subjectKinds": ("entity",),
                        "sectionIds": ("summary",)
                    }
                ]
            }
        ],
        "freshnessPolicy": {
            "required": True,
            "maxAgeSeconds": None,
            "sourceTimestamps": "preserve",
            "missingTimestamp": "unknown",
            "onStale": "mark_affected_slots_stale",
            "requirementStatus": "contract_requirement_not_provider_attestation"
        },
        "id": "account360",
        "lensContract": {
            "expectedCount": 8,
            "lensIds": ("account", "communications", "identity", "journey", "policy", "relationship", "risk", "value"),
            "sourceAlignmentStatus": "source_aligned"
        },
        "policyBehavior": {
            "tenantScopeRequired": True,
            "authorizationBeforeRead": True,
            "policyEvaluation": "per_projection_before_composition",
            "historicalConsentEvaluation": "required_when_applicable",
            "redactionBehavior": "suppress_disallowed_slot_without_inference",
            "requirementStatus": "contract_requirement_not_provider_attestation"
        },
        "projectionBindings": [
            {
                "projectionId": "communication360",
                "role": "primary",
                "bindingStatus": "catalog_only",
                "providerImplementationState": "implemented"
            },
            {
                "projectionId": "economic360",
                "role": "primary",
                "bindingStatus": "catalog_only",
                "providerImplementationState": "implemented"
            },
            {
                "projectionId": "profile360",
                "role": "primary",
                "bindingStatus": "catalog_only",
                "providerImplementationState": "in_flight"
            },
            {
                "projectionId": "relationship360",
                "role": "primary",
                "bindingStatus": "catalog_only",
                "providerImplementationState": "in_flight"
            }
        ],
        "sourceOfTruth": {
            "canonicalAuthorities": ("ai_execution_facts", "commerce", "communication_facts", "economic_facts", "entities", "entity_registry", "evidence", "graph", "identity", "journeys", "relationship_facts", "risk_outputs", "tenant_contract_profiles"),
            "ownsCanonicalTruth": False,
            "prohibitedOwnership": ("economic_facts", "execution_facts", "graph", "identity", "observations", "risk_outputs", "source_provenance")
        },
        "subjectKinds": ("account", "entity", "workspace")
    },
    "agent360": {
        "backendCapabilities": {
            "required": ("experience360.evidence.provenance", "experience360.frame.compose", "experience360.freshness.evaluate", "experience360.policy.evaluate", "experience360.tenant_scope.enforce"),
            "projectionCapabilityKeys": ("agent360.explore", "agent360.read", "communication360.explore", "communication360.read", "economic360.explore", "economic360.read", "execution360.explore", "execution360.read", "outcome360.explore", "outcome360.read", "relationship360.explore", "relationship360.read", "risk360.explore", "risk360.read"),
            "providerCapabilityStatus": "registry_requirements_not_route_attestation"
        },
        "blueprintContract": {
            "canonicalOwner": "agent_identity_authority",
            "priority": "P0",
            "purpose": "Builds the governed read model for an autonomous or delegated agent, including ownership, authority, lifecycle, executions, and risk evidence.",
            "requiredLensIds": ("agentic", "authority", "execution", "identity", "policy", "provenance", "relationship", "risk"),
            "requiredSlotIds": ("authority_envelope", "capabilities", "delegation_chain", "evidence_trace", "execution_history", "identity", "owner_delegator", "policy_boundary", "risk_summary", "spawned_agents", "tool_usage"),
            "sourceSection": "11.1",
            "subjectIdentifiers": ("agent_id", "delegated_agent_id", "spawned_agent_id", "tool_agent_id")
        },
        "contractStatus": "source_aligned",
        "description": "Governed view of an agent identity, actor attribution, authority and delegation, execution activity, communications, risk, evidence, and measured outcomes.",
        "displayName": "Agent 360",
        "domainSlots": [
            {
                "canonicalAuthorityRefs": ("agent_entities", "identity"),
                "description": "Optional Aether provider context retained for Agent 360: actor attribution.",
                "id": "actor_attribution",
                "implementationCrosswalk": ("actor_attribution",),
                "projectionBindings": [
                    {
                        "projectionId": "agent360",
                        "role": "supporting",
                        "subjectKinds": ("agent", "entity"),
                        "sectionIds": ("evidence", "state")
                    },
                    {
                        "projectionId": "execution360",
                        "role": "primary",
                        "subjectKinds": ("agent", "entity"),
                        "sectionIds": ("evidence", "state")
                    }
                ],
                "requirement": "optional"
            },
            {
                "canonicalAuthorityRefs": ("agent_access", "agent_executions", "identity"),
                "description": "Observed current capability grants and recorded action-scoped delegation decisions; no standing action or resource authorization verdict.",
                "id": "authority_envelope",
                "implementationCrosswalk": ("authority_and_delegation",),
                "projectionBindings": [
                    {
                        "projectionId": "agent360",
                        "role": "primary",
                        "subjectKinds": ("agent", "entity"),
                        "sectionIds": ("evidence", "state")
                    }
                ],
                "requiredFrameMetadata": ("slotActorAttribution", "slotAuthorityDecision"),
                "requirement": "required"
            },
            {
                "canonicalAuthorityRefs": ("outcome_facts",),
                "description": "Optional Aether provider context retained for Agent 360: business outcomes.",
                "id": "business_outcomes",
                "implementationCrosswalk": ("business_outcomes",),
                "projectionBindings": [
                    {
                        "projectionId": "outcome360",
                        "role": "primary",
                        "subjectKinds": ("agent",),
                        "sectionIds": ("evidence", "outcomes")
                    }
                ],
                "requirement": "optional"
            },
            {
                "authorityGapReason": "active_invoke_grants_do_not_evaluate_action_or_resource_specific_policy",
                "canonicalAuthorityRefs": ("actions", "agent_access", "resources", "tools"),
                "description": "Observed runtime capability reach joined to exact active invoke grants for the resolved canonical Agent and exact observed MCP tool catalog identity; action and resource authorization remains unknown.",
                "id": "capabilities",
                "implementationCrosswalk": ("actions_tools_resources",),
                "partialImplementationReason": "Current active grant join is bounded to 2000 records. Observed catalog identity for an exact MCP tool does not prove remote ownership, effective tool authorization, action or resource policy, or historical authority.",
                "projectionBindings": [
                    {
                        "projectionId": "agent360",
                        "role": "primary",
                        "subjectKinds": ("agent", "entity"),
                        "sectionIds": ("evidence", "state")
                    }
                ],
                "requirement": "required",
                "unboundCanonicalAuthorityRefs": ("actions", "resources")
            },
            {
                "canonicalAuthorityRefs": ("communication_facts", "observations"),
                "description": "Optional Aether provider context retained for Agent 360: communications.",
                "id": "communications",
                "implementationCrosswalk": ("communications",),
                "projectionBindings": [
                    {
                        "projectionId": "agent360",
                        "role": "supporting",
                        "subjectKinds": ("agent",),
                        "sectionIds": ("interactions",)
                    },
                    {
                        "projectionId": "communication360",
                        "role": "primary",
                        "subjectKinds": ("agent",),
                        "sectionIds": ("evidence", "interactions", "timeline")
                    }
                ],
                "requirement": "optional"
            },
            {
                "canonicalAuthorityRefs": ("agent_access", "identity"),
                "description": "Tenant-scoped stored delegation edges with party identity evidence; no transitive or action-specific authority is inferred.",
                "id": "delegation_chain",
                "implementationCrosswalk": ("authority_and_delegation",),
                "partialImplementationReason": "delegation_reads_are_bounded_and_do_not_evaluate_transitive_or_action_resource_authority",
                "projectionBindings": [
                    {
                        "projectionId": "agent360",
                        "role": "primary",
                        "subjectKinds": ("agent", "entity"),
                        "sectionIds": ("evidence", "state")
                    }
                ],
                "requiredFrameMetadata": ("slotActorAttribution", "slotAuthorityDecision"),
                "requirement": "required"
            },
            {
                "canonicalAuthorityRefs": ("ai_execution_facts", "commerce", "economic_facts", "payments"),
                "description": "Optional Aether provider context retained for Agent 360: economic cost and settlement.",
                "id": "economic_cost_and_settlement",
                "implementationCrosswalk": ("economic_cost_and_settlement",),
                "projectionBindings": [
                    {
                        "projectionId": "economic360",
                        "role": "primary",
                        "subjectKinds": ("agent", "entity"),
                        "sectionIds": ("evidence", "summary")
                    }
                ],
                "requirement": "optional"
            },
            {
                "canonicalAuthorityRefs": ("evidence", "source_provenance"),
                "description": "Required Agent 360 blueprint slot: evidence trace.",
                "id": "evidence_trace",
                "implementationCrosswalk": ("source_evidence_lineage",),
                "partialImplementationReason": "Canonical Bronze links are joined to exact tenant, agent, source-row, event, schema, and timestamp references. Registered Rights source identity, source trust, freshness SLA, complete lineage coverage, and unlinked historical rows remain unknown.",
                "projectionBindings": [
                    {
                        "projectionId": "agent360",
                        "role": "supporting",
                        "subjectKinds": ("agent", "entity"),
                        "sectionIds": ("evidence",)
                    }
                ],
                "requirement": "required"
            },
            {
                "canonicalAuthorityRefs": ("agent_executions", "execution_facts"),
                "description": "Required Agent 360 blueprint slot: execution history.",
                "id": "execution_history",
                "implementationCrosswalk": ("execution_lifecycle",),
                "projectionBindings": [
                    {
                        "projectionId": "execution360",
                        "role": "primary",
                        "subjectKinds": ("agent", "entity"),
                        "sectionIds": ("evidence", "state", "timeline")
                    }
                ],
                "requirement": "required"
            },
            {
                "canonicalAuthorityRefs": ("agent_entity", "identity"),
                "description": "Required Agent 360 blueprint slot: identity.",
                "id": "identity",
                "implementationCrosswalk": ("agent_identity",),
                "projectionBindings": [
                    {
                        "projectionId": "agent360",
                        "role": "primary",
                        "subjectKinds": ("agent", "entity"),
                        "sectionIds": ("state", "summary")
                    }
                ],
                "requirement": "required"
            },
            {
                "canonicalAuthorityRefs": ("agent_access", "graph", "identity"),
                "description": "Tenant-scoped owner and delegator records with canonical party identity only where resolved; no effective action authorization is inferred.",
                "id": "owner_delegator",
                "implementationCrosswalk": ("authority_and_delegation",),
                "partialImplementationReason": "Configured owner reference is resolved to an exact tenant entity and joined only to an exact tenant graph OWNS or OWNS_AGENT edge targeting the resolved canonical Agent. Legal or effective ownership, action authorization, historical validity, graph completeness, and freshness remain unknown.",
                "projectionBindings": [
                    {
                        "projectionId": "agent360",
                        "role": "primary",
                        "subjectKinds": ("agent", "entity"),
                        "sectionIds": ("evidence", "state")
                    }
                ],
                "requiredFrameMetadata": ("slotActorAttribution",),
                "requirement": "required"
            },
            {
                "canonicalAuthorityRefs": ("agent_access", "agent_executions", "delegations", "entities", "identity"),
                "description": "Exact stored active delegation scopes and recorded execution-scoped policy decisions; complete standing agent policy and a new action decision remain unknown.",
                "id": "policy_boundary",
                "implementationCrosswalk": ("authority_and_delegation",),
                "partialImplementationReason": "current_repository_active_delegation_scopes_are_bounded_and_may_lag_revocation; non_delegation_policy_historical_replay_and_new_action_authorization_remain_unknown",
                "projectionBindings": [
                    {
                        "projectionId": "agent360",
                        "role": "primary",
                        "subjectKinds": ("agent", "entity"),
                        "sectionIds": ("policy_boundary",)
                    }
                ],
                "requirement": "required"
            },
            {
                "canonicalAuthorityRefs": ("agent_entities", "identity", "relationship_facts", "risk_outputs", "social_observations"),
                "description": "Required Agent 360 blueprint slot: risk summary.",
                "id": "risk_summary",
                "implementationCrosswalk": ("risk_and_contagion",),
                "partialImplementationReason": "The Agent360 supporting path resolves exact tenant canonical Agent identity before policy-authorized Risk360 and Social360 reads. Social risk-context edges require consent and shared risk-signal evidence and are correlated context only. Agent-specific freshness, historical replay, social observation coverage, and causal contagion remain unknown.",
                "projectionBindings": [
                    {
                        "projectionId": "agent360",
                        "role": "supporting",
                        "subjectKinds": ("agent", "entity"),
                        "sectionIds": ("state",)
                    },
                    {
                        "projectionId": "risk360",
                        "role": "primary",
                        "subjectKinds": ("agent", "entity"),
                        "sectionIds": ("evidence", "findings")
                    }
                ],
                "requirement": "required"
            },
            {
                "canonicalAuthorityRefs": ("graph", "relationship_facts", "temporal"),
                "description": "Required Agent 360 blueprint slot: spawned agents.",
                "id": "spawned_agents",
                "implementationCrosswalk": ("temporal_relationship_context",),
                "projectionBindings": [
                    {
                        "projectionId": "relationship360",
                        "role": "primary",
                        "subjectKinds": ("agent", "entity"),
                        "sectionIds": ("agent_spawned_agents",)
                    }
                ],
                "requirement": "required"
            },
            {
                "canonicalAuthorityRefs": ("actions", "resources", "tools"),
                "description": "Required Agent 360 blueprint slot: tool usage.",
                "id": "tool_usage",
                "implementationCrosswalk": ("actions_tools_resources",),
                "projectionBindings": [
                    {
                        "projectionId": "execution360",
                        "role": "primary",
                        "subjectKinds": ("agent", "entity"),
                        "sectionIds": ("evidence", "interactions")
                    }
                ],
                "requirement": "required"
            }
        ],
        "freshnessPolicy": {
            "required": True,
            "maxAgeSeconds": None,
            "sourceTimestamps": "preserve",
            "missingTimestamp": "unknown",
            "onStale": "mark_affected_slots_stale",
            "requirementStatus": "contract_requirement_not_provider_attestation"
        },
        "id": "agent360",
        "lensContract": {
            "expectedCount": 8,
            "lensIds": ("agentic", "authority", "execution", "identity", "policy", "provenance", "relationship", "risk"),
            "sourceAlignmentStatus": "source_aligned"
        },
        "policyBehavior": {
            "tenantScopeRequired": True,
            "authorizationBeforeRead": True,
            "policyEvaluation": "per_projection_before_composition",
            "historicalConsentEvaluation": "required_when_applicable",
            "redactionBehavior": "suppress_disallowed_slot_without_inference",
            "requirementStatus": "contract_requirement_not_provider_attestation"
        },
        "projectionBindings": [
            {
                "projectionId": "agent360",
                "role": "primary",
                "bindingStatus": "catalog_only",
                "providerImplementationState": "in_flight"
            },
            {
                "projectionId": "communication360",
                "role": "primary",
                "bindingStatus": "catalog_only",
                "providerImplementationState": "implemented"
            },
            {
                "projectionId": "economic360",
                "role": "primary",
                "bindingStatus": "catalog_only",
                "providerImplementationState": "implemented"
            },
            {
                "projectionId": "execution360",
                "role": "primary",
                "bindingStatus": "catalog_only",
                "providerImplementationState": "in_flight"
            },
            {
                "projectionId": "outcome360",
                "role": "primary",
                "bindingStatus": "catalog_only",
                "providerImplementationState": "implemented"
            },
            {
                "projectionId": "relationship360",
                "role": "primary",
                "bindingStatus": "catalog_only",
                "providerImplementationState": "in_flight"
            },
            {
                "projectionId": "risk360",
                "role": "primary",
                "bindingStatus": "catalog_only",
                "providerImplementationState": "implemented"
            }
        ],
        "sourceOfTruth": {
            "canonicalAuthorities": ("actions", "agent_access", "agent_entities", "agent_entity", "agent_executions", "ai_execution_facts", "commerce", "communication_facts", "delegations", "economic_facts", "entities", "evidence", "execution_facts", "graph", "identity", "observations", "outcome_facts", "payments", "relationship_facts", "resources", "risk_outputs", "social_observations", "source_provenance", "temporal", "tools"),
            "ownsCanonicalTruth": False,
            "prohibitedOwnership": ("economic_facts", "execution_facts", "graph", "identity", "observations", "risk_outputs", "source_provenance")
        },
        "subjectKinds": ("agent", "entity")
    },
    "campaign360": {
        "backendCapabilities": {
            "required": ("experience360.evidence.provenance", "experience360.frame.compose", "experience360.freshness.evaluate", "experience360.policy.evaluate", "experience360.tenant_scope.enforce"),
            "projectionCapabilityKeys": ("campaign360.explore", "campaign360.read", "communication360.explore", "communication360.read", "economic360.explore", "economic360.read", "outcome360.explore", "outcome360.read"),
            "providerCapabilityStatus": "registry_requirements_not_route_attestation"
        },
        "blueprintContract": {
            "canonicalOwner": "campaign_resolution",
            "priority": "P1",
            "purpose": "Builds campaign state while preserving source classification versus campaign identity and attribution boundaries.",
            "requiredLensIds": ("attribution", "campaign", "communications", "journey", "provenance", "risk", "signals", "value"),
            "requiredSlotIds": ("anomalies", "attribution", "campaign_identity", "cohorts_syndicates", "conversions", "evidence_trace", "journeys", "performance", "signal_sources", "source_classification", "touchpoints"),
            "sourceSection": "11.11",
            "subjectIdentifiers": ("campaign_group_id", "campaign_id", "source_campaign_id")
        },
        "contractStatus": "source_aligned",
        "description": "Governed view of canonical campaign identity, source classification, signals, touchpoints, journeys, conversions, attribution, cohorts, performance, anomalies, and evidence.",
        "displayName": "Campaign 360",
        "domainSlots": [
            {
                "canonicalAuthorityRefs": ("risk_outputs", "source_provenance", "targeting_leakage_findings"),
                "description": "Tenant-scoped targeting leakage findings backed by source observation and eligibility-snapshot evidence, alongside exact campaign Risk360 assessment output; producer coverage and source anomalies stay unknown.",
                "id": "anomalies",
                "partialImplementationReason": "Exact targeting leakage findings and bounded exact-tenant campaign Risk360 assessments are read as separate dimensions with their own evidence. Campaign-specific risk production, complete risk and source-anomaly coverage, history, policy, and freshness remain unknown.",
                "projectionBindings": [
                    {
                        "projectionId": "campaign360",
                        "role": "primary",
                        "subjectKinds": ("campaign",),
                        "sectionIds": ("anomalies",)
                    }
                ],
                "requirement": "required"
            },
            {
                "id": "attribution",
                "requirement": "required",
                "description": "Active, evidence-backed attribution credits associated with the campaign.",
                "canonicalAuthorityRefs": ("attribution_credits",),
                "projectionBindings": [
                    {
                        "projectionId": "campaign360",
                        "role": "primary",
                        "subjectKinds": ("campaign",),
                        "sectionIds": ("evidence", "findings", "outcomes")
                    }
                ]
            },
            {
                "id": "campaign_identity",
                "requirement": "required",
                "description": "Canonical Aether campaign identity and registered state.",
                "canonicalAuthorityRefs": ("campaign_facts",),
                "projectionBindings": [
                    {
                        "projectionId": "campaign360",
                        "role": "primary",
                        "subjectKinds": ("campaign",),
                        "sectionIds": ("evidence", "state", "summary")
                    }
                ]
            },
            {
                "canonicalAuthorityRefs": ("campaign_facts", "campaign_population_link_events", "cluster_definitions", "cluster_membership", "cohort_membership", "population_definitions", "relationship_facts"),
                "description": "Explicit campaign-to-population associations with current versioned cluster definitions and consent-scoped membership evidence where exact tenant records resolve.",
                "id": "cohorts_syndicates",
                "partialImplementationReason": "Explicit links can resolve current exact cluster definition revisions and bounded consent-scoped cluster or cohort memberships backed by live graph ledger replay. A separate policy-authorized read can expose current evidence-backed FOLLOWS edges between consented linked members. Population and roster coverage, other relationship predicates, syndicates, historical membership and freshness remain unknown.",
                "projectionBindings": [
                    {
                        "projectionId": "campaign360",
                        "role": "primary",
                        "subjectKinds": ("campaign",),
                        "sectionIds": ("outcomes",)
                    }
                ],
                "requirement": "required"
            },
            {
                "canonicalAuthorityRefs": ("attribution_credits", "canonical_conversions", "measurement_contract", "outcome_facts"),
                "description": "Exact canonical conversion rows reached through active attribution credits scoped to the canonical campaign, preserving conversion and credit evidence.",
                "id": "conversions",
                "partialImplementationReason": "Only actively attributed exact conversions are visible; unattributed conversions, outcome facts, historical completeness and freshness remain unknown.",
                "projectionBindings": [
                    {
                        "projectionId": "campaign360",
                        "role": "primary",
                        "subjectKinds": ("campaign",),
                        "sectionIds": ("outcomes",)
                    },
                    {
                        "projectionId": "outcome360",
                        "role": "primary",
                        "subjectKinds": ("campaign",),
                        "sectionIds": ("evidence", "outcomes")
                    }
                ],
                "requirement": "required"
            },
            {
                "id": "evidence_trace",
                "requirement": "required",
                "description": "Source evidence references supporting the campaign frame and its claims.",
                "canonicalAuthorityRefs": ("attribution_credits", "campaign_facts", "campaign_touchpoints", "journeys", "touchpoints"),
                "projectionBindings": [
                    {
                        "projectionId": "campaign360",
                        "role": "primary",
                        "subjectKinds": ("campaign",),
                        "sectionIds": ("evidence",)
                    }
                ]
            },
            {
                "id": "journeys",
                "requirement": "required",
                "description": "Current journey versions that explicitly reference this canonical campaign.",
                "canonicalAuthorityRefs": ("journeys",),
                "projectionBindings": [
                    {
                        "projectionId": "campaign360",
                        "role": "primary",
                        "subjectKinds": ("campaign",),
                        "sectionIds": ("evidence", "state")
                    }
                ]
            },
            {
                "canonicalAuthorityRefs": ("ai_execution_facts", "attribution_credits", "canonical_conversions", "commerce", "economic_facts", "outcome_facts", "payments", "spend_records"),
                "description": "Exact active-attribution conversion revenue and bounded campaign spend ledger observations, with incomplete aggregates left unknown.",
                "id": "performance",
                "partialImplementationReason": "Spend ledger lacks a coverage watermark, so spend totals, ROAS and ROI are unknown. Only complete active-credit conversion joins yield currency-scoped attributed revenue; unattributed conversions and adjusted-after-run amounts remain unknown.",
                "projectionBindings": [
                    {
                        "projectionId": "campaign360",
                        "role": "supporting",
                        "subjectKinds": ("campaign",),
                        "sectionIds": ("state",)
                    },
                    {
                        "projectionId": "economic360",
                        "role": "primary",
                        "subjectKinds": ("campaign",),
                        "sectionIds": ("evidence", "outcomes", "summary")
                    }
                ],
                "requirement": "required"
            },
            {
                "canonicalAuthorityRefs": ("events", "observations", "source_facts"),
                "description": "Tenant-scoped signal and source observations associated with the campaign.",
                "id": "signal_sources",
                "partialImplementationReason": "Exact campaign touchpoint event references join tenant-scoped canonical events, matching gateway-admitted SDK Bronze observations, and verified current touchpoint classification revisions as source facts. Broader observation and source-fact producers, complete event coverage, and a freshness SLA remain unresolved.",
                "projectionBindings": [
                    {
                        "projectionId": "campaign360",
                        "role": "primary",
                        "subjectKinds": ("campaign",),
                        "sectionIds": ("state",)
                    }
                ],
                "requirement": "required"
            },
            {
                "canonicalAuthorityRefs": ("campaign_touchpoints", "source_facts", "source_provenance"),
                "description": "Canonical classification of the source that asserted or synchronized campaign evidence.",
                "id": "source_classification",
                "partialImplementationReason": "Exact current tenant touchpoint classification revisions are read and verified against the touchpoint classification pointer, class, classifier version, and time. Only classified touchpoints on the requested page are joined; campaign registry provenance and other asserting sources remain unknown.",
                "projectionBindings": [
                    {
                        "projectionId": "campaign360",
                        "role": "primary",
                        "subjectKinds": ("campaign",),
                        "sectionIds": ("evidence", "state")
                    }
                ],
                "requirement": "required"
            },
            {
                "id": "touchpoints",
                "requirement": "required",
                "description": "Campaign touchpoints with linked, policy-governed communication evidence.",
                "canonicalAuthorityRefs": ("campaign_touchpoints", "communication_facts", "touchpoints"),
                "projectionBindings": [
                    {
                        "projectionId": "campaign360",
                        "role": "primary",
                        "subjectKinds": ("campaign",),
                        "sectionIds": ("evidence", "state")
                    },
                    {
                        "projectionId": "communication360",
                        "role": "supporting",
                        "subjectKinds": ("campaign",),
                        "sectionIds": ("evidence", "interactions", "timeline")
                    }
                ]
            }
        ],
        "freshnessPolicy": {
            "required": True,
            "maxAgeSeconds": None,
            "sourceTimestamps": "preserve",
            "missingTimestamp": "unknown",
            "onStale": "mark_affected_slots_stale",
            "requirementStatus": "contract_requirement_not_provider_attestation"
        },
        "id": "campaign360",
        "lensContract": {
            "expectedCount": 8,
            "lensIds": ("attribution", "campaign", "communications", "journey", "provenance", "risk", "signals", "value"),
            "sourceAlignmentStatus": "source_aligned"
        },
        "policyBehavior": {
            "tenantScopeRequired": True,
            "authorizationBeforeRead": True,
            "policyEvaluation": "per_projection_before_composition",
            "historicalConsentEvaluation": "required_when_applicable",
            "redactionBehavior": "suppress_disallowed_slot_without_inference",
            "requirementStatus": "contract_requirement_not_provider_attestation"
        },
        "projectionBindings": [
            {
                "projectionId": "campaign360",
                "role": "primary",
                "bindingStatus": "catalog_only",
                "providerImplementationState": "in_flight"
            },
            {
                "projectionId": "communication360",
                "role": "supporting",
                "bindingStatus": "catalog_only",
                "providerImplementationState": "implemented"
            },
            {
                "projectionId": "economic360",
                "role": "primary",
                "bindingStatus": "catalog_only",
                "providerImplementationState": "implemented"
            },
            {
                "projectionId": "outcome360",
                "role": "primary",
                "bindingStatus": "catalog_only",
                "providerImplementationState": "implemented"
            }
        ],
        "sourceOfTruth": {
            "canonicalAuthorities": ("ai_execution_facts", "attribution_credits", "campaign_facts", "campaign_population_link_events", "campaign_touchpoints", "canonical_conversions", "cluster_definitions", "cluster_membership", "cohort_membership", "commerce", "communication_facts", "economic_facts", "events", "journeys", "measurement_contract", "observations", "outcome_facts", "payments", "population_definitions", "relationship_facts", "risk_outputs", "source_facts", "source_provenance", "spend_records", "targeting_leakage_findings", "touchpoints"),
            "ownsCanonicalTruth": False,
            "prohibitedOwnership": ("economic_facts", "execution_facts", "graph", "identity", "observations", "risk_outputs", "source_provenance")
        },
        "subjectKinds": ("campaign",)
    },
    "commerce360": {
        "backendCapabilities": {
            "required": ("experience360.evidence.provenance", "experience360.frame.compose", "experience360.freshness.evaluate", "experience360.policy.evaluate", "experience360.tenant_scope.enforce"),
            "projectionCapabilityKeys": ("commerce360.read",),
            "providerCapabilityStatus": "registry_requirements_not_route_attestation"
        },
        "blueprintContract": {
            "canonicalOwner": "commerce_product_offer_graph",
            "priority": "P2",
            "purpose": "Composes product, offer, checkout, purchase, and campaign/value relationships for commerce journeys.",
            "requiredLensIds": ("campaign", "commerce", "identity", "journey", "product-offer", "provenance", "risk", "value"),
            "requiredSlotIds": ("availability_price", "campaign_links", "cart_checkout", "catalog_links", "evidence_trace", "exposures", "intent", "product_offer_summary", "purchase", "risk", "value"),
            "sourceSection": "11.17",
            "subjectIdentifiers": ("checkout_id", "commerce_id", "offer_id", "product_id", "sku_id")
        },
        "contractStatus": "source_aligned",
        "description": "Governed view of commerce and payment facts, economic value, attributed outcomes, and supporting evidence.",
        "displayName": "Commerce 360",
        "domainSlots": [
            {
                "canonicalAuthorityRefs": ("commerce_product_offer_graph", "source_provenance"),
                "description": "Exact tenant product or offer catalog lifecycle evidence, with inventory availability, current offer price, and freshness represented independently.",
                "id": "availability_price",
                "partialImplementationReason": "Exact tenant product and offer catalog revisions provide lifecycle and provenance evidence only; inventory availability, current offer price, and freshness remain unknown because their authorities and joins are not connected.",
                "projectionBindings": [
                    {
                        "projectionId": "commerce360",
                        "role": "primary",
                        "subjectKinds": ("offer", "product"),
                        "sectionIds": ("availability_price",)
                    }
                ],
                "requirement": "required"
            },
            {
                "id": "campaign_links",
                "requirement": "required",
                "description": "Explicit campaign scoped commerce order references.",
                "canonicalAuthorityRefs": ("campaign_facts", "commerce", "source_provenance"),
                "projectionBindings": [
                    {
                        "projectionId": "commerce360",
                        "role": "primary",
                        "subjectKinds": ("campaign",),
                        "sectionIds": ("campaign_links",)
                    }
                ]
            },
            {
                "canonicalAuthorityRefs": ("commerce_product_offer_graph", "silver_commerce_flow_facts", "source_provenance"),
                "description": "Accepted source cart and checkout events with one explicit tenant catalog product or offer key and Silver event evidence.",
                "id": "cart_checkout",
                "partialImplementationReason": "exact_source_asserted_catalog_keyed_cart_checkout_events_only; current_cart_state_purchase_producer_coverage_and_freshness_unknown",
                "projectionBindings": [
                    {
                        "projectionId": "commerce360",
                        "role": "primary",
                        "subjectKinds": ("offer", "product"),
                        "sectionIds": ("cart_checkout",)
                    }
                ],
                "requirement": "required"
            },
            {
                "canonicalAuthorityRefs": ("commerce_product_offer_graph", "source_provenance"),
                "description": "Offer to product links from exact tenant-scoped catalog revisions.",
                "id": "catalog_links",
                "partialImplementationReason": "catalog_link_coverage_is_limited_to_persisted_product_offer_revisions_and_freshness_sla_is_unconfigured",
                "projectionBindings": [
                    {
                        "projectionId": "commerce360",
                        "role": "primary",
                        "subjectKinds": ("offer", "product"),
                        "sectionIds": ("catalog_links",)
                    }
                ],
                "requirement": "required"
            },
            {
                "id": "evidence_trace",
                "requirement": "required",
                "description": "Source evidence for exact scoped commerce facts.",
                "canonicalAuthorityRefs": ("commerce", "commerce_intent_authority", "commerce_product_offer_graph", "payments", "silver_commerce_flow_facts", "silver_exposure_facts", "source_provenance"),
                "projectionBindings": [
                    {
                        "projectionId": "commerce360",
                        "role": "primary",
                        "subjectKinds": ("campaign", "entity", "journey", "offer", "product"),
                        "sectionIds": ("evidence_trace",)
                    }
                ]
            },
            {
                "canonicalAuthorityRefs": ("commerce_product_offer_graph", "silver_exposure_facts", "source_provenance"),
                "description": "Accepted source exposure observations with an explicit tenant catalog product or offer key and Silver event evidence.",
                "id": "exposures",
                "partialImplementationReason": "exact_source_asserted_product_offer_exposure_events_only; producer_coverage_effect_and_freshness_unknown",
                "projectionBindings": [
                    {
                        "projectionId": "commerce360",
                        "role": "primary",
                        "subjectKinds": ("offer", "product"),
                        "sectionIds": ("exposures",)
                    }
                ],
                "requirement": "required"
            },
            {
                "canonicalAuthorityRefs": ("commerce_intent_authority", "commerce_product_offer_graph", "source_provenance"),
                "description": "Explicit tenant-owned intent records joined to an exact product or offer subject, with actor, source revision, timestamps, and evidence.",
                "id": "intent",
                "partialImplementationReason": "explicit_intent_subject_join_is_implemented_for_product_and_offer_only; commerce_sku_and_checkout_authorities_are_not_connected; freshness_threshold_is_unconfigured",
                "projectionBindings": [
                    {
                        "projectionId": "commerce360",
                        "role": "primary",
                        "subjectKinds": ("offer", "product"),
                        "sectionIds": ("intent",)
                    }
                ],
                "requirement": "required"
            },
            {
                "canonicalAuthorityRefs": ("commerce_product_offer_graph", "source_provenance"),
                "description": "Exact tenant-scoped product and offer revisions by canonical product or offer ID.",
                "id": "product_offer_summary",
                "partialImplementationReason": "catalog_source_ingestion_coverage_and_freshness_sla_are_unconfigured",
                "projectionBindings": [
                    {
                        "projectionId": "commerce360",
                        "role": "primary",
                        "subjectKinds": ("offer", "product"),
                        "sectionIds": ("product_offer_summary",)
                    }
                ],
                "requirement": "required"
            },
            {
                "id": "purchase",
                "requirement": "required",
                "description": "Explicit scoped commerce order and payment fact references.",
                "canonicalAuthorityRefs": ("commerce", "payments", "source_provenance"),
                "projectionBindings": [
                    {
                        "projectionId": "commerce360",
                        "role": "primary",
                        "subjectKinds": ("campaign", "entity", "journey"),
                        "sectionIds": ("purchase",)
                    }
                ]
            },
            {
                "canonicalAuthorityRefs": ("risk_outputs",),
                "description": "Required commerce360 slot: risk.",
                "id": "risk",
                "partialImplementationReason": "Current RiskSignal and RiskAssessment rows join only after exact tenant-scoped canonical product or offer resolution; historical coverage, freshness, policy, and causality remain unknown.",
                "projectionBindings": [
                    {
                        "projectionId": "commerce360",
                        "role": "primary",
                        "subjectKinds": ("offer", "product"),
                        "sectionIds": ("risk",)
                    }
                ],
                "requirement": "required"
            },
            {
                "id": "value",
                "requirement": "required",
                "description": "Observed purchase amounts and currency without unsupported aggregation.",
                "canonicalAuthorityRefs": ("payments", "source_provenance"),
                "projectionBindings": [
                    {
                        "projectionId": "commerce360",
                        "role": "primary",
                        "subjectKinds": ("campaign", "entity", "journey"),
                        "sectionIds": ("value",)
                    }
                ]
            }
        ],
        "freshnessPolicy": {
            "required": True,
            "maxAgeSeconds": None,
            "sourceTimestamps": "preserve",
            "missingTimestamp": "unknown",
            "onStale": "mark_affected_slots_stale",
            "requirementStatus": "contract_requirement_not_provider_attestation"
        },
        "id": "commerce360",
        "lensContract": {
            "expectedCount": 8,
            "lensIds": ("campaign", "commerce", "identity", "journey", "product-offer", "provenance", "risk", "value"),
            "sourceAlignmentStatus": "source_aligned"
        },
        "policyBehavior": {
            "tenantScopeRequired": True,
            "authorizationBeforeRead": True,
            "policyEvaluation": "per_projection_before_composition",
            "historicalConsentEvaluation": "required_when_applicable",
            "redactionBehavior": "suppress_disallowed_slot_without_inference",
            "requirementStatus": "contract_requirement_not_provider_attestation"
        },
        "projectionBindings": [
            {
                "projectionId": "commerce360",
                "role": "primary",
                "bindingStatus": "catalog_only",
                "providerImplementationState": "in_flight"
            }
        ],
        "sourceOfTruth": {
            "canonicalAuthorities": ("campaign_facts", "commerce", "commerce_intent_authority", "commerce_product_offer_graph", "payments", "risk_outputs", "silver_commerce_flow_facts", "silver_exposure_facts", "source_provenance"),
            "ownsCanonicalTruth": False,
            "prohibitedOwnership": ("economic_facts", "execution_facts", "graph", "identity", "observations", "risk_outputs", "source_provenance")
        },
        "subjectKinds": ("campaign", "checkout", "commerce", "entity", "journey", "offer", "product", "sku")
    },
    "communications360": {
        "backendCapabilities": {
            "required": ("experience360.evidence.provenance", "experience360.frame.compose", "experience360.freshness.evaluate", "experience360.policy.evaluate", "experience360.tenant_scope.enforce"),
            "projectionCapabilityKeys": ("communication360.explore", "communication360.read"),
            "providerCapabilityStatus": "registry_requirements_not_route_attestation"
        },
        "blueprintContract": {
            "canonicalOwner": "communications_graph",
            "priority": "P0",
            "purpose": "Attaches email/message/campaign communications to profiles, journeys, campaigns, episodes, and agent/human authorship evidence.",
            "requiredLensIds": ("campaign", "communications", "identity", "journey", "policy", "provenance", "risk"),
            "requiredSlotIds": ("agent_authorship", "campaign_links", "evidence_trace", "journey_links", "message_inventory", "participants", "policy_state", "profile_links", "response_events", "risk_flags", "thread_summary"),
            "sourceSection": "11.7",
            "subjectIdentifiers": ("campaign_id", "episode_id", "message_id", "profile_id", "thread_id")
        },
        "contractStatus": "source_aligned",
        "description": "Governed view of communication facts, delivery and engagement evidence, campaign and journey context, and applicable consent policy.",
        "displayName": "Communications 360",
        "domainSlots": [
            {
                "canonicalAuthorityRefs": ("communication_facts", "delegations", "entities"),
                "description": "Observed agent author bindings with exact event-time delegation decisions when tenant, parties, provider reference, and communication scope resolve.",
                "id": "agent_authorship",
                "partialImplementationReason": "Event-time delegation is read only for bounded exact agent author bindings. Provider grant references without a unique canonical metadata match remain unknown; complete author roster, current action authority, and freshness remain unproven.",
                "projectionBindings": [
                    {
                        "projectionId": "communication360",
                        "role": "primary",
                        "subjectKinds": ("agent",),
                        "sectionIds": ("evidence", "interactions")
                    }
                ],
                "requirement": "required"
            },
            {
                "id": "campaign_links",
                "requirement": "required",
                "description": "Explicit campaign scoped communication and touchpoint refs.",
                "canonicalAuthorityRefs": ("campaign_touchpoints", "communication_facts"),
                "projectionBindings": [
                    {
                        "projectionId": "communication360",
                        "role": "primary",
                        "subjectKinds": ("campaign",),
                        "sectionIds": ("evidence", "state")
                    }
                ]
            },
            {
                "id": "evidence_trace",
                "requirement": "required",
                "description": "Communication fact and message evidence with partial source provenance.",
                "canonicalAuthorityRefs": ("communication_facts", "evidence"),
                "projectionBindings": [
                    {
                        "projectionId": "communication360",
                        "role": "primary",
                        "subjectKinds": ("agent", "campaign"),
                        "sectionIds": ("evidence",)
                    }
                ]
            },
            {
                "canonicalAuthorityRefs": ("communication_facts", "journeys"),
                "description": "Explicit journey references on in-scope communication facts resolved to current tenant journey versions.",
                "id": "journey_links",
                "partialImplementationReason": "current_explicit_journey_references_only_no_historical_replay",
                "projectionBindings": [
                    {
                        "projectionId": "communication360",
                        "role": "primary",
                        "subjectKinds": ("agent", "campaign", "episode", "journey", "source"),
                        "sectionIds": ("evidence", "summary")
                    }
                ],
                "requirement": "required"
            },
            {
                "id": "message_inventory",
                "requirement": "required",
                "description": "Bounded observed message entries with message evidence.",
                "canonicalAuthorityRefs": ("communication_facts", "evidence"),
                "projectionBindings": [
                    {
                        "projectionId": "communication360",
                        "role": "primary",
                        "subjectKinds": ("agent", "campaign"),
                        "sectionIds": ("evidence", "timeline")
                    }
                ]
            },
            {
                "canonicalAuthorityRefs": ("communication_facts", "entities", "evidence", "identity"),
                "description": "Typed, source-authenticated participant role bindings joined through exact tenant-owned provider identity mappings; canonical conversation membership remains unresolved.",
                "id": "participants",
                "partialImplementationReason": "participant_roles_are_observed_from_signed_provider_rosters_and_exact_tenant_identity_mappings_but_canonical_conversation_membership_and_full_message_coverage_are_unresolved; provider_delegation_refs_are_not_canonical_grants",
                "projectionBindings": [
                    {
                        "projectionId": "communication360",
                        "role": "primary",
                        "subjectKinds": ("agent", "campaign"),
                        "sectionIds": ("interactions",)
                    }
                ],
                "requirement": "required"
            },
            {
                "canonicalAuthorityRefs": ("communication_facts", "consent_policy_decisions", "evidence"),
                "description": "Current server-consent decisions for exact tenant-scoped recipient and purpose pairs, separated from historical communication-time decisions.",
                "id": "policy_state",
                "implementationCrosswalk": ("communication_current_consent_policy_state",),
                "partialImplementationReason": "Current consent is evaluated only for exact tenant, recipient-entity, and purpose pairs supported by communication identity and evidence. Historical write-time outcomes are separate; non-consent policy, durable current-decision evidence, complete recipient coverage, and freshness remain unknown.",
                "projectionBindings": [
                    {
                        "projectionId": "communication360",
                        "role": "primary",
                        "subjectKinds": ("agent", "campaign", "episode", "journey", "source"),
                        "sectionIds": ("summary",)
                    }
                ],
                "requirement": "required"
            },
            {
                "canonicalAuthorityRefs": ("communication_facts", "entity_registry", "evidence", "identity"),
                "description": "Explicit profile identifiers on evidence-backed communication facts resolved against exact tenant profile records and the same canonical human entity.",
                "id": "profile_links",
                "partialImplementationReason": "Evidence-backed communication profile references now require both an exact tenant profile record and an exact same-ID canonical human entity record. Alias and independently keyed profile/entity identities, historical binding validity, complete link coverage, and freshness remain unknown.",
                "projectionBindings": [
                    {
                        "projectionId": "communication360",
                        "role": "primary",
                        "subjectKinds": ("agent", "campaign", "episode", "journey", "source"),
                        "sectionIds": ("evidence", "summary")
                    }
                ],
                "requirement": "required"
            },
            {
                "canonicalAuthorityRefs": ("communication", "communication_facts", "evidence", "identity"),
                "description": "Response-like canonical communication acts joined to exact tenant-scoped message and authenticated sender identity where available.",
                "id": "response_events",
                "partialImplementationReason": "Only bounded exact act-to-message and sender joins are observed. Reply target, causal response outcome, complete message history, and source freshness remain unknown.",
                "projectionBindings": [
                    {
                        "projectionId": "communication360",
                        "role": "primary",
                        "subjectKinds": ("agent", "campaign"),
                        "sectionIds": ("interactions",)
                    }
                ],
                "requirement": "required"
            },
            {
                "canonicalAuthorityRefs": ("communication_facts", "consent_policy_decisions", "evidence", "identity", "risk_assessments", "risk_outputs", "risk_signals"),
                "description": "Exact-subject canonical RiskSignal and RiskAssessment observations for resolved agents and sources and mapped recipient entities after current analytics consent; message-edge propagation is never inferred.",
                "id": "risk_flags",
                "partialImplementationReason": "Source, recipient, and resolved-agent RiskSignal and RiskAssessment reads require current analytics consent and exact tenant identity evidence. Assessment output remains attached only to its assessed subject; message-edge transfer, communication-specific composite risk, historical and producer coverage, and freshness remain unknown.",
                "projectionBindings": [
                    {
                        "projectionId": "communication360",
                        "role": "primary",
                        "subjectKinds": ("agent", "source"),
                        "sectionIds": ("evidence", "summary")
                    }
                ],
                "requirement": "required"
            },
            {
                "id": "thread_summary",
                "requirement": "required",
                "description": "Partial thread counts and canonical thread facts; message-thread composition is incomplete.",
                "canonicalAuthorityRefs": ("communication_facts",),
                "projectionBindings": [
                    {
                        "projectionId": "communication360",
                        "role": "primary",
                        "subjectKinds": ("agent", "campaign"),
                        "sectionIds": ("interactions", "summary")
                    }
                ]
            }
        ],
        "freshnessPolicy": {
            "required": True,
            "maxAgeSeconds": None,
            "sourceTimestamps": "preserve",
            "missingTimestamp": "unknown",
            "onStale": "mark_affected_slots_stale",
            "requirementStatus": "contract_requirement_not_provider_attestation"
        },
        "id": "communications360",
        "lensContract": {
            "expectedCount": 7,
            "lensIds": ("campaign", "communications", "identity", "journey", "policy", "provenance", "risk"),
            "sourceAlignmentStatus": "source_aligned"
        },
        "policyBehavior": {
            "tenantScopeRequired": True,
            "authorizationBeforeRead": True,
            "policyEvaluation": "per_projection_before_composition",
            "historicalConsentEvaluation": "required_when_applicable",
            "redactionBehavior": "suppress_disallowed_slot_without_inference",
            "requirementStatus": "contract_requirement_not_provider_attestation"
        },
        "projectionBindings": [
            {
                "projectionId": "communication360",
                "role": "primary",
                "bindingStatus": "catalog_only",
                "providerImplementationState": "implemented"
            }
        ],
        "sourceOfTruth": {
            "canonicalAuthorities": ("campaign_touchpoints", "communication", "communication_facts", "consent_policy_decisions", "delegations", "entities", "entity_registry", "evidence", "identity", "journeys", "risk_assessments", "risk_outputs", "risk_signals"),
            "ownsCanonicalTruth": False,
            "prohibitedOwnership": ("economic_facts", "execution_facts", "graph", "identity", "observations", "risk_outputs", "source_provenance")
        },
        "subjectKinds": ("agent", "campaign", "episode", "journey", "message", "profile", "source", "thread")
    },
    "episode360": {
        "backendCapabilities": {
            "required": ("experience360.evidence.provenance", "experience360.frame.compose", "experience360.freshness.evaluate", "experience360.policy.evaluate", "experience360.tenant_scope.enforce"),
            "projectionCapabilityKeys": ("campaign360.explore", "campaign360.read", "communication360.explore", "communication360.read", "episode360.explore", "episode360.read", "profile360.explore", "profile360.read", "relationship360.explore", "relationship360.read"),
            "providerCapabilityStatus": "registry_requirements_not_route_attestation"
        },
        "blueprintContract": {
            "canonicalOwner": "journey_event_reconstruction",
            "priority": "P0",
            "purpose": "Provides the backend reconstruction of a bounded session/activity narrative across humans, agents, communications, and outcomes.",
            "requiredLensIds": ("activity", "campaign", "communications", "identity", "journey", "location", "provenance", "risk"),
            "requiredSlotIds": ("agent_handoffs", "attribution_links", "communications", "conversion_events", "episode_summary", "evidence_trace", "participants", "risk_flags", "sessions", "timeline", "touchpoints"),
            "sourceSection": "11.3",
            "subjectIdentifiers": ("activity_window_id", "conversation_id", "episode_id", "session_id")
        },
        "contractStatus": "source_aligned",
        "description": "Governed time-bounded view of related events and journey activity, with entity context, evidence, and optional outcomes.",
        "displayName": "Episode 360",
        "domainSlots": [
            {
                "canonicalAuthorityRefs": ("agent_executions", "delegations", "episode_facts", "episode_journey_authority_records"),
                "description": "Explicit exact-episode link joining the canonical agent execution, delegation grant and episode source event with persisted evidence.",
                "id": "agent_handoffs",
                "partialImplementationReason": "Only recorded exact links are projected; complete handoff inventory, current delegation authorization, policy and freshness remain unknown.",
                "projectionBindings": [
                    {
                        "projectionId": "episode360",
                        "role": "primary",
                        "subjectKinds": ("episode",),
                        "sectionIds": ("evidence", "interactions")
                    }
                ],
                "requirement": "required"
            },
            {
                "canonicalAuthorityRefs": ("attribution_credits", "attribution_runs", "canonical_conversions", "episode_facts", "episode_journey_authority_records", "outcome_facts"),
                "description": "Explicit exact-episode and outcome link joining canonical conversion, attribution run and credit evidence.",
                "id": "attribution_links",
                "partialImplementationReason": "Only recorded exact links are projected; complete attribution inventory, current credit policy and freshness remain unknown.",
                "projectionBindings": [
                    {
                        "projectionId": "episode360",
                        "role": "primary",
                        "subjectKinds": ("episode",),
                        "sectionIds": ("evidence", "outcomes")
                    }
                ],
                "requirement": "required"
            },
            {
                "canonicalAuthorityRefs": ("communication_facts",),
                "description": "Bounded exact tenant episode_id or episode_ids-linked canonical communication facts with event-time and anchored receipt-time filtering; message history and complete conversation membership remain unavailable.",
                "id": "communications",
                "partialImplementationReason": "Episode communication facts join by exact typed episode references and preserve evidence, but this does not establish complete message or conversation coverage, source freshness, or provider policy evaluation.",
                "projectionBindings": [
                    {
                        "projectionId": "communication360",
                        "role": "supporting",
                        "subjectKinds": ("episode",),
                        "sectionIds": ("interactions",)
                    }
                ],
                "requirement": "required"
            },
            {
                "canonicalAuthorityRefs": ("episode_facts", "evidence", "outcome_facts"),
                "description": "Canonical conversion outcomes explicitly referenced by exact tenant episode records; only registered conversion definitions are admitted.",
                "id": "conversion_events",
                "partialImplementationReason": "Only outcome IDs explicitly recorded by tenant episode rows are joined and admitted for registered campaign_conversion or journey_completion definitions with canonical evidence; these references do not establish complete coverage or causal attribution, and freshness and policy remain unknown.",
                "projectionBindings": [
                    {
                        "projectionId": "episode360",
                        "role": "primary",
                        "subjectKinds": ("episode",),
                        "sectionIds": ("outcomes",)
                    }
                ],
                "requirement": "required"
            },
            {
                "id": "entity_and_relationship_context",
                "requirement": "optional",
                "description": "Canonical identity for entity and episode subjects, campaign identity for campaign subjects, and graph relationships where the subject has a supported entity graph.",
                "canonicalAuthorityRefs": ("campaign_facts", "episode_facts", "graph", "identity", "relationship_facts"),
                "projectionBindings": [
                    {
                        "projectionId": "campaign360",
                        "role": "primary",
                        "subjectKinds": ("campaign",),
                        "sectionIds": ("evidence", "state", "summary")
                    },
                    {
                        "projectionId": "episode360",
                        "role": "supporting",
                        "subjectKinds": ("campaign", "entity", "episode"),
                        "sectionIds": ("episode_context",)
                    },
                    {
                        "projectionId": "profile360",
                        "role": "primary",
                        "subjectKinds": ("entity", "episode"),
                        "sectionIds": ("evidence", "state", "summary")
                    },
                    {
                        "projectionId": "relationship360",
                        "role": "supporting",
                        "subjectKinds": ("entity", "episode"),
                        "sectionIds": ("evidence", "interactions")
                    }
                ]
            },
            {
                "id": "episode_summary",
                "requirement": "required",
                "description": "Exact tenant episode record with evidence lineage.",
                "canonicalAuthorityRefs": ("episode_facts", "evidence"),
                "projectionBindings": [
                    {
                        "projectionId": "episode360",
                        "role": "primary",
                        "subjectKinds": ("episode",),
                        "sectionIds": ("evidence", "summary")
                    }
                ]
            },
            {
                "id": "evidence_trace",
                "requirement": "required",
                "description": "Episode record and lineage refs; source event provenance is partial.",
                "canonicalAuthorityRefs": ("episode_facts", "evidence"),
                "projectionBindings": [
                    {
                        "projectionId": "episode360",
                        "role": "primary",
                        "subjectKinds": ("episode",),
                        "sectionIds": ("evidence",)
                    }
                ]
            },
            {
                "id": "participants",
                "requirement": "required",
                "description": "Primary user or agent subject reference only; full participant resolution is pending.",
                "canonicalAuthorityRefs": ("episode_facts",),
                "projectionBindings": [
                    {
                        "projectionId": "episode360",
                        "role": "primary",
                        "subjectKinds": ("episode",),
                        "sectionIds": ("episode_context", "interactions")
                    }
                ]
            },
            {
                "canonicalAuthorityRefs": ("episode_facts", "risk_signals"),
                "description": "Current canonical RiskSignals for an exact tenant episode primary subject; no episode-to-risk causality is inferred.",
                "id": "risk_flags",
                "partialImplementationReason": "Only current RiskSignals for the exact typed primary subject of one tenant-scoped EpisodeRecord are joined; risk history, complete signal coverage, policy, freshness, and causality remain unknown.",
                "projectionBindings": [
                    {
                        "projectionId": "episode360",
                        "role": "primary",
                        "subjectKinds": ("episode",),
                        "sectionIds": ("risk_flags",)
                    }
                ],
                "requirement": "required"
            },
            {
                "id": "sessions",
                "requirement": "required",
                "description": "Primary session reference only; session inventory is pending.",
                "canonicalAuthorityRefs": ("episode_facts",),
                "projectionBindings": [
                    {
                        "projectionId": "episode360",
                        "role": "primary",
                        "subjectKinds": ("episode",),
                        "sectionIds": ("episode_context",)
                    }
                ]
            },
            {
                "canonicalAuthorityRefs": ("episode_facts", "episode_journey_authority_records", "evidence", "silver_semantic_observations", "temporal"),
                "description": "Typed episode observation references joined by exact tenant, source namespace, observation ID, source event, association time, and semantic Silver evidence within bounded temporal context.",
                "id": "timeline",
                "partialImplementationReason": "Only explicitly authored typed observation references are resolved against exact semantic Silver event, namespace, timestamp, and evidence fields. EpisodeEngine can produce the exact typed link when its caller supplies a semantic observation authority marker, but no live semantic-to-episode association caller is connected. Legacy Silver rows without authenticated source namespace remain unknown; broader activity/session completeness, source freshness, and policy remain unverified.",
                "projectionBindings": [
                    {
                        "projectionId": "episode360",
                        "role": "primary",
                        "subjectKinds": ("episode",),
                        "sectionIds": ("timeline",)
                    }
                ],
                "requirement": "required"
            },
            {
                "canonicalAuthorityRefs": ("campaign_touchpoints", "episode_facts"),
                "description": "Exact tenant touchpoints explicitly linked by canonical episode records; journey touchpoints remain separate from attribution credits.",
                "id": "touchpoints",
                "partialImplementationReason": "Only journey_touchpoint_ids explicitly recorded by tenant-scoped EpisodeRecords are resolved to canonical touchpoint rows with evidence. Legacy records, incomplete link inventories, freshness, policy, and attribution links remain unknown.",
                "projectionBindings": [
                    {
                        "projectionId": "episode360",
                        "role": "primary",
                        "subjectKinds": ("episode",),
                        "sectionIds": ("interactions",)
                    }
                ],
                "requirement": "required"
            }
        ],
        "freshnessPolicy": {
            "required": True,
            "maxAgeSeconds": None,
            "sourceTimestamps": "preserve",
            "missingTimestamp": "unknown",
            "onStale": "mark_affected_slots_stale",
            "requirementStatus": "contract_requirement_not_provider_attestation"
        },
        "id": "episode360",
        "lensContract": {
            "expectedCount": 8,
            "lensIds": ("activity", "campaign", "communications", "identity", "journey", "location", "provenance", "risk"),
            "sourceAlignmentStatus": "source_aligned"
        },
        "policyBehavior": {
            "tenantScopeRequired": True,
            "authorizationBeforeRead": True,
            "policyEvaluation": "per_projection_before_composition",
            "historicalConsentEvaluation": "required_when_applicable",
            "redactionBehavior": "suppress_disallowed_slot_without_inference",
            "requirementStatus": "contract_requirement_not_provider_attestation"
        },
        "projectionBindings": [
            {
                "projectionId": "campaign360",
                "role": "primary",
                "bindingStatus": "catalog_only",
                "providerImplementationState": "in_flight"
            },
            {
                "projectionId": "communication360",
                "role": "supporting",
                "bindingStatus": "catalog_only",
                "providerImplementationState": "implemented"
            },
            {
                "projectionId": "episode360",
                "role": "primary",
                "bindingStatus": "catalog_only",
                "providerImplementationState": "in_flight"
            },
            {
                "projectionId": "profile360",
                "role": "primary",
                "bindingStatus": "catalog_only",
                "providerImplementationState": "in_flight"
            },
            {
                "projectionId": "relationship360",
                "role": "supporting",
                "bindingStatus": "catalog_only",
                "providerImplementationState": "in_flight"
            }
        ],
        "sourceOfTruth": {
            "canonicalAuthorities": ("agent_executions", "attribution_credits", "attribution_runs", "campaign_facts", "campaign_touchpoints", "canonical_conversions", "communication_facts", "delegations", "episode_facts", "episode_journey_authority_records", "evidence", "graph", "identity", "outcome_facts", "relationship_facts", "risk_signals", "silver_semantic_observations", "temporal"),
            "ownsCanonicalTruth": False,
            "prohibitedOwnership": ("economic_facts", "execution_facts", "graph", "identity", "observations", "risk_outputs", "source_provenance")
        },
        "subjectKinds": ("activity_window", "campaign", "conversation", "entity", "episode", "session")
    },
    "execution360": {
        "backendCapabilities": {
            "required": ("experience360.evidence.provenance", "experience360.frame.compose", "experience360.freshness.evaluate", "experience360.policy.evaluate", "experience360.tenant_scope.enforce"),
            "projectionCapabilityKeys": ("execution360.explore", "execution360.read"),
            "providerCapabilityStatus": "registry_requirements_not_route_attestation"
        },
        "blueprintContract": {
            "canonicalOwner": "execution_runtime",
            "priority": "P0",
            "purpose": "Reconstructs who or what drove a backend action, what authority existed, what tools were used, and what outputs or failures occurred.",
            "requiredLensIds": ("agentic", "authority", "execution", "identity", "policy", "provenance", "risk", "value"),
            "requiredSlotIds": ("actor_attribution", "approval_chain", "authority_check", "evidence_trace", "execution_summary", "failures", "inputs_outputs", "latency_cost", "plan_steps", "risk_events", "tool_calls"),
            "sourceSection": "11.2",
            "subjectIdentifiers": ("command_id", "execution_id", "run_id", "tool_call_id", "workflow_run_id")
        },
        "contractStatus": "source_aligned",
        "description": "Governed view of one execution lifecycle, attributed actors and delegation, action/tool/resource activity, evidence, and outcomes.",
        "displayName": "Execution 360",
        "domainSlots": [
            {
                "canonicalAuthorityRefs": ("agent_access", "agent_entities", "identity"),
                "description": "Required Execution 360 blueprint slot: actor attribution.",
                "id": "actor_attribution",
                "implementationCrosswalk": ("actor_and_delegation",),
                "projectionBindings": [
                    {
                        "projectionId": "execution360",
                        "role": "supporting",
                        "subjectKinds": ("agent", "entity", "episode", "execution"),
                        "sectionIds": ("evidence", "state")
                    }
                ],
                "requiredFrameMetadata": ("slotActorAttribution",),
                "requirement": "required"
            },
            {
                "canonicalAuthorityRefs": ("agent_access", "agent_entities", "commerce", "identity"),
                "description": "Exact tenant-scoped x402 commerce approval requests and decisions linked to admitted agent execution records and lifecycle action/resource references where recorded.",
                "id": "approval_chain",
                "implementationCrosswalk": ("actor_and_delegation",),
                "partialImplementationReason": "Execution360 joins exact tenant, admitted execution, approval request, decision, and lifecycle references; stored action/resource conflicts are rejected. Other approval authorities, effective authorization, historical run linkage, full authority-decision coverage, and a freshness threshold remain unknown.",
                "projectionBindings": [
                    {
                        "projectionId": "execution360",
                        "role": "primary",
                        "subjectKinds": ("agent", "entity", "episode", "execution"),
                        "sectionIds": ("interactions",)
                    }
                ],
                "requiredFrameMetadata": ("slotActorAttribution", "slotAuthorityDecision"),
                "requirement": "required"
            },
            {
                "canonicalAuthorityRefs": ("agent_access", "agent_entities", "identity"),
                "description": "Required Execution 360 blueprint slot: authority check.",
                "id": "authority_check",
                "implementationCrosswalk": ("actor_and_delegation",),
                "partialImplementationReason": "New delegation-engine decisions persist an evaluation timestamp in the exact tenant-scoped agent_executions policy log and Execution360 verifies it against execution-record creation time; legacy rows without that timestamp remain unknown. This is request-time application evidence only and does not establish current or standing authority, policy input replay, other authority sources, or freshness.",
                "projectionBindings": [
                    {
                        "projectionId": "execution360",
                        "role": "supporting",
                        "subjectKinds": ("agent", "entity", "episode", "execution"),
                        "sectionIds": ("evidence", "state")
                    }
                ],
                "requiredFrameMetadata": ("slotActorAttribution", "slotAuthorityDecision"),
                "requirement": "required"
            },
            {
                "canonicalAuthorityRefs": ("ai_execution_facts", "evidence", "source_provenance"),
                "description": "Exact execution and invocation evidence, plus bounded Bronze ingress provenance for admitted external telemetry events.",
                "id": "evidence_trace",
                "implementationCrosswalk": ("evidence_and_lineage",),
                "partialImplementationReason": "Exact workflow_run execution references include matching invocation evidence. Admitted external telemetry joins unique same-tenant Bronze event/type/time envelopes for ingress provenance only; registered source identity, external execution receipts, complete source coverage, workflow step coverage, historical replay, and a freshness threshold remain unknown.",
                "projectionBindings": [
                    {
                        "projectionId": "execution360",
                        "role": "primary",
                        "subjectKinds": ("agent", "entity", "episode", "execution", "workflow_run"),
                        "sectionIds": ("evidence",)
                    }
                ],
                "requirement": "required"
            },
            {
                "canonicalAuthorityRefs": ("agent_executions", "ai_execution_facts", "execution_facts"),
                "description": "Required Execution 360 blueprint slot: execution summary.",
                "id": "execution_summary",
                "implementationCrosswalk": ("execution_identity_and_state",),
                "partialImplementationReason": "For workflow_run subjects, execution evidence is limited to tenant-scoped agent_executions rows whose stored workflow_run_id and invocation IDs match current ai_execution_facts; this does not prove all workflow steps, completion, or external effects.",
                "projectionBindings": [
                    {
                        "projectionId": "execution360",
                        "role": "primary",
                        "subjectKinds": ("agent", "entity", "episode", "execution", "workflow_run"),
                        "sectionIds": ("state", "summary")
                    }
                ],
                "requirement": "required"
            },
            {
                "canonicalAuthorityRefs": ("agent_executions", "execution_facts"),
                "description": "Required Execution 360 blueprint slot: failures.",
                "id": "failures",
                "implementationCrosswalk": ("execution_identity_and_state",),
                "projectionBindings": [
                    {
                        "projectionId": "execution360",
                        "role": "primary",
                        "subjectKinds": ("agent", "entity", "episode", "execution"),
                        "sectionIds": ("state", "summary")
                    }
                ],
                "requirement": "required"
            },
            {
                "canonicalAuthorityRefs": ("actions", "agent_executions", "execution_facts", "resources", "tools"),
                "description": "Required Execution 360 blueprint slot: inputs outputs.",
                "id": "inputs_outputs",
                "implementationCrosswalk": ("action_tool_resource_trace", "execution_identity_and_state"),
                "projectionBindings": [
                    {
                        "projectionId": "execution360",
                        "role": "primary",
                        "subjectKinds": ("agent", "entity", "episode", "execution"),
                        "sectionIds": ("evidence", "interactions", "state", "summary", "timeline")
                    }
                ],
                "requirement": "required"
            },
            {
                "canonicalAuthorityRefs": ("agent_executions", "ai_execution_facts", "economic_facts", "execution_facts", "outcome_facts"),
                "description": "Server lifecycle duration and exact action-linked AI invocation latency and selected-cost evidence by currency.",
                "id": "latency_cost",
                "implementationCrosswalk": ("economic_and_business_outcomes", "execution_identity_and_state"),
                "partialImplementationReason": "AI invocation facts are joined only when tenant, execution action_id, and canonical agent match; selected cost is exposed only with a valid known cost basis. This is not provider/tool execution cost or business value. Other cost authorities, historical replay, complete coverage, and a freshness SLA remain unknown.",
                "projectionBindings": [
                    {
                        "projectionId": "execution360",
                        "role": "primary",
                        "subjectKinds": ("agent", "entity", "episode", "execution"),
                        "sectionIds": ("state", "summary")
                    }
                ],
                "requirement": "required"
            },
            {
                "canonicalAuthorityRefs": ("agent_executions", "episode_facts", "events", "execution_facts", "temporal_kernel"),
                "description": "Required Execution 360 blueprint slot: plan steps.",
                "id": "plan_steps",
                "implementationCrosswalk": ("execution_identity_and_state", "temporal_and_episode_context"),
                "projectionBindings": [
                    {
                        "projectionId": "execution360",
                        "role": "primary",
                        "subjectKinds": ("agent", "entity", "episode", "execution"),
                        "sectionIds": ("episode_context", "evidence", "state", "summary", "timeline")
                    }
                ],
                "requirement": "required"
            },
            {
                "canonicalAuthorityRefs": ("agent_executions", "execution_facts", "risk_assessments", "risk_signals"),
                "description": "Bounded current RiskSignals and RiskAssessment snapshots joined by exact tenant/execution subject to lifecycle-admitted executions; producer coverage, assessment history, freshness, and causal attribution remain unknown.",
                "id": "risk_events",
                "implementationCrosswalk": ("execution_identity_and_state",),
                "partialImplementationReason": "bounded_execution_subject_risk_signals_and_assessment_snapshots_joined_to_admitted_lifecycle_executions_producer_coverage_history_freshness_and_causality_unknown",
                "projectionBindings": [
                    {
                        "projectionId": "execution360",
                        "role": "primary",
                        "subjectKinds": ("agent", "entity", "episode", "execution"),
                        "sectionIds": ("interactions",)
                    }
                ],
                "requirement": "required"
            },
            {
                "canonicalAuthorityRefs": ("actions", "resources", "tools"),
                "description": "Tenant-scoped CALLED_TOOL lifecycle edges joined to admitted executions and canonical agent identity; source completeness and external receipt remain unknown.",
                "id": "tool_calls",
                "implementationCrosswalk": ("action_tool_resource_trace",),
                "partialImplementationReason": "Exact lifecycle edges are exposed, but source completeness, authorization outcome, and external execution receipt remain unknown.",
                "projectionBindings": [
                    {
                        "projectionId": "execution360",
                        "role": "primary",
                        "subjectKinds": ("agent", "entity", "episode", "execution"),
                        "sectionIds": ("evidence", "interactions")
                    }
                ],
                "requirement": "required"
            }
        ],
        "freshnessPolicy": {
            "required": True,
            "maxAgeSeconds": None,
            "sourceTimestamps": "preserve",
            "missingTimestamp": "unknown",
            "onStale": "mark_affected_slots_stale",
            "requirementStatus": "contract_requirement_not_provider_attestation"
        },
        "id": "execution360",
        "lensContract": {
            "expectedCount": 8,
            "lensIds": ("agentic", "authority", "execution", "identity", "policy", "provenance", "risk", "value"),
            "sourceAlignmentStatus": "source_aligned"
        },
        "policyBehavior": {
            "tenantScopeRequired": True,
            "authorizationBeforeRead": True,
            "policyEvaluation": "per_projection_before_composition",
            "historicalConsentEvaluation": "required_when_applicable",
            "redactionBehavior": "suppress_disallowed_slot_without_inference",
            "requirementStatus": "contract_requirement_not_provider_attestation"
        },
        "projectionBindings": [
            {
                "projectionId": "execution360",
                "role": "primary",
                "bindingStatus": "catalog_only",
                "providerImplementationState": "in_flight"
            }
        ],
        "sourceOfTruth": {
            "canonicalAuthorities": ("actions", "agent_access", "agent_entities", "agent_executions", "ai_execution_facts", "commerce", "economic_facts", "episode_facts", "events", "evidence", "execution_facts", "identity", "outcome_facts", "resources", "risk_assessments", "risk_signals", "source_provenance", "temporal_kernel", "tools"),
            "ownsCanonicalTruth": False,
            "prohibitedOwnership": ("economic_facts", "execution_facts", "graph", "identity", "observations", "risk_outputs", "source_provenance")
        },
        "subjectKinds": ("agent", "entity", "episode", "execution", "workflow_run")
    },
    "identity360": {
        "backendCapabilities": {
            "required": ("experience360.evidence.provenance", "experience360.frame.compose", "experience360.freshness.evaluate", "experience360.policy.evaluate", "experience360.tenant_scope.enforce"),
            "projectionCapabilityKeys": ("agent360.explore", "agent360.read", "execution360.explore", "execution360.read", "profile360.explore", "profile360.read", "relationship360.explore", "relationship360.read"),
            "providerCapabilityStatus": "registry_requirements_not_route_attestation"
        },
        "blueprintContract": {
            "canonicalOwner": "identity_resolution",
            "priority": "P0",
            "purpose": "Surfaces identity stitching state and evidence while preserving known, unknown, partial, conflict, and degraded identity conditions.",
            "requiredLensIds": ("identity", "location", "policy", "provenance", "risk"),
            "requiredSlotIds": ("aliases", "confidence", "conflicts", "devices_sessions", "evidence_trace", "identifier_inventory", "match_evidence", "namespace_map", "policy_redactions", "wallets"),
            "sourceSection": "11.5",
            "subjectIdentifiers": ("device_id", "identifier_id", "identity_id", "namespace_id", "profile_id", "wallet_id")
        },
        "contractStatus": "source_aligned",
        "description": "Governed view of resolved identities, source identifiers, actor bindings, relationships, and supporting evidence.",
        "directProviderBindings": [
            {
                "bindingStatus": "runtime_wired",
                "canonicalAuthorityRefs": ("entities", "entity_registry", "entity_wallets", "evidence", "identity", "provider_registry", "source_provenance"),
                "domainSlotIds": ("aliases", "confidence", "conflicts", "devices_sessions", "evidence_trace", "identifier_inventory", "match_evidence", "namespace_map", "policy_redactions", "wallets"),
                "implementationRef": "services/api/identity/identity/identity360_provider.py",
                "providerClass": "Identity360Provider",
                "providerKind": "surface_authority_reader",
                "runtimeBindingRef": "services/api/shared/intelligence_projections/frame_runtime.py",
                "subjectKinds": ("agent", "entity", "source")
            }
        ],
        "displayName": "Identity 360",
        "domainSlots": [
            {
                "canonicalAuthorityRefs": ("agent_access", "agent_entities", "agent_entity"),
                "description": "Optional Aether provider context retained for Identity 360: actor and agent binding.",
                "id": "actor_and_agent_binding",
                "implementationCrosswalk": ("actor_and_agent_binding",),
                "projectionBindings": [
                    {
                        "projectionId": "agent360",
                        "role": "primary",
                        "subjectKinds": ("agent", "entity"),
                        "sectionIds": ("evidence", "state")
                    },
                    {
                        "projectionId": "execution360",
                        "role": "supporting",
                        "subjectKinds": ("agent", "entity"),
                        "sectionIds": ("evidence", "state")
                    }
                ],
                "requirement": "optional"
            },
            {
                "canonicalAuthorityRefs": ("evidence", "identity"),
                "description": "Required Identity 360 blueprint slot: aliases.",
                "id": "aliases",
                "implementationCrosswalk": ("identity_evidence",),
                "projectionBindings": [],
                "requirement": "required"
            },
            {
                "canonicalAuthorityRefs": ("evidence", "identity"),
                "description": "Required Identity 360 blueprint slot: confidence.",
                "id": "confidence",
                "implementationCrosswalk": ("identity_evidence",),
                "projectionBindings": [],
                "requirement": "required"
            },
            {
                "canonicalAuthorityRefs": ("evidence", "identity"),
                "description": "Required Identity 360 blueprint slot: conflicts.",
                "id": "conflicts",
                "implementationCrosswalk": ("identity_evidence",),
                "projectionBindings": [],
                "requirement": "required"
            },
            {
                "canonicalAuthorityRefs": ("evidence", "identity", "source_provenance"),
                "description": "Required Identity 360 blueprint slot: devices sessions.",
                "id": "devices_sessions",
                "implementationCrosswalk": ("source_identifier_lineage",),
                "projectionBindings": [],
                "requirement": "required"
            },
            {
                "canonicalAuthorityRefs": ("evidence", "identity", "source_provenance"),
                "description": "Required Identity 360 blueprint slot: evidence trace.",
                "id": "evidence_trace",
                "implementationCrosswalk": ("identity_evidence",),
                "projectionBindings": [],
                "requirement": "required"
            },
            {
                "canonicalAuthorityRefs": ("evidence", "identity", "source_provenance"),
                "description": "Required Identity 360 blueprint slot: identifier inventory.",
                "id": "identifier_inventory",
                "implementationCrosswalk": ("source_identifier_lineage",),
                "projectionBindings": [],
                "requirement": "required"
            },
            {
                "canonicalAuthorityRefs": ("entities", "entity_registry", "evidence", "identity"),
                "description": "Required Identity 360 blueprint slot: match evidence.",
                "id": "match_evidence",
                "implementationCrosswalk": ("identity_evidence",),
                "projectionBindings": [],
                "requirement": "required"
            },
            {
                "canonicalAuthorityRefs": ("evidence", "identity", "provider_registry", "source_provenance"),
                "description": "Maps an exact source-system identity namespace to an already registered provider runtime identity without inferring a provider from namespace prefixes.",
                "id": "namespace_map",
                "implementationCrosswalk": ("source_identifier_lineage",),
                "partialImplementationReason": "Only exact recorded source_system_id values on tenant- and evidence-validated source identities are resolved; missing provider keys remain unknown and provider registry freshness is unavailable.",
                "projectionBindings": [],
                "requirement": "required"
            },
            {
                "canonicalAuthorityRefs": ("evidence", "identity"),
                "description": "Required Identity 360 blueprint slot: policy redactions.",
                "id": "policy_redactions",
                "implementationCrosswalk": ("identity_evidence",),
                "projectionBindings": [],
                "requirement": "required"
            },
            {
                "canonicalAuthorityRefs": ("graph", "relationship_facts"),
                "description": "Optional Aether provider context retained for Identity 360: relationship identity context.",
                "id": "relationship_identity_context",
                "implementationCrosswalk": ("relationship_identity_context",),
                "projectionBindings": [
                    {
                        "projectionId": "relationship360",
                        "role": "primary",
                        "subjectKinds": ("entity",),
                        "sectionIds": ("evidence", "interactions")
                    }
                ],
                "requirement": "optional"
            },
            {
                "canonicalAuthorityRefs": ("entity_registry", "identity"),
                "description": "Optional Aether provider context retained for Identity 360: resolved subject identity.",
                "id": "resolved_subject_identity",
                "implementationCrosswalk": ("resolved_subject_identity",),
                "projectionBindings": [
                    {
                        "projectionId": "profile360",
                        "role": "primary",
                        "subjectKinds": ("agent", "entity"),
                        "sectionIds": ("state", "summary")
                    }
                ],
                "requirement": "optional"
            },
            {
                "canonicalAuthorityRefs": ("entity_wallets", "evidence", "identity", "source_provenance"),
                "description": "Exact canonical-entity wallet inventory joined to historical verification evidence; current wallet control and completeness remain unknown.",
                "id": "wallets",
                "implementationCrosswalk": ("source_identifier_lineage",),
                "partialImplementationReason": "Exact tenant and canonical-entity wallet links are read from entity_wallets, with separate historical verification evidence; current control, complete ownership, and freshness remain unknown.",
                "projectionBindings": [],
                "requirement": "required"
            }
        ],
        "freshnessPolicy": {
            "required": True,
            "maxAgeSeconds": None,
            "sourceTimestamps": "preserve",
            "missingTimestamp": "unknown",
            "onStale": "mark_affected_slots_stale",
            "requirementStatus": "contract_requirement_not_provider_attestation"
        },
        "id": "identity360",
        "lensContract": {
            "expectedCount": 5,
            "lensIds": ("identity", "location", "policy", "provenance", "risk"),
            "sourceAlignmentStatus": "source_aligned"
        },
        "policyBehavior": {
            "tenantScopeRequired": True,
            "authorizationBeforeRead": True,
            "policyEvaluation": "per_projection_before_composition",
            "historicalConsentEvaluation": "required_when_applicable",
            "redactionBehavior": "suppress_disallowed_slot_without_inference",
            "requirementStatus": "contract_requirement_not_provider_attestation"
        },
        "projectionBindings": [
            {
                "projectionId": "agent360",
                "role": "primary",
                "bindingStatus": "catalog_only",
                "providerImplementationState": "in_flight"
            },
            {
                "projectionId": "execution360",
                "role": "supporting",
                "bindingStatus": "catalog_only",
                "providerImplementationState": "in_flight"
            },
            {
                "projectionId": "profile360",
                "role": "primary",
                "bindingStatus": "catalog_only",
                "providerImplementationState": "in_flight"
            },
            {
                "projectionId": "relationship360",
                "role": "primary",
                "bindingStatus": "catalog_only",
                "providerImplementationState": "in_flight"
            }
        ],
        "sourceOfTruth": {
            "canonicalAuthorities": ("agent_access", "agent_entities", "agent_entity", "entities", "entity_registry", "entity_wallets", "evidence", "graph", "identity", "provider_registry", "relationship_facts", "source_provenance"),
            "ownsCanonicalTruth": False,
            "prohibitedOwnership": ("economic_facts", "execution_facts", "graph", "identity", "observations", "risk_outputs", "source_provenance")
        },
        "subjectKinds": ("agent", "entity", "source")
    },
    "journey360": {
        "backendCapabilities": {
            "required": ("experience360.evidence.provenance", "experience360.frame.compose", "experience360.freshness.evaluate", "experience360.policy.evaluate", "experience360.tenant_scope.enforce"),
            "projectionCapabilityKeys": ("communication360.explore", "communication360.read", "episode360.explore", "episode360.read", "profile360.explore", "profile360.read"),
            "providerCapabilityStatus": "registry_requirements_not_route_attestation"
        },
        "blueprintContract": {
            "canonicalOwner": "journey_graph",
            "priority": "P0",
            "purpose": "Composes cross-session journeys while maintaining boundaries between events, touchpoints, conversions, and immutable attribution credits.",
            "requiredLensIds": ("activity", "agentic", "campaign", "communications", "identity", "journey", "location", "risk", "value"),
            "requiredSlotIds": ("agent_interventions", "attribution", "communications", "conversions", "dropoffs", "episodes", "evidence_trace", "journey_summary", "recommended_actions", "stages", "touchpoints"),
            "sourceSection": "11.6",
            "subjectIdentifiers": ("account_id", "campaign_id", "episode_id", "journey_id", "profile_id")
        },
        "contractStatus": "source_aligned",
        "description": "Governed temporal view of journey state, stages, events, handoffs, and measured outcomes.",
        "displayName": "Journey 360",
        "domainSlots": [
            {
                "canonicalAuthorityRefs": ("evidence", "journeys"),
                "description": "Explicit current-journey references to agent-family JourneySteps, with exact step evidence; actor identity, authority, and intervention outcome remain unjoined.",
                "id": "agent_interventions",
                "partialImplementationReason": "Only current journey version activity IDs join to unique, current tenant-scoped agent-family journey steps with version and step evidence. Canonical agent identity, delegated authority, intervention outcome, and full step-inventory completeness remain unknown.",
                "projectionBindings": [
                    {
                        "projectionId": "episode360",
                        "role": "primary",
                        "subjectKinds": ("journey",),
                        "sectionIds": ("interactions",)
                    }
                ],
                "requirement": "required"
            },
            {
                "canonicalAuthorityRefs": ("attribution_credits", "attribution_runs", "canonical_conversions", "journeys", "touchpoints"),
                "description": "Active completed attribution credits linked through a same-tenant run for the exact current JourneyVersion.",
                "id": "attribution",
                "partialImplementationReason": "Only active completed credits from exact same-tenant attribution runs for the current journey version are joined. Recorded conversion and touchpoint IDs resolve only to eligible current exact-tenant rows when their event times do not follow run completion; missing or conflicting rows stay unknown. Inactive and historical runs, subject state at run time, policy, freshness, complete coverage, and causal validity remain unknown.",
                "projectionBindings": [
                    {
                        "projectionId": "episode360",
                        "role": "primary",
                        "subjectKinds": ("journey",),
                        "sectionIds": ("journey_attribution",)
                    }
                ],
                "requirement": "required"
            },
            {
                "canonicalAuthorityRefs": ("communication_facts",),
                "description": "Bounded tenant-scoped canonical communication facts carrying this exact typed journey_id or journey_ids reference.",
                "id": "communications",
                "partialImplementationReason": "Only exact typed journey-linked canonical communication facts are joined. Message-spine coverage, completeness, freshness, and historical replay remain unestablished.",
                "projectionBindings": [
                    {
                        "projectionId": "communication360",
                        "role": "primary",
                        "subjectKinds": ("journey",),
                        "sectionIds": ("evidence", "interactions")
                    }
                ],
                "requirement": "required"
            },
            {
                "canonicalAuthorityRefs": ("canonical_conversions", "journeys"),
                "description": "Canonical conversions explicitly referenced by the current JourneyVersion.",
                "id": "conversions",
                "partialImplementationReason": "Only the current journey version's explicit conversion IDs are resolved; wider conversion inventory and historical versions are not established.",
                "projectionBindings": [
                    {
                        "projectionId": "episode360",
                        "role": "primary",
                        "subjectKinds": ("journey",),
                        "sectionIds": ("outcomes",)
                    }
                ],
                "requirement": "required"
            },
            {
                "canonicalAuthorityRefs": ("episode_journey_authority_records", "events", "evidence", "journeys"),
                "description": "Exact current-version journey abandonment records with evidence-backed journey-step events; missing history does not imply no dropoff.",
                "id": "dropoffs",
                "partialImplementationReason": "Only explicit current-version abandonment records are joined. Complete journey history, causal dropoff reason, permanence, and source freshness remain unknown.",
                "projectionBindings": [
                    {
                        "projectionId": "episode360",
                        "role": "primary",
                        "subjectKinds": ("journey",),
                        "sectionIds": ("evidence", "interactions", "summary")
                    }
                ],
                "requirement": "required"
            },
            {
                "id": "entity_context",
                "requirement": "optional",
                "description": "Resolved linked user-profile context for entity, journey, or episode subjects; parent identity is not substituted for the requested subject.",
                "canonicalAuthorityRefs": ("episode_facts", "graph", "identity", "journeys"),
                "projectionBindings": [
                    {
                        "projectionId": "profile360",
                        "role": "primary",
                        "subjectKinds": ("entity", "episode", "journey"),
                        "sectionIds": ("evidence", "state", "summary")
                    }
                ]
            },
            {
                "canonicalAuthorityRefs": ("episode_facts",),
                "description": "Tenant-scoped episodes that explicitly record the exact journey ID.",
                "id": "episodes",
                "partialImplementationReason": "Only EpisodeRecords with an explicit journey_id are joined through the tenant-scoped episode store. Legacy or unlinked records, association-population completeness, store freshness, policy, and historical replay remain unknown.",
                "projectionBindings": [
                    {
                        "projectionId": "episode360",
                        "role": "primary",
                        "subjectKinds": ("journey",),
                        "sectionIds": ("episode_context",)
                    }
                ],
                "requirement": "required"
            },
            {
                "id": "events_and_episode_context",
                "requirement": "optional",
                "description": "Events and episode facts associated with the journey.",
                "canonicalAuthorityRefs": ("episode_facts", "events"),
                "projectionBindings": [
                    {
                        "projectionId": "episode360",
                        "role": "primary",
                        "subjectKinds": ("entity", "episode", "journey"),
                        "sectionIds": ("evidence", "timeline")
                    }
                ]
            },
            {
                "id": "evidence_trace",
                "requirement": "required",
                "description": "Journey version, step, and exact touchpoint record refs.",
                "canonicalAuthorityRefs": ("campaign_touchpoints", "evidence", "journeys"),
                "projectionBindings": [
                    {
                        "projectionId": "episode360",
                        "role": "primary",
                        "subjectKinds": ("journey",),
                        "sectionIds": ("evidence",)
                    }
                ]
            },
            {
                "canonicalAuthorityRefs": ("journeys",),
                "description": "Exact current JourneyVersion record and version evidence.",
                "id": "journey_summary",
                "partialImplementationReason": "current_version_only_and_source_freshness_threshold_is_unconfigured",
                "projectionBindings": [
                    {
                        "projectionId": "episode360",
                        "role": "primary",
                        "subjectKinds": ("journey",),
                        "sectionIds": ("summary",)
                    }
                ],
                "requirement": "required"
            },
            {
                "authorityGapReason": "A non-executable recommendation record does not join the canonical action execution authority.",
                "canonicalAuthorityRefs": ("actions", "episode_journey_authority_records", "journeys"),
                "description": "Exact current-journey-version non-executable action intent records validated against canonical journey and step evidence.",
                "id": "recommended_actions",
                "partialImplementationReason": "Current-version intents and exact caller-associated agent lifecycle requests are visible after slot policy; action dispatch, external effects, policy replay, outcomes, full recommendation inventory and freshness remain unknown.",
                "projectionBindings": [
                    {
                        "projectionId": "episode360",
                        "role": "primary",
                        "subjectKinds": ("journey",),
                        "sectionIds": ("evidence", "interactions", "summary")
                    }
                ],
                "requirement": "required",
                "unboundCanonicalAuthorityRefs": ("actions",)
            },
            {
                "canonicalAuthorityRefs": ("events", "evidence", "journeys"),
                "description": "Versioned source-role markers on exact current-version journey steps, with typed v3.0 role and event evidence; business stages remain distinct.",
                "id": "stages",
                "partialImplementationReason": "Exact v3.0 role markers and a bounded, fully evidenced current-version marker inventory are available. No canonical business-stage definition or boundary authority exists, so stage taxonomy and stage completeness remain unknown.",
                "projectionBindings": [
                    {
                        "projectionId": "episode360",
                        "role": "primary",
                        "subjectKinds": ("journey",),
                        "sectionIds": ("stages",)
                    }
                ],
                "requirement": "required"
            },
            {
                "id": "touchpoints",
                "requirement": "required",
                "description": "Exact tenant touchpoints named by current JourneyVersion references.",
                "canonicalAuthorityRefs": ("campaign_touchpoints", "journeys"),
                "projectionBindings": [
                    {
                        "projectionId": "episode360",
                        "role": "primary",
                        "subjectKinds": ("journey",),
                        "sectionIds": ("evidence", "timeline")
                    }
                ]
            }
        ],
        "freshnessPolicy": {
            "required": True,
            "maxAgeSeconds": None,
            "sourceTimestamps": "preserve",
            "missingTimestamp": "unknown",
            "onStale": "mark_affected_slots_stale",
            "requirementStatus": "contract_requirement_not_provider_attestation"
        },
        "id": "journey360",
        "lensContract": {
            "expectedCount": 9,
            "lensIds": ("activity", "agentic", "campaign", "communications", "identity", "journey", "location", "risk", "value"),
            "sourceAlignmentStatus": "source_aligned"
        },
        "policyBehavior": {
            "tenantScopeRequired": True,
            "authorizationBeforeRead": True,
            "policyEvaluation": "per_projection_before_composition",
            "historicalConsentEvaluation": "required_when_applicable",
            "redactionBehavior": "suppress_disallowed_slot_without_inference",
            "requirementStatus": "contract_requirement_not_provider_attestation"
        },
        "projectionBindings": [
            {
                "projectionId": "communication360",
                "role": "primary",
                "bindingStatus": "catalog_only",
                "providerImplementationState": "implemented"
            },
            {
                "projectionId": "episode360",
                "role": "primary",
                "bindingStatus": "catalog_only",
                "providerImplementationState": "in_flight"
            },
            {
                "projectionId": "profile360",
                "role": "primary",
                "bindingStatus": "catalog_only",
                "providerImplementationState": "in_flight"
            }
        ],
        "sourceOfTruth": {
            "canonicalAuthorities": ("actions", "attribution_credits", "attribution_runs", "campaign_touchpoints", "canonical_conversions", "communication_facts", "episode_facts", "episode_journey_authority_records", "events", "evidence", "graph", "identity", "journeys", "touchpoints"),
            "ownsCanonicalTruth": False,
            "prohibitedOwnership": ("economic_facts", "execution_facts", "graph", "identity", "observations", "risk_outputs", "source_provenance")
        },
        "subjectKinds": ("account", "campaign", "entity", "episode", "journey", "profile")
    },
    "location360": {
        "backendCapabilities": {
            "required": ("experience360.evidence.provenance", "experience360.frame.compose", "experience360.freshness.evaluate", "experience360.policy.evaluate", "experience360.tenant_scope.enforce"),
            "projectionCapabilityKeys": ("geographic360.explore", "geographic360.read", "population360.explore", "population360.read", "profile360.explore", "profile360.read"),
            "providerCapabilityStatus": "registry_requirements_not_route_attestation"
        },
        "blueprintContract": {
            "canonicalOwner": "geo_temporal_graph",
            "priority": "P1",
            "purpose": "Normalizes place, geography, timezone, and activity projections without over-precise location exposure.",
            "requiredLensIds": ("campaign", "identity", "journey", "location", "provenance", "risk", "signals", "value"),
            "requiredSlotIds": ("activity_density", "campaigns", "evidence_trace", "geo_hierarchy", "journeys", "normalization", "place_summary", "profiles", "risk", "timezone", "value"),
            "sourceSection": "11.14",
            "subjectIdentifiers": ("geohash", "location_id", "place_id", "region_id", "timezone_id")
        },
        "contractStatus": "source_aligned",
        "description": "Governed view of locations and geographic observations linked to entities, populations, and temporal context.",
        "displayName": "Location 360",
        "domainSlots": [
            {
                "canonicalAuthorityRefs": ("geo_observations", "gold_temporal_heatmap"),
                "description": "Tenant-scoped heatmap density bins only when an explicit location_id or source_observation_id names the exact canonical location fact.",
                "id": "activity_density",
                "partialImplementationReason": "Exact-linked heatmap bins carry both Gold and location-fact evidence. Aggregate-only bins remain unknown; location-specific coverage, freshness, and privacy policy evaluation remain unestablished.",
                "projectionBindings": [
                    {
                        "projectionId": "geographic360",
                        "role": "primary",
                        "subjectKinds": ("entity",),
                        "sectionIds": ("state",)
                    }
                ],
                "requirement": "required"
            },
            {
                "canonicalAuthorityRefs": ("campaign_facts", "locations"),
                "description": "Exact campaigns linked to a canonical location fact.",
                "id": "campaigns",
                "partialImplementationReason": "Campaign touchpoints join only by exact location source observation ID; missing touchpoints, full campaign coverage, history, and freshness remain unknown.",
                "projectionBindings": [
                    {
                        "projectionId": "geographic360",
                        "role": "primary",
                        "subjectKinds": ("entity", "population", "source"),
                        "sectionIds": ("state",)
                    }
                ],
                "requirement": "required"
            },
            {
                "id": "entity_graph_context",
                "requirement": "optional",
                "description": "Entity graph context linked to locations.",
                "canonicalAuthorityRefs": ("entity_graph", "graph"),
                "projectionBindings": [
                    {
                        "projectionId": "geographic360",
                        "role": "primary",
                        "subjectKinds": ("entity", "population", "source"),
                        "sectionIds": ("findings", "summary")
                    },
                    {
                        "projectionId": "profile360",
                        "role": "supporting",
                        "subjectKinds": ("entity",),
                        "sectionIds": ("findings", "summary")
                    }
                ]
            },
            {
                "id": "evidence_trace",
                "requirement": "required",
                "description": "Location fact and source observation references at allowed precision.",
                "canonicalAuthorityRefs": ("context_capsules", "locations"),
                "projectionBindings": [
                    {
                        "projectionId": "geographic360",
                        "role": "primary",
                        "subjectKinds": ("entity", "population", "source"),
                        "sectionIds": ("evidence", "state")
                    }
                ]
            },
            {
                "id": "geo_hierarchy",
                "requirement": "required",
                "description": "Recorded geographic labels at source supported precision.",
                "canonicalAuthorityRefs": ("geo_observations", "locations"),
                "projectionBindings": [
                    {
                        "projectionId": "geographic360",
                        "role": "primary",
                        "subjectKinds": ("entity", "population", "source"),
                        "sectionIds": ("evidence", "state")
                    }
                ]
            },
            {
                "id": "geographic_observations",
                "requirement": "optional",
                "description": "Observed geographic facts and their temporal context.",
                "canonicalAuthorityRefs": ("geo_observations", "temporal"),
                "projectionBindings": [
                    {
                        "projectionId": "geographic360",
                        "role": "primary",
                        "subjectKinds": ("entity", "population", "source"),
                        "sectionIds": ("evidence", "timeline")
                    }
                ]
            },
            {
                "canonicalAuthorityRefs": ("journeys", "locations"),
                "description": "Exact journeys linked to a canonical location fact.",
                "id": "journeys",
                "partialImplementationReason": "Current exact entity journey versions are joined only when they cite the location source observation; historical versions, other subject kinds, and complete coverage remain unknown.",
                "projectionBindings": [
                    {
                        "projectionId": "geographic360",
                        "role": "primary",
                        "subjectKinds": ("entity",),
                        "sectionIds": ("state",)
                    }
                ],
                "requirement": "required"
            },
            {
                "id": "location_identity_and_state",
                "requirement": "optional",
                "description": "Location registry and geographic context.",
                "canonicalAuthorityRefs": ("context_capsules", "locations"),
                "projectionBindings": [
                    {
                        "projectionId": "geographic360",
                        "role": "primary",
                        "subjectKinds": ("entity", "population", "source"),
                        "sectionIds": ("evidence", "state", "summary")
                    }
                ]
            },
            {
                "canonicalAuthorityRefs": ("locations",),
                "description": "Canonical location-fact source links, capsule transformation version, and materialization time; raw record and validation lineage are explicit unknowns.",
                "id": "normalization",
                "partialImplementationReason": "Capsule transformation version and location-fact materialization timestamp are recorded separately from schema version. Validation version, raw record reference, complete lineage, and freshness remain unknown.",
                "projectionBindings": [
                    {
                        "projectionId": "geographic360",
                        "role": "primary",
                        "subjectKinds": ("entity", "population", "source"),
                        "sectionIds": ("normalization",)
                    }
                ],
                "requirement": "required"
            },
            {
                "id": "place_summary",
                "requirement": "required",
                "description": "Best supported place fact at policy capped precision.",
                "canonicalAuthorityRefs": ("context_capsules", "geo_observations", "locations"),
                "projectionBindings": [
                    {
                        "projectionId": "geographic360",
                        "role": "primary",
                        "subjectKinds": ("entity", "population", "source"),
                        "sectionIds": ("state", "summary")
                    }
                ]
            },
            {
                "id": "population_context",
                "requirement": "optional",
                "description": "Population context for a location.",
                "canonicalAuthorityRefs": ("cohort_membership", "population_definitions"),
                "projectionBindings": [
                    {
                        "projectionId": "population360",
                        "role": "primary",
                        "subjectKinds": ("entity", "population"),
                        "sectionIds": ("findings", "state", "summary")
                    }
                ]
            },
            {
                "canonicalAuthorityRefs": ("identity", "locations"),
                "description": "Profiles linked to place with profile policy applied.",
                "id": "profiles",
                "partialImplementationReason": "Only exact tenant entity profile records are joined; other location subject kinds, history, complete identity coverage, and freshness remain unknown.",
                "projectionBindings": [
                    {
                        "projectionId": "geographic360",
                        "role": "primary",
                        "subjectKinds": ("entity",),
                        "sectionIds": ("state",)
                    }
                ],
                "requirement": "required"
            },
            {
                "canonicalAuthorityRefs": ("locations", "risk_outputs", "risk_signals"),
                "description": "Risk outputs linked to place with evidence.",
                "id": "risk",
                "partialImplementationReason": "RiskSignals and canonical RiskAssessments join only when exact typed-subject evidence cites the location observation. Assessment output is separate from signal input; causal location risk, producer coverage, history, policy, and freshness remain unknown.",
                "projectionBindings": [
                    {
                        "projectionId": "geographic360",
                        "role": "primary",
                        "subjectKinds": ("entity", "population", "source"),
                        "sectionIds": ("state",)
                    }
                ],
                "requirement": "required"
            },
            {
                "canonicalAuthorityRefs": ("geo_temporal_timezone_assertions", "locations", "temporal"),
                "description": "Verified time zone and temporal conversion evidence.",
                "id": "timezone",
                "partialImplementationReason": "Timezone assertions join exact location facts with effective and recorded time; source assertion coverage, non-geographic projection subjects, and freshness SLA remain unknown.",
                "projectionBindings": [
                    {
                        "projectionId": "geographic360",
                        "role": "primary",
                        "subjectKinds": ("entity", "population", "source"),
                        "sectionIds": ("evidence", "state")
                    }
                ],
                "requirement": "required"
            },
            {
                "canonicalAuthorityRefs": ("economic_facts", "locations"),
                "description": "Economic facts linked to place without subject inference.",
                "id": "value",
                "partialImplementationReason": "Economic facts join only by exact location source observation ID for entity subjects; causal location value, other subject kinds, history, and freshness remain unknown.",
                "projectionBindings": [
                    {
                        "projectionId": "geographic360",
                        "role": "primary",
                        "subjectKinds": ("entity",),
                        "sectionIds": ("state",)
                    }
                ],
                "requirement": "required"
            }
        ],
        "freshnessPolicy": {
            "required": True,
            "maxAgeSeconds": None,
            "sourceTimestamps": "preserve",
            "missingTimestamp": "unknown",
            "onStale": "mark_affected_slots_stale",
            "requirementStatus": "contract_requirement_not_provider_attestation"
        },
        "id": "location360",
        "lensContract": {
            "expectedCount": 8,
            "lensIds": ("campaign", "identity", "journey", "location", "provenance", "risk", "signals", "value"),
            "sourceAlignmentStatus": "source_aligned"
        },
        "policyBehavior": {
            "tenantScopeRequired": True,
            "authorizationBeforeRead": True,
            "policyEvaluation": "per_projection_before_composition",
            "historicalConsentEvaluation": "required_when_applicable",
            "redactionBehavior": "suppress_disallowed_slot_without_inference",
            "requirementStatus": "contract_requirement_not_provider_attestation"
        },
        "projectionBindings": [
            {
                "projectionId": "geographic360",
                "role": "primary",
                "bindingStatus": "catalog_only",
                "providerImplementationState": "implemented"
            },
            {
                "projectionId": "population360",
                "role": "primary",
                "bindingStatus": "catalog_only",
                "providerImplementationState": "implemented"
            },
            {
                "projectionId": "profile360",
                "role": "supporting",
                "bindingStatus": "catalog_only",
                "providerImplementationState": "in_flight"
            }
        ],
        "sourceOfTruth": {
            "canonicalAuthorities": ("campaign_facts", "cohort_membership", "context_capsules", "economic_facts", "entity_graph", "geo_observations", "geo_temporal_timezone_assertions", "gold_temporal_heatmap", "graph", "identity", "journeys", "locations", "population_definitions", "risk_outputs", "risk_signals", "temporal"),
            "ownsCanonicalTruth": False,
            "prohibitedOwnership": ("economic_facts", "execution_facts", "graph", "identity", "observations", "risk_outputs", "source_provenance")
        },
        "subjectKinds": ("entity", "geohash", "location", "place", "population", "region", "source", "timezone")
    },
    "memory360": {
        "backendCapabilities": {
            "required": ("experience360.evidence.provenance", "experience360.frame.compose", "experience360.freshness.evaluate", "experience360.policy.evaluate", "experience360.tenant_scope.enforce"),
            "projectionCapabilityKeys": ("memory360.read",),
            "providerCapabilityStatus": "registry_requirements_not_route_attestation"
        },
        "blueprintContract": {
            "canonicalOwner": "semantic_memory_graph",
            "priority": "P2",
            "purpose": "Backs semantic memory, knowledge cards, topic context, provenance, freshness, and conflict handling.",
            "requiredLensIds": ("identity", "policy", "provenance", "risk", "semantic-memory", "topic"),
            "requiredSlotIds": ("cards", "conflicts", "decay", "embeddings_meta", "evidence_trace", "memories", "policy_state", "semantic_summary", "source_links", "topics"),
            "sourceSection": "11.16",
            "subjectIdentifiers": ("card_id", "memory_id", "semantic_entity_id", "topic_id")
        },
        "contractStatus": "source_aligned",
        "description": "Governed temporal and evidentiary view of entity and agent history, episodes, and observed state; it does not own memory truth.",
        "displayName": "Memory 360",
        "domainSlots": [
            {
                "canonicalAuthorityRefs": ("consent_policy_decisions", "semantic_context_cards", "semantic_memory_records"),
                "description": "Append-only exact tenant/subject context-card records with source-memory evidence and recorded policy disposition.",
                "id": "cards",
                "partialImplementationReason": "Only active same-tenant policy-allowed records project from bounded pages; actor identity resolution, complete producer coverage, historical replay, and freshness thresholds remain unknown.",
                "projectionBindings": [
                    {
                        "projectionId": "memory360",
                        "role": "primary",
                        "subjectKinds": ("entity", "semantic_entity"),
                        "sectionIds": ("cards",)
                    }
                ],
                "requirement": "required"
            },
            {
                "id": "conflicts",
                "requirement": "required",
                "description": "Derived contradiction signal only; canonical conflict objects remain unknown.",
                "canonicalAuthorityRefs": ("semantic_memory_graph",),
                "projectionBindings": [
                    {
                        "projectionId": "memory360",
                        "role": "primary",
                        "subjectKinds": ("entity", "semantic_entity"),
                        "sectionIds": ("conflicts",)
                    }
                ]
            },
            {
                "id": "decay",
                "requirement": "required",
                "description": "Reducer half-life parameter only; per-memory decay remains unknown.",
                "canonicalAuthorityRefs": ("semantic_memory_graph",),
                "projectionBindings": [
                    {
                        "projectionId": "memory360",
                        "role": "primary",
                        "subjectKinds": ("entity", "semantic_entity"),
                        "sectionIds": ("decay",)
                    }
                ]
            },
            {
                "canonicalAuthorityRefs": ("consent_policy_decisions", "semantic_context_cards", "semantic_embedding_metadata"),
                "description": "Append-only exact tenant/subject embedding producer metadata linked through canonical context cards and source evidence.",
                "id": "embeddings_meta",
                "partialImplementationReason": "Metadata is bounded and always degraded when present because vector existence, provider inventory, actor identity resolution, complete producer coverage, and freshness thresholds remain unknown.",
                "projectionBindings": [
                    {
                        "projectionId": "memory360",
                        "role": "primary",
                        "subjectKinds": ("entity", "semantic_entity"),
                        "sectionIds": ("embeddings_meta",)
                    }
                ],
                "requirement": "required"
            },
            {
                "id": "evidence_trace",
                "requirement": "required",
                "description": "Gold and active Silver semantic record lineage.",
                "canonicalAuthorityRefs": ("evidence", "semantic_memory_graph"),
                "projectionBindings": [
                    {
                        "projectionId": "memory360",
                        "role": "primary",
                        "subjectKinds": ("entity", "semantic_entity"),
                        "sectionIds": ("evidence_trace",)
                    }
                ]
            },
            {
                "canonicalAuthorityRefs": ("consent_policy_decisions", "semantic_memory_graph", "semantic_memory_records", "silver_semantic_observations"),
                "description": "Required memory360 slot: memories.",
                "id": "memories",
                "partialImplementationReason": "Only explicit stored memories with exact source and historical consent-decision evidence are read; no automatic memory producer or configured freshness SLA is available.",
                "projectionBindings": [
                    {
                        "projectionId": "memory360",
                        "role": "primary",
                        "subjectKinds": ("entity", "semantic_entity"),
                        "sectionIds": ("memories",)
                    }
                ],
                "requirement": "required"
            },
            {
                "canonicalAuthorityRefs": ("consent_policy_decisions", "evidence", "semantic_memory_records"),
                "description": "Required memory360 slot: policy state.",
                "id": "policy_state",
                "partialImplementationReason": "Exact tenant and subject historical allow decisions are rendered with timestamped canonical consent-policy evidence. Explicit nonempty required purposes stamped from that verified write-time decision are surfaced; legacy unstamped purposes remain unknown. Current consent and policy are not evaluated, so present authorization remains unknown.",
                "projectionBindings": [
                    {
                        "projectionId": "memory360",
                        "role": "primary",
                        "subjectKinds": ("entity", "semantic_entity"),
                        "sectionIds": ("policy_state",)
                    }
                ],
                "requirement": "required"
            },
            {
                "id": "semantic_summary",
                "requirement": "required",
                "description": "Current Gold semantic entity state with explicit scope and provenance.",
                "canonicalAuthorityRefs": ("semantic_memory_graph",),
                "projectionBindings": [
                    {
                        "projectionId": "memory360",
                        "role": "primary",
                        "subjectKinds": ("entity", "semantic_entity"),
                        "sectionIds": ("semantic_summary",)
                    }
                ]
            },
            {
                "id": "source_links",
                "requirement": "required",
                "description": "Exact tenant scoped semantic observation source event references.",
                "canonicalAuthorityRefs": ("semantic_memory_graph", "source_provenance"),
                "projectionBindings": [
                    {
                        "projectionId": "memory360",
                        "role": "primary",
                        "subjectKinds": ("entity", "semantic_entity"),
                        "sectionIds": ("source_links",)
                    }
                ]
            },
            {
                "id": "topics",
                "requirement": "required",
                "description": "Derived reducer topic labels with inferred epistemic state.",
                "canonicalAuthorityRefs": ("semantic_memory_graph",),
                "projectionBindings": [
                    {
                        "projectionId": "memory360",
                        "role": "primary",
                        "subjectKinds": ("entity", "semantic_entity"),
                        "sectionIds": ("topics",)
                    }
                ]
            }
        ],
        "freshnessPolicy": {
            "required": True,
            "maxAgeSeconds": None,
            "sourceTimestamps": "preserve",
            "missingTimestamp": "unknown",
            "onStale": "mark_affected_slots_stale",
            "requirementStatus": "contract_requirement_not_provider_attestation"
        },
        "id": "memory360",
        "lensContract": {
            "expectedCount": 6,
            "lensIds": ("identity", "policy", "provenance", "risk", "semantic-memory", "topic"),
            "sourceAlignmentStatus": "source_aligned"
        },
        "policyBehavior": {
            "tenantScopeRequired": True,
            "authorizationBeforeRead": True,
            "policyEvaluation": "per_projection_before_composition",
            "historicalConsentEvaluation": "required_when_applicable",
            "redactionBehavior": "suppress_disallowed_slot_without_inference",
            "requirementStatus": "contract_requirement_not_provider_attestation"
        },
        "projectionBindings": [
            {
                "projectionId": "memory360",
                "role": "primary",
                "bindingStatus": "catalog_only",
                "providerImplementationState": "in_flight"
            }
        ],
        "sourceOfTruth": {
            "canonicalAuthorities": ("consent_policy_decisions", "evidence", "semantic_context_cards", "semantic_embedding_metadata", "semantic_memory_graph", "semantic_memory_records", "silver_semantic_observations", "source_provenance"),
            "ownsCanonicalTruth": False,
            "prohibitedOwnership": ("economic_facts", "execution_facts", "graph", "identity", "observations", "risk_outputs", "source_provenance")
        },
        "subjectKinds": ("card", "entity", "memory", "semantic_entity", "topic")
    },
    "profile360": {
        "backendCapabilities": {
            "required": ("experience360.evidence.provenance", "experience360.frame.compose", "experience360.freshness.evaluate", "experience360.policy.evaluate", "experience360.tenant_scope.enforce"),
            "projectionCapabilityKeys": ("economic360.explore", "economic360.read", "geographic360.explore", "geographic360.read", "outcome360.explore", "outcome360.read", "profile360.explore", "profile360.read", "risk360.explore", "risk360.read"),
            "providerCapabilityStatus": "registry_requirements_not_route_attestation"
        },
        "blueprintContract": {
            "canonicalOwner": "identity_profile",
            "priority": "P0",
            "purpose": "Builds the backend read model for who a human or agent-associated profile has been, is now, and is likely to become across identity, sessions, journeys, agents, communications, value, and risk.",
            "requiredLensIds": ("agentic", "campaign", "communications", "identity", "journey", "location", "provenance", "relationship", "risk", "value"),
            "requiredSlotIds": ("agent_delegations", "communications", "evidence_trace", "identity_spine", "journey_participation", "known_unknown_resolution", "likely_next_states", "location_temporal", "relationships", "risk_summary", "session_history", "syndicates", "value_summary"),
            "sourceSection": "11.4",
            "subjectIdentifiers": ("account_member_id", "anonymous_subject_id", "person_id", "profile_id", "wallet_cluster_id")
        },
        "contractStatus": "source_aligned",
        "description": "Governed entity-level contextual frame combining identity, observations, relationships, evidence, and optional risk and value context.",
        "displayName": "Profile 360",
        "domainSlots": [
            {
                "canonicalAuthorityRefs": ("agent_access", "agent_executions", "identity"),
                "description": "Current delegation and action-scoped authority evidence for an exact Agent subject or canonical Agent entity; unbound profiles remain unknown.",
                "id": "agent_delegations",
                "partialImplementationReason": "Exact Agent subjects and canonical Agent entities reuse Agent360 identity and delegation evidence; unbound profile links, historical replay, effective authorization, and freshness remain unknown.",
                "projectionBindings": [
                    {
                        "projectionId": "profile360",
                        "role": "primary",
                        "subjectKinds": ("agent", "entity"),
                        "sectionIds": ("agent_delegations",)
                    }
                ],
                "requirement": "required"
            },
            {
                "canonicalAuthorityRefs": ("communication_facts",),
                "description": "Exact tenant-scoped recipient messages for a resolved profile entity with recorded consent; sender identity, unknown consent, threads, and semantic interaction remain unknown.",
                "id": "communications",
                "partialImplementationReason": "recipient_message_history_is_bounded_and_sender_thread_semantics_and_freshness_sla_are_unverified",
                "projectionBindings": [
                    {
                        "projectionId": "profile360",
                        "role": "primary",
                        "subjectKinds": ("entity",),
                        "sectionIds": ("interactions",)
                    }
                ],
                "requirement": "required"
            },
            {
                "id": "economic_value_context",
                "requirement": "optional",
                "description": "Economic facts and measured outcomes.",
                "canonicalAuthorityRefs": ("ai_execution_facts", "economic_facts", "outcome_facts"),
                "projectionBindings": [
                    {
                        "projectionId": "economic360",
                        "role": "primary",
                        "subjectKinds": ("agent", "entity"),
                        "sectionIds": ("evidence", "outcomes", "summary")
                    },
                    {
                        "projectionId": "outcome360",
                        "role": "supporting",
                        "subjectKinds": [],
                        "sectionIds": ("evidence", "outcomes")
                    }
                ]
            },
            {
                "id": "entity_identity",
                "requirement": "optional",
                "description": "Resolved entity identity and registry context.",
                "canonicalAuthorityRefs": ("entity_registry", "identity"),
                "projectionBindings": [
                    {
                        "projectionId": "profile360",
                        "role": "primary",
                        "subjectKinds": ("agent", "entity"),
                        "sectionIds": ("state", "summary")
                    }
                ]
            },
            {
                "id": "evidence_and_limitations",
                "requirement": "optional",
                "description": "Evidence supporting the displayed profile claims.",
                "canonicalAuthorityRefs": ("evidence",),
                "projectionBindings": [
                    {
                        "projectionId": "profile360",
                        "role": "primary",
                        "subjectKinds": ("agent", "entity"),
                        "sectionIds": ("evidence", "findings")
                    }
                ]
            },
            {
                "id": "evidence_trace",
                "requirement": "required",
                "description": "Source references and coverage limits for the exact tenant profile.",
                "canonicalAuthorityRefs": ("evidence",),
                "projectionBindings": [
                    {
                        "projectionId": "profile360",
                        "role": "primary",
                        "subjectKinds": ("entity",),
                        "sectionIds": ("evidence", "findings")
                    }
                ]
            },
            {
                "id": "identity_spine",
                "requirement": "required",
                "description": "Exact tenant profile and canonical entity identity; other identifier resolution remains unknown.",
                "canonicalAuthorityRefs": ("entity_registry", "identity"),
                "projectionBindings": [
                    {
                        "projectionId": "profile360",
                        "role": "primary",
                        "subjectKinds": ("entity",),
                        "sectionIds": ("state", "summary")
                    }
                ]
            },
            {
                "id": "journey_participation",
                "requirement": "required",
                "description": "Current journey versions joined by exact tenant and typed profile ID; history and completeness remain explicit.",
                "canonicalAuthorityRefs": ("journeys",),
                "projectionBindings": [
                    {
                        "projectionId": "profile360",
                        "role": "primary",
                        "subjectKinds": ("entity",),
                        "sectionIds": ("journeys",)
                    }
                ]
            },
            {
                "id": "known_unknown_resolution",
                "requirement": "required",
                "description": "Known canonical entity identity and stated unresolved limits, without inferring an anonymous match.",
                "canonicalAuthorityRefs": ("entity_registry", "identity"),
                "projectionBindings": [
                    {
                        "projectionId": "profile360",
                        "role": "primary",
                        "subjectKinds": ("entity",),
                        "sectionIds": ("state", "summary")
                    }
                ]
            },
            {
                "authorityGapReason": "Model calibration and independent outcome verification are not joined to prediction outputs.",
                "canonicalAuthorityRefs": ("analytics_events", "consent_policy_decisions", "identity_source_identities", "model_artifact_registry", "model_governance", "outcome_facts", "profile_prediction_outputs"),
                "description": "Policy-admitted append-only future-state predictions for an exact canonical human entity, versioned state schema, active production artifact checksum, source event evidence, and bounded validity and freshness.",
                "id": "likely_next_states",
                "partialImplementationReason": "The read rechecks the exact recorded inference policy decision and, for session models, the current session-to-entity evidence, alongside the future-state schema, current production artifact, validity interval, and freshness. An artifact-reported calibration metric may be exposed with unknown evaluation scope. Current serving outputs omit required fields; historical identity, current consent, revocation history, outcome verification, and independently validated model calibration remain unknown.",
                "projectionBindings": [
                    {
                        "projectionId": "profile360",
                        "role": "primary",
                        "subjectKinds": ("entity",),
                        "sectionIds": ("likely_next_states",)
                    }
                ],
                "requirement": "required",
                "unboundCanonicalAuthorityRefs": ("model_governance", "outcome_facts")
            },
            {
                "canonicalAuthorityRefs": ("geo_observations", "temporal"),
                "description": "Tenant-scoped observed location facts and their recorded temporal bounds for the exact entity subject.",
                "id": "location_temporal",
                "partialImplementationReason": "The source reports recorded entity location facts only; profile alias resolution, continuous trajectory reconstruction, cross-surface completeness, historical point-in-time reconstruction, and Profile-specific freshness remain unknown.",
                "projectionBindings": [
                    {
                        "projectionId": "geographic360",
                        "role": "primary",
                        "subjectKinds": ("entity",),
                        "sectionIds": ("evidence", "timeline")
                    }
                ],
                "requirement": "required"
            },
            {
                "id": "observed_state_and_activity",
                "requirement": "optional",
                "description": "Observed state and temporal activity with explicit provenance.",
                "canonicalAuthorityRefs": ("graph", "observations", "temporal"),
                "projectionBindings": [
                    {
                        "projectionId": "profile360",
                        "role": "primary",
                        "subjectKinds": ("agent", "entity"),
                        "sectionIds": ("interactions", "state", "timeline")
                    }
                ]
            },
            {
                "id": "relationship_context",
                "requirement": "optional",
                "description": "Relationship context through the Profile360 identity and policy gate.",
                "canonicalAuthorityRefs": ("relationship_facts",),
                "projectionBindings": [
                    {
                        "projectionId": "profile360",
                        "role": "primary",
                        "subjectKinds": ("entity",),
                        "sectionIds": ("relationships",)
                    }
                ]
            },
            {
                "canonicalAuthorityRefs": ("graph", "relationship_facts"),
                "description": "Tenant-scoped canonical human profile identity gates a nested Relationship360 read over the exact entity's graph mutation ledger with bounded edge evidence.",
                "id": "relationships",
                "partialImplementationReason": "Profile360 now requires an exact tenant human profile/entity same-ID binding and an allowed relationships slot before a nested Relationship360 ledger read. Alias and account-member identities remain unresolved; bounded ledger evidence, history, complete edge coverage, and Profile-specific freshness remain unknown.",
                "projectionBindings": [
                    {
                        "projectionId": "profile360",
                        "role": "primary",
                        "subjectKinds": ("entity",),
                        "sectionIds": ("relationships",)
                    }
                ],
                "requirement": "required"
            },
            {
                "id": "risk_context",
                "requirement": "optional",
                "description": "Governed risk and fraud context.",
                "canonicalAuthorityRefs": ("model_governance", "risk_outputs"),
                "projectionBindings": [
                    {
                        "projectionId": "risk360",
                        "role": "primary",
                        "subjectKinds": ("entity",),
                        "sectionIds": ("evidence", "findings", "summary")
                    }
                ]
            },
            {
                "canonicalAuthorityRefs": ("evidence", "risk_outputs"),
                "description": "Tenant-exact Risk360 assessment and evidence for the same canonical entity or Agent subject; no profile identity is inferred.",
                "id": "risk_summary",
                "partialImplementationReason": "Risk assessment and evidence reads bind by exact tenant, subject kind, and subject ID; a Profile-specific freshness threshold remains unknown.",
                "projectionBindings": [
                    {
                        "projectionId": "risk360",
                        "role": "primary",
                        "subjectKinds": ("agent", "entity"),
                        "sectionIds": ("evidence", "findings", "state", "summary")
                    }
                ],
                "requirement": "required"
            },
            {
                "canonicalAuthorityRefs": ("analytics_events", "evidence", "identity"),
                "description": "Resolved tenant/profile identities join exact analytics session rollups and identity-owned activity event IDs in the requested window.",
                "id": "session_history",
                "partialImplementationReason": "Only exact identity-owned session and event records are observed. Session roster and event-timeline completeness remain partial without source watermarks; missing records do not prove inactivity.",
                "projectionBindings": [
                    {
                        "projectionId": "profile360",
                        "role": "primary",
                        "subjectKinds": ("entity",),
                        "sectionIds": ("sessions",)
                    }
                ],
                "requirement": "required"
            },
            {
                "canonicalAuthorityRefs": ("cohort_membership", "evidence", "population_definitions"),
                "description": "Exact current tenant entity membership in an explicitly opted-in Syndicates population, verified by the live graph ledger edge.",
                "id": "syndicates",
                "partialImplementationReason": "Exact current MEMBER_OF edges for explicitly opted-in tenant populations are evidence-backed; unbounded roster completeness, historical replay, and a membership freshness policy remain unavailable.",
                "projectionBindings": [
                    {
                        "projectionId": "profile360",
                        "role": "primary",
                        "subjectKinds": ("entity",),
                        "sectionIds": ("syndicates",)
                    }
                ],
                "requirement": "required"
            },
            {
                "canonicalAuthorityRefs": ("ai_execution_facts", "economic_facts", "outcome_facts"),
                "description": "Direct tenant-scoped economic facts for the exact canonical entity or Agent subject; measured outcomes and attribution remain unresolved.",
                "id": "value_summary",
                "partialImplementationReason": "Economic360 reads exact tenant-scoped economic facts for canonical entity and Agent subjects; Outcome360 does not yet support exact entity/profile subjects for attributed outcomes, and Profile-specific freshness remains unknown.",
                "projectionBindings": [
                    {
                        "projectionId": "economic360",
                        "role": "primary",
                        "subjectKinds": ("agent", "entity"),
                        "sectionIds": ("evidence", "summary")
                    }
                ],
                "requirement": "required"
            }
        ],
        "freshnessPolicy": {
            "required": True,
            "maxAgeSeconds": None,
            "sourceTimestamps": "preserve",
            "missingTimestamp": "unknown",
            "onStale": "mark_affected_slots_stale",
            "requirementStatus": "contract_requirement_not_provider_attestation"
        },
        "id": "profile360",
        "lensContract": {
            "expectedCount": 10,
            "lensIds": ("agentic", "campaign", "communications", "identity", "journey", "location", "provenance", "relationship", "risk", "value"),
            "sourceAlignmentStatus": "source_aligned"
        },
        "policyBehavior": {
            "tenantScopeRequired": True,
            "authorizationBeforeRead": True,
            "policyEvaluation": "per_projection_before_composition",
            "historicalConsentEvaluation": "required_when_applicable",
            "redactionBehavior": "suppress_disallowed_slot_without_inference",
            "requirementStatus": "contract_requirement_not_provider_attestation"
        },
        "projectionBindings": [
            {
                "projectionId": "economic360",
                "role": "primary",
                "bindingStatus": "catalog_only",
                "providerImplementationState": "implemented"
            },
            {
                "projectionId": "geographic360",
                "role": "primary",
                "bindingStatus": "catalog_only",
                "providerImplementationState": "implemented"
            },
            {
                "projectionId": "outcome360",
                "role": "supporting",
                "bindingStatus": "catalog_only",
                "providerImplementationState": "implemented"
            },
            {
                "projectionId": "profile360",
                "role": "primary",
                "bindingStatus": "catalog_only",
                "providerImplementationState": "in_flight"
            },
            {
                "projectionId": "risk360",
                "role": "primary",
                "bindingStatus": "catalog_only",
                "providerImplementationState": "implemented"
            }
        ],
        "sourceOfTruth": {
            "canonicalAuthorities": ("agent_access", "agent_executions", "ai_execution_facts", "analytics_events", "cohort_membership", "communication_facts", "consent_policy_decisions", "economic_facts", "entity_registry", "evidence", "geo_observations", "graph", "identity", "identity_source_identities", "journeys", "model_artifact_registry", "model_governance", "observations", "outcome_facts", "population_definitions", "profile_prediction_outputs", "relationship_facts", "risk_outputs", "temporal"),
            "ownsCanonicalTruth": False,
            "prohibitedOwnership": ("economic_facts", "execution_facts", "graph", "identity", "observations", "risk_outputs", "source_provenance")
        },
        "subjectKinds": ("account_member", "agent", "anonymous_subject", "cluster", "entity", "profile")
    },
    "risk360": {
        "backendCapabilities": {
            "required": ("experience360.evidence.provenance", "experience360.frame.compose", "experience360.freshness.evaluate", "experience360.policy.evaluate", "experience360.tenant_scope.enforce"),
            "projectionCapabilityKeys": ("economic360.explore", "economic360.read", "execution360.explore", "execution360.read", "fraud360.explore", "fraud360.read", "relationship360.explore", "relationship360.read", "risk360.explore", "risk360.read", "social360.explore", "social360.read"),
            "providerCapabilityStatus": "registry_requirements_not_route_attestation"
        },
        "blueprintContract": {
            "canonicalOwner": "risk_trust_safety",
            "priority": "P0",
            "purpose": "Summarizes trust, anomaly, poisoning, contagion, policy, social, financial, and agent-amplified risk without hiding evidence lineage.",
            "requiredLensIds": ("agentic", "communications", "identity", "policy", "provenance", "relationship", "risk", "social", "value"),
            "requiredSlotIds": ("agent_amplification", "anomaly_events", "audit_history", "evidence_trace", "financial_contagion", "interventions", "poisoning_evidence", "policy_flags", "propagation_paths", "risk_summary", "social_contagion", "source_trust"),
            "sourceSection": "11.8",
            "subjectIdentifiers": ("account_id", "agent_id", "campaign_id", "contagion_path_id", "profile_id", "risk_subject_id", "source_id")
        },
        "contractStatus": "source_aligned",
        "description": "Governed view of risk findings, evidence, relationship and economic exposure, with explicit coverage and uncertainty.",
        "displayName": "Risk 360",
        "domainSlots": [
            {
                "id": "agent_amplification",
                "requirement": "required",
                "description": "Persisted agentic delegation abuse signal only for exact agent subject.",
                "canonicalAuthorityRefs": ("evidence", "risk_outputs"),
                "projectionBindings": [
                    {
                        "projectionId": "risk360",
                        "role": "primary",
                        "subjectKinds": ("agent",),
                        "sectionIds": ("evidence", "findings", "health")
                    }
                ]
            },
            {
                "canonicalAuthorityRefs": ("evidence", "observations", "risk_outputs", "risk_signals"),
                "description": "Exact tenant and typed-subject Gold anomaly alerts, with optional bounded RiskSignal, event evidence, and Bronze SDK event-record metadata when explicit identifiers match.",
                "id": "anomaly_events",
                "partialImplementationReason": "Authenticated Gold alert materialization verifies an exact tenant/subject RiskSignal and one selected event EvidenceRef before writing the link triplet. For explicit bronze_sdk_events references, Risk360 also checks one exact tenant Bronze V1/V2 record without exposing payload; missing, duplicate, tombstoned, or quarantined records remain unverified. Legacy alerts remain metadata only. This is a caller-selected alert path, not an automatic detector producer; complete event coverage, detector coverage, cause, severity, and freshness remain unknown.",
                "projectionBindings": [
                    {
                        "projectionId": "risk360",
                        "role": "primary",
                        "subjectKinds": ("agent", "cluster", "contagion_path", "entity", "relationship", "source"),
                        "sectionIds": ("evidence", "findings", "health")
                    }
                ],
                "requirement": "required"
            },
            {
                "canonicalAuthorityRefs": ("computation", "evidence", "risk_assessments", "risk_intervention_records"),
                "description": "Exact-subject assessment-run and intervention histories with bounded, verified direct predecessor links when the stored supersedes reference agrees on tenant, subject, definition, version, and context.",
                "id": "audit_history",
                "partialImplementationReason": "Assessment-run and append-only intervention histories are available for exact subjects; direct supersedes references are exposed only after exact predecessor verification. Cross-assessment late-data lineage, full restatement history, actor authority, producer completeness, independent outcome verification, and freshness remain unknown.",
                "projectionBindings": [
                    {
                        "projectionId": "risk360",
                        "role": "primary",
                        "subjectKinds": ("agent", "cluster", "contagion_path", "entity", "relationship", "source"),
                        "sectionIds": ("evidence", "findings")
                    }
                ],
                "requirement": "required"
            },
            {
                "id": "economic_exposure",
                "requirement": "optional",
                "description": "Economic facts associated with the risk subject and network.",
                "canonicalAuthorityRefs": ("ai_execution_facts", "economic_facts"),
                "projectionBindings": [
                    {
                        "projectionId": "economic360",
                        "role": "primary",
                        "subjectKinds": ("agent", "entity"),
                        "sectionIds": ("evidence", "outcomes", "summary")
                    }
                ]
            },
            {
                "id": "evidence_trace",
                "requirement": "required",
                "description": "Exact assessment, signal, and source ingress evidence references.",
                "canonicalAuthorityRefs": ("evidence", "flow_trace_paths", "flow_traces", "risk_assessments", "risk_outputs", "risk_signals", "source_provenance", "transfers"),
                "projectionBindings": [
                    {
                        "projectionId": "risk360",
                        "role": "primary",
                        "subjectKinds": ("agent", "cluster", "contagion_path", "entity", "relationship", "source"),
                        "sectionIds": ("evidence", "findings", "health")
                    }
                ]
            },
            {
                "id": "execution_exposure",
                "requirement": "optional",
                "description": "Execution facts associated with an agent or execution subject.",
                "canonicalAuthorityRefs": ("execution_facts",),
                "projectionBindings": [
                    {
                        "projectionId": "execution360",
                        "role": "primary",
                        "subjectKinds": ("agent", "entity"),
                        "sectionIds": ("evidence", "summary", "timeline")
                    }
                ]
            },
            {
                "canonicalAuthorityRefs": ("consent_policy_decisions", "flow_trace_paths", "flow_traces", "risk_assessments", "risk_signals", "transfers"),
                "description": "Exact financial transfer path linked to risk evidence for each node after affirmative current analytics consent for every path entity; causal contagion, exposure, and loss remain unproven.",
                "id": "financial_contagion",
                "partialImplementationReason": "The bounded path is a correlated observation only. Causal contagion, exposure, loss, source coverage, current risk policy outcome, and freshness are unknown; missing or denied entity consent suppresses path details.",
                "projectionBindings": [
                    {
                        "projectionId": "risk360",
                        "role": "primary",
                        "subjectKinds": ("contagion_path",),
                        "sectionIds": ("findings",)
                    }
                ],
                "requirement": "required"
            },
            {
                "id": "fraud_and_social_patterns",
                "requirement": "optional",
                "description": "Fraud synthesis, graph motifs, and social observations.",
                "canonicalAuthorityRefs": ("fraud_synthesis", "graph_motifs", "social_observations"),
                "projectionBindings": [
                    {
                        "projectionId": "fraud360",
                        "role": "primary",
                        "subjectKinds": ("agent", "entity", "relationship"),
                        "sectionIds": ("evidence", "findings", "health")
                    },
                    {
                        "projectionId": "social360",
                        "role": "supporting",
                        "subjectKinds": ("entity", "relationship"),
                        "sectionIds": ("evidence", "findings")
                    }
                ]
            },
            {
                "authorityGapReason": "Append-only exact-subject intervention decisions and reported outcomes are readable; actor authority, producer coverage, independent outcome verification, and freshness remain unknown.",
                "canonicalAuthorityRefs": ("actions", "risk_intervention_records", "risk_outputs"),
                "description": "Recorded risk interventions and results.",
                "id": "interventions",
                "partialImplementationReason": "Exact-subject intervention decisions and reported outcomes can include slot-authorized, caller-associated agent lifecycle requests; dispatch, external effects, actor authority, producer coverage, independent outcome verification, and freshness remain unknown.",
                "projectionBindings": [
                    {
                        "projectionId": "risk360",
                        "role": "primary",
                        "subjectKinds": ("agent", "cluster", "contagion_path", "entity", "relationship", "source"),
                        "sectionIds": ("evidence", "findings", "health")
                    }
                ],
                "requirement": "required",
                "unboundCanonicalAuthorityRefs": ("actions",)
            },
            {
                "canonicalAuthorityRefs": ("risk_outputs", "source_provenance"),
                "description": "Tenant-scoped detector evidence for exact subjects, with versioned lifecycle and evidence references; detector completeness and source reputation remain unknown.",
                "id": "poisoning_evidence",
                "partialImplementationReason": "Risk360 reads explicitly stored detector evidence for exact tenant and subject bindings, with temporal anchors, lifecycle, restatement lineage, and evidence references. Detector coverage, independent source verification, population-wide completeness, and a source freshness SLA remain unknown.",
                "projectionBindings": [
                    {
                        "projectionId": "risk360",
                        "role": "primary",
                        "subjectKinds": ("agent", "cluster", "contagion_path", "entity", "relationship", "source"),
                        "sectionIds": ("evidence", "findings")
                    }
                ],
                "requirement": "required"
            },
            {
                "canonicalAuthorityRefs": ("model_governance", "risk_outputs", "risk_signals"),
                "description": "Exact agent risk-signal policy-flag observations with evidence; evaluated flags require versioned model-governance decisions.",
                "id": "policy_flags",
                "partialImplementationReason": "Only exact tenant-scoped current agent risk-signal records are exposed as reported observations. Policy evaluation, model/version, non-agent subjects, historical replay, and complete coverage remain unknown.",
                "projectionBindings": [
                    {
                        "projectionId": "risk360",
                        "role": "primary",
                        "subjectKinds": ("agent",),
                        "sectionIds": ("evidence", "findings")
                    }
                ],
                "requirement": "required"
            },
            {
                "canonicalAuthorityRefs": ("consent_policy_decisions", "evidence", "graph", "relationship_facts"),
                "description": "Observed, consent-governed social graph paths used as risk investigation context; path evidence alone does not establish risk propagation.",
                "id": "propagation_paths",
                "implementationCrosswalk": ("risk_observed_social_graph_paths",),
                "partialImplementationReason": "Bounded current tenant-scoped FOLLOWS paths are emitted only with analytics consent, canonical graph and relationship evidence, exact endpoint scope, valid edge state, and acceptable evidence times. Observed edges do not prove causal risk propagation; historical reads, complete path coverage, and freshness remain unknown.",
                "projectionBindings": [
                    {
                        "projectionId": "risk360",
                        "role": "primary",
                        "subjectKinds": ("entity",),
                        "sectionIds": ("findings",)
                    }
                ],
                "requirement": "required"
            },
            {
                "id": "relationship_network_context",
                "requirement": "optional",
                "description": "Entity graph and relationship evidence relevant to risk.",
                "canonicalAuthorityRefs": ("entity_graph", "graph", "relationship_facts"),
                "projectionBindings": [
                    {
                        "projectionId": "relationship360",
                        "role": "primary",
                        "subjectKinds": ("agent", "entity", "relationship"),
                        "sectionIds": ("evidence", "interactions", "summary")
                    },
                    {
                        "projectionId": "risk360",
                        "role": "supporting",
                        "subjectKinds": ("cluster", "entity", "relationship"),
                        "sectionIds": ("evidence", "summary")
                    }
                ]
            },
            {
                "id": "risk_assessment_state",
                "requirement": "optional",
                "description": "Risk outputs, model governance context, and assessment state.",
                "canonicalAuthorityRefs": ("model_governance", "risk_outputs"),
                "projectionBindings": [
                    {
                        "projectionId": "risk360",
                        "role": "primary",
                        "subjectKinds": ("agent", "cluster", "entity", "relationship"),
                        "sectionIds": ("findings", "health", "state", "summary")
                    }
                ]
            },
            {
                "id": "risk_evidence_and_limitations",
                "requirement": "optional",
                "description": "Evidence and limitations supporting risk findings.",
                "canonicalAuthorityRefs": ("evidence",),
                "projectionBindings": [
                    {
                        "projectionId": "risk360",
                        "role": "primary",
                        "subjectKinds": ("agent", "cluster", "entity", "relationship"),
                        "sectionIds": ("evidence", "findings")
                    }
                ]
            },
            {
                "id": "risk_summary",
                "requirement": "required",
                "description": "Exact scoped canonical assessment and dimension state with evidence and confidence.",
                "canonicalAuthorityRefs": ("evidence", "risk_outputs"),
                "projectionBindings": [
                    {
                        "projectionId": "risk360",
                        "role": "primary",
                        "subjectKinds": ("agent", "cluster", "entity", "relationship", "source"),
                        "sectionIds": ("evidence", "findings", "state", "summary")
                    }
                ]
            },
            {
                "canonicalAuthorityRefs": ("bronze_sdk_events", "consent_policy_decisions", "entity_graph", "relationship_facts", "risk_signals", "social_relationship_evidence_events"),
                "description": "Exact source-reported social path evidence joined to tenant-scoped risk, relationship, and event authorities; causality remains unverified.",
                "id": "social_contagion",
                "partialImplementationReason": "The bounded source-reported path is correlated only; causal contagion, complete source coverage, current policy outcome, and freshness are unproven. Consent denial suppresses content.",
                "projectionBindings": [
                    {
                        "projectionId": "risk360",
                        "role": "primary",
                        "subjectKinds": ("entity",),
                        "sectionIds": ("findings",)
                    }
                ],
                "requirement": "required"
            },
            {
                "id": "source_trust",
                "requirement": "required",
                "description": "Gateway stamped ingress classification for an exact source subject; reliability remains unknown.",
                "canonicalAuthorityRefs": ("source_provenance",),
                "projectionBindings": [
                    {
                        "projectionId": "risk360",
                        "role": "primary",
                        "subjectKinds": ("source",),
                        "sectionIds": ("evidence", "findings", "health")
                    }
                ]
            }
        ],
        "freshnessPolicy": {
            "required": True,
            "maxAgeSeconds": None,
            "sourceTimestamps": "preserve",
            "missingTimestamp": "unknown",
            "onStale": "mark_affected_slots_stale",
            "requirementStatus": "contract_requirement_not_provider_attestation"
        },
        "id": "risk360",
        "lensContract": {
            "expectedCount": 9,
            "lensIds": ("agentic", "communications", "identity", "policy", "provenance", "relationship", "risk", "social", "value"),
            "sourceAlignmentStatus": "source_aligned"
        },
        "policyBehavior": {
            "tenantScopeRequired": True,
            "authorizationBeforeRead": True,
            "policyEvaluation": "per_projection_before_composition",
            "historicalConsentEvaluation": "required_when_applicable",
            "redactionBehavior": "suppress_disallowed_slot_without_inference",
            "requirementStatus": "contract_requirement_not_provider_attestation"
        },
        "projectionBindings": [
            {
                "projectionId": "economic360",
                "role": "primary",
                "bindingStatus": "catalog_only",
                "providerImplementationState": "implemented"
            },
            {
                "projectionId": "execution360",
                "role": "primary",
                "bindingStatus": "catalog_only",
                "providerImplementationState": "in_flight"
            },
            {
                "projectionId": "fraud360",
                "role": "primary",
                "bindingStatus": "catalog_only",
                "providerImplementationState": "implemented"
            },
            {
                "projectionId": "relationship360",
                "role": "primary",
                "bindingStatus": "catalog_only",
                "providerImplementationState": "in_flight"
            },
            {
                "projectionId": "risk360",
                "role": "primary",
                "bindingStatus": "catalog_only",
                "providerImplementationState": "implemented"
            },
            {
                "projectionId": "social360",
                "role": "supporting",
                "bindingStatus": "catalog_only",
                "providerImplementationState": "in_flight"
            }
        ],
        "sourceOfTruth": {
            "canonicalAuthorities": ("actions", "ai_execution_facts", "bronze_sdk_events", "computation", "consent_policy_decisions", "economic_facts", "entity_graph", "evidence", "execution_facts", "flow_trace_paths", "flow_traces", "fraud_synthesis", "graph", "graph_motifs", "model_governance", "observations", "relationship_facts", "risk_assessments", "risk_intervention_records", "risk_outputs", "risk_signals", "social_observations", "social_relationship_evidence_events", "source_provenance", "transfers"),
            "ownsCanonicalTruth": False,
            "prohibitedOwnership": ("economic_facts", "execution_facts", "graph", "identity", "observations", "risk_outputs", "source_provenance")
        },
        "subjectKinds": ("account", "agent", "campaign", "cluster", "contagion_path", "entity", "profile", "relationship", "risk", "source")
    },
    "signals360": {
        "backendCapabilities": {
            "required": ("experience360.evidence.provenance", "experience360.frame.compose", "experience360.freshness.evaluate", "experience360.policy.evaluate", "experience360.tenant_scope.enforce"),
            "projectionCapabilityKeys": ("signals360.read",),
            "providerCapabilityStatus": "registry_requirements_not_route_attestation"
        },
        "blueprintContract": {
            "canonicalOwner": "signal_event_intake",
            "priority": "P1",
            "purpose": "Shows source events/signals, normalization quality, classification, lineage, and downstream graph links.",
            "requiredLensIds": ("campaign", "event-signal", "identity", "location", "policy", "provenance", "risk"),
            "requiredSlotIds": ("campaign_links", "classification", "evidence_trace", "freshness", "linked_entities", "normalization", "quality", "risk_flags", "signal_summary", "source_inventory"),
            "sourceSection": "11.12",
            "subjectIdentifiers": ("event_id", "observation_id", "signal_id", "source_id", "stream_id")
        },
        "contractStatus": "source_aligned",
        "description": "Governed view of risk, fraud, source, social, and outcome signals with evidence and freshness status.",
        "displayName": "Signals 360",
        "domainSlots": [
            {
                "canonicalAuthorityRefs": ("campaign_facts", "campaign_touchpoints"),
                "description": "Exact tenant source-event links from campaign touchpoints, admitted only after the campaign owner resolves the referenced canonical campaign.",
                "id": "campaign_links",
                "partialImplementationReason": "Only exact event or observation IDs linked by tenant-scoped campaign touchpoints and resolved to canonical tenant campaigns are available; entity, source, stream, missing-reference, and incomplete reads remain unknown or degraded.",
                "projectionBindings": [
                    {
                        "projectionId": "signals360",
                        "role": "primary",
                        "subjectKinds": ("event", "observation"),
                        "sectionIds": ("campaign_links",)
                    }
                ],
                "requirement": "required"
            },
            {
                "canonicalAuthorityRefs": ("events", "observations", "silver_semantic_observations"),
                "description": "Required signals360 slot: classification.",
                "id": "classification",
                "partialImplementationReason": "Exact gateway-accepted SDK event type and family are registry-validated. A bounded current Silver semantic read may expose model-output metadata only when tenant, event ID, stamped namespace, event type, time, and source evidence match. Derived labels remain suppressed; source attribution, semantic correctness, policy, producer coverage, and freshness remain unknown.",
                "projectionBindings": [
                    {
                        "projectionId": "signals360",
                        "role": "primary",
                        "subjectKinds": ("event", "observation"),
                        "sectionIds": ("classification",)
                    }
                ],
                "requirement": "required"
            },
            {
                "id": "evidence_trace",
                "requirement": "required",
                "description": "Evidence references for bounded derived signal records.",
                "canonicalAuthorityRefs": ("behavioral_signals",),
                "projectionBindings": [
                    {
                        "projectionId": "signals360",
                        "role": "primary",
                        "subjectKinds": ("entity",),
                        "sectionIds": ("evidence_trace",)
                    }
                ]
            },
            {
                "id": "freshness",
                "requirement": "required",
                "description": "Source timestamps retained from bounded derived signal records; freshness threshold remains unknown.",
                "canonicalAuthorityRefs": ("behavioral_signals",),
                "projectionBindings": [
                    {
                        "projectionId": "signals360",
                        "role": "primary",
                        "subjectKinds": ("entity",),
                        "sectionIds": ("freshness",)
                    }
                ]
            },
            {
                "canonicalAuthorityRefs": ("behavioral_signals", "identity"),
                "description": "Exact tenant signal, event, or observation bindings to active canonical identity subjects; observation IDs join only when recorded as the matching source_event_id.",
                "id": "linked_entities",
                "partialImplementationReason": "Exact links are emitted for signal, event, and matching observation IDs; entity, source, stream, absent-link, and incomplete reads remain unknown or degraded.",
                "projectionBindings": [
                    {
                        "projectionId": "signals360",
                        "role": "primary",
                        "subjectKinds": ("event", "observation", "signal"),
                        "sectionIds": ("linked_entities",)
                    }
                ],
                "requirement": "required"
            },
            {
                "canonicalAuthorityRefs": ("observations", "source_schema"),
                "description": "Exact tenant SDK observation gateway normalization lineage with adapter and envelope schema versions; semantic correctness and producer coverage remain unknown.",
                "id": "normalization",
                "partialImplementationReason": "exact_gateway_accepted_sdk_adapter_and_envelope_schema_lineage_only; semantic_correctness_producer_coverage_and_freshness_sla_unknown",
                "projectionBindings": [
                    {
                        "projectionId": "signals360",
                        "role": "primary",
                        "subjectKinds": ("event", "observation"),
                        "sectionIds": ("normalization",)
                    }
                ],
                "requirement": "required"
            },
            {
                "canonicalAuthorityRefs": ("ingestion_health", "observations", "source_schema"),
                "description": "Exact SDK Bronze gateway acceptance and, for an authenticated site namespace, separately observed current site install-signal status; event and fleet health remain unknown.",
                "id": "quality",
                "partialImplementationReason": "Gateway acceptance and exact tenant/site install-signal status are separate observations. Mobile and tenant-wide events have no installation-health join; event-time health, fleet completeness, source reliability, semantic quality, and a freshness SLA remain unknown.",
                "projectionBindings": [
                    {
                        "projectionId": "signals360",
                        "role": "primary",
                        "subjectKinds": ("event", "observation"),
                        "sectionIds": ("quality",)
                    }
                ],
                "requirement": "required"
            },
            {
                "canonicalAuthorityRefs": ("risk_outputs",),
                "description": "Required signals360 slot: risk flags.",
                "id": "risk_flags",
                "partialImplementationReason": "Exact tenant and typed-subject RiskSignal records are projected as partial observations; producer coverage, assessment history, policy, freshness, and causality remain unknown.",
                "projectionBindings": [
                    {
                        "projectionId": "signals360",
                        "role": "primary",
                        "subjectKinds": ("event", "observation", "signal", "source", "stream"),
                        "sectionIds": ("risk_flags",)
                    }
                ],
                "requirement": "required"
            },
            {
                "id": "signal_summary",
                "requirement": "required",
                "description": "Bounded tenant and entity scoped translator-derived signal records.",
                "canonicalAuthorityRefs": ("behavioral_signals",),
                "projectionBindings": [
                    {
                        "projectionId": "signals360",
                        "role": "primary",
                        "subjectKinds": ("entity",),
                        "sectionIds": ("signal_summary",)
                    }
                ]
            },
            {
                "canonicalAuthorityRefs": ("source_facts", "source_provenance"),
                "description": "Authenticated source metadata for an exact SDK event or observation, with an exact current tenant site registration fact when its server-stamped site namespace resolves; fleet inventory remains unknown.",
                "id": "source_inventory",
                "partialImplementationReason": "One exact SDK event or observation is described; authenticated site-scoped events may join the current canonical tenant site registry. Mobile and tenant-wide events, historical registration state, fleet inventory, and source reliability remain unknown.",
                "projectionBindings": [
                    {
                        "projectionId": "signals360",
                        "role": "primary",
                        "subjectKinds": ("event", "observation"),
                        "sectionIds": ("source_inventory",)
                    }
                ],
                "requirement": "required"
            }
        ],
        "freshnessPolicy": {
            "required": True,
            "maxAgeSeconds": None,
            "sourceTimestamps": "preserve",
            "missingTimestamp": "unknown",
            "onStale": "mark_affected_slots_stale",
            "requirementStatus": "contract_requirement_not_provider_attestation"
        },
        "id": "signals360",
        "lensContract": {
            "expectedCount": 7,
            "lensIds": ("campaign", "event-signal", "identity", "location", "policy", "provenance", "risk"),
            "sourceAlignmentStatus": "source_aligned"
        },
        "policyBehavior": {
            "tenantScopeRequired": True,
            "authorizationBeforeRead": True,
            "policyEvaluation": "per_projection_before_composition",
            "historicalConsentEvaluation": "required_when_applicable",
            "redactionBehavior": "suppress_disallowed_slot_without_inference",
            "requirementStatus": "contract_requirement_not_provider_attestation"
        },
        "projectionBindings": [
            {
                "projectionId": "signals360",
                "role": "primary",
                "bindingStatus": "catalog_only",
                "providerImplementationState": "in_flight"
            }
        ],
        "sourceOfTruth": {
            "canonicalAuthorities": ("behavioral_signals", "campaign_facts", "campaign_touchpoints", "events", "identity", "ingestion_health", "observations", "risk_outputs", "silver_semantic_observations", "source_facts", "source_provenance", "source_schema"),
            "ownsCanonicalTruth": False,
            "prohibitedOwnership": ("economic_facts", "execution_facts", "graph", "identity", "observations", "risk_outputs", "source_provenance")
        },
        "subjectKinds": ("entity", "event", "observation", "signal", "source", "stream")
    },
    "social360": {
        "backendCapabilities": {
            "required": ("experience360.evidence.provenance", "experience360.frame.compose", "experience360.freshness.evaluate", "experience360.policy.evaluate", "experience360.tenant_scope.enforce"),
            "projectionCapabilityKeys": ("geographic360.explore", "geographic360.read", "population360.explore", "population360.read", "relationship360.explore", "relationship360.read", "social360.explore", "social360.read", "source360.explore", "source360.read"),
            "providerCapabilityStatus": "registry_requirements_not_route_attestation"
        },
        "blueprintContract": {
            "canonicalOwner": "relationship_social_graph",
            "priority": "P0",
            "purpose": "Surfaces relationship graph, syndicates, communities, multi-hop paths, influence, and social propagation evidence.",
            "requiredLensIds": ("communications", "identity", "provenance", "relationship", "risk", "social", "syndicate", "value"),
            "requiredSlotIds": ("communities", "evidence_trace", "influence_paths", "multi_hop_paths", "propagation", "relationship_map", "risk_edges", "social_contagion", "syndicates", "trust_edges"),
            "sourceSection": "11.10",
            "subjectIdentifiers": ("community_id", "profile_id", "relationship_edge_id", "social_subject_id", "syndicate_id")
        },
        "contractStatus": "source_aligned",
        "description": "Governed view of social observations, source-backed relationships, evidence, and optional population or geographic context.",
        "displayName": "Social 360",
        "domainSlots": [
            {
                "id": "communities",
                "requirement": "required",
                "description": "Recorded Social Silver community membership observations.",
                "canonicalAuthorityRefs": ("social_observations",),
                "projectionBindings": [
                    {
                        "projectionId": "social360",
                        "role": "primary",
                        "subjectKinds": ("entity", "population", "relationship", "source"),
                        "sectionIds": ("evidence", "findings")
                    }
                ]
            },
            {
                "id": "evidence_and_coverage",
                "requirement": "optional",
                "description": "Evidence and source coverage for social claims.",
                "canonicalAuthorityRefs": ("cohort_membership", "evidence", "identity", "source_coverage"),
                "projectionBindings": [
                    {
                        "projectionId": "social360",
                        "role": "primary",
                        "subjectKinds": ("entity", "population", "relationship", "source"),
                        "sectionIds": ("evidence", "findings")
                    },
                    {
                        "projectionId": "source360",
                        "role": "supporting",
                        "subjectKinds": ("source",),
                        "sectionIds": ("coverage", "evidence")
                    }
                ]
            },
            {
                "id": "evidence_trace",
                "requirement": "required",
                "description": "Source references for exact scoped social observations.",
                "canonicalAuthorityRefs": ("evidence", "social_observations"),
                "projectionBindings": [
                    {
                        "projectionId": "social360",
                        "role": "primary",
                        "subjectKinds": ("entity", "population", "relationship", "source"),
                        "sectionIds": ("evidence",)
                    }
                ]
            },
            {
                "id": "geographic_context",
                "requirement": "optional",
                "description": "Location context for social observations.",
                "canonicalAuthorityRefs": ("geo_observations", "locations"),
                "projectionBindings": [
                    {
                        "projectionId": "geographic360",
                        "role": "primary",
                        "subjectKinds": ("entity", "population", "source"),
                        "sectionIds": ("evidence", "summary", "timeline")
                    }
                ]
            },
            {
                "canonicalAuthorityRefs": ("computation", "graph", "influence_propagation", "relationship_facts", "relationship_fidelity", "relationship_predicate_registry"),
                "description": "Bounded evidence-backed directed FOLLOWS paths enriched with exact per-hop persisted RelationshipFidelity measurements when their evidence fully matches the graph relationship facts. Paths do not establish actual influence, trust, or causal contagion.",
                "id": "influence_paths",
                "partialImplementationReason": "bounded_paths_and_exact_m7_evidence_join_only_component_measurements_may_be_partial_completeness_freshness_and_causality_unknown",
                "projectionBindings": [
                    {
                        "projectionId": "social360",
                        "role": "primary",
                        "subjectKinds": ("entity", "relationship"),
                        "sectionIds": ("influence",)
                    }
                ],
                "requirement": "required"
            },
            {
                "canonicalAuthorityRefs": ("graph", "relationship_facts"),
                "description": "Bounded observed FOLLOWS edge sequences for an exact entity; no transitive trust, influence, or exhaustive path claim.",
                "id": "multi_hop_paths",
                "partialImplementationReason": "bounded_observed_paths_only_no_exhaustive_or_causal_social_semantics",
                "projectionBindings": [
                    {
                        "projectionId": "social360",
                        "role": "primary",
                        "subjectKinds": ("entity",),
                        "sectionIds": ("paths",)
                    }
                ],
                "requirement": "required"
            },
            {
                "id": "population_context",
                "requirement": "optional",
                "description": "Population and cohort context for social observations.",
                "canonicalAuthorityRefs": ("cohort_membership", "population_definitions"),
                "projectionBindings": [
                    {
                        "projectionId": "population360",
                        "role": "primary",
                        "subjectKinds": ("entity", "population"),
                        "sectionIds": ("evidence", "state", "summary")
                    }
                ]
            },
            {
                "canonicalAuthorityRefs": ("graph", "influence_propagation", "relationship_facts", "relationship_predicate_registry", "social_observations"),
                "description": "Exact tenant-scoped, consent-authorized FOLLOWS paths whose predicates permit propagation analysis; component measurements and full path completeness remain unavailable.",
                "id": "propagation",
                "partialImplementationReason": "bounded_observed_paths_have_no_component_measurements_or_completeness_and_freshness_sla",
                "projectionBindings": [
                    {
                        "projectionId": "social360",
                        "role": "primary",
                        "subjectKinds": ("entity", "relationship"),
                        "sectionIds": ("propagation",)
                    }
                ],
                "requirement": "required"
            },
            {
                "id": "relationship_graph",
                "requirement": "optional",
                "description": "Relationship facts and graph context.",
                "canonicalAuthorityRefs": ("cohort_membership", "graph", "identity", "relationship_facts"),
                "projectionBindings": [
                    {
                        "projectionId": "relationship360",
                        "role": "primary",
                        "subjectKinds": ("entity", "population", "relationship", "source"),
                        "sectionIds": ("evidence", "interactions", "summary")
                    }
                ]
            },
            {
                "id": "relationship_map",
                "requirement": "required",
                "description": "Recorded Social Silver connection facts; not canonical graph edges.",
                "canonicalAuthorityRefs": ("social_observations",),
                "projectionBindings": [
                    {
                        "projectionId": "social360",
                        "role": "primary",
                        "subjectKinds": ("entity", "population", "relationship", "source"),
                        "sectionIds": ("evidence", "findings")
                    }
                ]
            },
            {
                "canonicalAuthorityRefs": ("graph", "relationship_facts", "risk_outputs"),
                "description": "Policy governed risk relationship edges.",
                "id": "risk_edges",
                "partialImplementationReason": "Only evidence-linked current SHARES_RISK_CONTEXT_WITH edges are projected as correlated context; policy, freshness, trust, propagation, contagion, and causality remain unestablished.",
                "projectionBindings": [
                    {
                        "projectionId": "social360",
                        "role": "primary",
                        "subjectKinds": ("entity", "relationship"),
                        "sectionIds": ("risk_edges",)
                    }
                ],
                "requirement": "required"
            },
            {
                "canonicalAuthorityRefs": ("entity_identity", "graph", "relationship_facts", "risk_outputs", "risk_signals", "social_observations", "social_relationship_evidence_events", "source_provenance"),
                "description": "Exact source-reported social risk association over a validated canonical entity path with source ingress, risk signal, actor and evidence references; causality remains unverified.",
                "id": "social_contagion",
                "partialImplementationReason": "Source-reported correlated path evidence is available, but causal contagion, source reliability policy, completeness and freshness remain unknown.",
                "projectionBindings": [
                    {
                        "projectionId": "social360",
                        "role": "primary",
                        "subjectKinds": ("entity",),
                        "sectionIds": ("social_contagion",)
                    }
                ],
                "requirement": "required"
            },
            {
                "id": "social_observations_and_sources",
                "requirement": "optional",
                "description": "Social observations and their source facts.",
                "canonicalAuthorityRefs": ("cohort_membership", "identity", "social_observations", "source_facts"),
                "projectionBindings": [
                    {
                        "projectionId": "social360",
                        "role": "primary",
                        "subjectKinds": ("entity", "population", "relationship", "source"),
                        "sectionIds": ("evidence", "interactions", "summary", "timeline")
                    }
                ]
            },
            {
                "canonicalAuthorityRefs": ("cohort_membership", "evidence", "graph", "population_definitions"),
                "description": "Verified syndicate membership and topology.",
                "id": "syndicates",
                "partialImplementationReason": "membership_roster_completeness_historical_replay_and_freshness_remain_unknown",
                "projectionBindings": [
                    {
                        "projectionId": "social360",
                        "role": "primary",
                        "subjectKinds": ("entity",),
                        "sectionIds": ("syndicates",)
                    }
                ],
                "requirement": "required"
            },
            {
                "canonicalAuthorityRefs": ("authenticated_tenant_permission", "entity_identity", "relationship_facts", "social_relationship_evidence_events"),
                "description": "Authenticated tenant operator trust assertion for an exact canonical entity pair, with actor and policy-grant evidence; no inferred trust score or graph edge.",
                "id": "trust_edges",
                "partialImplementationReason": "Operator-asserted directional trust is available; policy-derived trust semantics, relationship graph mutation, score, completeness and freshness remain unknown.",
                "projectionBindings": [
                    {
                        "projectionId": "social360",
                        "role": "primary",
                        "subjectKinds": ("entity",),
                        "sectionIds": ("trust_edges",)
                    }
                ],
                "requirement": "required"
            }
        ],
        "freshnessPolicy": {
            "required": True,
            "maxAgeSeconds": None,
            "sourceTimestamps": "preserve",
            "missingTimestamp": "unknown",
            "onStale": "mark_affected_slots_stale",
            "requirementStatus": "contract_requirement_not_provider_attestation"
        },
        "id": "social360",
        "lensContract": {
            "expectedCount": 8,
            "lensIds": ("communications", "identity", "provenance", "relationship", "risk", "social", "syndicate", "value"),
            "sourceAlignmentStatus": "source_aligned"
        },
        "policyBehavior": {
            "tenantScopeRequired": True,
            "authorizationBeforeRead": True,
            "policyEvaluation": "per_projection_before_composition",
            "historicalConsentEvaluation": "required_when_applicable",
            "redactionBehavior": "suppress_disallowed_slot_without_inference",
            "requirementStatus": "contract_requirement_not_provider_attestation"
        },
        "projectionBindings": [
            {
                "projectionId": "geographic360",
                "role": "primary",
                "bindingStatus": "catalog_only",
                "providerImplementationState": "implemented"
            },
            {
                "projectionId": "population360",
                "role": "primary",
                "bindingStatus": "catalog_only",
                "providerImplementationState": "implemented"
            },
            {
                "projectionId": "relationship360",
                "role": "primary",
                "bindingStatus": "catalog_only",
                "providerImplementationState": "in_flight"
            },
            {
                "projectionId": "social360",
                "role": "primary",
                "bindingStatus": "catalog_only",
                "providerImplementationState": "in_flight"
            },
            {
                "projectionId": "source360",
                "role": "supporting",
                "bindingStatus": "catalog_only",
                "providerImplementationState": "in_flight"
            }
        ],
        "sourceOfTruth": {
            "canonicalAuthorities": ("authenticated_tenant_permission", "cohort_membership", "computation", "entity_identity", "evidence", "geo_observations", "graph", "identity", "influence_propagation", "locations", "population_definitions", "relationship_facts", "relationship_fidelity", "relationship_predicate_registry", "risk_outputs", "risk_signals", "social_observations", "social_relationship_evidence_events", "source_coverage", "source_facts", "source_provenance"),
            "ownsCanonicalTruth": False,
            "prohibitedOwnership": ("economic_facts", "execution_facts", "graph", "identity", "observations", "risk_outputs", "source_provenance")
        },
        "subjectKinds": ("community", "entity", "population", "profile", "relationship", "source", "syndicate")
    },
    "support360": {
        "backendCapabilities": {
            "required": ("experience360.evidence.provenance", "experience360.frame.compose", "experience360.freshness.evaluate", "experience360.policy.evaluate", "experience360.tenant_scope.enforce"),
            "projectionCapabilityKeys": ("agent360.explore", "agent360.read", "episode360.explore", "episode360.read", "outcome360.explore", "outcome360.read", "profile360.explore", "profile360.read", "risk360.explore", "risk360.read", "source360.explore", "source360.read", "support360.explore", "support360.read"),
            "providerCapabilityStatus": "registry_requirements_not_route_attestation"
        },
        "blueprintContract": {
            "canonicalOwner": "support_callback_graph",
            "priority": "P2",
            "purpose": "Provides support cases, callbacks, conversations, participants, agent handoffs, SLA, and resolution state.",
            "requiredLensIds": ("communications", "identity", "journey", "policy", "risk", "support", "workflow"),
            "requiredSlotIds": ("agents", "callbacks", "case_summary", "conversation_history", "evidence_trace", "journey_links", "participants", "resolution", "risk", "sla"),
            "sourceSection": "11.18",
            "subjectIdentifiers": ("callback_id", "conversation_id", "support_case_id", "ticket_id")
        },
        "contractStatus": "source_aligned",
        "description": "Governed support context composed from communications, episodes and journeys, entity identity, and evidence.",
        "displayName": "Support 360",
        "domainSlots": [
            {
                "canonicalAuthorityRefs": ("agent_entities", "communication_facts", "support_case_agent_assignment_events", "support_cases"),
                "description": "Validated support agent assignments and handoffs.",
                "id": "agents",
                "partialImplementationReason": "Append-only exact case assignment and handoff events resolve canonical Agent identities and assigning principals; upstream history, delegation authority, and freshness remain unknown.",
                "projectionBindings": [
                    {
                        "projectionId": "support360",
                        "role": "primary",
                        "subjectKinds": ("support_case",),
                        "sectionIds": ("evidence", "state")
                    }
                ],
                "requirement": "required"
            },
            {
                "canonicalAuthorityRefs": ("evidence", "provider_connections", "support_callback_events", "support_callbacks", "support_case_events", "support_cases"),
                "description": "Canonical callback schedule and execution records joined to the exact tenant, support case, provider connection, and retained callback events.",
                "id": "callbacks",
                "partialImplementationReason": "callback_schedule_and_execution_authority_is_tenant_case_connection_scoped_but_upstream_provider_origin_and_actor_attribution_are_unverified; source_history_completeness_and_freshness_remain_unknown",
                "projectionBindings": [
                    {
                        "projectionId": "support360",
                        "role": "primary",
                        "subjectKinds": ("callback", "support_case"),
                        "sectionIds": ("evidence", "state", "timeline")
                    }
                ],
                "requirement": "required"
            },
            {
                "canonicalAuthorityRefs": ("evidence", "provider_connections", "support_case_events", "support_cases"),
                "description": "Exact tenant-owned support case identity and observed lifecycle state from persisted source events.",
                "id": "case_summary",
                "partialImplementationReason": "persisted_case_events_do_not_prove_source_history_completeness_or_freshness_sla",
                "projectionBindings": [
                    {
                        "projectionId": "support360",
                        "role": "primary",
                        "subjectKinds": ("support_case",),
                        "sectionIds": ("evidence", "state", "summary")
                    }
                ],
                "requirement": "required"
            },
            {
                "canonicalAuthorityRefs": ("communication_facts", "evidence", "provider_connections", "support_case_events", "support_cases"),
                "description": "Tenant scoped support communication metadata; bodies require separate content permission.",
                "id": "conversation_history",
                "partialImplementationReason": "Canonical support_case history joins only through the exact tenant, provider connection, and source case key; message bodies and participant identities stay suppressed without their separate authorities, source-history completeness is unverified, and no freshness SLA is available.",
                "projectionBindings": [
                    {
                        "projectionId": "support360",
                        "role": "primary",
                        "subjectKinds": ("entity", "support_case"),
                        "sectionIds": ("interactions",)
                    }
                ],
                "requirement": "required"
            },
            {
                "id": "entity_and_agent_context",
                "requirement": "optional",
                "description": "Identity and agent context associated with support activity.",
                "canonicalAuthorityRefs": ("agent_entity", "identity"),
                "projectionBindings": [
                    {
                        "projectionId": "agent360",
                        "role": "supporting",
                        "subjectKinds": ("agent", "entity"),
                        "sectionIds": ("evidence", "state", "summary")
                    },
                    {
                        "projectionId": "profile360",
                        "role": "primary",
                        "subjectKinds": ("agent", "entity"),
                        "sectionIds": ("state", "summary")
                    }
                ]
            },
            {
                "canonicalAuthorityRefs": ("communication_facts", "evidence", "provider_connections", "support_case_events", "support_cases"),
                "description": "Source references for exact support communication metadata or case lifecycle; message bodies are excluded.",
                "id": "evidence_trace",
                "partialImplementationReason": "source_history_completeness_and_freshness_sla_are_unverified",
                "projectionBindings": [
                    {
                        "projectionId": "support360",
                        "role": "primary",
                        "subjectKinds": ("entity", "support_case"),
                        "sectionIds": ("evidence", "state", "summary")
                    }
                ],
                "requirement": "required"
            },
            {
                "canonicalAuthorityRefs": ("episode_facts", "journeys", "support_case_context_events", "support_cases"),
                "description": "Exact support case to journey relationships.",
                "id": "journey_links",
                "partialImplementationReason": "Append-only support case journey-link events join current exact tenant journey records. An EpisodeRecord is linked only when it names the same journey and cites the exact verified case context event; no live producer populates that relation today, and source authorship, historical state, complete population, and freshness remain unknown.",
                "projectionBindings": [
                    {
                        "projectionId": "support360",
                        "role": "primary",
                        "subjectKinds": ("support_case",),
                        "sectionIds": ("evidence", "state")
                    }
                ],
                "requirement": "required"
            },
            {
                "id": "measured_outcomes",
                "requirement": "optional",
                "description": "Measured support outcomes where an authoritative provider exists.",
                "canonicalAuthorityRefs": ("outcome_facts",),
                "projectionBindings": [
                    {
                        "projectionId": "outcome360",
                        "role": "primary",
                        "subjectKinds": ("episode",),
                        "sectionIds": ("evidence", "outcomes")
                    }
                ]
            },
            {
                "canonicalAuthorityRefs": ("communication_facts", "identity", "provider_connections", "support_cases"),
                "description": "Case participants with identity and content policy.",
                "id": "participants",
                "partialImplementationReason": "Participants require exact support-scoped communication thread and current provider account binding; identity linkage, source history, historical membership, and freshness may remain unknown.",
                "projectionBindings": [
                    {
                        "projectionId": "support360",
                        "role": "primary",
                        "subjectKinds": ("support_case",),
                        "sectionIds": ("evidence", "interactions")
                    }
                ],
                "requirement": "required"
            },
            {
                "canonicalAuthorityRefs": ("support_case_events", "support_cases"),
                "description": "Recorded support outcome and resolution state; lifecycle resolution alone does not prove the business outcome.",
                "id": "resolution",
                "partialImplementationReason": "exact_applied_case_lifecycle_event_and_provider_connection_evidence_support_resolved_or_closed_state; canonical_business_outcome_facts_remain_unavailable",
                "projectionBindings": [
                    {
                        "projectionId": "support360",
                        "role": "primary",
                        "subjectKinds": ("support_case",),
                        "sectionIds": ("outcomes", "state")
                    }
                ],
                "requirement": "required"
            },
            {
                "canonicalAuthorityRefs": ("evidence", "risk_outputs", "risk_signals", "support_cases"),
                "description": "Risk outputs associated with the exact support case.",
                "id": "risk",
                "implementationCrosswalk": ("risk_and_contagion",),
                "partialImplementationReason": "The tenant-owned support case and its exact risk assessment and signals are joined with canonical evidence; risk-history completeness, support-case freshness SLA, and business outcome remain unknown.",
                "projectionBindings": [
                    {
                        "projectionId": "risk360",
                        "role": "primary",
                        "subjectKinds": ("support_case",),
                        "sectionIds": ("evidence", "findings", "state", "summary")
                    }
                ],
                "requirement": "required"
            },
            {
                "id": "risk_context",
                "requirement": "optional",
                "description": "Risk context from its governing projection, subject to policy.",
                "canonicalAuthorityRefs": ("risk_outputs",),
                "projectionBindings": [
                    {
                        "projectionId": "risk360",
                        "role": "primary",
                        "subjectKinds": ("entity",),
                        "sectionIds": ("evidence", "findings", "summary")
                    }
                ]
            },
            {
                "canonicalAuthorityRefs": ("measurement_contract", "support_case_context_events", "support_cases"),
                "description": "Support service level contract and timer state.",
                "id": "sla",
                "partialImplementationReason": "Exact tenant-registered source policy revisions bind matching case timers and target durations, with contract evidence. Historical applicability, measured breach evaluation, source-history completeness, and freshness remain unknown.",
                "projectionBindings": [
                    {
                        "projectionId": "support360",
                        "role": "primary",
                        "subjectKinds": ("support_case",),
                        "sectionIds": ("evidence", "state")
                    }
                ],
                "requirement": "required"
            },
            {
                "id": "source_lineage_and_coverage",
                "requirement": "optional",
                "description": "Source provenance and coverage for support context.",
                "canonicalAuthorityRefs": ("source_coverage", "source_provenance"),
                "projectionBindings": [
                    {
                        "projectionId": "source360",
                        "role": "primary",
                        "subjectKinds": ("source",),
                        "sectionIds": ("coverage", "evidence")
                    }
                ]
            },
            {
                "id": "support_communications",
                "requirement": "optional",
                "description": "Communication events and interaction evidence.",
                "canonicalAuthorityRefs": ("communication_facts", "evidence"),
                "projectionBindings": [
                    {
                        "projectionId": "support360",
                        "role": "primary",
                        "subjectKinds": ("entity",),
                        "sectionIds": ("evidence", "interactions", "outcomes", "state", "summary", "timeline")
                    }
                ]
            },
            {
                "id": "support_episode_and_journey",
                "requirement": "optional",
                "description": "Episode and journey context for support interactions.",
                "canonicalAuthorityRefs": ("episode_facts", "events", "journeys"),
                "projectionBindings": [
                    {
                        "projectionId": "episode360",
                        "role": "primary",
                        "subjectKinds": ("entity", "episode"),
                        "sectionIds": ("evidence", "state", "summary", "timeline")
                    }
                ]
            }
        ],
        "freshnessPolicy": {
            "required": True,
            "maxAgeSeconds": None,
            "sourceTimestamps": "preserve",
            "missingTimestamp": "unknown",
            "onStale": "mark_affected_slots_stale",
            "requirementStatus": "contract_requirement_not_provider_attestation"
        },
        "id": "support360",
        "lensContract": {
            "expectedCount": 7,
            "lensIds": ("communications", "identity", "journey", "policy", "risk", "support", "workflow"),
            "sourceAlignmentStatus": "source_aligned"
        },
        "policyBehavior": {
            "tenantScopeRequired": True,
            "authorizationBeforeRead": True,
            "policyEvaluation": "per_projection_before_composition",
            "historicalConsentEvaluation": "required_when_applicable",
            "redactionBehavior": "suppress_disallowed_slot_without_inference",
            "requirementStatus": "contract_requirement_not_provider_attestation"
        },
        "projectionBindings": [
            {
                "projectionId": "agent360",
                "role": "supporting",
                "bindingStatus": "catalog_only",
                "providerImplementationState": "in_flight"
            },
            {
                "projectionId": "episode360",
                "role": "primary",
                "bindingStatus": "catalog_only",
                "providerImplementationState": "in_flight"
            },
            {
                "projectionId": "outcome360",
                "role": "primary",
                "bindingStatus": "catalog_only",
                "providerImplementationState": "implemented"
            },
            {
                "projectionId": "profile360",
                "role": "primary",
                "bindingStatus": "catalog_only",
                "providerImplementationState": "in_flight"
            },
            {
                "projectionId": "risk360",
                "role": "primary",
                "bindingStatus": "catalog_only",
                "providerImplementationState": "implemented"
            },
            {
                "projectionId": "source360",
                "role": "primary",
                "bindingStatus": "catalog_only",
                "providerImplementationState": "in_flight"
            },
            {
                "projectionId": "support360",
                "role": "primary",
                "bindingStatus": "catalog_only",
                "providerImplementationState": "in_flight"
            }
        ],
        "sourceOfTruth": {
            "canonicalAuthorities": ("agent_entities", "agent_entity", "communication_facts", "episode_facts", "events", "evidence", "identity", "journeys", "measurement_contract", "outcome_facts", "provider_connections", "risk_outputs", "risk_signals", "source_coverage", "source_provenance", "support_callback_events", "support_callbacks", "support_case_agent_assignment_events", "support_case_context_events", "support_case_events", "support_cases"),
            "ownsCanonicalTruth": False,
            "prohibitedOwnership": ("economic_facts", "execution_facts", "graph", "identity", "observations", "risk_outputs", "source_provenance")
        },
        "subjectKinds": ("agent", "callback", "conversation", "entity", "episode", "source", "support_case", "ticket")
    },
    "value360": {
        "backendCapabilities": {
            "required": ("experience360.evidence.provenance", "experience360.frame.compose", "experience360.freshness.evaluate", "experience360.policy.evaluate", "experience360.tenant_scope.enforce"),
            "projectionCapabilityKeys": ("campaign360.explore", "campaign360.read", "economic360.explore", "economic360.read", "outcome360.explore", "outcome360.read", "risk360.explore", "risk360.read", "temporal360.explore", "temporal360.read"),
            "providerCapabilityStatus": "registry_requirements_not_route_attestation"
        },
        "blueprintContract": {
            "canonicalOwner": "value_attribution",
            "priority": "P0",
            "purpose": "Normalizes Web2 and Web3 value, conversions, revenue, and attribution credits into a governed backend frame.",
            "requiredLensIds": ("attribution", "campaign", "commerce", "identity", "journey", "provenance", "risk", "value"),
            "requiredSlotIds": ("attribution_credits", "confidence", "conversion_inventory", "evidence_trace", "financial_risk", "ltv", "reconciliation", "revenue_events", "value_summary", "web2_value", "web3_value"),
            "sourceSection": "11.9",
            "subjectIdentifiers": ("account_id", "campaign_id", "conversion_id", "profile_id", "value_subject_id", "wallet_cluster_id")
        },
        "contractStatus": "source_aligned",
        "description": "Governed view of economic facts, payment and commerce evidence, attribution, and measured outcomes; missing values remain explicit.",
        "displayName": "Value 360",
        "domainSlots": [
            {
                "canonicalAuthorityRefs": ("ai_execution_facts", "attribution_credits", "attribution_runs", "campaign_touchpoints", "canonical_conversions"),
                "description": "Credited value allocated by canonical attribution authority.",
                "id": "attribution_credits",
                "partialImplementationReason": "attribution_credit_reads_are_bounded_and_explicitly_truncated_but_history_is_not_bitemporal_and_model_credit_is_not_independently_measured_value",
                "projectionBindings": [
                    {
                        "projectionId": "economic360",
                        "role": "primary",
                        "subjectKinds": ("account", "agent", "campaign", "cluster", "conversion", "entity", "episode", "journey", "profile", "source"),
                        "sectionIds": ("evidence",)
                    }
                ],
                "requirement": "required"
            },
            {
                "id": "campaign_and_attribution_context",
                "requirement": "optional",
                "description": "Campaign facts and attribution credits associated with value.",
                "canonicalAuthorityRefs": ("attribution_credits", "campaign_facts"),
                "projectionBindings": [
                    {
                        "projectionId": "campaign360",
                        "role": "primary",
                        "subjectKinds": ("campaign", "episode"),
                        "sectionIds": ("evidence", "outcomes", "summary")
                    }
                ]
            },
            {
                "authorityGapReason": "model_governance_calibration_and_validation_not_joined",
                "canonicalAuthorityRefs": ("ai_execution_facts", "attribution_credits", "attribution_runs", "canonical_conversions", "model_governance"),
                "description": "Evidence-linked, model-reported attribution confidence only; not a calibrated estimate of realized value or ROI.",
                "id": "confidence",
                "partialImplementationReason": "Exact conversion/run/credit-linked model-reported confidence may include a persisted check of recorded run configuration lineage against the current matching config. Model governance approval, calibration, historical config immutability, and applicability to realized value remain unvalidated.",
                "projectionBindings": [
                    {
                        "projectionId": "economic360",
                        "role": "primary",
                        "subjectKinds": ("account", "agent", "campaign", "cluster", "conversion", "entity", "journey", "profile"),
                        "sectionIds": ("evidence",)
                    }
                ],
                "requirement": "required",
                "unboundCanonicalAuthorityRefs": ("model_governance",)
            },
            {
                "canonicalAuthorityRefs": ("ai_execution_facts", "canonical_conversions", "entity_registry", "identity_clusters_v2"),
                "description": "Canonical conversion ledger records linked to exact tenant-scoped subject identity; account subjects resolve through Account360 entity authority and cluster subjects through the active identity-cluster authority before current conversion reads.",
                "id": "conversion_inventory",
                "partialImplementationReason": "Exact account entity identity and active identity-cluster records gate their conversion inventories; wallet-cluster crosswalks, historical replay, full source coverage, and freshness remain unknown.",
                "projectionBindings": [
                    {
                        "projectionId": "economic360",
                        "role": "primary",
                        "subjectKinds": ("account", "agent", "campaign", "cluster", "conversion", "entity", "journey", "profile"),
                        "sectionIds": ("evidence",)
                    }
                ],
                "requirement": "required"
            },
            {
                "id": "economic_facts_and_state",
                "requirement": "optional",
                "description": "Economic facts and value state with currency normalization provenance.",
                "canonicalAuthorityRefs": ("ai_execution_facts", "currency_value_normalization", "economic_facts"),
                "projectionBindings": [
                    {
                        "projectionId": "economic360",
                        "role": "primary",
                        "subjectKinds": ("campaign", "episode", "journey"),
                        "sectionIds": ("evidence", "state", "summary")
                    }
                ]
            },
            {
                "id": "evidence_trace",
                "requirement": "required",
                "description": "Canonical economic, payment, commerce, and conversion evidence references for exact supported subjects.",
                "canonicalAuthorityRefs": ("ai_execution_facts", "canonical_conversions", "commerce", "economic_facts", "payments"),
                "projectionBindings": [
                    {
                        "projectionId": "economic360",
                        "role": "primary",
                        "subjectKinds": ("account", "agent", "campaign", "cluster", "conversion", "entity", "episode", "journey", "profile", "source"),
                        "sectionIds": ("evidence", "summary")
                    }
                ]
            },
            {
                "canonicalAuthorityRefs": ("ai_execution_facts", "economic_facts", "risk_outputs"),
                "description": "Financial risk linked to economic facts by exact subject.",
                "id": "financial_risk",
                "partialImplementationReason": "Exact tenant and subject economic claims join only to assessed economic, payment, or transaction Risk360 dimension claims on current reads; historical joins, coordinated freshness thresholds, and complete source coverage remain unknown.",
                "projectionBindings": [
                    {
                        "projectionId": "economic360",
                        "role": "primary",
                        "subjectKinds": ("agent", "cluster", "entity", "source"),
                        "sectionIds": ("evidence", "summary")
                    },
                    {
                        "projectionId": "risk360",
                        "role": "supporting",
                        "subjectKinds": ("agent", "cluster", "entity", "source"),
                        "sectionIds": ("financial_risk",)
                    }
                ],
                "requiredClaimProjectionIds": ("economic360", "risk360"),
                "requirement": "required"
            },
            {
                "canonicalAuthorityRefs": ("ai_execution_facts", "canonical_conversions", "evidence"),
                "description": "Evidence-backed confirmed or adjusted canonical conversion net value over a defined subject and temporal scope; full lifetime coverage remains unknown and native currencies stay partitioned.",
                "id": "ltv",
                "partialImplementationReason": "Exact evidence-backed confirmed_or_adjusted conversion net values are reported only for the canonical rows returned; lifetime and historical completeness, outcome attribution, and freshness remain unknown, missing net values degrade the slot, and native currency totals are not combined.",
                "projectionBindings": [
                    {
                        "projectionId": "economic360",
                        "role": "primary",
                        "subjectKinds": ("account", "agent", "campaign", "cluster", "entity", "journey", "profile"),
                        "sectionIds": ("evidence",)
                    }
                ],
                "requirement": "required"
            },
            {
                "id": "measured_outcomes",
                "requirement": "optional",
                "description": "Measured outcome facts linked to economic value.",
                "canonicalAuthorityRefs": ("measurement_contract", "outcome_facts"),
                "projectionBindings": [
                    {
                        "projectionId": "outcome360",
                        "role": "primary",
                        "subjectKinds": ("campaign", "episode", "journey"),
                        "sectionIds": ("evidence", "outcomes", "summary")
                    }
                ]
            },
            {
                "id": "payments_and_commerce_evidence",
                "requirement": "optional",
                "description": "Payment and commerce evidence from the corresponding authorities.",
                "canonicalAuthorityRefs": ("ai_execution_facts", "commerce", "payments"),
                "projectionBindings": [
                    {
                        "projectionId": "economic360",
                        "role": "primary",
                        "subjectKinds": ("campaign", "episode", "journey"),
                        "sectionIds": ("evidence", "outcomes")
                    }
                ]
            },
            {
                "canonicalAuthorityRefs": ("ai_execution_facts", "commerce", "currency_value_normalization", "economic_facts", "evidence", "payments"),
                "description": "Separate source-native economic and commerce observations with exact settlement-to-payment references; cross-source reconciliation remains explicit.",
                "id": "reconciliation",
                "implementationCrosswalk": ("value_source_reconciliation_observations",),
                "partialImplementationReason": "Subject-scoped economic rows and exact order-linked commerce facts remain separate observations. Settlement-to-payment links require the explicit provider payment ID and same commerce order reference; only native USD identity normalization is accepted. Economic records lack exact order, payment, and settlement IDs, so cross-source matching, non-USD commerce normalization, reconciled totals, and completeness remain unavailable.",
                "projectionBindings": [
                    {
                        "projectionId": "economic360",
                        "role": "primary",
                        "subjectKinds": ("campaign", "entity", "journey"),
                        "sectionIds": ("evidence",)
                    }
                ],
                "requirement": "required"
            },
            {
                "canonicalAuthorityRefs": ("ai_execution_facts", "canonical_conversions", "economic_facts", "payments", "revenue_adjustments"),
                "description": "Source-settled payment observations and append-only canonical conversion revenue-adjustment events with exact tenant-scoped joins and transaction evidence; adjustment event-time windows are queried against the exact unwindowed conversion subject or the returned conversion cohort, without a recognized revenue total.",
                "id": "revenue_events",
                "partialImplementationReason": "Bounded revenue-adjustment reads join exact canonical conversions and apply strict event-time windows; conversion subjects are re-read without a conversion-occurrence filter so older conversions adjusted in the requested window remain eligible. Broader subject cohorts can still omit older conversions; other revenue sources, historical replay, full source coverage, reconciliation, and attribution remain unknown.",
                "projectionBindings": [
                    {
                        "projectionId": "economic360",
                        "role": "primary",
                        "subjectKinds": ("account", "agent", "campaign", "cluster", "conversion", "entity", "journey", "profile"),
                        "sectionIds": ("evidence",)
                    }
                ],
                "requirement": "required"
            },
            {
                "id": "temporal_context",
                "requirement": "optional",
                "description": "Temporal context for value facts and comparisons.",
                "canonicalAuthorityRefs": ("temporal_kernel",),
                "projectionBindings": [
                    {
                        "projectionId": "temporal360",
                        "role": "primary",
                        "subjectKinds": [],
                        "sectionIds": ("state", "timeline")
                    }
                ]
            },
            {
                "id": "value_summary",
                "requirement": "required",
                "description": "Subject-scoped computed economic value with explicit missing, zero, and source currency states; no inferred attribution or AI cost aggregation.",
                "canonicalAuthorityRefs": ("ai_execution_facts", "currency_value_normalization", "economic_facts"),
                "projectionBindings": [
                    {
                        "projectionId": "economic360",
                        "role": "primary",
                        "subjectKinds": ("agent", "campaign", "entity", "episode", "journey", "source"),
                        "sectionIds": ("summary",)
                    }
                ]
            },
            {
                "canonicalAuthorityRefs": ("ai_execution_facts", "canonical_activity", "commerce", "commerce_order_payment_ledger", "journey_steps", "payments"),
                "description": "Evidence-backed Web2 payment observations classified only after exact subject activity or journey-step association, tenant commerce-ledger order reference, and source payment evidence agree on a supported rail.",
                "id": "web2_value",
                "partialImplementationReason": "Only completed payment facts with exact campaign/entity activity or current journey-step evidence, the same tenant commerce-ledger order reference, and source transaction evidence are classified when the rail is explicitly supported. Non-USD normalization, historical association, source coverage, policy, and freshness remain unknown.",
                "projectionBindings": [
                    {
                        "projectionId": "economic360",
                        "role": "primary",
                        "subjectKinds": ("campaign", "entity", "journey"),
                        "sectionIds": ("evidence",)
                    }
                ],
                "requirement": "required"
            },
            {
                "canonicalAuthorityRefs": ("ai_execution_facts", "canonical_activity", "commerce", "commerce_order_payment_ledger", "currency_value_normalization", "journey_steps"),
                "description": "Evidence-backed Web3 native-asset payment observations with exact subject association and commerce-ledger order reference plus explicit flow, rail, chain, asset, amount, and transaction-hash evidence.",
                "id": "web3_value",
                "partialImplementationReason": "Only completed source payment facts with exact campaign/entity activity or current journey-step evidence, the same tenant commerce-ledger order reference, explicit crypto flow or on-chain rail, and a complete asset leg plus transaction-hash evidence are classified. Wallet identity, currency normalization, historical association, source coverage, policy, and freshness remain unknown.",
                "projectionBindings": [
                    {
                        "projectionId": "economic360",
                        "role": "primary",
                        "subjectKinds": ("campaign", "entity", "journey"),
                        "sectionIds": ("evidence",)
                    }
                ],
                "requirement": "required"
            }
        ],
        "freshnessPolicy": {
            "required": True,
            "maxAgeSeconds": None,
            "sourceTimestamps": "preserve",
            "missingTimestamp": "unknown",
            "onStale": "mark_affected_slots_stale",
            "requirementStatus": "contract_requirement_not_provider_attestation"
        },
        "id": "value360",
        "lensContract": {
            "expectedCount": 8,
            "lensIds": ("attribution", "campaign", "commerce", "identity", "journey", "provenance", "risk", "value"),
            "sourceAlignmentStatus": "source_aligned"
        },
        "policyBehavior": {
            "tenantScopeRequired": True,
            "authorizationBeforeRead": True,
            "policyEvaluation": "per_projection_before_composition",
            "historicalConsentEvaluation": "required_when_applicable",
            "redactionBehavior": "suppress_disallowed_slot_without_inference",
            "requirementStatus": "contract_requirement_not_provider_attestation"
        },
        "projectionBindings": [
            {
                "projectionId": "campaign360",
                "role": "primary",
                "bindingStatus": "catalog_only",
                "providerImplementationState": "in_flight"
            },
            {
                "projectionId": "economic360",
                "role": "primary",
                "bindingStatus": "catalog_only",
                "providerImplementationState": "implemented"
            },
            {
                "projectionId": "outcome360",
                "role": "primary",
                "bindingStatus": "catalog_only",
                "providerImplementationState": "implemented"
            },
            {
                "projectionId": "risk360",
                "role": "supporting",
                "bindingStatus": "catalog_only",
                "providerImplementationState": "implemented"
            },
            {
                "projectionId": "temporal360",
                "role": "primary",
                "bindingStatus": "catalog_only",
                "providerImplementationState": "implemented"
            }
        ],
        "sourceOfTruth": {
            "canonicalAuthorities": ("ai_execution_facts", "attribution_credits", "attribution_runs", "campaign_facts", "campaign_touchpoints", "canonical_activity", "canonical_conversions", "commerce", "commerce_order_payment_ledger", "currency_value_normalization", "economic_facts", "entity_registry", "evidence", "identity_clusters_v2", "journey_steps", "measurement_contract", "model_governance", "outcome_facts", "payments", "revenue_adjustments", "risk_outputs", "temporal_kernel"),
            "ownsCanonicalTruth": False,
            "prohibitedOwnership": ("economic_facts", "execution_facts", "graph", "identity", "observations", "risk_outputs", "source_provenance")
        },
        "subjectKinds": ("account", "agent", "campaign", "cluster", "conversion", "entity", "episode", "journey", "profile", "source", "value")
    },
    "workflow360": {
        "backendCapabilities": {
            "required": ("experience360.evidence.provenance", "experience360.frame.compose", "experience360.freshness.evaluate", "experience360.policy.evaluate", "experience360.tenant_scope.enforce"),
            "projectionCapabilityKeys": ("workflow360.read",),
            "providerCapabilityStatus": "registry_requirements_not_route_attestation"
        },
        "blueprintContract": {
            "canonicalOwner": "workflow_automation_runtime",
            "priority": "P1",
            "purpose": "Surfaces workflow definitions, automation triggers, runs, approvals, actions, and agent/human authority boundaries.",
            "requiredLensIds": ("agentic", "automation", "execution", "identity", "policy", "risk", "value", "workflow"),
            "requiredSlotIds": ("actions", "actors", "agent_steps", "approvals", "evidence_trace", "failures", "outcomes", "risk", "runs", "triggers", "workflow_summary"),
            "sourceSection": "11.15",
            "subjectIdentifiers": ("automation_id", "run_id", "trigger_id", "workflow_id")
        },
        "contractStatus": "source_aligned",
        "description": "Governed operational view of agent executions, actions and tools, integration lifecycle, evidence, and optional outcomes.",
        "displayName": "Workflow 360",
        "domainSlots": [
            {
                "authorityGapReason": "Action and resource result authorities are not joined beyond the recorded execution to Tool call edge.",
                "canonicalAuthorityRefs": ("actions", "agent_executions", "graph_edges", "resources", "tools"),
                "description": "Exact tenant/run agent execution call edges joined to CALLED_TOOL graph edges and Tool vertices.",
                "id": "actions",
                "partialImplementationReason": "Call edges are bounded to 200 execution rows and 10000 graph edges. Exact tenant Tool vertices now have separate identity evidence when resolved; authorization, completion, external effects, resource results, producer coverage, historical replay, and freshness remain unknown.",
                "projectionBindings": [
                    {
                        "projectionId": "workflow360",
                        "role": "primary",
                        "subjectKinds": ("run", "workflow_run"),
                        "sectionIds": ("actions",)
                    }
                ],
                "requirement": "required",
                "unboundCanonicalAuthorityRefs": ("actions", "resources")
            },
            {
                "canonicalAuthorityRefs": ("agent_entities", "agent_executions", "ai_execution_facts", "commerce", "identity"),
                "description": "Exact run-linked AI invocation agents plus human initiator and approver identities resolved through active tenant USER_ID aliases; full actor coverage and workflow authority remain unknown.",
                "id": "actors",
                "partialImplementationReason": "Exact execution initiator and approval decider references resolve through unique active tenant USER_ID aliases; workflow-wide actor coverage and authority remain unknown.",
                "projectionBindings": [
                    {
                        "projectionId": "workflow360",
                        "role": "primary",
                        "subjectKinds": ("run", "workflow_run"),
                        "sectionIds": ("actors",)
                    }
                ],
                "requirement": "required"
            },
            {
                "canonicalAuthorityRefs": ("agent_executions",),
                "description": "Exact tenant and run-linked AgentExecution records admitted only when stored invocation IDs match run-linked AI facts and the stable action/execution ID; complete workflow step coverage remains unknown.",
                "id": "agent_steps",
                "partialImplementationReason": "The canonical AgentExecution writer persists workflow_run_id and exact invocation IDs when a unique tenant-scoped AI invocation has action_id equal to the stable execution ID. Workflow definition, complete step coverage, policy, and freshness remain unknown.",
                "projectionBindings": [
                    {
                        "projectionId": "workflow360",
                        "role": "primary",
                        "subjectKinds": ("run", "workflow_run"),
                        "sectionIds": ("agent_steps",)
                    }
                ],
                "requirement": "required"
            },
            {
                "canonicalAuthorityRefs": ("agent_access", "agent_executions", "commerce"),
                "description": "Exact x402 approval requests and decisions referenced by tenant and run-linked AgentExecutions; workflow-wide approval coverage and authorization policy remain unknown.",
                "id": "approvals",
                "partialImplementationReason": "Exact x402 approval decisions referenced by admitted run-linked AgentExecutions can carry the recorded human permission check and a matching request-time agent delegation decision with exact current grant, agent, action, resource and amount evidence. Workflow-wide coverage, historical policy replay, and current effective agent authorization remain unknown.",
                "projectionBindings": [
                    {
                        "projectionId": "workflow360",
                        "role": "primary",
                        "subjectKinds": ("run", "workflow_run"),
                        "sectionIds": ("approvals",)
                    }
                ],
                "requirement": "required"
            },
            {
                "id": "evidence_trace",
                "requirement": "required",
                "description": "Lineage of exact workflow run linked AI invocation facts.",
                "canonicalAuthorityRefs": ("ai_execution_facts",),
                "projectionBindings": [
                    {
                        "projectionId": "workflow360",
                        "role": "primary",
                        "subjectKinds": ("run", "workflow_run"),
                        "sectionIds": ("evidence_trace",)
                    }
                ]
            },
            {
                "id": "failures",
                "requirement": "required",
                "description": "Observed AI invocation failure status only; workflow failure state is unknown.",
                "canonicalAuthorityRefs": ("ai_execution_facts",),
                "projectionBindings": [
                    {
                        "projectionId": "workflow360",
                        "role": "primary",
                        "subjectKinds": ("run", "workflow_run"),
                        "sectionIds": ("failures",)
                    }
                ]
            },
            {
                "canonicalAuthorityRefs": ("ai_execution_facts", "evidence", "outcome_facts"),
                "description": "Canonical outcomes explicitly referenced by tenant-scoped invocation facts for an exact workflow run.",
                "id": "outcomes",
                "partialImplementationReason": "Only canonical outcome IDs explicitly referenced by tenant/run invocation facts are joined with invocation and outcome evidence; this association does not establish workflow causality or complete outcome coverage, and policy and freshness remain unknown.",
                "projectionBindings": [
                    {
                        "projectionId": "workflow360",
                        "role": "primary",
                        "subjectKinds": ("run", "workflow_run"),
                        "sectionIds": ("outcomes",)
                    }
                ],
                "requirement": "required"
            },
            {
                "canonicalAuthorityRefs": ("agent_executions", "risk_assessments"),
                "description": "Current canonical RiskAssessments for exact run-linked AgentExecution subjects.",
                "id": "risk",
                "partialImplementationReason": "Only current RiskAssessments for exact admitted AgentExecution subjects linked to the requested run are joined; workflow execution coverage, risk history, policy authority and replay, freshness, and causality remain unknown.",
                "projectionBindings": [
                    {
                        "projectionId": "workflow360",
                        "role": "primary",
                        "subjectKinds": ("run", "workflow_run"),
                        "sectionIds": ("risk",)
                    }
                ],
                "requirement": "required"
            },
            {
                "id": "runs",
                "requirement": "required",
                "description": "AI invocation facts explicitly linked to a workflow run ID; run state is partial.",
                "canonicalAuthorityRefs": ("ai_execution_facts",),
                "projectionBindings": [
                    {
                        "projectionId": "workflow360",
                        "role": "primary",
                        "subjectKinds": ("run", "workflow_run"),
                        "sectionIds": ("runs",)
                    }
                ]
            },
            {
                "canonicalAuthorityRefs": ("agent_executions", "events"),
                "description": "Exact run-linked event references stored on admitted AgentExecution records; does not establish workflow trigger causality or coverage.",
                "id": "triggers",
                "partialImplementationReason": "Only exact tenant/run-linked AgentExecution records and their stored trigger event references are joined; trigger definitions, workflow causality, complete coverage, policy authority, and freshness remain unknown.",
                "projectionBindings": [
                    {
                        "projectionId": "workflow360",
                        "role": "primary",
                        "subjectKinds": ("run", "workflow_run"),
                        "sectionIds": ("triggers",)
                    }
                ],
                "requirement": "required"
            },
            {
                "canonicalAuthorityRefs": ("execution_facts", "identity", "workflow_definition_revisions"),
                "description": "Latest or exact as-of tenant workflow definition revision, with registration evidence, current registrar identity when proven, and bounded caller-reported run association when exact execution references match.",
                "id": "workflow_summary",
                "partialImplementationReason": "Registered definition revision is bounded to an exact tenant workflow and a complete 200-revision as-of history read. The authenticated registrar can resolve through a current active tenant USER_ID alias with Human evidence. An exact run-linked AgentExecution may persist a caller-reported workflow id, revision, and digest only after tenant AI invocation and definition validation; Workflow360 rechecks the link and exposes it as a partial observation. Historical registrar identity and run-definition replay, unsupported external runs, complete run actors, trigger or step completion, external effects, and freshness remain unknown.",
                "projectionBindings": [
                    {
                        "projectionId": "workflow360",
                        "role": "primary",
                        "subjectKinds": ("automation", "run", "workflow", "workflow_run"),
                        "sectionIds": ("workflow_summary",)
                    }
                ],
                "requirement": "required"
            }
        ],
        "freshnessPolicy": {
            "required": True,
            "maxAgeSeconds": None,
            "sourceTimestamps": "preserve",
            "missingTimestamp": "unknown",
            "onStale": "mark_affected_slots_stale",
            "requirementStatus": "contract_requirement_not_provider_attestation"
        },
        "id": "workflow360",
        "lensContract": {
            "expectedCount": 8,
            "lensIds": ("agentic", "automation", "execution", "identity", "policy", "risk", "value", "workflow"),
            "sourceAlignmentStatus": "source_aligned"
        },
        "policyBehavior": {
            "tenantScopeRequired": True,
            "authorizationBeforeRead": True,
            "policyEvaluation": "per_projection_before_composition",
            "historicalConsentEvaluation": "required_when_applicable",
            "redactionBehavior": "suppress_disallowed_slot_without_inference",
            "requirementStatus": "contract_requirement_not_provider_attestation"
        },
        "projectionBindings": [
            {
                "projectionId": "workflow360",
                "role": "primary",
                "bindingStatus": "catalog_only",
                "providerImplementationState": "in_flight"
            }
        ],
        "sourceOfTruth": {
            "canonicalAuthorities": ("actions", "agent_access", "agent_entities", "agent_executions", "ai_execution_facts", "commerce", "events", "evidence", "execution_facts", "graph_edges", "identity", "outcome_facts", "resources", "risk_assessments", "tools", "workflow_definition_revisions"),
            "ownsCanonicalTruth": False,
            "prohibitedOwnership": ("economic_facts", "execution_facts", "graph", "identity", "observations", "risk_outputs", "source_provenance")
        },
        "subjectKinds": ("automation", "run", "trigger", "workflow", "workflow_run")
    },
}

# Pending canonical-authority declarations (sorted by projection id).
PENDING_AUTHORITIES: dict[str, list] = {
    "connection360": [
        {
            "id": "reconciled_control_plane",
            "kind": "spine",
            "reason": "harness control-plane rollup (PR #529) merged; reconciled control-plane spine not yet formalized as a projection-plane authority",
            "resolvesInProjection": "connection360"
        }
    ],
    "episode360": [
        {
            "id": "journey_continuity",
            "kind": "spine",
            "reason": "journey continuity plane not yet formalized",
            "resolvesInProjection": "episode360"
        }
    ],
}

# Pending reference declarations (sorted by projection id).
PENDING_REFERENCES: dict[str, list] = {
}

__all__ = [
    "EXPERIENCE_360_FRAME_STATES",
    "GRAPH_MUTATION_POLICIES",
    "INTELLIGENCE_PROJECTIONS_CONTRACT_VERSION",
    "INTELLIGENCE_PROJECTION_DEFINITIONS",
    "INTELLIGENCE_PROJECTION_IDS",
    "PENDING_AUTHORITIES",
    "PENDING_REFERENCES",
    "PRODUCT_360_SURFACE_CATALOG_VERSION",
    "PRODUCT_360_SURFACE_DEFINITIONS",
    "PRODUCT_360_SURFACE_IDS",
    "PROJECTION_CAPABILITY_MAP",
    "PROJECTION_DEPENDENCY_GRAPH",
    "PROJECTION_IMPLEMENTATION_STATES",
    "PROJECTION_KINDS",
    "PROJECTION_SECTION_STATES",
    "PROJECTION_SUBJECT_KINDS",
    "PROJECTION_SURFACE_MAP",
]
