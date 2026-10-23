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
        "canonicalAuthorities": ("agent_access", "agent_entities", "agent_entity", "agent_executions", "economic_facts", "evidence", "graph", "identity", "observations", "outcome_facts"),
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
        "canonicalAuthorities": ("attribution_credits", "campaign_facts", "campaign_touchpoints", "communication", "economic", "journeys", "outcomes", "population", "source_provenance", "targeting_leakage_findings", "touchpoints"),
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
        "canonicalAuthorities": ("campaign_facts", "commerce", "commerce_product_offer_graph", "payments", "source_provenance"),
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
        "subjectKinds": ("agent", "campaign", "episode", "journey", "source"),
        "canonicalAuthorities": ("campaign_touchpoints", "communication_facts", "entities", "evidence", "journeys", "outcomes", "risk_signals"),
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
        "canonicalAuthorities": ("ai_execution_facts", "attribution_credits", "attribution_runs", "canonical_conversions", "commerce", "currency_value_normalization", "economic_facts", "graph", "outcome_facts", "payments"),
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
        "canonicalAuthorities": ("campaign_touchpoints", "canonical_conversions", "episode_facts", "events", "evidence", "graph", "journeys", "temporal"),
        "hardDependencies": ("contract_spine", "journey_continuity", "temporal_kernel"),
        "projectionDependencies": ("profile360", "relationship360"),
        "optionalProjectionDependencies": [],
        "inputRefs": ("EntityRef", "EvidenceRef", "GraphSnapshotRef", "PageRequest", "RelationshipRef", "TimeRangeFilter"),
        "outputSections": ("episode_context", "evidence", "interactions", "outcomes", "stages", "state", "summary", "timeline"),
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
        "subjectKinds": ("agent", "entity", "episode", "execution"),
        "canonicalAuthorities": ("actions", "agent_access", "agent_entities", "agent_executions", "economic_facts", "entity_registry", "episode_facts", "events", "evidence", "execution_facts", "graph", "identity", "outcome_facts", "resources", "risk_signals", "temporal_kernel", "tools"),
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
        "canonicalAuthorities": ("context_capsules", "entity_graph", "geo_observations", "gold_temporal_heatmap", "locations", "temporal"),
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
        "canonicalAuthorities": ("consent_policy_decisions", "evidence", "semantic_memory_graph", "semantic_memory_records", "silver_semantic_observations", "source_provenance"),
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
        "canonicalAuthorities": ("agent_access", "agent_executions", "communication_facts", "entity_registry", "episode_facts", "evidence", "graph", "identity", "journeys", "observations", "temporal"),
        "hardDependencies": ("contract_spine", "evidence_provenance", "identity_resolution", "temporal_kernel"),
        "projectionDependencies": [],
        "optionalProjectionDependencies": ("risk360",),
        "inputRefs": ("EntityRef", "EvidenceRef", "GraphSnapshotRef", "PageRequest", "TimeRangeFilter"),
        "outputSections": ("agent_delegations", "evidence", "findings", "interactions", "journeys", "sessions", "state", "summary", "timeline"),
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
        "subjectKinds": ("agent", "cluster", "contagion_path", "entity", "population", "relationship", "source"),
        "canonicalAuthorities": ("cluster_membership", "economic_facts", "entity_graph", "evidence", "flow_trace_paths", "flow_traces", "model_governance", "risk_assessments", "risk_outputs", "risk_signals", "source_provenance", "transfers"),
        "hardDependencies": ("computation_substrate", "evidence_provenance", "model_governance"),
        "projectionDependencies": ("cluster360", "economic360", "profile360"),
        "optionalProjectionDependencies": [],
        "inputRefs": ("EntityRef", "EvidenceRef", "FilterExpression", "GraphSnapshotRef", "PageRequest", "RelationshipRef", "TimeRangeFilter"),
        "outputSections": ("evidence", "findings", "health", "state", "summary"),
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
        "canonicalAuthorities": ("behavioral_signals", "identity", "observations", "source_provenance"),
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
        "canonicalAuthorities": ("agent_entities", "cohort_membership", "evidence", "graph", "identity", "influence_propagation", "relationship_facts", "relationship_predicate_registry", "social_observations", "source_facts"),
        "hardDependencies": ("relationship_fidelity", "temporal_kernel", "upr"),
        "projectionDependencies": ("profile360", "relationship360"),
        "optionalProjectionDependencies": [],
        "inputRefs": ("EntityRef", "EvidenceRef", "GraphSnapshotRef", "PageRequest", "RelationshipRef", "TimeRangeFilter"),
        "outputSections": ("evidence", "findings", "interactions", "paths", "propagation", "state", "summary", "timeline"),
        "supportedTemporalModes": ("as_of", "relative", "window"),
        "surfaceIds": ("profile360",),
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
            "surfaceIds": ("profile360",),
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
        "subjectKinds": ("entity", "support_case"),
        "canonicalAuthorities": ("communication_facts", "evidence", "provider_connections", "support_case_events", "support_cases"),
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
        "canonicalAuthorities": ("agent_entities", "ai_execution_facts", "identity"),
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
    "profile360": {"required": (), "optional": ("risk360",)},
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
    "social360": ("profile360",),
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
            "projectionCapabilityKeys": ("economic360.explore", "economic360.read", "profile360.explore", "profile360.read", "relationship360.explore", "relationship360.read"),
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
                "canonicalAuthorityRefs": ("entities", "entity_registry", "graph", "identity", "risk_outputs"),
                "domainSlotIds": ("account_summary", "agents", "members", "profiles", "risk"),
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
                "description": "Account linked communication threads with participant policy.",
                "id": "communications",
                "projectionBindings": [],
                "requirement": "required",
                "unboundReason": "account_communication_subject_binding_not_available"
            },
            {
                "canonicalAuthorityRefs": ("commerce",),
                "description": "Canonical account contract and obligation records.",
                "id": "contracts",
                "projectionBindings": [],
                "requirement": "required",
                "unboundReason": "canonical_account_contract_authority_not_available"
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
                "canonicalAuthorityRefs": ("journeys",),
                "description": "Journeys directly linked to the account by a canonical relationship.",
                "id": "journeys",
                "projectionBindings": [],
                "requirement": "required",
                "unboundReason": "account_journey_membership_authority_not_joined"
            },
            {
                "id": "members",
                "requirement": "required",
                "description": "Known current organization MEMBER_OF edges validated against canonical member entities; roster completeness unknown.",
                "canonicalAuthorityRefs": ("entity_registry", "graph"),
                "projectionBindings": []
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
                "canonicalAuthorityRefs": ("risk_outputs",),
                "description": "Exact resolved account-entity Risk360 outputs backed by canonical evidence; related-account coverage remains partial.",
                "id": "risk",
                "partialImplementationReason": "Direct account-entity risk evidence is available; member and related-entity aggregation and a freshness SLA remain unimplemented.",
                "projectionBindings": [],
                "requirement": "required"
            },
            {
                "id": "value",
                "requirement": "required",
                "description": "Direct entity-scoped economic value for the canonical account profile, without member or execution-cost aggregation.",
                "canonicalAuthorityRefs": ("economic_facts",),
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
            "canonicalAuthorities": ("ai_execution_facts", "commerce", "communication_facts", "economic_facts", "entities", "entity_registry", "evidence", "graph", "identity", "journeys", "relationship_facts", "risk_outputs"),
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
                "description": "Observed runtime capability reach joined to exact active invoke grants for the resolved canonical Agent; action and resource authorization remains unknown.",
                "id": "capabilities",
                "implementationCrosswalk": ("actions_tools_resources",),
                "partialImplementationReason": "current_active_grant_join_is_bounded_to_2000_records_and_does_not_replay_historical_authority",
                "projectionBindings": [
                    {
                        "projectionId": "agent360",
                        "role": "primary",
                        "subjectKinds": ("agent", "entity"),
                        "sectionIds": ("evidence", "state")
                    }
                ],
                "requirement": "required",
                "unboundCanonicalAuthorityRefs": ("actions", "resources", "tools")
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
                "authorityGapReason": "exact_subject_authority_join_not_implemented",
                "canonicalAuthorityRefs": ("evidence", "source_provenance"),
                "description": "Required Agent 360 blueprint slot: evidence trace.",
                "id": "evidence_trace",
                "implementationCrosswalk": ("source_evidence_lineage",),
                "projectionBindings": [
                    {
                        "projectionId": "agent360",
                        "role": "supporting",
                        "subjectKinds": ("agent", "entity"),
                        "sectionIds": ("evidence",)
                    }
                ],
                "requirement": "required",
                "unboundCanonicalAuthorityRefs": ("source_provenance",)
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
                "canonicalAuthorityRefs": ("agent_access", "identity"),
                "description": "Tenant-scoped owner and delegator records with canonical party identity only where resolved; no effective action authorization is inferred.",
                "id": "owner_delegator",
                "implementationCrosswalk": ("authority_and_delegation",),
                "partialImplementationReason": "delegation_reads_are_bounded_and_party_identity_or_current_authority_can_remain_unknown",
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
                "canonicalAuthorityRefs": ("agent_access", "agent_executions", "identity"),
                "description": "Recorded execution-scoped policy decisions; standing agent policy and a new action decision remain unknown.",
                "id": "policy_boundary",
                "implementationCrosswalk": ("authority_and_delegation",),
                "partialImplementationReason": "only_stored_execution_time_decisions_are_available_and_standing_policy_is_not_exposed",
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
                "authorityGapReason": "exact_subject_authority_join_not_implemented",
                "canonicalAuthorityRefs": ("agent_entities", "identity", "relationship_facts", "risk_outputs", "social_observations"),
                "description": "Required Agent 360 blueprint slot: risk summary.",
                "id": "risk_summary",
                "implementationCrosswalk": ("risk_and_contagion",),
                "projectionBindings": [
                    {
                        "projectionId": "risk360",
                        "role": "primary",
                        "subjectKinds": ("agent", "entity"),
                        "sectionIds": ("evidence", "findings")
                    }
                ],
                "requirement": "required",
                "unboundCanonicalAuthorityRefs": ("agent_entities", "identity", "relationship_facts", "social_observations")
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
            "canonicalAuthorities": ("actions", "agent_access", "agent_entities", "agent_entity", "agent_executions", "ai_execution_facts", "commerce", "communication_facts", "economic_facts", "evidence", "execution_facts", "graph", "identity", "observations", "outcome_facts", "payments", "relationship_facts", "resources", "risk_outputs", "social_observations", "source_provenance", "temporal", "tools"),
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
                "authorityGapReason": "General campaign risk outputs are not joined by this targeting leakage finding provider.",
                "canonicalAuthorityRefs": ("risk_outputs", "source_provenance", "targeting_leakage_findings"),
                "description": "Tenant-scoped targeting leakage findings backed by source observation and eligibility-snapshot evidence; broader risk and source anomalies stay unknown.",
                "id": "anomalies",
                "partialImplementationReason": "Exact targeting leakage findings are joined with a bounded evidence chain; general risk outputs and source anomalies remain unknown.",
                "projectionBindings": [
                    {
                        "projectionId": "campaign360",
                        "role": "primary",
                        "subjectKinds": ("campaign",),
                        "sectionIds": ("anomalies",)
                    }
                ],
                "requirement": "required",
                "unboundCanonicalAuthorityRefs": ("risk_outputs",)
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
                "canonicalAuthorityRefs": ("cluster_definitions", "cluster_membership", "cohort_membership", "relationship_facts"),
                "description": "Canonical cohort, cluster, and syndicate memberships associated with the campaign.",
                "id": "cohorts_syndicates",
                "projectionBindings": [],
                "requirement": "required",
                "unboundReason": "No exact campaign-to-cohort or campaign-to-syndicate relationship is currently joined."
            },
            {
                "id": "conversions",
                "requirement": "required",
                "description": "Canonical conversion and measured-outcome records scoped to the campaign.",
                "canonicalAuthorityRefs": ("measurement_contract", "outcome_facts"),
                "projectionBindings": [
                    {
                        "projectionId": "outcome360",
                        "role": "primary",
                        "subjectKinds": ("campaign",),
                        "sectionIds": ("evidence", "outcomes")
                    }
                ]
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
                "id": "performance",
                "requirement": "required",
                "description": "Observed economic and outcome performance facts for the campaign.",
                "canonicalAuthorityRefs": ("commerce", "economic_facts", "outcome_facts", "payments"),
                "projectionBindings": [
                    {
                        "projectionId": "economic360",
                        "role": "primary",
                        "subjectKinds": ("campaign",),
                        "sectionIds": ("evidence", "outcomes", "summary")
                    }
                ]
            },
            {
                "canonicalAuthorityRefs": ("events", "observations", "source_facts"),
                "description": "Tenant-scoped signal and source observations associated with the campaign.",
                "id": "signal_sources",
                "projectionBindings": [],
                "requirement": "required",
                "unboundReason": "No campaign-scoped signal-source authority is connected to this surface."
            },
            {
                "authorityGapReason": "Touchpoint classification revisions do not classify the campaign registry source or every asserting source.",
                "canonicalAuthorityRefs": ("campaign_touchpoints", "source_facts", "source_provenance"),
                "description": "Canonical classification of the source that asserted or synchronized campaign evidence.",
                "id": "source_classification",
                "partialImplementationReason": "Only classified tenant campaign touchpoints on the requested page are joined; campaign registry provenance remains unknown.",
                "projectionBindings": [
                    {
                        "projectionId": "campaign360",
                        "role": "primary",
                        "subjectKinds": ("campaign",),
                        "sectionIds": ("evidence", "state")
                    }
                ],
                "requirement": "required",
                "unboundCanonicalAuthorityRefs": ("source_facts",)
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
            "canonicalAuthorities": ("attribution_credits", "campaign_facts", "campaign_touchpoints", "cluster_definitions", "cluster_membership", "cohort_membership", "commerce", "communication_facts", "economic_facts", "events", "journeys", "measurement_contract", "observations", "outcome_facts", "payments", "relationship_facts", "risk_outputs", "source_facts", "source_provenance", "targeting_leakage_findings", "touchpoints"),
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
                "canonicalAuthorityRefs": ("commerce",),
                "description": "Required commerce360 slot: availability price.",
                "id": "availability_price",
                "projectionBindings": [],
                "requirement": "required",
                "unboundReason": "commerce_availability_price_authority_not_connected"
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
                "canonicalAuthorityRefs": ("commerce",),
                "description": "Required commerce360 slot: cart checkout.",
                "id": "cart_checkout",
                "projectionBindings": [],
                "requirement": "required",
                "unboundReason": "commerce_cart_checkout_authority_not_connected"
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
                "canonicalAuthorityRefs": ("commerce", "payments", "source_provenance"),
                "projectionBindings": [
                    {
                        "projectionId": "commerce360",
                        "role": "primary",
                        "subjectKinds": ("campaign", "entity", "journey"),
                        "sectionIds": ("evidence_trace",)
                    }
                ]
            },
            {
                "canonicalAuthorityRefs": ("commerce",),
                "description": "Required commerce360 slot: exposures.",
                "id": "exposures",
                "projectionBindings": [],
                "requirement": "required",
                "unboundReason": "commerce_exposure_subject_join_not_available"
            },
            {
                "canonicalAuthorityRefs": ("commerce",),
                "description": "Required commerce360 slot: intent.",
                "id": "intent",
                "projectionBindings": [],
                "requirement": "required",
                "unboundReason": "commerce_intent_subject_join_not_available"
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
                "projectionBindings": [],
                "requirement": "required",
                "unboundReason": "commerce_risk_subject_join_not_available"
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
            "canonicalAuthorities": ("campaign_facts", "commerce", "commerce_product_offer_graph", "payments", "risk_outputs", "source_provenance"),
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
                "id": "agent_authorship",
                "requirement": "required",
                "description": "Observed agent author bindings; delegation authority remains unjoined.",
                "canonicalAuthorityRefs": ("communication_facts", "entities"),
                "projectionBindings": [
                    {
                        "projectionId": "communication360",
                        "role": "primary",
                        "subjectKinds": ("agent",),
                        "sectionIds": ("evidence", "interactions")
                    }
                ]
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
                "id": "participants",
                "requirement": "required",
                "description": "Participant binding rows and endpoint metadata; full role resolution is pending.",
                "canonicalAuthorityRefs": ("communication_facts", "entities"),
                "projectionBindings": [
                    {
                        "projectionId": "communication360",
                        "role": "primary",
                        "subjectKinds": ("agent", "campaign"),
                        "sectionIds": ("interactions",)
                    }
                ]
            },
            {
                "canonicalAuthorityRefs": ("communication_facts",),
                "description": "Required communications360 slot: policy state.",
                "id": "policy_state",
                "projectionBindings": [],
                "requirement": "required",
                "unboundReason": "communication_policy_evaluation_authority_not_joined"
            },
            {
                "canonicalAuthorityRefs": ("communication_facts", "identity"),
                "description": "Required communications360 slot: profile links.",
                "id": "profile_links",
                "projectionBindings": [],
                "requirement": "required",
                "unboundReason": "typed_profile_message_link_authority_not_joined"
            },
            {
                "id": "response_events",
                "requirement": "required",
                "description": "Observed response-like communication acts; expectations stay distinct.",
                "canonicalAuthorityRefs": ("communication_facts",),
                "projectionBindings": [
                    {
                        "projectionId": "communication360",
                        "role": "primary",
                        "subjectKinds": ("agent", "campaign"),
                        "sectionIds": ("interactions",)
                    }
                ]
            },
            {
                "authorityGapReason": "message_scoped_composite_risk_output_not_joined",
                "canonicalAuthorityRefs": ("risk_outputs", "risk_signals"),
                "description": "Exact current risk-signal records for direct source or identity-resolved agent communication subjects.",
                "id": "risk_flags",
                "partialImplementationReason": "agent_and_source_current_risk_signals_only",
                "projectionBindings": [
                    {
                        "projectionId": "communication360",
                        "role": "primary",
                        "subjectKinds": ("agent", "source"),
                        "sectionIds": ("evidence", "summary")
                    }
                ],
                "requirement": "required",
                "unboundCanonicalAuthorityRefs": ("risk_outputs",)
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
            "canonicalAuthorities": ("campaign_touchpoints", "communication_facts", "entities", "evidence", "identity", "journeys", "risk_outputs", "risk_signals"),
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
                "canonicalAuthorityRefs": ("agent_executions",),
                "description": "Required episode360 slot: agent handoffs.",
                "id": "agent_handoffs",
                "projectionBindings": [],
                "requirement": "required",
                "unboundReason": "episode_agent_handoff_authority_not_joined"
            },
            {
                "canonicalAuthorityRefs": ("attribution_credits",),
                "description": "Required episode360 slot: attribution links.",
                "id": "attribution_links",
                "projectionBindings": [],
                "requirement": "required",
                "unboundReason": "episode_attribution_credit_authority_not_joined"
            },
            {
                "canonicalAuthorityRefs": ("communication_facts",),
                "description": "Exact tenant episode_id-linked communication facts; message history and complete conversation membership remain unavailable.",
                "id": "communications",
                "partialImplementationReason": "episode_communication_facts_are_exact_but_message_spine_join_and_completeness_are_unavailable",
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
                "canonicalAuthorityRefs": ("outcome_facts",),
                "description": "Required episode360 slot: conversion events.",
                "id": "conversion_events",
                "projectionBindings": [],
                "requirement": "required",
                "unboundReason": "episode_outcome_ids_are_not_conversion_records"
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
                "canonicalAuthorityRefs": ("risk_outputs",),
                "description": "Required episode360 slot: risk flags.",
                "id": "risk_flags",
                "projectionBindings": [],
                "requirement": "required",
                "unboundReason": "episode_risk_authority_not_joined"
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
                "id": "timeline",
                "requirement": "required",
                "description": "Episode observation IDs and bounded temporal context; observation rows remain unjoined.",
                "canonicalAuthorityRefs": ("episode_facts", "temporal"),
                "projectionBindings": [
                    {
                        "projectionId": "episode360",
                        "role": "primary",
                        "subjectKinds": ("episode",),
                        "sectionIds": ("timeline",)
                    }
                ]
            },
            {
                "canonicalAuthorityRefs": ("campaign_touchpoints",),
                "description": "Required episode360 slot: touchpoints.",
                "id": "touchpoints",
                "projectionBindings": [],
                "requirement": "required",
                "unboundReason": "episode_record_has_no_typed_touchpoint_references"
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
            "canonicalAuthorities": ("agent_executions", "attribution_credits", "campaign_facts", "campaign_touchpoints", "communication_facts", "episode_facts", "evidence", "graph", "identity", "outcome_facts", "relationship_facts", "risk_outputs", "temporal"),
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
                "canonicalAuthorityRefs": ("agent_access", "agent_entities", "identity"),
                "description": "Required Execution 360 blueprint slot: approval chain.",
                "id": "approval_chain",
                "implementationCrosswalk": ("actor_and_delegation",),
                "projectionBindings": [],
                "requiredFrameMetadata": ("slotActorAttribution", "slotAuthorityDecision"),
                "requirement": "required",
                "unboundReason": "execution_approval_id_canonical_join_not_available"
            },
            {
                "canonicalAuthorityRefs": ("agent_access", "agent_entities", "identity"),
                "description": "Required Execution 360 blueprint slot: authority check.",
                "id": "authority_check",
                "implementationCrosswalk": ("actor_and_delegation",),
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
                "authorityGapReason": "exact_subject_authority_join_not_implemented",
                "canonicalAuthorityRefs": ("evidence", "source_provenance"),
                "description": "Required Execution 360 blueprint slot: evidence trace.",
                "id": "evidence_trace",
                "implementationCrosswalk": ("evidence_and_lineage",),
                "projectionBindings": [
                    {
                        "projectionId": "execution360",
                        "role": "primary",
                        "subjectKinds": ("agent", "entity", "episode", "execution"),
                        "sectionIds": ("evidence",)
                    }
                ],
                "requirement": "required",
                "unboundCanonicalAuthorityRefs": ("source_provenance",)
            },
            {
                "canonicalAuthorityRefs": ("agent_executions", "execution_facts"),
                "description": "Required Execution 360 blueprint slot: execution summary.",
                "id": "execution_summary",
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
                "authorityGapReason": "exact_subject_authority_join_not_implemented",
                "canonicalAuthorityRefs": ("agent_executions", "ai_execution_facts", "economic_facts", "execution_facts", "outcome_facts"),
                "description": "Required Execution 360 blueprint slot: latency cost.",
                "id": "latency_cost",
                "implementationCrosswalk": ("economic_and_business_outcomes", "execution_identity_and_state"),
                "projectionBindings": [
                    {
                        "projectionId": "execution360",
                        "role": "primary",
                        "subjectKinds": ("agent", "entity", "episode", "execution"),
                        "sectionIds": ("state", "summary")
                    }
                ],
                "requirement": "required",
                "unboundCanonicalAuthorityRefs": ("ai_execution_facts",)
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
                "canonicalAuthorityRefs": ("agent_executions", "execution_facts", "risk_signals"),
                "description": "Recorded Risk360 signals joined to exact tenant-scoped executions admitted by lifecycle; producer coverage and freshness threshold remain unknown.",
                "id": "risk_events",
                "implementationCrosswalk": ("execution_identity_and_state",),
                "partialImplementationReason": "only_existing_execution_subject_risk_signals_joined_to_admitted_lifecycle_executions_producer_coverage_and_freshness_threshold_unknown",
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
            "canonicalAuthorities": ("actions", "agent_access", "agent_entities", "agent_executions", "ai_execution_facts", "economic_facts", "episode_facts", "events", "evidence", "execution_facts", "identity", "outcome_facts", "resources", "risk_signals", "source_provenance", "temporal_kernel", "tools"),
            "ownsCanonicalTruth": False,
            "prohibitedOwnership": ("economic_facts", "execution_facts", "graph", "identity", "observations", "risk_outputs", "source_provenance")
        },
        "subjectKinds": ("agent", "entity", "episode", "execution")
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
                "canonicalAuthorityRefs": ("entities", "entity_registry", "evidence", "identity", "source_provenance"),
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
                "canonicalAuthorityRefs": ("evidence", "identity", "source_provenance"),
                "description": "Required Identity 360 blueprint slot: namespace map.",
                "id": "namespace_map",
                "implementationCrosswalk": ("source_identifier_lineage",),
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
                "canonicalAuthorityRefs": ("evidence", "identity", "source_provenance"),
                "description": "Historical canonical-subject-bound wallet verification proofs; wallet inventory and current control remain unknown.",
                "id": "wallets",
                "implementationCrosswalk": ("source_identifier_lineage",),
                "partialImplementationReason": "Historical ownership verification evidence can be surfaced, but wallet inventory and current control are not established.",
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
            "canonicalAuthorities": ("agent_access", "agent_entities", "agent_entity", "entities", "entity_registry", "evidence", "graph", "identity", "relationship_facts", "source_provenance"),
            "ownsCanonicalTruth": False,
            "prohibitedOwnership": ("economic_facts", "execution_facts", "graph", "identity", "observations", "risk_outputs", "source_provenance")
        },
        "subjectKinds": ("agent", "entity", "source")
    },
    "journey360": {
        "backendCapabilities": {
            "required": ("experience360.evidence.provenance", "experience360.frame.compose", "experience360.freshness.evaluate", "experience360.policy.evaluate", "experience360.tenant_scope.enforce"),
            "projectionCapabilityKeys": ("episode360.explore", "episode360.read", "profile360.explore", "profile360.read"),
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
                "id": "agent_interventions",
                "requirement": "required",
                "description": "Typed JourneyStep agent IDs with step evidence; actor and authority joins pending.",
                "canonicalAuthorityRefs": ("journeys",),
                "projectionBindings": [
                    {
                        "projectionId": "episode360",
                        "role": "primary",
                        "subjectKinds": ("journey",),
                        "sectionIds": ("interactions",)
                    }
                ]
            },
            {
                "canonicalAuthorityRefs": ("attribution_credits",),
                "description": "Required journey360 slot: attribution.",
                "id": "attribution",
                "projectionBindings": [],
                "requirement": "required",
                "unboundReason": "immutable_attribution_credit_authority_not_joined"
            },
            {
                "canonicalAuthorityRefs": ("communication_facts",),
                "description": "Required journey360 slot: communications.",
                "id": "communications",
                "projectionBindings": [],
                "requirement": "required",
                "unboundReason": "journey_communications_authority_not_joined"
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
                "canonicalAuthorityRefs": ("outcome_facts",),
                "description": "Required journey360 slot: dropoffs.",
                "id": "dropoffs",
                "projectionBindings": [],
                "requirement": "required",
                "unboundReason": "journey_dropoff_authority_not_joined"
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
                "description": "Required journey360 slot: episodes.",
                "id": "episodes",
                "projectionBindings": [],
                "requirement": "required",
                "unboundReason": "typed_journey_to_episode_reference_not_available"
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
                "canonicalAuthorityRefs": ("actions",),
                "description": "Required journey360 slot: recommended actions.",
                "id": "recommended_actions",
                "projectionBindings": [],
                "requirement": "required",
                "unboundReason": "governed_journey_recommendation_authority_not_joined"
            },
            {
                "canonicalAuthorityRefs": ("journeys",),
                "description": "Explicit journey-role markers on exact current-version steps; no inferred stage boundaries or taxonomy.",
                "id": "stages",
                "partialImplementationReason": "Only persisted explicit journey-role markers are exposed; stage taxonomy and completeness remain unknown.",
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
            "canonicalAuthorities": ("actions", "attribution_credits", "campaign_touchpoints", "canonical_conversions", "communication_facts", "episode_facts", "events", "evidence", "graph", "identity", "journeys", "outcome_facts"),
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
                "description": "Tenant scoped density aggregation with location privacy.",
                "id": "activity_density",
                "partialImplementationReason": "The exact entity heatmap supplies temporal counts but has no join from a count to a particular location fact or place.",
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
                "projectionBindings": [],
                "requirement": "required",
                "unboundReason": "exact_location_campaign_join_unavailable"
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
                "projectionBindings": [],
                "requirement": "required",
                "unboundReason": "exact_location_journey_join_unavailable"
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
                "description": "Source links recorded on canonical location facts, without claiming transformation-version or normalization-time lineage.",
                "id": "normalization",
                "partialImplementationReason": "Canonical location fact source links are surfaced, but normalization and validation versions, raw record refs, and normalization timestamps are unavailable.",
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
                "projectionBindings": [],
                "requirement": "required",
                "unboundReason": "exact_location_profile_join_and_policy_unavailable"
            },
            {
                "canonicalAuthorityRefs": ("locations", "risk_outputs"),
                "description": "Risk outputs linked to place with evidence.",
                "id": "risk",
                "projectionBindings": [],
                "requirement": "required",
                "unboundReason": "exact_location_risk_join_unavailable"
            },
            {
                "canonicalAuthorityRefs": ("locations", "temporal"),
                "description": "Verified time zone and temporal conversion evidence.",
                "id": "timezone",
                "projectionBindings": [],
                "requirement": "required",
                "unboundReason": "canonical_timezone_authority_not_joined"
            },
            {
                "canonicalAuthorityRefs": ("economic_facts", "locations"),
                "description": "Economic facts linked to place without subject inference.",
                "id": "value",
                "projectionBindings": [],
                "requirement": "required",
                "unboundReason": "exact_location_value_join_unavailable"
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
            "canonicalAuthorities": ("campaign_facts", "cohort_membership", "context_capsules", "economic_facts", "entity_graph", "geo_observations", "gold_temporal_heatmap", "graph", "identity", "journeys", "locations", "population_definitions", "risk_outputs", "temporal"),
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
                "canonicalAuthorityRefs": ("semantic_memory_graph",),
                "description": "Required memory360 slot: cards.",
                "id": "cards",
                "projectionBindings": [],
                "requirement": "required",
                "unboundReason": "canonical_context_card_authority_not_available"
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
                "canonicalAuthorityRefs": ("semantic_memory_graph",),
                "description": "Required memory360 slot: embeddings meta.",
                "id": "embeddings_meta",
                "projectionBindings": [],
                "requirement": "required",
                "unboundReason": "canonical_embedding_metadata_authority_not_available"
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
                "canonicalAuthorityRefs": ("semantic_memory_graph",),
                "description": "Required memory360 slot: policy state.",
                "id": "policy_state",
                "projectionBindings": [],
                "requirement": "required",
                "unboundReason": "semantic_memory_policy_state_authority_not_connected"
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
            "canonicalAuthorities": ("consent_policy_decisions", "evidence", "semantic_memory_graph", "semantic_memory_records", "silver_semantic_observations", "source_provenance"),
            "ownsCanonicalTruth": False,
            "prohibitedOwnership": ("economic_facts", "execution_facts", "graph", "identity", "observations", "risk_outputs", "source_provenance")
        },
        "subjectKinds": ("card", "entity", "memory", "semantic_entity", "topic")
    },
    "profile360": {
        "backendCapabilities": {
            "required": ("experience360.evidence.provenance", "experience360.frame.compose", "experience360.freshness.evaluate", "experience360.policy.evaluate", "experience360.tenant_scope.enforce"),
            "projectionCapabilityKeys": ("economic360.explore", "economic360.read", "outcome360.explore", "outcome360.read", "profile360.explore", "profile360.read", "relationship360.explore", "relationship360.read", "risk360.explore", "risk360.read"),
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
                "canonicalAuthorityRefs": ("model_governance", "outcome_facts"),
                "description": "Evidence backed future states when an approved model supplies them.",
                "id": "likely_next_states",
                "projectionBindings": [],
                "requirement": "required",
                "unboundReason": "profile_prediction_authority_not_available"
            },
            {
                "canonicalAuthorityRefs": ("geo_observations", "temporal"),
                "description": "Time scoped location evidence for the exact profile.",
                "id": "location_temporal",
                "projectionBindings": [],
                "requirement": "required",
                "unboundReason": "profile_location_temporal_join_not_available"
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
                "description": "Relationships around the entity.",
                "canonicalAuthorityRefs": ("relationship_facts",),
                "projectionBindings": [
                    {
                        "projectionId": "relationship360",
                        "role": "primary",
                        "subjectKinds": ("entity",),
                        "sectionIds": ("evidence", "interactions", "timeline")
                    }
                ]
            },
            {
                "canonicalAuthorityRefs": ("graph", "relationship_facts"),
                "description": "Canonical relationship facts for the profile.",
                "id": "relationships",
                "projectionBindings": [],
                "requirement": "required",
                "unboundReason": "profile_relationship_subject_mapping_not_proven"
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
                "canonicalAuthorityRefs": ("identity",),
                "description": "Resolved source identities with session identifiers linked to the exact canonical profile; event timeline and completeness remain unknown.",
                "id": "session_history",
                "partialImplementationReason": "event_session_timeline_and_complete_roster_not_available",
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
                "canonicalAuthorityRefs": ("graph", "relationship_facts"),
                "description": "Typed syndicate or cohort relationships.",
                "id": "syndicates",
                "projectionBindings": [],
                "requirement": "required",
                "unboundReason": "profile_syndicate_membership_authority_not_joined"
            },
            {
                "canonicalAuthorityRefs": ("economic_facts", "outcome_facts"),
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
            "canonicalAuthorities": ("agent_access", "agent_executions", "ai_execution_facts", "communication_facts", "economic_facts", "entity_registry", "evidence", "geo_observations", "graph", "identity", "journeys", "model_governance", "observations", "outcome_facts", "relationship_facts", "risk_outputs", "temporal"),
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
                "canonicalAuthorityRefs": ("observations", "risk_outputs"),
                "description": "Typed anomaly event records.",
                "id": "anomaly_events",
                "projectionBindings": [],
                "requirement": "required",
                "unboundReason": "canonical_anomaly_event_authority_not_connected"
            },
            {
                "canonicalAuthorityRefs": ("evidence", "mutation_history"),
                "description": "Versioned risk assessment and intervention audit lineage.",
                "id": "audit_history",
                "projectionBindings": [],
                "requirement": "required",
                "unboundReason": "risk_audit_history_authority_not_connected"
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
                "canonicalAuthorityRefs": ("flow_trace_paths", "flow_traces", "risk_assessments", "risk_signals", "transfers"),
                "description": "Exact financial transfer path linked to risk evidence for each node; causal contagion, exposure, and loss remain unproven.",
                "id": "financial_contagion",
                "partialImplementationReason": "causal_contagion_exposure_and_loss_model_not_available",
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
                "canonicalAuthorityRefs": ("actions", "risk_outputs"),
                "description": "Recorded risk interventions and results.",
                "id": "interventions",
                "projectionBindings": [],
                "requirement": "required",
                "unboundReason": "risk_intervention_authority_not_connected"
            },
            {
                "canonicalAuthorityRefs": ("risk_outputs", "source_provenance"),
                "description": "Verified data poisoning evidence with source lineage.",
                "id": "poisoning_evidence",
                "projectionBindings": [],
                "requirement": "required",
                "unboundReason": "data_poisoning_evidence_authority_not_connected"
            },
            {
                "canonicalAuthorityRefs": ("model_governance", "risk_outputs"),
                "description": "Evaluated risk policy flags with policy version and evidence.",
                "id": "policy_flags",
                "projectionBindings": [],
                "requirement": "required",
                "unboundReason": "evaluated_policy_flag_authority_not_connected"
            },
            {
                "canonicalAuthorityRefs": ("graph", "relationship_facts"),
                "description": "Causally supported risk propagation paths.",
                "id": "propagation_paths",
                "projectionBindings": [],
                "requirement": "required",
                "unboundReason": "canonical_contagion_path_authority_not_connected"
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
                "canonicalAuthorityRefs": ("risk_outputs", "social_observations"),
                "description": "Social contagion supported by exact propagation evidence.",
                "id": "social_contagion",
                "projectionBindings": [],
                "requirement": "required",
                "unboundReason": "social_contagion_causal_authority_not_connected"
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
            "canonicalAuthorities": ("actions", "ai_execution_facts", "economic_facts", "entity_graph", "evidence", "execution_facts", "flow_trace_paths", "flow_traces", "fraud_synthesis", "graph", "graph_motifs", "model_governance", "mutation_history", "observations", "relationship_facts", "risk_assessments", "risk_outputs", "risk_signals", "social_observations", "source_provenance", "transfers"),
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
                "description": "Required signals360 slot: campaign links.",
                "id": "campaign_links",
                "projectionBindings": [],
                "requirement": "required",
                "unboundReason": "canonical_signal_campaign_join_not_available"
            },
            {
                "canonicalAuthorityRefs": ("events", "observations"),
                "description": "Required signals360 slot: classification.",
                "id": "classification",
                "projectionBindings": [],
                "requirement": "required",
                "unboundReason": "canonical_event_signal_classifier_not_joined"
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
                "description": "Required signals360 slot: normalization.",
                "id": "normalization",
                "projectionBindings": [],
                "requirement": "required",
                "unboundReason": "canonical_observation_normalization_read_not_joined"
            },
            {
                "authorityGapReason": "source_reliability_and_semantic_quality_authorities_not_joined",
                "canonicalAuthorityRefs": ("ingestion_health", "observations", "source_schema"),
                "description": "Exact SDK Bronze gateway acceptance for an event or observation; source reliability and semantic quality remain unknown.",
                "id": "quality",
                "partialImplementationReason": "gateway_acceptance_only_no_reliability_semantic_quality_or_freshness_sla",
                "projectionBindings": [
                    {
                        "projectionId": "signals360",
                        "role": "primary",
                        "subjectKinds": ("event", "observation"),
                        "sectionIds": ("quality",)
                    }
                ],
                "requirement": "required",
                "unboundCanonicalAuthorityRefs": ("ingestion_health", "source_schema")
            },
            {
                "canonicalAuthorityRefs": ("risk_outputs",),
                "description": "Required signals360 slot: risk flags.",
                "id": "risk_flags",
                "projectionBindings": [],
                "requirement": "required",
                "unboundReason": "canonical_signal_risk_join_not_available"
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
                "authorityGapReason": "This read is limited to authenticated Envelope-B metadata on one SDK event and does not join a tenant source registry or inventory.",
                "canonicalAuthorityRefs": ("source_facts", "source_provenance"),
                "description": "Authenticated source metadata for an exact SDK event or observation; fleet inventory remains unknown.",
                "id": "source_inventory",
                "partialImplementationReason": "Only one exact SDK event or observation is described; the provider cannot enumerate sources or establish source reliability.",
                "projectionBindings": [
                    {
                        "projectionId": "signals360",
                        "role": "primary",
                        "subjectKinds": ("event", "observation"),
                        "sectionIds": ("source_inventory",)
                    }
                ],
                "requirement": "required",
                "unboundCanonicalAuthorityRefs": ("source_facts",)
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
            "canonicalAuthorities": ("behavioral_signals", "campaign_facts", "campaign_touchpoints", "events", "identity", "ingestion_health", "observations", "risk_outputs", "source_facts", "source_provenance", "source_schema"),
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
                "canonicalAuthorityRefs": ("relationship_facts", "social_observations"),
                "description": "Evidence backed influence paths and direction.",
                "id": "influence_paths",
                "projectionBindings": [],
                "requirement": "required",
                "unboundReason": "canonical_influence_path_derivation_unavailable"
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
                "canonicalAuthorityRefs": ("graph", "risk_outputs"),
                "description": "Policy governed risk relationship edges.",
                "id": "risk_edges",
                "projectionBindings": [],
                "requirement": "required",
                "unboundReason": "social_risk_edge_derivation_not_connected"
            },
            {
                "canonicalAuthorityRefs": ("risk_outputs", "social_observations"),
                "description": "Causal contagion evidence with source trust and policy.",
                "id": "social_contagion",
                "projectionBindings": [],
                "requirement": "required",
                "unboundReason": "social_contagion_causal_evidence_authority_unavailable"
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
                "canonicalAuthorityRefs": ("cluster_membership", "relationship_facts"),
                "description": "Verified syndicate membership and topology.",
                "id": "syndicates",
                "projectionBindings": [],
                "requirement": "required",
                "unboundReason": "canonical_syndicate_membership_authority_not_joined"
            },
            {
                "canonicalAuthorityRefs": ("relationship_facts",),
                "description": "Policy governed trust relationship edges.",
                "id": "trust_edges",
                "projectionBindings": [],
                "requirement": "required",
                "unboundReason": "social_trust_edge_derivation_not_connected"
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
            "canonicalAuthorities": ("cluster_membership", "cohort_membership", "evidence", "geo_observations", "graph", "identity", "influence_propagation", "locations", "population_definitions", "relationship_facts", "relationship_predicate_registry", "risk_outputs", "social_observations", "source_coverage", "source_facts"),
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
                "canonicalAuthorityRefs": ("agent_entities", "communication_facts"),
                "description": "Validated support agent assignments and handoffs.",
                "id": "agents",
                "projectionBindings": [],
                "requirement": "required",
                "unboundReason": "canonical_support_case_agent_assignment_unavailable"
            },
            {
                "canonicalAuthorityRefs": ("communication_facts",),
                "description": "Canonical callback schedule and execution records.",
                "id": "callbacks",
                "projectionBindings": [],
                "requirement": "required",
                "unboundReason": "canonical_support_callback_authority_unavailable"
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
                "id": "conversation_history",
                "requirement": "required",
                "description": "Tenant scoped support communication metadata; bodies require separate content permission.",
                "canonicalAuthorityRefs": ("communication_facts", "evidence"),
                "projectionBindings": [
                    {
                        "projectionId": "support360",
                        "role": "primary",
                        "subjectKinds": ("entity",),
                        "sectionIds": ("evidence", "state", "timeline")
                    }
                ]
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
                "canonicalAuthorityRefs": ("episode_facts", "journeys"),
                "description": "Exact support case to journey relationships.",
                "id": "journey_links",
                "projectionBindings": [],
                "requirement": "required",
                "unboundReason": "canonical_support_case_journey_join_unavailable"
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
                "canonicalAuthorityRefs": ("communication_facts", "identity"),
                "description": "Case participants with identity and content policy.",
                "id": "participants",
                "projectionBindings": [],
                "requirement": "required",
                "unboundReason": "canonical_support_case_participants_unavailable"
            },
            {
                "canonicalAuthorityRefs": ("outcome_facts",),
                "description": "Recorded support outcome and resolution state.",
                "id": "resolution",
                "projectionBindings": [],
                "requirement": "required",
                "unboundReason": "canonical_support_resolution_authority_unavailable"
            },
            {
                "canonicalAuthorityRefs": ("risk_outputs",),
                "description": "Risk outputs associated with the exact support case.",
                "id": "risk",
                "projectionBindings": [],
                "requirement": "required",
                "unboundReason": "support_risk_subject_join_unavailable"
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
                "canonicalAuthorityRefs": ("measurement_contract",),
                "description": "Support service level contract and timer state.",
                "id": "sla",
                "projectionBindings": [],
                "requirement": "required",
                "unboundReason": "canonical_support_sla_authority_unavailable"
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
            "canonicalAuthorities": ("agent_entities", "agent_entity", "communication_facts", "episode_facts", "events", "evidence", "identity", "journeys", "measurement_contract", "outcome_facts", "provider_connections", "risk_outputs", "source_coverage", "source_provenance", "support_case_events", "support_cases"),
            "ownsCanonicalTruth": False,
            "prohibitedOwnership": ("economic_facts", "execution_facts", "graph", "identity", "observations", "risk_outputs", "source_provenance")
        },
        "subjectKinds": ("agent", "callback", "conversation", "entity", "episode", "source", "support_case", "ticket")
    },
    "value360": {
        "backendCapabilities": {
            "required": ("experience360.evidence.provenance", "experience360.frame.compose", "experience360.freshness.evaluate", "experience360.policy.evaluate", "experience360.tenant_scope.enforce"),
            "projectionCapabilityKeys": ("campaign360.explore", "campaign360.read", "economic360.explore", "economic360.read", "outcome360.explore", "outcome360.read", "temporal360.explore", "temporal360.read"),
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
                "authorityGapReason": "credit_records_are_not_rejoined_to_canonical_campaign_touchpoint_rows",
                "canonicalAuthorityRefs": ("attribution_credits", "attribution_runs", "campaign_touchpoints", "canonical_conversions"),
                "description": "Credited value allocated by canonical attribution authority.",
                "id": "attribution_credits",
                "partialImplementationReason": "credit_records_are_not_rejoined_to_canonical_campaign_touchpoint_rows",
                "projectionBindings": [
                    {
                        "projectionId": "economic360",
                        "role": "primary",
                        "subjectKinds": ("account", "agent", "campaign", "cluster", "conversion", "entity", "episode", "journey", "profile", "source"),
                        "sectionIds": ("evidence",)
                    }
                ],
                "requirement": "required",
                "unboundCanonicalAuthorityRefs": ("campaign_touchpoints",)
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
                "canonicalAuthorityRefs": ("economic_facts", "model_governance"),
                "description": "Confidence of the value/attribution estimate with model lineage.",
                "id": "confidence",
                "projectionBindings": [],
                "requirement": "required",
                "unboundReason": "value_confidence_authority_not_connected"
            },
            {
                "canonicalAuthorityRefs": ("canonical_conversions",),
                "description": "Canonical conversion ledger records linked to an exact subject reference; aggregate attribution and unsupported value or wallet-cluster joins remain unknown.",
                "id": "conversion_inventory",
                "partialImplementationReason": "value_subject_wallet_cluster_and_historical_inventory_joins_not_available",
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
                "canonicalAuthorityRefs": ("canonical_conversions", "commerce", "economic_facts", "payments"),
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
                "canonicalAuthorityRefs": ("economic_facts", "risk_outputs"),
                "description": "Financial risk linked to economic facts by exact subject.",
                "id": "financial_risk",
                "projectionBindings": [],
                "requirement": "required",
                "unboundReason": "financial_risk_value_join_not_connected"
            },
            {
                "canonicalAuthorityRefs": ("economic_facts", "outcome_facts"),
                "description": "Lifetime value over a defined subject and temporal window.",
                "id": "ltv",
                "projectionBindings": [],
                "requirement": "required",
                "unboundReason": "canonical_ltv_measurement_authority_not_available"
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
                "canonicalAuthorityRefs": ("currency_value_normalization", "payments"),
                "description": "Source and currency reconciliation evidence.",
                "id": "reconciliation",
                "projectionBindings": [],
                "requirement": "required",
                "unboundReason": "cross_source_value_reconciliation_not_available"
            },
            {
                "canonicalAuthorityRefs": ("economic_facts", "payments"),
                "description": "Source-recorded settled payment events with an explicit operation join and transaction evidence; no attributed revenue total.",
                "id": "revenue_events",
                "partialImplementationReason": "all_revenue_event_sources_and_attribution_not_joined",
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
                "canonicalAuthorityRefs": ("currency_value_normalization", "economic_facts"),
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
                "canonicalAuthorityRefs": ("commerce", "payments"),
                "description": "Evidence backed Web2 payment and commerce value.",
                "id": "web2_value",
                "projectionBindings": [],
                "requirement": "required",
                "unboundReason": "web2_value_semantic_classification_not_joined"
            },
            {
                "canonicalAuthorityRefs": ("commerce", "currency_value_normalization"),
                "description": "Evidence backed Web3 wallet and on-chain value.",
                "id": "web3_value",
                "projectionBindings": [],
                "requirement": "required",
                "unboundReason": "web3_value_semantic_classification_not_joined"
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
                "projectionId": "temporal360",
                "role": "primary",
                "bindingStatus": "catalog_only",
                "providerImplementationState": "implemented"
            }
        ],
        "sourceOfTruth": {
            "canonicalAuthorities": ("ai_execution_facts", "attribution_credits", "attribution_runs", "campaign_facts", "campaign_touchpoints", "canonical_conversions", "commerce", "currency_value_normalization", "economic_facts", "measurement_contract", "model_governance", "outcome_facts", "payments", "risk_outputs", "temporal_kernel"),
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
                "canonicalAuthorityRefs": ("actions", "resources", "tools"),
                "description": "Required Workflow 360 slot: actions.",
                "id": "actions",
                "projectionBindings": [],
                "requirement": "required",
                "unboundReason": "canonical_workflow_action_authority_not_joined"
            },
            {
                "canonicalAuthorityRefs": ("agent_entities", "ai_execution_facts", "identity"),
                "description": "Agent references on exact workflow-run AI invocations resolved to tenant canonical Agent identity; human and approval actors remain unknown.",
                "id": "actors",
                "partialImplementationReason": "ai_invocation_agent_actors_only_no_human_initiator_approver_or_authority",
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
                "description": "Required Workflow 360 slot: agent steps.",
                "id": "agent_steps",
                "projectionBindings": [],
                "requirement": "required",
                "unboundReason": "canonical_workflow_step_authority_not_joined"
            },
            {
                "canonicalAuthorityRefs": ("agent_access",),
                "description": "Required Workflow 360 slot: approvals.",
                "id": "approvals",
                "projectionBindings": [],
                "requirement": "required",
                "unboundReason": "canonical_workflow_approval_authority_not_available"
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
                "canonicalAuthorityRefs": ("outcome_facts",),
                "description": "Required Workflow 360 slot: outcomes.",
                "id": "outcomes",
                "projectionBindings": [],
                "requirement": "required",
                "unboundReason": "canonical_workflow_business_outcome_join_not_available"
            },
            {
                "canonicalAuthorityRefs": ("risk_outputs",),
                "description": "Required Workflow 360 slot: risk.",
                "id": "risk",
                "projectionBindings": [],
                "requirement": "required",
                "unboundReason": "canonical_workflow_risk_policy_join_not_available"
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
                "canonicalAuthorityRefs": ("events",),
                "description": "Required Workflow 360 slot: triggers.",
                "id": "triggers",
                "projectionBindings": [],
                "requirement": "required",
                "unboundReason": "canonical_workflow_trigger_authority_not_available"
            },
            {
                "canonicalAuthorityRefs": ("execution_facts",),
                "description": "Required Workflow 360 slot: workflow summary.",
                "id": "workflow_summary",
                "projectionBindings": [],
                "requirement": "required",
                "unboundReason": "canonical_workflow_definition_authority_not_available"
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
            "canonicalAuthorities": ("actions", "agent_access", "agent_entities", "agent_executions", "ai_execution_facts", "events", "execution_facts", "identity", "outcome_facts", "resources", "risk_outputs", "tools"),
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
